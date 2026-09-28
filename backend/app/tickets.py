"""
Ticket domain logic (P13 remediation workflow): the priority formula,
SLA deadline stamping + policy seeding, assignment-rule evaluation,
auto-creation eligibility and the status transition map. Kept in one
module so everything below the HTTP/worker layers is testable without a
database (the routers and worker jobs import from here).

The priority formula is documented in docs/API_CONTRACT.md ("Tickets --
Priority") and pinned in docs/DECISIONS.md; if the weights change,
change them here and in both docs in the same commit.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActorType,
    AssignmentRule,
    Asset,
    AssetCriticality,
    EventSeverity,
    Organization,
    SlaPolicy,
    Ticket,
    TicketAssignment,
    TicketStatus,
    User,
    UserRole,
)

# ---------------------------------------------------------------------------
# Priority (documented formula, unit-tested)
# ---------------------------------------------------------------------------

SEVERITY_POINTS: dict[EventSeverity, int] = {
    EventSeverity.critical: 40,
    EventSeverity.high: 30,
    EventSeverity.medium: 20,
    EventSeverity.low: 10,
    EventSeverity.info: 5,
}

ASSET_CRITICALITY_POINTS: dict[AssetCriticality, int] = {
    AssetCriticality.critical: 30,
    AssetCriticality.high: 22,
    AssetCriticality.medium: 12,
    AssetCriticality.low: 5,
}

# Confidence bands: >=0.9 +10, >=0.7 +5, below +0.
CONFIDENCE_HIGH = 0.9
CONFIDENCE_MID = 0.7
CONFIDENCE_HIGH_POINTS = 10
CONFIDENCE_MID_POINTS = 5

# Score -> P-code thresholds (>= comparison, tested at the boundaries).
P1_MIN = 80
P2_MIN = 60
P3_MIN = 35


def confidence_points(confidence: float | None) -> int:
    if confidence is None:
        return 0
    if confidence >= CONFIDENCE_HIGH:
        return CONFIDENCE_HIGH_POINTS
    if confidence >= CONFIDENCE_MID:
        return CONFIDENCE_MID_POINTS
    return 0


def compute_priority(
    severity: EventSeverity,
    asset_criticality: AssetCriticality | None,
    confidence: float | None,
) -> str:
    """
    P1..P4 from incident/ticket severity + the asset's criticality + the
    incident's confidence score:

        score = severity_points + asset_criticality_points (0 if no asset)
                + confidence_points (None = 0)
        P1 >= 80 | P2 >= 60 | P3 >= 35 | else P4
    """
    score = SEVERITY_POINTS.get(severity, 0)
    if asset_criticality is not None:
        score += ASSET_CRITICALITY_POINTS.get(asset_criticality, 0)
    score += confidence_points(confidence)
    if score >= P1_MIN:
        return "P1"
    if score >= P2_MIN:
        return "P2"
    if score >= P3_MIN:
        return "P3"
    return "P4"


# ---------------------------------------------------------------------------
# SLA policies
# ---------------------------------------------------------------------------

# The default policies seeded for every organization (docs/DECISIONS.md);
# the migration's backfill writes the same table for existing orgs.
DEFAULT_SLA_MINUTES: dict[str, tuple[int, int]] = {
    "P1": (15, 240),
    "P2": (30, 480),
    "P3": (60, 1440),
    "P4": (240, 4320),
}


async def seed_default_sla_policies(db: AsyncSession, organization_id: uuid.UUID) -> None:
    """Idempotent: only fills priorities the org has no row for yet."""
    existing = (
        await db.execute(
            select(SlaPolicy.priority).where(SlaPolicy.organization_id == organization_id)
        )
    ).scalars().all()
    have = set(existing)
    for priority, (ack, resolve) in DEFAULT_SLA_MINUTES.items():
        if priority in have:
            continue
        db.add(
            SlaPolicy(
                organization_id=organization_id,
                priority=priority,
                acknowledge_minutes=ack,
                resolve_minutes=resolve,
                business_hours_only=False,
            )
        )


async def stamp_sla_deadlines(db: AsyncSession, ticket: Ticket) -> None:
    """
    Resolve the org's policy for the ticket's priority, stamp ack/resolve
    deadlines from now, and link the policy. No policy (or no matching
    priority row) leaves the deadlines NULL -- the ticket runs without an
    SLA rather than inheriting a wrong one.
    """
    if ticket.priority is None:
        return
    policy = (
        await db.execute(
            select(SlaPolicy).where(
                SlaPolicy.organization_id == ticket.organization_id,
                SlaPolicy.priority == ticket.priority,
            )
        )
    ).scalar_one_or_none()
    if policy is None:
        return
    now = datetime.now(timezone.utc)
    ticket.sla_policy_id = policy.id
    ticket.ack_due_at = now + timedelta(minutes=policy.acknowledge_minutes)
    ticket.resolve_due_at = now + timedelta(minutes=policy.resolve_minutes)


# SLA evaluation thresholds (worker cron + tests with a controllable clock).
AT_RISK_FRACTION = 0.8


def _aware(value: datetime) -> datetime:
    """Treat naive DB timestamps as UTC (created_at is a plain
    `timestamp` via server_default=func.now(); the deadline columns are
    TIMESTAMP(timezone=True)) so comparisons never mix the two."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def evaluate_sla_state(
    *,
    created_at: datetime,
    acknowledged_at: datetime | None,
    ack_due_at: datetime | None,
    resolve_due_at: datetime | None,
    resolved_at: datetime | None,
    now: datetime,
) -> tuple[bool, bool]:
    """Returns (at_risk, breached) for one ticket at `now`. A ticket
    without deadlines or already resolved/closed is never marked.

    At-risk (>=80% of the running window elapsed): the window is
    ack_due_at - created_at until the ticket is acknowledged, then
    resolve_due_at - acknowledged_at (or created_at when never
    acknowledged). A breached deadline implies at-risk too.
    """
    if resolve_due_at is None or resolved_at is not None:
        return False, False
    now = _aware(now)
    resolve_due_at = _aware(resolve_due_at)
    breach = now >= resolve_due_at

    def at_risk_for(start: datetime, deadline: datetime) -> bool:
        window = (_aware(deadline) - _aware(start)).total_seconds()
        if window <= 0:
            return breach
        return (now - _aware(start)).total_seconds() >= AT_RISK_FRACTION * window

    if acknowledged_at is None:
        start = _aware(created_at)
        if ack_due_at is not None and now < _aware(ack_due_at):
            # Ack clock still running: at-risk against that window, and
            # the resolve window cannot have run past its deadline yet.
            return at_risk_for(start, ack_due_at), breach
    else:
        start = _aware(acknowledged_at)
    return at_risk_for(start, resolve_due_at), breach


