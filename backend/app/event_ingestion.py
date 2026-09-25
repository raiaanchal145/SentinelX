"""
Event ingestion shared logic (P07, docs/API_CONTRACT.md "Event ingestion"):

- the fixed event_type vocabulary and the normalized event schema every
  collector's payload is validated against;
- the per-key fixed-window Redis rate limit implementing the
  `rate_limit_for_key` stub that P06 left in event_sources.py;
- the dedup hash the worker deduplicates replays with, and the
  severity-defaulting rules applied at normalization time.

Kept free of FastAPI imports so the worker can use it too.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from app.models import EventSeverity, EventSourceType

# ---------------------------------------------------------------------------
# The fixed event_type vocabulary.
#
# Collectors send `event_type` from this list; anything else is rejected at
# the API with a per-item reason (the payload is versioned -- schema_version
# bumps when this list or the field rules change, and the worker keeps
# honoring older versions it knows). A type not on the list cannot be
# "forced through" as something cleverer: unknown-to-the-vocabulary values
# never reach the worker, while KNOWN types whose raw record doesn't parse
# map to "other" there with the raw record kept verbatim.
# ---------------------------------------------------------------------------

EVENT_TYPE_VOCABULARY: dict[str, str] = {
    # linux_auth
    "auth_success": "Authentication succeeded (ssh, su, sudo, local login).",
    "auth_failure": "Authentication failed (wrong password, refused key).",
    "sudo_command": "A sudo command was run.",
    "user_add": "A user account was created.",
    "user_delete": "A user account was deleted.",
    "group_change": "Group membership changed.",
    "package_install": "A package was installed or upgraded.",
    # application
    "app_error": "Application error log entry.",
    "app_warning": "Application warning log entry.",
    "app_login": "Application-level user login.",
    "app_login_failed": "Application-level failed login.",
    "config_change": "Application configuration changed.",
    "permission_change": "Permissions on an application resource changed.",
    "api_request": "API request log entry.",
    "api_error": "API 5xx/error log entry.",
    # docker
    "container_start": "A container started.",
    "container_stop": "A container stopped.",
    "container_kill": "A container was killed (OOM, SIGKILL).",
    "container_create": "A container was created.",
    "container_destroy": "A container was removed.",
    "image_pull": "An image was pulled.",
    "image_push": "An image was pushed.",
    "docker_daemon_event": "Docker daemon-level event.",
    # network
    "firewall_allow": "Firewall allowed a connection.",
    "firewall_deny": "Firewall denied/blocked a connection.",
    "port_scan": "A scan pattern was detected upstream.",
    "ids_alert": "An IDS/IPS raised a signature alert.",
    "connection_allowed": "Flow record: connection permitted.",
    "connection_blocked": "Flow record: connection blocked/dropped.",
    "dns_query": "DNS query observed.",
    "dns_response": "DNS response observed.",
    # windows (the P21 endpoint agent)
    "logon_success": "Windows logon succeeded (4624).",
    "logon_failure": "Windows logon failed (4625).",
    "process_create": "A process was created (4688).",
    "service_install": "A service was installed (7045).",
    "account_created": "A user account was created (4720).",
    "account_disabled": "A user account was disabled (4722).",
    "account_lockout": "An account was locked out (4740).",
    "log_cleared": "The Windows event log was cleared (1102).",
    "policy_change": "A local/security policy changed.",
    "scheduled_task": "A scheduled task was created/registered.",
    # custom_json / test / fallback
    "custom": "Custom JSON feed record.",
    "test_event": "Synthetic test-data event.",
    "other": "Anything recognizable as an event but not classifiable.",
}

# The vocabulary flattened -- validation order-stable dict keys in 3.7+.
EVENT_TYPES: frozenset[str] = frozenset(EVENT_TYPE_VOCABULARY)

# severity values as plain strings, for the events-API filter check.
EVENT_SEVERITY_VALUES: frozenset[str] = frozenset(s.value for s in EventSeverity)

# Unknown-classification fallback: a known type whose raw record the parser
# can't structure maps here, keeping the raw record intact.
UNKNOWN_EVENT_TYPE = "other"

# ---------------------------------------------------------------------------
# The versioned normalized schema.
#
# schema_version "1.0": every record carries these fields. `required` fields
# must be present and well-typed; `optional` fields may be null/omitted but
# must be well-typed when present. `event_type` must be in the fixed
# vocabulary above; `source_type` in the EventSourceType list.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0"

REQUIRED_STRING_FIELDS = ("timestamp", "source_type", "event_type", "message")
OPTIONAL_STRING_FIELDS = ("host", "asset", "user", "severity_hint", "ip", "process")


def _is_blank(v: object) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def validate_event_record(record: object) -> tuple[dict | None, str | None]:
    """
    Validate one event record against schema_version 1.0.

    Returns (clean_record, None) or (None, reason). The clean record is the
    exact shape enqueue_work ships to the worker; `raw` is preserved
    verbatim (stringified if the collector sent something non-object) so
    the worker's parsers can re-read it.
    """
    if not isinstance(record, dict):
        return None, "event must be a JSON object"

    missing = [f for f in REQUIRED_STRING_FIELDS if _is_blank(record.get(f))]
    if missing:
        return None, "missing required field(s): " + ", ".join(missing)

    for field in REQUIRED_STRING_FIELDS + OPTIONAL_STRING_FIELDS:
        value = record.get(field)
        if value is not None and not isinstance(value, str):
            return None, f"field '{field}' must be a string"

    source_type = record["source_type"].strip()
    valid_source_types = {s.value for s in EventSourceType}
    if source_type not in valid_source_types:
        return None, f"unknown source_type '{source_type}' -- must be one of: {', '.join(sorted(valid_source_types))}"

    event_type = record["event_type"].strip()
    if event_type not in EVENT_TYPES:
        return None, (
            f"unknown event_type '{event_type}' -- must be one of the fixed vocabulary "
            f"(see docs/API_CONTRACT.md)"
        )

    hint = _clean(record.get("severity_hint"))
    if hint is not None and hint not in {s.value for s in EventSeverity}:
        return None, f"severity_hint must be one of: {', '.join(s.value for s in EventSeverity)}"

    return {
        "schema_version": record.get("schema_version", SCHEMA_VERSION),
        "timestamp": record["timestamp"].strip(),
        "source_type": source_type,
        "host": _clean(record.get("host")),
        "asset": _clean(record.get("asset")),
        "event_type": event_type,
        "severity_hint": hint,
        "user": _clean(record.get("user")),
        "ip": _clean(record.get("ip")),
        "process": _clean(record.get("process")),
        "message": record["message"].strip(),
        # JSON round-trip: preserves any nested object the collector sent.
        "raw": record.get("raw"),
    }, None


# ---------------------------------------------------------------------------
# Timestamps.
# ---------------------------------------------------------------------------

MAX_FUTURE_SKEW = timedelta(hours=24)      # reject timestamps > 24h in the future
MAX_PAST_AGE = timedelta(days=30)          # reject timestamps older than 30 days


def parse_timestamp(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp; naive values are read as UTC."""
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def timestamp_window_check(now: datetime, occurred_at: datetime) -> str | None:
    """The 24h-future / 30d-past rule. Returns a rejection reason or None."""
    if occurred_at > now + MAX_FUTURE_SKEW:
        return "timestamp is more than 24 hours in the future"
    if occurred_at < now - MAX_PAST_AGE:
        return "timestamp is older than 30 days"
    return None


