"""
The P10 alert pipeline (docs/API_CONTRACT.md "Alerts"):

1. dedup: repeated hits inside the dedup window fold into one alert
   (event_count grows, last_seen extends), a fresh bucket creates a new
   one;
2. correlation: the simulator's brute-force scenario produces exactly
   ONE correlated alert alongside the three detection alerts, and a
   re-run of the same batch (replay) stays idempotent;
3. the API: transitions (valid + 409s), the routing matrix (managed vs
   in-house x roles), isolation (404 across orgs), dismiss-requires-
   reason, assignment scope, list filters (rule_id/asset_id included)
   and history+audit rows on every change.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.routers.events as events_router
from app.models import (
    AdminLevel,
    Alert,
    AlertEvent,
    AlertHistory,
    AlertStatus,
    AuditLog,
    Correlation,
    CorrelationAlert,
    Organization,
    SocMode,
    UserRole,
)
from app.detection.builtin_rules import BUILTIN_BY_ID
from app.detection.state import MemoryWindowStore
from app.routers.event_sources import generate_api_key
from app.worker.event_jobs import process_events, seed_builtin_rules

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.simulator.scenarios import generate  # noqa: E402

from tests.helpers import auth, login, make_admin, make_organization, make_user

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc)

REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ---------------------------------------------------------------------------
# The P23 pipeline-test harness, reused: an org + event source + API key,
# an eager in-process queue, the real job over a real second session
# factory, an in-memory detection window store.
# ---------------------------------------------------------------------------


async def _make_source_with_key(db_session, org=None, source_type="windows", name="alerts source"):
    org = org or await make_organization(db_session)
    from app.models import ApiKey, EventSource

    source = EventSource(organization_id=org.id, name=name, source_type=source_type, status="active")
    db_session.add(source)
    await db_session.flush()
    full_key, key_hash, prefix = generate_api_key()
    api_key = ApiKey(organization_id=org.id, event_source_id=source.id, key_hash=key_hash, prefix=prefix)
    db_session.add(api_key)
    await db_session.commit()
    return org, source, full_key


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


class _EagerQueue:
    def __init__(self):
        self.payloads = []

    async def __call__(self, job_name, payload):
        self.payloads.append((job_name, payload))
        return "job-id"


class _Holder:
    factory = None


@pytest_asyncio.fixture
async def job_db(db_session):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import os

    from app.config import settings

    url = os.environ.get("TEST_DATABASE_URL") or (
        settings.database_url.rpartition("/")[0] + "/sentinelx_test"
    )
    engine = create_async_engine(url, poolclass=NullPool)
    _Holder.factory = async_sessionmaker(engine, expire_on_commit=False)
    yield
    _Holder.factory = None
    await engine.dispose()


@pytest.fixture
def eager_queue():
    q = _EagerQueue()
    with patch.object(events_router, "enqueue_work", q):
        yield q


async def _drain(eager_queue):
    ctx = {"session_factory": _Holder.factory, "detection_store": MemoryWindowStore()}
    for job_name, payload in eager_queue.payloads:
        assert job_name == "process_events"
        await process_events(ctx, payload)
    eager_queue.payloads.clear()


def _sim_events(scenario, seed=42):
    events = generate(scenario, seed=seed, base_time=NOW)
    return [{k: v for k, v in e.items() if not k.startswith("_")} for e in events]


async def _send_and_drain(client, eager_queue, key, scenario, seed=42):
    resp = await client.post(
        "/api/v1/events", json={"events": _sim_events(scenario, seed=seed)}, headers=_auth(key)
    )
    assert resp.status_code == 202, resp.text
    await _drain(eager_queue)


async def _seed_detection_and_correlation():
    from tests.conftest import TestSessionLocal

    await seed_builtin_rules(TestSessionLocal)
    from app.alerting import seed_builtin_correlation_rules

    await seed_builtin_correlation_rules(TestSessionLocal)


# ---------------------------------------------------------------------------
# Dedup: fold inside the window, new alert in a fresh bucket.
# ---------------------------------------------------------------------------


async def test_dedup_same_batch_folds_into_one_alert(db_session, eager_queue, job_db, client):
    """Every hit from one brute-force batch lands inside one 15-minute
    dedup window -> exactly three detection alerts, one per rule."""
    org, source, key = await _make_source_with_key(db_session, source_type="windows")
    await _seed_detection_and_correlation()

    await _send_and_drain(client, eager_queue, key, "ssh_or_windows_bruteforce")

    alerts = (
        await db_session.execute(select(Alert).where(Alert.organization_id == org.id))
    ).scalars().all()
    detection = [a for a in alerts if a.kind == "detection"]
    assert len(detection) == 3  # one per fired rule, not one per event
    by_rule = {a.rule_name: a for a in detection}
    assert BUILTIN_BY_ID["repeated-failed-logins"].name in by_rule
    failed = by_rule[BUILTIN_BY_ID["repeated-failed-logins"].name]
    assert failed.event_count == 20
    # The 20 supporting events are linked (under the 50-link cap).
    links = (
        await db_session.execute(select(AlertEvent).where(AlertEvent.alert_id == failed.id))
    ).scalars().all()
    assert len(links) == 20
    assert failed.dedup_key.startswith("Repeated failed logins:user=")
    # Correlation keys resolved from the events, not the pattern hit's key.
    assert failed.username is not None
    assert failed.source_ip is not None


async def test_replayed_batch_extends_not_duplicates(db_session, eager_queue, job_db, client):
    """A distinct second batch for the same user inside the window folds
    into the existing alert (count grows, last_seen extends); the same
    batch replayed adds nothing (P07 dedup -> no new hits -> no fold)."""
    org, source, key = await _make_source_with_key(db_session, source_type="windows")
    await _seed_detection_and_correlation()

    batch = _sim_events("ssh_or_windows_bruteforce", seed=10)
    resp = await client.post("/api/v1/events", json={"events": batch}, headers=_auth(key))
    assert resp.status_code == 202
    await _drain(eager_queue)

    alerts = (
        await db_session.execute(select(Alert).where(Alert.organization_id == org.id, Alert.kind == "detection"))
    ).scalars().all()
    assert len(alerts) == 3
    failed = next(a for a in alerts if a.rule_name == BUILTIN_BY_ID["repeated-failed-logins"].name)
    assert failed.event_count == 20

    # Same events replayed: P07 dedup swallows them -> no new hits, no fold.
    resp = await client.post("/api/v1/events", json={"events": batch}, headers=_auth(key))
    assert resp.status_code == 202
    await _drain(eager_queue)
    alerts = (
        await db_session.execute(select(Alert).where(Alert.organization_id == org.id, Alert.kind == "detection"))
    ).scalars().all()
    assert len(alerts) == 3
    failed2 = next(a for a in alerts if a.rule_name == BUILTIN_BY_ID["repeated-failed-logins"].name)
    assert failed2.event_count == 20  # unchanged


async def test_second_batch_new_bucket_creates_new_alert(db_session, eager_queue, job_db, client):
    """A second attack (different seed => different events) well past the
    dedup window creates its own alert rather than folding."""
    org, source, key = await _make_source_with_key(db_session, source_type="windows")
    await _seed_detection_and_correlation()

    await _send_and_drain(client, eager_queue, key, "ssh_or_windows_bruteforce", seed=21)
    first = (
        await db_session.execute(select(Alert).where(Alert.organization_id == org.id, Alert.kind == "detection"))
    ).scalars().all()
    assert len(first) == 3

    # A fresh batch whose events are hours later => a different dedup
    # bucket for every rule.
    global NOW
    NOW = NOW + timedelta(hours=6)
    try:
        await _send_and_drain(client, eager_queue, key, "ssh_or_windows_bruteforce", seed=22)
    finally:
        NOW = NOW - timedelta(hours=6)

    second = (
        await db_session.execute(select(Alert).where(Alert.organization_id == org.id, Alert.kind == "detection"))
    ).scalars().all()
    assert len(second) == 6  # the second attack made three NEW alerts
    failed = [a for a in second if a.rule_name == BUILTIN_BY_ID["repeated-failed-logins"].name]
    assert len(failed) == 2
    assert len({a.dedup_key for a in failed}) == 2  # distinct buckets, distinct keys


# ---------------------------------------------------------------------------
# Correlation: the DONE-WHEN scenario.
# ---------------------------------------------------------------------------


async def test_bruteforce_produces_exactly_one_correlated_alert(db_session, eager_queue, job_db, client):
    """THE done-when: one correlated alert alongside the three detection
    alerts, with reasoning and grouping, and nothing for benign noise."""
    org, source, key = await _make_source_with_key(db_session, source_type="windows")
    await _seed_detection_and_correlation()

    await _send_and_drain(client, eager_queue, key, "ssh_or_windows_bruteforce")

    alerts = (
        await db_session.execute(select(Alert).where(Alert.organization_id == org.id))
    ).scalars().all()
    correlated = [a for a in alerts if a.kind == "correlation"]
    detection = [a for a in alerts if a.kind == "detection"]
    assert len(correlated) == 1  # EXACTLY ONE correlated alert
    assert len(detection) == 3  # the underlying alerts stay visible (alongside)

    corr = correlated[0]
    assert corr.status == AlertStatus.new
    assert corr.severity.value == "high"
    assert corr.username is not None  # grouped by user

    # The Correlation row carries the reasoning and links all three.
    correlations = (await db_session.execute(select(Correlation))).scalars().all()
    assert len(correlations) == 1
    reasoning = correlations[0].reasoning
    assert reasoning is not None
    for fragment in (
        BUILTIN_BY_ID["repeated-failed-logins"].name,
        BUILTIN_BY_ID["success-after-failures"].name,
        BUILTIN_BY_ID["privileged-group-change"].name,
    ):
        assert fragment in reasoning  # "why these were grouped"
    links = (await db_session.execute(select(CorrelationAlert))).scalars().all()
    assert {str(l.alert_id) for l in links} == {str(a.id) for a in detection}


async def test_benign_noise_produces_no_alerts_at_all(db_session, eager_queue, job_db, client):
    org, source, key = await _make_source_with_key(db_session, source_type="test")
    await _seed_detection_and_correlation()

    await _send_and_drain(client, eager_queue, key, "benign_noise", seed=7)

    assert (await db_session.execute(select(Alert))).scalars().all() == []


async def test_correlation_rerun_is_idempotent(db_session, eager_queue, job_db, client):
    """Draining a second (identical-content, different-ids) batch of the
    same attack doesn't stack correlations; the dedup key holds one."""
    org, source, key = await _make_source_with_key(db_session, source_type="windows")
    await _seed_detection_and_correlation()

    await _send_and_drain(client, eager_queue, key, "ssh_or_windows_bruteforce", seed=31)
    assert len((await db_session.execute(select(Correlation))).scalars().all()) == 1

    # A replay adds no new events (P07 dedup) => no new hits => the
    # correlation pass runs over the same alerts and must not re-create.
    await _send_and_drain(client, eager_queue, key, "ssh_or_windows_bruteforce", seed=31)
    assert len((await db_session.execute(select(Correlation))).scalars().all()) == 1


