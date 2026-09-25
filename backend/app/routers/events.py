"""
Event ingestion + the events read API (P07, docs/API_CONTRACT.md
"Event ingestion").

POST /api/v1/events -- collectors authenticate with an event-source API
key (`Authorization: Bearer sx_...`, same mechanism as P06), submit one
event or a batch, and get 202 with per-item accept/reject results. The
endpoint does no heavy work: validation is cheap, and accepted records
are handed to the Arq worker through enqueue_work. A dropped enqueue is
logged and the request still succeeds (the response carries an
X-Ingestion-Warning header) -- background work is optional to a
request's success, same stance as the rest of the queue layer.

Limits (settings, defaults): batches of at most 500 events, request body
of at most 1 MiB (checked before parsing), 600 events/key/minute as a
fixed window in Redis (see rate_limit_for_key in event_sources.py).
Timestamps must be ISO-8601 and within -30 days / +24 hours of now.

Trust rules:
  - organization_id ALWAYS comes from the API key's event source. An
    organization_id in the payload is ignored -- it is never even read.
  - One key = one event source = one organization. Key isolation is
    structural, not a filter the queries can get wrong.

GET /api/v1/events and GET /api/v1/events/{id} -- the human side,
user-token auth, module `soc` read, visibility through
soc_visible_organization_ids(): super_admin sees everything, a platform
SOC analyst their assigned managed+active organizations, an in-house
organization's accounts their own organization (a managed organization's
own accounts see nothing -- platform SOC staff do; the owner's read-only
oversight under managed mode falls out of effective access). Cursor
pagination is keyset on (occurred_at DESC, id DESC).
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import String, false as sqlalchemy_false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_module
from app.config import settings
from app.database import get_db
from app.event_ingestion import (
    EVENT_SEVERITY_VALUES,
    EVENT_TYPES,
    SCHEMA_VERSION,
    parse_timestamp,
    timestamp_window_check,
    validate_event_record,
)
from app.models import EventSeverity, SecurityEvent
from app.scope import Scope
from app.worker.queue import enqueue_work

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


# ---------------------------------------------------------------------------
# Ingestion (API-key auth -- no user login).
# ---------------------------------------------------------------------------


@router.post("", status_code=202)
async def ingest_events(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict:
    from app.routers.event_sources import get_event_source_from_api_key

    # ---- Size guard, before reading/parsing the body --------------------
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.events_max_request_bytes:
        raise _err("request_too_large", "Request body exceeds 1 MiB.", 413)

    body_bytes = await request.body()
    if len(body_bytes) > settings.events_max_request_bytes:
        raise _err("request_too_large", "Request body exceeds 1 MiB.", 413)

    try:
        payload = json.loads(body_bytes or b"")
    except (ValueError, UnicodeDecodeError):
        raise _err("invalid_json", "Request body is not valid JSON.", 400)

    # One event or a batch: all three shapes are accepted.
    if isinstance(payload, dict) and "events" in payload:
        records = payload["events"]
        if not isinstance(records, list):
            raise _err("invalid_batch", "'events' must be a list of event objects.", 400)
    elif isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = [payload]
    else:
        raise _err("invalid_batch", "Body must be an event object or a batch.", 400)

    if not records:
        raise _err("empty_batch", "No events submitted.", 400)
    if len(records) > settings.events_max_batch_size:
        raise _err("batch_too_large", f"Batch exceeds {settings.events_max_batch_size} events.", 413)

    # ---- Authentication: the key decides the organization ---------------
    # (After the cheap size/shape guards so garbage requests never touch
    # the DB; the key check itself is a single indexed lookup, and it
    # enforces the per-key rate limit and last_used_at.)
    event_source, _api_key = await get_event_source_from_api_key(db, authorization)

    async def _consume_rate_limit(_db, _key, _count):
        """Top up the rate-limit counter for events beyond the one the
        auth-time call already counted. Re-raises 429 when the batch
        pushes the key past its per-minute quota."""
        from app.config import settings as _settings
        from app.event_ingestion import KeyRateLimited as _KRL
        from app.event_ingestion import enforce_key_rate_limit as _enforce
        from app.routers.event_sources import _get_rate_limit_redis

        client = await _get_rate_limit_redis()
        if client is None:
            return
        try:
            await _enforce(client, str(_key.id), _settings.events_rate_limit_per_minute, count=_count)
        except _KRL as exc:
            raise _err("rate_limited", "Too many events for this API key this minute.", 429) from exc

    # ---- Per-item validation --------------------------------------------
    now_utc = datetime.now(timezone.utc)
    accepted: list[dict] = []
    results: list[dict] = []
    for index, record in enumerate(records):
        clean, reason = validate_event_record(record)
        if clean is None:
            results.append({"index": index, "status": "rejected", "reason": reason})
            continue

        occurred_at = parse_timestamp(clean["timestamp"])
        if occurred_at is None:
            results.append({"index": index, "status": "rejected", "reason": "timestamp is not a valid ISO-8601 value"})
            continue

        window_reason = timestamp_window_check(now_utc, occurred_at)
        if window_reason is not None:
            results.append({"index": index, "status": "rejected", "reason": window_reason})
            continue

        accepted.append(clean)
        results.append({"index": index, "status": "accepted"})

    # ---- Event-based accounting (the request itself already consumed 1)
    if len(accepted) > 1:
        await _consume_rate_limit(db, _api_key, len(accepted) - 1)

    if accepted:
        enqueued = await enqueue_work(
            "process_events",
            {
                "organization_id": str(event_source.organization_id),
                "event_source_id": str(event_source.id),
                "source_name": event_source.name,
                "schema_version": SCHEMA_VERSION,
                "events": accepted,
            },
        )
        if enqueued is None:
            # enqueue_work already logged the Redis failure. The client
            # still gets 202 for the validated events -- with a warning
            # header so the collector knows the batch needs re-sending.
            response.headers["X-Ingestion-Warning"] = "queued=false; queue unreachable, re-send this batch"

    return {
        "status": "accepted" if accepted else "no_acceptable_events",
        "accepted": len(accepted),
        "rejected": len(results) - len(accepted),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Read API (user-token auth, module `soc` read).
# ---------------------------------------------------------------------------


def _require_soc_read():
    """Dependency factory: module `soc` read for organization accounts.
    super_admin and platform_soc_analyst pass the underlying org_scope
    chain by design (require_module lets platform accounts through) --
    their visibility is decided per query by soc_visible_organization_ids
    in the handlers below."""
    return require_module("soc", write=False)


_soc_read = _require_soc_read()


async def _organization_filter_scope(
    db: AsyncSession, scope: Scope, organization_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Validate the list endpoints' optional organization_id filter
    (used by super_admin / platform SOC to scope the UI to one org).
    Unchecked, it would be a visibility bypass; the rule matches the
    assets router: an id the caller cannot see is a 404
    `organization_not_found` (existence never leaked), not a 403. A
    caller with a single visible organization (an org account) passing
    that id is fine -- it's a no-op for them."""
    if organization_id is None:
        return None
    from app.models import Organization

    mode, org_ids = await _event_visibility(db, scope)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to events for this organization.", 403)
    # "orgs" callers must name one of THEIR organizations; "all"
    # callers (super_admin) may name anything that exists at all -- an
    # unknown id is a 404 either way, so a guessed id reveals nothing.
    if mode == "orgs" and organization_id not in (org_ids or []):
        raise _err("organization_not_found", "Organization not found.", 404)
    if mode == "all":
        exists = (
            await db.execute(
                select(Organization.id).where(Organization.id == organization_id)
            )
        ).scalar_one_or_none()
        if exists is None:
            raise _err("organization_not_found", "Organization not found.", 404)
    return organization_id


