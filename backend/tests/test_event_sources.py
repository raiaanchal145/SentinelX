"""
Event sources + API keys (routers/event_sources.py) and the worker
heartbeat job (app/worker/jobs.py, run in fake mode -- no Redis).
"""

import uuid

import pytest

from app.models import ApiKey, EventSource, EventSourceType
from app.routers.event_sources import generate_api_key, get_event_source_from_api_key, hash_api_key
from app.worker.jobs import heartbeat

from tests.helpers import auth, login, make_admin, make_organization, make_user

pytestmark = pytest.mark.asyncio


async def _seed(db_session, org_name="Aurora Health", email="es-owner@example.com"):
    org = await make_organization(db_session, name=org_name)
    owner = await make_admin(
        db_session,
        email=email,
        name="Owner",
        admin_level="organization_admin",
        organization_id=org.id,
    )
    return org, owner


# ---------------------------------------------------------------------------
# Key generation: secret shown once, hash-only storage.
# ---------------------------------------------------------------------------

async def test_generate_api_key_shape_and_uniqueness():
    full, key_hash, display = generate_api_key()
    assert full.startswith("sx_")
    # sx_<prefix>_<secret>: at least the two delimiters (url-safe base64
    # can itself contain _ or -, so count them separately).
    assert full[3:].count("_") >= 1
    # 32+ bytes of entropy: url-safe base64 of >32 raw bytes.
    assert len(full) > 60
    assert key_hash == hash_api_key(full)
    assert display.startswith("sx_") and len(display) <= 20
    other, other_hash, _ = generate_api_key()
    assert full != other and key_hash != other_hash


