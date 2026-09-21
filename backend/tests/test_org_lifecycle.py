"""
End-to-end coverage of the spec's own "DONE WHEN" scenario: self-signup
creates a pending organization; a super_admin approves it; the owner
logs in, invites an IT developer; the invitee accepts and logs in and
/auth/me shows exactly the modules their role/org/overrides allow; the
owner denies a module for that person and it disappears from
effective_modules; the platform switches the organization to in_house
and a soc_analyst can then be invited and reaches full soc_analyst access.

No SMTP is configured in tests, so nobody's invite link ever actually
gets emailed -- the raw invitation token isn't returned by any endpoint
either (only its hash is ever stored, by design). Rather than reaching
into invite_service internals, this test mints a token the exact same
way app.security.generate_invitation_token() does and stamps its hash
directly onto the already-created invitation row, which is equivalent
to "the email link the invitee actually clicked".
"""

from sqlalchemy import select

from app.models import AdminLevel, Invitation, Organization, OrganizationStatus, PendingRegistration
from app.security import generate_invitation_token, hash_invitation_token
from tests.helpers import auth, login, make_admin

ADMIN_BASE = "/api/v1/admin/organizations"
ORG_BASE = "/api/v1/organization"
INVITATIONS_BASE = "/api/v1/invitations"


async def _mint_and_stamp_token(db_session, *, email: str) -> str:
    raw_token, token_hash = generate_invitation_token()
    invitation = (await db_session.execute(select(Invitation).where(Invitation.email == email))).scalar_one()
    invitation.token_hash = token_hash
    await db_session.commit()
    assert hash_invitation_token(raw_token) == token_hash
    return raw_token


async def test_full_signup_to_soc_staffing_lifecycle(client, db_session):
    # 1. Self-signup: register -> verify -> a brand-new pending organization.
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Olivia Owner",
            "email": "olivia@example.com",
            "password": "correct-horse-battery",
            "organization_name": "Aurora Health",
            "industry": "Healthcare",
        },
    )
    assert register_resp.status_code == 200, register_resp.text

    pending = (
        await db_session.execute(select(PendingRegistration).where(PendingRegistration.email == "olivia@example.com"))
    ).scalar_one()
    code = pending.verification_code

    verify_resp = await client.post(
        "/api/v1/auth/verify-email", json={"email": "olivia@example.com", "code": code}
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["account_type"] == "admin"
    assert verify_resp.json()["role"] == "organization_admin"

    org = (await db_session.execute(select(Organization).where(Organization.name == "Aurora Health"))).scalar_one()
    assert org.status == OrganizationStatus.pending
    assert org.industry == "Healthcare"

    # Login is allowed while pending, but the organization endpoints are not.
    owner_login = await client.post(
        "/api/v1/auth/login", json={"email": "olivia@example.com", "password": "correct-horse-battery"}
    )
    assert owner_login.status_code == 200
    owner_token = owner_login.json()["access_token"]

    blocked = await client.get(f"{ORG_BASE}/members", headers=auth(owner_token))
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "organization_pending"

    overview_while_pending = await client.get(ORG_BASE, headers=auth(owner_token))
    assert overview_while_pending.status_code == 200
    assert overview_while_pending.json()["status"] == "pending"

    # 2. super_admin approves the organization.
    await make_admin(db_session, email="root@example.com", admin_level=AdminLevel.super_admin)
    root_token = await login(client, "root@example.com")

    approve_resp = await client.post(f"{ADMIN_BASE}/{org.id}/approve", headers=auth(root_token))
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "active"

    # 3. Owner can now use the organization; invites an IT developer.
    invite_resp = await client.post(
        f"{ORG_BASE}/invitations",
        json={"email": "dev@example.com", "role": "it_developer"},
        headers=auth(owner_token),
    )
    assert invite_resp.status_code == 201, invite_resp.text

    dev_raw_token = await _mint_and_stamp_token(db_session, email="dev@example.com")

    # 4. The invitee accepts and logs in; /auth/me shows exactly their role's
    # default modules (assets: read, it_tickets: write) -- nothing else,
    # since the organization is still soc_mode=managed at this point.
    accept_resp = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": dev_raw_token, "full_name": "Dana Developer", "password": "correct-horse-battery"},
    )
    assert accept_resp.status_code == 200, accept_resp.text
    dev_token = accept_resp.json()["access_token"]
    dev_id = accept_resp.json()["user"]["id"]

    me_resp = await client.get("/api/v1/auth/me", headers=auth(dev_token))
    assert me_resp.status_code == 200
    assert me_resp.json()["effective_modules"] == {"assets": "read", "it_tickets": "write"}

    # 5. Owner denies a module for that member; it disappears from effective_modules.
    deny_resp = await client.put(
        f"{ORG_BASE}/members/{dev_id}/access",
        json={"denied_modules": ["it_tickets"]},
        headers=auth(owner_token),
    )
    assert deny_resp.status_code == 200

    me_after_deny = await client.get("/api/v1/auth/me", headers=auth(dev_token))
    assert me_after_deny.json()["effective_modules"] == {"assets": "read"}

    # 6. Inviting a soc_analyst is rejected while the organization is
    # managed, since only platform SOC staff work its incidents.
    soc_rejected = await client.post(
        f"{ORG_BASE}/invitations", json={"email": "analyst@example.com", "role": "soc_analyst"}, headers=auth(owner_token)
    )
    assert soc_rejected.status_code == 422
    assert soc_rejected.json()["detail"]["code"] == "soc_analyst_requires_in_house"

    # 7. Platform admin switches the organization to in_house.
    soc_mode_resp = await client.put(
        f"{ADMIN_BASE}/{org.id}/soc-mode", json={"soc_mode": "in_house"}, headers=auth(root_token)
    )
    assert soc_mode_resp.status_code == 200
    assert soc_mode_resp.json()["organization"]["soc_mode"] == "in_house"

    # 8. Now a soc_analyst can be invited, accepted, and reaches full
    # soc_analyst access.
    soc_invite_resp = await client.post(
        f"{ORG_BASE}/invitations", json={"email": "analyst@example.com", "role": "soc_analyst"}, headers=auth(owner_token)
    )
    assert soc_invite_resp.status_code == 201

    soc_raw_token = await _mint_and_stamp_token(db_session, email="analyst@example.com")

    soc_accept_resp = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": soc_raw_token, "full_name": "Sam Analyst", "password": "correct-horse-battery"},
    )
    assert soc_accept_resp.status_code == 200, soc_accept_resp.text
    soc_analyst_token = soc_accept_resp.json()["access_token"]

    soc_me_resp = await client.get("/api/v1/auth/me", headers=auth(soc_analyst_token))
    assert soc_me_resp.json()["effective_modules"] == {
        "assets": "write", "soc": "write", "incidents": "write", "ai_agents": "write", "reports": "write",
    }