async def _event_visibility(db: AsyncSession, scope: Scope) -> tuple[str, list[uuid.UUID] | None]:
    """
    Which events may this caller see (docs/API_CONTRACT.md "Event
    ingestion" -- access matrix):

      ("all", None)       super_admin: every organization.
      ("orgs", ids)       platform SOC: assigned managed+active orgs;
                          an organization owner: their own org
                          (read-only oversight -- `soc` read was already
                          enforced by the dependency; managed mode
                          grants read, in-house write).
      ("empty", None)     a platform SOC analyst with zero assigned orgs:
                          200 with an empty list (like any other list).
      ("forbidden", None) anyone else with no visibility (e.g. a managed
                          organization's own non-owner accounts):
                          403.

    soc_visible_organization_ids() deliberately returns [] for managed
    organizations' own accounts (platform SOC staff work those orgs);
    the owner's read-only oversight is the one exception, restored here.
    """
    from app.access import soc_visible_organization_ids
    from app.models import AdminLevel

    visible = await soc_visible_organization_ids(db, scope)
    if visible is None:
        return "all", None

    if scope.account_type == "admin" and scope.role == AdminLevel.organization_admin.value:
        return "orgs", [scope.organization_id]

    if visible:
        return "orgs", list(visible)

    if scope.role == AdminLevel.platform_soc_analyst.value:
        return "empty", None
    return "forbidden", None