async def test_create_key_returns_secret_exactly_once(client, db_session):
    org, owner = await _seed(db_session)
    token = await login(client, owner.email)

    resp = await client.post(
        "/api/v1/event-sources",
        json={"name": "docker collector", "source_type": "docker"},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    source_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/event-sources/{source_id}/keys", headers=auth(token))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["key"].startswith("sx_")

    # The secret never comes back again...
    resp = await client.get(f"/api/v1/event-sources/{source_id}/keys", headers=auth(token))
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert len(keys) == 1
    assert "key" not in keys[0]
    assert keys[0]["prefix"] == body["prefix"]
    assert keys[0]["revoked"] is False

    # ...and only the hash is stored.
    stored = (await db_session.execute(__import__("sqlalchemy").select(ApiKey))).scalars().all()
    assert len(stored) == 1
    assert stored[0].key_hash == hash_api_key(body["key"])
    assert body["key"] not in stored[0].key_hash


async def test_revoked_key_rejected_and_auth_updates_last_used(client, db_session):
    org, owner = await _seed(db_session)
    token = await login(client, owner.email)

    source_id = (
        await client.post(
            "/api/v1/event-sources",
            json={"name": "auth log", "source_type": "linux_auth"},
            headers=auth(token),
        )
    ).json()["id"]
    full_key = (
        await client.post(f"/api/v1/event-sources/{source_id}/keys", headers=auth(token))
    ).json()["key"]
    key_id = (
        await client.get(f"/api/v1/event-sources/{source_id}/keys", headers=auth(token))
    ).json()["keys"][0]["id"]

    # Same session the client's requests use (conftest overrides get_db
    # with it) -- NEVER app.database.AsyncSessionLocal here, that's the
    # real dev database, not the test schema.
    source, api_key = await get_event_source_from_api_key(db_session, f"Bearer {full_key}")
    resolved_source_id = str(source.id)
    assert resolved_source_id == source_id
    assert api_key.last_used_at is not None  # auth records last use

    # Revoke it through the API (the real path a caller uses).
    resp = await client.delete(f"/api/v1/event-sources/{source_id}/keys/{key_id}", headers=auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["revoked"] is True

    with pytest.raises(Exception) as exc:
        await get_event_source_from_api_key(db_session, f"Bearer {full_key}")
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "invalid_api_key"


async def test_disabled_source_rejected_with_403(client, db_session):
    org, owner = await _seed(db_session)
    token = await login(client, owner.email)
    source_id = (
        await client.post(
            "/api/v1/event-sources",
            json={"name": "app feed", "source_type": "application"},
            headers=auth(token),
        )
    ).json()["id"]
    full_key = (
        await client.post(f"/api/v1/event-sources/{source_id}/keys", headers=auth(token))
    ).json()["key"]

    # Owner disables the source.
    resp = await client.delete(f"/api/v1/event-sources/{source_id}", headers=auth(token))
    assert resp.status_code == 200

    with pytest.raises(Exception) as exc:
        await get_event_source_from_api_key(db_session, f"Bearer {full_key}")
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "event_source_disabled"


async def test_key_of_org_a_cannot_authenticate_as_org_b(client, db_session):
    org_a, owner_a = await _seed(db_session, "Org Alpha", email="es-a@example.com")
    org_b, owner_b = await _seed(db_session, "Org Beta", email="es-b@example.com")
    token_a = await login(client, owner_a.email)

    source_a = (
        await client.post(
            "/api/v1/event-sources",
            json={"name": "A collector", "source_type": "custom_json"},
            headers=auth(token_a),
        )
    ).json()
    key_a = (
        await client.post(f"/api/v1/event-sources/{source_a['id']}/keys", headers=auth(token_a))
    ).json()["key"]

    # Auth resolves the key to the source. Compare against org ids captured
    # as plain values BEFORE touching the session again -- after a rollback
    # every ORM instance is expired, and attribute access on an expired
    # instance inside an async session raises MissingGreenlet.
    org_a_id = org_a.id
    org_b_id = org_b.id

    source, _ = await get_event_source_from_api_key(db_session, f"Bearer {key_a}")
    resolved_org_id = source.organization_id

    assert resolved_org_id == org_a_id
    assert resolved_org_id != org_b_id

    # B cannot even LIST A's sources (isolation), let alone mint keys for them.
    token_b = await login(client, owner_b.email)
    assert (await client.get(f"/api/v1/event-sources/{source_a['id']}", headers=auth(token_b))).status_code == 404
    assert (
        await client.post(f"/api/v1/event-sources/{source_a['id']}/keys", headers=auth(token_b))
    ).status_code == 404


# ---------------------------------------------------------------------------
# CRUD role matrix + audits.
# ---------------------------------------------------------------------------

async def _make_source(client, token, name="src"):
    resp = await client.post(
        "/api/v1/event-sources", json={"name": name, "source_type": "network"}, headers=auth(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_crud_role_matrix(client, db_session):
    org, owner = await _seed(db_session)
    owner_token = await login(client, owner.email)
    source = await _make_source(client, owner_token)

    security = await make_user(
        db_session, email="es-sec@test.local", role="security_manager", organization_id=org.id
    )
    it_dev = await make_user(db_session, email="es-it@test.local", role="it_developer", organization_id=org.id)
    analyst = await make_user(db_session, email="es-soc@test.local", role="soc_analyst", organization_id=org.id)
    auditor = await make_user(db_session, email="es-aud@test.local", role="auditor", organization_id=org.id)

    sec_token = await login(client, security.email)
    it_token = await login(client, it_dev.email)
    soc_token = await login(client, analyst.email)
    aud_token = await login(client, auditor.email)

    # security_manager: full write.
    assert (await _make_source(client, sec_token, "sec-src"))["can_manage"] is True
    # it_developer: NO write (dedicated role check, not assets-write).
    assert (await client.post("/api/v1/event-sources", json={"name": "x", "source_type": "docker"}, headers=auth(it_token))).status_code == 403
    assert (await client.post(f"/api/v1/event-sources/{source['id']}/keys", headers=auth(it_token))).status_code == 403
    # soc_analyst / auditor: read-only.
    for tok in (soc_token, aud_token):
        listing = await client.get("/api/v1/event-sources", headers=auth(tok))
        assert listing.status_code == 200
        assert listing.json()["event_sources"][0]["can_manage"] is False
        assert (
            await client.post("/api/v1/event-sources", json={"name": "y", "source_type": "docker"}, headers=auth(tok))
        ).status_code == 403

    # Owner can disable (soft-delete) and revoke.
    resp = await client.patch(f"/api/v1/event-sources/{source['id']}", json={"enabled": False}, headers=auth(owner_token))
    assert resp.status_code == 200 and resp.json()["enabled"] is False


async def test_audit_entries_written_without_key_material(client, db_session):
    org, owner = await _seed(db_session)
    token = await login(client, owner.email)
    source = await _make_source(client, token)
    key_body = (
        await client.post(f"/api/v1/event-sources/{source['id']}/keys", headers=auth(token))
    ).json()

    from sqlalchemy import select

    from app.models import AuditLog

    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "api_key.create"))).scalars().all()
    )
    assert rows, "expected an api_key.create audit entry"
    summary = str(rows[-1].__dict__)
    assert key_body["key"] not in summary, "the full key must never appear in audit data"
    assert key_body["prefix"] in summary


# ---------------------------------------------------------------------------
# Heartbeat job (fake mode -- direct call, no Redis).
# ---------------------------------------------------------------------------

async def test_heartbeat_upserts_single_row(db_session):
    # Inject the TEST session factory (conftest's TestSessionLocal shape:
    # a callable returning an async context manager) -- without this the
    # job would write through the app's DEV AsyncSessionLocal.
    from tests.conftest import TestSessionLocal

    result1 = await heartbeat({}, session_factory=TestSessionLocal)
    assert result1["worker_name"] and result1["pid"] > 0

    from sqlalchemy import select

    from app.models import WorkerStatus

    rows = (await db_session.execute(select(WorkerStatus.id))).scalars().all()
    assert rows == [1]

    await heartbeat({}, session_factory=TestSessionLocal)  # second tick: still one row (id=1)
    rows = (await db_session.execute(select(WorkerStatus.id))).scalars().all()
    assert rows == [1]

    status = (await db_session.execute(select(WorkerStatus).where(WorkerStatus.id == 1))).scalar_one()
    assert status.pid == result1["pid"]
    assert status.last_heartbeat_at is not None
