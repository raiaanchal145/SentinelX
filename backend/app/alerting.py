"""
The alerting half of P10 (docs/API_CONTRACT.md "Alerts"): turn P09's
rule hits into deduplicated alerts, then correlate related alerts.

Runs INLINE at the end of process_events, in the same transaction as
the hit writes (docs/DECISIONS.md): a failure rolls back hits and
alerts together, so the next batch re-evaluates and re-alerts from the
same events -- ingestion itself never breaks.

Two phases:

1. create_alerts_for_hits -- one alert per (organization, rule, group
   key, time bucket). The bucket is hit.window_end floored to the
   rule's dedup_window_seconds (default 15 min, per-rule column): hits
   landing in the same bucket FOLD into the existing row (event_count
   grows, last_seen_at extends, alert_events links are added -- capped,
   the true count is kept), hits in a fresh bucket create a new alert.
   The partial unique index on (organization, dedup_key) makes the
   fold-attempt race-safe.

2. run_correlations -- the seeded correlation rules over the
   organization's recent alerts. Exactly one rule ships (built-in,
   org NULL): "many failed logins + success + privileged action for
   the same user within 30 minutes" = one high-severity correlated
   alert, a Correlation row with the reasoning text ("why these were
   grouped"), and correlation_alerts links. Correlated alerts are
   ALONGSIDE the underlying ones (they group, they don't hide) --
   docs/DECISIONS.md.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActorType,
    Alert,
    AlertEvent,
    AlertHistory,
    AlertStatus,
    Correlation,
    CorrelationAlert,
    CorrelationRule,
    DetectionRule,
    EventSeverity,
    RuleHit,
)

logger = logging.getLogger("sentinelx.alerting")

# alert_events rows stored per alert. Repeated hits can reference
# hundreds of events; the alert keeps the first MAX (oldest first) as
# concrete links and the true total in alerts.event_count.
MAX_ALERT_EVENT_LINKS = 50

# The one built-in correlation rule (stable slug -- the seeding key).
BRUTE_FORCE_CORRELATION_ID = "brute-force-then-privileged-activity"

# The detection rule names the correlation matches on. Kept in one
# place so a future rename of a built-in rule updates here and in the
# seeding tests together.
_CORRELATION_REQUIRED_RULE_NAMES = (
    "Repeated failed logins",  # threshold: N failures
    "Successful login after many failures",  # sequence: failure -> success
    "Privileged group membership change",  # pattern: privileged group action
)


# ---------------------------------------------------------------------------
# Built-in correlation rule seeding (mirrors detection's seed_builtin_rules).
# ---------------------------------------------------------------------------


async def seed_builtin_correlation_rules(session_factory=None) -> int:
    """Idempotently write the built-in correlation rule (organization_id
    NULL). Nothing per-organization to preserve yet, so ON CONFLICT DO
    UPDATE simply refreshes."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if session_factory is None:
        from app.database import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    row = {
        "name": "Brute force followed by privileged activity",
        "time_window_seconds": 1800,
        "conditions": {
            "description": (
                "Repeated failed logins plus a successful login plus a "
                "privileged action, for the same user, within 30 minutes."
            ),
            "match_rule_names": list(_CORRELATION_REQUIRED_RULE_NAMES),
            "group_by": "user",
        },
        "enabled": True,
    }
    async with session_factory() as db:
        stmt = pg_insert(CorrelationRule).values(**row).on_conflict_do_update(
            index_elements=["name"],
            # The unique index is PARTIAL (built-in rules only, see the
            # model) -- without index_where Postgres can't match it and
            # the insert fails with InvalidColumnReferenceError.
            index_where=CorrelationRule.organization_id.is_(None),
            set_={
                "time_window_seconds": row["time_window_seconds"],
                "conditions": row["conditions"],
                "enabled": row["enabled"],
            },
        )
        await db.execute(stmt)
        await db.commit()
    return 1


# ---------------------------------------------------------------------------
# Phase 1: hits -> deduplicated alerts.
# ---------------------------------------------------------------------------


