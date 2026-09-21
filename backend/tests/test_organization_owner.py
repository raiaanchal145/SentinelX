"""
Organization owner (organization_admin) endpoints -- app/routers/organization.py.
Always scoped to the caller's own organization; every endpoint here
except the overview requires the organization to be active.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import (
    ActorType,
    AuditLog,
    Invitation,
    OrganizationModule,
    OrganizationRoleAccess,
    OrganizationStatus,
    SocMode,
    Team,
    UserAccessOverride,
    UserRole,
)
from tests.helpers import auth, login, make_admin, make_organization, make_user

ORG_BASE = "/api/v1/organization"


async def _owner_token(db_session, client, *, org=None, email="owner@example.com"):
    if org is None:
        org = await make_organization(db_session)
    owner = await make_admin(db_session, email=email, organization_id=org.id)
    token = await login(client, email)
    return org, owner, token


async def test_overview_returns_full_detail_for_active_organization(client, db_session):
    """Organizations are born active (invite-only, docs/DECISIONS.md),
    so the owner overview always carries the full payload -- the old
    pending "message only" shape died with self-signup."""
    org, _owner, token = await _owner_token(db_session, client)

    resp = await client.get(ORG_BASE, headers=auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert "recent_activity" in body
    assert "members" in body


async def test_non_owner_cannot_reach_organization_endpoints(client, db_session):
    org = await make_organization(db_session)
    analyst = await make_user(db_session, email="analyst@example.com", role=UserRole.soc_analyst, organization_id=org.id)
    token = await login(client, analyst.email)

    resp = await client.get(f"{ORG_BASE}/members", headers=auth(token))
    assert resp.status_code == 403


async def test_suspended_archived_block_member_endpoints_but_not_overview_or_me(client, db_session):
    org, _owner, token = await _owner_token(db_session, client)

    for status, code in (
        (OrganizationStatus.suspended, "organization_suspended"),
        (OrganizationStatus.archived, "organization_archived"),
    ):
        org.status = status
        await db_session.commit()

        blocked = await client.get(f"{ORG_BASE}/members", headers=auth(token))
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == code

        overview = await client.get(ORG_BASE, headers=auth(token))
        assert overview.status_code == 200

        me = await client.get("/api/v1/auth/me", headers=auth(token))
        assert me.status_code == 200


async def test_patch_member_role_requires_in_house_soc_mode_for_soc_analyst(client, db_session):
    org, _owner, token = await _owner_token(db_session, client, org=await make_organization(db_session, soc_mode=SocMode.managed))
    dev = await make_user(db_session, email="dev@example.com", role=UserRole.it_developer, organization_id=org.id)

    rejected = await client.patch(f"{ORG_BASE}/members/{dev.id}", json={"role": "soc_analyst"}, headers=auth(token))
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "soc_analyst_requires_in_house"

    org.soc_mode = SocMode.in_house
    await db_session.commit()

    ok = await client.patch(f"{ORG_BASE}/members/{dev.id}", json={"role": "soc_analyst"}, headers=auth(token))
    assert ok.status_code == 200
    assert ok.json()["role"] == "soc_analyst"


async def test_patch_member_invalid_team_is_404(client, db_session):
    org, _owner, token = await _owner_token(db_session, client)
    dev = await make_user(db_session, email="dev@example.com", role=UserRole.it_developer, organization_id=org.id)

    resp = await client.patch(
        f"{ORG_BASE}/members/{dev.id}",
        json={"team_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth(token),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "team_not_found"


async def test_remove_member_hard_deletes_when_unreferenced(client, db_session):
    org, _owner, token = await _owner_token(db_session, client)
    dev = await make_user(db_session, email="dev@example.com", role=UserRole.it_developer, organization_id=org.id)

    resp = await client.delete(f"{ORG_BASE}/members/{dev.id}", headers=auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is True
    assert body["deactivated"] is False


async def test_remove_member_soft_deactivates_when_referenced_by_audit_history(client, db_session):
    org, _owner, token = await _owner_token(db_session, client)
    dev = await make_user(db_session, email="dev@example.com", role=UserRole.it_developer, organization_id=org.id)

    db_session.add(
        AuditLog(actor_type=ActorType.user, actor_id=dev.id, action="test.action", organization_id=org.id)
    )
    await db_session.commit()

    resp = await client.delete(f"{ORG_BASE}/members/{dev.id}", headers=auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is False
    assert body["deactivated"] is True


async def test_invite_member_rejects_duplicate_pending_and_registered_email(client, db_session):
    org, _owner, token = await _owner_token(db_session, client, org=await make_organization(db_session, soc_mode=SocMode.in_house))

    first = await client.post(
        f"{ORG_BASE}/invitations", json={"email": "new.dev@example.com", "role": "it_developer"}, headers=auth(token)
    )
    assert first.status_code == 201

    duplicate_pending = await client.post(
        f"{ORG_BASE}/invitations", json={"email": "new.dev@example.com", "role": "it_developer"}, headers=auth(token)
    )
    assert duplicate_pending.status_code == 409
    assert duplicate_pending.json()["detail"]["code"] == "invitation_already_pending"

    existing = await make_user(db_session, email="existing@example.com", organization_id=org.id)
    already_registered = await client.post(
        f"{ORG_BASE}/invitations", json={"email": existing.email, "role": "it_developer"}, headers=auth(token)
    )
    assert already_registered.status_code == 409
    assert already_registered.json()["detail"]["code"] == "email_already_registered"


async def test_invite_member_enforces_soc_mode_and_member_limit(client, db_session):
    org, _owner, token = await _owner_token(
        db_session, client, org=await make_organization(db_session, soc_mode=SocMode.managed, max_members=1)
    )

    soc_gated = await client.post(
        f"{ORG_BASE}/invitations", json={"email": "analyst@example.com", "role": "soc_analyst"}, headers=auth(token)
    )
    assert soc_gated.status_code == 422
    assert soc_gated.json()["detail"]["code"] == "soc_analyst_requires_in_house"

    # max_members=1 and the owner itself already counts as a member.
    over_limit = await client.post(
        f"{ORG_BASE}/invitations", json={"email": "dev@example.com", "role": "it_developer"}, headers=auth(token)
    )
    assert over_limit.status_code == 409
    assert over_limit.json()["detail"]["code"] == "member_limit_reached"


async def test_invite_member_rate_limit(client, db_session):
    org, _owner, token = await _owner_token(db_session, client)

    for i in range(20):
        db_session.add(
            Invitation(
                organization_id=org.id, email=f"seed{i}@example.com", kind="member", role=UserRole.it_developer,
                token_hash=f"hash{i}" * 8, status="pending", expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
        )
    await db_session.commit()

    resp = await client.post(
        f"{ORG_BASE}/invitations", json={"email": "one.more@example.com", "role": "it_developer"}, headers=auth(token)
    )
    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "invitation_rate_limited"


async def test_list_resend_and_revoke_invitations(client, db_session):
    org, _owner, token = await _owner_token(db_session, client)

    create_resp = await client.post(
        f"{ORG_BASE}/invitations", json={"email": "dev@example.com", "role": "it_developer"}, headers=auth(token)
    )
    invitation_id = create_resp.json()["id"]

    listed = await client.get(f"{ORG_BASE}/invitations", headers=auth(token))
    assert listed.status_code == 200
    assert len(listed.json()["invitations"]) == 1

    before_row = (
        await db_session.execute(select(Invitation).where(Invitation.id == invitation_id))
    ).scalar_one()
    old_token_hash = before_row.token_hash

    resend = await client.post(f"{ORG_BASE}/invitations/{invitation_id}/resend", headers=auth(token))
    assert resend.status_code == 200
    assert resend.json()["expires_at"] is not None

    await db_session.refresh(before_row)
    # Resend rotates the token on the SAME row rather than creating a new
    # one -- the old raw token must no longer hash to what's stored.
    assert before_row.token_hash != old_token_hash

    revoke = await client.delete(f"{ORG_BASE}/invitations/{invitation_id}", headers=auth(token))
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "revoked"

    revoke_again = await client.delete(f"{ORG_BASE}/invitations/{invitation_id}", headers=auth(token))
    assert revoke_again.status_code == 409
    assert revoke_again.json()["detail"]["code"] == "invitation_not_pending"


async def test_teams_crud_and_set_members(client, db_session):
    org, _owner, token = await _owner_token(db_session, client)
    dev = await make_user(db_session, email="dev@example.com", role=UserRole.it_developer, organization_id=org.id)

    create = await client.post(f"{ORG_BASE}/teams", json={"name": "Platform"}, headers=auth(token))
    assert create.status_code == 201
    team_id = create.json()["id"]

    listed = await client.get(f"{ORG_BASE}/teams", headers=auth(token))
    assert listed.json()["teams"][0]["member_count"] == 0

    set_members = await client.put(
        f"{ORG_BASE}/teams/{team_id}/members", json={"user_ids": [str(dev.id)]}, headers=auth(token)
    )
    assert set_members.status_code == 200

    listed_again = await client.get(f"{ORG_BASE}/teams", headers=auth(token))
    assert listed_again.json()["teams"][0]["member_count"] == 1

    patch = await client.patch(f"{ORG_BASE}/teams/{team_id}", json={"name": "Platform Eng"}, headers=auth(token))
    assert patch.status_code == 200
    assert patch.json()["name"] == "Platform Eng"

    delete = await client.delete(f"{ORG_BASE}/teams/{team_id}", headers=auth(token))
    assert delete.status_code == 200

    remaining_teams = (await db_session.execute(select(Team).where(Team.organization_id == org.id))).scalars().all()
    assert remaining_teams == []


async def test_access_matrix_get_reflects_defaults_and_gating(client, db_session):
    org, _owner, token = await _owner_token(db_session, client, org=await make_organization(db_session, soc_mode=SocMode.managed))

    resp = await client.get(f"{ORG_BASE}/access", headers=auth(token))
    assert resp.status_code == 200
    matrix = resp.json()["matrix"]

    assert matrix["it_developer"]["assets"]["role_has_default"] is True
    assert matrix["it_developer"]["assets"]["effective"] is True
    assert matrix["it_developer"]["soc"]["role_has_default"] is False
    assert matrix["it_developer"]["soc"]["effective"] is False

    assert matrix["soc_analyst"]["soc"]["role_has_default"] is True
    assert matrix["soc_analyst"]["soc"]["soc_gated"] is True
    assert matrix["soc_analyst"]["soc"]["effective"] is False


async def test_access_matrix_put_rejects_non_default_and_platform_disabled(client, db_session):
    org, _owner, token = await _owner_token(db_session, client)

    non_default = await client.put(
        f"{ORG_BASE}/access",
        json={"updates": [{"role": "it_developer", "module_key": "soc", "enabled": False}]},
        headers=auth(token),
    )
    assert non_default.status_code == 422
    assert non_default.json()["detail"]["code"] == "module_not_default_for_role"

    row = (
        await db_session.execute(
            select(OrganizationModule).where(
                OrganizationModule.organization_id == org.id, OrganizationModule.module_key == "it_tickets"
            )
        )
    ).scalar_one()
    row.enabled = False
    await db_session.commit()

    disabled_by_platform = await client.put(
        f"{ORG_BASE}/access",
        json={"updates": [{"role": "it_developer", "module_key": "it_tickets", "enabled": False}]},
        headers=auth(token),
    )
    assert disabled_by_platform.status_code == 422
    assert disabled_by_platform.json()["detail"]["code"] == "module_disabled_by_platform"

    valid = await client.put(
        f"{ORG_BASE}/access",
        json={"updates": [{"role": "it_developer", "module_key": "assets", "enabled": False}]},
        headers=auth(token),
    )
    assert valid.status_code == 200

    row = (
        await db_session.execute(
            select(OrganizationRoleAccess).where(
                OrganizationRoleAccess.organization_id == org.id,
                OrganizationRoleAccess.role == UserRole.it_developer,
                OrganizationRoleAccess.module_key == "assets",
            )
        )
    ).scalar_one()
    assert row.enabled is False


async def test_get_member_access_reflects_role_defaults_and_own_overrides(client, db_session):
    org, _owner, token = await _owner_token(db_session, client)
    dev = await make_user(db_session, email="dev@example.com", role=UserRole.it_developer, organization_id=org.id)

    before = await client.get(f"{ORG_BASE}/members/{dev.id}/access", headers=auth(token))
    assert before.status_code == 200
    body = before.json()
    assert body["role"] == "it_developer"
    assert body["modules"]["assets"]["role_has_default"] is True
    assert body["modules"]["assets"]["denied"] is False
    assert body["modules"]["assets"]["effective"] is True
    assert body["modules"]["soc"]["role_has_default"] is False
    assert body["modules"]["soc"]["effective"] is False

    await client.put(f"{ORG_BASE}/members/{dev.id}/access", json={"denied_modules": ["assets"]}, headers=auth(token))

    after = await client.get(f"{ORG_BASE}/members/{dev.id}/access", headers=auth(token))
    assert after.status_code == 200
    assert after.json()["modules"]["assets"]["denied"] is True
    assert after.json()["modules"]["assets"]["effective"] is False


async def test_get_member_access_unknown_member_is_404(client, db_session):
    _org, _owner, token = await _owner_token(db_session, client)
    resp = await client.get(f"{ORG_BASE}/members/00000000-0000-0000-0000-000000000000/access", headers=auth(token))
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "member_not_found"


async def test_member_access_override_put_sets_and_clears_denied_modules(client, db_session):
    org, _owner, token = await _owner_token(db_session, client)
    dev = await make_user(db_session, email="dev@example.com", role=UserRole.it_developer, organization_id=org.id)

    deny = await client.put(
        f"{ORG_BASE}/members/{dev.id}/access", json={"denied_modules": ["assets"]}, headers=auth(token)
    )
    assert deny.status_code == 200
    assert deny.json()["denied_modules"] == ["assets"]

    rows = (await db_session.execute(select(UserAccessOverride).where(UserAccessOverride.user_id == dev.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].allowed is False

    clear = await client.put(f"{ORG_BASE}/members/{dev.id}/access", json={"denied_modules": []}, headers=auth(token))
    assert clear.status_code == 200
    assert clear.json()["denied_modules"] == []

    rows_after = (await db_session.execute(select(UserAccessOverride).where(UserAccessOverride.user_id == dev.id))).scalars().all()
    assert rows_after == []
