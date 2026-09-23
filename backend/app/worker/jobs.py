"""Job registry and the heartbeat job.

Every job is an async function taking (ctx, ...) and registered in
JOB_FUNCTIONS, which is both the arq worker's function list and the
authority for what enqueue_work() accepts by name. Keep jobs small,
idempotent, and resilient to the row they touch having vanished.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

from arq.cron import cron
from sqlalchemy import select

from app.models import WorkerStatus

logger = logging.getLogger("sentinelx.worker")


async def heartbeat(ctx: dict[str, Any], session_factory=None) -> dict[str, Any]:
    """
    Cron job (every 30s via WorkerSettings): upsert the single
    worker_status row so the API (and the doctor) can answer "is the
    worker alive and when did it last tick?" without touching Redis.

    The session factory comes from ctx (WorkerSettings.on_startup puts
    the app's there), so tests can inject their own; the app default is
    the fallback for direct calls.
    """
    now = dt.datetime.now(dt.timezone.utc)
    worker_name = os.environ.get("SENTINELX_WORKER_NAME", "worker-1")
    pid = os.getpid()

    if session_factory is None:
        session_factory = ctx.get("session_factory")
    if session_factory is None:
        from app.database import AsyncSessionLocal  # lazy: keep module import light

        session_factory = AsyncSessionLocal

    async with session_factory() as db:
        row = (await db.execute(select(WorkerStatus).where(WorkerStatus.id == 1))).scalar_one_or_none()
        if row is None:
            row = WorkerStatus(id=1)
            db.add(row)
        row.last_heartbeat_at = now
        row.worker_name = worker_name
        row.pid = pid
        await db.commit()

    logger.info("heartbeat ok (pid=%s)", pid)
    return {"last_heartbeat_at": now.isoformat(), "worker_name": worker_name, "pid": pid}


async def on_startup(ctx: dict[str, Any]) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # Jobs resolve their DB session through ctx so tests (and any future
    # second worker) can inject a different session factory.
    from app.database import AsyncSessionLocal

    ctx["session_factory"] = AsyncSessionLocal
    logger.info("worker starting (pid=%s, redis=%s)", os.getpid(), ctx.get("_redis_url", "configured"))

    # Prove Redis is reachable now, not on the first job -- a wrong
    # REDIS_URL should be a startup error, per the spec.
    pool = ctx.get("redis")
    if pool is None or not await pool.ping():
        raise RuntimeError(
            "Worker cannot reach Redis -- check settings.redis_url / REDIS_URL "
            "and that the redis container is up (docker compose up -d redis)."
        )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker stopped gracefully (pid=%s)", os.getpid())


# The registry: both arq's function list and what enqueue_work() accepts.
JOB_FUNCTIONS = [heartbeat]


class WorkerSettings:
    """Passed to `arq app.worker.WorkerSettings` by the dev launcher."""

    functions = JOB_FUNCTIONS
    # Cron instead of a sleep-loop: arq schedules and re-fires it; also
    # survives worker restarts without losing the cadence. run_at_startup
    # writes one heartbeat immediately so a fresh worker is visible right
    # away instead of up to 30s later.
    cron_jobs = [
        cron(heartbeat, second={0, 30}, unique=True, run_at_startup=True),
    ]
    # Direct function references -- arq calls these objects itself.
    on_startup = on_startup
    on_shutdown = on_shutdown
    # Fail fast with a clear message instead of retrying forever when
    # Redis is unreachable -- the launcher surfaces the error text.
    max_jobs = 10
    job_timeout = 120
    keep_result = 3600
    health_check_interval = 15
