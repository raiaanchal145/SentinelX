"""
SentinelX QA Test Suite: Network Signal & Port Scan Ingestion.

Module: NET
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

import datetime as dt
from unittest.mock import patch
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.evaluators import evaluate_threshold
from app.detection.definitions import ThresholdDefinition
from app.models import ApiKey, EventSource
from app.routers.event_sources import generate_api_key
from backend.tests.helpers import make_organization
from tc import tc


async def _create_network_source(db_session: AsyncSession, org=None):
    if org is None:
        org = await make_organization(db_session, name="NetOrg")
    source = EventSource(organization_id=org.id, name="Firewall Collector", source_type="network", status="active")
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
    id="NET-01",
    module="Network",
    description="Ingest network firewall event successfully",
    preconditions="Network event source active with API key",
    steps="POST /api/v1/events with firewall_deny telemetry event",
    expected="Response status 202 with accepted=1",
    type="automated",
    owner="Riteka Singh",
)
@pytest.mark.asyncio
async def test_net_01_ingest_firewall_event(client: AsyncClient, db_session: AsyncSession):
    org, source, api_key = await _create_network_source(db_session)
    now_str = dt.datetime.now(dt.timezone.utc).isoformat()

    payload = {
        "events": [
            {
                "schema_version": "1.0",
                "timestamp": now_str,
                "source_type": "network",
                "event_type": "firewall_deny",
                "message": "DROP inbound TCP 198.51.100.4:44321 -> 10.0.0.5:22",
                "ip": "198.51.100.4",
                "host": "gw-firewall-01",
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
    assert resp.json()["accepted"] == 1


@tc(
    id="NET-02",
    module="Network",
    description="Ingest DNS query network telemetry event",
    preconditions="Network event source active",
    steps="POST /api/v1/events with dns_query event",
    expected="Response status 202 with accepted=1",
    type="automated",
    owner="Aanchal Rai",
)
@pytest.mark.asyncio
async def test_net_02_ingest_dns_query(client: AsyncClient, db_session: AsyncSession):
    org, source, api_key = await _create_network_source(db_session)
    now_str = dt.datetime.now(dt.timezone.utc).isoformat()

    payload = {
        "events": [
            {
                "schema_version": "1.0",
                "timestamp": now_str,
                "source_type": "network",
                "event_type": "dns_query",
                "message": "Query: malicious-c2-domain.com IN A from 10.0.0.45",
                "ip": "10.0.0.45",
                "host": "dns-server-internal",
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
    assert resp.json()["accepted"] == 1


@tc(
    id="NET-03",
    module="Network",
    description="Evaluate port scan pattern: threshold rule triggers when connection denies exceed limit",
    preconditions="Threshold definition for firewall_deny with threshold=5",
    steps="Feed 6 firewall_deny events within window to evaluator",
    expected="RuleMatch record returned identifying source IP group",
    type="automated",
    owner="Ansh",
)
def test_net_03_port_scan_detection():
    now = dt.datetime.now(dt.timezone.utc)
    events = [
        {
            "id": f"evt-{i}",
            "event_type": "firewall_deny",
            "ip": "203.0.113.55",
            "occurred_at": (now - dt.timedelta(seconds=i * 5)).isoformat(),
            "message": f"Denied connection to port {8000 + i}",
        }
        for i in range(6)
    ]

    definition = ThresholdDefinition(
        event_types=["firewall_deny"],
        threshold=5,
        window_seconds=300,
        group_by="ip",
    )

    matches = evaluate_threshold(
        definition,
        events,
        window_start=now - dt.timedelta(seconds=300),
        window_end=now,
    )

    assert len(matches) == 1
    assert matches[0].group_key == "203.0.113.55"
    assert len(matches[0].event_ids) == 6


@tc(
    id="NET-04",
    module="Network",
    description="IDS alert signal with high severity signature is accepted",
    preconditions="Network event source active",
    steps="POST /api/v1/events with ids_alert event type and severity_hint='high'",
    expected="Response status 202 accepted",
    type="automated",
    owner="Riteka Singh",
)
@pytest.mark.asyncio
async def test_net_04_ids_alert_ingest(client: AsyncClient, db_session: AsyncSession):
    org, source, api_key = await _create_network_source(db_session)
    now_str = dt.datetime.now(dt.timezone.utc).isoformat()

    payload = {
        "events": [
            {
                "schema_version": "1.0",
                "timestamp": now_str,
                "source_type": "network",
                "event_type": "ids_alert",
                "message": "ET MALWARE Win32/CobaltStrike Beacon Outbound",
                "ip": "10.0.2.15",
                "severity_hint": "high",
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
    assert resp.json()["accepted"] == 1
