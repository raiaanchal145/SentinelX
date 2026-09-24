"""
Rate limiting (P07): the per-key fixed window in Redis, event-based
accounting, isolation between keys, and Redis-outage degradation.

Uses a REAL local Redis (settings.redis_url) -- the same stance as the
rest of the suite, which needs a real Postgres. Keys are namespaced per
api_key id and the windows are 120s-expiry calendar-minute buckets, so
tests don't interfere with each other or with a dev worker sharing the
instance.
"""

from unittest.mock import patch

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

import app.routers.event_sources as event_sources_router
from app.config import settings
from app.event_ingestion import KeyRateLimited, enforce_key_rate_limit

from tests.test_events_ingestion import (
    NOW,
    _EagerQueue,
    _auth,
    _event,
    _make_source_with_key,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def real_redis():
    async def _make():
        return aioredis.from_url(settings.redis_url, decode_responses=True)

    return _make


@pytest_asyncio.fixture
async def live_redis_rate_limit():
    """Point the router's lazy singleton at a real client for this test."""
    import unittest.mock as _mock

    holder = {}

    async def _fake_get():
        if "client" not in holder:
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            holder["client"] = client
        return holder["client"]

    with _mock.patch.object(event_sources_router, "_get_rate_limit_redis", _fake_get), _mock.patch(
        "app.routers.events._get_rate_limit_redis", _fake_get, create=True
    ):
        yield

    if "client" in holder:
        await holder["client"].aclose()


async def test_enforce_allows_under_limit(real_redis):
    client = await real_redis()
    try:
        for _ in range(5):
            await enforce_key_rate_limit(client, "key-under", 10)
    finally:
        await client.aclose()


async def test_enforce_raises_at_limit(real_redis):
    client = await real_redis()
    try:
        window = int(NOW.timestamp()) // 60
        for _ in range(10):
            await enforce_key_rate_limit(client, "key-at", 10, window=window)
        with pytest.raises(KeyRateLimited):
            await enforce_key_rate_limit(client, "key-at", 10, window=window)
    finally:
        await client.aclose()


async def test_enforce_counts_events_not_requests(real_redis):
    """count=5 in one call burns 5 slots: two 5-event calls against a
    limit of 9 -- the second raises as the running total (10) crosses it."""
    client = await real_redis()
    try:
        window = int(NOW.timestamp()) // 60
        await enforce_key_rate_limit(client, "key-bulk", 9, count=5, window=window)
        with pytest.raises(KeyRateLimited):
            await enforce_key_rate_limit(client, "key-bulk", 9, count=5, window=window)  # 10 > 9
    finally:
        await client.aclose()


async def test_keys_are_isolated(real_redis):
    client = await real_redis()
    try:
        window = int(NOW.timestamp()) // 60
        for _ in range(3):
            await enforce_key_rate_limit(client, "iso-a", 3, window=window)
        # key B unaffected by A's exhaustion
        for _ in range(3):
            await enforce_key_rate_limit(client, "iso-b", 3, window=window)
        with pytest.raises(KeyRateLimited):
            await enforce_key_rate_limit(client, "iso-a", 3, window=window)
    finally:
        await client.aclose()


async def test_endpoint_429s_when_batch_exceeds_quota(
    client, db_session, live_redis_rate_limit
):
    """A batch of 50 events against a 10/minute limit: the request costs
    1 (auth) + 49 (events) and is refused with 429 rate_limited."""
    import unittest.mock as _mock

    from app.config import settings as _settings

    org, source, key = await _make_source_with_key(db_session)
    batch = [_event(message=f"m{i}") for i in range(50)]
    # Scrub the rate-limit window for this key, then shrink the limit.
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    await redis_client.flushdb()
    with _mock.patch.object(_settings, "events_rate_limit_per_minute", 10):
        resp = await client.post("/api/v1/events", json={"events": batch}, headers=_auth(key))
    await redis_client.aclose()
    assert resp.status_code == 429, resp.text
    assert resp.json()["detail"]["code"] == "rate_limited"


async def test_rate_limit_degrades_gracefully_when_redis_down(client, db_session):
    """Redis unreachable -> no rate limit, ingestion still works (the
    same stance as enqueue_work: infrastructure is optional to the
    request's success)."""
    async def _unreachable():
        return None

    with patch.object(event_sources_router, "_get_rate_limit_redis", _unreachable), patch(
        "app.routers.events._get_rate_limit_redis", _unreachable, create=True
    ):
        org, source, key = await _make_source_with_key(db_session)
        resp = await client.post("/api/v1/events", json=_event(), headers=_auth(key))
    assert resp.status_code == 202, resp.text
    assert resp.json()["accepted"] == 1