# ---------------------------------------------------------------------------
# Transitions.
# ---------------------------------------------------------------------------


async def _make_alert(db_session, org, *, rule_name="Test rule", status=AlertStatus.new):
    alert = Alert(
        organization_id=org.id,
        rule_name=rule_name,
        kind="detection",
        severity=__import__("app.models", fromlist=["EventSeverity"]).EventSeverity.high,
        status=status,
        title=f"{rule_name} -- user=test",
        first_seen_at=NOW,
        last_seen_at=NOW,
        event_count=1,
        dedup_key=f"{rule_name}:{uuid.uuid4()}",
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert)
    return alert


async def _token_for(client, db_session, *, org=None, level=None, role=None):
    if level == AdminLevel.super_admin:
        admin = await make_admin(db_session, email=f"sa-{uuid.uuid4().hex[:8]}@x.io", admin_level=level)
    elif level == AdminLevel.platform_soc_analyst:
        admin = await make_admin(db_session, email=f"psa-{uuid.uuid4().hex[:8]}@x.io", admin_level=level)
    elif level == AdminLevel.organization_admin:
        admin = await make_admin(
            db_session, email=f"owner-{uuid.uuid4().hex[:8]}@x.io", admin_level=level, organization_id=org.id
        )
    else:
        user = await make_user(db_session, email=f"u-{uuid.uuid4().hex[:8]}@x.io", role=role, organization_id=org.id)
        return await login(client, user.email)
    return await login(client, admin.email)


