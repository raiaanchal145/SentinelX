"""
Tests for Profile, Sessions, 2FA, and Command Palette Search (P25).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import (
    Admin,
    AdminLevel,
    Alert,
    AlertStatus,
    Asset,
    AssetCriticality,
    AssetType,
    Incident,
    IncidentStatus,
    Session,
    Ticket,
    TicketStatus,
    User,
    UserRole,
)
from tests.helpers import (
    TEST_PASSWORD,
    auth,
    login,
    make_admin,
    make_organization,
    make_user,
)

PROFILE_BASE = "/api/v1/profile"
PALETTE_BASE = "/api/v1/palette"


@pytest.mark.asyncio
async def test_profile_get_and_update_name(client, db_session):
    org = await make_organization(db_session, name="Cyberdyne")
    user = await make_user(
        db_session,
        email="john.connor@example.com",
        name="John Connor",
        role=UserRole.soc_analyst,
        organization_id=org.id,
    )
    token = await login(client, user.email)

    # 1. GET profile
    res = await client.get(f"{PROFILE_BASE}", headers=auth(token))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["name"] == "John Connor"
    assert data["email"] == "john.connor@example.com"
    assert data["role"] == "soc_analyst"
    assert data["account_type"] == "user"
    assert data["organization_name"] == "Cyberdyne"
    assert data["two_factor_enabled"] is False

    # 2. PUT profile to update name
    res_put = await client.put(f"{PROFILE_BASE}", json={"name": "Sarah Connor"}, headers=auth(token))
    assert res_put.status_code == 200, res_put.text
    assert res_put.json()["name"] == "Sarah Connor"

    # Verify DB update
    updated_user = await db_session.get(User, user.id)
    await db_session.refresh(updated_user)
    assert updated_user.name == "Sarah Connor"


@pytest.mark.asyncio
async def test_change_password_validations_and_session_revocation(client, db_session):
    org = await make_organization(db_session)
    user = await make_user(db_session, email="alice@example.com", organization_id=org.id)

    # Browser 1 login
    token1 = await login(client, user.email)
    # Browser 2 login
    token2 = await login(client, user.email)

    # 1. Wrong old password
    res = await client.post(
        f"{PROFILE_BASE}/change-password",
        json={"old_password": "wrong-password", "new_password": "brand-new-secret", "revoke_other_sessions": True},
        headers=auth(token1),
    )
    assert res.status_code == 400
    assert "Incorrect current password" in res.json()["detail"]

    # 2. Password too short (< 6 chars)
    res = await client.post(
        f"{PROFILE_BASE}/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": "123", "revoke_other_sessions": True},
        headers=auth(token1),
    )
    assert res.status_code in (400, 422)

    # 3. Same password
    res = await client.post(
        f"{PROFILE_BASE}/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": TEST_PASSWORD, "revoke_other_sessions": True},
        headers=auth(token1),
    )
    assert res.status_code == 400
    assert "different from your current password" in res.json()["detail"]

    # 4. Successful change with revoke_other_sessions=True
    res = await client.post(
        f"{PROFILE_BASE}/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": "brand-new-secret", "revoke_other_sessions": True},
        headers=auth(token1),
    )
    assert res.status_code == 200

    # Token 1 (current) must still work
    res_me = await client.get(f"{PROFILE_BASE}", headers=auth(token1))
    assert res_me.status_code == 200

    # Token 2 (other session) MUST be revoked and return 401 on next request!
    res_other = await client.get(f"{PROFILE_BASE}", headers=auth(token2))
    assert res_other.status_code == 401
    assert "revoked" in res_other.json()["detail"].lower()

    # Old password no longer works for login
    res_old_login = await client.post("/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert res_old_login.status_code == 401

    # New password logs in successfully
    res_new_login = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "brand-new-secret"})
    assert res_new_login.status_code == 200


@pytest.mark.asyncio
async def test_session_listing_and_manual_revocation(client, db_session):
    org = await make_organization(db_session)
    user = await make_user(db_session, email="bob@example.com", organization_id=org.id)

    # Session 1: Client A
    token_a = await login(client, user.email)
    # Session 2: Client B
    token_b = await login(client, user.email)

    # List sessions from Client A
    res_sess = await client.get(f"{PROFILE_BASE}/sessions", headers=auth(token_a))
    assert res_sess.status_code == 200
    sessions = res_sess.json()["sessions"]
    assert len(sessions) >= 2

    # Find the current session (Client A) and the other session (Client B)
    curr_sess = [s for s in sessions if s["is_current"]]
    other_sess = [s for s in sessions if not s["is_current"]]
    assert len(curr_sess) == 1
    assert len(other_sess) >= 1

    other_id = other_sess[0]["id"]

    # Revoke Client B's session from Client A
    res_del = await client.delete(f"{PROFILE_BASE}/sessions/{other_id}", headers=auth(token_a))
    assert res_del.status_code == 200
    assert res_del.json()["revoked"] is True

    # Client B's next request MUST fail with 401!
    res_b = await client.get(f"{PROFILE_BASE}", headers=auth(token_b))
    assert res_b.status_code == 401

    # Client A's request MUST still succeed!
    res_a = await client.get(f"{PROFILE_BASE}", headers=auth(token_a))
    assert res_a.status_code == 200


@pytest.mark.asyncio
async def test_two_factor_setup_and_login_flow(client, db_session):
    org = await make_organization(db_session)
    user = await make_user(db_session, email="carol@example.com", organization_id=org.id)
    token = await login(client, user.email)

    # 1. Send 2FA setup code
    res_send = await client.post(f"{PROFILE_BASE}/2fa/send-code", headers=auth(token))
    assert res_send.status_code == 200

    # Retrieve code from DB
    await db_session.refresh(user)
    assert user.two_factor_code is not None

    # 2. Toggle 2FA with wrong code
    res_toggle_bad = await client.post(
        f"{PROFILE_BASE}/2fa/toggle",
        json={"enable": True, "code": "000000"},
        headers=auth(token),
    )
    assert res_toggle_bad.status_code == 400
    assert "Incorrect" in res_toggle_bad.json()["detail"]

    # 3. Toggle 2FA with correct code
    res_toggle_ok = await client.post(
        f"{PROFILE_BASE}/2fa/toggle",
        json={"enable": True, "code": user.two_factor_code},
        headers=auth(token),
    )
    assert res_toggle_ok.status_code == 200
    assert res_toggle_ok.json()["two_factor_enabled"] is True

    # 4. Next login requires 2FA
    res_login = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": TEST_PASSWORD},
    )
    assert res_login.status_code == 200
    login_data = res_login.json()
    assert login_data["requires_2fa"] is True
    assert login_data["temp_token"] != ""
    temp_token = login_data["temp_token"]

    # Attempting to use temp_token on standard API endpoint returns 401
    res_probe = await client.get(f"{PROFILE_BASE}", headers=auth(temp_token))
    assert res_probe.status_code == 401

    # Retrieve newly sent 2FA login code
    await db_session.refresh(user)
    two_factor_login_code = user.two_factor_code
    assert two_factor_login_code is not None

    # 5. Complete 2FA login with incorrect code
    res_2fa_bad = await client.post(
        "/api/v1/auth/login-2fa",
        json={"temp_token": temp_token, "code": "999999"},
    )
    assert res_2fa_bad.status_code == 400

    # 6. Complete 2FA login with correct code
    res_2fa_ok = await client.post(
        "/api/v1/auth/login-2fa",
        json={"temp_token": temp_token, "code": two_factor_login_code},
    )
    assert res_2fa_ok.status_code == 200
    real_token = res_2fa_ok.json()["access_token"]
    assert real_token != ""

    # Real token succeeds
    res_verify = await client.get(f"{PROFILE_BASE}", headers=auth(real_token))
    assert res_verify.status_code == 200
    assert res_verify.json()["email"] == user.email


@pytest.mark.asyncio
async def test_palette_search_scope_isolation(client, db_session):
    # Setup Org 1 and Org 2
    org1 = await make_organization(db_session, name="Acme Security")
    org2 = await make_organization(db_session, name="Beta Corp")

    user1 = await make_user(db_session, email="analyst1@acme.com", organization_id=org1.id)
    user2 = await make_user(db_session, email="analyst2@beta.com", organization_id=org2.id)
    super_admin = await make_admin(
        db_session,
        email="super@sentinelx.io",
        admin_level=AdminLevel.super_admin,
    )

    now = datetime.now(timezone.utc)
    # Seed data in Org 1
    alert1 = Alert(
        organization_id=org1.id,
        rule_name="Brute Force Detection",
        title="Acme SSH Brute Force Alert",
        severity="high",
        status=AlertStatus.new,
        first_seen_at=now,
        last_seen_at=now,
    )
    incident1 = Incident(
        organization_id=org1.id,
        title="Acme Ransomware Outbreak",
        severity="critical",
        status=IncidentStatus.new,
    )
    ticket1 = Ticket(
        organization_id=org1.id,
        ticket_number="1001",
        title="Acme Patch Kernel vulnerability",
        priority="high",
        status=TicketStatus.open,
    )
    asset1 = Asset(
        organization_id=org1.id,
        name="Acme Primary Database Server",
        hostname="db-acme-01.local",
        ip_address="10.0.1.50",
        asset_type=AssetType.server,
        criticality=AssetCriticality.high,
        status="active",
    )
    db_session.add_all([alert1, incident1, ticket1, asset1])

    # Seed data in Org 2
    alert2 = Alert(
        organization_id=org2.id,
        rule_name="Malware Download",
        title="Beta Trojan Download Alert",
        severity="medium",
        status=AlertStatus.new,
        first_seen_at=now,
        last_seen_at=now,
    )
    incident2 = Incident(
        organization_id=org2.id,
        title="Beta Data Exfiltration",
        severity="high",
        status=IncidentStatus.new,
    )
    ticket2 = Ticket(
        organization_id=org2.id,
        ticket_number="2002",
        title="Beta Rotate API Keys",
        priority="medium",
        status=TicketStatus.open,
    )
    asset2 = Asset(
        organization_id=org2.id,
        name="Beta Production Gateway",
        hostname="gw-beta-01.local",
        ip_address="10.0.2.10",
        asset_type=AssetType.firewall,
        criticality=AssetCriticality.critical,
        status="active",
    )
    db_session.add_all([alert2, incident2, ticket2, asset2])
    await db_session.commit()

    token_user1 = await login(client, user1.email)
    token_super = await login(client, super_admin.email)

    # 1. Org 1 user searches "Alert"
    res1 = await client.get(f"{PALETTE_BASE}/search?q=Alert", headers=auth(token_user1))
    assert res1.status_code == 200
    data1 = res1.json()
    alert_titles = [a["title"] for a in data1["alerts"]]
    assert "Acme SSH Brute Force Alert" in alert_titles
    assert "Beta Trojan Download Alert" not in alert_titles, "Tenant isolation breach! Org 1 saw Org 2's alert."

    # 2. Org 1 user searches "1001" (ticket number)
    res_ticket = await client.get(f"{PALETTE_BASE}/search?q=1001", headers=auth(token_user1))
    assert res_ticket.status_code == 200
    assert len(res_ticket.json()["tickets"]) == 1
    assert res_ticket.json()["tickets"][0]["ticket_number"] == "1001"

    # Org 1 user searches Org 2 ticket "2002" -> must NOT be returned!
    res_ticket_leak = await client.get(f"{PALETTE_BASE}/search?q=2002", headers=auth(token_user1))
    assert res_ticket_leak.status_code == 200
    assert len(res_ticket_leak.json()["tickets"]) == 0

    # 3. Super Admin searches "Alert" -> sees alerts from both organizations
    res_super = await client.get(f"{PALETTE_BASE}/search?q=Alert", headers=auth(token_super))
    assert res_super.status_code == 200
    super_alert_titles = [a["title"] for a in res_super.json()["alerts"]]
    assert "Acme SSH Brute Force Alert" in super_alert_titles
    assert "Beta Trojan Download Alert" in super_alert_titles
