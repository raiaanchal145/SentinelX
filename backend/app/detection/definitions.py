"""
Detection rule definitions (P23): the JSON schema every rule's
`condition` column must satisfy, validated by Pydantic. Rules are DATA
-- a rule is a row in detection_rules, not code -- so adding or tuning
a detection never ships Python; only the three evaluator functions are
code. Custom rule creation (P24) will validate against these same
models.

Three rule types (DetectionRuleType in app/models.py):

- threshold: N events of (one or more) event types within a window,
  grouped by user/ip/host. Fires when any group's count reaches
  `threshold` inside `window_seconds`.
- sequence: an ORDERED list of event types within a window for the
  same group key. Fires when the last type arrives after the earlier
  ones, in order, inside the window.
- pattern: field-match filters (allowlist/blocklist). Fires when an
  event matches a `match` expression and nothing on its `exclude`
  list (e.g. a known service account allowlist).

Every definition carries its own `window_seconds` (60..86400) and an
optional `group_by` ("user" | "ip" | "host"; default "user" for
threshold/sequence, None for pattern -- pattern matches per event).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

GROUP_BY_KEYS = ("user", "ip", "host")

WINDOW_MIN_SECONDS = 60
WINDOW_MAX_SECONDS = 24 * 3600


class ThresholdDefinition(BaseModel):
    """N events of `event_types` within `window_seconds`, grouped by
    `group_by`. `threshold` >= 2 (a 1-of-type rule is a pattern rule)."""

    rule_kind: Literal["threshold"] = "threshold"
    event_types: list[str] = Field(min_length=1)
    threshold: int = Field(ge=2, le=10_000)
    window_seconds: int = Field(ge=WINDOW_MIN_SECONDS, le=WINDOW_MAX_SECONDS)
    group_by: Literal["user", "ip", "host"] = "user"
    # Severity hint overrides are NOT part of the definition -- a rule's
    # severity lives on the DetectionRule row, editable there.

    @field_validator("event_types")
    @classmethod
    def _types_nonempty(cls, value: list[str]) -> list[str]:
        cleaned = [t.strip() for t in value if t and t.strip()]
        if not cleaned:
            raise ValueError("event_types must contain at least one non-blank type")
        return cleaned


class SequenceStep(BaseModel):
    event_type: str = Field(min_length=1)
    # Optional filter: only events whose listed fields match these exact
    # values count toward this step (e.g. process=cmd.exe).
    fields: dict[str, str] = Field(default_factory=dict)


class SequenceDefinition(BaseModel):
    """Ordered `steps` (2..5) within `window_seconds` for the same
    `group_by` key. Events may interleave with other activity; only the
    order of matching steps matters."""

    rule_kind: Literal["sequence"] = "sequence"
    steps: list[SequenceStep] = Field(min_length=2, max_length=5)
    window_seconds: int = Field(ge=WINDOW_MIN_SECONDS, le=WINDOW_MAX_SECONDS)
    group_by: Literal["user", "ip", "host"] = "user"

    @model_validator(mode="after")
    def _same_type_not_adjacent(self) -> "SequenceDefinition":
        if all(step.event_type == self.steps[0].event_type for step in self.steps):
            raise ValueError("a sequence of identical event types is a threshold rule, not a sequence")
        return self


class PatternCondition(BaseModel):
    """One field matcher: the event's field (from the normalized view --
    event_type, username, source_ip, host, process, or raw.<key> /
    normalized.<key> paths) must equal / contain / start with / regex-
    match the value."""

    field: str = Field(min_length=1)
    op: Literal["eq", "contains", "starts_with", "ends_with", "regex"]
    value: str = Field(min_length=1)


class PatternDefinition(BaseModel):
    """Per-event match: all `match` conditions must hold (AND) and none
    of the `exclude` conditions may hold. `exclude` implements
    allowlists (e.g. skip a scheduled backup account) and blocklists
    (e.g. always skip events from a known-scanner host)."""

    rule_kind: Literal["pattern"] = "pattern"
    match: list[PatternCondition] = Field(min_length=1)
    exclude: list[PatternCondition] = Field(default_factory=list)


Definition = ThresholdDefinition | SequenceDefinition | PatternDefinition


def parse_definition(rule_type: str, condition: dict[str, Any]) -> Definition:
    """Validate a rule row's condition against its rule_type. Raises
    pydantic.ValidationError on a mismatch -- the worker skips (and
    logs) an invalid rule rather than crashing the batch."""
    if rule_type == "threshold":
        return ThresholdDefinition.model_validate(condition)
    if rule_type == "sequence":
        return SequenceDefinition.model_validate(condition)
    if rule_type == "pattern":
        return PatternDefinition.model_validate(condition)
    raise ValueError(f"unknown rule_type '{rule_type}'")


def group_key_for(group_by: str, event: dict[str, Any]) -> str | None:
    """The grouping key for an event, or None when the event has no
    value for that key (an event without a username can't be grouped
    by user -- it is skipped for the rule, not treated as one shared
    None group, which would correlate unrelated events)."""
    if group_by == "user":
        value = event.get("username") or event.get("user")
    elif group_by == "ip":
        value = event.get("source_ip") or event.get("ip")
    elif group_by == "host":
        value = event.get("host")
    else:
        return None
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return str(value)


def event_field(event: dict[str, Any], path: str) -> str | None:
    """Resolve a pattern condition's field path against the normalized
    view of an event. Top-level names hit the normalized columns; a
    `raw.<key>` / `normalized.<key>` prefix digs into the JSONB blobs
    (one level deep -- enough for the vocabulary's fields)."""
    if path.startswith("raw."):
        value = (event.get("raw") or {}).get(path[4:])
    elif path.startswith("normalized."):
        value = (event.get("normalized") or {}).get(path[11:])
    elif path in ("user", "username"):
        value = event.get("username") or event.get("user")
    elif path == "ip":
        value = event.get("source_ip") or event.get("ip")
    else:
        value = event.get(path)
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def condition_matches(event: dict[str, Any], condition: PatternCondition) -> bool:
    actual = event_field(event, condition.field)
    if actual is None:
        return False
    expected = condition.value
    if condition.op == "eq":
        return actual == expected
    if condition.op == "contains":
        return expected in actual
    if condition.op == "starts_with":
        return actual.startswith(expected)
    if condition.op == "ends_with":
        return actual.endswith(expected)
    if condition.op == "regex":
        import re

        try:
            return re.search(expected, actual) is not None
        except re.error:
            return False  # an invalid regex in a definition matches nothing
    return False
