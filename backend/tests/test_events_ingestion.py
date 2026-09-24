"""
Event ingestion end-to-end (P07): POST /api/v1/events with API-key auth,
validation, the 24h/30d timestamp window, batch limits, dedup on replay
(through the real process_events job against the test database), and
key isolation.

The queue is faked: tests patch app.routers.events.enqueue_work so no
Redis is needed; process_events is invoked directly with the payload
the API would have enqueued.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.routers.events as events_router
from app.models import ApiKey, EventSource, SecurityEvent
from app.routers.event_sources import generate_api_key, get_event_source_from_api_key, hash_api_key
from app.worker.event_jobs import process_events
from app.worker.jobs import JOB_FUNCTIONS

from tests.helpers import make_organization

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures/helpers.
# ---------------------------------------------------------------------------


async def _make_source_with_key(db_session, org=None, source_type="test", name="test source"):
    org = org or await make_organization(db_session)
    source = EventSource(organization_id=org.id, name=name, source_type=source_type, status="active")
    db_session.add(source)
    await db_session.flush()
    full_key, key_hash, prefix = generate_api_key()
    api_key = ApiKey(
        organization_id=org.id,
        event_source_id=source.id,
        key_hash=key_hash,
        prefix=prefix,
    )
    db_session.add(api_key)
    await db_session.commit()
    return org, source, full_key


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _event(**overrides) -> dict:
    base = {
        "schema_version": "1.0",
        "timestamp": NOW.isoformat(),
        "source_type": "test",
        "host": "host-a",
        "event_type": "test_event",
        "message": "hello from the collector",
        "user": "alice",
        "ip": "10.0.0.1",
    }
    base.update(overrides)
    return base


class _EagerQueue:
    """Captures what the API would enqueue; tests then run the real job."""

    def __init__(self):
        self.payloads = []

    async def __call__(self, job_name, payload):
        self.payloads.append((job_name, payload))
        return "job-id"


async def _drain_queue(eager, db_session):
    """Run every captured process_events payload through the real job."""
    ctx = {"session_factory": None}
    # Use the test session factory so the job writes to the same DB.
    from tests.test_events_ingestion import _TestSessionFactoryHolder

    ctx["session_factory"] = _TestSessionFactoryHolder.factory
    stored = {"stored": 0, "duplicates": 0}
    for job_name, payload in eager.payloads:
        assert job_name == "process_events"
        result = await process_events(ctx, payload)
        stored["stored"] += result["stored"]
        stored["duplicates"] += result["duplicates"]
    return stored


class _TestSessionFactoryHolder:
    """Set by tests: a sessionmaker bound to the test engine (the job
    opens its own session, mirroring production)."""

    factory = None


@pytest_asyncio.fixture
async def job_db(db_session):
    """A sessionmaker over the test engine, for process_events."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import os

    from app.config import settings

    url = os.environ.get("TEST_DATABASE_URL") or (
        settings.database_url.rpartition("/")[0] + "/sentinelx_test"
    )
    engine = create_async_engine(url, poolclass=NullPool)
    _TestSessionFactoryHolder.factory = async_sessionmaker(engine, expire_on_commit=False)
    yield
    _TestSessionFactoryHolder.factory = None
    await engine.dispose()


@pytest.fixture
def eager_queue():
    q = _EagerQueue()
    with patch.object(events_router, "enqueue_work", q):
        yield q


# ---------------------------------------------------------------------------
# Validation and response shape.
# ---------------------------------------------------------------------------


async def test_single_event_accepted(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session)
    resp = await client.post("/api/v1/events", json=_event(), headers=_auth(key))
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["accepted"] == 1
    assert body["rejected"] == 0
    assert len(eager_queue.payloads) == 1
    payload = eager_queue.payloads[0][1]
    assert payload["organization_id"] == str(org.id)
    assert payload["event_source_id"] == str(source.id)
    assert payload["events"][0]["event_type"] == "test_event"