# ---------------------------------------------------------------------------
# Severity defaulting (applied at normalization time, in the worker).
#
# Priority: the record's severity_hint > the event_type's default > "info".
# ---------------------------------------------------------------------------

SEVERITY_DEFAULTS: dict[str, EventSeverity] = {
    "auth_failure": EventSeverity.medium,
    "sudo_command": EventSeverity.low,
    "user_add": EventSeverity.low,
    "user_delete": EventSeverity.medium,
    "group_change": EventSeverity.low,
    "package_install": EventSeverity.info,
    "app_error": EventSeverity.medium,
    "app_warning": EventSeverity.low,
    "app_login": EventSeverity.info,
    "app_login_failed": EventSeverity.medium,
    "config_change": EventSeverity.medium,
    "permission_change": EventSeverity.medium,
    "api_error": EventSeverity.medium,
    "firewall_deny": EventSeverity.low,
    "port_scan": EventSeverity.high,
    "ids_alert": EventSeverity.high,
    "connection_blocked": EventSeverity.low,
    "logon_failure": EventSeverity.medium,
    "process_create": EventSeverity.info,
    "service_install": EventSeverity.high,
    "account_lockout": EventSeverity.medium,
    "log_cleared": EventSeverity.critical,
    "policy_change": EventSeverity.medium,
    "scheduled_task": EventSeverity.low,
}


