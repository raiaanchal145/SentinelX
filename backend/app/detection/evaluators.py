"""
Detection evaluators (P23): PURE functions over an event stream.

Each evaluator takes a validated definition, an in-window event list
(oldest first -- the caller sorts once), and returns the groups that
satisfy the rule as `RuleMatch` records (group key, contributing event
ids, window). No DB, no Redis, no clock: the caller passes the window
boundaries, so edge cases (event exactly at the boundary, out-of-order
arrival, interleaved keys) are unit-testable by construction.

The state store (state.py) is what makes these work incrementally in
the worker: the worker keeps each group's recent events in Redis, and
on every newly stored event calls the evaluator with that group's
window slice. The evaluators themselves are stateless.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from app.detection.definitions import (
    PatternDefinition,
    SequenceDefinition,
    ThresholdDefinition,
    condition_matches,
    group_key_for,
)


@dataclass
class RuleMatch:
    """One satisfied group: the key, its event ids (oldest first) and
    the actual window the events span (which may be tighter than the
    rule's configured window)."""

    group_key: str
    event_ids: list[str] = field(default_factory=list)
    window_start: dt.datetime | None = None
    window_end: dt.datetime | None = None


def _occurred_at(event: dict) -> dt.datetime | None:
    value = event.get("occurred_at")
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _span(events: list[dict]) -> tuple[dt.datetime | None, dt.datetime | None]:
    times = [t for t in (_occurred_at(e) for e in events) if t is not None]
    if not times:
        return None, None
    return min(times), max(times)


def _in_window(event: dict, window_start: dt.datetime, window_end: dt.datetime) -> bool:
    """Left-edge INCLUSIVE: an event occurred exactly window_start ago
    belongs to the window (a 600s window spans [now-600s, now])."""
    occurred = _occurred_at(event)
    if occurred is None:
        return True  # untimeable events are the caller's problem
    return window_start <= occurred <= window_end


def evaluate_threshold(
    definition: ThresholdDefinition,
    events: list[dict],
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> list[RuleMatch]:
    """Groups of `group_by` whose matching-event count within the window
    reaches `threshold`. Every matching event id is reported (not just
    the last N) so the alert can show the whole story. Events outside
    [window_start, window_end] are ignored -- the evaluators are
    self-contained about the window, not just the state store."""
    by_group: dict[str, list[dict]] = {}
    for event in events:
        if event.get("event_type") not in definition.event_types:
            continue
        if not _in_window(event, window_start, window_end):
            continue
        key = group_key_for(definition.group_by, event)
        if key is None:
            continue
        by_group.setdefault(key, []).append(event)

    matches: list[RuleMatch] = []
    for key, group_events in by_group.items():
        if len(group_events) >= definition.threshold:
            start, end = _span(group_events)
            matches.append(
                RuleMatch(
                    group_key=key,
                    event_ids=[str(e["id"]) for e in group_events],
                    window_start=start or window_start,
                    window_end=end or window_end,
                )
            )
    return matches


def evaluate_sequence(
    definition: SequenceDefinition,
    events: list[dict],
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> list[RuleMatch]:
    """Groups whose events contain the definition's steps IN ORDER
    within the window. Implementation: walk the group's events oldest
    -> newest, consuming steps as they match; the rule fires when every
    step has been consumed. An out-of-order event simply doesn't
    consume a step (it may still be reported if it matches a later
    step). Only the events that actually contributed to the consumed
    steps are reported."""
    by_group: dict[str, list[dict]] = {}
    for event in events:
        if not _in_window(event, window_start, window_end):
            continue
        key = group_key_for(definition.group_by, event)
        if key is None:
            continue
        by_group.setdefault(key, []).append(event)

    matches: list[RuleMatch] = []
    for key, group_events in by_group.items():
        ordered = sorted(
            group_events,
            key=lambda e: (_occurred_at(e) is None, _occurred_at(e)),
        )
        matched_events: list[dict] = []
        step_index = 0
        for event in ordered:
            if step_index >= len(definition.steps):
                break
            step = definition.steps[step_index]
            if event.get("event_type") != step.event_type:
                continue
            if step.fields and not all(
                condition_matches(event, type("_C", (), {"field": f"raw.{k}", "op": "eq", "value": v})())
                for k, v in step.fields.items()
            ) and not all((event.get("raw") or {}).get(k) == v for k, v in step.fields.items()):
                continue
            matched_events.append(event)
            step_index += 1

        if step_index == len(definition.steps):
            start, end = _span(matched_events)
            matches.append(
                RuleMatch(
                    group_key=key,
                    event_ids=[str(e["id"]) for e in matched_events],
                    window_start=start or window_start,
                    window_end=end or window_end,
                )
            )
    return matches


def evaluate_pattern(
    definition: PatternDefinition,
    events: list[dict],
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> list[RuleMatch]:
    """Per-event match: all `match` conditions hold AND none of the
    `exclude` conditions do. One RuleMatch per matching event (the
    group key names the event, e.g. `event=<uuid>`, since pattern rules
    have no natural grouping)."""
    matches: list[RuleMatch] = []
    for event in events:
        if not _in_window(event, window_start, window_end):
            continue
        if not all(condition_matches(event, c) for c in definition.match):
            continue
        if any(condition_matches(event, c) for c in definition.exclude):
            continue
        occurred = _occurred_at(event) or window_end
        matches.append(
            RuleMatch(
                group_key=f"event={event.get('id', 'unknown')}",
                event_ids=[str(event.get("id", ""))],
                window_start=occurred,
                window_end=occurred,
            )
        )
    return matches


def evaluate(rule_type: str, condition, events: list[dict], *, window_start: dt.datetime, window_end: dt.datetime) -> list[RuleMatch]:
    """Dispatch by rule type. `condition` is already a parsed definition
    (definitions.parse_definition)."""
    if isinstance(condition, ThresholdDefinition):
        return evaluate_threshold(condition, events, window_start=window_start, window_end=window_end)
    if isinstance(condition, SequenceDefinition):
        return evaluate_sequence(condition, events, window_start=window_start, window_end=window_end)
    if isinstance(condition, PatternDefinition):
        return evaluate_pattern(condition, events, window_start=window_start, window_end=window_end)
    raise ValueError(f"no evaluator for rule type '{rule_type}'")
