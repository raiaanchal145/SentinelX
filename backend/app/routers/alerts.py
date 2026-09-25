"""
Alerts API (P10, docs/API_CONTRACT.md "Alerts").

GET   /api/v1/alerts                -- the SOC alert queue, filtered and
                                    cursor-paginated; visibility through
                                    soc_visible_organization_ids() (the
                                    events-router pattern: super_admin all,
                                    platform SOC assigned+managed+active,
                                    in-house org accounts their own org, a
                                    managed org's owner/security_manager
                                    read-only, everyone else 403).
GET   /api/v1/alerts/{id}           -- detail: supporting events, rule,
                                    correlation + grouped alerts, history.
POST  /api/v1/alerts/{id}/acknowledge | /assign | /dismiss | /reopen

Write access ("who may work the queue"): super_admin and platform SOC
analysts for their assigned managed organizations; an in-house
organization's soc_analyst (module `soc` write); the owner and
security_manager of an in-house organization via the module matrix. A
managed organization's own accounts are read-only at most -- state
changes are 403, platform SOC staff work those queues.

Every status change is validated against ALERT_TRANSITIONS (the one
place, tested), audited to audit_logs, and appended to alert_history.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_module, soc_visible_organization_ids
from app.audit import audit_from_scope
from app.database import get_db
from app.models import (
    ActorType,
    Admin,
    AdminLevel,
    Alert,
    AlertEvent,
    AlertHistory,
    AlertStatus,
    Correlation,
    CorrelationAlert,
    DetectionRule,
    EventSeverity,
    Organization,
    SecurityEvent,
    SocMode,
    SocOrganizationAssignment,
    User,
    UserRole,
)
from app.scope import Scope

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


# ---------------------------------------------------------------------------
# The transition map -- the ONE place status changes are validated.
# ---------------------------------------------------------------------------

ALERT_TRANSITIONS: dict[AlertStatus, set[AlertStatus]] = {
    AlertStatus.new: {AlertStatus.triaged, AlertStatus.dismissed},
    AlertStatus.triaged: {AlertStatus.investigating, AlertStatus.dismissed},
    AlertStatus.investigating: {AlertStatus.triaged, AlertStatus.dismissed, AlertStatus.converted},
    # dismissed/converted are terminal for the API; /reopen is the only
    # way out of dismissed (validated separately below).
    AlertStatus.dismissed: set(),
    AlertStatus.converted: set(),
}


def _validate_transition(current: AlertStatus, target: AlertStatus) -> None:
    allowed = ALERT_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise _err(
            "invalid_alert_transition",
            f"Cannot move an alert from '{current.value}' to '{target.value}'.",
            409,
        )


# ---------------------------------------------------------------------------
# Visibility + write-access matrix.
# ---------------------------------------------------------------------------


async def _alert_visibility(db: AsyncSession, scope: Scope) -> tuple[str, list[uuid.UUID] | None]:
    """
    Which alerts may this caller see (docs/API_CONTRACT.md "Alerts" --
    routing matrix), reusing soc_visible_organization_ids() plus the
    events router's mode convention:

      ("all", None)       super_admin.
      ("orgs", ids)       platform SOC: assigned managed+active orgs; an
                          in-house org's accounts (module `soc` read was
                          already enforced): their own org; a MANAGED
                          org's owner/security_manager: their own org,
                          READ-ONLY (write guards below refuse them --
                          platform SOC staff work that queue).
      ("empty", None)     a platform SOC analyst with zero assignments.
      ("forbidden", None) everyone else (managed org's non-privileged
                          accounts, no soc access at all): 403.
    """
    visible = await soc_visible_organization_ids(db, scope)
    if visible is None:
        return "all", None

    if scope.account_type == "admin" and scope.role == AdminLevel.organization_admin.value:
        return "orgs", [scope.organization_id]

    # The security_manager keeps soc read in BOTH modes (the role default
    # isn't soc-mode-gated), so in managed mode they still see their own
    # org's queue read-only -- requirement: "the owner and security
    # manager see read-only alert counts and details when
    # soc_mode = managed". Write access below still refuses them there.
    if scope.role == UserRole.security_manager.value and scope.organization_id is not None:
        return "orgs", [scope.organization_id]

    if visible:
        return "orgs", list(visible)

    if scope.role == AdminLevel.platform_soc_analyst.value:
        return "empty", None
    return "forbidden", None


async def _require_alert_write(db: AsyncSession, scope: Scope, organization_id: uuid.UUID) -> None:
    """Who may CHANGE an alert: super_admin; a platform SOC analyst for
    one of their assigned managed organizations; an in-house org's
    owner, security_manager (their own org only) and soc_analyst.
    A managed organization's own accounts (owner included) are
    read-only -- 403 alert_write_not_allowed."""
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
            raise _err("alert_not_found", "Alert not found.", 404)  # existence never leaked
        return
    if scope.account_type == "admin" or scope.role == UserRole.security_manager.value:
        # Owner or security manager: only their own org, only in-house.
        if scope.organization_id != organization_id:
            raise _err("alert_not_found", "Alert not found.", 404)

        org = await db.get(Organization, organization_id)
        if org is not None and org.soc_mode == SocMode.in_house:
            return
        raise _err(
            "alert_write_not_allowed",
            "This organization's SOC is managed by the platform; its own accounts cannot change alerts.",
            403,
        )
    if scope.role == UserRole.soc_analyst.value and scope.organization_id == organization_id:
        # An in-house org's own soc_analyst works their queue (the module
        # gate above only lets them through when soc_mode is in_house;
        # a managed org's analyst never even sees the queue).
        return
    raise _err(
        "alert_write_not_allowed",
        "You do not have permission to change alerts.",
        403,
    )


_require_soc_read = require_module("soc", write=False)


async def _organization_filter_scope(
    db: AsyncSession, scope: Scope, organization_id: uuid.UUID | None
) -> uuid.UUID | None:
    """The list endpoint's optional organization_id filter -- same rule
    as the events router: an id the caller cannot see is 404, never a
    leak."""
    if organization_id is None:
        return None
    mode, org_ids = await _alert_visibility(db, scope)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to alerts for this organization.", 403)
    if mode == "orgs" and organization_id not in (org_ids or []):
        raise _err("organization_not_found", "Organization not found.", 404)
    if mode == "all":
        exists = (
            await db.execute(select(Organization.id).where(Organization.id == organization_id))
        ).scalar_one_or_none()
        if exists is None:
            raise _err("organization_not_found", "Organization not found.", 404)
    return organization_id


# ---------------------------------------------------------------------------
# Row shaping.
# ---------------------------------------------------------------------------


def _row(alert: Alert, *, correlation_id: uuid.UUID | None = None) -> dict:
    return {
        "id": str(alert.id),
        "organization_id": str(alert.organization_id),
        "kind": alert.kind,
        "rule_id": str(alert.detection_rule_id) if alert.detection_rule_id else None,
        "rule_name": alert.rule_name,
        "asset_id": str(alert.asset_id) if alert.asset_id else None,
        "severity": alert.severity.value if hasattr(alert.severity, "value") else alert.severity,
        "status": alert.status.value if hasattr(alert.status, "value") else alert.status,
        "title": alert.title,
        "summary": alert.summary,
        "group_key": alert.group_key,
        "username": alert.username,
        "source_ip": alert.source_ip,
        "event_count": alert.event_count,
        "first_seen_at": alert.first_seen_at.isoformat() if alert.first_seen_at else None,
        "last_seen_at": alert.last_seen_at.isoformat() if alert.last_seen_at else None,
        "dismissed_reason": alert.dismissed_reason,
        "assigned_account_type": alert.assigned_account_type,
        "assigned_account_id": str(alert.assigned_account_id) if alert.assigned_account_id else None,
        "correlation_id": str(correlation_id) if correlation_id else None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }


# ---------------------------------------------------------------------------
# GET /alerts -- the queue.
# ---------------------------------------------------------------------------


@router.get("")
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
    status: str | None = None,
    severity: str | None = None,
    rule_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    assigned_to_me: bool = False,
    time_from: str | None = None,
    time_to: str | None = None,
    organization_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
):
    """The SOC alert queue. Filters: status, severity, rule, asset,
    assigned_to_me, time range on last_seen_at, plus organization_id for
    platform roles. Keyset pagination on (last_seen_at DESC, id DESC)."""
    mode, org_ids = await _alert_visibility(db, scope)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to alerts.", 403)
    if mode == "empty":
        return {"alerts": [], "next_cursor": None}

    effective_org = await _organization_filter_scope(db, scope, organization_id)

    stmt = select(Alert)
    if mode == "orgs":
        stmt = stmt.where(Alert.organization_id.in_(org_ids))
    if effective_org is not None:
        stmt = stmt.where(Alert.organization_id == effective_org)
    if status:
        try:
            stmt = stmt.where(Alert.status == AlertStatus(status))
        except ValueError:
            raise _err("invalid_status", f"Unknown alert status '{status}'.", 400)
    if severity:
        try:
            stmt = stmt.where(Alert.severity == EventSeverity(severity))
        except ValueError:
            raise _err("invalid_severity", f"Unknown severity '{severity}'.", 400)
    if rule_id:
        stmt = stmt.where(Alert.detection_rule_id == rule_id)
    if asset_id:
        stmt = stmt.where(Alert.asset_id == asset_id)
    if assigned_to_me:
        stmt = stmt.where(
            Alert.assigned_account_id == scope.user_id,
            Alert.assigned_account_type == scope.account_type,
        )
    if time_from:
        parsed = _parse_time(time_from, "time_from")
        stmt = stmt.where(Alert.last_seen_at >= parsed)
    if time_to:
        parsed = _parse_time(time_to, "time_to")
        stmt = stmt.where(Alert.last_seen_at <= parsed)
    if cursor:
        cursor_last_seen, cursor_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Alert.last_seen_at < cursor_last_seen,
                (Alert.last_seen_at == cursor_last_seen) & (Alert.id < cursor_id),
            )
        )

    stmt = stmt.order_by(Alert.last_seen_at.desc(), Alert.id.desc()).limit(limit + 1)
    rows = ((await db.execute(stmt)).scalars().all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.last_seen_at, last.id)

    # Batch the correlation pointer (an alert belongs to at most one
    # correlation in practice; take the newest).
    corr_map: dict[uuid.UUID, uuid.UUID] = {}
    if rows:
        links = (
            await db.execute(
                select(CorrelationAlert.alert_id, CorrelationAlert.correlation_id)
                .where(CorrelationAlert.alert_id.in_([a.id for a in rows]))
                .order_by(CorrelationAlert.correlation_id)
            )
        ).all()
        for alert_id, corr_id in links:
            corr_map[alert_id] = corr_id

    return {
        "alerts": [_row(a, correlation_id=corr_map.get(a.id)) for a in rows],
        "next_cursor": next_cursor,
    }


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        raise _err("invalid_time_range", f"Invalid ISO-8601 timestamp for {field}.", 400)


def _encode_cursor(last_seen: datetime, alert_id: uuid.UUID) -> str:
    import base64
    import json

    payload = json.dumps({"t": last_seen.isoformat(), "id": str(alert_id)})
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
# GET /alerts/{id} -- detail.
# ---------------------------------------------------------------------------


async def _visible_alert(db: AsyncSession, scope: Scope, alert_id: uuid.UUID) -> Alert:
    """The alert if the caller may see it, else 404 (existence never
    leaked across the visibility boundary)."""
    mode, org_ids = await _alert_visibility(db, scope)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to alerts.", 403)
    if mode == "empty":
        raise _err("alert_not_found", "Alert not found.", 404)

    stmt = select(Alert).where(Alert.id == alert_id)
    if mode == "orgs":
        stmt = stmt.where(Alert.organization_id.in_(org_ids))
    alert = (await db.execute(stmt)).scalar_one_or_none()
    if alert is None:
        raise _err("alert_not_found", "Alert not found.", 404)
    return alert


@router.get("/{alert_id}")
async def get_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
):
    """Detail: the alert, its supporting events (id/type/user/ip/time/
    message), the detection rule, any correlation (with reasoning and
    the grouped alerts), and the alert's own history timeline."""
    alert = await _visible_alert(db, scope, alert_id)

    event_rows = (
        await db.execute(
            select(AlertEvent, SecurityEvent)
            .join(SecurityEvent, SecurityEvent.id == AlertEvent.event_id)
            .where(AlertEvent.alert_id == alert.id)
            .order_by(AlertEvent.occurred_at, SecurityEvent.id)
            .limit(200)
        )
    ).all()

    rule = None
    if alert.detection_rule_id:
        rule = await db.get(DetectionRule, alert.detection_rule_id)

    if alert.kind == "correlation":
        # The correlated alert IS the correlation's own alert (their
        # dedup keys match); correlation_alerts links the grouped
        # UNDERLYING alerts, not this one.
        correlation = (
            await db.execute(
                select(Correlation).where(
                    Correlation.organization_id == alert.organization_id,
                    Correlation.dedup_key == alert.dedup_key,
                )
            )
        ).scalar_one_or_none()
    else:
        # A detection alert: find the correlation that grouped it, if any.
        correlation = (
            await db.execute(
                select(Correlation)
                .join(CorrelationAlert, CorrelationAlert.correlation_id == Correlation.id)
                .where(CorrelationAlert.alert_id == alert.id)
                .order_by(Correlation.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    grouped: list[Alert] = []
    if correlation is not None:
        grouped = (
            (
                await db.execute(
                    select(Alert)
                    .join(CorrelationAlert, CorrelationAlert.alert_id == Alert.id)
                    .where(CorrelationAlert.correlation_id == correlation.id)
                    .order_by(Alert.first_seen_at)
                )
            )
            .scalars()
            .all()
        )

    history = (
        (
            await db.execute(
                select(AlertHistory)
                .where(AlertHistory.alert_id == alert.id)
                .order_by(AlertHistory.created_at, AlertHistory.id)
            )
        )
        .scalars()
        .all()
    )

    return {
        "alert": _row(alert, correlation_id=correlation.id if correlation else None),
        "rule": (
            {
                "id": str(rule.id),
                "name": rule.name,
                "description": rule.description,
                "severity": rule.severity.value if hasattr(rule.severity, "value") else rule.severity,
                "mitre_technique": rule.mitre_technique,
            }
            if rule
            else None
        ),
        "events": [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "username": event.username,
                "source_ip": event.source_ip,
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                "message": (event.normalized_data or {}).get("message"),
            }
            for _, event in event_rows
        ],
        "correlation": (
            {
                "id": str(correlation.id),
                "title": correlation.title,
                "severity": correlation.severity.value if hasattr(correlation.severity, "value") else correlation.severity,
                "reasoning": correlation.reasoning,
                "first_seen_at": correlation.first_seen_at.isoformat() if correlation.first_seen_at else None,
                "last_seen_at": correlation.last_seen_at.isoformat() if correlation.last_seen_at else None,
                "event_count": correlation.event_count,
                "grouped_alerts": [_row(a) for a in grouped],
            }
            if correlation
            else None
        ),
        "history": [
            {
                "action": h.action,
                "actor_type": h.actor_type.value if hasattr(h.actor_type, "value") else h.actor_type,
                "actor_id": str(h.actor_id) if h.actor_id else None,
                "status_from": h.status_from.value if h.status_from else None,
                "status_to": h.status_to.value if h.status_to else None,
                "detail": h.detail,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in history
        ],
    }


# ---------------------------------------------------------------------------
# Write endpoints.
# ---------------------------------------------------------------------------


class AcknowledgePayload(BaseModel):
    pass


class AssignPayload(BaseModel):
    account_type: str = Field(pattern="^(admin|user)$")
    account_id: uuid.UUID


class DismissPayload(BaseModel):
    reason: str = Field(min_length=1)


async def _append_history_and_audit(
    db: AsyncSession,
    scope: Scope,
    alert: Alert,
    *,
    action: str,
    status_from: AlertStatus,
    status_to: AlertStatus | None,
    detail: dict | None,
    organization_id: uuid.UUID | None = None,
) -> None:
    """One history row + one audit_logs row per change, in the caller's
    transaction. status_from must be captured by the caller BEFORE it
    mutates alert.status -- the whole point of the column."""
    db.add(
        AlertHistory(
            alert_id=alert.id,
            organization_id=organization_id or alert.organization_id,
            action=action,
            actor_type=ActorType.admin if scope.account_type == "admin" else ActorType.user,
            actor_id=scope.user_id,
            status_from=status_from,
            status_to=status_to or alert.status,
            detail=detail,
        )
    )
    await audit_from_scope(
        db,
        scope,
        f"alert.{action}",
        organization_id=organization_id,
        target_type="alert",
        target_id=alert.id,
        before={"status": alert.status.value},
        after={"status": (status_to or alert.status).value, **(detail or {})},
    )


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
):
    """new -> triaged ONLY (the transition map is the single source of
    truth; anything else is 409)."""
    alert = await _visible_alert(db, scope, alert_id)
    await _require_alert_write(db, scope, alert.organization_id)

    _validate_transition(alert.status, AlertStatus.triaged)
    from_status = alert.status
    alert.status = AlertStatus.triaged
    await _append_history_and_audit(
        db,
        scope,
        alert,
        action="acknowledge",
        status_from=from_status,
        status_to=AlertStatus.triaged,
        detail={},
        organization_id=alert.organization_id,
    )
    await db.commit()
    await db.refresh(alert)
    return {"id": str(alert.id), "status": alert.status.value, "previous_status": from_status.value}


@router.post("/{alert_id}/assign")
async def assign_alert(
    alert_id: uuid.UUID,
    payload: AssignPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
):
    """Assign to a user in scope. Who may be assigned:
    - an in-house org's queue: that org's own soc_analyst users
      (owner/security_manager assigning among their analysts);
    - a platform-SOC-worked queue: a platform SOC analyst assigned to
      that organization, to another platform SOC analyst of it.
    Invalid targets are 422 assignee_not_in_scope."""
    alert = await _visible_alert(db, scope, alert_id)
    await _require_alert_write(db, scope, alert.organization_id)

    assignee = await _validate_assignee(db, alert.organization_id, payload.account_type, payload.account_id)

    previous = (
        str(alert.assigned_account_id) if alert.assigned_account_id else None,
        alert.assigned_account_type,
    )
    alert.assigned_account_type = payload.account_type
    alert.assigned_account_id = payload.account_id
    await _append_history_and_audit(
        db,
        scope,
        alert,
        action="assign",
        status_from=alert.status,
        status_to=None,
        detail={"assigned_to": str(payload.account_id), "assigned_account_type": payload.account_type},
        organization_id=alert.organization_id,
    )
    await db.commit()
    await db.refresh(alert)
    return {
        "id": str(alert.id),
        "assigned_account_type": alert.assigned_account_type,
        "assigned_account_id": str(alert.assigned_account_id),
        "previous_assigned_account_id": previous[0],
    }


async def _validate_assignee(
    db: AsyncSession, organization_id: uuid.UUID, account_type: str, account_id: uuid.UUID
) -> None:
    """The assignee must actually belong to the queue being worked: an
    in-house org -> that org's soc_analyst users; a managed org ->
    platform SOC analysts assigned to it. Anything else is
    422 assignee_not_in_scope (after 404 on a nonexistent account)."""
    org = await db.get(Organization, organization_id)
    if org is None:
        raise _err("alert_not_found", "Alert not found.", 404)

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
            "Alerts can only be assigned to this organization's own soc_analyst users.",
            422,
        )


@router.post("/{alert_id}/dismiss")
async def dismiss_alert(
    alert_id: uuid.UUID,
    payload: DismissPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
):
    """Mark false positive; the reason is REQUIRED (422 without one) and
    stored on the alert and in history/audit."""
    alert = await _visible_alert(db, scope, alert_id)
    await _require_alert_write(db, scope, alert.organization_id)

    _validate_transition(alert.status, AlertStatus.dismissed)
    from_status = alert.status
    alert.status = AlertStatus.dismissed
    alert.dismissed_reason = payload.reason
    await _append_history_and_audit(
        db,
        scope,
        alert,
        action="dismiss",
        status_from=from_status,
        status_to=AlertStatus.dismissed,
        detail={"reason": payload.reason},
        organization_id=alert.organization_id,
    )
    await db.commit()
    await db.refresh(alert)
    return {
        "id": str(alert.id),
        "status": alert.status.value,
        "dismissed_reason": alert.dismissed_reason,
        "previous_status": from_status.value,
    }


@router.post("/{alert_id}/reopen")
async def reopen_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
):
    """The only way out of dismissed: back to new (triage starts over).
    Reopening clears the dismissal reason -- the alert is no longer
    considered a false positive."""
    alert = await _visible_alert(db, scope, alert_id)
    await _require_alert_write(db, scope, alert.organization_id)

    if alert.status != AlertStatus.dismissed:
        raise _err(
            "invalid_alert_transition",
            "Only a dismissed alert can be reopened.",
            409,
        )
    from_status = alert.status
    alert.status = AlertStatus.new
    alert.dismissed_reason = None
    await _append_history_and_audit(
        db,
        scope,
        alert,
        action="reopen",
        status_from=from_status,
        status_to=AlertStatus.new,
        detail={},
        organization_id=alert.organization_id,
    )
    await db.commit()
    await db.refresh(alert)
    return {"id": str(alert.id), "status": alert.status.value, "previous_status": from_status.value}
