"""
Measure the events list query against 100k rows (P07 deliverable:
"measure the list query with 100k rows and tell me the timing").

Run against a THROWAWAY database (it creates/drops its own scratch DB):

    cd backend && ../.venv/Scripts/python scripts/measure_events_query.py

Seeds 100,000 security_events across 2 organizations (80k/20k), then
times the exact queries GET /api/v1/events issues:
  - unfiltered first page (keyset on org + occurred_at DESC, id DESC)
  - severity-filtered, asset-filtered, time-windowed, free-text
Each is run 5x after a warmup and reports min/median; EXPLAIN ANALYZE
is printed for the unfiltered and severity cases.
"""

import asyncio
import os
import statistics
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PAGE_SIZE = 50
TOTAL_ROWS = 100_000
ORG_A_SHARE = 0.8

EVENT_TYPES = ["auth_failure", "auth_success", "firewall_deny", "process_create", "test_event", "other"]
SEVERITIES = ["info", "low", "medium", "high", "critical"]


async def main() -> None:
    base_url = os.environ.get(
        "MEASURE_DATABASE_URL",
        "postgresql+asyncpg://sentinelx:sentinelx_dev_pw@localhost:5432/postgres",
    )
    scratch_name = f"sentinelx_measure_{uuid.uuid4().hex[:8]}"
    root, _, _ = base_url.rpartition("/")
    scratch_url = f"{root}/{scratch_name}"

    admin_engine = create_async_engine(base_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.begin() as conn:
        await conn.execute(text(f'CREATE DATABASE "{scratch_name}"'))
    await admin_engine.dispose()

    engine = create_async_engine(scratch_url, poolclass=None)
    try:
        await _run(engine, scratch_url)
    finally:
        await engine.dispose()
        admin_engine = create_async_engine(base_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.begin() as conn:
            # Force-drop: kill any lingering backend sessions first.
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": scratch_name},
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch_name}"'))
        await admin_engine.dispose()


async def _run(engine, scratch_url: str) -> None:
    now = datetime.now(timezone.utc)
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    src_a, src_b = uuid.uuid4(), uuid.uuid4()

    print(f"Seeding {TOTAL_ROWS:,} rows ...")
    t0 = time.perf_counter()
    # The severity enum must exist before the table can.
    check_engine = create_async_engine(scratch_url, isolation_level="AUTOCOMMIT")
    async with check_engine.connect() as conn:
        exists = (await conn.execute(
            text("SELECT 1 FROM pg_type WHERE typname = 'event_severity'")
        )).scalar()
        if not exists:
            await conn.execute(text("CREATE TYPE event_severity AS ENUM ('critical','high','medium','low','info')"))
    await check_engine.dispose()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE security_events (
                    id uuid PRIMARY KEY,
                    organization_id uuid NOT NULL,
                    event_source_id uuid NOT NULL,
                    asset_id uuid,
                    occurred_at timestamptz NOT NULL,
                    ingested_at timestamp DEFAULT now() NOT NULL,
                    event_type varchar(120) NOT NULL,
                    severity event_severity NOT NULL DEFAULT 'info',
                    username varchar(150),
                    source_ip varchar(64),
                    dedup_hash varchar(64),
                    raw_data jsonb,
                    normalized_data jsonb
                )
                """
            )
        )

    batch = []
    for i in range(TOTAL_ROWS):
        org = org_a if i < int(TOTAL_ROWS * ORG_A_SHARE) else org_b
        src = src_a if org == org_a else src_b
        ts = now - timedelta(seconds=i % (60 * 60 * 24 * 7))
        batch.append(
            {
                "id": uuid.uuid4(),
                "org": org,
                "src": src,
                "ts": ts,
                "etype": EVENT_TYPES[i % len(EVENT_TYPES)],
                "sev": SEVERITIES[i % len(SEVERITIES)],
                "user": f"user{i % 500}",
                "ip": f"10.{(i // 254) % 250}.{i % 254}.{(i * 7) % 254}",
            }
        )
    # Straight COPY-style insert via jsonb_to_recordset (unnest(jsonb)
    # needs a cast; jsonb_to_recordset is the cleaner bulk path).
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO security_events
                    (id, organization_id, event_source_id, occurred_at, event_type, severity, username, source_ip, dedup_hash, normalized_data)
                SELECT id, org, src, ts, etype, sev::event_severity, "user", ip, md5(id::text),
                       jsonb_build_object('message', 'seeded ' || (row_number() OVER () - 1)::text, 'detail', 'x')
                FROM jsonb_to_recordset(CAST(:batch AS jsonb))
                     AS t(id uuid, org uuid, src uuid, ts timestamptz, etype text, sev text, "user" text, ip text)
                """
            ),
            {"batch": _json_batch(batch)},
        )
    print(f"  seeded in {time.perf_counter() - t0:.1f}s")

    # Production indexes (migration f7a8b9c0d1e2 + the originals).
    async with engine.begin() as conn:
        await conn.execute(text("CREATE INDEX ix_seed_dedup ON security_events (dedup_hash)"))
        await conn.execute(text("CREATE UNIQUE INDEX uq_seed_dedup ON security_events (organization_id, dedup_hash)"))
        await conn.execute(text("CREATE INDEX ix_seed_org_occurred ON security_events (organization_id, occurred_at)"))
        await conn.execute(text("CREATE INDEX ix_seed_org_occurred_desc ON security_events (organization_id, occurred_at DESC)"))
        await conn.execute(text("CREATE INDEX ix_seed_org_sev ON security_events (organization_id, severity, occurred_at)"))
        await conn.execute(text("CREATE INDEX ix_seed_src ON security_events (event_source_id)"))
    await engine.dispose()

    engine = create_async_engine(scratch_url)
    try:
        queries = {
            "unfiltered first page": text(
                """
                SELECT * FROM security_events
                WHERE organization_id = :org
                ORDER BY occurred_at DESC, id DESC
                LIMIT :lim
                """
            ),
            "severity=high": text(
                """
                SELECT * FROM security_events
                WHERE organization_id = :org AND severity = 'high'
                ORDER BY occurred_at DESC, id DESC
                LIMIT :lim
                """
            ),
            "time window (24h)": text(
                """
                SELECT * FROM security_events
                WHERE organization_id = :org AND occurred_at >= :since
                ORDER BY occurred_at DESC, id DESC
                LIMIT :lim
                """
            ),
            "second page (keyset cursor)": text(
                """
                SELECT * FROM security_events
                WHERE organization_id = :org
                  AND (occurred_at, id) < (:cursor_ts, :cursor_id)
                ORDER BY occurred_at DESC, id DESC
                LIMIT :lim
                """
            ),
            "free-text q (JSONB ilike)": text(
                """
                SELECT * FROM security_events
                WHERE organization_id = :org
                  AND (event_type ILIKE :q OR username ILIKE :q
                       OR coalesce(normalized_data, raw_data)::text ILIKE :q)
                ORDER BY occurred_at DESC, id DESC
                LIMIT :lim
                """
            ),
        }
        params = {
            "org": str(org_a),
            "lim": PAGE_SIZE,
            "since": now - timedelta(hours=24),
            "cursor_ts": now - timedelta(minutes=5),
            "cursor_id": str(uuid.uuid4()),
            "q": "%seeded 42%",
        }

        for name, query in queries.items():
            # Warmup.
            async with engine.connect() as conn:
                await conn.execute(query, params)
            timings = []
            for _ in range(5):
                t0 = time.perf_counter()
                async with engine.connect() as conn:
                    rows = (await conn.execute(query, params)).fetchall()
                timings.append((time.perf_counter() - t0) * 1000)
            print(
                f"{name:32s} rows={len(rows):3d}  "
                f"min={min(timings):7.2f}ms  median={statistics.median(timings):7.2f}ms  max={max(timings):7.2f}ms"
            )

        async with engine.connect() as conn:
            plan = (await conn.execute(
                text("EXPLAIN ANALYZE " + queries["unfiltered first page"].text), params
            )).fetchall()
            print("\nEXPLAIN ANALYZE (unfiltered first page):")
            for row in plan:
                print("  " + row[0])
    finally:
        await engine.dispose()


def _json_batch(rows: list[dict]) -> str:
    import json

    return json.dumps(rows, default=str)


if __name__ == "__main__":
    asyncio.run(main())
