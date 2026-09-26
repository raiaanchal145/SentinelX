"""
Incidents API (docs/API_CONTRACT.md "Incidents").

POST  /api/v1/incidents                  -- create manually.
POST  /api/v1/incidents/from-alerts      -- create from 1+ alerts
                                            (the alerts become TRIAGED --
                                            "alert status follows the
                                            incident" at creation; they
                                            become CONVERTED when the
                                            incident reaches RESOLVED or
                                            CLOSED).
GET   /api/v1/incidents                  -- the queue (filters: status,
                                            severity, organization for
                                            platform roles, assignee,
                                            asset, time; keyset cursor).
GET   /api/v1/incidents/{id}             -- detail: linked alerts,
                                            events, assets, timeline.
PATCH /api/v1/incidents/{id}             -- title/description/severity/
                                            assignee.
POST  /api/v1/incidents/{id}/transition  -- the one state-change door.
POST  /api/v1/incidents/{id}/links       -- add/remove alert/event/asset.
POST  /incidents/{id}/merge              -- merge a DUPLICATE into its
                                            parent.
POST  /incidents/{id}/comments           -- internal vs shared notes.

Ownership follows the soc mode (same matrix as alerts): managed orgs'
incidents are worked by platform SOC analysts assigned to them; in-house
orgs' by their own soc_analyst users. Owner and security_manager keep
read oversight everywhere; the security_manager may additionally request
escalation (ESCALATED) from any non-terminal state. Every state change
validates against INCIDENT_TRANSITIONS (the one map, tested), appends
one incident_timeline row and one audit_logs row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_module, soc_visible_organization_ids
from app.audit import audit_from_scope
from app.database import get_db
from app.models import (
    ActorType,
    Admin,
    AdminLevel,
    Alert,
    AlertHistory,
    AlertStatus,
    Asset,
    Incident,
    IncidentAlert,
    IncidentAsset,
    IncidentEvent,
    IncidentStatus,
    IncidentTimeline,
    Organization,
    SecurityEvent,
    SocMode,
    SocOrganizationAssignment,
    User,
    UserRole,
)
from app.scope import Scope, org_scope

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


def _err(
    code: str,
    message: str,
    status_code: int = 400,
    allowed: set[IncidentStatus] | None = None,
) -> HTTPException:
    """The structured-detail error; `allowed` (the legal next states)
    rides along on 409 invalid_incident_transition responses."""
    detail: dict = {"code": code, "message": message}
    if allowed is not None:
        detail["allowed_next_states"] = sorted(s.value for s in allowed)
    return HTTPException(status_code=status_code, detail=detail)


# ---------------------------------------------------------------------------
# The transition map -- the ONE place incident status changes are validated.
# (docs/DECISIONS.md; the lifecycle's "CONTAINED" and "PENDING_VERIFICATION"
# are the enum's own CONTAINMENT and VERIFICATION members.)
# ---------------------------------------------------------------------------

# The lifecycle, one table (docs/DECISIONS.md): NEW -> TRIAGED ->
# INVESTIGATING -> CONTAINMENT -> REMEDIATION -> VERIFICATION -> RESOLVED
# -> CLOSED, one-step back everywhere, ESCALATED into and out of every
# active state, and FALSE_POSITIVE/DUPLICATE reachable from every
# ACTIVE state (i.e. everything except RESOLVED/CLOSED/ESCALATED and
# the two terminal states themselves).
_ACTIVE_CLOSURES = {IncidentStatus.false_positive, IncidentStatus.duplicate}
INCIDENT_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.new: {IncidentStatus.triaged, IncidentStatus.investigating}
    | _ACTIVE_CLOSURES,
    IncidentStatus.triaged: {IncidentStatus.investigating}
    | {IncidentStatus.escalated}
    | _ACTIVE_CLOSURES,
    IncidentStatus.investigating: {IncidentStatus.triaged, IncidentStatus.containment}
    | {IncidentStatus.escalated}
    | _ACTIVE_CLOSURES,
    IncidentStatus.containment: {IncidentStatus.investigating, IncidentStatus.remediation}
    | {IncidentStatus.escalated}
    | _ACTIVE_CLOSURES,
    IncidentStatus.remediation: {IncidentStatus.containment, IncidentStatus.verification}
    | {IncidentStatus.escalated}
    | _ACTIVE_CLOSURES,
    IncidentStatus.verification: {IncidentStatus.remediation, IncidentStatus.resolved}
    | {IncidentStatus.escalated}
    | _ACTIVE_CLOSURES,
    IncidentStatus.resolved: {IncidentStatus.closed, IncidentStatus.reopened},
    IncidentStatus.closed: {IncidentStatus.reopened},
    IncidentStatus.reopened: {IncidentStatus.triaged, IncidentStatus.investigating, IncidentStatus.containment}
    | {IncidentStatus.escalated}
    | _ACTIVE_CLOSURES,
    # Picked back up by the owning SOC team.
    IncidentStatus.escalated: {
        IncidentStatus.triaged,
        IncidentStatus.investigating,
        IncidentStatus.containment,
    },
    # Terminal.
    IncidentStatus.false_positive: set(),
    IncidentStatus.duplicate: set(),
}


def _validate_transition(current: IncidentStatus, target: IncidentStatus) -> None:
    """Kept alongside the map for parity with the alerts router (tests
    call the endpoints, which inline the same check to attach the
    allowed-states list to the 409)."""
    allowed = INCIDENT_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise _err(
            "invalid_incident_transition",
            f"Cannot move an incident from '{current.value}' to '{target.value}'.",
            409,
            allowed,
        )


# ---------------------------------------------------------------------------
# Visibility + write access (the alerts routing matrix, reused).
# ---------------------------------------------------------------------------


async def _incident_visibility(db: AsyncSession, scope: Scope) -> tuple[str, list[uuid.UUID] | None]:
    """
    ("all", None)              super_admin.
    ("orgs", ids)              platform SOC (assigned managed+active);
                               in-house org accounts with module
                               `incidents` read: their own org; a
                               MANAGED org's owner/security_manager:
                               their own org, READ-ONLY.
    ("it_shared", [own org])   it_developer: their own organization only,
                               READ-ONLY, and the detail endpoint filters
                               internal timeline entries out (shared
                               comments only -- docs/DECISIONS.md).
    ("empty", None)            a platform SOC analyst with zero
                               assignments.
    ("forbidden", None)        everyone else.
    """
    visible = await soc_visible_organization_ids(db, scope)
    if visible is None:
        return "all", None

    if scope.account_type == "admin" and scope.role == AdminLevel.organization_admin.value:
        return "orgs", [scope.organization_id]

    # Same rule the alerts router applies: the security_manager keeps
    # incidents read in BOTH modes (role default isn't soc-mode-gated),
    # so a managed org's security_manager keeps read oversight + the
    # escalation request.
    if scope.role == UserRole.security_manager.value and scope.organization_id is not None:
        return "orgs", [scope.organization_id]

    # IT developers get a narrow, read-only window: their own
    # organization's incidents with SHARED timeline entries only (the
    # remediation context for their tickets), never the SOC's internal
    # notes, never a write.
    if scope.role == UserRole.it_developer.value and scope.organization_id is not None:
        return "it_shared", [scope.organization_id]

    if visible:
        return "orgs", list(visible)

    if scope.role == AdminLevel.platform_soc_analyst.value:
        return "empty", None
    return "forbidden", None


async def _require_incident_write(db: AsyncSession, scope: Scope, organization_id: uuid.UUID) -> None:
    """
    Who may CHANGE an incident: super_admin; a platform SOC analyst
    assigned to that (managed) organization; an in-house org's
    soc_analyst. Owner and security_manager are read-only at most --
    except the security_manager's ESCALATION request, validated by the
    transition endpoint separately.
    """
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
            raise _err("incident_not_found", "Incident not found.", 404)  # existence never leaked
        return
    # Owner (organization_admin) and security_manager are READ-ONLY in
    # both modes (docs/API_CONTRACT.md "Incidents" -- the milestone
    # spec overrides the role-default module write for this feature;
    # the security_manager's one write is the ESCALATED request, which
    # the transition endpoint permits before this guard).
    if scope.account_type == "admin" or scope.role == UserRole.security_manager.value:
        raise _err(
            "incident_write_not_allowed",
            "The organization owner and security manager have read-only oversight of incidents.",
            403,
        )
    if scope.role == UserRole.soc_analyst.value and scope.organization_id == organization_id:
        return
    raise _err("incident_write_not_allowed", "You do not have permission to change incidents.", 403)


_require_incidents_read = require_module("incidents", write=False)


async def _require_incidents_read_or_it(
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(org_scope)
) -> Scope:
    """The read gate for list/detail: module `incidents` read -- with one
    deliberate exception, the IT developer's shared-only window (no
    incidents module by default; docs/DECISIONS.md). Every OTHER rule
    (which organization, which timeline rows) is still enforced by the
    endpoints themselves, so this widens the gate, never the data."""
    if scope.role == UserRole.it_developer.value and scope.organization_id is not None:
        return scope
    return await _require_incidents_read(db=db, scope=scope)


async def _organization_filter_scope(
    db: AsyncSession, scope: Scope, organization_id: uuid.UUID | None
) -> uuid.UUID | None:
    """The list endpoint's optional organization_id -- same rule as
    alerts/events: an id the caller cannot see is 404, never a leak."""
    if organization_id is None:
        return None
    mode, org_ids = await _incident_visibility(db, scope)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to incidents for this organization.", 403)
    if mode in ("orgs", "it_shared", "empty") and organization_id not in (org_ids or []):
        raise _err("organization_not_found", "Organization not found.", 404)
    if mode == "all":
        exists = (
            await db.execute(select(Organization.id).where(Organization.id == organization_id))
        ).scalar_one_or_none()
        if exists is None:
            raise _err("organization_not_found", "Organization not found.", 404)
    return organization_id


# ---------------------------------------------------------------------------
# Timeline + audit -- every change appends one row to each.
# ---------------------------------------------------------------------------


def _actor(scope: Scope) -> tuple[ActorType, uuid.UUID]:
    return (ActorType.admin if scope.account_type == "admin" else ActorType.user, scope.user_id)


async def _append_timeline(
    db: AsyncSession,
    incident: Incident,
    *,
    entry_type: str,
    description: str,
    scope: Scope | None,
    metadata: dict | None = None,
) -> None:
    if scope is None:
        actor_type, actor_id = ActorType.system, None
    else:
        actor_type, actor_id = _actor(scope)
    db.add(
        IncidentTimeline(
            incident_id=incident.id,
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
    incident: Incident,
    *,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    await audit_from_scope(
        db,
        scope,
        action,
        organization_id=incident.organization_id,
        target_type="incident",
        target_id=incident.id,
        before=before,
        after=after,
    )


def _append_alert_history(
    db: AsyncSession,
    alert: Alert,
    *,
    organization_id: uuid.UUID,
    action: str,
    scope: Scope,
    status_from: AlertStatus | None = None,
    detail: dict | None = None,
) -> None:
    """One alert_history row for a side-effect change an incident made to
    a linked alert (the P10 convention: the alert's own story records
    every status touch, whoever made it)."""
    db.add(
        AlertHistory(
            alert_id=alert.id,
            organization_id=organization_id,
            action=action,
            actor_type=ActorType.admin if scope.account_type == "admin" else ActorType.user,
            actor_id=scope.user_id,
            status_from=status_from,
            status_to=alert.status,
            detail=detail,
        )
    )


# ---------------------------------------------------------------------------
# Row shaping.
# ---------------------------------------------------------------------------


def _row(incident: Incident, *, alert_count: int | None = None) -> dict:
    row = {
        "id": str(incident.id),
        "organization_id": str(incident.organization_id),
        "title": incident.title,
        "summary": incident.summary,
        "severity": incident.severity.value if hasattr(incident.severity, "value") else incident.severity,
        "priority": incident.priority,
        "confidence": incident.confidence,
        "status": incident.status.value if hasattr(incident.status, "value") else incident.status,
        "primary_asset_id": str(incident.primary_asset_id) if incident.primary_asset_id else None,
        "correlation_id": str(incident.correlation_id) if incident.correlation_id else None,
        "assigned_account_type": incident.assigned_account_type,
        "assigned_account_id": str(incident.assigned_account_id) if incident.assigned_account_id else None,
        "resolution_summary": incident.resolution_summary,
        "closure_reason": incident.closure_reason,
        "duplicate_of_id": str(incident.duplicate_of_id) if incident.duplicate_of_id else None,
        "opened_at": incident.opened_at.isoformat() if incident.opened_at else None,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "closed_at": incident.closed_at.isoformat() if incident.closed_at else None,
        "created_by_type": incident.created_by_type.value if hasattr(incident.created_by_type, "value") else incident.created_by_type,
        "created_by_id": str(incident.created_by_id) if incident.created_by_id else None,
    }
    if alert_count is not None:
        row["alert_count"] = alert_count
    return row


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        raise _err("invalid_time_range", f"Invalid ISO-8601 timestamp for {field}.", 400)


def _encode_cursor(opened_at: datetime, incident_id: uuid.UUID) -> str:
    import base64
    import json

    payload = json.dumps({"t": opened_at.isoformat(), "id": str(incident_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    import base64
    import json

    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(payload["t"]), uuid.UUID(payload["id"])
    except Exception:  # noqa: BLE001 -- a bad cursor is a 400, not a 500
        raise _err("invalid_cursor", "Invalid pagination cursor.", 400)


# ---------------------------------------------------------------------------
# Visible-incident lookup (404 across the visibility boundary).
# ---------------------------------------------------------------------------


async def _visible_incident(db: AsyncSession, scope: Scope, incident_id: uuid.UUID) -> Incident:
    mode, org_ids = await _incident_visibility(db, scope)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to incidents.", 403)
    if mode == "empty":
        raise _err("incident_not_found", "Incident not found.", 404)

    stmt = select(Incident).where(Incident.id == incident_id)
    if mode in ("orgs", "it_shared"):
        stmt = stmt.where(Incident.organization_id.in_(org_ids))
    incident = (await db.execute(stmt)).scalar_one_or_none()
    if incident is None:
        raise _err("incident_not_found", "Incident not found.", 404)
    return incident


async def _validate_assignee(
    db: AsyncSession, organization_id: uuid.UUID, account_type: str, account_id: uuid.UUID
) -> None:
    """The same scope rules as alerts: a managed org's incidents assign
    to platform SOC analysts assigned to it; an in-house org's to its
    own soc_analyst users."""
    org = await db.get(Organization, organization_id)
    if org is None:
        raise _err("incident_not_found", "Incident not found.", 404)

    if account_type == "admin":
        admin = (await db.execute(select(Admin).where(Admin.id == account_id))).scalar_one_or_none()
        if admin is None:
            raise _err("assignee_not_found", "No such admin account.", 404)
        if admin.admin_level != AdminLevel.platform_soc_analyst:
            raise _err("assignee_not_in_scope", "Only platform SOC analysts can be assigned platform-side.", 422)
        assigned = (
            await db.execute(
                select(SocOrganizationAssignment.organization_id).where(
                    SocOrganizationAssignment.admin_id == account_id,
                    SocOrganizationAssignment.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        if assigned is None:
            raise _err("assignee_not_in_scope", "That analyst is not assigned to this organization.", 422)
        return

    user = (await db.execute(select(User).where(User.id == account_id))).scalar_one_or_none()
    if user is None:
        raise _err("assignee_not_found", "No such user account.", 404)
    if user.organization_id != organization_id:
        raise _err("assignee_not_in_scope", "That user does not belong to this organization.", 422)
    if org.soc_mode != SocMode.in_house or user.role != UserRole.soc_analyst:
        raise _err(
            "assignee_not_in_scope",
            "Incidents can only be assigned to this organization's own soc_analyst users.",
            422,
        )


VALID_PRIORITIES = {"p1", "p2", "p3", "p4", "P1", "P2", "P3", "P4"}


# ---------------------------------------------------------------------------
# Creation.
# ---------------------------------------------------------------------------


class CreatePayload(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    description: str | None = None
    severity: str = "medium"
    priority: str | None = None  # suggested only; P13 derives the real one
    category: str | None = Field(default=None, max_length=60)
    # Platform roles (and super_admin) name the organization; org-scoped
    # callers may omit it (their own organization is used).
    organization_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    event_ids: list[uuid.UUID] = Field(default_factory=list)
    alert_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("priority")
    @classmethod
    def _priority_shape(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_PRIORITIES:
            raise ValueError("priority must be one of P1..P4")
        return value


class FromAlertsPayload(BaseModel):
    alert_ids: list[uuid.UUID] = Field(min_length=1)
    title: str | None = Field(default=None, max_length=250)
    description: str | None = None
    severity: str | None = None
    priority: str | None = None
    category: str | None = Field(default=None, max_length=60)

    @field_validator("priority")
    @classmethod
    def _priority_shape(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_PRIORITIES:
            raise ValueError("priority must be one of P1..P4")
        return value


async def _create_incident(
    db: AsyncSession,
    scope: Scope,
    *,
    organization_id: uuid.UUID,
    payload: CreatePayload | FromAlertsPayload,
    alert_ids: list[uuid.UUID],
) -> Incident:
    """Shared creation path for both endpoints: validates every linked
    row belongs to the organization, writes the incident + links +
    opening timeline + audit. The caller commits."""
    severity_value = (payload.severity or "medium").lower()
    try:
        from app.models import EventSeverity

        severity = EventSeverity(severity_value)
    except ValueError:
        raise _err("invalid_severity", f"Unknown severity '{payload.severity}'.", 400)

    priority = getattr(payload, "priority", None)
    category = getattr(payload, "category", None)
    description = getattr(payload, "description", None)

    # --- validate links (existence is never leaked across orgs) -------
    linked_alerts: list[Alert] = []
    if alert_ids:
        rows = (
            await db.execute(
                select(Alert).where(Alert.id.in_(alert_ids), Alert.organization_id == organization_id)
            )
        ).scalars().all()
        found = {a.id for a in rows}
        missing = [str(a) for a in alert_ids if a not in found]
        if missing:
            raise _err("alert_not_found", f"Alert(s) not found: {', '.join(missing[:3])}.", 404)
        linked_alerts = list(rows)

    event_rows: list[SecurityEvent] = []
    event_ids = getattr(payload, "event_ids", []) or []
    if event_ids:
        rows = (
            await db.execute(
                select(SecurityEvent).where(SecurityEvent.id.in_(event_ids), SecurityEvent.organization_id == organization_id)
            )
        ).scalars().all()
        found = {e.id for e in rows}
        missing = [str(e) for e in event_ids if e not in found]
        if missing:
            raise _err("event_not_found", f"Event(s) not found: {', '.join(missing[:3])}.", 404)
        event_rows = list(rows)

    asset_id = getattr(payload, "asset_id", None)
    primary_asset: Asset | None = None
    if asset_id is not None:
        primary_asset = (
            await db.execute(select(Asset).where(Asset.id == asset_id, Asset.organization_id == organization_id))
        ).scalar_one_or_none()
        if primary_asset is None:
            raise _err("asset_not_found", "Asset not found.", 404)

    # --- the row -------------------------------------------------------
    incident = Incident(
        organization_id=organization_id,
        title=payload.title,
        summary=description,
        severity=severity,
        priority=priority.upper() if priority else None,
        status=IncidentStatus.new,
        primary_asset_id=primary_asset.id if primary_asset else None,
        created_by_type=ActorType.admin if scope.account_type == "admin" else ActorType.user,
        created_by_id=scope.user_id,
    )
    db.add(incident)
    await db.flush()

    for alert in linked_alerts:
        db.add(IncidentAlert(incident_id=incident.id, alert_id=alert.id))
        # Alert status follows the incident: triaged at creation.
        if alert.status == AlertStatus.new:
            alert.status = AlertStatus.triaged
    for event in event_rows:
        db.add(IncidentEvent(incident_id=incident.id, event_id=event.id))

    await _append_timeline(
        db,
        incident,
        entry_type="created",
        description=f"Incident created with {len(linked_alerts)} linked alert(s), {len(event_rows)} linked event(s).",
        scope=scope,
        metadata={"alert_ids": [str(a.id) for a in linked_alerts], "event_ids": [str(e.id) for e in event_rows]},
    )
    await _audit(db, scope, incident, action="incident.create", after={"status": "NEW", "title": incident.title})
    return incident


@router.post("", status_code=201)
async def create_incident(
    payload: CreatePayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_incidents_read),
):
    """Manual creation. Module `incidents` read gets visibility, but only
    writers may create -- enforced after the visibility check so the
    error shapes stay consistent with the rest of the router."""
    mode, org_ids = await _incident_visibility(db, scope)
    if mode in ("forbidden", "empty", "it_shared"):
        raise _err("soc_not_visible", "You do not have access to incidents.", 403)

    # Where does the incident live? Org-scoped callers: their own org.
    # Platform roles/super_admin: the payload must name it, and it must
    # be one the caller may see (404 otherwise -- never a leak).
    if scope.organization_id is not None:
        organization_id = scope.organization_id
    else:
        if payload.organization_id is None:
            raise _err("organization_id_required", "An organization_id is required to create an incident.", 400)
        organization_id = await _organization_filter_scope(db, scope, payload.organization_id)

    await _require_incident_write(db, scope, organization_id)

    if payload.asset_id is not None:
        asset = (
            await db.execute(select(Asset).where(Asset.id == payload.asset_id, Asset.organization_id == organization_id))
        ).scalar_one_or_none()
        if asset is None:
            raise _err("asset_not_found", "Asset not found.", 404)

    incident = await _create_incident(db, scope, organization_id=organization_id, payload=payload, alert_ids=[])
    await db.commit()
    await db.refresh(incident)
    return _row(incident)


@router.post("/from-alerts", status_code=201)
async def create_from_alerts(
    payload: FromAlertsPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_incidents_read),
):
    """Create from 1+ alerts of one organization. The alerts' statuses
    follow: NEW alerts become TRIAGED here; when the incident later
    reaches RESOLVED/CLOSED they become CONVERTED. Every alert must be
    visible to the caller (another org's id is 404)."""
    mode, org_ids = await _incident_visibility(db, scope)
    if mode in ("forbidden", "empty", "it_shared"):
        raise _err("soc_not_visible", "You do not have access to incidents.", 403)

    alerts = (
        await db.execute(select(Alert).where(Alert.id.in_(payload.alert_ids)))
    ).scalars().all()
    found = {a.id for a in alerts}
    missing = [str(a) for a in payload.alert_ids if a not in found]
    if missing:
        raise _err("alert_not_found", f"Alert(s) not found: {', '.join(missing[:3])}.", 404)

    alert_orgs = {a.organization_id for a in alerts}
    if len(alert_orgs) != 1:
        raise _err("alerts_from_multiple_organizations", "All alerts must belong to the same organization.", 400)
    organization_id = alert_orgs.pop()

    # Visibility over that organization specifically.
    mode, org_ids = await _incident_visibility(db, scope)
    if mode == "orgs" and organization_id not in (org_ids or []):
        raise _err("alert_not_found", "Alert not found.", 404)  # existence never leaked

    await _require_incident_write(db, scope, organization_id)

    # Alerts already converted (or linked to another incident of this
    # org) cannot start a new one.
    for alert in alerts:
        if alert.status == AlertStatus.converted:
            raise _err("alert_already_converted", f"Alert {alert.id} is already part of an incident.", 409)

    title = payload.title or f"Incident from {len(payload.alert_ids)} alert(s)"
    severity = payload.severity or max((a.severity.value for a in alerts), key=lambda s: ["info", "low", "medium", "high", "critical"].index(s))
    create_payload = CreatePayload(
        title=title,
        description=payload.description,
        severity=severity,
        priority=payload.priority,
        category=payload.category,
        asset_id=None,
        event_ids=[],
        alert_ids=[],
    )
    incident = await _create_incident(db, scope, organization_id=organization_id, payload=create_payload, alert_ids=list(payload.alert_ids))

    # Link the alerts' supporting events too -- the incident's evidence
    # starts from what the alerts already collected.
    from app.models import AlertEvent

    alert_event_rows = (
        await db.execute(
            select(AlertEvent).where(AlertEvent.alert_id.in_([a.id for a in alerts]))
        )
    ).scalars().all()
    seen_events: set[uuid.UUID] = set()
    for link in alert_event_rows:
        if link.event_id in seen_events:
            continue
        seen_events.add(link.event_id)
        db.add(IncidentEvent(incident_id=incident.id, event_id=link.event_id))

    await db.commit()
    await db.refresh(incident)
    return _row(incident)


# ---------------------------------------------------------------------------
# The queue.
# ---------------------------------------------------------------------------


@router.get("")
async def list_incidents(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_incidents_read_or_it),
    status: str | None = None,
    severity: str | None = None,
    assignee: str | None = None,
    asset_id: uuid.UUID | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
    organization_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
):
    """The incident queue. Filters: status, severity, assignee ("me" or
    an account id), asset, time range on opened_at, plus
    organization_id for platform roles. Keyset pagination on
    (opened_at DESC, id DESC)."""
    mode, org_ids = await _incident_visibility(db, scope)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to incidents.", 403)

    # Validate the organization filter BEFORE the empty-queue return:
    # an unassigned platform SOC analyst naming an organization gets a
    # 404, never a silent 200 with zero rows.
    effective_org = await _organization_filter_scope(db, scope, organization_id)

    if mode == "empty":
        return {"incidents": [], "next_cursor": None}

    stmt = select(Incident)
    if mode in ("orgs", "it_shared"):
        stmt = stmt.where(Incident.organization_id.in_(org_ids))
    if effective_org is not None:
        stmt = stmt.where(Incident.organization_id == effective_org)
    if status:
        try:
            stmt = stmt.where(Incident.status == IncidentStatus[status.lower()])
        except KeyError:
            raise _err("invalid_status", f"Unknown incident status '{status}'.", 400)
    if severity:
        try:
            from app.models import EventSeverity

            stmt = stmt.where(Incident.severity == EventSeverity(severity.lower()))
        except ValueError:
            raise _err("invalid_severity", f"Unknown severity '{severity}'.", 400)
    if assignee:
        if assignee == "me":
            stmt = stmt.where(
                Incident.assigned_account_id == scope.user_id,
                Incident.assigned_account_type == scope.account_type,
            )
        else:
            try:
                stmt = stmt.where(Incident.assigned_account_id == uuid.UUID(assignee))
            except ValueError:
                raise _err("invalid_assignee", "assignee must be 'me' or an account id.", 400)
    if asset_id:
        stmt = stmt.where(Incident.primary_asset_id == asset_id)
    if time_from:
        stmt = stmt.where(Incident.opened_at >= _parse_time(time_from, "time_from"))
    if time_to:
        stmt = stmt.where(Incident.opened_at <= _parse_time(time_to, "time_to"))
    if cursor:
        cursor_opened, cursor_id = _decode_cursor(cursor)
        from sqlalchemy import or_

        stmt = stmt.where(
            or_(
                Incident.opened_at < cursor_opened,
                (Incident.opened_at == cursor_opened) & (Incident.id < cursor_id),
            )
        )

    stmt = stmt.order_by(Incident.opened_at.desc(), Incident.id.desc()).limit(limit + 1)
    rows = ((await db.execute(stmt)).scalars().all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.opened_at, last.id)

    # Batch the per-incident alert counts for the queue view.
    counts: dict[uuid.UUID, int] = {}
    if rows:
        count_rows = (
            await db.execute(
                select(IncidentAlert.incident_id, func.count())
                .where(IncidentAlert.incident_id.in_([i.id for i in rows]))
                .group_by(IncidentAlert.incident_id)
            )
        ).all()
        counts = {incident_id: count for incident_id, count in count_rows}

    return {
        "incidents": [_row(i, alert_count=counts.get(i.id, 0)) for i in rows],
        "next_cursor": next_cursor,
    }


