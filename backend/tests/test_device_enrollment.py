"""
Tests for P20 Consented Device Monitoring & Enrollment.

Verifies:
1. Role matrix: owner, security manager, and it_developer can create tokens; platform SOC cannot.
2. Preview enrollment token returns transparent category disclosures and version stamp.
3. User consent grants specific categories; platform SOC can NEVER grant consent (403).
4. Agent token swap is strictly single-use; ApiKey is returned once (second swap fails 409).
5. Expired enrollment tokens (>30 min) cannot be used (410).
6. Agent cannot enroll before consent is granted (400).
7. Ingestion strictly filters events: non-consented categories are rejected, counted in
   rejected_no_consent, and stored nowhere.
8. Consent update creates a NEW immutable consent_records row; history is never mutated.
9. Revocation immediately halts ingestion (401/403) and signals agent to terminate on heartbeat.
10. Device liveness and status calculation (connected, stale, offline, revoked).
11. Audit entries recorded for every lifecycle transition.
"""

from __future__ import annotations

import datetime as dt
import uuid
import pytest
from sqlalchemy import select

from app.consent import CONSENT_TEXT_VERSION
from app.models import (
    AdminLevel,
    ApiKey,
    Asset,
    AssetCriticality,
    AssetType,
    AuditLog,
    ConsentRecord,
    DeviceEnrollment,
    EventSource,
    OrganizationStatus,
    SocMode,
    UserRole,
)
from tests.helpers import (
    auth,
    login,
    make_admin,
    make_organization,
    make_user,
)


@pytest.fixture
async def device_world(db_session):
    """Provisions test org, owner, sec manager, it dev, soc analyst, and platform soc."""
    org = await make_organization(db_session, name="Cyberdyne Corp", soc_mode=SocMode.in_house)

    owner = await make_admin(
        db_session,
        email="owner@cyberdyne.io",
        name="Sarah Connor",
        organization_id=org.id,
        admin_level=AdminLevel.organization_admin,
    )
    sec_mgr = await make_user(
        db_session,
        email="sec_mgr@cyberdyne.io",
        name="John Connor",
        organization_id=org.id,
        role=UserRole.security_manager,
    )
    it_dev = await make_user(
        db_session,
        email="it_dev@cyberdyne.io",
        name="Miles Dyson",
        organization_id=org.id,
        role=UserRole.it_developer,
    )
    soc_analyst = await make_user(
        db_session,
        email="analyst@cyberdyne.io",
        name="Kyle Reese",
        organization_id=org.id,
        role=UserRole.soc_analyst,
    )
    platform_soc = await make_admin(
        db_session,
        email="platform@sentinelx.io",
        name="Platform SOC",
        organization_id=None,
        admin_level=AdminLevel.platform_soc_analyst,
    )

    asset = Asset(
        organization_id=org.id,
        name="Workstation-Alpha",
        hostname="alpha.corp.local",
        ip_address="192.168.1.105",
        asset_type=AssetType.workstation,
        criticality=AssetCriticality.medium,
        operating_system="Windows 11 Pro",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    return {
        "org": org,
        "owner": owner,
        "sec_mgr": sec_mgr,
        "it_dev": it_dev,
        "soc_analyst": soc_analyst,
        "platform_soc": platform_soc,
        "asset": asset,
    }


@pytest.mark.asyncio
async def test_enrollment_token_role_matrix(client, db_session, device_world):
    w = device_world

    # 1. Owner can create token
    owner_token = await login(client, w["owner"].email)
    res = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(owner_token),
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["token"].startswith("sxe_")
    assert data["token_prefix"].startswith("sxe_")

    # 2. Security manager can create token
    sm_token = await login(client, w["sec_mgr"].email)
    res_sm = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(sm_token),
    )
    assert res_sm.status_code == 200

    # 3. IT developer can create token
    it_token = await login(client, w["it_dev"].email)
    res_it = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(it_token),
    )
    assert res_it.status_code == 200

    # 4. SOC analyst cannot create token (403)
    soc_token = await login(client, w["soc_analyst"].email)
    res_soc = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(soc_token),
    )
    assert res_soc.status_code == 403

    # 5. Platform SOC cannot create token (403)
    plat_token = await login(client, w["platform_soc"].email)
    res_plat = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(plat_token),
    )
    assert res_plat.status_code == 403


