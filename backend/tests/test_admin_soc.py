"""
Platform SOC team management -- app/routers/admin_soc.py. super_admin-only.
"""

from sqlalchemy import select

from app.models import AdminLevel, Invitation, OrganizationStatus, SocMode, SocOrganizationAssignment
from tests.helpers import auth, login, make_admin, make_organization

SOC_BASE = "/api/v1/admin/soc-analysts"


async def _super_admin_token(client, db_session, email="root@example.com"):
    await make_admin(db_session, email=email, admin_level=AdminLevel.super_admin)
    return await login(client, email)


async def test_non_super_admin_cannot_reach_admin_soc(client, db_session):
    org = await make_organization(db_session)
    owner = await make_admin(db_session, email="owner@example.com", organization_id=org.id)
    owner_token = await login(client, owner.email)
    assert (await client.get(SOC_BASE, headers=auth(owner_token))).status_code == 403


async def test_invite_soc_analyst_creates_pending_invitation(client, db_session):
    token = await _super_admin_token(client, db_session)
    resp = await client.post(SOC_BASE, json={"email": "soc.new@example.com"}, headers=auth(token))
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == "soc.new@example.com"

    invitation = (
        await db_session.execute(select(Invitation).where(Invitation.email == "soc.new@example.com"))
    ).scalar_one()
    assert invitation.kind == "platform_soc"
    assert invitation.organization_id is None
    assert invitation.status == "pending"


async def test_invite_soc_analyst_rejects_already_registered_email(client, db_session):
    token = await _super_admin_token(client, db_session)
    org = await make_organization(db_session)
    await make_admin(db_session, email="taken@example.com", organization_id=org.id)

    resp = await client.post(SOC_BASE, json={"email": "taken@example.com"}, headers=auth(token))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "email_already_registered"


async def test_list_soc_analysts_includes_assigned_organizations(client, db_session):
    token = await _super_admin_token(client, db_session)
    soc = await make_admin(db_session, email="soc@example.com", admin_level=AdminLevel.platform_soc_analyst)
    org = await make_organization(db_session, name="Managed Co", soc_mode=SocMode.managed)
    db_session.add(SocOrganizationAssignment(admin_id=soc.id, organization_id=org.id))
    await db_session.commit()

    resp = await client.get(SOC_BASE, headers=auth(token))
    assert resp.status_code == 200
    body = resp.json()["soc_analysts"]
    assert len(body) == 1
    assert body[0]["email"] == "soc@example.com"
    assert [o["name"] for o in body[0]["assigned_organizations"]] == ["Managed Co"]


async def test_my_assigned_organizations_returns_own_assignments(client, db_session):
    soc = await make_admin(db_session, email="soc@example.com", admin_level=AdminLevel.platform_soc_analyst)
    org = await make_organization(db_session, name="Managed Co", soc_mode=SocMode.managed)
    db_session.add(SocOrganizationAssignment(admin_id=soc.id, organization_id=org.id))
    await db_session.commit()
    token = await login(client, soc.email)

    resp = await client.get(f"{SOC_BASE}/me", headers=auth(token))
    assert resp.status_code == 200
    assert [o["name"] for o in resp.json()["assigned_organizations"]] == ["Managed Co"]


async def test_my_assigned_organizations_rejects_non_platform_soc(client, db_session):
    token = await _super_admin_token(client, db_session)
    resp = await client.get(f"{SOC_BASE}/me", headers=auth(token))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "platform_soc_required"


async def test_patch_soc_analyst_toggles_is_active(client, db_session):
    token = await _super_admin_token(client, db_session)
    soc = await make_admin(db_session, email="soc@example.com", admin_level=AdminLevel.platform_soc_analyst)

    resp = await client.patch(f"{SOC_BASE}/{soc.id}", json={"is_active": False}, headers=auth(token))
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    not_found = await client.patch(
        f"{SOC_BASE}/00000000-0000-0000-0000-000000000000", json={"is_active": True}, headers=auth(token)
    )
    assert not_found.status_code == 404
    assert not_found.json()["detail"]["code"] == "soc_analyst_not_found"


async def test_update_soc_analyst_organizations_validates_and_replaces(client, db_session):
    token = await _super_admin_token(client, db_session)
    soc = await make_admin(db_session, email="soc@example.com", admin_level=AdminLevel.platform_soc_analyst)

    managed_active = await make_organization(db_session, name="Managed Active", soc_mode=SocMode.managed, status=OrganizationStatus.active)
    in_house = await make_organization(db_session, name="In House", soc_mode=SocMode.in_house)
    archived_managed = await make_organization(db_session, name="Archived Managed", soc_mode=SocMode.managed, status=OrganizationStatus.archived)

    invalid = await client.put(
        f"{SOC_BASE}/{soc.id}/organizations",
        json={"organization_ids": [str(managed_active.id), str(in_house.id)]},
        headers=auth(token),
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "invalid_organization_assignment"

    invalid_archived = await client.put(
        f"{SOC_BASE}/{soc.id}/organizations",
        json={"organization_ids": [str(archived_managed.id)]},
        headers=auth(token),
    )
    assert invalid_archived.status_code == 400

    another_managed_active = await make_organization(db_session, name="Second Managed Active", soc_mode=SocMode.managed)

    first = await client.put(
        f"{SOC_BASE}/{soc.id}/organizations",
        json={"organization_ids": [str(managed_active.id), str(another_managed_active.id)]},
        headers=auth(token),
    )
    assert first.status_code == 200
    assert {o["name"] for o in first.json()["assigned_organizations"]} == {"Managed Active", "Second Managed Active"}

    replaced = await client.put(
        f"{SOC_BASE}/{soc.id}/organizations",
        json={"organization_ids": [str(another_managed_active.id)]},
        headers=auth(token),
    )
    assert replaced.status_code == 200
    assert {o["name"] for o in replaced.json()["assigned_organizations"]} == {"Second Managed Active"}

    remaining = (
        await db_session.execute(select(SocOrganizationAssignment).where(SocOrganizationAssignment.admin_id == soc.id))
    ).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].organization_id == another_managed_active.id
