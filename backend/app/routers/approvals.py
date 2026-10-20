"""
The approvals API (P19: full).

Endpoints the brief names, on real data:
- GET  /approvals?view=pending|mine|history   the queue
- GET  /approvals/{id}                        the detail
- POST /approvals/{id}/approve   (reason required)
- POST /approvals/{id}/reject    (reason REQUIRED -- a rejection without
   a "why" is a metric the acceptance rate cannot trust, the same
   instinct as alert dismissal in P10)

Who decides (locked-in decisions): in managed mode the organization's
security_manager or organization_admin (owner) -- they own the assets;
the platform SOC and the requester can NEVER approve, including when a
platform analyst triggered the action in managed mode (decided: they
may trigger, never approve). In in-house mode: security_manager or
owner. Expiry is enforced at decision time too: a pending approval
whose clock ran out is marked expired (audit row) and cannot be
approved.

The legacy POST /approvals/{id}/decision is GONE this milestone
(decision locked in): the ticket-close flow was migrated to /approve +
/reject in the same change.

Who authorizes execution: the worker job (approval_jobs) enqueued
after the decide-commit; when Redis is unreachable the job is not
dropped -- the endpoint executes inline instead, so approval always
leads to exactly-once execution.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_active_organization
from app.audit import audit_from_scope
from app.database import get_db
from app.models import (
    Approval,
    ApprovalStatus,
    Organization,
    User,
    UserRole,
)
from app.scope import Scope, org_scope
from app.worker.queue import enqueue_work

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def _decide_gate(
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(org_scope)
) -> tuple[Scope, Organization]:
    """Only the organization's security_manager or owner
    (organization_admin) may decide an approval -- in both soc modes
    (locked-in). Platform roles (super_admin, platform_soc_analyst) are
    structurally excluded: they have no user rows in the org."""
    if scope.account_type == "admin":
        if scope.role == "organization_admin":
            org, user = await db.get(Organization, scope.organization_id), None
        else:
            raise _err("approvals_decide_not_allowed", "Only the organization's owner or security manager may decide approvals.", 403)
    elif scope.role == UserRole.security_manager.value:
        org = await db.get(Organization, scope.organization_id)
        user = await db.get(User, scope.user_id)
    else:
        raise _err("approvals_decide_not_allowed", "Only the organization's owner or security manager may decide approvals.", 403)
    if org is None:
        raise _err("organization_not_found", "Organization not found.", 404)
    from app.access import get_effective_access

    if scope.account_type == "user":
        access = await get_effective_access(db, scope.account, org)
        if access["modules"].get("approvals") != "write":
            raise _err("approvals_decide_not_allowed", "Only the organization's owner or security manager may decide approvals.", 403)
    return scope, org


def _row(a: Approval, *, tool: str | None = None) -> dict:
    payload = a.action_payload or {}
    return {
        "id": str(a.id),
        "organization_id": str(a.organization_id),
        "action_type": a.action_type,
        "tool": tool or payload.get("tool"),
        "arguments": payload.get("arguments"),
        "incident_id": str(a.incident_id) if a.incident_id else None,
        "risk_level": a.risk_level.value if hasattr(a.risk_level, "value") else a.risk_level,
        "status": a.status.value if hasattr(a.status, "value") else a.status,
        "requested_by_type": a.requested_by_type.value if hasattr(a.requested_by_type, "value") else a.requested_by_type,
        "requested_by_id": str(a.requested_by_id) if a.requested_by_id else None,
        "requested_reason": a.requested_reason,
        "decision_reason": a.decision_reason,
        "reviewed_by_user_id": str(a.reviewed_by_user_id) if a.reviewed_by_user_id else None,
        "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "executed_at": a.executed_at.isoformat() if a.executed_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("")
async def list_approvals(
    view: Literal["pending", "mine", "history"] = "pending",
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_active_organization),
):
    """The approvals queue. view=pending (default): PENDING rows, live
    state computed (an expired clock shows expired) -- managers only.
    view=mine: rows THIS user requested (any org member who ever
    triggered a response action needs their own status view).
    view=history: decided/expired rows -- managers only."""
    if view != "mine":
        # pending/history are the manager's queue: same gate as deciding.
        scope, _org = await _decide_gate(db=db, scope=scope)
    else:
        org = await db.get(Organization, scope.organization_id)
        if org is None:
            raise _err("organization_not_found", "Organization not found.", 404)
    stmt = select(Approval).where(Approval.organization_id == scope.organization_id)
    if view == "pending":
        stmt = stmt.where(Approval.status == ApprovalStatus.pending)
    elif view == "mine":
        stmt = stmt.where(
            Approval.requested_by_id == scope.user_id,
            Approval.requested_by_type == ("admin" if scope.account_type == "admin" else "user"),
        )
    else:
        stmt = stmt.where(Approval.status != ApprovalStatus.pending)
    rows = (await db.execute(stmt.order_by(Approval.created_at.desc()))).scalars().all()
    now = datetime.now(timezone.utc)
    out = []
    for a in rows:
        row = _row(a)
        if view == "pending" and a.expires_at is not None and a.expires_at <= now:
            row["status"] = "expired"
        out.append(row)
    return {"approvals": out}


@router.get("/{approval_id}")
async def get_approval(
    approval_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_decide_gate),
):
    approval = (
        await db.execute(
            select(Approval).where(
                Approval.id == approval_id, Approval.organization_id == scope.organization_id
            )
        )
    ).scalar_one_or_none()
    if approval is None:
        raise _err("approval_not_found", "Approval not found.", 404)
    row = _row(approval)
    now = datetime.now(timezone.utc)
    if approval.status == ApprovalStatus.pending and approval.expires_at is not None and approval.expires_at <= now:
        row["status"] = "expired"
    return row


class ApprovePayload(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class RejectPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


async def _decide(
    db: AsyncSession,
    scope: Scope,
    approval_id: uuid.UUID,
    *,
    approve: bool,
    reason: str | None,
) -> dict:
    approval = (
        await db.execute(
            select(Approval).where(
                Approval.id == approval_id, Approval.organization_id == scope.organization_id
            )
        )
    ).scalar_one_or_none()
    if approval is None:
        raise _err("approval_not_found", "Approval not found.", 404)

    if approval.requested_by_type == ("admin" if scope.account_type == "admin" else "user") and approval.requested_by_id == scope.user_id:
        raise _err("self_approval_not_allowed", "The requester cannot decide their own approval request.", 403)

    now = datetime.now(timezone.utc)
    if approval.status == ApprovalStatus.pending and approval.expires_at is not None and approval.expires_at <= now:
        approval.status = ApprovalStatus.expired
        await audit_from_scope(
            db, scope, "approval.expired",
            target_type="approval", target_id=approval.id,
            before={"status": "pending"}, after={"status": "expired"},
        )
        await db.commit()
        raise _err("approval_expired", "This approval request expired before a decision.", 409)
    if approval.status != ApprovalStatus.pending:
        raise _err("approval_already_decided", f"This approval is already {approval.status.value}.", 409)

    approval.status = ApprovalStatus.approved if approve else ApprovalStatus.rejected
    approval.reviewed_by_user_id = scope.user_id if scope.account_type == "user" else None
    approval.reviewed_at = now
    approval.decision_reason = reason

    await audit_from_scope(
        db, scope, "approval.decided",
        target_type="approval", target_id=approval.id,
        before={"status": "pending"},
        after={"status": approval.status.value, "action_type": approval.action_type, "reason": reason},
    )

    decided_payload = {
        "action_type": approval.action_type,
        "decision": approval.status.value,
        "related_type": "approval",
        "related_id": approval.id,
    }
    from app.notifications import notify

    await notify(db, "approval.decided", organization_id=approval.organization_id, payload=decided_payload)

    if not approve:
        await db.commit()
        await db.refresh(approval)
        return _row(approval)

    # Approved: hand to the worker for the once-only execution. If the
    # queue is unreachable, execute INLINE -- the job's own row-lock
    # re-check makes either path exactly-once.
    await db.commit()
    job_id = await enqueue_work("execute_approved_action_job", approval_id=str(approval.id))
    if job_id is None:
        from app.ai.policy import execute_approved_action

        await execute_approved_action(db, approval.id, origin="inline_on_enqueue_failure")
    await db.refresh(approval)
    return _row(approval)


@router.post("/{approval_id}/approve")
async def approve_approval(
    approval_id: uuid.UUID,
    payload: ApprovePayload,
    decided: tuple[Scope, Organization] = Depends(_decide_gate),
    decided_db: AsyncSession = Depends(get_db),
):
    scope, _org = decided
    return await _decide(decided_db, scope, approval_id, approve=True, reason=payload.reason)


@router.post("/{approval_id}/reject")
async def reject_approval(
    approval_id: uuid.UUID,
    payload: RejectPayload,
    decided: tuple[Scope, Organization] = Depends(_decide_gate),
    decided_db: AsyncSession = Depends(get_db),
):
    scope, _org = decided
    return await _decide(decided_db, scope, approval_id, approve=False, reason=payload.reason)