# ---------------------------------------------------------------------------
# Detail.
# ---------------------------------------------------------------------------


@router.get("/{incident_id}")
async def get_incident(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_incidents_read_or_it),
):
    """The incident plus linked alerts, events, assets and the full
    timeline. Internal timeline entries are filtered to SOC eyes
    (everyone in this router passes module `incidents`; IT developers
    never reach here because the module gate refuses them)."""
    incident = await _visible_incident(db, scope, incident_id)

    linked_alerts = (
        (
            await db.execute(
                select(Alert)
                .join(IncidentAlert, IncidentAlert.alert_id == Alert.id)
                .where(IncidentAlert.incident_id == incident.id)
                .order_by(Alert.first_seen_at)
            )
        )
        .scalars()
        .all()
    )

    linked_events = (
        (
            await db.execute(
                select(SecurityEvent)
                .join(IncidentEvent, IncidentEvent.event_id == SecurityEvent.id)
                .where(IncidentEvent.incident_id == incident.id)
                .order_by(SecurityEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )

    linked_assets = (
        (
            await db.execute(
                select(Asset)
                .join(IncidentAsset, IncidentAsset.asset_id == Asset.id)
                .where(IncidentAsset.incident_id == incident.id)
            )
        )
        .scalars()
        .all()
    )

    timeline = (
        (
            await db.execute(
                select(IncidentTimeline)
                .where(IncidentTimeline.incident_id == incident.id)
                .order_by(IncidentTimeline.occurred_at, IncidentTimeline.id)
            )
        )
        .scalars()
        .all()
    )

    # The IT developer's window: internal (SOC-only) timeline entries are
    # filtered out server-side -- they see the shared story only. The
    # filter happens HERE, not in the client, so the data never leaves
    # the API for an unauthorized caller.
    mode_for_filter, _ = await _incident_visibility(db, scope)
    if mode_for_filter == "it_shared":
        timeline = [
            t
            for t in timeline
            if t.entry_type != "comment" or (t.entry_metadata or {}).get("visibility") == "shared"
        ]

    parent = None
    if incident.duplicate_of_id:
        parent_row = await db.get(Incident, incident.duplicate_of_id)
        if parent_row is not None:
            parent = {"id": str(parent_row.id), "title": parent_row.title, "status": parent_row.status.value}

    return {
        "incident": _row(incident),
        "alerts": [
            {
                "id": str(a.id),
                "title": a.title,
                "severity": a.severity.value,
                "status": a.status.value,
                "rule_name": a.rule_name,
            }
            for a in linked_alerts
        ],
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "username": e.username,
                "source_ip": e.source_ip,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                "message": (e.normalized_data or {}).get("message"),
            }
            for e in linked_events
        ],
        "assets": [
            {
                "id": str(a.id),
                "name": a.name,
                "hostname": a.hostname,
                "criticality": a.criticality.value,
            }
            for a in linked_assets
        ],
        "duplicate_of": parent,
        "timeline": [
            {
                "id": str(t.id),
                "entry_type": t.entry_type,
                "description": t.description,
                "actor_type": t.actor_type.value if hasattr(t.actor_type, "value") else t.actor_type,
                "actor_id": str(t.actor_id) if t.actor_id else None,
                "visibility": (t.entry_metadata or {}).get("visibility", "internal"),
                "metadata": t.entry_metadata,
                "occurred_at": t.occurred_at.isoformat() if t.occurred_at else None,
            }
            for t in timeline
        ],
    }


# ---------------------------------------------------------------------------
# PATCH (title/description/severity/assignee).
# ---------------------------------------------------------------------------


class PatchPayload(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=250)
    description: str | None = None
    severity: str | None = None
    assigned_account_type: str | None = Field(default=None, pattern="^(admin|user)$")
    assigned_account_id: uuid.UUID | None = None


@router.patch("/{incident_id}")
async def patch_incident(
    incident_id: uuid.UUID,
    payload: PatchPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_incidents_read),
):
    incident = await _visible_incident(db, scope, incident_id)
    await _require_incident_write(db, scope, incident.organization_id)

    changes: dict = {}
    before: dict = {}

    if payload.title is not None and payload.title != incident.title:
        before["title"] = incident.title
        incident.title = payload.title
        changes["title"] = payload.title
    if payload.description is not None and payload.description != incident.summary:
        before["summary"] = incident.summary
        incident.summary = payload.description
        changes["description"] = payload.description
    if payload.severity is not None:
        from app.models import EventSeverity

        try:
            severity = EventSeverity(payload.severity.lower())
        except ValueError:
            raise _err("invalid_severity", f"Unknown severity '{payload.severity}'.", 400)
        if severity != incident.severity:
            before["severity"] = incident.severity.value
            incident.severity = severity
            changes["severity"] = severity.value

    if (payload.assigned_account_type is None) != (payload.assigned_account_id is None):
        raise _err("assignee_fields_required", "Assign both assigned_account_type and assigned_account_id.", 400)
    if payload.assigned_account_type and payload.assigned_account_id:
        await _validate_assignee(db, incident.organization_id, payload.assigned_account_type, payload.assigned_account_id)
        if (
            incident.assigned_account_id != payload.assigned_account_id
            or incident.assigned_account_type != payload.assigned_account_type
        ):
            before["assigned_to"] = str(incident.assigned_account_id) if incident.assigned_account_id else None
            incident.assigned_account_type = payload.assigned_account_type
            incident.assigned_account_id = payload.assigned_account_id
            changes["assigned_to"] = str(payload.assigned_account_id)

    if not changes:
        return _row(incident)

    await _append_timeline(
        db,
        incident,
        entry_type="updated",
        description="Updated " + ", ".join(sorted(changes.keys())) + ".",
        scope=scope,
        metadata={"changes": changes},
    )
    await _audit(db, scope, incident, action="incident.update", before=before, after=changes)
    await db.commit()
    await db.refresh(incident)
    return _row(incident)