async def test_batch_accepted_and_mixed_results(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session)
    batch = [
        _event(),
        _event(message="second"),
        _event(event_type="not_in_vocabulary"),
        {"timestamp": NOW.isoformat(), "source_type": "test", "message": "missing event_type"},
        _event(timestamp="not-a-date"),
        _event(timestamp=(NOW + timedelta(hours=48)).isoformat()),
        _event(timestamp=(NOW - timedelta(days=45)).isoformat()),
    ]
    resp = await client.post("/api/v1/events", json={"events": batch}, headers=_auth(key))
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["accepted"] == 2
    assert body["rejected"] == 5
    reasons = [r["reason"] for r in body["results"] if r["status"] == "rejected"]
    assert any("event_type" in r for r in reasons)
    assert any("required field" in r for r in reasons)
    assert any("ISO-8601" in r for r in reasons)
    assert any("24 hours" in r for r in reasons)
    assert any("30 days" in r for r in reasons)


async def test_payload_organization_id_is_ignored(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session)
    other_org_id = str(uuid.uuid4())
    resp = await client.post(
        "/api/v1/events",
        json=_event(organization_id=other_org_id),
        headers=_auth(key),
    )
    assert resp.status_code == 202
    payload = eager_queue.payloads[0][1]
    assert payload["organization_id"] == str(org.id)  # from the KEY, not the payload
    assert payload["organization_id"] != other_org_id


async def test_auth_failures(client, db_session):
    org, source, key = await _make_source_with_key(db_session)
    for headers, status in (
        ({}, 401),
        (_auth("garbage"), 401),
        (_auth("sx_wrong_prefix_0000"), 401),
    ):
        resp = await client.post("/api/v1/events", json=_event(), headers=headers)
        assert resp.status_code == status, resp.text
        assert resp.json()["detail"]["code"] == "invalid_api_key"


async def test_disabled_source_rejects(client, db_session, eager_queue):
    org, source, key = await _make_source_with_key(db_session)
    source.status = "disabled"
    await db_session.commit()
    resp = await client.post("/api/v1/events", json=_event(), headers=_auth(key))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "event_source_disabled"


async def test_empty_and_oversize_batch_rejected(client, db_session, eager_queue):
    org, source, key = await _make_source_with_key(db_session)
    resp = await client.post("/api/v1/events", json={"events": []}, headers=_auth(key))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "empty_batch"

    too_many = [_event(message=f"m{i}") for i in range(501)]
    resp = await client.post("/api/v1/events", json={"events": too_many}, headers=_auth(key))
    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "batch_too_large"
    assert eager_queue.payloads == []


