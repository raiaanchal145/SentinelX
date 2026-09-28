"""
Tickets API (P13 remediation workflow, docs/API_CONTRACT.md "Tickets").

The remediation workflow between the SOC and IT:

- The ticket ALWAYS belongs to the organization whose IT will fix it.
  A managed organization's tickets are created/worked by platform SOC
  staff (assigned analysts) but remain visible and workable by that
  organization's own IT developers -- the SOC-side story (internal
  comments) stays hidden from IT.
- IT developers move the ticket OPEN/ASSIGNED -> INVESTIGATING ->
  PENDING (VERIFICATION) and add comments/tasks/evidence; they can
  never close. The SOC verifies and closes or reopens.
- CRITICAL tickets require an APPROVED approval row
  (action_type="ticket_close") from the organization's
  security_manager or owner before the SOC may close them.
- Every change writes ticket_status_history + audit_logs and, when the
  ticket is linked to an incident, one incident_timeline entry.

Roles:
  SOC-side writer  = platform_soc_analyst assigned to the org (managed)
                     | the org's own soc_analyst (in_house) | super_admin
  SOC-side reader  = + the org's owner & security_manager (oversight)
  IT-side worker   = the org's it_developer (own org only; no close,
                     no internal comments, no assignment to others)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_module
from app.audit import audit_from_scope
from app.database import get_db
from app.models import (
    ActorType,
    Admin,
    AdminLevel,
    Approval,
    ApprovalRiskLevel,
    ApprovalStatus,
    AssignmentRule,
    Asset,
    Evidence,
    EvidenceType,
    Incident,
    IncidentStatus,
    IncidentTimeline,
    Organization,
    SocMode,
    SocOrganizationAssignment,
    Task,
    TaskStatus,
    Ticket,
    TicketAssignment,
    TicketComment,
    TicketStatus,
    TicketStatusHistory,
    User,
    UserRole,
    Verification,
    VerificationResult,
)
from app.scope import Scope, org_scope
from app.models import Team
from app.tickets import (
    TICKET_TRANSITIONS,
    compute_priority,
    evaluate_assignment_rules,
    least_loaded_member,
    stamp_sla_deadlines,
)

router = APIRouter(prefix="/api/v1/tickets", tags=["tickets"])

WORKING_STATUSES = [
    TicketStatus.open,
    TicketStatus.triaged,
    TicketStatus.assigned,
    TicketStatus.acknowledged,
    TicketStatus.investigating,
    TicketStatus.remediation,
    TicketStatus.verification,
]

VALID_PRIORITIES = {"P1", "P2", "P3", "P4"}


def _err(
    code: str,
    message: str,
    status_code: int = 400,
    allowed: set[TicketStatus] | None = None,
) -> HTTPException:
    detail: dict = {"code": code, "message": message}
    if allowed is not None:
        detail["allowed_next_states"] = sorted(s.value for s in allowed)
    return HTTPException(status_code=status_code, detail=detail)


def _actor(scope: Scope) -> tuple[ActorType, uuid.UUID | None]:
    return (ActorType.admin if scope.account_type == "admin" else ActorType.user, scope.user_id)


# ---------------------------------------------------------------------------
# Visibility + write access (the incidents matrix, adapted to tickets:
# IT developers gain a WORK window, everyone else mirrors incidents).
# ---------------------------------------------------------------------------


async def _ticket_visibility(
    db: AsyncSession, scope: Scope
) -> tuple[str, list[uuid.UUID] | None]:
    """
    ("soc", ids)       SOC-side access: super_admin (None ids = all),
                       assigned platform SOC analysts (managed orgs),
                       in-house orgs' own soc_analyst users, plus the
                       owner/security_manager (oversight in both modes).
    ("it", [own org])  it_developer: their own organization only.
    ("empty", None)    unassigned platform SOC analyst.
    ("forbidden", None) everyone else.
    """
    if scope.role == AdminLevel.super_admin.value:
        return "soc", None

    if scope.role == AdminLevel.platform_soc_analyst.value:
        rows = (
            await db.execute(
                select(SocOrganizationAssignment.organization_id).where(
                    SocOrganizationAssignment.admin_id == scope.user_id
                )
            )
        ).scalars().all()
        return ("soc", list(rows)) if rows else ("empty", None)

    if scope.organization_id is None:
        return "forbidden", None

    # Organization-scoped accounts (admins = owner, users = the roles).
    if scope.account_type == "admin" or scope.role in (
        UserRole.soc_analyst.value,
        UserRole.security_manager.value,
    ):
        return "soc", [scope.organization_id]
    if scope.role == UserRole.it_developer.value:
        return "it", [scope.organization_id]
    return "forbidden", None


async def _require_ticket_soc_write(
    db: AsyncSession, scope: Scope, organization_id: uuid.UUID
) -> None:
    """Who may WRITE a ticket as the SOC side: super_admin; a platform
    SOC analyst assigned to that organization; an in-house org's own
    soc_analyst. Owner/security_manager are read-only (oversight)."""
    if scope.role == AdminLevel.super_admin.value:
        return
    if scope.role == AdminLevel.platform_soc_analyst.value:
        assigned = (
            await db.execute(
                select(SocOrganizationAssignment.organization_id).where(
                    SocOrganizationAssignment.admin_id == scope.user_id,
                    SocOrganizationAssignment.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        if assigned is None:
            raise _err("ticket_not_found", "Ticket not found.", 404)  # never leak
        return
    if scope.role == UserRole.soc_analyst.value and scope.organization_id == organization_id:
        org = await db.get(Organization, organization_id)
        if org is not None and org.soc_mode == SocMode.in_house:
            return
    raise _err("ticket_write_not_allowed", "You do not have permission to change tickets as the SOC.", 403)


async def _require_it_write(db: AsyncSession, scope: Scope, ticket: Ticket) -> None:
    """IT developers write only their own organization's tickets."""
    if scope.role == UserRole.it_developer.value and scope.organization_id == ticket.organization_id:
        return
    raise _err("ticket_write_not_allowed", "You do not have permission to change this ticket.", 403)


_require_tickets_read = require_module("it_tickets", write=False)


