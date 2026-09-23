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

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import WorkerStatus

logger = logging.getLogger("sentinelx.worker")


async def heartbeat(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Cron job (every 30s via WorkerSettings): upsert the single
    worker_status row so the API (and the doctor) can answer "is the
    worker alive and when did it last tick?" without touching Redis.
    """
    now = dt.datetime.now(dt.timezone.utc)
    worker_name = os.environ.get("SENTINELX_WORKER_NAME", "worker-1")
    pid = os.getpid()

    async with AsyncSessionLocal() as db:
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


# The registry: both arq's function list and what enqueue_work() accepts.
JOB_FUNCTIONS = [heartbeat]


class WorkerSettings:
    """Passed to `arq app.worker.WorkerSettings` by the dev launcher."""

    functions = JOB_FUNCTIONS
    # Cron instead of a sleep-loop: arq schedules and re-fires it; also
    # survives worker restarts without losing the cadence.
    cron_jobs = [
        dict(cron=heartbeat, second={0, 30}, unique=True, run_at_startup=True),
    ]
    on_startup = "app.worker.jobs.on_startup"
    on_shutdown = "app.worker.jobs.on_shutdown"
    # Fail fast with a clear message instead of retrying forever when
    # Redis is unreachable -- the launcher surfaces the error text.
    max_jobs = 10
    job_timeout = 120
    keep_result = 3600
    health_check_interval = 15


async def on_startup(ctx: dict[str, Any]) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logger.info("worker starting (pid=%s, redis=%s)", os.getpid(), ctx.get("_redis_url", "configured"))

    # Prove Redis is reachable now, not on the first job -- a wrong
    # REDIS_URL should be a startup error, per the spec.
    pool = ctx.get("redis")
    if pool is None or not await pool.ping():
        raise RuntimeError(
            "Worker cannot reach Redis -- check settings.redis_url / REDIS_URL "
            f"and that the redis container is up (docker compose up -d redis)."
        )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker stopped gracefully (pid=%s)", os.getpid())
