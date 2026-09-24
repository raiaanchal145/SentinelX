"""
The process_events job (P07): normalize -> dedup -> enrich -> store.

The API enqueues a batch of validated records (see
app/routers/events.py / app/event_ingestion.py). This job:
  1. parses each record with its source-type parser
     (app/worker/parsers.py) into the normalized schema;
  2. computes the dedup hash over (organization, source, exact-second
     timestamp, type, host, user, ip, message) and inserts with
     ON CONFLICT DO NOTHING against
     uq_security_events_org_dedup_hash, so replaying the same batch
     adds zero rows;
  3. enriches with asset context -- asset_id, criticality and owner
     (into normalized_data) -- by hostname/IP match against the
     organization's assets;
  4. applies severity defaulting (hint > type default > info);
  5. stores raw_data (size-capped) and normalized_data.

Idempotent by construction: a replay recomputes identical hashes and
conflicts away. A vanished event source makes the whole batch a no-op
(the FK would cascade; nothing to attach events to).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.event_ingestion import (
    UNKNOWN_EVENT_TYPE,
    cap_raw_data,
    compute_dedup_hash_for_record,
    resolve_severity,
)
from app.models import Asset, SecurityEvent
from app.worker.parsers import parse_record

logger = logging.getLogger("sentinelx.worker")

# Event types that legitimately carry no asset context (no host/ip at all).
_ASSET_MATCH_FIELDS = ("host", "ip")


async def process_events(ctx: dict[str, Any], payload: dict) -> dict:
    """Job entry point: `enqueue_work("process_events", payload)`."""
    session_factory = ctx.get("session_factory")
    if session_factory is None:
        from app.database import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    organization_id = uuid.UUID(payload["organization_id"])
    event_source_id = uuid.UUID(payload["event_source_id"])
    records: list[dict] = payload.get("events", [])

    async with session_factory() as db:
        # The source must still exist and belong to the organization --
        # belt and braces: the API resolved both from the key, the worker
        # never trusts the payload alone.
        source_row = (
            await db.execute(
                text_query_event_source(event_source_id, organization_id)
            )
        ).first()
        if source_row is None:
            logger.warning(
                "process_events: event source %s for org %s vanished -- dropping batch of %d",
                event_source_id,
                organization_id,
                len(records),
            )
            return {"stored": 0, "duplicates": 0, "dropped": len(records)}

        # ---- Asset lookup cache ----------------------------------------
        asset_cache = await _load_asset_cache(db, organization_id)

        stored = 0
        duplicates = 0
        unknown_types = 0

        for record in records:
            occurred_at = _parse_occurred_at(record["timestamp"])
            if occurred_at is None:
                # The API validated it, but be defensive: skip rather than
                # store a NULL occurred_at.
                continue

            parsed = parse_record(record["source_type"], record)

            # Classification: parser-derived concrete type wins when the
            # parser recognized the raw content; unknown/unmappable ->
            # "other" with raw kept; unparseable -> keep the declared type.
            event_type = record["event_type"]
            if parsed.event_type is not None:
                event_type = parsed.event_type
            if event_type == UNKNOWN_EVENT_TYPE:
                unknown_types += 1

            host = record.get("host") or parsed.host
            user = record.get("user") or parsed.user
            ip = record.get("ip") or parsed.ip
            process_name = record.get("process") or parsed.process

            asset = _match_asset(asset_cache, host=host, ip=ip)

            severity = resolve_severity(record.get("severity_hint"), event_type)

            dedup_hash = compute_dedup_hash_for_record(
                organization_id=str(organization_id),
                record={**record, "host": host, "user": user, "ip": ip},
                occurred_at=occurred_at,
            )

            normalized = {
                "schema_version": record.get("schema_version", "1.0"),
                "source_type": record["source_type"],
                "event_type": event_type,
                "message": record["message"],
                "host": host,
                "user": user,
                "ip": ip,
                "process": process_name,
                "severity_hint": record.get("severity_hint"),
                "asset": {
                    "id": str(asset.id) if asset else None,
                    "criticality": asset.criticality.value if asset else None,
                    "owner_user_id": str(asset.owner_user_id) if asset and asset.owner_user_id else None,
                    "owner": asset.owner if asset else None,
                },
                "extracted": parsed.extracted or None,
            }

            stmt = pg_insert(SecurityEvent).values(
                id=uuid.uuid4(),
                organization_id=organization_id,
                event_source_id=event_source_id,
                asset_id=asset.id if asset else None,
                occurred_at=occurred_at,
                event_type=event_type,
                severity=severity,
                username=user,
                source_ip=ip,
                dedup_hash=dedup_hash,
                raw_data=cap_raw_data(record.get("raw") if record.get("raw") is not None else record),
                normalized_data=normalized,
            ).on_conflict_do_nothing(
                index_elements=["organization_id", "dedup_hash"]
            )
            result = await db.execute(stmt)
            if result.rowcount:
                stored += 1
            else:
                duplicates += 1

        await db.commit()
        logger.info(
            "process_events: org=%s source=%s stored=%d duplicates=%d unknown=%d",
            organization_id,
            event_source_id,
            stored,
            duplicates,
            unknown_types,
        )
        return {"stored": stored, "duplicates": duplicates, "unknown_types": unknown_types}


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def text_query_event_source(event_source_id, organization_id):
    from sqlalchemy import select

    from app.models import EventSource

    return select(EventSource.id).where(
        EventSource.id == event_source_id, EventSource.organization_id == organization_id
    )


def _parse_occurred_at(value: str) -> dt.datetime | None:
    from app.event_ingestion import parse_timestamp

    return parse_timestamp(value)


async def _load_asset_cache(db, organization_id) -> list:
    """The organization's active assets with a hostname or IP -- the only
    rows that can match an event by hostname/IP."""
    result = await db.execute(
        select(Asset).where(
            Asset.organization_id == organization_id,
            Asset.status == "active",
            Asset.hostname.isnot(None) | Asset.ip_address.isnot(None),
        )
    )
    return list(result.scalars().all())


def _match_asset(assets: list, *, host: str | None, ip: str | None):
    """Hostname match first (exact, case-insensitive), then IP. The cache
    is small in practice; revisit with a DB-side match only if orgs grow
    asset counts that make O(n) per event measurable."""
    if not host and not ip:
        return None
    if host:
        host_lower = host.lower()
        for asset in assets:
            if asset.hostname and asset.hostname.lower() == host_lower:
                return asset
    if ip:
        for asset in assets:
            if asset.ip_address and asset.ip_address == ip:
                return asset
    return None