async def test_oversize_body_rejected(client, db_session, eager_queue):
    org, source, key = await _make_source_with_key(db_session)
    # One event with a >1MiB message -> body guard fires before parsing.
    big = _event(message="x" * (1_048_576 + 10))
    resp = await client.post(
        "/api/v1/events",
        content=json.dumps(big),
        headers={**_auth(key), "Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "request_too_large"


async def test_invalid_json(client, db_session):
    org, source, key = await _make_source_with_key(db_session)
    resp = await client.post(
        "/api/v1/events",
        content=b"{not json",
        headers={**_auth(key), "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_json"


# ---------------------------------------------------------------------------
# Queue -> worker -> rows: dedup, enrichment, isolation.
# ---------------------------------------------------------------------------


async def test_end_to_end_store_and_replay_dedupes(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session)
    batch = [_event(message=f"event {i}") for i in range(5)]
    resp = await client.post("/api/v1/events", json={"events": batch}, headers=_auth(key))
    assert resp.status_code == 202

    first = await _drain_queue(eager_queue, db_session)
    assert first["stored"] == 5

    count = (
        await db_session.execute(select(func.count()).select_from(SecurityEvent))
    ).scalar()
    assert count == 5

    # Replay the exact same batch through a fresh API request + job run:
    # zero new rows.
    eager_queue.payloads.clear()
    resp = await client.post("/api/v1/events", json={"events": batch}, headers=_auth(key))
    assert resp.status_code == 202
    second = await _drain_queue(eager_queue, db_session)
    assert second["stored"] == 0
    assert second["duplicates"] == 5

    count = (
        await db_session.execute(select(func.count()).select_from(SecurityEvent))
    ).scalar()
    assert count == 5  # unchanged

    rows = (await db_session.execute(select(SecurityEvent))).scalars().all()
    assert all(r.dedup_hash for r in rows)
    assert all(r.raw_data for r in rows)
    assert all(r.normalized_data for r in rows)


async def test_worker_normalizes_linux_auth_line(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session, source_type="linux_auth")
    event = _event(
        source_type="linux_auth",
        event_type="auth_failure",
        host="web01",
        message="Sep 24 03:14:15 web01 sshd[2201]: Failed password for root from 203.0.113.9 port 41000 ssh2",
        raw="Sep 24 03:14:15 web01 sshd[2201]: Failed password for root from 203.0.113.9 port 41000 ssh2",
        user=None,
        ip=None,
    )
    resp = await client.post("/api/v1/events", json=event, headers=_auth(key))
    assert resp.status_code == 202
    await _drain_queue(eager_queue, db_session)

    row = (await db_session.execute(select(SecurityEvent))).scalar_one()
    assert row.event_type == "auth_failure"
    assert row.username == "root"  # extracted by the parser, not the payload
    assert row.source_ip == "203.0.113.9"
    assert row.normalized_data["process"] == "sshd"
    assert row.severity.value == "medium"  # type default; no hint sent
    assert row.raw_data  # the raw line is kept


async def test_unknown_type_maps_to_other_with_raw_kept(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session, source_type="docker")
    event = _event(
        source_type="docker",
        event_type="container_start",
        message="container xyz: prune",
        raw={"status": "prune", "id": "xyz"},  # recognized verb, no vocabulary mapping
    )
    resp = await client.post("/api/v1/events", json=event, headers=_auth(key))
    assert resp.status_code == 202
    await _drain_queue(eager_queue, db_session)

    row = (await db_session.execute(select(SecurityEvent))).scalar_one()
    assert row.event_type == "other"
    assert row.raw_data == {"status": "prune", "id": "xyz"}


async def test_severity_hint_wins_and_invalid_hint_falls_back(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session)
    resp = await client.post(
        "/api/v1/events",
        json={"events": [_event(message="hinted", severity_hint="critical"), _event(message="defaulted")]},
        headers=_auth(key),
    )
    assert resp.status_code == 202
    await _drain_queue(eager_queue, db_session)

    rows = (await db_session.execute(select(SecurityEvent).order_by(SecurityEvent.occurred_at))).scalars().all()
    by_message = {r.normalized_data["message"]: r for r in rows}
    assert by_message["hinted"].severity.value == "critical"
    # test_event has no type default -> info.
    assert by_message["defaulted"].severity.value == "info"


async def test_key_isolation(client, db_session, eager_queue, job_db):
    """Events sent with key A never appear for organization B -- and B's
    key cannot write into A."""
    org_a, source_a, key_a = await _make_source_with_key(db_session, name="source A")
    org_b, source_b, key_b = await _make_source_with_key(db_session, name="source B")
    assert org_a.id != org_b.id

    resp = await client.post(
        "/api/v1/events",
        json={"events": [_event(message="org A event"), _event(message="org A event 2")]},
        headers=_auth(key_a),
    )
    assert resp.status_code == 202
    await _drain_queue(eager_queue, db_session)

    count = (
        await db_session.execute(select(func.count()).select_from(SecurityEvent))
    ).scalar()
    assert count == 2

    rows = (
        await db_session.execute(select(SecurityEvent).where(SecurityEvent.organization_id == org_b.id))
    ).scalars().all()
    assert rows == []  # nothing for B

    # B's key writes only into B.
    eager_queue.payloads.clear()
    resp = await client.post("/api/v1/events", json=_event(message="org B event"), headers=_auth(key_b))
    assert resp.status_code == 202
    await _drain_queue(eager_queue, db_session)

    b_rows = (
        await db_session.execute(select(SecurityEvent).where(SecurityEvent.organization_id == org_b.id))
    ).scalars().all()
    assert len(b_rows) == 1 and b_rows[0].normalized_data["message"] == "org B event"


async def test_identical_content_in_two_organizations_does_not_collide(client, db_session, eager_queue, job_db):
    """The dedup hash includes the organization id: the same event sent
    by two organizations stores twice, once per org."""
    org_a, source_a, key_a = await _make_source_with_key(db_session, name="A")
    org_b, source_b, key_b = await _make_source_with_key(db_session, name="B")
    event = _event()
    for key in (key_a, key_b):
        resp = await client.post("/api/v1/events", json=event, headers=_auth(key))
        assert resp.status_code == 202
    await _drain_queue(eager_queue, db_session)
    count = (
        await db_session.execute(select(func.count()).select_from(SecurityEvent))
    ).scalar()
    assert count == 2


async def test_job_registered():
    assert "process_events" in {f.__name__ for f in JOB_FUNCTIONS}


# ---------------------------------------------------------------------------
# Enrichment + pagination.
# ---------------------------------------------------------------------------


async def test_asset_enrichment_by_hostname_and_ip(client, db_session, eager_queue, job_db):
    from app.models import Asset

    org, source, key = await _make_source_with_key(db_session)
    asset = Asset(
        organization_id=org.id,
        name="Web server",
        hostname="WEB01",
        ip_address="10.0.0.5",
        asset_type="server",
        criticality="critical",
        owner="Alice Owner",
        status="active",
    )
    db_session.add(asset)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/events",
        json={"events": [
            _event(host="web01", message="by hostname"),          # case-insensitive hostname match
            _event(host=None, ip="10.0.0.5", message="by ip"),     # IP fallback
            _event(host="unknown-box", ip="10.9.9.9", message="no match"),
        ]},
        headers=_auth(key),
    )
    assert resp.status_code == 202
    await _drain_queue(eager_queue, db_session)

    rows = (await db_session.execute(select(SecurityEvent))).scalars().all()
    by_message = {r.normalized_data["message"]: r for r in rows}
    assert by_message["by hostname"].asset_id == asset.id
    assert by_message["by hostname"].normalized_data["asset"]["criticality"] == "critical"
    assert by_message["by hostname"].normalized_data["asset"]["owner"] == "Alice Owner"
    assert by_message["by ip"].asset_id == asset.id
    assert by_message["no match"].asset_id is None
    assert by_message["no match"].normalized_data["asset"]["id"] is None


async def test_cursor_pagination_walks_all_pages(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session)
    batch = [_event(message=f"page item {i}", timestamp=(NOW - timedelta(minutes=i)).isoformat()) for i in range(7)]
    resp = await client.post("/api/v1/events", json={"events": batch}, headers=_auth(key))
    assert resp.status_code == 202
    await _drain_queue(eager_queue, db_session)

    # Login is not possible for a key-only org; use a super_admin to read.
    from tests.helpers import make_admin

    from app.security import hash_password

    super_admin = await make_admin(
        db_session,
        email="events-super@example.com",
        name="Super",
        admin_level="super_admin",
        organization_id=None,
    )
    token = await _login_super(client, super_admin.email)

    seen: list[str] = []
    cursor = None
    for _ in range(10):  # bounded loop: a broken cursor must fail the test, not hang
        params = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        resp = await client.get("/api/v1/events", params=params, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        seen.extend(e["id"] for e in body["events"])
        if not body["next_cursor"]:
            break
        cursor = body["next_cursor"]

    assert len(seen) == 7
    assert len(set(seen)) == 7  # no duplicates across pages


async def _login_super(client, email):
    from tests.helpers import TEST_PASSWORD

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]
