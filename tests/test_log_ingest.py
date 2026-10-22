"""
SentinelX QA Test Suite: Log Ingestion & Validation.

Module: LOG
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

import datetime as dt
from unittest.mock import patch
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiKey, EventSource
from app.routers.event_sources import generate_api_key
from backend.tests.helpers import make_organization
from tc import tc


async def _create_test_event_source(db_session: AsyncSession, org=None):
    if org is None:
        org = await make_organization(db_session, name="LogIngestOrg")
    source = EventSource(organization_id=org.id, name="Syslog Collector", source_type="linux_auth", status="active")
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


@tc(
    id="LOG-01",
    module="LogIngest",
    description="Ingest single valid log event returns 202 Accepted",
    preconditions="Active event source with valid API key exists",
    steps="POST /api/v1/events with well-formed log event payload and API key",
    expected="Response status 202 with 1 accepted event and 0 rejected",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_log_01_ingest_single_event(client: AsyncClient, db_session: AsyncSession):
    org, source, api_key = await _create_test_event_source(db_session)
    now_str = dt.datetime.now(dt.timezone.utc).isoformat()

    payload = {
        "events": [
            {
                "schema_version": "1.0",
                "timestamp": now_str,
                "source_type": "linux_auth",
                "event_type": "auth_success",
                "message": "Accepted publickey for ubuntu from 192.168.1.100 port 54321 ssh2",
                "host": "prod-auth-01",
                "user": "ubuntu",
                "ip": "192.168.1.100",
            }
        ]
    }

    with patch("app.routers.events.enqueue_work", return_value=None):
        resp = await client.post(
            "/api/v1/events",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )

    assert resp.status_code == 202
    data = resp.json()
    assert data["accepted"] == 1
    assert data["rejected"] == 0


@tc(
    id="LOG-02",
    module="LogIngest",
    description="Malformed log payload (missing required message) is rejected",
    preconditions="Active event source API key",
    steps="POST /api/v1/events with missing required 'message' field",
    expected="Response reports item rejected with validation error explanation",
    type="automated",
    owner="Riteka Singh",
)
@pytest.mark.asyncio
async def test_log_02_ingest_malformed_event(client: AsyncClient, db_session: AsyncSession):
    org, source, api_key = await _create_test_event_source(db_session)
    now_str = dt.datetime.now(dt.timezone.utc).isoformat()

    payload = {
        "events": [
            {
                "schema_version": "1.0",
                "timestamp": now_str,
                "source_type": "linux_auth",
                "event_type": "auth_success",
                # missing "message"
                "user": "ubuntu",
            }
        ]
    }

    with patch("app.routers.events.enqueue_work", return_value=None):
        resp = await client.post(
            "/api/v1/events",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )

    assert resp.status_code == 202
    data = resp.json()
    assert data["accepted"] == 0
    assert data["rejected"] == 1
    assert "errors" in data or "results" in data


@tc(
    id="LOG-03",
    module="LogIngest",
    description="Batch ingestion processes multiple log events in single request",
    preconditions="Active event source API key",
    steps="POST /api/v1/events with 5 valid log records",
    expected="Response status 202 with accepted=5 and rejected=0",
    type="automated",
    owner="Aanchal Rai",
)
@pytest.mark.asyncio
async def test_log_03_batch_ingestion(client: AsyncClient, db_session: AsyncSession):
    org, source, api_key = await _create_test_event_source(db_session)
    now = dt.datetime.now(dt.timezone.utc)

    events = [
        {
            "schema_version": "1.0",
            "timestamp": (now - dt.timedelta(seconds=i * 10)).isoformat(),
            "source_type": "linux_auth",
            "event_type": "auth_failure" if i % 2 == 0 else "auth_success",
            "message": f"Log event number {i}",
            "host": "srv-web",
            "user": f"user_{i}",
        }
        for i in range(5)
    ]

    with patch("app.routers.events.enqueue_work", return_value=None):
        resp = await client.post(
            "/api/v1/events",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"events": events},
        )

    assert resp.status_code == 202
    data = resp.json()
    assert data["accepted"] == 5
    assert data["rejected"] == 0


@tc(
    id="LOG-04",
    module="LogIngest",
    description="Unauthorized request without valid Bearer API key is rejected",
    preconditions="Client with unrecognized API key",
    steps="POST /api/v1/events with unrecognized API key",
    expected="Response status 401 or 400 rejecting unauthorized event ingestion",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_log_04_unauthorized_ingest(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post(
        "/api/v1/events",
        headers={"Authorization": "Bearer sx_unrecognized_key_9999"},
        json={"events": []},
    )
    assert resp.status_code in {400, 401}

