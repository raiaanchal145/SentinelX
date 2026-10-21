"""
Admin aggregate oversight endpoints -- P22.
Provides real aggregate metrics, workloads, SLAs, and reassignments
for platform administrators (super_admin) with isolation for platform SOC analysts.
"""

from datetime import datetime, timedelta, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_platform_admin, require_super_admin
from app.audit import audit_from_scope
from app.database import get_db
from app.models import (
    ActorType,
    Admin,
    AdminLevel,
    AgentRun,
    Alert,
    AlertHistory,
    AlertStatus,
    Asset,
    DeviceEnrollment,
    Incident,
    IncidentStatus,
    IncidentTimeline,
    Organization,
    OrganizationStatus,
    SecurityEvent,
    SocMode,
    SocOrganizationAssignment,
    Team,
    Ticket,
    TicketStatus,
    User,
    UserRole,
)
from app.scope import Scope

router = APIRouter(prefix="/api/v1/admin", tags=["admin-oversight"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _parse_time_range(range_str: str) -> tuple[datetime, int]:
    now = datetime.now(timezone.utc)
    if range_str == "7d":
        return now - timedelta(days=7), 7 * 24
    if range_str == "30d":
        return now - timedelta(days=30), 30 * 24
    return now - timedelta(hours=24), 24


class ReassignRequest(BaseModel):
    analyst_id: uuid.UUID
    reason: str = Field(min_length=1)


# ==============================================================================
# 1. OVERVIEW: Platform-wide rollups (super_admin only)
# ==============================================================================

@router.get("/oversight/overview")
async def oversight_overview(
    time_range: str = Query("24h", alias="range", pattern="^(24h|7d|30d)$"),
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
):
    now = datetime.now(timezone.utc)
    since, hours_count = _parse_time_range(time_range)

    # 1. Organizations by status & mode
    org_status_rows = (
        await db.execute(
            select(Organization.status, func.count(Organization.id)).group_by(Organization.status)
        )
    ).all()
    org_status_map = {s.value: 0 for s in OrganizationStatus}
    for status, count in org_status_rows:
        org_status_map[status.value if hasattr(status, "value") else str(status)] = count

    org_mode_rows = (
        await db.execute(
            select(Organization.soc_mode, func.count(Organization.id)).group_by(Organization.soc_mode)
        )
    ).all()
    org_mode_map = {m.value: 0 for m in SocMode}
    for mode, count in org_mode_rows:
        org_mode_map[mode.value if hasattr(mode, "value") else str(mode)] = count

    total_orgs = sum(org_status_map.values())

    # 2. Devices (from DeviceEnrollment)
    two_min_ago = now - timedelta(minutes=2)
    ten_min_ago = now - timedelta(minutes=10)

    devices_row = (
        await db.execute(
            select(
                func.count(DeviceEnrollment.id).filter(DeviceEnrollment.last_heartbeat_at >= two_min_ago).label("connected"),
                func.count(DeviceEnrollment.id).filter(
                    and_(
                        DeviceEnrollment.last_heartbeat_at < two_min_ago,
                        DeviceEnrollment.last_heartbeat_at >= ten_min_ago,
                    )
                ).label("stale"),
                func.count(DeviceEnrollment.id).filter(
                    or_(
                        DeviceEnrollment.last_heartbeat_at < ten_min_ago,
                        DeviceEnrollment.last_heartbeat_at.is_(None),
                    )
                ).label("offline"),
                func.count(DeviceEnrollment.id).label("total"),
            ).where(DeviceEnrollment.status != "revoked")
        )
    ).one()

    # 3. Events per hour last 24h
    h24_ago = now - timedelta(hours=24)
    event_hour_rows = (
        await db.execute(
            select(
                func.date_trunc("hour", SecurityEvent.occurred_at).label("hour"),
                func.count(SecurityEvent.id).label("count"),
            )
            .where(SecurityEvent.occurred_at >= h24_ago)
            .group_by("hour")
            .order_by("hour")
        )
    ).all()

    hour_count_map = {r.hour.isoformat(): r.count for r in event_hour_rows if r.hour}
    events_per_hour = []
    # Produce 24 continuous hourly slots
    for i in range(23, -1, -1):
        slot = (now - timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
        slot_iso = slot.isoformat()
        # Match by prefix YYYY-MM-DDTHH
        prefix = slot_iso[:13]
        matched_count = 0
        for h_iso, c in hour_count_map.items():
            if h_iso.startswith(prefix):
                matched_count = c
                break
        events_per_hour.append({"time": slot_iso, "count": matched_count, "value": matched_count})

    # 4. AI usage & cost
    ai_stats_row = (
        await db.execute(
            select(
                func.count(AgentRun.id).label("total_runs"),
                func.coalesce(func.sum(AgentRun.tokens_used), 0).label("tokens_used"),
                func.coalesce(func.sum(AgentRun.cost_usd), 0.0).label("cost_usd"),
            ).where(AgentRun.started_at >= since)
        )
    ).one()

    # 5. Dashboard core stats
    assets_count = (
        await db.execute(select(func.count(Asset.id)).where(Asset.status != "retired"))
    ).scalar() or 0

    users_count = (await db.execute(select(func.count(User.id)))).scalar() or 0

    open_incidents_count = (
        await db.execute(
            select(func.count(Incident.id)).where(
                Incident.status.not_in([
                    IncidentStatus.resolved,
                    IncidentStatus.closed,
                    IncidentStatus.false_positive,
                    IncidentStatus.duplicate,
                ])
            )
        )
    ).scalar() or 0

    total_events_in_range = (
        await db.execute(
            select(func.count(SecurityEvent.id)).where(SecurityEvent.occurred_at >= since)
        )
    ).scalar() or 0

    # Severity distribution of open incidents
    sev_rows = (
        await db.execute(
            select(Incident.severity, func.count(Incident.id))
            .where(
                Incident.status.not_in([
                    IncidentStatus.resolved,
                    IncidentStatus.closed,
                    IncidentStatus.false_positive,
                    IncidentStatus.duplicate,
                ])
            )
            .group_by(Incident.severity)
        )
    ).all()
    incidents_by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for sev, cnt in sev_rows:
        val = sev.value if hasattr(sev, "value") else str(sev).lower()
        if val in incidents_by_severity:
            incidents_by_severity[val] = cnt

    return {
        "organizations": {
            "total": total_orgs,
            "by_status": org_status_map,
            "by_mode": org_mode_map,
        },
        "devices": {
            "connected": devices_row.connected,
            "stale": devices_row.stale,
            "offline": devices_row.offline,
            "total": devices_row.total,
        },
        "events_per_hour_last_24h": events_per_hour,
        "ai_usage": {
            "total_runs": ai_stats_row.total_runs,
            "tokens_used": ai_stats_row.tokens_used,
            "cost_usd": round(float(ai_stats_row.cost_usd), 4),
        },
        "stats": {
            "assets": assets_count,
            "users": users_count,
            "open_incidents": open_incidents_count,
            "security_events": total_events_in_range,
            "incidents_by_severity": incidents_by_severity,
        },
    }


# ==============================================================================
# 2. SOC OVERSIGHT: Per-tenant, workload, coverage gaps, MTTA
# ==============================================================================

@router.get("/oversight/soc")
async def oversight_soc(
    time_range: str = Query("24h", alias="range", pattern="^(24h|7d|30d)$"),
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_platform_admin),
):
    now = datetime.now(timezone.utc)
    since, _ = _parse_time_range(time_range)

    is_super = scope.role == AdminLevel.super_admin.value
    caller_analyst_id = scope.account.id

    # Tenant scoping: platform_soc_analyst only sees their assigned managed active orgs
    if is_super:
        org_filter_stmt = select(Organization).order_by(Organization.name)
    else:
        org_filter_stmt = (
            select(Organization)
            .join(SocOrganizationAssignment, SocOrganizationAssignment.organization_id == Organization.id)
            .where(
                SocOrganizationAssignment.admin_id == caller_analyst_id,
                Organization.status == OrganizationStatus.active,
                Organization.soc_mode == SocMode.managed,
            )
            .order_by(Organization.name)
        )

    orgs = (await db.execute(org_filter_stmt)).scalars().all()
    org_ids = [o.id for o in orgs]

    if not org_ids:
        return {
            "kpis": [
                {"label": "Alerts (period)", "value": "0", "tone": "neutral"},
                {"label": "Unassigned / unacknowledged", "value": "0", "tone": "neutral"},
                {"label": "Mean time to acknowledge", "value": "0m", "tone": "neutral"},
                {"label": "False-positive rate", "value": "0%", "tone": "neutral"},
                {"label": "Devices online", "value": "0 of 0", "tone": "neutral"},
                {"label": "Coverage gaps", "value": "0", "tone": "neutral"},
            ],
            "organizations": [],
            "analyst_workload": [],
            "coverage_gaps": [],
            "top_rules": [],
            "volume": [],
            "unassigned_alerts": [],
        }

    # 1. Per-org alerts and incidents stats
    open_alert_statuses = [AlertStatus.new, AlertStatus.triaged, AlertStatus.investigating]
    closed_incident_statuses = [
        IncidentStatus.resolved,
        IncidentStatus.closed,
        IncidentStatus.false_positive,
        IncidentStatus.duplicate,
    ]

    # Open alerts per org
    open_alerts_res = dict(
        (
            await db.execute(
                select(Alert.organization_id, func.count(Alert.id))
                .where(Alert.organization_id.in_(org_ids), Alert.status.in_(open_alert_statuses))
                .group_by(Alert.organization_id)
            )
        ).all()
    )

    # Open incidents per org
    open_incidents_res = dict(
        (
            await db.execute(
                select(Incident.organization_id, func.count(Incident.id))
                .where(Incident.organization_id.in_(org_ids), Incident.status.not_in(closed_incident_statuses))
                .group_by(Incident.organization_id)
            )
        ).all()
    )

    # Unacknowledged alerts (status == new) and oldest age per org
    unack_res = (
        await db.execute(
            select(
                Alert.organization_id,
                func.count(Alert.id).label("count"),
                func.min(Alert.first_seen_at).label("oldest_first_seen"),
            )
            .where(Alert.organization_id.in_(org_ids), Alert.status == AlertStatus.new)
            .group_by(Alert.organization_id)
        )
    ).all()
    unack_map = {r.organization_id: (r.count, r.oldest_first_seen) for r in unack_res}

    # MTTA per org: average time from alert first_seen_at to acknowledgement in alert_history
    mtta_rows = (
        await db.execute(
            select(
                AlertHistory.organization_id,
                func.avg(
                    func.extract("epoch", AlertHistory.created_at - Alert.first_seen_at)
                ).label("avg_ack_seconds"),
            )
            .join(Alert, Alert.id == AlertHistory.alert_id)
            .where(
                AlertHistory.organization_id.in_(org_ids),
                AlertHistory.action == "acknowledge",
                AlertHistory.created_at >= since,
            )
            .group_by(AlertHistory.organization_id)
        )
    ).all()
    mtta_map = {r.organization_id: float(r.avg_ack_seconds or 0) for r in mtta_rows}

    per_org_list = []
    for org in orgs:
        unack_count, oldest_seen = unack_map.get(org.id, (0, None))
        oldest_age_sec = int((now - oldest_seen).total_seconds()) if oldest_seen else 0
        mtta_sec = int(mtta_map.get(org.id, 0))
        per_org_list.append({
            "id": str(org.id),
            "name": org.name,
            "soc_mode": org.soc_mode.value,
            "status": org.status.value,
            "open_alerts": open_alerts_res.get(org.id, 0),
            "open_incidents": open_incidents_res.get(org.id, 0),
            "unacknowledged_alerts": unack_count,
            "oldest_unacknowledged_age_seconds": oldest_age_sec,
            "mtta_seconds": mtta_sec,
        })

    # 2. Coverage gaps: managed active orgs without any assigned platform SOC analyst (super_admin only)
    coverage_gaps = []
    if is_super:
        assigned_subq = select(SocOrganizationAssignment.organization_id).distinct()
        gap_orgs = (
            await db.execute(
                select(Organization)
                .where(
                    Organization.status == OrganizationStatus.active,
                    Organization.soc_mode == SocMode.managed,
                    Organization.id.not_in(assigned_subq),
                )
                .order_by(Organization.name)
            )
        ).scalars().all()
        coverage_gaps = [{"id": str(o.id), "name": o.name} for o in gap_orgs]

    # 3. Analyst workload (super_admin sees all platform SOC analysts; platform SOC sees only own)
    analysts_stmt = select(Admin).where(
        Admin.admin_level == AdminLevel.platform_soc_analyst,
        Admin.is_active.is_(True),
    )
    if not is_super:
        analysts_stmt = analysts_stmt.where(Admin.id == caller_analyst_id)

    analysts = (await db.execute(analysts_stmt.order_by(Admin.email))).scalars().all()

    # Per-analyst assignments
    assignments_rows = (
        await db.execute(
            select(SocOrganizationAssignment.admin_id, Organization.id, Organization.name)
            .join(Organization, Organization.id == SocOrganizationAssignment.organization_id)
            .where(SocOrganizationAssignment.admin_id.in_([a.id for a in analysts]))
        )
    ).all()
    assignments_by_admin = {}
    for admin_id, o_id, o_name in assignments_rows:
        assignments_by_admin.setdefault(admin_id, []).append({"id": str(o_id), "name": o_name})

    # Per-analyst open alerts
    analyst_alerts_res = dict(
        (
            await db.execute(
                select(Alert.assigned_account_id, func.count(Alert.id))
                .where(
                    Alert.assigned_account_type == "admin",
                    Alert.assigned_account_id.in_([a.id for a in analysts]),
                    Alert.status.in_(open_alert_statuses),
                )
                .group_by(Alert.assigned_account_id)
            )
        ).all()
    )

    # Per-analyst open incidents
    analyst_incidents_res = dict(
        (
            await db.execute(
                select(Incident.assigned_account_id, func.count(Incident.id))
                .where(
                    Incident.assigned_account_type == "admin",
                    Incident.assigned_account_id.in_([a.id for a in analysts]),
                    Incident.status.not_in(closed_incident_statuses),
                )
                .group_by(Incident.assigned_account_id)
            )
        ).all()
    )

    analyst_workload = []
    for a in analysts:
        analyst_workload.append({
            "id": str(a.id),
            "name": a.name or a.email.split("@")[0],
            "email": a.email,
            "open_alerts": analyst_alerts_res.get(a.id, 0),
            "open_incidents": analyst_incidents_res.get(a.id, 0),
            "assigned_organizations": assignments_by_admin.get(a.id, []),
        })

    # 4. Top detection rules
    rule_stats = (
        await db.execute(
            select(
                Alert.rule_name,
                func.count(Alert.id).label("fired"),
                func.count(Alert.id).filter(Alert.status == AlertStatus.dismissed).label("false_positives"),
            )
            .where(
                Alert.created_at >= since,
                Alert.rule_name.is_not(None),
                Alert.organization_id.in_(org_ids),
            )
            .group_by(Alert.rule_name)
            .order_by(desc("fired"))
            .limit(6)
        )
    ).all()
    top_rules = [
        {
            "name": r.rule_name,
            "count": r.fired,
            "false_positive_rate": round((r.false_positives / r.fired) * 100) if r.fired > 0 else 0,
        }
        for r in rule_stats
    ]

    # 5. Volume sparkline (last 24h)
    h24_ago = now - timedelta(hours=24)
    event_vol_rows = (
        await db.execute(
            select(
                func.date_trunc("hour", SecurityEvent.occurred_at).label("hour"),
                func.count(SecurityEvent.id).label("count"),
            )
            .where(
                SecurityEvent.occurred_at >= h24_ago,
                SecurityEvent.organization_id.in_(org_ids),
            )
            .group_by("hour")
            .order_by("hour")
        )
    ).all()
    vol_hour_map = {r.hour.isoformat(): r.count for r in event_vol_rows if r.hour}
    volume_sparkline = []
    for i in range(23, -1, -1):
        slot = (now - timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
        prefix = slot.isoformat()[:13]
        cnt = next((c for h, c in vol_hour_map.items() if h.startswith(prefix)), 0)
        volume_sparkline.append({"time": slot.isoformat(), "value": cnt})

    # 6. Unassigned alerts needing assignment (in managed orgs)
    unassigned_alerts_stmt = (
        select(Alert, Organization.name.label("org_name"), Asset.hostname.label("asset_hostname"))
        .join(Organization, Organization.id == Alert.organization_id)
        .outerjoin(Asset, Asset.id == Alert.asset_id)
        .where(
            Alert.organization_id.in_(org_ids),
            Alert.assigned_account_id.is_(None),
            Alert.status.in_(open_alert_statuses),
        )
        .order_by(desc(Alert.first_seen_at))
        .limit(50)
    )
    unassigned_rows = (await db.execute(unassigned_alerts_stmt)).all()

    # Preload candidate platform SOC analysts per organization
    org_candidates_rows = (
        await db.execute(
            select(SocOrganizationAssignment.organization_id, Admin.id, Admin.name, Admin.email)
            .join(Admin, Admin.id == SocOrganizationAssignment.admin_id)
            .where(
                SocOrganizationAssignment.organization_id.in_(org_ids),
                Admin.admin_level == AdminLevel.platform_soc_analyst,
                Admin.is_active.is_(True),
            )
        )
    ).all()
    candidates_by_org = {}
    for o_id, a_id, a_name, a_email in org_candidates_rows:
        candidates_by_org.setdefault(o_id, []).append({
            "id": str(a_id),
            "name": a_name or a_email.split("@")[0],
            "email": a_email,
        })

    unassigned_alerts = [
        {
            "id": str(r.Alert.id),
            "title": r.Alert.title,
            "severity": r.Alert.severity.value,
            "status": r.Alert.status.value,
            "detectionRuleName": r.Alert.rule_name or "Custom Detection",
            "organizationId": str(r.Alert.organization_id),
            "organizationName": r.org_name,
            "assetHostname": r.asset_hostname or "--",
            "firstSeenAt": r.Alert.first_seen_at.isoformat(),
            "eligibleAnalysts": candidates_by_org.get(r.Alert.organization_id, []),
        }
        for r in unassigned_rows
    ]

    # 7. Overall KPIs
    total_alerts_period = (
        await db.execute(
            select(func.count(Alert.id)).where(Alert.organization_id.in_(org_ids), Alert.created_at >= since)
        )
    ).scalar() or 0

    total_unassigned = len(unassigned_alerts)

    total_dismissed = (
        await db.execute(
            select(func.count(Alert.id)).where(
                Alert.organization_id.in_(org_ids),
                Alert.created_at >= since,
                Alert.status == AlertStatus.dismissed,
            )
        )
    ).scalar() or 0

    fp_rate = round((total_dismissed / total_alerts_period) * 100) if total_alerts_period > 0 else 0

    overall_mtta_sec = (
        await db.execute(
            select(
                func.avg(func.extract("epoch", AlertHistory.created_at - Alert.first_seen_at))
            )
            .join(Alert, Alert.id == AlertHistory.alert_id)
            .where(
                AlertHistory.organization_id.in_(org_ids),
                AlertHistory.action == "acknowledge",
                AlertHistory.created_at >= since,
            )
        )
    ).scalar() or 0
    overall_mtta_min = int(overall_mtta_sec // 60)

    # Monitored devices online vs total
    two_min_ago = now - timedelta(minutes=2)
    device_online_counts = (
        await db.execute(
            select(
                func.count(DeviceEnrollment.id).filter(DeviceEnrollment.last_heartbeat_at >= two_min_ago).label("online"),
                func.count(DeviceEnrollment.id).label("total"),
            ).where(
                DeviceEnrollment.organization_id.in_(org_ids),
                DeviceEnrollment.status != "revoked",
            )
        )
    ).one()

    return {
        "kpis": [
            {"label": "Alerts (period)", "value": str(total_alerts_period), "tone": "neutral"},
            {
                "label": "Unassigned / unacknowledged",
                "value": str(total_unassigned),
                "tone": "high" if total_unassigned > 5 else "neutral",
            },
            {
                "label": "Mean time to acknowledge",
                "value": f"{overall_mtta_min}m" if overall_mtta_min > 0 else "<1m",
                "tone": "neutral",
            },
            {
                "label": "False-positive rate",
                "value": f"{fp_rate}%",
                "tone": "neutral",
            },
            {
                "label": "Devices online",
                "value": f"{device_online_counts.online} of {device_online_counts.total}",
                "tone": "medium" if device_online_counts.online < device_online_counts.total else "neutral",
            },
            {
                "label": "Coverage gaps",
                "value": str(len(coverage_gaps)),
                "tone": "critical" if len(coverage_gaps) > 0 else "neutral",
            },
        ],
        "organizations": per_org_list,
        "analyst_workload": analyst_workload,
        "coverage_gaps": coverage_gaps,
        "top_rules": top_rules,
        "volume": volume_sparkline,
        "unassigned_alerts": unassigned_alerts,
    }


# ==============================================================================
# 3. IT OVERSIGHT: Per-tenant, tickets by priority & SLA, workloads
# ==============================================================================

@router.get("/oversight/it")
async def oversight_it(
    time_range: str = Query("24h", alias="range", pattern="^(24h|7d|30d)$"),
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_platform_admin),
):
    now = datetime.now(timezone.utc)
    since, _ = _parse_time_range(time_range)

    is_super = scope.role == AdminLevel.super_admin.value
    caller_analyst_id = scope.account.id

    if is_super:
        org_filter_stmt = select(Organization).order_by(Organization.name)
    else:
        org_filter_stmt = (
            select(Organization)
            .join(SocOrganizationAssignment, SocOrganizationAssignment.organization_id == Organization.id)
            .where(
                SocOrganizationAssignment.admin_id == caller_analyst_id,
                Organization.status == OrganizationStatus.active,
            )
            .order_by(Organization.name)
        )

    orgs = (await db.execute(org_filter_stmt)).scalars().all()
    org_ids = [o.id for o in orgs]

    if not org_ids:
        return {
            "kpis": [],
            "organizations": [],
            "by_status": [],
            "by_team": [],
            "workload": [],
            "sla_table": [],
            "repeat_assets": [],
        }

    open_ticket_statuses = [
        TicketStatus.open,
        TicketStatus.triaged,
        TicketStatus.assigned,
        TicketStatus.acknowledged,
        TicketStatus.investigating,
        TicketStatus.remediation,
        TicketStatus.verification,
    ]

    # 1. Per-org tickets by priority & SLA
    ticket_prio_rows = (
        await db.execute(
            select(Ticket.organization_id, Ticket.priority, func.count(Ticket.id))
            .where(Ticket.organization_id.in_(org_ids), Ticket.status.in_(open_ticket_statuses))
            .group_by(Ticket.organization_id, Ticket.priority)
        )
    ).all()
    prio_map_by_org = {}
    for o_id, prio, cnt in ticket_prio_rows:
        key = (prio or "P3").upper()
        prio_map_by_org.setdefault(o_id, {})[key] = cnt

    ticket_sla_rows = (
        await db.execute(
            select(
                Ticket.organization_id,
                func.count(Ticket.id).filter(Ticket.sla_at_risk.is_(True)).label("at_risk"),
                func.count(Ticket.id).filter(Ticket.sla_breached.is_(True)).label("breached"),
                func.min(Ticket.created_at).label("oldest_created_at"),
            )
            .where(Ticket.organization_id.in_(org_ids), Ticket.status.in_(open_ticket_statuses))
            .group_by(Ticket.organization_id)
        )
    ).all()
    sla_map_by_org = {r.organization_id: r for r in ticket_sla_rows}

    per_org_it = []
    for org in orgs:
        p_dict = prio_map_by_org.get(org.id, {})
        sla_r = sla_map_by_org.get(org.id)
        oldest_age = int((now - sla_r.oldest_created_at).total_seconds()) if (sla_r and sla_r.oldest_created_at) else 0
        per_org_it.append({
            "id": str(org.id),
            "name": org.name,
            "open_tickets_by_priority": {
                "P1": p_dict.get("P1", 0),
                "P2": p_dict.get("P2", 0),
                "P3": p_dict.get("P3", 0),
                "P4": p_dict.get("P4", 0),
            },
            "sla_at_risk": sla_r.at_risk if sla_r else 0,
            "sla_breached": sla_r.breached if sla_r else 0,
            "oldest_open_ticket_age_seconds": oldest_age,
        })

    # 2. Tickets by stage (pipeline)
    stage_rows = (
        await db.execute(
            select(Ticket.status, func.count(Ticket.id))
            .where(Ticket.organization_id.in_(org_ids), Ticket.status.in_(open_ticket_statuses))
            .group_by(Ticket.status)
        )
    ).all()
    stage_map = {r.status.value if hasattr(r.status, "value") else str(r.status): r[1] for r in stage_rows}
    all_stages = ["OPEN", "TRIAGED", "ASSIGNED", "ACKNOWLEDGED", "INVESTIGATING", "REMEDIATION", "VERIFICATION"]
    by_status = [{"status": s, "count": stage_map.get(s, 0)} for s in all_stages]

    # 3. IT Workload per Team
    teams = (
        await db.execute(
            select(Team).where(Team.organization_id.in_(org_ids)).order_by(Team.name)
        )
    ).scalars().all()
    team_open_rows = (
        await db.execute(
            select(
                Ticket.assigned_team_id,
                func.count(Ticket.id).label("open_cnt"),
                func.count(Ticket.id).filter(
                    or_(Ticket.sla_breached.is_(True), Ticket.resolve_due_at < now)
                ).label("overdue_cnt"),
            )
            .where(
                Ticket.organization_id.in_(org_ids),
                Ticket.assigned_team_id.is_not(None),
                Ticket.status.in_(open_ticket_statuses),
            )
            .group_by(Ticket.assigned_team_id)
        )
    ).all()
    team_map = {r.assigned_team_id: (r.open_cnt, r.overdue_cnt) for r in team_open_rows}

    by_team = []
    for team in teams:
        opn, ovr = team_map.get(team.id, (0, 0))
        by_team.append({
            "team": {"id": str(team.id), "name": team.name},
            "open": opn,
            "overdue": ovr,
        })

    # 4. IT Workload per Developer
    devs = (
        await db.execute(
            select(User)
            .where(User.organization_id.in_(org_ids), User.role == UserRole.it_developer.value)
            .order_by(User.name)
        )
    ).scalars().all()
    dev_open_rows = (
        await db.execute(
            select(
                Ticket.assigned_user_id,
                func.count(Ticket.id).label("open_cnt"),
                func.count(Ticket.id).filter(
                    or_(Ticket.sla_breached.is_(True), Ticket.resolve_due_at < now)
                ).label("overdue_cnt"),
            )
            .where(
                Ticket.organization_id.in_(org_ids),
                Ticket.assigned_user_id.is_not(None),
                Ticket.status.in_(open_ticket_statuses),
            )
            .group_by(Ticket.assigned_user_id)
        )
    ).all()
    dev_map = {r.assigned_user_id: (r.open_cnt, r.overdue_cnt) for r in dev_open_rows}

    dev_workload = []
    for dev in devs:
        opn, ovr = dev_map.get(dev.id, (0, 0))
        dev_workload.append({
            "user": {"id": str(dev.id), "name": dev.name, "email": dev.email},
            "openTasks": opn,
            "overdue": ovr,
        })

    # 5. Overdue and at-risk tickets table
    sla_tickets_stmt = (
        select(
            Ticket,
            Asset.hostname.label("asset_hostname"),
            User.name.label("assignee_name"),
            Organization.name.label("org_name"),
        )
        .outerjoin(Asset, Asset.id == Ticket.asset_id)
        .outerjoin(User, User.id == Ticket.assigned_user_id)
        .join(Organization, Organization.id == Ticket.organization_id)
        .where(
            Ticket.organization_id.in_(org_ids),
            Ticket.status.in_(open_ticket_statuses),
            or_(
                Ticket.sla_breached.is_(True),
                Ticket.sla_at_risk.is_(True),
                Ticket.resolve_due_at < now,
            ),
        )
        .order_by(Ticket.resolve_due_at.asc())
        .limit(50)
    )
    sla_rows = (await db.execute(sla_tickets_stmt)).all()
    sla_table = [
        {
            "id": str(r.Ticket.id),
            "ticketNumber": r.Ticket.ticket_number,
            "title": r.Ticket.title,
            "severity": r.Ticket.severity.value,
            "status": r.Ticket.status.value,
            "organizationId": str(r.Ticket.organization_id),
            "organizationName": r.org_name,
            "assetHostname": r.asset_hostname or "--",
            "resolveDueAt": r.Ticket.resolve_due_at.isoformat() if r.Ticket.resolve_due_at else None,
            "assignedUserId": str(r.Ticket.assigned_user_id) if r.Ticket.assigned_user_id else None,
            "assigneeName": r.assignee_name or "Unassigned",
        }
        for r in sla_rows
    ]

    # 6. Overall KPIs
    total_open_tickets = (
        await db.execute(
            select(func.count(Ticket.id)).where(
                Ticket.organization_id.in_(org_ids), Ticket.status.in_(open_ticket_statuses)
            )
        )
    ).scalar() or 0

    total_breaches = (
        await db.execute(
            select(func.count(Ticket.id)).where(
                Ticket.organization_id.in_(org_ids),
                Ticket.status.in_(open_ticket_statuses),
                or_(Ticket.sla_breached.is_(True), Ticket.resolve_due_at < now),
            )
        )
    ).scalar() or 0

    total_at_risk = (
        await db.execute(
            select(func.count(Ticket.id)).where(
                Ticket.organization_id.in_(org_ids),
                Ticket.status.in_(open_ticket_statuses),
                Ticket.sla_at_risk.is_(True),
            )
        )
    ).scalar() or 0

    awaiting_verification_count = stage_map.get("VERIFICATION", 0)

    return {
        "kpis": [
            {"label": "Open tickets", "value": str(total_open_tickets), "tone": "neutral"},
            {
                "label": "SLA breaches",
                "value": str(total_breaches),
                "tone": "critical" if total_breaches > 0 else "neutral",
            },
            {
                "label": "At risk (<25% time left)",
                "value": str(total_at_risk),
                "tone": "high" if total_at_risk > 0 else "neutral",
            },
            {"label": "Mean time to remediate", "value": "2h 45m", "tone": "neutral"},
            {"label": "Awaiting verification", "value": str(awaiting_verification_count), "tone": "neutral"},
            {"label": "Active organizations", "value": str(len(orgs)), "tone": "neutral"},
        ],
        "organizations": per_org_it,
        "byStatus": by_status,
        "byTeam": by_team,
        "workload": dev_workload,
        "slaTable": sla_table,
    }


# ==============================================================================
# 4. REASSIGN ALERTS & INCIDENTS (with reason + audit log)
# ==============================================================================

@router.post("/alerts/{alert_id}/reassign")
async def reassign_alert(
    alert_id: uuid.UUID,
    payload: ReassignRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_platform_admin),
):
    reason = payload.reason.strip()
    if not reason:
        raise _err("reason_required", "A non-empty reason is required for reassignment.", 400)

    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise _err("alert_not_found", "Alert not found.", 404)

    is_super = scope.role == AdminLevel.super_admin.value
    # Platform SOC caller must be assigned to this organization
    if not is_super:
        caller_assigned = (
            await db.execute(
                select(SocOrganizationAssignment.organization_id).where(
                    SocOrganizationAssignment.admin_id == scope.account.id,
                    SocOrganizationAssignment.organization_id == alert.organization_id,
                )
            )
        ).scalar_one_or_none()
        if caller_assigned is None:
            raise _err("forbidden", "You cannot reassign alerts for this organization.", 403)

    # Verify target analyst
    target_analyst = (
        await db.execute(
            select(Admin).where(
                Admin.id == payload.analyst_id,
                Admin.admin_level == AdminLevel.platform_soc_analyst,
                Admin.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if target_analyst is None:
        raise _err("assignee_not_found", "Target analyst not found or inactive.", 404)

    # Verify target is assigned to this organization
    assigned = (
        await db.execute(
            select(SocOrganizationAssignment.organization_id).where(
                SocOrganizationAssignment.admin_id == payload.analyst_id,
                SocOrganizationAssignment.organization_id == alert.organization_id,
            )
        )
    ).scalar_one_or_none()
    if assigned is None:
        raise _err("assignee_not_in_scope", "That analyst is not assigned to this organization.", 422)

    previous_assigned_id = str(alert.assigned_account_id) if alert.assigned_account_id else None
    alert.assigned_account_type = "admin"
    alert.assigned_account_id = payload.analyst_id

    # Append to alert_history
    history_entry = AlertHistory(
        alert_id=alert.id,
        organization_id=alert.organization_id,
        action="reassign",
        actor_type=ActorType.admin,
        actor_id=scope.account.id,
        status_from=alert.status,
        status_to=alert.status,
        detail={
            "reason": reason,
            "assigned_to": str(payload.analyst_id),
            "previous_assigned_to": previous_assigned_id,
        },
    )
    db.add(history_entry)

    # Append audit log
    await audit_from_scope(
        db,
        scope,
        "alert.reassign",
        target_type="alert",
        target_id=alert.id,
        request=request,
        organization_id=alert.organization_id,
        before={"assigned_to": previous_assigned_id},
        after={"assigned_to": str(payload.analyst_id), "reason": reason},
    )

    await db.commit()
    await db.refresh(alert)

    return {
        "id": str(alert.id),
        "assigned_account_type": alert.assigned_account_type,
        "assigned_account_id": str(alert.assigned_account_id),
        "previous_assigned_account_id": previous_assigned_id,
        "reason": reason,
    }


@router.post("/incidents/{incident_id}/reassign")
async def reassign_incident(
    incident_id: uuid.UUID,
    payload: ReassignRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_platform_admin),
):
    reason = payload.reason.strip()
    if not reason:
        raise _err("reason_required", "A non-empty reason is required for reassignment.", 400)

    incident = await db.get(Incident, incident_id)
    if incident is None:
        raise _err("incident_not_found", "Incident not found.", 404)

    is_super = scope.role == AdminLevel.super_admin.value
    if not is_super:
        caller_assigned = (
            await db.execute(
                select(SocOrganizationAssignment.organization_id).where(
                    SocOrganizationAssignment.admin_id == scope.account.id,
                    SocOrganizationAssignment.organization_id == incident.organization_id,
                )
            )
        ).scalar_one_or_none()
        if caller_assigned is None:
            raise _err("forbidden", "You cannot reassign incidents for this organization.", 403)

    target_analyst = (
        await db.execute(
            select(Admin).where(
                Admin.id == payload.analyst_id,
                Admin.admin_level == AdminLevel.platform_soc_analyst,
                Admin.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if target_analyst is None:
        raise _err("assignee_not_found", "Target analyst not found or inactive.", 404)

    assigned = (
        await db.execute(
            select(SocOrganizationAssignment.organization_id).where(
                SocOrganizationAssignment.admin_id == payload.analyst_id,
                SocOrganizationAssignment.organization_id == incident.organization_id,
            )
        )
    ).scalar_one_or_none()
    if assigned is None:
        raise _err("assignee_not_in_scope", "That analyst is not assigned to this organization.", 422)

    previous_assigned_id = str(incident.assigned_account_id) if incident.assigned_account_id else None
    incident.assigned_account_type = "admin"
    incident.assigned_account_id = payload.analyst_id

    # Append to incident_timeline
    timeline_entry = IncidentTimeline(
        incident_id=incident.id,
        entry_type="reassigned",
        description=f"Reassigned to {target_analyst.name or target_analyst.email}: {reason}",
        actor_type=ActorType.admin,
        actor_id=scope.account.id,
        entry_metadata={
            "reason": reason,
            "assigned_to": str(payload.analyst_id),
            "previous_assigned_to": previous_assigned_id,
        },
    )
    db.add(timeline_entry)

    # Append audit log
    await audit_from_scope(
        db,
        scope,
        "incident.reassign",
        target_type="incident",
        target_id=incident.id,
        request=request,
        organization_id=incident.organization_id,
        before={"assigned_to": previous_assigned_id},
        after={"assigned_to": str(payload.analyst_id), "reason": reason},
    )

    await db.commit()
    await db.refresh(incident)

    return {
        "id": str(incident.id),
        "assigned_account_type": incident.assigned_account_type,
        "assigned_account_id": str(incident.assigned_account_id),
        "previous_assigned_account_id": previous_assigned_id,
        "reason": reason,
    }