async def _read_gate(
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(org_scope)
) -> Scope:
    """Module read for org accounts; platform roles pass through here
    (they are gated per-row by the visibility check like incidents)."""
    if scope.account_type == "admin" and scope.role != AdminLevel.organization_admin.value:
        return scope
    return await _require_tickets_read(db=db, scope=scope)


async def _visible_ticket(db: AsyncSession, scope: Scope, ticket_id: uuid.UUID) -> Ticket:
    mode, org_ids = await _ticket_visibility(db, scope)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to tickets.", 403)
    if mode == "empty":
        raise _err("ticket_not_found", "Ticket not found.", 404)
    stmt = select(Ticket).where(Ticket.id == ticket_id)
    if mode != "soc" or org_ids is not None:
        stmt = stmt.where(Ticket.organization_id.in_(org_ids or []))
    ticket = (await db.execute(stmt)).scalar_one_or_none()
    if ticket is None:
        raise _err("ticket_not_found", "Ticket not found.", 404)
    return ticket


# ---------------------------------------------------------------------------
# Rows.
# ---------------------------------------------------------------------------


def _sla_state(ticket: Ticket, now: datetime | None = None) -> str:
    if ticket.sla_breached:
        return "breached"
    if ticket.sla_at_risk:
        return "at_risk"
    if ticket.resolve_due_at is None:
        return "none"
    return "on_track"


def _row(ticket: Ticket) -> dict:
    return {
        "id": str(ticket.id),
        "organization_id": str(ticket.organization_id),
        "ticket_number": ticket.ticket_number,
        "incident_id": str(ticket.incident_id) if ticket.incident_id else None,
        "asset_id": str(ticket.asset_id) if ticket.asset_id else None,
        "title": ticket.title,
        "description": ticket.description,
        "category": ticket.category,
        "severity": ticket.severity.value if hasattr(ticket.severity, "value") else ticket.severity,
        "priority": ticket.priority,
        "status": ticket.status.value if hasattr(ticket.status, "value") else ticket.status,
        "assigned_team_id": str(ticket.assigned_team_id) if ticket.assigned_team_id else None,
        "assigned_user_id": str(ticket.assigned_user_id) if ticket.assigned_user_id else None,
        "sla": {
            "state": _sla_state(ticket),
            "ack_due_at": ticket.ack_due_at.isoformat() if ticket.ack_due_at else None,
            "resolve_due_at": ticket.resolve_due_at.isoformat() if ticket.resolve_due_at else None,
            "acknowledged_at": ticket.acknowledged_at.isoformat() if ticket.acknowledged_at else None,
            "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
            "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None,
        },
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
    }


# ---------------------------------------------------------------------------
# History + timeline + audit (every change, one row each).
# ---------------------------------------------------------------------------


async def _append_status_history(
    db: AsyncSession,
    ticket: Ticket,
    *,
    from_status: TicketStatus | None,
    to_status: TicketStatus,
    scope: Scope | None,
    note: str | None = None,
) -> None:
    actor_type, actor_id = _actor(scope) if scope else (ActorType.system, None)
    db.add(
        TicketStatusHistory(
            ticket_id=ticket.id,
            from_status=from_status,
            to_status=to_status,
            changed_by_type=actor_type,
            changed_by_id=actor_id,
            note=note,
        )
    )


async def _append_incident_timeline(
    db: AsyncSession,
    ticket: Ticket,
    *,
    entry_type: str,
    description: str,
    scope: Scope | None,
    metadata: dict | None = None,
) -> None:
    if ticket.incident_id is None:
        return
    actor_type, actor_id = _actor(scope) if scope else (ActorType.system, None)
    db.add(
        IncidentTimeline(
            incident_id=ticket.incident_id,
            entry_type=entry_type,
            description=description,
            actor_type=actor_type,
            actor_id=actor_id,
            entry_metadata=metadata,
        )
    )


async def _audit(
    db: AsyncSession,
    scope: Scope,
    ticket: Ticket,
    *,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
    request=None,
) -> None:
    await audit_from_scope(
        db,
        scope,
        action,
        organization_id=ticket.organization_id,
        target_type="ticket",
        target_id=ticket.id,
        request=request,
        before=before,
        after=after,
    )


# ---------------------------------------------------------------------------
# Creation.
# ---------------------------------------------------------------------------


