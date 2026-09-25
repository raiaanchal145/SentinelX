"""
Detection engine integration (P23): built-in rule seeding, evaluation
through the real process_events job, per-organization settings
(disabled rule never fires; settings are org-isolated), and the
simulator scenarios -- brute force produces the expected hits,
benign noise produces none.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.routers.events as events_router
from app.models import DetectionRule, OrganizationRuleSetting, RuleHit, SecurityEvent
from app.detection.builtin_rules import BUILTIN_BY_ID
from app.detection.state import MemoryWindowStore
from app.routers.event_sources import generate_api_key
from app.worker.event_jobs import process_events, seed_builtin_rules
from app.worker.jobs import JOB_FUNCTIONS

from tests.helpers import make_organization

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc)

REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.simulator.scenarios import generate  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: an org + source + key, an eager queue, the real job with an
# in-memory state store (no Redis needed for these tests).
# ---------------------------------------------------------------------------


async def _make_source_with_key(db_session, org=None, source_type="windows", name="det source"):
    org = org or await make_organization(db_session)
    from app.models import EventSource, ApiKey

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


async def _drain(eager_queue, *, store=None):
    """Run the captured payloads through the real job with an injected
    in-memory detection state store."""
    ctx = {"session_factory": _Holder.factory, "detection_store": store or MemoryWindowStore()}
    totals = {"stored": 0, "hits": 0}
    for job_name, payload in eager_queue.payloads:
        assert job_name == "process_events"
        result = await process_events(ctx, payload)
        totals["stored"] += result["stored"]
        totals["hits"] += result["rule_hits"]
    return totals


def _sim_events(scenario, seed=42):
    """A simulator scenario as an API batch, timestamps rebased to now."""
    events = generate(scenario, seed=seed, base_time=NOW)
    return [{k: v for k, v in e.items() if not k.startswith("_")} for e in events]


# ---------------------------------------------------------------------------
# Seeding + job registration.
# ---------------------------------------------------------------------------


async def test_builtin_rules_seed_idempotently(db_session):
    # Seed through the TEST session factory -- passing None would make
    # seed_builtin_rules fall back to the real app database (settings
    # DATABASE_URL), which the test suite must never touch.
    from tests.conftest import TestSessionLocal

    count_first = await seed_builtin_rules(TestSessionLocal)
    count_second = await seed_builtin_rules(TestSessionLocal)
    assert count_first == count_second == 8

    total = (await db_session.execute(select(func.count()).select_from(DetectionRule).where(DetectionRule.organization_id.is_(None)))).scalar()
    assert total == 8  # a re-seed updated, not duplicated


async def test_process_events_registered():
    assert "process_events" in {f.__name__ for f in JOB_FUNCTIONS}


# ---------------------------------------------------------------------------
# Brute force: the expected hits. benign noise: none.
# ---------------------------------------------------------------------------


async def test_bruteforce_scenario_produces_expected_hits(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session, source_type="windows")
    await seed_builtin_rules(_Holder.factory or None)

    resp = await client.post("/api/v1/events", json={"events": _sim_events("ssh_or_windows_bruteforce")}, headers=_auth(key))
    assert resp.status_code == 202, resp.text
    totals = await _drain(eager_queue)
    assert totals["stored"] == 22

    hits = (await db_session.execute(select(RuleHit).where(RuleHit.organization_id == org.id))).scalars().all()
    hit_rules = {h.rule_name for h in hits}

    # 20 failures within 10 minutes -> repeated-failed-logins.
    assert BUILTIN_BY_ID["repeated-failed-logins"].name in hit_rules
    # failure -> success (same user, 15 minutes) -> success-after-failures.
    assert BUILTIN_BY_ID["success-after-failures"].name in hit_rules
    # the final privileged `net group` process is a group_change -> privileged-group-change.
    assert BUILTIN_BY_ID["privileged-group-change"].name in hit_rules

    failed_rule = next(h for h in hits if h.rule_name == BUILTIN_BY_ID["repeated-failed-logins"].name)
    assert failed_rule.event_count == 20
    assert failed_rule.group_key.startswith("user=")


async def test_benign_noise_produces_zero_hits(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session, source_type="test")
    await seed_builtin_rules(_Holder.factory or None)

    resp = await client.post("/api/v1/events", json={"events": _sim_events("benign_noise", seed=7)}, headers=_auth(key))
    assert resp.status_code == 202
    totals = await _drain(eager_queue)
    assert totals["stored"] == 12

    hits = (await db_session.execute(select(func.count()).select_from(RuleHit))).scalar()
    assert hits == 0  # no false positives on normal activity


async def test_mixed_scenario_hits_only_the_attack(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session)
    await seed_builtin_rules(_Holder.factory or None)

    resp = await client.post("/api/v1/events", json={"events": _sim_events("mixed", seed=42)}, headers=_auth(key))
    assert resp.status_code == 202
    await _drain(eager_queue)

    hits = (await db_session.execute(select(RuleHit))).scalars().all()
    # The noise half stays quiet; every hit belongs to the bruteforce half.
    assert all(
        h.rule_name
        in {
            BUILTIN_BY_ID["repeated-failed-logins"].name,
            BUILTIN_BY_ID["success-after-failures"].name,
            BUILTIN_BY_ID["privileged-group-change"].name,
        }
        for h in hits
    )
    assert len(hits) >= 2


async def test_other_attack_scenarios_fire_their_rules(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session)
    await seed_builtin_rules(_Holder.factory or None)

    resp = await client.post(
        "/api/v1/events",
        json={"events": _sim_events("audit_log_cleared", seed=3) + _sim_events("service_installed", seed=3) + _sim_events("new_user_created", seed=3)},
        headers=_auth(key),
    )
    assert resp.status_code == 202
    await _drain(eager_queue)

    hit_rules = {h.rule_name for h in (await db_session.execute(select(RuleHit))).scalars().all()}
    assert BUILTIN_BY_ID["audit-log-cleared"].name in hit_rules
    assert BUILTIN_BY_ID["service-installed"].name in hit_rules
    assert BUILTIN_BY_ID["new-local-user"].name in hit_rules


# ---------------------------------------------------------------------------
# Disabled rules + organization isolation.
# ---------------------------------------------------------------------------


async def test_disabled_rule_never_fires(client, db_session, eager_queue, job_db):
    org, source, key = await _make_source_with_key(db_session)
    await seed_builtin_rules(_Holder.factory or None)

    rule = (
        await db_session.execute(
            select(DetectionRule).where(DetectionRule.name == BUILTIN_BY_ID["repeated-failed-logins"].name)
        )
    ).scalar_one()
    db_session.add(OrganizationRuleSetting(organization_id=org.id, rule_id=rule.id, enabled=False))
    await db_session.commit()

    resp = await client.post("/api/v1/events", json={"events": _sim_events("ssh_or_windows_bruteforce")}, headers=_auth(key))
    assert resp.status_code == 202
    await _drain(eager_queue)

    hits = (await db_session.execute(select(RuleHit).where(RuleHit.organization_id == org.id))).scalars().all()
    hit_rules = {h.rule_name for h in hits}
    assert BUILTIN_BY_ID["repeated-failed-logins"].name not in hit_rules  # disabled for THIS org
    # The sequence still fires -- a different rule, still enabled.
    assert BUILTIN_BY_ID["success-after-failures"].name in hit_rules


async def test_rule_state_is_organization_isolated(client, db_session, eager_queue, job_db):
    """Two organizations, identical events: each gets its own hits and
    its own window state -- disabling in A doesn't silence B."""
    org_a, source_a, key_a = await _make_source_with_key(db_session, name="src A")
    org_b, source_b, key_b = await _make_source_with_key(db_session, name="src B")
    await seed_builtin_rules(_Holder.factory or None)

    rule = (
        await db_session.execute(
            select(DetectionRule).where(DetectionRule.name == BUILTIN_BY_ID["repeated-failed-logins"].name)
        )
    ).scalar_one()
    db_session.add(OrganizationRuleSetting(organization_id=org_a.id, rule_id=rule.id, enabled=False))
    await db_session.commit()

    for key in (key_a, key_b):
        resp = await client.post("/api/v1/events", json={"events": _sim_events("ssh_or_windows_bruteforce", seed=5)}, headers=_auth(key))
        assert resp.status_code == 202
    await _drain(eager_queue)

    a_hits = (await db_session.execute(select(RuleHit).where(RuleHit.organization_id == org_a.id))).scalars().all()
    b_hits = (await db_session.execute(select(RuleHit).where(RuleHit.organization_id == org_b.id))).scalars().all()

    assert BUILTIN_BY_ID["repeated-failed-logins"].name not in {h.rule_name for h in a_hits}
    assert BUILTIN_BY_ID["repeated-failed-logins"].name in {h.rule_name for h in b_hits}
    # Both orgs' events landed separately; no cross-org hit attribution.
    assert all(h.organization_id == org_a.id for h in a_hits)
    assert all(h.organization_id == org_b.id for h in b_hits)


async def test_replayed_batch_does_not_re_hit(client, db_session, eager_queue, job_db):
    """A replay's rows conflict away (P07 dedup) -- zero NEW stored rows
    means zero new detection input, so no duplicate hit storm."""
    org, source, key = await _make_source_with_key(db_session)
    await seed_builtin_rules(_Holder.factory or None)
    batch = _sim_events("ssh_or_windows_bruteforce", seed=9)

    resp = await client.post("/api/v1/events", json={"events": batch}, headers=_auth(key))
    assert resp.status_code == 202
    first = await _drain(eager_queue)
    eager_queue.payloads.clear()

    resp = await client.post("/api/v1/events", json={"events": batch}, headers=_auth(key))
    assert resp.status_code == 202
    second = await _drain(eager_queue)

    assert first["hits"] > 0
    assert second["stored"] == 0
    assert second["hits"] == 0  # nothing new stored, nothing new evaluated
