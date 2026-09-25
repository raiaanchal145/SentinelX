"""
The detection engine's runtime half (P23): given a batch of newly
stored events for one organization, evaluate them against the
organization's enabled rules and persist RuleHit rows.

Design (docs/DECISIONS.md): evaluation runs INLINE at the end of the
process_events job -- no second queue hop, batch order is inherently
deterministic, and a failed evaluation can't lose events (they're
already committed; the next batch re-evaluates against the windows).

For each enabled rule:
  1. the batch's events matching the rule's event types are added to
     the rule's sliding windows (state store, keyed by group);
  2. every touched group's in-window events are evaluated (windowed
     rules over [now - window, now], anchored at the batch's newest
     event; pattern rules over the batch's own span);
  3. satisfied groups become RuleHit rows (rule, org, key, event ids,
     window). Hit rows are NOT deduplicated -- a rule that keeps
     matching while the window stays saturated reports again, which is
     correct behavior for an ongoing attack (P10's alert pipeline will
     coalesce).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.definitions import group_key_for, parse_definition
from app.detection.evaluators import evaluate
from app.models import DetectionRule, EventSeverity, OrganizationRuleSetting, RuleHit

logger = logging.getLogger("sentinelx.detection")


def _normalized_event_view(stored: dict[str, Any]) -> dict[str, Any]:
    """The evaluator/state view of an event: the normalized columns the
    definitions can reference, plus the raw/normalized payloads for
    pattern paths."""
    normalized_data = stored.get("normalized_data") or {}
    return {
        "id": str(stored["id"]),
        "event_type": stored.get("event_type"),
        "username": stored.get("username"),
        "source_ip": stored.get("source_ip"),
        "host": normalized_data.get("host"),
        "process": normalized_data.get("process"),
        "raw": stored.get("raw_data") or {},
        "normalized": normalized_data,
        "occurred_at": stored.get("occurred_at"),
    }


async def _enabled_rules(db: AsyncSession, organization_id: uuid.UUID) -> list[DetectionRule]:
    """Built-in rules (org NULL) + this org's own custom rules, minus
    disabled ones, with organization_rule_settings overrides applied.
    A settings row always wins over the rule row's own flag; absence
    falls back to it."""
    rules = (
        (
            await db.execute(
                select(DetectionRule).where(
                    (DetectionRule.organization_id.is_(None))
                    | (DetectionRule.organization_id == organization_id)
                )
            )
        )
        .scalars()
        .all()
    )
    settings_rows = (
        (
            await db.execute(
                select(OrganizationRuleSetting).where(
                    OrganizationRuleSetting.organization_id == organization_id
                )
            )
        )
        .scalars()
        .all()
    )
    overrides = {row.rule_id: row.enabled for row in settings_rows}

    enabled: list[DetectionRule] = []
    for rule in rules:
        effective = overrides.get(rule.id, rule.enabled)
        if effective:
            enabled.append(rule)
    return enabled


async def evaluate_batch_for_organization(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    stored_events: list[dict[str, Any]],
    store,  # RedisWindowStore | MemoryWindowStore
) -> list[RuleHit]:
    """Run every enabled rule for one organization over a batch of
    freshly stored events. Returns the RuleHit rows that were written
    (also returned to the job for logging). Never raises for a bad
    rule definition -- that rule is skipped and logged; the event
    pipeline must not break because of one bad rule."""
    if not stored_events:
        return []

    rules = await _enabled_rules(db, organization_id)
    if not rules:
        return []

    # The window is anchored at the NEWEST event in the batch (or wall
    # clock when the batch is older): an online stream's events cluster
    # around now, but a burst that sat in the queue or a simulator run
    # with slightly stale timestamps must still be fully inside the
    # window -- otherwise a 20-failure batch whose tail is a few seconds
    # older than (now - window) silently escapes detection.
    newest = max(
        (e["occurred_at"] for e in stored_events if e.get("occurred_at") is not None),
        default=datetime.now(timezone.utc),
    )
    if isinstance(newest, str):
        newest = datetime.fromisoformat(newest.replace("Z", "+00:00"))
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    now = max(newest, datetime.now(timezone.utc))
    hits: list[RuleHit] = []

    for rule in rules:
        try:
            definition = parse_definition(rule.rule_type.value, rule.condition)
        except Exception:  # noqa: BLE001 -- one bad rule must not stop the batch
            logger.warning("detection: rule %s (%s) has an invalid definition -- skipped", rule.name, rule.id)
            continue

        # Only events the rule cares about touch its state.
        interesting_types = set(getattr(definition, "event_types", []) or []) | {
            step.event_type for step in getattr(definition, "steps", [])
        }
        if rule.rule_type.value == "pattern":
            # Pattern rules match per event over any type their
            # conditions name; a regex condition may span types
            # (group_change|process_create), so feed them every event.
            candidate_rows = stored_events
        else:
            candidate_rows = [e for e in stored_events if e.get("event_type") in interesting_types]
        if not candidate_rows:
            continue

        candidates = [_normalized_event_view(e) for e in candidate_rows]

        # Pattern rules match per event -- no window semantics. They
        # still evaluate over a span (oldest stored event -> now, the
        # same anchor the windowed rules use): the batch IS the recent
        # stream, and a [now, now] window would exclude every event
        # that arrived even a second before evaluation. A hit's own
        # window stays the event's timestamp (the evaluators set it).
        window_seconds = getattr(definition, "window_seconds", 0)
        if window_seconds > 0:
            window_start = now - dt.timedelta(seconds=window_seconds)
        else:
            # Span the batch: oldest event in the batch (or `now` when
            # the batch is empty of timeable events).
            oldest = min(
                (e["occurred_at"] for e in stored_events if e.get("occurred_at") is not None),
                default=None,
            )
            if isinstance(oldest, str):
                oldest = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
            if oldest is not None and oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            window_start = oldest if oldest is not None else now

        group_by = getattr(definition, "group_by", None)
        if group_by is not None and window_seconds > 0:
            await store.add_events(
                organization_id=str(organization_id),
                rule_id=str(rule.id),
                group_by=group_by,
                events=candidates,
            )

        if group_by is not None:
            # Evaluate every group the batch touched -- a small batch
            # can complete a sequence started by an earlier one.
            group_values = {
                key
                for key in (group_key_for(group_by, e) for e in candidates)
                if key is not None
            }
            matches = []
            for group_value in group_values:
                window_events = await store.get_window_events(
                    organization_id=str(organization_id),
                    rule_id=str(rule.id),
                    group_by=group_by,
                    group_value=group_value,
                    window_seconds=window_seconds,
                    now=now,
                )
                matches.extend(
                    evaluate(rule.rule_type.value, definition, window_events, window_start=window_start, window_end=now)
                )
        else:
            matches = evaluate(rule.rule_type.value, definition, candidates, window_start=window_start, window_end=now)

        for match in matches:
            # Hit keys are prefixed with what they grouped by so the
            # history table is self-describing ("user=alice",
            # "ip=1.2.3.4"); pattern hits are already "event=<id>".
            hit_key = match.group_key if match.group_key.startswith("event=") else f"{group_by or 'event'}={match.group_key}"
            hits.append(
                RuleHit(
                    organization_id=organization_id,
                    rule_id=rule.id,
                    rule_name=rule.name,
                    severity=EventSeverity(rule.severity.value if hasattr(rule.severity, "value") else rule.severity),
                    group_key=hit_key,
                    event_ids=match.event_ids,
                    event_count=len(match.event_ids),
                    window_start=match.window_start or window_start,
                    window_end=match.window_end or now,
                )
            )

    if hits:
        db.add_all(hits)
        await db.flush()

    return hits