class CreateTicketPayload(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    description: str | None = None
    category: str | None = Field(default=None, max_length=80)
    severity: str = "medium"
    priority: str | None = None  # SOC manual override; computed when omitted
    incident_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None  # platform roles must name it

    @field_validator("priority")
    @classmethod
    def _priority_shape(cls, value: str | None) -> str | None:
        if value is not None and value.upper() not in VALID_PRIORITIES:
            raise ValueError("priority must be one of P1..P4")
        return value.upper() if value else value


async def _allocate_ticket_number(db: AsyncSession, organization_id: uuid.UUID) -> str:
    """Next TICK-<n> for the organization (count+1, retried by the
    caller's unique constraint if two creations race)."""
    count = (
        await db.execute(
            select(func.count(Ticket.id)).where(Ticket.organization_id == organization_id)
        )
    ).scalar_one()
    return f"TICK-{count + 1}"


@router.post("", status_code=201)
async def create_ticket(
    payload: CreateTicketPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    """Manual creation (from an incident or standalone). The SOC side
    creates; the ticket belongs to the organization whose IT will fix
    it. Priority comes from the documented formula unless the SOC
    overrides it (audited as ticket.priority_override)."""
    try:
        from app.models import EventSeverity

        severity = EventSeverity(payload.severity.lower())
    except ValueError:
        raise _err("invalid_severity", f"Unknown severity '{payload.severity}'.", 400)

    mode, org_ids = await _ticket_visibility(db, scope)
    if mode in ("forbidden", "it"):
        raise _err("soc_not_visible", "You do not have access to tickets.", 403)

    # Whose ticket is this? Org-scoped SOC callers: their own org. Platform
    # roles/super_admin: the payload must name the organization.
    if scope.organization_id is not None:
        organization_id = scope.organization_id
    else:
        if payload.organization_id is None:
            raise _err("organization_id_required", "An organization_id is required to create a ticket.", 400)
        if mode == "soc" and org_ids is not None and payload.organization_id not in org_ids:
            raise _err("organization_not_found", "Organization not found.", 404)
        if await db.get(Organization, payload.organization_id) is None:
            raise _err("organization_not_found", "Organization not found.", 404)
        organization_id = payload.organization_id

    await _require_ticket_soc_write(db, scope, organization_id)

    incident: Incident | None = None
    if payload.incident_id is not None:
        incident = (
            await db.execute(
                select(Incident).where(
                    Incident.id == payload.incident_id,
                    Incident.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        if incident is None:
            raise _err("incident_not_found", "Incident not found.", 404)

    asset: Asset | None = None
    if payload.asset_id is not None:
        asset = (
            await db.execute(
                select(Asset).where(Asset.id == payload.asset_id, Asset.organization_id == organization_id)
            )
        ).scalar_one_or_none()
        if asset is None:
            raise _err("asset_not_found", "Asset not found.", 404)
    elif incident is not None and incident.primary_asset_id is not None:
        asset = await db.get(Asset, incident.primary_asset_id)

    confidence = incident.confidence if incident is not None else None
    if payload.priority:
        priority = payload.priority
    else:
        priority = compute_priority(
            severity,
            asset.criticality if asset else None,
            confidence,
        )

    ticket = Ticket(
        organization_id=organization_id,
        ticket_number=await _allocate_ticket_number(db, organization_id),
        incident_id=incident.id if incident else None,
        asset_id=asset.id if asset else None,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        severity=severity,
        priority=priority,
        status=TicketStatus.open,
    )
    db.add(ticket)
    await db.flush()

    await stamp_sla_deadlines(db, ticket)

    await _append_status_history(
        db, ticket, from_status=None, to_status=TicketStatus.open, scope=scope
    )
    await _append_incident_timeline(
        db,
        ticket,
        entry_type="ticket_created",
        description=f"Remediation ticket {ticket.ticket_number} created (priority {priority}).",
        scope=scope,
        metadata={"ticket_id": str(ticket.id), "ticket_number": ticket.ticket_number},
    )
    await _audit(db, scope, ticket, action="ticket.create", after={"status": "OPEN", "priority": priority})
    await db.commit()
    await db.refresh(ticket)
    return _row(ticket)


# ---------------------------------------------------------------------------
# The queue + detail.
# ---------------------------------------------------------------------------


@router.get("")
async def list_tickets(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
    status: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    team_id: uuid.UUID | None = None,
    incident_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    sla_state: str | None = None,
    organization_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """The ticket queue. `assignee=me` for the caller's own tickets;
    `organization_id` narrows platform roles (an invisible id is 404)."""
    mode, org_ids = await _ticket_visibility(db, scope)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to tickets.", 403)

    if organization_id is not None:
        if mode == "empty":
            raise _err("organization_not_found", "Organization not found.", 404)
        if mode == "soc" and org_ids is not None and organization_id not in org_ids:
            raise _err("organization_not_found", "Organization not found.", 404)
        if await db.get(Organization, organization_id) is None:
            raise _err("organization_not_found", "Organization not found.", 404)
    elif mode == "soc" and org_ids is None:
        pass  # super_admin sees everything
    elif mode == "empty":
        return {"tickets": [], "total": 0}

    stmt = select(Ticket)
    if mode != "soc" or org_ids is not None:
        stmt = stmt.where(Ticket.organization_id.in_(org_ids or []))
    if organization_id is not None:
        stmt = stmt.where(Ticket.organization_id == organization_id)
    if status:
        try:
            stmt = stmt.where(Ticket.status == TicketStatus[status.lower()])
        except KeyError:
            raise _err("invalid_status", f"Unknown ticket status '{status}'.", 400)
    if priority:
        if priority.upper() not in VALID_PRIORITIES:
            raise _err("invalid_priority", f"Unknown priority '{priority}'.", 400)
        stmt = stmt.where(Ticket.priority == priority.upper())
    if team_id:
        stmt = stmt.where(Ticket.assigned_team_id == team_id)
    if incident_id:
        stmt = stmt.where(Ticket.incident_id == incident_id)
    if asset_id:
        stmt = stmt.where(Ticket.asset_id == asset_id)
    if assignee:
        if scope.account_type == "admin" or scope.organization_id is None:
            pass  # platform accounts have no "me"
        elif assignee == "me":
            stmt = stmt.where(Ticket.assigned_user_id == scope.user_id)
        else:
            try:
                stmt = stmt.where(Ticket.assigned_user_id == uuid.UUID(assignee))
            except ValueError:
                raise _err("invalid_assignee", "Invalid assignee id.", 400)

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(stmt.order_by(Ticket.created_at.desc()).limit(limit))
    ).scalars().all()

    tickets = [_row(t) for t in rows]
    if sla_state:
        tickets = [t for t in tickets if t["sla"]["state"] == sla_state]
        total = len(tickets)
    return {"tickets": tickets, "total": total}


@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    """Detail: the ticket plus assignments, comments, tasks, evidence,
    status history, and the verifications. IT developers see shared
    comments only -- internal notes never leave the API for them."""
    ticket = await _visible_ticket(db, scope, ticket_id)
    mode, _ = await _ticket_visibility(db, scope)
    it_view = mode == "it"

    comments = (
        await db.execute(
            select(TicketComment)
            .where(TicketComment.ticket_id == ticket.id)
            .order_by(TicketComment.created_at)
        )
    ).scalars().all()
    if it_view:
        comments = [c for c in comments if not c.is_internal]

    tasks = (
        await db.execute(
            select(Task).where(Task.ticket_id == ticket.id).order_by(Task.created_at)
        )
    ).scalars().all()
    evidence = (
        await db.execute(
            select(Evidence).where(Evidence.ticket_id == ticket.id).order_by(Evidence.created_at)
        )
    ).scalars().all()
    history = (
        await db.execute(
            select(TicketStatusHistory)
            .where(TicketStatusHistory.ticket_id == ticket.id)
            .order_by(TicketStatusHistory.changed_at)
        )
    ).scalars().all()
    assignments = (
        await db.execute(
            select(TicketAssignment)
            .where(TicketAssignment.ticket_id == ticket.id)
            .order_by(TicketAssignment.created_at)
        )
    ).scalars().all()
    verifications = (
        await db.execute(
            select(Verification)
            .where(Verification.ticket_id == ticket.id)
            .order_by(Verification.created_at)
        )
    ).scalars().all()
    approvals = (
        await db.execute(
            select(Approval).where(
                Approval.action_type == "ticket_close",
                Approval.action_payload["ticket_id"].as_string() == str(ticket.id),
            )
        )
    ).scalars().all()

    incident = None
    if ticket.incident_id:
        row = await db.get(Incident, ticket.incident_id)
        if row is not None:
            incident = {"id": str(row.id), "title": row.title, "status": row.status.value}

    return {
        "ticket": _row(ticket),
        "incident": incident,
        "comments": [
            {
                "id": str(c.id),
                "body": c.body,
                "is_internal": c.is_internal,
                "author_type": c.author_type.value if hasattr(c.author_type, "value") else c.author_type,
                "author_id": str(c.author_id) if c.author_id else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in comments
        ],
        "tasks": [
            {
                "id": str(t.id),
                "title": t.title,
                "description": t.description,
                "status": t.status.value if hasattr(t.status, "value") else t.status,
                "assignee_user_id": str(t.assignee_user_id) if t.assignee_user_id else None,
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in tasks
        ],
        "evidence": [
            {
                "id": str(e.id),
                "evidence_type": e.evidence_type.value if hasattr(e.evidence_type, "value") else e.evidence_type,
                "title": e.title,
                "storage_ref": e.storage_ref,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in evidence
        ],
        "status_history": [
            {
                "from_status": h.from_status.value if h.from_status else None,
                "to_status": h.to_status.value if hasattr(h.to_status, "value") else h.to_status,
                "changed_by_type": h.changed_by_type.value if hasattr(h.changed_by_type, "value") else h.changed_by_type,
                "changed_by_id": str(h.changed_by_id) if h.changed_by_id else None,
                "note": h.note,
                "changed_at": h.changed_at.isoformat() if h.changed_at else None,
            }
            for h in history
        ],
        "assignments": [
            {
                "assigned_team_id": str(a.assigned_team_id) if a.assigned_team_id else None,
                "assigned_user_id": str(a.assigned_user_id) if a.assigned_user_id else None,
                "assigned_by_type": a.assigned_by_type.value if hasattr(a.assigned_by_type, "value") else a.assigned_by_type,
                "reason": a.reason,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in assignments
        ],
        "verifications": [
            {
                "result": v.result.value if hasattr(v.result, "value") else v.result,
                "notes": v.notes,
                "verified_by_type": v.verified_by_type.value if hasattr(v.verified_by_type, "value") else v.verified_by_type,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in verifications
        ],
        "close_approvals": [
            {
                "id": str(a.id),
                "status": a.status.value if hasattr(a.status, "value") else a.status,
                "requested_by_id": str(a.requested_by_id) if a.requested_by_id else None,
                "reviewed_by_user_id": str(a.reviewed_by_user_id) if a.reviewed_by_user_id else None,
            }
            for a in approvals
        ],
    }


# ---------------------------------------------------------------------------
# PATCH (title/description/category/severity/priority override).
# ---------------------------------------------------------------------------


class PatchTicketPayload(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=250)
    description: str | None = None
    category: str | None = Field(default=None, max_length=80)
    severity: str | None = None
    priority: str | None = None  # manual override by the SOC (audited)

    @field_validator("priority")
    @classmethod
    def _priority_shape(cls, value: str | None) -> str | None:
        if value is not None and value.upper() not in VALID_PRIORITIES:
            raise ValueError("priority must be one of P1..P4")
        return value.upper() if value else value


@router.patch("/{ticket_id}")
async def patch_ticket(
    ticket_id: uuid.UUID,
    payload: PatchTicketPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    ticket = await _visible_ticket(db, scope, ticket_id)
    it_caller = scope.role == UserRole.it_developer.value

    if it_caller:
        await _require_it_write(db, scope, ticket)
        if payload.priority is not None or payload.severity is not None:
            raise _err(
                "priority_override_not_allowed",
                "Only the SOC may override priority or severity.",
                403,
            )
    else:
        await _require_ticket_soc_write(db, scope, ticket.organization_id)

    changes: dict = {}
    before: dict = {}
    if payload.title is not None and payload.title != ticket.title:
        before["title"] = ticket.title
        ticket.title = payload.title
        changes["title"] = payload.title
    if payload.description is not None and payload.description != ticket.description:
        before["description"] = ticket.description
        ticket.description = payload.description
        changes["description"] = payload.description
    if payload.category is not None and payload.category != ticket.category:
        before["category"] = ticket.category
        ticket.category = payload.category
        changes["category"] = payload.category
    if payload.severity is not None:
        from app.models import EventSeverity

        try:
            severity = EventSeverity(payload.severity.lower())
        except ValueError:
            raise _err("invalid_severity", f"Unknown severity '{payload.severity}'.", 400)
        if severity != ticket.severity:
            before["severity"] = ticket.severity.value
            ticket.severity = severity
            changes["severity"] = severity.value
    if payload.priority is not None and payload.priority != ticket.priority:
        before["priority"] = ticket.priority
        ticket.priority = payload.priority
        changes["priority"] = payload.priority
        await _audit(
            db, scope, ticket,
            action="ticket.priority_override",
            before={"priority": before.get("priority")},
            after={"priority": payload.priority},
        )
        await _append_incident_timeline(
            db, ticket,
            entry_type="ticket_updated",
            description=f"Ticket {ticket.ticket_number} priority manually overridden to {payload.priority}.",
            scope=scope,
        )

    if not changes:
        return _row(ticket)

    await _audit(db, scope, ticket, action="ticket.update", before=before, after=changes)
    await db.commit()
    await db.refresh(ticket)
    return _row(ticket)


# ---------------------------------------------------------------------------
# Transition (the ONE state-change door; role rules enforced here).
# ---------------------------------------------------------------------------


class TransitionPayload(BaseModel):
    status: str
    note: str | None = None


IT_ALLOWED_TARGETS = {
    TicketStatus.acknowledged,
    TicketStatus.investigating,
    TicketStatus.remediation,
    TicketStatus.triaged,
    TicketStatus.assigned,
    # The IT hand-off: "work done, please verify".
    TicketStatus.verification,
}


async def _resolve_close_approval(
    db: AsyncSession, ticket: Ticket
) -> Approval | None:
    if ticket.priority != "P1":
        return None
    approvals = (
        await db.execute(
            select(Approval).where(
                Approval.action_type == "ticket_close",
                Approval.action_payload["ticket_id"].as_string() == str(ticket.id),
                Approval.status == ApprovalStatus.approved,
            )
        )
    ).scalars().all()
    return approvals[0] if approvals else None


@router.post("/{ticket_id}/transition")
async def transition_ticket(
    ticket_id: uuid.UUID,
    payload: TransitionPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    """The one state-change door (table in app/tickets.py, tested per
    role). IT developers may move the ticket through its working states
    but NEVER to VERIFICATION's successors (resolved/closed/reopen) --
    the SOC verifies and closes or reopens. CRITICAL (P1) tickets
    additionally require an approved ticket_close approval before
    CLOSED."""
    ticket = await _visible_ticket(db, scope, ticket_id)

    try:
        target = TicketStatus[payload.status.lower()]
    except KeyError:
        raise _err("invalid_status", f"Unknown ticket status '{payload.status}'.", 400)

    from_status = ticket.status

    # --- role wall BEFORE the map: an IT developer's attempt to close is
    # a permission failure (403 it_cannot_close), not a workflow mistake
    # (409) -- the role rule is the point being enforced.
    it_caller = scope.role == UserRole.it_developer.value
    if it_caller:
        await _require_it_write(db, scope, ticket)
        # IT's hard wall: working states only. VERIFICATION itself is the
        # hand-off ("work done, please verify"); everything out of
        # VERIFICATION (resolve/close/reopen) is the SOC's alone.
        if target in {TicketStatus.resolved, TicketStatus.closed} or (
            from_status == TicketStatus.verification
        ):
            raise _err(
                "it_cannot_close",
                "IT developers cannot verify or close tickets -- the SOC does that.",
                403,
            )

    allowed = TICKET_TRANSITIONS.get(from_status, set())
    if target not in allowed:
        raise _err(
            "invalid_ticket_transition",
            f"Cannot move a ticket from '{from_status.value}' to '{target.value}'.",
            409,
            allowed,
        )

    if it_caller:
        if target not in IT_ALLOWED_TARGETS:
            raise _err("ticket_write_not_allowed", "You do not have permission for this transition.", 403)
    else:
        await _require_ticket_soc_write(db, scope, ticket.organization_id)

    # --- the critical-close gate ---------------------------------------
    # P1 only: a lower-priority ticket closes freely; a CRITICAL one needs
    # an APPROVED ticket_close approval from the org's security_manager or
    # owner (created via the approvals router, decided by the deciders).
    if target == TicketStatus.closed and ticket.priority == "P1":
        approval = await _resolve_close_approval(db, ticket)
        if approval is None:
            raise _err(
                "close_approval_required",
                "A CRITICAL ticket needs an approved close approval from the organization's security manager or owner.",
                403,
            )

    ticket.status = target
    now = datetime.now(timezone.utc)
    if target == TicketStatus.acknowledged and ticket.acknowledged_at is None:
        ticket.acknowledged_at = now
    if target == TicketStatus.resolved:
        ticket.resolved_at = now
    if target == TicketStatus.closed:
        ticket.closed_at = now
    if target == TicketStatus.open and from_status in (TicketStatus.resolved, TicketStatus.closed):
        # Reopening clears the closure stamps.
        ticket.resolved_at = None
        ticket.closed_at = None

    await _append_status_history(
        db, ticket, from_status=from_status, to_status=target, scope=scope, note=payload.note
    )
    await _append_incident_timeline(
        db, ticket,
        entry_type="ticket_status",
        description=f"Ticket {ticket.ticket_number}: {from_status.value} -> {target.value}.",
        scope=scope,
        metadata={"ticket_id": str(ticket.id), "status_from": from_status.value, "status_to": target.value},
    )
    await _audit(
        db, scope, ticket,
        action="ticket.transition",
        before={"status": from_status.value},
        after={"status": target.value, **({"note": payload.note} if payload.note else {})},
    )
    await db.commit()
    await db.refresh(ticket)
    return _row(ticket)


# ---------------------------------------------------------------------------
# Assign (manual reassign; rules run via /auto-assign).
# ---------------------------------------------------------------------------


class AssignPayload(BaseModel):
    team_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    reason: str | None = None


async def _validate_assign_target(
    db: AsyncSession, ticket: Ticket, team_id: uuid.UUID | None, user_id: uuid.UUID | None
) -> None:
    """Assignment targets live in the ticket's organization: teams by FK
    scope, users by organization_id -- IT developers can only ever be
    assigned within their own organization."""
    if team_id is not None:
        team = (
            await db.execute(
                select(Team).where(Team.id == team_id, Team.organization_id == ticket.organization_id)
            )
        ).scalar_one_or_none()
        if team is None:
            raise _err("team_not_found", "Team not found in this organization.", 404)
    if user_id is not None:
        user = (
            await db.execute(
                select(User).where(
                    User.id == user_id,
                    User.organization_id == ticket.organization_id,
                    User.role == UserRole.it_developer,
                )
            )
        ).scalar_one_or_none()
        if user is None:
            raise _err(
                "assignee_not_in_scope",
                "Tickets can only be assigned to it_developer users of the ticket's organization.",
                422,
            )


@router.post("/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: uuid.UUID,
    payload: AssignPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    """Manual assignment/reassignment. Writes one ticket_assignments row
    per hand-off and moves an OPEN ticket to ASSIGNED (a valid
    transition; anything else keeps its status)."""
    ticket = await _visible_ticket(db, scope, ticket_id)
    it_caller = scope.role == UserRole.it_developer.value
    if it_caller:
        raise _err("ticket_write_not_allowed", "IT developers cannot reassign tickets.", 403)
    await _require_ticket_soc_write(db, scope, ticket.organization_id)

    if payload.team_id is None and payload.user_id is None:
        raise _err("assign_target_required", "Name a team_id and/or user_id.", 400)
    await _validate_assign_target(db, ticket, payload.team_id, payload.user_id)

    # A named user must belong to the named team when both are given.
    if payload.team_id and payload.user_id:
        user = await db.get(User, payload.user_id)
        if user is not None and user.team_id != payload.team_id:
            raise _err("assignee_not_in_scope", "That user is not on the named team.", 422)

    from_status = ticket.status
    ticket.assigned_team_id = payload.team_id
    ticket.assigned_user_id = payload.user_id
    db.add(
        TicketAssignment(
            ticket_id=ticket.id,
            assigned_team_id=payload.team_id,
            assigned_user_id=payload.user_id,
            assigned_by_type=ActorType.admin if scope.account_type == "admin" else ActorType.user,
            assigned_by_id=scope.user_id,
            reason=payload.reason,
        )
    )
    if from_status == TicketStatus.open:
        ticket.status = TicketStatus.assigned
        await _append_status_history(
            db, ticket, from_status=from_status, to_status=TicketStatus.assigned, scope=scope,
            note=payload.reason,
        )
        await _append_incident_timeline(
            db, ticket,
            entry_type="ticket_status",
            description=f"Ticket {ticket.ticket_number} assigned.",
            scope=scope,
        )
        await _audit(db, scope, ticket, action="ticket.transition",
                     before={"status": from_status.value}, after={"status": "ASSIGNED"})
    await _audit(db, scope, ticket, action="ticket.assign",
                 after={
                     "team_id": str(payload.team_id) if payload.team_id else None,
                     "user_id": str(payload.user_id) if payload.user_id else None,
                     "reason": payload.reason,
                 })
    await db.commit()
    await db.refresh(ticket)
    return _row(ticket)


@router.post("/{ticket_id}/auto-assign")
async def auto_assign_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    """Run the org's assignment rules (in priority_order) to pick a team,
    then the team's least-loaded it_developer. 409 when nothing matches."""
    ticket = await _visible_ticket(db, scope, ticket_id)
    if scope.role == UserRole.it_developer.value:
        raise _err("ticket_write_not_allowed", "IT developers cannot reassign tickets.", 403)
    await _require_ticket_soc_write(db, scope, ticket.organization_id)

    team_id, rule_name = await evaluate_assignment_rules(db, ticket)
    if team_id is None:
        raise _err("no_assignment_rule_matched", "No enabled assignment rule matched this ticket.", 409)

    user = await least_loaded_member(db, ticket.organization_id, team_id)
    from_status = ticket.status
    ticket.assigned_team_id = team_id
    ticket.assigned_user_id = user.id if user else None
    db.add(
        TicketAssignment(
            ticket_id=ticket.id,
            assigned_team_id=team_id,
            assigned_user_id=user.id if user else None,
            assigned_by_type=ActorType.admin if scope.account_type == "admin" else ActorType.user,
            assigned_by_id=scope.user_id,
            reason=f"Rule: {rule_name}" if rule_name else None,
        )
    )
    if from_status == TicketStatus.open:
        ticket.status = TicketStatus.assigned
        await _append_status_history(
            db, ticket, from_status=from_status, to_status=TicketStatus.assigned, scope=scope,
            note=f"Rule: {rule_name}",
        )
    await _audit(db, scope, ticket, action="ticket.auto_assign",
                 after={"team_id": str(team_id), "rule": rule_name,
                        "user_id": str(user.id) if user else None})
    await db.commit()
    await db.refresh(ticket)
    return _row(ticket)


# ---------------------------------------------------------------------------
# Comments (internal vs shared; internal never reaches IT).
# ---------------------------------------------------------------------------


class CommentPayload(BaseModel):
    body: str = Field(min_length=1)
    is_internal: bool = True


@router.post("/{ticket_id}/comments", status_code=201)
async def add_comment(
    ticket_id: uuid.UUID,
    payload: CommentPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    ticket = await _visible_ticket(db, scope, ticket_id)
    actor_type, actor_id = _actor(scope)

    if scope.role == UserRole.it_developer.value:
        await _require_it_write(db, scope, ticket)
        if payload.is_internal:
            raise _err(
                "internal_comment_not_allowed",
                "IT developers write shared comments only.",
                403,
            )

    comment = TicketComment(
        ticket_id=ticket.id,
        author_type=actor_type,
        author_id=actor_id,
        body=payload.body,
        is_internal=payload.is_internal,
    )
    db.add(comment)
    # Comments surface on the linked incident's timeline too (internal
    # ones stay SOC-only there as well).
    await _append_incident_timeline(
        db, ticket,
        entry_type="comment",
        description=payload.body,
        scope=scope,
        metadata={"ticket_id": str(ticket.id), "visibility": "internal" if payload.is_internal else "shared"},
    )
    await _audit(db, scope, ticket, action="ticket.comment",
                 after={"is_internal": payload.is_internal, "length": len(payload.body)})
    await db.commit()
    return {
        "id": str(comment.id),
        "ticket_id": str(ticket.id),
        "body": comment.body,
        "is_internal": comment.is_internal,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }


# ---------------------------------------------------------------------------
# Tasks (CRUD under a ticket).
# ---------------------------------------------------------------------------


class TaskPayload(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    description: str | None = None
    assignee_user_id: uuid.UUID | None = None
    due_at: datetime | None = None
    status: str | None = None

    @field_validator("status")
    @classmethod
    def _status_shape(cls, value: str | None) -> str | None:
        if value is not None and value not in {"open", "in_progress", "completed", "blocked"}:
            raise ValueError("status must be open|in_progress|completed|blocked")
        return value


class TaskPatchPayload(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=250)
    description: str | None = None
    assignee_user_id: uuid.UUID | None = None
    due_at: datetime | None = None
    status: str | None = None

    @field_validator("status")
    @classmethod
    def _status_shape(cls, value: str | None) -> str | None:
        if value is not None and value not in {"open", "in_progress", "completed", "blocked"}:
            raise ValueError("status must be open|in_progress|completed|blocked")
        return value


async def _validate_task_assignee(
    db: AsyncSession, ticket: Ticket, user_id: uuid.UUID | None
) -> None:
    if user_id is None:
        return
    user = (
        await db.execute(
            select(User).where(
                User.id == user_id,
                User.organization_id == ticket.organization_id,
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise _err("assignee_not_in_scope", "Task assignees must belong to the ticket's organization.", 422)


@router.post("/{ticket_id}/tasks", status_code=201)
async def create_task(
    ticket_id: uuid.UUID,
    payload: TaskPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    ticket = await _visible_ticket(db, scope, ticket_id)
    if scope.role == UserRole.it_developer.value:
        await _require_it_write(db, scope, ticket)
    else:
        await _require_ticket_soc_write(db, scope, ticket.organization_id)
    await _validate_task_assignee(db, ticket, payload.assignee_user_id)

    task = Task(
        ticket_id=ticket.id,
        title=payload.title,
        description=payload.description,
        status=TaskStatus(payload.status) if payload.status else TaskStatus.open,
        assignee_user_id=payload.assignee_user_id,
        due_at=payload.due_at,
    )
    db.add(task)
    await _audit(db, scope, ticket, action="ticket.task_create", after={"title": task.title})
    await db.commit()
    await db.refresh(task)
    return {
        "id": str(task.id),
        "ticket_id": str(ticket.id),
        "title": task.title,
        "status": task.status.value,
        "assignee_user_id": str(task.assignee_user_id) if task.assignee_user_id else None,
        "due_at": task.due_at.isoformat() if task.due_at else None,
    }


@router.patch("/{ticket_id}/tasks/{task_id}")
async def patch_task(
    ticket_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskPatchPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    ticket = await _visible_ticket(db, scope, ticket_id)
    if scope.role == UserRole.it_developer.value:
        await _require_it_write(db, scope, ticket)
    else:
        await _require_ticket_soc_write(db, scope, ticket.organization_id)

    task = (
        await db.execute(
            select(Task).where(Task.id == task_id, Task.ticket_id == ticket.id)
        )
    ).scalar_one_or_none()
    if task is None:
        raise _err("task_not_found", "Task not found.", 404)

    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.assignee_user_id is not None:
        await _validate_task_assignee(db, ticket, payload.assignee_user_id)
        task.assignee_user_id = payload.assignee_user_id
    if payload.due_at is not None:
        task.due_at = payload.due_at
    if payload.status is not None:
        task.status = TaskStatus(payload.status)
        task.completed_at = datetime.now(timezone.utc) if task.status == TaskStatus.completed else None

    await _audit(db, scope, ticket, action="ticket.task_update",
                 after={"title": task.title, "status": task.status.value})
    await db.commit()
    await db.refresh(task)
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status.value,
        "assignee_user_id": str(task.assignee_user_id) if task.assignee_user_id else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.delete("/{ticket_id}/tasks/{task_id}", status_code=204)
async def delete_task(
    ticket_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    ticket = await _visible_ticket(db, scope, ticket_id)
    if scope.role == UserRole.it_developer.value:
        await _require_it_write(db, scope, ticket)
    else:
        await _require_ticket_soc_write(db, scope, ticket.organization_id)
    task = (
        await db.execute(
            select(Task).where(Task.id == task_id, Task.ticket_id == ticket.id)
        )
    ).scalar_one_or_none()
    if task is None:
        raise _err("task_not_found", "Task not found.", 404)
    await db.delete(task)
    await _audit(db, scope, ticket, action="ticket.task_delete", before={"title": task.title})
    await db.commit()


# ---------------------------------------------------------------------------
# Evidence links.
# ---------------------------------------------------------------------------


class EvidencePayload(BaseModel):
    evidence_type: str = "note"
    title: str = Field(min_length=1, max_length=250)
    description: str | None = None
    storage_ref: str | None = Field(default=None, max_length=500)

    @field_validator("evidence_type")
    @classmethod
    def _type_shape(cls, value: str) -> str:
        if value not in {"log", "file", "screenshot", "note", "command_output"}:
            raise ValueError("evidence_type must be log|file|screenshot|note|command_output")
        return value


@router.post("/{ticket_id}/evidence", status_code=201)
async def add_evidence(
    ticket_id: uuid.UUID,
    payload: EvidencePayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    ticket = await _visible_ticket(db, scope, ticket_id)
    if scope.role == UserRole.it_developer.value:
        await _require_it_write(db, scope, ticket)
    else:
        await _require_ticket_soc_write(db, scope, ticket.organization_id)

    actor_type, actor_id = _actor(scope)
    evidence = Evidence(
        organization_id=ticket.organization_id,
        incident_id=ticket.incident_id,  # NULL on standalone tickets
        ticket_id=ticket.id,
        evidence_type=EvidenceType(payload.evidence_type),
        title=payload.title,
        description=payload.description,
        storage_ref=payload.storage_ref,
        added_by_type=actor_type,
        added_by_id=actor_id,
    )
    db.add(evidence)
    await _audit(db, scope, ticket, action="ticket.evidence_add", after={"title": evidence.title})
    await db.commit()
    await db.refresh(evidence)
    return {
        "id": str(evidence.id),
        "ticket_id": str(ticket.id),
        "evidence_type": evidence.evidence_type.value,
        "title": evidence.title,
        "storage_ref": evidence.storage_ref,
    }


# ---------------------------------------------------------------------------
# Verify (the SOC's verdict; /transition handles plain status moves).
# ---------------------------------------------------------------------------


class VerifyPayload(BaseModel):
    result: str
    notes: str | None = None
    method: str | None = Field(default=None, max_length=120)

    @field_validator("result")
    @classmethod
    def _result_shape(cls, value: str) -> str:
        if value not in {"verified", "failed", "reopened"}:
            raise ValueError("result must be verified|failed|reopened")
        return value


VERIFY_TRANSITIONS = {
    VerificationResult.verified: TicketStatus.resolved,
    VerificationResult.failed: TicketStatus.investigating,
    VerificationResult.reopened: TicketStatus.open,
}


@router.post("/{ticket_id}/verify")
async def verify_ticket(
    ticket_id: uuid.UUID,
    payload: VerifyPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    """The SOC verifies the fix: verified -> RESOLVED, failed ->
    INVESTIGATING, reopened -> OPEN. SOC-only (IT never verifies)."""
    ticket = await _visible_ticket(db, scope, ticket_id)
    if scope.role == UserRole.it_developer.value:
        raise _err("it_cannot_close", "IT developers cannot verify tickets.", 403)
    await _require_ticket_soc_write(db, scope, ticket.organization_id)

    result = VerificationResult(payload.result)
    if ticket.status != TicketStatus.verification:
        raise _err(
            "invalid_ticket_transition",
            "Only a ticket in VERIFICATION can be verified.",
            409,
            TICKET_TRANSITIONS.get(ticket.status, set()),
        )

    target = VERIFY_TRANSITIONS[result]
    from_status = ticket.status
    ticket.status = target
    now = datetime.now(timezone.utc)
    if target == TicketStatus.resolved:
        ticket.resolved_at = now
    else:
        ticket.resolved_at = None

    db.add(
        Verification(
            ticket_id=ticket.id,
            verified_by_type=ActorType.admin if scope.account_type == "admin" else ActorType.user,
            verified_by_id=scope.user_id,
            method=payload.method,
            result=result,
            notes=payload.notes,
        )
    )
    await _append_status_history(
        db, ticket, from_status=from_status, to_status=target, scope=scope,
        note=payload.notes or f"Verification {result.value}",
    )
    await _append_incident_timeline(
        db, ticket,
        entry_type="ticket_status",
        description=f"Ticket {ticket.ticket_number} verification {result.value}.",
        scope=scope,
        metadata={"ticket_id": str(ticket.id), "verification": result.value},
    )
    await _audit(
        db, scope, ticket, action="ticket.verify",
        before={"status": from_status.value},
        after={"status": target.value, "result": result.value},
    )
    await db.commit()
    await db.refresh(ticket)
    return _row(ticket)


# ---------------------------------------------------------------------------
# Close-request (critical tickets): the SOC asks the organization's
# security_manager or owner for the ticket_close approval the close gate
# requires. The row these create is decided via the approvals router
# (POST /api/v1/approvals/{id}/decision); P19 brings the full UI.
# ---------------------------------------------------------------------------


class CloseRequestPayload(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


@router.post("/{ticket_id}/close-request", status_code=201)
async def request_ticket_close(
    ticket_id: uuid.UUID,
    payload: CloseRequestPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    """SOC-only: create the PENDING ticket_close approval a CRITICAL
    (P1) ticket must have approved before the SOC may close it. An
    already-pending request for this ticket is 409
    close_request_already_pending; a non-critical ticket is 422 (it
    closes freely -- asking for approval would be noise)."""
    ticket = await _visible_ticket(db, scope, ticket_id)
    if scope.role == UserRole.it_developer.value:
        raise _err("ticket_write_not_allowed", "IT developers cannot request ticket closure.", 403)
    await _require_ticket_soc_write(db, scope, ticket.organization_id)

    if ticket.priority != "P1":
        raise _err(
            "close_approval_not_required",
            "Only CRITICAL (P1) tickets need a close approval.",
            422,
        )

    pending = (
        await db.execute(
            select(Approval).where(
                Approval.action_type == "ticket_close",
                Approval.action_payload["ticket_id"].as_string() == str(ticket.id),
                Approval.status == ApprovalStatus.pending,
            )
        )
    ).scalar_one_or_none()
    if pending is not None:
        raise _err(
            "close_request_already_pending",
            "A close approval is already pending for this ticket.",
            409,
        )

    actor_type, actor_id = _actor(scope)
    approval = Approval(
        organization_id=ticket.organization_id,
        requested_by_type=actor_type,
        requested_by_id=actor_id,
        action_type="ticket_close",
        action_payload={"ticket_id": str(ticket.id), "notes": payload.notes} if payload.notes else {"ticket_id": str(ticket.id)},
        risk_level=ApprovalRiskLevel.high,
    )
    db.add(approval)
    await _append_incident_timeline(
        db, ticket,
        entry_type="ticket_close_requested",
        description=f"Ticket {ticket.ticket_number}: SOC requested closure approval.",
        scope=scope,
        metadata={"ticket_id": str(ticket.id), "approval_id": None},
    )
    await _audit(db, scope, ticket, action="ticket.close_request", after={"priority": ticket.priority})
    await db.commit()
    await db.refresh(approval)
    return {
        "id": str(approval.id),
        "ticket_id": str(ticket.id),
        "status": approval.status.value if hasattr(approval.status, "value") else approval.status,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
    }


# ---------------------------------------------------------------------------
# Escalate (manual; the worker creates breach escalations too).
# ---------------------------------------------------------------------------


class EscalatePayload(BaseModel):
    reason: str = Field(min_length=1)
    escalated_to_user_id: uuid.UUID | None = None


@router.post("/{ticket_id}/escalate", status_code=201)
async def escalate_ticket(
    ticket_id: uuid.UUID,
    payload: EscalatePayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_read_gate),
):
    ticket = await _visible_ticket(db, scope, ticket_id)
    if scope.role == UserRole.it_developer.value:
        raise _err("ticket_write_not_allowed", "IT developers cannot escalate tickets.", 403)
    await _require_ticket_soc_write(db, scope, ticket.organization_id)

    if payload.escalated_to_user_id is not None:
        user = (
            await db.execute(
                select(User).where(
                    User.id == payload.escalated_to_user_id,
                    User.organization_id == ticket.organization_id,
                )
            )
        ).scalar_one_or_none()
        if user is None:
            raise _err("assignee_not_in_scope", "Escalation target must belong to the ticket's organization.", 422)

    actor_type, actor_id = _actor(scope)
    from app.models import Escalation

    escalation = Escalation(
        ticket_id=ticket.id,
        incident_id=ticket.incident_id,
        reason=payload.reason,
        escalated_from=actor_id if actor_type == ActorType.user else None,
        escalated_to_user_id=payload.escalated_to_user_id,
    )
    db.add(escalation)
    await _append_incident_timeline(
        db, ticket,
        entry_type="ticket_escalated",
        description=f"Ticket {ticket.ticket_number} escalated: {payload.reason}",
        scope=scope,
    )
    await _audit(db, scope, ticket, action="ticket.escalate", after={"reason": payload.reason})
    await db.commit()
    return {
        "id": str(escalation.id),
        "ticket_id": str(ticket.id),
        "reason": escalation.reason,
        "created_at": escalation.created_at.isoformat() if escalation.created_at else None,
    }