# ---------------------------------------------------------------------------
# Assignment rules
# ---------------------------------------------------------------------------


async def evaluate_assignment_rules(
    db: AsyncSession, ticket: Ticket
) -> tuple[uuid.UUID | None, str | None]:
    """
    Walk the org's enabled assignment_rules in priority_order (lower
    first) and return (team_id, rule_name) for the first whose
    match_conditions match the ticket. Conditions are the same shape as
    detection's: [{field, op, value}] over ticket columns severity,
    priority, category, asset criticality ("asset_criticality").
    Returns (None, None) when no rule matches.
    """
    rules = (
        await db.execute(
            select(AssignmentRule)
            .where(
                AssignmentRule.organization_id == ticket.organization_id,
                AssignmentRule.enabled.is_(True),
            )
            .order_by(AssignmentRule.priority_order.asc(), AssignmentRule.created_at.asc())
        )
    ).scalars().all()
    if not rules:
        return None, None

    asset = None
    if ticket.asset_id is not None:
        asset = await db.get(Asset, ticket.asset_id)

    field_values: dict[str, object] = {
        "severity": ticket.severity.value if ticket.severity else None,
        "priority": ticket.priority,
        "category": ticket.category,
        "asset_criticality": asset.criticality.value if asset else None,
    }

    for rule in rules:
        conditions = rule.match_conditions or []
        ok = True
        for cond in conditions:
            field = cond.get("field")
            op = cond.get("op")
            value = cond.get("value")
            actual = field_values.get(field)
            if op == "eq":
                matched = str(actual) == str(value)
            elif op == "in":
                matched = str(actual) in [str(v) for v in value] if isinstance(value, list) else False
            elif op == "ne":
                matched = str(actual) != str(value)
            else:
                matched = False
            if not matched:
                ok = False
                break
        if ok:
            return rule.assign_to_team_id, rule.name
    return None, None