# ---------------------------------------------------------------------------
# Transition.
# ---------------------------------------------------------------------------


class TransitionPayload(BaseModel):
    status: str
    reason: str | None = None
    resolution_summary: str | None = None
    parent_incident_id: uuid.UUID | None = None


@router.post("/{incident_id}/transition")
async def transition_incident(
    incident_id: uuid.UUID,
    payload: TransitionPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_incidents_read),
):
    """The one state-change door. Payload requirements per target:
    CLOSED -> resolution_summary required; FALSE_POSITIVE -> reason;
    DUPLICATE -> reason + parent_incident_id (same org, not itself).
    The security_manager may request ESCALATED from any non-terminal
    state (their one write); everything else needs a writer."""
    incident = await _visible_incident(db, scope, incident_id)

    try:
        target = IncidentStatus[payload.status.lower()]
    except KeyError:
        raise _err("invalid_status", f"Unknown incident status '{payload.status}'.", 400)

    from_status = incident.status
    allowed = INCIDENT_TRANSITIONS.get(from_status, set())
    if target not in allowed:
        raise _err(
            "invalid_incident_transition",
            f"Cannot move an incident from '{from_status.value}' to '{target.value}'.",
            409,
            allowed,
        )

    # --- role checks ----------------------------------------------------
    # The security_manager's ONE write is the escalation request (their
    # own organization only -- visibility already proved that); every
    # other transition needs a full writer.
    is_security_manager = scope.role == UserRole.security_manager.value
    if not (is_security_manager and target == IncidentStatus.escalated):
        await _require_incident_write(db, scope, incident.organization_id)

    # --- payload requirements ------------------------------------------
    if target == IncidentStatus.closed:
        if not payload.resolution_summary or not payload.resolution_summary.strip():
            raise _err("resolution_summary_required", "Closing an incident requires a resolution summary.", 422)
    if target in (IncidentStatus.false_positive, IncidentStatus.duplicate):
        if not payload.reason or not payload.reason.strip():
            raise _err("closure_reason_required", f"Moving to {target.value} requires a reason.", 422)
    if target == IncidentStatus.duplicate:
        if payload.parent_incident_id is None:
            raise _err("duplicate_parent_required", "Marking a duplicate requires the parent incident id.", 422)
        if payload.parent_incident_id == incident.id:
            raise _err("duplicate_parent_invalid", "An incident cannot be its own duplicate parent.", 422)
        parent = (
            await db.execute(
                select(Incident).where(
                    Incident.id == payload.parent_incident_id,
                    Incident.organization_id == incident.organization_id,
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise _err("incident_not_found", "Parent incident not found.", 404)
        incident.duplicate_of_id = parent.id

    # --- apply ----------------------------------------------------------
    incident.status = target
    now = datetime.now(timezone.utc)
    if target in (IncidentStatus.resolved, IncidentStatus.false_positive, IncidentStatus.duplicate):
        incident.resolved_at = now
    if target == IncidentStatus.resolved:
        incident.resolution_summary = payload.resolution_summary or incident.resolution_summary
    if target == IncidentStatus.closed:
        incident.closed_at = now
        incident.resolution_summary = payload.resolution_summary.strip()
    if target in (IncidentStatus.false_positive, IncidentStatus.duplicate):
        incident.closure_reason = payload.reason.strip()
    if target == IncidentStatus.reopened:
        # Reopening clears the closure fields -- the incident is live again.
        incident.resolved_at = None
        incident.closed_at = None
        incident.closure_reason = None
        incident.duplicate_of_id = None

    # Alert status follows the incident: linked alerts become CONVERTED
    # when the incident is resolved or closed, DISMISSED (with the
    # incident's closure reason) when it is closed out as
    # FALSE_POSITIVE/DUPLICATE.
    if target in (IncidentStatus.resolved, IncidentStatus.closed):
        linked_alert_rows = (
            await db.execute(select(Alert).join(IncidentAlert, IncidentAlert.alert_id == Alert.id).where(IncidentAlert.incident_id == incident.id))
        ).scalars().all()
        for alert in linked_alert_rows:
            if alert.status != AlertStatus.converted:
                alert.status = AlertStatus.converted
    elif target in (IncidentStatus.false_positive, IncidentStatus.duplicate):
        linked_alert_rows = (
            await db.execute(select(Alert).join(IncidentAlert, IncidentAlert.alert_id == Alert.id).where(IncidentAlert.incident_id == incident.id))
        ).scalars().all()
        for alert in linked_alert_rows:
            if alert.status not in (AlertStatus.converted, AlertStatus.dismissed):
                status_before = alert.status
                alert.status = AlertStatus.dismissed
                alert.dismissed_reason = payload.reason.strip()
                _append_alert_history(
                    db,
                    alert,
                    organization_id=alert.organization_id,
                    action="dismiss",
                    scope=scope,
                    status_from=status_before,
                    detail={"reason": payload.reason.strip(), "via": "incident_transition"},
                )

    await _append_timeline(
        db,
        incident,
        entry_type="status_change",
        description=f"Status changed {from_status.value} -> {target.value}.",
        scope=scope,
        metadata={
            "status_from": from_status.value,
            "status_to": target.value,
            **({"reason": payload.reason} if payload.reason else {}),
            **({"resolution_summary": payload.resolution_summary} if payload.resolution_summary else {}),
            **({"parent_incident_id": str(payload.parent_incident_id)} if payload.parent_incident_id else {}),
        },
    )
    await _audit(
        db,
        scope,
        incident,
        action="incident.transition",
        before={"status": from_status.value},
        after={
            "status": target.value,
            **({"reason": payload.reason} if payload.reason else {}),
        },
    )
    await db.commit()
    await db.refresh(incident)
    return {
        "id": str(incident.id),
        "status": incident.status.value,
        "previous_status": from_status.value,
    }


# ---------------------------------------------------------------------------
# Links.
# ---------------------------------------------------------------------------


class LinkPayload(BaseModel):
    action: str = Field(pattern="^(add|remove)$")
    alert_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None


@router.post("/{incident_id}/links")
async def modify_links(
    incident_id: uuid.UUID,
    payload: LinkPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_incidents_read),
):
    """Add/remove one alert, event or asset link per call. Every linked
    row must belong to the incident's organization (404 otherwise)."""
    incident = await _visible_incident(db, scope, incident_id)
    await _require_incident_write(db, scope, incident.organization_id)

    named = [payload.alert_id, payload.event_id, payload.asset_id]
    if sum(1 for x in named if x is not None) != 1:
        raise _err("link_target_required", "Name exactly one of alert_id, event_id, asset_id.", 400)

    if payload.alert_id is not None:
        row = (
            await db.execute(select(Alert).where(Alert.id == payload.alert_id, Alert.organization_id == incident.organization_id))
        ).scalar_one_or_none()
        if row is None:
            raise _err("alert_not_found", "Alert not found.", 404)
        existing = (
            await db.execute(
                select(IncidentAlert).where(IncidentAlert.incident_id == incident.id, IncidentAlert.alert_id == row.id)
            )
        ).scalar_one_or_none()
        if payload.action == "add":
            if existing is None:
                db.add(IncidentAlert(incident_id=incident.id, alert_id=row.id))
                if row.status == AlertStatus.new:
                    row.status = AlertStatus.triaged
        elif existing is not None:
            await db.delete(existing)
        kind, target_id = "alert", row.id
    elif payload.event_id is not None:
        row = (
            await db.execute(
                select(SecurityEvent).where(
                    SecurityEvent.id == payload.event_id, SecurityEvent.organization_id == incident.organization_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise _err("event_not_found", "Event not found.", 404)
        existing = (
            await db.execute(
                select(IncidentEvent).where(IncidentEvent.incident_id == incident.id, IncidentEvent.event_id == row.id)
            )
        ).scalar_one_or_none()
        if payload.action == "add":
            if existing is None:
                db.add(IncidentEvent(incident_id=incident.id, event_id=row.id))
        elif existing is not None:
            await db.delete(existing)
        kind, target_id = "event", row.id
    else:
        row = (
            await db.execute(select(Asset).where(Asset.id == payload.asset_id, Asset.organization_id == incident.organization_id))
        ).scalar_one_or_none()
        if row is None:
            raise _err("asset_not_found", "Asset not found.", 404)
        existing = (
            await db.execute(
                select(IncidentAsset).where(IncidentAsset.incident_id == incident.id, IncidentAsset.asset_id == row.id)
            )
        ).scalar_one_or_none()
        if payload.action == "add":
            if existing is None:
                db.add(IncidentAsset(incident_id=incident.id, asset_id=row.id))
                if incident.primary_asset_id is None:
                    incident.primary_asset_id = row.id
        elif existing is not None:
            await db.delete(existing)
        kind, target_id = "asset", row.id

    await _append_timeline(
        db,
        incident,
        entry_type="link_change",
        description=f"{payload.action.capitalize()}ed {kind} link.",
        scope=scope,
        metadata={"action": payload.action, "kind": kind, "target_id": str(target_id)},
    )
    await _audit(
        db,
        scope,
        incident,
        action=f"incident.link_{payload.action}",
        after={"kind": kind, "target_id": str(target_id)},
    )
    await db.commit()
    return {"id": str(incident.id), "action": payload.action, "kind": kind, "target_id": str(target_id)}


# ---------------------------------------------------------------------------
# Merge duplicates.
# ---------------------------------------------------------------------------


class MergePayload(BaseModel):
    duplicate_incident_id: uuid.UUID


@router.post("/{incident_id}/merge")
async def merge_incident(
    incident_id: uuid.UUID,
    payload: MergePayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_incidents_read),
):
    """Merge ANOTHER incident into this one (the parent): the duplicate
    is marked DUPLICATE with reason + parent, and its alert/event/asset
    links move to the parent so no evidence is lost. The duplicate must
    be visible, same organization, not the parent itself, and not
    already terminal-duplicate."""
    incident = await _visible_incident(db, scope, incident_id)
    await _require_incident_write(db, scope, incident.organization_id)

    duplicate = (
        await db.execute(
            select(Incident).where(
                Incident.id == payload.duplicate_incident_id,
                Incident.organization_id == incident.organization_id,
            )
        )
    ).scalar_one_or_none()
    if duplicate is None:
        raise _err("incident_not_found", "Duplicate incident not found.", 404)
    if duplicate.id == incident.id:
        raise _err("duplicate_parent_invalid", "An incident cannot be merged into itself.", 422)
    if duplicate.status in (IncidentStatus.false_positive, IncidentStatus.duplicate):
        raise _err("incident_already_closed", "That incident is already closed as a duplicate or false positive.", 409)

    # Move the evidence links.
    for link in (
        await db.execute(select(IncidentAlert).where(IncidentAlert.incident_id == duplicate.id))
    ).scalars().all():
        existing = (
            await db.execute(
                select(IncidentAlert).where(IncidentAlert.incident_id == incident.id, IncidentAlert.alert_id == link.alert_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(IncidentAlert(incident_id=incident.id, alert_id=link.alert_id))
        await db.delete(link)
    for link in (
        await db.execute(select(IncidentEvent).where(IncidentEvent.incident_id == duplicate.id))
    ).scalars().all():
        existing = (
            await db.execute(
                select(IncidentEvent).where(IncidentEvent.incident_id == incident.id, IncidentEvent.event_id == link.event_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(IncidentEvent(incident_id=incident.id, event_id=link.event_id))
        await db.delete(link)
    for link in (
        await db.execute(select(IncidentAsset).where(IncidentAsset.incident_id == duplicate.id))
    ).scalars().all():
        existing = (
            await db.execute(
                select(IncidentAsset).where(IncidentAsset.incident_id == incident.id, IncidentAsset.asset_id == link.asset_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(IncidentAsset(incident_id=incident.id, asset_id=link.asset_id))
        await db.delete(link)

    duplicate.status = IncidentStatus.duplicate
    duplicate.closure_reason = f"Merged into {incident.id}"
    duplicate.duplicate_of_id = incident.id
    duplicate.resolved_at = datetime.now(timezone.utc)

    await _append_timeline(
        db,
        incident,
        entry_type="merged",
        description=f"Merged duplicate incident {duplicate.title}.",
        scope=scope,
        metadata={"duplicate_incident_id": str(duplicate.id)},
    )
    await _append_timeline(
        db,
        duplicate,
        entry_type="status_change",
        description=f"Marked DUPLICATE of {incident.title}; links moved to the parent.",
        scope=scope,
        metadata={"status_to": "DUPLICATE", "parent_incident_id": str(incident.id)},
    )
    await _audit(
        db,
        scope,
        incident,
        action="incident.merge",
        after={"duplicate_incident_id": str(duplicate.id)},
    )
    await db.commit()
    return {"id": str(incident.id), "merged": str(duplicate.id), "duplicate_status": duplicate.status.value}


# ---------------------------------------------------------------------------
# Comments.
# ---------------------------------------------------------------------------


class CommentPayload(BaseModel):
    body: str = Field(min_length=1)
    visibility: str = Field(default="internal", pattern="^(internal|shared)$")


@router.post("/{incident_id}/comments")
async def add_comment(
    incident_id: uuid.UUID,
    payload: CommentPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_incidents_read),
):
    """A timeline comment. `visibility: "internal"` = SOC-only note;
    "shared" = also readable by the organization (IT developers only
    ever see shared entries -- the detail endpoint filters internal rows
    out for callers without incidents-soc access, which the module gate
    already refuses; shared entries are what the IT-side view reads)."""
    incident = await _visible_incident(db, scope, incident_id)
    await _require_incident_write(db, scope, incident.organization_id)

    await _append_timeline(
        db,
        incident,
        entry_type="comment",
        description=payload.body,
        scope=scope,
        metadata={"visibility": payload.visibility, "comment": True},
    )
    await _audit(
        db,
        scope,
        incident,
        action="incident.comment",
        after={"visibility": payload.visibility},
    )
    await db.commit()
    return {"id": str(incident.id), "visibility": payload.visibility}
