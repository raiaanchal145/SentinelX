"""Queue access for the API side: enqueue jobs without blocking the event
loop. The pool is created lazily on first use and shared for the process
lifetime; tests can patch enqueue_work or pass an explicit eager queue.
"""

from __future__ import annotations

import logging
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings

logger = logging.getLogger(__name__)

_pool: Any | None = None


def _redis_settings() -> RedisSettings:
    """Parse settings.redis_url into arq's RedisSettings."""
    return RedisSettings.from_dsn(settings.redis_url)


async def get_arq_pool() -> Any:
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue_work(job_name: str, *args: Any, **kwargs: Any) -> str | None:
    """
    Enqueue a registered job by name. Returns the arq job id (useful for
    logs/tests) or None when running with the fake/eager queue injected
    by tests (they patch this function directly).

    Never raises on a Redis outage -- background work is optional to a
    request's success; a dropped enqueue is logged and the API keeps
    serving. (The worker's own startup, by contrast, fails fast.)
    """
    try:
        pool = await get_arq_pool()
        job = await pool.enqueue_job(job_name, *args, **kwargs)
        return job.job_id if job else None
    except Exception:  # noqa: BLE001 -- deliberate: enqueue must not 500 a request
        logger.exception("enqueue_work(%s) failed -- is Redis reachable?", job_name)
        return None
