"""
Minimal approvals API (P13 -- the full approvals UI is P19).

Only what the remediation workflow needs to be exercisable end to end:
list an organization's pending approvals and decide them
(approve/reject) by the organization's security_manager or owner. The
critical-ticket close gate (app/routers/tickets.py) reads the APPROVED
row these endpoints produce.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_active_organization, require_module
from app.audit import audit_from_scope
from app.database import get_db
from app.models import (
    Approval,
    ApprovalStatus,
    User,
    UserRole,
)
from app.scope import Scope, org_scope

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


_require_approvals_write = require_module("approvals", write=True)


async def _decide_gate(
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(org_scope)
) -> Scope:
    """Only the organization's security_manager or owner may decide an
    approval (the spec's approver set for critical-ticket closure)."""
    if scope.account_type == "admin":
        if scope.role == "organization_admin":
            return scope
        raise _err("approvals_decide_not_allowed", "Only the organization's owner or security manager may decide approvals.", 403)
    if scope.role == UserRole.security_manager.value:
        return scope
    raise _err("approvals_decide_not_allowed", "Only the organization's owner or security manager may decide approvals.", 403)


def _row(a: Approval) -> dict:
    return {
        "id": str(a.id),
        "organization_id": str(a.organization_id),
        "action_type": a.action_type,
        "action_payload": a.action_payload,
        "risk_level": a.risk_level.value if hasattr(a.risk_level, "value") else a.risk_level,
        "status": a.status.value if hasattr(a.status, "value") else a.status,
        "requested_by_type": a.requested_by_type.value if hasattr(a.requested_by_type, "value") else a.requested_by_type,
        "requested_by_id": str(a.requested_by_id) if a.requested_by_id else None,
        "reviewed_by_user_id": str(a.reviewed_by_user_id) if a.reviewed_by_user_id else None,
        "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("")
async def list_approvals(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_approvals_write),
):
    """The organization's approvals (pending by default). Owner and
    security_manager (the deciders) plus whoever holds approvals-module
    read... they don't by default, so in practice: the deciders."""
    from app.access import get_effective_access
    from app.models import Organization

    organization = await db.get(Organization, scope.organization_id)
    if organization is None:
        raise _err("organization_not_found", "Organization not found.", 404)

    access = await get_effective_access(db, scope.account, organization)
    if access["modules"].get("approvals") is None:
        raise _err("module_not_available", "You do not have access to approvals.", 403)

    stmt = select(Approval).where(Approval.organization_id == scope.organization_id)
    if status:
        try:
            stmt = stmt.where(Approval.status == ApprovalStatus(status))
        except ValueError:
            raise _err("invalid_status", f"Unknown approval status '{status}'.", 400)
    rows = (await db.execute(stmt.order_by(Approval.created_at.desc()))).scalars().all()
    return {"approvals": [_row(a) for a in rows]}


class DecisionPayload(BaseModel):
    decision: str
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("decision")
    @classmethod
    def _decision_shape(cls, value: str) -> str:
        if value not in {"approved", "rejected"}:
            raise ValueError("decision must be approved|rejected")
        return value


@router.post("/{approval_id}/decision")
async def decide_approval(
    approval_id: uuid.UUID,
    payload: DecisionPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_decide_gate),
):
    """Approve or reject a PENDING approval. The reviewer must belong to
    the approval's organization (isolation is structural for users)."""
    approval = (await db.execute(
        select(Approval).where(
            Approval.id == approval_id,
            Approval.organization_id == scope.organization_id,
        )
    )).scalar_one_or_none()
    if approval is None:
        raise _err("approval_not_found", "Approval not found.", 404)
    if approval.status != ApprovalStatus.pending:
        raise _err("approval_already_decided", f"This approval is already {approval.status.value}.", 409)

    reviewer = await db.get(User, scope.user_id) if scope.account_type == "user" else None
    if scope.account_type == "user" and reviewer is None:
        raise _err("approvals_decide_not_allowed", "Only the organization's owner or security manager may decide approvals.", 403)

    approval.status = ApprovalStatus(payload.decision)
    approval.reviewed_by_user_id = scope.user_id if scope.account_type == "user" else None
    approval.reviewed_at = datetime.now(timezone.utc)
    if payload.notes and approval.action_payload is not None:
        approval.action_payload = {**approval.action_payload, "decision_notes": payload.notes}

    await audit_from_scope(
        db, scope, "approval.decision",
        target_type="approval", target_id=approval.id,
        before={"status": "pending"},
        after={"status": payload.decision, "action_type": approval.action_type},
    )
    await db.commit()
    await db.refresh(approval)
    return _row(approval)
