"""One datetime rule for the whole backend (P15): every Python datetime
is timezone-aware UTC, every stored point in time is TIMESTAMPTZ, and
API time filters accept ISO strings with "Z", an explicit offset, or
naive (treated as UTC).

Use these helpers everywhere instead of raw datetime.now()/utcnow():
- `utcnow()` -- the only "current time" any code needs.
- `ensure_utc(dt)` -- normalize a value that may be naive (legacy rows,
  test fixtures) or carry any offset into aware UTC before comparing,
  storing, or doing arithmetic with it.
- `parse_query_time(value, field)` -- the query-parameter parser every
  list endpoint shares (Z / offset / naive-as-UTC), raising the
  project's structured 400 `invalid_time_range` for garbage input.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException


def utcnow() -> datetime:
    """The current time, timezone-aware UTC. The single sanctioned
    replacement for datetime.now()/utcnow()."""
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Coerce `value` to an aware UTC datetime. Naive values are
    interpreted AS UTC (that is what every writer of the pre-P15 naive
    columns meant); offsets are converted. Idempotent."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_query_time(value: str, field: str) -> datetime:
    """Parse a time-range query parameter. Accepts ISO-8601 with "Z",
    with an explicit offset, or naive (treated as UTC); always returns
    aware UTC. Malformed values raise 400 invalid_time_range with the
    offending field named -- never a 500."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_time_range",
                "message": f"{field} is not a valid ISO-8601 timestamp.",
            },
        )
    return ensure_utc(parsed)


def require_ordered_range(time_from: datetime | None, time_to: datetime | None) -> None:
    """A from/to pair with from > to is a client mistake, not an empty
    result -- reject it with a clear 422 so the UI can say so instead of
    showing a silently empty page."""
    if time_from is not None and time_to is not None and time_from > time_to:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_time_range",
                "message": "time_from must not be after time_to.",
            },
        )