async def least_loaded_member(
    db: AsyncSession, organization_id: uuid.UUID, team_id: uuid.UUID
) -> User | None:
    """
    The team's active it_developer with the fewest OPEN tickets
    (open = not resolved/closed). Ties broken by name for determinism.
    """
    members = (
        await db.execute(
            select(User).where(
                User.organization_id == organization_id,
                User.team_id == team_id,
                User.role == UserRole.it_developer,
                User.is_active.is_(True),
            )
        )
    ).scalars().all()
    if not members:
        return None
    open_statuses = [TicketStatus.resolved.value, TicketStatus.closed.value]
    counts: dict[uuid.UUID, int] = {}
    rows = (
        await db.execute(
            select(Ticket.assigned_user_id, func.count(Ticket.id))
            .where(
                Ticket.organization_id == organization_id,
                Ticket.assigned_user_id.isnot(None),
                Ticket.status.notin_([TicketStatus.resolved, TicketStatus.closed]),
            )
            .group_by(Ticket.assigned_user_id)
        )
    ).all()
    for user_id, count in rows:
        counts[user_id] = count
    return min(members, key=lambda u: (counts.get(u.id, 0), u.name))


# ---------------------------------------------------------------------------
# Auto-creation eligibility (rules from the documentation)
# ---------------------------------------------------------------------------


async def auto_ticket_eligible(
    db: AsyncSession, organization: Organization, incident
) -> bool:
    """
    An incident auto-creates a ticket when every gate passes:
      - the org has both thresholds configured (severity + confidence;
        either NULL = that gate is off = feature disabled),
      - incident.severity >= auto_ticket_threshold,
        incident.confidence >= auto_ticket_min_confidence,
      - no OPEN/WORKING ticket already exists for the same incident AND
        asset (duplicate prevention).
    """
    from app.models import OrganizationSettings

    settings_row = (
        await db.execute(
            select(OrganizationSettings).where(
                OrganizationSettings.organization_id == organization.id
            )
        )
    ).scalar_one_or_none()
    if settings_row is None:
        return False

    min_severity = settings_row.auto_ticket_threshold
    min_confidence = settings_row.auto_ticket_min_confidence
    if min_severity is None or min_confidence is None:
        return False

    # Declaration order is NOT severity order (critical is first in the
    # enum), so rank explicitly: info=0 .. critical=4. ">= threshold"
    # means at least as severe as the threshold.
    severity_rank = {
        EventSeverity.info: 0,
        EventSeverity.low: 1,
        EventSeverity.medium: 2,
        EventSeverity.high: 3,
        EventSeverity.critical: 4,
    }
    if incident.severity is None or severity_rank[incident.severity] < severity_rank[min_severity]:
        return False
    if incident.confidence is None or incident.confidence < min_confidence:
        return False

    # Duplicate guard: same incident + same asset (NULL asset groups as
    # NULL-asset) with a ticket still open.
    dup = await db.execute(
        select(Ticket.id)
        .where(
            Ticket.organization_id == incident.organization_id,
            Ticket.incident_id == incident.id,
            Ticket.asset_id.is_(None) if incident.primary_asset_id is None else Ticket.asset_id == incident.primary_asset_id,
            Ticket.status.notin_([TicketStatus.resolved, TicketStatus.closed]),
        )
        .limit(1)
    )
    return dup.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# The transition table -- ONE map, all 9 TicketStatus values (docs/
# API_CONTRACT.md "Tickets -- Status machine"; tested per role).
# ---------------------------------------------------------------------------

SOC_CLOSE_STATES = {TicketStatus.verification, TicketStatus.resolved, TicketStatus.closed}

TICKET_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.open: {
        TicketStatus.triaged,
        TicketStatus.assigned,
        TicketStatus.acknowledged,
        TicketStatus.investigating,
    },
    TicketStatus.triaged: {
        TicketStatus.assigned,
        TicketStatus.acknowledged,
        TicketStatus.investigating,
    },
    TicketStatus.assigned: {
        TicketStatus.triaged,
        TicketStatus.acknowledged,
        TicketStatus.investigating,
    },
    TicketStatus.acknowledged: {
        TicketStatus.assigned,
        TicketStatus.investigating,
    },
    TicketStatus.investigating: {
        TicketStatus.triaged,
        TicketStatus.remediation,
        TicketStatus.verification,
    },
    TicketStatus.remediation: {
        TicketStatus.investigating,
        TicketStatus.verification,
    },
    # SOC-only targets (role-gated in the router, not here):
    TicketStatus.verification: {
        TicketStatus.resolved,
        TicketStatus.investigating,
        TicketStatus.open,
    },
    TicketStatus.resolved: {TicketStatus.closed, TicketStatus.open},
    TicketStatus.closed: {TicketStatus.open},
}


# Worker/stamp helpers


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