def resolve_severity(severity_hint: str | None, event_type: str) -> EventSeverity:
    """severity_hint wins; then the type default; else info."""
    if severity_hint:
        try:
            return EventSeverity(severity_hint)
        except ValueError:
            pass
    return SEVERITY_DEFAULTS.get(event_type, EventSeverity.info)


# ---------------------------------------------------------------------------
# Dedup hash.
#
# (organization, source, timestamp bucket, type, host, user, ip, message).
# The timestamp bucket is the event's exact timestamp truncated to whole
# seconds: byte-identical timestamps deduplicate, anything differing by even
# one second is a distinct event (the team's explicit choice -- see
# docs/DECISIONS.md). organization is the UUID string from the API key, so
# two organizations can never collide on identical content.
# ---------------------------------------------------------------------------

DEDUP_FIELDS = ("source_type", "event_type", "host", "user", "ip", "message")


def compute_dedup_hash(
    organization_id: str,
    source_type: str,
    event_type: str,
    occurred_at: datetime,
    host: str | None,
    user: str | None,
    ip: str | None,
    message: str,
) -> str:
    bucket = occurred_at.replace(microsecond=0).isoformat()
    parts = [
        organization_id,
        source_type,
        bucket,
        event_type,
        host or "",
        user or "",
        ip or "",
        message,
    ]
    payload = "\x1f".join(parts)  # unit-separator join: message can contain anything
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Per-key rate limiting -- the fixed-window Redis implementation of the
# `rate_limit_for_key` stub P06 left in event_sources.py.
# ---------------------------------------------------------------------------


async def enforce_key_rate_limit(
    redis, api_key_id: str, limit_per_minute: int, count: int = 1, window: int | None = None
) -> None:
    """
    Fixed window per API key: one counter per key per calendar minute,
    INCRBY `count` + 120s expiry, atomic via a single pipeline. Raises
    KeyRateLimited when the window's quota is exhausted.

    Accounting (docs/DECISIONS.md "Rate limit counts events, not
    requests"): the request itself consumes one slot at authentication
    time (the P06 rate_limit_for_key seam -- a flood of pure-garbage
    requests still burns slots), and the endpoint consumes the remaining
    len(accepted)-1 slots after validation, so single-event requests
    cost exactly 1 and a batch of N costs exactly N. `window` is
    injectable for tests (defaults to the current calendar minute).

    `redis` is an asyncio redis client. Called from the API request path;
    a Redis outage does NOT block ingestion (same stance as enqueue_work:
    the queue is optional to a request's success).
    """
    if window is None:
        window = int(datetime.now(timezone.utc).timestamp()) // 60
    key = f"ratelimit:events:{api_key_id}:{window}"

    pipe = redis.pipeline()
    pipe.incrby(key, max(1, count))
    pipe.expire(key, 120)
    results = await pipe.execute()
    total = int(results[0])

    if total > limit_per_minute:
        retry_after = 60 - (int(datetime.now(timezone.utc).timestamp()) % 60)
        raise KeyRateLimited(retry_after=retry_after)


class KeyRateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"rate limited, retry after {retry_after}s")


# ---------------------------------------------------------------------------
# Worker-side helpers.
# ---------------------------------------------------------------------------

# raw_data is stored size-capped so a single giant record can't bloat the
# hot table: the worker keeps the first 64 KB of the serialized raw record.
MAX_RAW_JSON_BYTES = 64 * 1024


def cap_raw_data(raw: object) -> dict:
    """Cap the stored raw record at MAX_RAW_JSON_BYTES; oversize keeps a
    placeholder with the size noted instead of the full payload."""
    try:
        serialized = json.dumps(raw, default=str)
    except (TypeError, ValueError):
        serialized = json.dumps({"unserializable_raw": str(raw)[:1024]})
    if len(serialized.encode("utf-8")) <= MAX_RAW_JSON_BYTES:
        return {"raw": raw} if not isinstance(raw, dict) else raw
    return {
        "raw_truncated": True,
        "raw_size_bytes": len(serialized.encode("utf-8")),
        "raw_preview": serialized[: MAX_RAW_JSON_BYTES // 2],
    }


def compute_dedup_hash_for_record(
    organization_id: str, record: dict, occurred_at: datetime
) -> str:
    """Convenience wrapper over compute_dedup_hash for validated records."""
    return compute_dedup_hash(
        organization_id=organization_id,
        source_type=record["source_type"],
        event_type=record["event_type"],
        occurred_at=occurred_at,
        host=record.get("host"),
        user=record.get("user"),
        ip=record.get("ip"),
        message=record["message"],
    )