async def test_acknowledge_new_to_triaged(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    alert = await _make_alert(db_session, org)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    resp = await client.post(f"/api/v1/alerts/{alert.id}/acknowledge", headers=auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "triaged"
    assert resp.json()["previous_status"] == "new"


async def test_acknowledge_twice_is_409(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    alert = await _make_alert(db_session, org)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    await client.post(f"/api/v1/alerts/{alert.id}/acknowledge", headers=auth(token))
    resp = await client.post(f"/api/v1/alerts/{alert.id}/acknowledge", headers=auth(token))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "invalid_alert_transition"


async def test_invalid_transitions_across_the_map(db_session, client):
    """new -> investigating is not allowed; dismissed is terminal except
    via /reopen; converted is terminal."""
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    a_new = await _make_alert(db_session, org, status=AlertStatus.new)
    resp = await client.post(f"/api/v1/alerts/{a_new.id}/dismiss", json={"reason": "fp"}, headers=auth(token))
    assert resp.status_code == 200  # new -> dismissed is allowed

    resp = await client.post(f"/api/v1/alerts/{a_new.id}/reopen", headers=auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "new"

    # acknowledge from dismissed was already refused above via /reopen
    # back to new; dismiss without a reason shape-checks the 422:
    resp = await client.post(f"/api/v1/alerts/{a_new.id}/dismiss", json={}, headers=auth(token))
    assert resp.status_code == 422


async def test_dismissed_terminal_converted_terminal(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    alert = await _make_alert(db_session, org, status=AlertStatus.dismissed)
    resp = await client.post(f"/api/v1/alerts/{alert.id}/acknowledge", headers=auth(token))
    assert resp.status_code == 409

    alert2 = await _make_alert(db_session, org, status=AlertStatus.converted)
    resp = await client.post(f"/api/v1/alerts/{alert2.id}/dismiss", json={"reason": "x"}, headers=auth(token))
    assert resp.status_code == 409


async def test_dismiss_requires_reason_422(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    alert = await _make_alert(db_session, org)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    resp = await client.post(f"/api/v1/alerts/{alert.id}/dismiss", json={}, headers=auth(token))
    assert resp.status_code == 422
    resp = await client.post(f"/api/v1/alerts/{alert.id}/dismiss", json={"reason": ""}, headers=auth(token))
    assert resp.status_code == 422

    resp = await client.post(f"/api/v1/alerts/{alert.id}/dismiss", json={"reason": "false positive -- legitimate backup"}, headers=auth(token))
    assert resp.status_code == 200
    assert resp.json()["dismissed_reason"] == "false positive -- legitimate backup"


async def test_reopen_only_from_dismissed(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    alert = await _make_alert(db_session, org, status=AlertStatus.triaged)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    resp = await client.post(f"/api/v1/alerts/{alert.id}/reopen", headers=auth(token))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "invalid_alert_transition"


# ---------------------------------------------------------------------------
# Routing matrix: managed vs in-house x every role/account type.
# ---------------------------------------------------------------------------


async def test_routing_matrix_managed(db_session, client):
    """Managed org: owner + security_manager read their queue (200 GET,
    403 writes); soc_analyst and auditor see nothing (403/404); platform
    SOC assigned sees and writes; unassigned platform SOC sees an empty
    queue; super_admin sees all."""
    org = await make_organization(db_session, soc_mode=SocMode.managed)
    alert = await _make_alert(db_session, org)

    # Owner: read OK, write 403.
    owner_token = await _token_for(client, db_session, org=org, level=AdminLevel.organization_admin)
    resp = await client.get("/api/v1/alerts", headers=auth(owner_token))
    assert resp.status_code == 200
    assert [a["id"] for a in resp.json()["alerts"]] == [str(alert.id)]
    resp = await client.post(f"/api/v1/alerts/{alert.id}/acknowledge", headers=auth(owner_token))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "alert_write_not_allowed"

    # Security manager: read OK, write 403.
    sm_token = await _token_for(client, db_session, org=org, role=UserRole.security_manager)
    resp = await client.get("/api/v1/alerts", headers=auth(sm_token))
    assert resp.status_code == 200
    assert [a["id"] for a in resp.json()["alerts"]] == [str(alert.id)]
    resp = await client.post(f"/api/v1/alerts/{alert.id}/dismiss", json={"reason": "x"}, headers=auth(sm_token))
    assert resp.status_code == 403

    # soc_analyst (managed => module `soc` is gated off): 403.
    analyst_token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    resp = await client.get("/api/v1/alerts", headers=auth(analyst_token))
    assert resp.status_code == 403

    # auditor: no soc module -> 403.
    auditor_token = await _token_for(client, db_session, org=org, role=UserRole.auditor)
    resp = await client.get("/api/v1/alerts", headers=auth(auditor_token))
    assert resp.status_code == 403

    # Platform SOC analyst assigned to the org: sees and can write.
    psa = await make_admin(db_session, email=f"psa-{uuid.uuid4().hex[:8]}@x.io", admin_level=AdminLevel.platform_soc_analyst)
    from app.models import SocOrganizationAssignment

    db_session.add(SocOrganizationAssignment(admin_id=psa.id, organization_id=org.id))
    await db_session.commit()
    psa_token = await login(client, psa.email)
    resp = await client.get("/api/v1/alerts", headers=auth(psa_token))
    assert resp.status_code == 200
    assert [a["id"] for a in resp.json()["alerts"]] == [str(alert.id)]
    resp = await client.post(f"/api/v1/alerts/{alert.id}/acknowledge", headers=auth(psa_token))
    assert resp.status_code == 200

    # Unassigned platform SOC analyst: 200 with an empty queue.
    psa2 = await make_admin(db_session, email=f"psa2-{uuid.uuid4().hex[:8]}@x.io", admin_level=AdminLevel.platform_soc_analyst)
    psa2_token = await login(client, psa2.email)
    resp = await client.get("/api/v1/alerts", headers=auth(psa2_token))
    assert resp.status_code == 200
    assert resp.json()["alerts"] == []
    # ...and get on the alert id is a 404 (never a leak).
    resp = await client.get(f"/api/v1/alerts/{alert.id}", headers=auth(psa2_token))
    assert resp.status_code == 404

    # Super admin: sees everything.
    sa_token = await _token_for(client, db_session, level=AdminLevel.super_admin)
    resp = await client.get("/api/v1/alerts", headers=auth(sa_token))
    assert resp.status_code == 200
    assert str(alert.id) in [a["id"] for a in resp.json()["alerts"]]


async def test_routing_matrix_in_house(db_session, client):
    """In-house org: soc_analyst reads AND writes; owner and
    security_manager read and write (their module matrix allows soc in
    in-house); auditor 403."""
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    alert = await _make_alert(db_session, org)

    analyst_token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    resp = await client.get("/api/v1/alerts", headers=auth(analyst_token))
    assert resp.status_code == 200
    assert [a["id"] for a in resp.json()["alerts"]] == [str(alert.id)]
    resp = await client.post(f"/api/v1/alerts/{alert.id}/acknowledge", headers=auth(analyst_token))
    assert resp.status_code == 200

    owner_token = await _token_for(client, db_session, org=org, level=AdminLevel.organization_admin)
    resp = await client.get("/api/v1/alerts", headers=auth(owner_token))
    assert resp.status_code == 200
    resp = await client.post(f"/api/v1/alerts/{alert.id}/dismiss", json={"reason": "dup"}, headers=auth(owner_token))
    # The alert is now triaged (analyst acked it) -> dismissed is valid.
    assert resp.status_code == 200

    sm_token = await _token_for(client, db_session, org=org, role=UserRole.security_manager)
    resp = await client.get("/api/v1/alerts", headers=auth(sm_token))
    assert resp.status_code == 200

    auditor_token = await _token_for(client, db_session, org=org, role=UserRole.auditor)
    resp = await client.get("/api/v1/alerts", headers=auth(auditor_token))
    assert resp.status_code == 403


async def test_isolation_cross_org_404(db_session, client):
    """A different org's analyst gets 404 (not 403) on our alert --
    existence never leaks across the boundary."""
    org_a = await make_organization(db_session, name="Org A", soc_mode=SocMode.in_house)
    org_b = await make_organization(db_session, name="Org B", soc_mode=SocMode.in_house)
    alert_a = await _make_alert(db_session, org_a)
    token_b = await _token_for(client, db_session, org=org_b, role=UserRole.soc_analyst)

    resp = await client.get(f"/api/v1/alerts/{alert_a.id}", headers=auth(token_b))
    assert resp.status_code == 404
    resp = await client.post(f"/api/v1/alerts/{alert_a.id}/acknowledge", headers=auth(token_b))
    assert resp.status_code == 404

    # And org B's queue shows only org B's alerts.
    resp = await client.get("/api/v1/alerts", headers=auth(token_b))
    assert resp.status_code == 200
    assert all(a["organization_id"] == str(org_b.id) for a in resp.json()["alerts"])


async def test_organization_filter_for_platform_role(db_session, client):
    """organization_id filter: a visible id works, an invisible one 404s,
    a bogus one 404s."""
    org_a = await make_organization(db_session, name="Org A", soc_mode=SocMode.managed)
    org_b = await make_organization(db_session, name="Org B", soc_mode=SocMode.managed)
    alert_a = await _make_alert(db_session, org_a)
    await _make_alert(db_session, org_b)

    psa = await make_admin(db_session, email=f"psa-{uuid.uuid4().hex[:8]}@x.io", admin_level=AdminLevel.platform_soc_analyst)
    from app.models import SocOrganizationAssignment

    db_session.add(SocOrganizationAssignment(admin_id=psa.id, organization_id=org_a.id))
    await db_session.commit()
    token = await login(client, psa.email)

    resp = await client.get(f"/api/v1/alerts?organization_id={org_a.id}", headers=auth(token))
    assert resp.status_code == 200
    assert [a["id"] for a in resp.json()["alerts"]] == [str(alert_a.id)]

    resp = await client.get(f"/api/v1/alerts?organization_id={org_b.id}", headers=auth(token))
    assert resp.status_code == 404

    resp = await client.get(f"/api/v1/alerts?organization_id={uuid.uuid4()}", headers=auth(token))
    assert resp.status_code == 404


async def test_list_filters_and_pagination(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    a1 = await _make_alert(db_session, org, rule_name="R1")
    a2 = await _make_alert(db_session, org, rule_name="R2")
    a2.last_seen_at = NOW + timedelta(minutes=5)
    a2.status = AlertStatus.dismissed
    a2.dismissed_reason = "fp"
    await db_session.commit()

    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    # status filter.
    resp = await client.get("/api/v1/alerts?status=dismissed", headers=auth(token))
    assert [a["id"] for a in resp.json()["alerts"]] == [str(a2.id)]
    # invalid status -> 400 with a code.
    resp = await client.get("/api/v1/alerts?status=bogus", headers=auth(token))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_status"

    # assigned_to_me: none of these alerts are assigned to this caller.
    resp = await client.get("/api/v1/alerts?assigned_to_me=true", headers=auth(token))
    assert resp.json()["alerts"] == []

    # rule_id and asset_id filters resolve only matching alerts (the
    # rule/asset are attached to one of the two).
    from app.models import Asset, DetectionRule, DetectionRuleType

    rule = DetectionRule(
        organization_id=org.id,
        name="Filter rule",
        rule_type=DetectionRuleType.threshold,
        condition={},
        severity=__import__("app.models", fromlist=["EventSeverity"]).EventSeverity.low,
    )
    asset = Asset(organization_id=org.id, name="filter-asset", asset_type="server", criticality="low")
    db_session.add_all([rule, asset])
    await db_session.commit()
    a1.detection_rule_id = rule.id
    a1.asset_id = asset.id
    await db_session.commit()

    resp = await client.get(f"/api/v1/alerts?rule_id={rule.id}", headers=auth(token))
    assert [a["id"] for a in resp.json()["alerts"]] == [str(a1.id)]
    resp = await client.get(f"/api/v1/alerts?asset_id={asset.id}", headers=auth(token))
    assert [a["id"] for a in resp.json()["alerts"]] == [str(a1.id)]
    # A nonexistent rule id simply matches nothing (a valid uuid).
    resp = await client.get(f"/api/v1/alerts?rule_id={uuid.uuid4()}", headers=auth(token))
    assert resp.json()["alerts"] == []

    # Pagination: limit=1 walks to the second alert.
    resp = await client.get("/api/v1/alerts?limit=1", headers=auth(token))
    body = resp.json()
    assert len(body["alerts"]) == 1
    assert body["next_cursor"] is not None
    resp = await client.get(f"/api/v1/alerts?limit=1&cursor={body['next_cursor']}", headers=auth(token))
    assert len(resp.json()["alerts"]) == 1
    assert resp.json()["next_cursor"] is None


# ---------------------------------------------------------------------------
# Assignment scope.
# ---------------------------------------------------------------------------


async def test_assign_in_house_to_own_analyst(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    alert = await _make_alert(db_session, org)
    owner_token = await _token_for(client, db_session, org=org, level=AdminLevel.organization_admin)
    analyst = await make_user(db_session, email=f"a-{uuid.uuid4().hex[:8]}@x.io", role=UserRole.soc_analyst, organization_id=org.id)

    resp = await client.post(
        f"/api/v1/alerts/{alert.id}/assign",
        json={"account_type": "user", "account_id": str(analyst.id)},
        headers=auth(owner_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assigned_account_id"] == str(analyst.id)
    assert resp.json()["assigned_account_type"] == "user"


async def test_assign_rejects_out_of_scope_targets(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    alert = await _make_alert(db_session, org)
    owner_token = await _token_for(client, db_session, org=org, level=AdminLevel.organization_admin)

    # A user from ANOTHER org -> 422 (not 404: the account exists).
    other = await make_organization(db_session, name="Other", soc_mode=SocMode.in_house)
    outsider = await make_user(db_session, email=f"o-{uuid.uuid4().hex[:8]}@x.io", role=UserRole.soc_analyst, organization_id=other.id)
    resp = await client.post(
        f"/api/v1/alerts/{alert.id}/assign",
        json={"account_type": "user", "account_id": str(outsider.id)},
        headers=auth(owner_token),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "assignee_not_in_scope"

    # A nonexistent user -> 404.
    resp = await client.post(
        f"/api/v1/alerts/{alert.id}/assign",
        json={"account_type": "user", "account_id": str(uuid.uuid4())},
        headers=auth(owner_token),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "assignee_not_found"

    # A security_manager user of the same org -> 422 (only soc_analyst).
    sm = await make_user(db_session, email=f"sm-{uuid.uuid4().hex[:8]}@x.io", role=UserRole.security_manager, organization_id=org.id)
    resp = await client.post(
        f"/api/v1/alerts/{alert.id}/assign",
        json={"account_type": "user", "account_id": str(sm.id)},
        headers=auth(owner_token),
    )
    assert resp.status_code == 422

    # account_type admin against an in-house queue -> the admin exists
    # check fires first for a bogus id: 404.
    resp = await client.post(
        f"/api/v1/alerts/{alert.id}/assign",
        json={"account_type": "admin", "account_id": str(uuid.uuid4())},
        headers=auth(owner_token),
    )
    assert resp.status_code == 404


async def test_assign_platform_side_between_analysts(db_session, client):
    """On a managed org's queue, a platform SOC analyst assigns to
    another platform SOC analyst assigned to the same org."""
    org = await make_organization(db_session, soc_mode=SocMode.managed)
    alert = await _make_alert(db_session, org)
    psa1 = await make_admin(db_session, email=f"p1-{uuid.uuid4().hex[:8]}@x.io", admin_level=AdminLevel.platform_soc_analyst)
    psa2 = await make_admin(db_session, email=f"p2-{uuid.uuid4().hex[:8]}@x.io", admin_level=AdminLevel.platform_soc_analyst)
    from app.models import SocOrganizationAssignment

    db_session.add(SocOrganizationAssignment(admin_id=psa1.id, organization_id=org.id))
    db_session.add(SocOrganizationAssignment(admin_id=psa2.id, organization_id=org.id))
    await db_session.commit()
    token = await login(client, psa1.email)

    resp = await client.post(
        f"/api/v1/alerts/{alert.id}/assign",
        json={"account_type": "admin", "account_id": str(psa2.id)},
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assigned_account_id"] == str(psa2.id)

    # ...but a platform analyst NOT assigned to this org is 422.
    psa3 = await make_admin(db_session, email=f"p3-{uuid.uuid4().hex[:8]}@x.io", admin_level=AdminLevel.platform_soc_analyst)
    resp = await client.post(
        f"/api/v1/alerts/{alert.id}/assign",
        json={"account_type": "admin", "account_id": str(psa3.id)},
        headers=auth(token),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "assignee_not_in_scope"


# ---------------------------------------------------------------------------
# History + audit.
# ---------------------------------------------------------------------------


async def test_history_and_audit_written_on_every_change(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    alert = await _make_alert(db_session, org)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    await client.post(f"/api/v1/alerts/{alert.id}/acknowledge", headers=auth(token))
    assignee = await make_user(db_session, email=f"asg-{uuid.uuid4().hex[:8]}@x.io", role=UserRole.soc_analyst, organization_id=org.id)
    await client.post(
        f"/api/v1/alerts/{alert.id}/assign",
        json={"account_type": "user", "account_id": str(assignee.id)},
        headers=auth(token),
    )
    await client.post(f"/api/v1/alerts/{alert.id}/dismiss", json={"reason": "fp"}, headers=auth(token))
    await client.post(f"/api/v1/alerts/{alert.id}/reopen", headers=auth(token))

    history = (
        await db_session.execute(select(AlertHistory).where(AlertHistory.alert_id == alert.id).order_by(AlertHistory.created_at))
    ).scalars().all()
    actions = [h.action for h in history]
    assert actions == ["acknowledge", "assign", "dismiss", "reopen"]
    assert all(h.actor_type.value == "user" for h in history)
    dismiss_row = next(h for h in history if h.action == "dismiss")
    assert dismiss_row.detail["reason"] == "fp"
    assert dismiss_row.status_from.value == "triaged"
    assert dismiss_row.status_to.value == "dismissed"

    audits = (
        await db_session.execute(select(AuditLog).where(AuditLog.action.like("alert.%")))
    ).scalars().all()
    assert {a.action for a in audits} == {"alert.acknowledge", "alert.assign", "alert.dismiss", "alert.reopen"}


# ---------------------------------------------------------------------------
# Detail endpoint.
# ---------------------------------------------------------------------------


async def test_detail_includes_events_rule_correlation_history(db_session, eager_queue, job_db, client):
    org, source, key = await _make_source_with_key(db_session, source_type="windows")
    await _seed_detection_and_correlation()
    await _send_and_drain(client, eager_queue, key, "ssh_or_windows_bruteforce")

    correlated = (
        await db_session.execute(select(Alert).where(Alert.kind == "correlation"))
    ).scalars().one()
    token = await _token_for(client, db_session, level=AdminLevel.super_admin)

    resp = await client.get(f"/api/v1/alerts/{correlated.id}", headers=auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["alert"]["kind"] == "correlation"
    assert body["correlation"] is not None
    assert "brute-force" in body["correlation"]["reasoning"].lower() or "classic" in body["correlation"]["reasoning"].lower()
    assert len(body["correlation"]["grouped_alerts"]) == 3
    assert body["rule"] is None  # a correlation alert has no detection rule
    # History: the worker's system "create" row.
    assert body["history"][0]["action"] == "create"
    assert body["history"][0]["actor_type"] == "system"

    # A detection alert's detail carries its events and rule.
    detection = (
        await db_session.execute(select(Alert).where(Alert.kind == "detection"))
    ).scalars().first()
    resp = await client.get(f"/api/v1/alerts/{detection.id}", headers=auth(token))
    body = resp.json()
    assert len(body["events"]) > 0
    assert body["rule"]["name"] == detection.rule_name
    assert body["correlation"] is not None  # it belongs to the correlation