def _uuid_of(value) -> uuid.UUID:
    """The worker's stored-row view carries event ids as UUID objects;
    hit JSONB event_ids are strings. Accept either."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _dedup_bucket(window_end: datetime, window_seconds: int) -> int:
    """The dedup bucket a hit's window end falls into: epoch seconds
    floored to the rule's dedup window. Hits inside one window share a
    bucket and therefore fold into one alert."""
    return int(window_end.timestamp()) // window_seconds


def _resolved_keys(hits: list[RuleHit], events: list[dict[str, Any]]) -> dict[str, Any]:
    """The correlation keys for a would-be alert, resolved from the
    supporting events (a pattern hit's group key names one event, so
    keys come from the events' normalized view, not the hit key).
    events: [{id, username, source_ip, occurred_at, asset_id}]"""
    usernames = [e.get("username") for e in events if e.get("username")]
    ips = [e.get("source_ip") for e in events if e.get("source_ip")]
    assets = [e.get("asset_id") for e in events if e.get("asset_id")]
    occurred = [e.get("occurred_at") for e in events if e.get("occurred_at")]
    return {
        "username": usernames[0] if usernames else None,
        "source_ip": ips[0] if ips else None,
        "asset_id": assets[0] if assets else None,
        # Oldest supporting event's time = the alert's first_seen.
        "first_seen_at": min(occurred) if occurred else None,
    }


async def create_alerts_for_hits(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    hits: list[RuleHit],
    stored_events: list[dict[str, Any]],
) -> int:
    """Create-or-fold one alert per (rule, group key, dedup bucket).
    Returns how many alert rows were created (folds don't count).
    stored_events is the worker's stored-row view (id, username,
    source_ip, occurred_at, asset_id) -- used to resolve correlation
    keys and link alert_events."""
    if not hits:
        return 0

    event_by_id: dict[str, dict[str, Any]] = {str(e["id"]): e for e in stored_events}

    rules = {
        r.id: r
        for r in (
            await db.execute(select(DetectionRule).where(DetectionRule.id.in_([h.rule_id for h in hits])))
        )
        .scalars()
        .all()
    }

    created = 0
    for hit in hits:
        rule = rules.get(hit.rule_id)
        window_seconds = rule.dedup_window_seconds if rule else 900
        bucket = _dedup_bucket(hit.window_end, window_seconds)
        dedup_key = f"{hit.rule_name}:{hit.group_key}:{bucket}"

        # The hit's events, in window order (oldest first), as linkable
        # rows. Events may be missing from event_by_id if they were
        # stored by an earlier batch (a fold); those still count toward
        # event_count via the hit's own count.
        hit_event_ids = [str(e) for e in (hit.event_ids or [])]
        linked = [event_by_id[e] for e in hit_event_ids if e in event_by_id]

        existing = (
            await db.execute(
                select(Alert).where(
                    Alert.organization_id == organization_id,
                    Alert.dedup_key == dedup_key,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            # Fold: extend the window, grow the count, add any links we
            # don't already have (up to the cap).
            existing.event_count += hit.event_count
            if hit.window_end > existing.last_seen_at:
                existing.last_seen_at = hit.window_end
            if hit.window_start < existing.first_seen_at:
                existing.first_seen_at = hit.window_start
            already = set(
                (
                    await db.execute(
                        select(AlertEvent.event_id).where(AlertEvent.alert_id == existing.id)
                    )
                ).scalars()
            )
            slots = MAX_ALERT_EVENT_LINKS - len(already)
            for e in linked:
                if slots <= 0:
                    break
                if _uuid_of(e["id"]) in already:
                    continue
                db.add(
                    AlertEvent(
                        alert_id=existing.id,
                        event_id=_uuid_of(e["id"]),
                        occurred_at=e.get("occurred_at") or existing.last_seen_at,
                    )
                )
                slots -= 1
            continue

        keys = _resolved_keys(hits, linked)
        alert = Alert(
            organization_id=organization_id,
            detection_rule_id=hit.rule_id,
            rule_name=hit.rule_name,
            kind="detection",
            asset_id=keys["asset_id"],
            severity=hit.severity,
            status=AlertStatus.new,
            title=f"{hit.rule_name} -- {hit.group_key}",
            summary=(
                f"{hit.event_count} event(s) matched '{hit.rule_name}' for {hit.group_key} "
                f"between {hit.window_start:%H:%M:%S} and {hit.window_end:%H:%M:%S} UTC."
            ),
            first_seen_at=keys["first_seen_at"] or hit.window_start,
            last_seen_at=hit.window_end,
            event_count=hit.event_count,
            group_key=hit.group_key,
            username=keys["username"],
            source_ip=keys["source_ip"],
            dedup_key=dedup_key,
        )
        db.add(alert)
        await db.flush()  # alert.id for the links + history row
        for e in linked[:MAX_ALERT_EVENT_LINKS]:
            db.add(
                AlertEvent(
                    alert_id=alert.id,
                    event_id=_uuid_of(e["id"]),
                    occurred_at=e.get("occurred_at") or alert.last_seen_at,
                )
            )
        db.add(
            AlertHistory(
                alert_id=alert.id,
                organization_id=organization_id,
                action="create",
                actor_type=ActorType.system,
                actor_id=None,
                status_to=AlertStatus.new,
                detail={"dedup_key": dedup_key, "hit_id": str(hit.id)},
            )
        )
        created += 1

    return created


# ---------------------------------------------------------------------------
# Phase 2: correlation.
# ---------------------------------------------------------------------------


def _correlation_signature(alerts: list[Alert]) -> tuple[str, str | None, str | None]:
    """(group_by, key_value, secondary) for a candidate alert set -- the
    user (or IP/host fallback) every alert in the set must share."""
    usernames = [a.username for a in alerts if a.username]
    ips = [a.source_ip for a in alerts if a.source_ip]
    if usernames:
        return "user", usernames[0], ips[0] if ips else None
    if ips:
        return "ip", ips[0], None
    return "unknown", None, None


def _correlation_reasoning(
    rule: CorrelationRule, alerts: list[Alert], group_by: str, key_value: str | None, window_seconds: int
) -> str:
    """The 'why these were grouped' text stored on the Correlation row:
    which rule matched, which alerts with which keys and what span."""
    parts = [
        a.rule_name or (str(a.detection_rule_id) if a.detection_rule_id else "correlated alert")
        for a in alerts
    ]
    span_start = min(a.first_seen_at for a in alerts if a.first_seen_at)
    span_end = max(a.last_seen_at for a in alerts if a.last_seen_at)
    return (
        f"Correlation rule '{rule.name}': the alerts [{', '.join(sorted(set(parts)))}] "
        f"all belong to {group_by} '{key_value}' and fall within {window_seconds} seconds "
        f"({span_start:%H:%M:%S} to {span_end:%H:%M:%S} UTC). Repeated failures followed by "
        "a success and privileged activity is the classic brute-force-then-takeover pattern, "
        "so the SOC sees one high-severity incident-shaped story instead of three unrelated alerts."
    )


async def run_correlations(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> int:
    """Evaluate enabled correlation rules for the organization over its
    recent (30x window) detection alerts. Returns how many correlation
    rows were created. Deterministic: ordered by (username, first_seen),
    greedy earliest-match per candidate set, no double-assignment of an
    alert to two correlations of the same rule."""
    rules = (
        (
            await db.execute(
                select(CorrelationRule).where(
                    (CorrelationRule.organization_id.is_(None))
                    | (CorrelationRule.organization_id == organization_id),
                    CorrelationRule.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rules:
        return 0

    recent_window = max(r.time_window_seconds for r in rules) * 10
    cutoff = datetime.now(timezone.utc) - dt.timedelta(seconds=recent_window)
    candidates = (
        (
            await db.execute(
                select(Alert)
                .where(
                    Alert.organization_id == organization_id,
                    Alert.kind == "detection",
                    Alert.first_seen_at >= cutoff,
                    Alert.dismissed_reason.is_(None),
                )
                .order_by(Alert.first_seen_at, Alert.id)
            )
        )
        .scalars()
        .all()
    )
    if len(candidates) < 2:
        return 0

    created = 0
    for rule in rules:
        window_seconds = rule.time_window_seconds
        match_names = list((rule.conditions or {}).get("match_rule_names") or [])
        by_name = {a.rule_name: a for a in candidates if a.rule_name in match_names}
        missing = [n for n in match_names if n not in by_name]
        if missing:
            continue  # the rule needs every named alert kind present

        picks = [by_name[n] for n in match_names if n in by_name]
        span = max(a.last_seen_at for a in picks) - min(a.first_seen_at for a in picks)
        if span > dt.timedelta(seconds=window_seconds):
            continue  # same user, but outside the correlation window

        group_by, key_value, _secondary = _correlation_signature(picks)
        if key_value is None:
            continue

        bucket = int(min(a.first_seen_at for a in picks).timestamp()) // window_seconds
        dedup_key = f"corr:{rule.name}:{group_by}={key_value}:{bucket}"

        existing = (
            await db.execute(
                select(Correlation).where(
                    Correlation.organization_id == organization_id,
                    Correlation.dedup_key == dedup_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue

        first_seen = min(a.first_seen_at for a in picks)
        last_seen = max(a.last_seen_at for a in picks)
        event_count = sum(a.event_count for a in picks)
        reasoning = _correlation_reasoning(rule, picks, group_by, key_value, window_seconds)

        correlated = Alert(
            organization_id=organization_id,
            detection_rule_id=None,
            rule_name=None,
            kind="correlation",
            severity=EventSeverity.high,
            status=AlertStatus.new,
            title=f"Brute force followed by privileged activity -- {group_by}={key_value}",
            summary=(
                f"{len(picks)} related alerts for {group_by} '{key_value}' were grouped by "
                f"correlation rule '{rule.name}'. See the correlation for the reasoning."
            ),
            first_seen_at=first_seen,
            last_seen_at=last_seen,
            event_count=event_count,
            group_key=f"{group_by}={key_value}",
            username=key_value if group_by == "user" else None,
            source_ip=key_value if group_by == "ip" else None,
            dedup_key=dedup_key,
        )
        db.add(correlated)
        await db.flush()

        correlation = Correlation(
            organization_id=organization_id,
            correlation_rule_id=rule.id,
            title=correlated.title,
            severity=EventSeverity.high,
            reasoning=reasoning,
            first_seen_at=first_seen,
            last_seen_at=last_seen,
            event_count=event_count,
            dedup_key=dedup_key,
            summary=correlated.summary,
        )
        db.add(correlation)
        await db.flush()
        for a in picks:
            db.add(CorrelationAlert(correlation_id=correlation.id, alert_id=a.id))

        db.add(
            AlertHistory(
                alert_id=correlated.id,
                organization_id=organization_id,
                action="create",
                actor_type=ActorType.system,
                actor_id=None,
                status_to=AlertStatus.new,
                detail={"correlation_id": str(correlation.id), "grouped_alerts": [str(a.id) for a in picks]},
            )
        )
        created += 1

    return created