@router.get("/summary")
async def events_summary(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_soc_read),
    time_from: str | None = None,
    time_to: str | None = None,
    source_id: uuid.UUID | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    asset_id: uuid.UUID | None = None,
    user: str | None = None,
    ip: str | None = None,
    q: str | None = None,
    organization_id: uuid.UUID | None = None,
    buckets: int = 12,
    bucket_hours: int = 2,
):
    """Aggregates for the SOC Overview tile: total events in the window
    plus severity- and type-breakdowns and `buckets` time buckets of
    `bucket_hours` each, ending now (the frontend draws the sparkline
    from these). Same filters and the same visibility rules as the list
    endpoint -- one indexed aggregate query instead of the frontend
    paging through everything. Defined BEFORE /{event_id} so "summary"
    is never parsed as an event id."""
    mode, org_ids = await _event_visibility(db, scope)
    if mode == "empty":
        return _empty_summary(buckets)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to events for this organization.", 403)

    if organization_id is not None:
        if mode == "orgs" and organization_id not in (org_ids or []):
            raise _err("organization_not_found", "Organization not found.", 404)
        if mode == "all":
            from app.models import Organization

            exists = (
                await db.execute(
                    select(Organization.id).where(Organization.id == organization_id)
                )
            ).scalar_one_or_none()
            if exists is None:
                raise _err("organization_not_found", "Organization not found.", 404)
        org_filter = [organization_id]
    else:
        org_filter = org_ids if mode == "orgs" else None

    buckets = max(1, min(buckets, 48))
    bucket_hours = max(1, min(bucket_hours, 720))
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(hours=bucket_hours * buckets)

    query = select(SecurityEvent)
    if org_filter is not None:
        query = query.where(SecurityEvent.organization_id.in_(org_filter))
    query = query.where(SecurityEvent.occurred_at >= window_start)
    # The optional filters reuse the list endpoint's validation by
    # sharing the filter-building helper below.
    query = _apply_event_filters(
        query,
        time_from=time_from,
        time_to=time_to,
        source_id=source_id,
        event_type=event_type,
        severity=severity,
        asset_id=asset_id,
        user=user,
        ip=ip,
        q=q,
    )

    rows = (
        await db.execute(
            select(
                SecurityEvent.occurred_at,
                SecurityEvent.severity,
                SecurityEvent.event_type,
            ).from_statement(query)
        )
    ).all()

    by_severity: dict[str, int] = {}
    by_type: dict[str, int] = {}
    timeline = [0] * buckets
    for occurred_at, severity_value, event_type_value in rows:
        sev = severity_value.value if hasattr(severity_value, "value") else str(severity_value)
        by_severity[sev] = by_severity.get(sev, 0) + 1
        by_type[event_type_value] = by_type.get(event_type_value, 0) + 1
        bucket_ms = bucket_hours * 3600
        age_seconds = (now_utc - occurred_at).total_seconds()
        index = buckets - 1 - int(age_seconds // (bucket_ms))
        if 0 <= index < buckets:
            timeline[index] += 1

    return {
        "total": len(rows),
        "bucket_hours": bucket_hours,
        "buckets": buckets,
        "timeline": timeline,
        "by_severity": by_severity,
        "by_type": by_type,
    }


def _empty_summary(buckets: int) -> dict:
    return {
        "total": 0,
        "bucket_hours": 2,
        "buckets": buckets,
        "timeline": [0] * buckets,
        "by_severity": {},
        "by_type": {},
    }


@router.get("")
async def list_events(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_soc_read),
    time_from: str | None = None,
    time_to: str | None = None,
    source_id: uuid.UUID | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    asset_id: uuid.UUID | None = None,
    user: str | None = None,
    ip: str | None = None,
    q: str | None = None,
    organization_id: uuid.UUID | None = None,
    limit: int = 50,
    cursor: str | None = None,
):
    mode, org_ids = await _event_visibility(db, scope)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to events for this organization.", 403)

    organization_id = await _organization_filter_scope(db, scope, organization_id)

    query = select(SecurityEvent)
    if mode == "all":
        if organization_id is not None:
            query = query.where(SecurityEvent.organization_id == organization_id)
    elif mode == "orgs":
        effective_orgs = [organization_id] if organization_id is not None else org_ids
        query = query.where(SecurityEvent.organization_id.in_(effective_orgs))
    elif mode == "empty":
        query = query.where(sqlalchemy_false())

    # ---- Filters (shared with /summary) ----------------------------------
    query = _apply_event_filters(
        query,
        time_from=time_from,
        time_to=time_to,
        source_id=source_id,
        event_type=event_type,
        severity=severity,
        asset_id=asset_id,
        user=user,
        ip=ip,
        q=q,
    )

    # ---- Cursor pagination: keyset on (occurred_at DESC, id DESC) -------
    limit = max(1, min(limit, 200))
    if cursor:
        cursor_ts, cursor_id = _decode_cursor(cursor)
        query = query.where(
            or_(
                SecurityEvent.occurred_at < cursor_ts,
                (SecurityEvent.occurred_at == cursor_ts) & (SecurityEvent.id < cursor_id),
            )
        )

    query = query.order_by(SecurityEvent.occurred_at.desc(), SecurityEvent.id.desc()).limit(limit + 1)
    rows = (await db.execute(query)).scalars().all()

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.occurred_at, last.id)

    return {
        "events": [_event_row(e, include_raw=False) for e in rows],
        "next_cursor": next_cursor,
    }


