"""
Detection state store (P23): each (organization, rule, group) keeps a
sliding window of its recent matching events in Redis so the evaluators
can run incrementally as events arrive, without re-querying
security_events for the whole window on every batch.

Two interchangeable implementations:

- RedisWindowStore -- the worker's real store. One sorted-set key per
  (org, rule, group); members are the event ids, scores are the events'
  epoch timestamps. ZREMRANGEBYSCORE slides the window, ZCARD bounds
  memory, and every key carries the organization id in its name, so two
  organizations can never see each other's state (organization
  isolation is structural, the same stance as key isolation in
  ingestion).
- MemoryWindowStore -- same API over dicts, for unit tests (no Redis)
  and as a drop-in when Redis is down (a lost window can only delay a
  detection, never fabricate one; the events themselves are safe in
  Postgres).

Window entries are written ONLY for events matching the rule's own
event types -- an irrelevant event doesn't touch the state at all, so
the benign_noise scenario leaves the bruteforce rules' windows empty.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

logger = logging.getLogger("sentinelx.detection")

# Sorted sets larger than this get trimmed defensively; real windows
# (a rule's threshold + slack) are far smaller.
MAX_WINDOW_ENTRIES = 1000


def state_key(organization_id: str, rule_id: str, group_by: str, group_value: str) -> str:
    """The organization id is IN the key: isolation is structural."""
    return f"detection:window:{organization_id}:{rule_id}:{group_by}:{group_value}"


def _epoch(value: dt.datetime | str) -> float:
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.timestamp()


class RedisWindowStore:
    """Sliding windows in Redis sorted sets."""

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    async def add_events(
        self,
        *,
        organization_id: str,
        rule_id: str,
        group_by: str,
        events: list[dict[str, Any]],
    ) -> None:
        """Add events to their groups' windows and slide each touched
        window. Events must already match the rule's event types (the
        engine filters before calling); entries carry the full event
        JSON so the evaluator can inspect fields without a DB read."""
        by_group: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            from app.detection.definitions import group_key_for

            key_value = group_key_for(group_by, event)
            if key_value is None:
                continue
            by_group.setdefault(key_value, []).append(event)

        for group_value, group_events in by_group.items():
            key = state_key(organization_id, rule_id, group_by, group_value)
            mapping = {
                json.dumps(event, default=str): _epoch(event.get("occurred_at"))
                for event in group_events
                if event.get("occurred_at") is not None
            }
            if not mapping:
                continue
            pipe = self._redis.pipeline()
            pipe.zadd(key, mapping)
            pipe.zremrangebyrank(key, 0, -MAX_WINDOW_ENTRIES - 1)
            await pipe.execute()

    async def get_window_events(
        self,
        *,
        organization_id: str,
        rule_id: str,
        group_by: str,
        group_value: str,
        window_seconds: int,
        now: dt.datetime,
    ) -> list[dict[str, Any]]:
        """The group's events within [now - window, now], oldest first."""
        key = state_key(organization_id, rule_id, group_by, group_value)
        min_score = now.timestamp() - window_seconds
        raw = await self._redis.zrangebyscore(key, min_score, "+inf")
        events = [json.loads(item) for item in raw]
        events.sort(key=lambda e: _epoch(e.get("occurred_at")))
        return events

    async def slide(
        self,
        *,
        organization_id: str,
        rule_id: str,
        group_by: str,
        group_value: str,
        window_seconds: int,
        now: dt.datetime,
    ) -> None:
        key = state_key(organization_id, rule_id, group_by, group_value)
        await self._redis.zremrangebyscore(key, "-inf", now.timestamp() - window_seconds)


class MemoryWindowStore:
    """Same API over dicts -- unit tests and Redis-outage fallback."""

    def __init__(self) -> None:
        self._windows: dict[str, list[tuple[float, dict[str, Any]]]] = {}

    async def add_events(
        self,
        *,
        organization_id: str,
        rule_id: str,
        group_by: str,
        events: list[dict[str, Any]],
    ) -> None:
        from app.detection.definitions import group_key_for

        for event in events:
            key_value = group_key_for(group_by, event)
            if key_value is None or event.get("occurred_at") is None:
                continue
            key = state_key(organization_id, rule_id, group_by, key_value)
            self._windows.setdefault(key, []).append((_epoch(event["occurred_at"]), event))

    async def get_window_events(
        self,
        *,
        organization_id: str,
        rule_id: str,
        group_by: str,
        group_value: str,
        window_seconds: int,
        now: dt.datetime,
    ) -> list[dict[str, Any]]:
        key = state_key(organization_id, rule_id, group_by, group_value)
        min_score = now.timestamp() - window_seconds
        entries = sorted(self._windows.get(key, []), key=lambda pair: pair[0])
        return [event for score, event in entries if score >= min_score]

    async def slide(
        self,
        *,
        organization_id: str,
        rule_id: str,
        group_by: str,
        group_value: str,
        window_seconds: int,
        now: dt.datetime,
    ) -> None:
        key = state_key(organization_id, rule_id, group_by, group_value)
        min_score = now.timestamp() - window_seconds
        self._windows[key] = [
            (score, event) for score, event in self._windows.get(key, []) if score >= min_score
        ]


def build_store(redis_client=None):
    """Redis when a client is given (and reachable), the in-memory store
    otherwise -- a down Redis delays detections, it doesn't break the
    event pipeline (same degradation stance as the rate limit)."""
    if redis_client is not None:
        return RedisWindowStore(redis_client)
    logger.warning("Redis unavailable for detection state -- windows are in-memory for this run")
    return MemoryWindowStore()