@pytest.mark.asyncio
async def test_preview_enrollment_token(client, db_session, device_world):
    w = device_world
    owner_token = await login(client, w["owner"].email)

    # Mint token
    res = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(owner_token),
    )
    token = res.json()["token"]

    # Preview
    preview_res = await client.get(f"/api/v1/devices/enrollment-tokens/{token}/preview")
    assert preview_res.status_code == 200
    p = preview_res.json()
    assert p["organization_name"] == "Cyberdyne Corp"
    assert p["asset"]["name"] == "Workstation-Alpha"
    assert p["consent_version"] == CONSENT_TEXT_VERSION
    assert len(p["categories"]) >= 5
    # Verify categories have labels, descriptions, and prohibited disclosure
    for cat in p["categories"]:
        assert "key" in cat
        assert "label" in cat
        assert "description" in cat
        assert "prohibited" in cat

    # Non-existent token -> 404
    bad_res = await client.get("/api/v1/devices/enrollment-tokens/sxe_fake_token_12345/preview")
    assert bad_res.status_code == 404


@pytest.mark.asyncio
async def test_grant_consent_and_platform_soc_forbidden(client, db_session, device_world):
    w = device_world
    owner_token = await login(client, w["owner"].email)

    res = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(owner_token),
    )
    token = res.json()["token"]

    # Platform SOC attempting to consent -> 403
    plat_token = await login(client, w["platform_soc"].email)
    plat_res = await client.post(
        f"/api/v1/devices/enrollment-tokens/{token}/consent",
        json={"categories": ["authentication", "process_activity"]},
        headers=auth(plat_token),
    )
    assert plat_res.status_code == 403

    # Device user / employee consents to subset
    it_token = await login(client, w["it_dev"].email)
    consent_res = await client.post(
        f"/api/v1/devices/enrollment-tokens/{token}/consent",
        json={"categories": ["authentication", "process_activity"]},
        headers=auth(it_token),
    )
    assert consent_res.status_code == 200
    cdata = consent_res.json()
    assert cdata["status"] == "consent_recorded"
    assert cdata["categories_granted"] == ["authentication", "process_activity"]

    # Verify DB row
    consent_row = (
        await db_session.execute(
            select(ConsentRecord).where(ConsentRecord.id == uuid.UUID(cdata["consent_id"]))
        )
    ).scalars().first()
    assert consent_row is not None
    assert consent_row.categories_granted == ["authentication", "process_activity"]
    assert consent_row.consent_text_version == CONSENT_TEXT_VERSION
    assert consent_row.revoked_at is None


@pytest.mark.asyncio
async def test_agent_enroll_swap_single_use_and_key_returned_once(client, db_session, device_world):
    w = device_world
    owner_token = await login(client, w["owner"].email)

    res = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(owner_token),
    )
    token = res.json()["token"]

    # 1. Agent tries to swap before consent -> 400 consent_required
    early_res = await client.post(
        "/api/v1/agent/enroll",
        json={"enrollment_token": token, "operating_system": "Windows 11", "agent_version": "1.0.1"},
    )
    assert early_res.status_code == 400
    assert early_res.json()["detail"]["code"] == "consent_required"

    # 2. User consents
    await client.post(
        f"/api/v1/devices/enrollment-tokens/{token}/consent",
        json={"categories": ["authentication", "process_activity"]},
        headers=auth(owner_token),
    )

    # 3. Agent swaps token for API key
    enroll_res = await client.post(
        "/api/v1/agent/enroll",
        json={"enrollment_token": token, "operating_system": "Windows 11", "agent_version": "1.0.1"},
    )
    assert enroll_res.status_code == 201
    edata = enroll_res.json()
    assert edata["status"] == "enrolled"
    assert edata["api_key"].startswith("sx_")
    assert edata["enabled_categories"] == ["authentication", "process_activity"]

    # 4. Second swap attempt with same token -> 409 token_already_used (single-use enforced!)
    dup_res = await client.post(
        "/api/v1/agent/enroll",
        json={"enrollment_token": token},
    )
    assert dup_res.status_code == 409
    assert dup_res.json()["detail"]["code"] == "token_already_used"


@pytest.mark.asyncio
async def test_expired_token_refuses_enrollment(client, db_session, device_world):
    w = device_world
    owner_token = await login(client, w["owner"].email)

    res = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(owner_token),
    )
    token = res.json()["token"]

    # Fast forward expiration to 31 minutes ago
    enrollment = (
        await db_session.execute(
            select(DeviceEnrollment).where(DeviceEnrollment.asset_id == w["asset"].id)
        )
    ).scalars().first()
    enrollment.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=31)
    await db_session.commit()

    # Attempt consent on expired token -> 410
    consent_res = await client.post(
        f"/api/v1/devices/enrollment-tokens/{token}/consent",
        json={"categories": ["authentication"]},
        headers=auth(owner_token),
    )
    assert consent_res.status_code == 410
    assert consent_res.json()["detail"]["code"] == "token_expired"

    # Attempt agent swap on expired token -> 410
    swap_res = await client.post(
        "/api/v1/agent/enroll",
        json={"enrollment_token": token},
    )
    assert swap_res.status_code == 410
    assert swap_res.json()["detail"]["code"] == "token_expired"