def _apply_event_filters(
    query,
    *,
    time_from: str | None,
    time_to: str | None,
    source_id: uuid.UUID | None,
    event_type: str | None,
    severity: str | None,
    asset_id: uuid.UUID | None,
    user: str | None,
    ip: str | None,
    q: str | None,
):
    """The optional WHERE clauses shared by the list and summary
    endpoints -- validation and shapes must stay identical between them."""
    if time_from:
        ts = parse_timestamp(time_from)
        if ts is None:
            raise _err("invalid_time_range", "time_from is not a valid ISO-8601 timestamp.")
        query = query.where(SecurityEvent.occurred_at >= ts)
    if time_to:
        ts = parse_timestamp(time_to)
        if ts is None:
            raise _err("invalid_time_range", "time_to is not a valid ISO-8601 timestamp.")
        query = query.where(SecurityEvent.occurred_at <= ts)
    if source_id is not None:
        query = query.where(SecurityEvent.event_source_id == source_id)
    if event_type:
        if event_type not in EVENT_TYPES:
            raise _err("invalid_event_type", f"event_type must be one of the fixed vocabulary.")
        query = query.where(SecurityEvent.event_type == event_type)
    if severity:
        if severity not in EVENT_SEVERITY_VALUES:
            raise _err("invalid_severity", "severity must be one of critical|high|medium|low|info.")
        query = query.where(SecurityEvent.severity == EventSeverity(severity))
    if asset_id is not None:
        query = query.where(SecurityEvent.asset_id == asset_id)
    if user:
        query = query.where(SecurityEvent.username.ilike(f"%{user}%"))
    if ip:
        query = query.where(SecurityEvent.source_ip == ip)
    if q:
        like = f"%{q}%"
        # The message lives inside the JSONB payloads; coalesce to the
        # normalized copy, fall back to raw, and search the text form.
        blob = func.coalesce(SecurityEvent.normalized_data, SecurityEvent.raw_data).cast(String)
        query = query.where(
            or_(
                SecurityEvent.event_type.ilike(like),
                SecurityEvent.username.ilike(like),
                SecurityEvent.source_ip.ilike(like),
                blob.ilike(like),
            )
        )
    return query


@router.get("/{event_id}")
async def get_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_soc_read),
):
    mode, org_ids = await _event_visibility(db, scope)
    event = (
        await db.execute(select(SecurityEvent).where(SecurityEvent.id == event_id))
    ).scalar_one_or_none()
    visible = (
        mode == "all"
        or (mode == "orgs" and event is not None and event.organization_id in org_ids)
    )
    if event is None or not visible:
        # 404 either way: another organization's event existence is never leaked.
        raise _err("event_not_found", "Event not found.", 404)
    return _event_row(event, include_raw=True)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _encode_cursor(occurred_at: datetime, event_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"t": occurred_at.isoformat(), "id": str(event_id)}).encode()
    ).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["id"])
    except Exception:  # noqa: BLE001 -- a bad cursor is just "invalid cursor"
        raise _err("invalid_cursor", "cursor is not a valid pagination token.", 400)


def _event_row(event: SecurityEvent, *, include_raw: bool) -> dict:
    row = {
        "id": str(event.id),
        "organization_id": str(event.organization_id),
        "event_source_id": str(event.event_source_id),
        "asset_id": str(event.asset_id) if event.asset_id else None,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "ingested_at": event.ingested_at.isoformat() if event.ingested_at else None,
        "event_type": event.event_type,
        "severity": event.severity.value if hasattr(event.severity, "value") else event.severity,
        "username": event.username,
        "source_ip": event.source_ip,
        "normalized_data": event.normalized_data,
    }
    if include_raw:
        row["raw_data"] = event.raw_data
    return row
