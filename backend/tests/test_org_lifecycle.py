"""
End-to-end coverage of the invite-only lifecycle (docs/DECISIONS.md):
the platform admin creates an organization (active immediately) together
with the owner's invitation; the owner accepts it, sets a password, logs
in and reaches the organization endpoints; the owner invites an IT
developer, who accepts and logs in and /auth/me shows exactly the
modules their role/org/overrides allow; the owner denies a module for
that person and it disappears from effective_modules; the platform
switches the organization to in_house and a soc_analyst can then be
invited and reaches full soc_analyst access. Also covers the
super_admin's owner-invitation management endpoints (list / resend /
revoke) and what a suspended/archived organization looks like to its
owner.

No SMTP is configured in tests, so nobody's invite link ever actually
gets emailed -- the raw invitation token isn't returned by any endpoint
either (only its hash is ever stored, by design). Rather than reaching
into invite_service internals, this test mints a token the exact same
way app.security.generate_invitation_token() does and stamps its hash
directly onto the already-created invitation row, which is equivalent
to "the email link the invitee actually clicked".
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import AdminLevel, Invitation
from app.security import generate_invitation_token, hash_invitation_token
from tests.helpers import auth, login, make_admin, make_organization, make_user

ADMIN_BASE = "/api/v1/admin/organizations"
ORG_BASE = "/api/v1/organization"
INVITATIONS_BASE = "/api/v1/invitations"

from app.models import UserRole  # noqa: E402  (grouped with the helpers above)


async def _mint_and_stamp_token(db_session, *, email: str) -> str:
    raw_token, token_hash = generate_invitation_token()
    invitation = (
        await db_session.execute(select(Invitation).where(Invitation.email == email))
    ).scalar_one()
    invitation.token_hash = token_hash
    await db_session.commit()
    assert hash_invitation_token(raw_token) == token_hash
    return raw_token


async def _super_admin_token(client, db_session) -> str:
    await make_admin(db_session, email="root@example.com", admin_level=AdminLevel.super_admin)
    return await login(client, "root@example.com")


async def _create_org(client, root_token, *, name, owner_email, soc_mode="managed"):
    resp = await client.post(
        ADMIN_BASE,
        json={"name": name, "owner_email": owner_email, "soc_mode": soc_mode, "industry": "Healthcare"},
        headers=auth(root_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_full_invite_only_lifecycle(client, db_session):
    # 1. The platform admin creates the organization (active immediately)
    #    together with the owner's invitation.
    root_token = await _super_admin_token(client, db_session)
    org_row = await _create_org(client, root_token, name="Aurora Health", owner_email="olivia@example.com")
    org_id = org_row["id"]
    assert org_row["status"] == "active"

    # 2. The owner accepts the invitation, sets a password, and is
    #    straight in -- no OTP step: the link proved email ownership.
    raw_token = await _mint_and_stamp_token(db_session, email="olivia@example.com")
    accept_resp = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": raw_token, "full_name": "Olivia Owner", "password": "correct-horse-battery"},
    )
    assert accept_resp.status_code == 200, accept_resp.text
    owner_token = accept_resp.json()["access_token"]
    owner_id = accept_resp.json()["user"]["id"]

    me_resp = await client.get("/api/v1/auth/me", headers=auth(owner_token))
    assert me_resp.status_code == 200
    assert me_resp.json()["role"] == "organization_admin"
    assert me_resp.json()["organization"]["status"] == "active"
    # Owner defaults with every module enabled while soc_mode=managed:
    # everything at write except soc/incidents (oversight-only read).
    assert me_resp.json()["effective_modules"] == {
        "assets": "write", "soc": "read", "incidents": "read",
        "it_tickets": "write", "approvals": "write", "ai_agents": "write",
        "device_agents": "write", "reports": "write", "audit_logs": "write",
    }

    # 3. The owner reaches the organization endpoints right away.
    overview = await client.get(ORG_BASE, headers=auth(owner_token))
    assert overview.status_code == 200
    assert overview.json()["status"] == "active"
    assert "recent_activity" in overview.json()
    assert "members" in overview.json()

    # 4. Invites an IT developer, who accepts and logs in.
    invite_resp = await client.post(
        f"{ORG_BASE}/invitations",
        json={"email": "dev@example.com", "role": "it_developer"},
        headers=auth(owner_token),
    )
    assert invite_resp.status_code == 201, invite_resp.text

    dev_raw_token = await _mint_and_stamp_token(db_session, email="dev@example.com")
    dev_accept = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": dev_raw_token, "full_name": "Dana Developer", "password": "correct-horse-battery"},
    )
    assert dev_accept.status_code == 200, dev_accept.text
    dev_token = dev_accept.json()["access_token"]
    dev_id = dev_accept.json()["user"]["id"]

    dev_me = await client.get("/api/v1/auth/me", headers=auth(dev_token))
    assert dev_me.status_code == 200
    assert dev_me.json()["effective_modules"] == {"assets": "write", "it_tickets": "write"}

    # 5. Owner denies a module for that member; it disappears from
    #    effective_modules.
    deny_resp = await client.put(
        f"{ORG_BASE}/members/{dev_id}/access",
        json={"denied_modules": ["it_tickets"]},
        headers=auth(owner_token),
    )
    assert deny_resp.status_code == 200

    dev_me_after_deny = await client.get("/api/v1/auth/me", headers=auth(dev_token))
    assert dev_me_after_deny.json()["effective_modules"] == {"assets": "write"}

    # 6. Inviting a soc_analyst is rejected while the organization is
    #    managed, since only platform SOC staff work its incidents.
    soc_rejected = await client.post(
        f"{ORG_BASE}/invitations",
        json={"email": "analyst@example.com", "role": "soc_analyst"},
        headers=auth(owner_token),
    )
    assert soc_rejected.status_code == 422
    assert soc_rejected.json()["detail"]["code"] == "soc_analyst_requires_in_house"

    # 7. Platform admin switches the organization to in_house.
    soc_mode_resp = await client.put(
        f"{ADMIN_BASE}/{org_id}/soc-mode", json={"soc_mode": "in_house"}, headers=auth(root_token)
    )
    assert soc_mode_resp.status_code == 200
    assert soc_mode_resp.json()["organization"]["soc_mode"] == "in_house"

    # 8. Now a soc_analyst can be invited, accepted, and reaches full
    #    soc_analyst access.
    soc_invite_resp = await client.post(
        f"{ORG_BASE}/invitations",
        json={"email": "analyst@example.com", "role": "soc_analyst"},
        headers=auth(owner_token),
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
        "assets": "read", "soc": "write", "incidents": "write", "ai_agents": "write", "reports": "write",
    }

    # 9. The platform admin's view of "has the owner accepted yet?":
    #    the list shows the accepted owner invitation, and a non-pending
    #    one can be neither resent nor revoked.
    invs = await client.get(f"{ADMIN_BASE}/{org_id}/invitations", headers=auth(root_token))
    assert invs.status_code == 200
    owner_inv = next(i for i in invs.json()["invitations"] if i["email"] == "olivia@example.com")
    assert owner_inv["status"] == "accepted"

    resend = await client.post(
        f"{ADMIN_BASE}/{org_id}/invitations/{owner_inv['id']}/resend", headers=auth(root_token)
    )
    assert resend.status_code == 409
    assert resend.json()["detail"]["code"] == "invitation_not_pending"

    revoke = await client.delete(
        f"{ADMIN_BASE}/{org_id}/invitations/{owner_inv['id']}", headers=auth(root_token)
    )
    assert revoke.status_code == 409
    assert revoke.json()["detail"]["code"] == "invitation_not_pending"


async def test_owner_invitation_resend_rotates_expiry_shows_and_revoke_blocks_the_link(client, db_session):
    root_token = await _super_admin_token(client, db_session)
    org_row = await _create_org(client, root_token, name="Resend Org", owner_email="late.owner@example.com")
    org_id = org_row["id"]

    listed = await client.get(f"{ADMIN_BASE}/{org_id}/invitations", headers=auth(root_token))
    invitation = listed.json()["invitations"][0]
    assert invitation["status"] == "pending"
    assert invitation["expired"] is False

    # Stamp a token we know onto the row, so we can later prove the
    # revoked link is dead.
    usable_token = await _mint_and_stamp_token(db_session, email="late.owner@example.com")

    row = (
        await db_session.execute(select(Invitation).where(Invitation.email == "late.owner@example.com"))
    ).scalar_one()
    hash_after_stamp = row.token_hash

    # Resend rotates the token on the SAME row (the old link stops
    # working) and pushes the expiry out.
    row.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db_session.commit()
    old_row = (
        await db_session.execute(select(Invitation).where(Invitation.email == "late.owner@example.com"))
    ).scalar_one()
    old_expiry = old_row.expires_at

    resend = await client.post(
        f"{ADMIN_BASE}/{org_id}/invitations/{invitation['id']}/resend", headers=auth(root_token)
    )
    assert resend.status_code == 200
    await db_session.refresh(old_row)
    assert old_row.token_hash != hash_after_stamp
    assert old_row.expires_at > old_expiry

    # An expired-but-still-pending invitation reads as expired in the
    # list before anyone clicks the link.
    old_row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()
    listing = await client.get(f"{ADMIN_BASE}/{org_id}/invitations", headers=auth(root_token))
    listing_row = next(i for i in listing.json()["invitations"] if i["email"] == "late.owner@example.com")
    assert listing_row["expired"] is True

    # Revoke flips the row to revoked; the link we hold now 404s, and a
    # second revoke is refused.
    revoke = await client.delete(
        f"{ADMIN_BASE}/{org_id}/invitations/{invitation['id']}", headers=auth(root_token)
    )
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "revoked"

    accept_revoked = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": usable_token, "full_name": "Too Late", "password": "correct-horse-battery"},
    )
    assert accept_revoked.status_code == 404

    revoke_again = await client.delete(
        f"{ADMIN_BASE}/{org_id}/invitations/{invitation['id']}", headers=auth(root_token)
    )
    assert revoke_again.status_code == 409
    assert revoke_again.json()["detail"]["code"] == "invitation_not_pending"


async def test_suspended_and_archived_organization_owner_keeps_me_and_overview_only(client, db_session):
    root_token = await _super_admin_token(client, db_session)
    org_row = await _create_org(client, root_token, name="Susp Org", owner_email="susp.owner@example.com")
    org_id = org_row["id"]

    raw_token = await _mint_and_stamp_token(db_session, email="susp.owner@example.com")
    accept_resp = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": raw_token, "full_name": "Susp Owner", "password": "correct-horse-battery"},
    )
    assert accept_resp.status_code == 200
    owner_token = accept_resp.json()["access_token"]

    suspend = await client.post(
        f"{ADMIN_BASE}/{org_id}/suspend", json={"reason": "Non-payment"}, headers=auth(root_token)
    )
    assert suspend.status_code == 200

    # me and the overview keep working (the frontend needs them to show
    # the right screen at all); member endpoints do not.
    me = await client.get("/api/v1/auth/me", headers=auth(owner_token))
    assert me.status_code == 200
    assert me.json()["organization"]["status"] == "suspended"

    overview = await client.get(ORG_BASE, headers=auth(owner_token))
    assert overview.status_code == 200
    assert overview.json()["status"] == "suspended"

    members = await client.get(f"{ORG_BASE}/members", headers=auth(owner_token))
    assert members.status_code == 403
    assert members.json()["detail"]["code"] == "organization_suspended"

    # A fresh login is blocked outright with the machine-readable reason.
    blocked_login = await client.post(
        "/api/v1/auth/login", json={"email": "susp.owner@example.com", "password": "correct-horse-battery"}
    )
    assert blocked_login.status_code == 401
    assert blocked_login.json()["detail"]["code"] == "organization_suspended"

    # Archiving on top of suspension: same shape, archived reason.
    archive = await client.post(f"{ADMIN_BASE}/{org_id}/archive", headers=auth(root_token))
    assert archive.status_code == 200

    blocked_login = await client.post(
        "/api/v1/auth/login", json={"email": "susp.owner@example.com", "password": "correct-horse-battery"}
    )
    assert blocked_login.status_code == 401
    assert blocked_login.json()["detail"]["code"] == "organization_archived"

    members = await client.get(f"{ORG_BASE}/members", headers=auth(owner_token))
    assert members.status_code == 403
    assert members.json()["detail"]["code"] == "organization_archived"


async def test_non_owner_cannot_reach_organization_endpoints(client, db_session):
    org = await make_organization(db_session)
    analyst = await make_user(
        db_session, email="analyst@example.com", role=UserRole.soc_analyst, organization_id=org.id
    )
    token = await login(client, analyst.email)

    resp = await client.get(f"{ORG_BASE}/members", headers=auth(token))
    assert resp.status_code == 403