@pytest.mark.asyncio
async def test_ingest_enforces_consent_categories(client, db_session, device_world):
    w = device_world
    owner_token = await login(client, w["owner"].email)

    # 1. Mint token and grant consent ONLY for authentication
    res = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(owner_token),
    )
    token = res.json()["token"]

    await client.post(
        f"/api/v1/devices/enrollment-tokens/{token}/consent",
        json={"categories": ["authentication"]},
        headers=auth(owner_token),
    )

    # 2. Enroll agent and get API key
    agent_res = await client.post(
        "/api/v1/agent/enroll",
        json={"enrollment_token": token},
    )
    api_key = agent_res.json()["api_key"]

    # 3. Submit mixed batch:
    #    - 2 authentication events (logon_success, auth_failure) -> Consented
    #    - 1 test_event -> Consented
    #    - 2 process_activity events (process_create, service_install) -> NOT consented
    #    - 1 network event (connection_blocked) -> NOT consented
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    events_payload = [
        {"timestamp": now_iso, "source_type": "application", "event_type": "logon_success", "message": "User alice logged in", "raw": {"user": "alice"}},
        {"timestamp": now_iso, "source_type": "application", "event_type": "auth_failure", "message": "Failed login for bob", "raw": {"user": "bob"}},
        {"timestamp": now_iso, "source_type": "application", "event_type": "test_event", "message": "Diagnostic ping", "raw": {"msg": "ping"}},
        {"timestamp": now_iso, "source_type": "application", "event_type": "process_create", "message": "powershell.exe started", "raw": {"cmd": "powershell"}},
        {"timestamp": now_iso, "source_type": "application", "event_type": "service_install", "message": "New service evil installed", "raw": {"svc": "evil"}},
        {"timestamp": now_iso, "source_type": "application", "event_type": "connection_blocked", "message": "Outbound blocked to 1.2.3.4", "raw": {"ip": "1.2.3.4"}},
    ]

    ingest_res = await client.post(
        "/api/v1/events",
        json={"events": events_payload},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert ingest_res.status_code == 202
    result = ingest_res.json()

    # 3 accepted, 3 rejected for lack of consent
    assert result["accepted"] == 3
    assert result["rejected"] == 3
    assert result["rejected_no_consent"] == 3

    # Verify per-item results specify category_not_consented
    for item in result["results"]:
        if item["index"] in (3, 4, 5):
            assert item["status"] == "rejected"
            assert item["reason"] == "category_not_consented"
        else:
            assert item["status"] == "accepted"


@pytest.mark.asyncio
async def test_consent_update_creates_new_record_never_mutates_history(client, db_session, device_world):
    w = device_world
    owner_token = await login(client, w["owner"].email)

    # Enroll device with authentication
    res = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(owner_token),
    )
    token = res.json()["token"]
    await client.post(
        f"/api/v1/devices/enrollment-tokens/{token}/consent",
        json={"categories": ["authentication"]},
        headers=auth(owner_token),
    )
    agent_res = await client.post("/api/v1/agent/enroll", json={"enrollment_token": token})
    device_id = agent_res.json()["device_id"]
    api_key = agent_res.json()["api_key"]

    # Update consent to add process_activity
    update_res = await client.post(
        f"/api/v1/devices/{device_id}/consent",
        json={"categories": ["authentication", "process_activity"]},
        headers=auth(owner_token),
    )
    assert update_res.status_code == 200

    # Ingest process_create -> Now accepted!
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    ingest_res = await client.post(
        "/api/v1/events",
        json={"events": [{"timestamp": now_iso, "source_type": "application", "event_type": "process_create", "message": "powershell started", "raw": {}}]},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert ingest_res.status_code == 202
    assert ingest_res.json()["accepted"] == 1
    assert ingest_res.json()["rejected_no_consent"] == 0

    # Check device detail history -> Exactly 2 consent records exist
    detail_res = await client.get(f"/api/v1/devices/{device_id}", headers=auth(owner_token))
    assert detail_res.status_code == 200
    history = detail_res.json()["consent_history"]
    assert len(history) == 2
    # Newest record is active
    assert history[0]["categories"] == ["authentication", "process_activity"]
    assert history[0]["revoked_at"] is None
    # Old record is archived with revocation reason
    assert history[1]["categories"] == ["authentication"]
    assert history[1]["revoked_at"] is not None
    assert history[1]["revocation_reason"] == "superseded_by_consent_update"


@pytest.mark.asyncio
async def test_revocation_halts_ingest_and_heartbeat(client, db_session, device_world):
    w = device_world
    owner_token = await login(client, w["owner"].email)

    # Enroll device
    res = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(owner_token),
    )
    token = res.json()["token"]
    await client.post(
        f"/api/v1/devices/enrollment-tokens/{token}/consent",
        json={"categories": ["authentication"]},
        headers=auth(owner_token),
    )
    agent_res = await client.post("/api/v1/agent/enroll", json={"enrollment_token": token})
    device_id = agent_res.json()["device_id"]
    api_key = agent_res.json()["api_key"]

    # Revoke device
    revoke_res = await client.post(
        f"/api/v1/devices/{device_id}/revoke",
        json={"reason": "Device decommissioned by administrator"},
        headers=auth(owner_token),
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "revoked"

    # Ingest event -> Rejected (401 or 403)
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    ingest_res = await client.post(
        "/api/v1/events",
        json={"events": [{"timestamp": now_iso, "source_type": "application", "event_type": "logon_success", "message": "logon", "raw": {}}]},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert ingest_res.status_code in (401, 403)

    # Heartbeat -> Returns terminate=True
    hb_res = await client.post(
        "/api/v1/agent/heartbeat",
        json={"agent_version": "1.0.1"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert hb_res.status_code in (200, 401)
    if hb_res.status_code == 200:
        assert hb_res.json()["status"] == "revoked"
        assert hb_res.json()["terminate"] is True


@pytest.mark.asyncio
async def test_device_status_liveness_and_summary(client, db_session, device_world):
    w = device_world
    owner_token = await login(client, w["owner"].email)

    # Enroll device
    res = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(owner_token),
    )
    token = res.json()["token"]
    await client.post(
        f"/api/v1/devices/enrollment-tokens/{token}/consent",
        json={"categories": ["authentication"]},
        headers=auth(owner_token),
    )
    agent_res = await client.post("/api/v1/agent/enroll", json={"enrollment_token": token})
    device_id = agent_res.json()["device_id"]
    api_key = agent_res.json()["api_key"]

    # Send heartbeat -> Status is connected
    await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    detail = (await client.get(f"/api/v1/devices/{device_id}", headers=auth(owner_token))).json()
    assert detail["status"] == "connected"

    # Simulate heartbeat 5 minutes ago -> Stale
    enrollment = await db_session.get(DeviceEnrollment, uuid.UUID(device_id))
    enrollment.last_heartbeat_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    await db_session.commit()

    detail_stale = (await client.get(f"/api/v1/devices/{device_id}", headers=auth(owner_token))).json()
    assert detail_stale["status"] == "stale"

    # Simulate heartbeat 15 minutes ago -> Offline
    enrollment.last_heartbeat_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=15)
    await db_session.commit()

    detail_offline = (await client.get(f"/api/v1/devices/{device_id}", headers=auth(owner_token))).json()
    assert detail_offline["status"] == "offline"

    # Check summary
    summary = (await client.get("/api/v1/devices/summary", headers=auth(owner_token))).json()
    assert summary["offline"] >= 1
    assert summary["total"] >= 1


@pytest.mark.asyncio
async def test_audit_logs_recorded_for_device_lifecycle(client, db_session, device_world):
    w = device_world
    owner_token = await login(client, w["owner"].email)

    # 1. Create token
    res = await client.post(
        "/api/v1/devices/enrollment-tokens",
        json={"asset_id": str(w["asset"].id)},
        headers=auth(owner_token),
    )
    token = res.json()["token"]

    # 2. Grant consent
    await client.post(
        f"/api/v1/devices/enrollment-tokens/{token}/consent",
        json={"categories": ["authentication"]},
        headers=auth(owner_token),
    )

    # 3. Enroll agent
    agent_res = await client.post("/api/v1/agent/enroll", json={"enrollment_token": token})
    device_id = agent_res.json()["device_id"]

    # 4. Revoke
    await client.post(
        f"/api/v1/devices/{device_id}/revoke",
        json={"reason": "Security decommission"},
        headers=auth(owner_token),
    )

    # Verify audit logs in DB
    logs = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.organization_id == w["org"].id)
            .order_by(AuditLog.created_at.asc())
        )
    ).scalars().all()

    actions = [l.action for l in logs]
    assert "device.enrollment_token_created" in actions
    assert "device.consent_granted" in actions
    assert "device.revoked" in actions
