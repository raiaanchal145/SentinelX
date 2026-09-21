"""
Platform admin endpoints -- app/routers/admin_organizations.py.
Everything here is super_admin-only; a couple of tests confirm an
organization owner or a platform_soc_analyst can't reach any of it.
"""

from sqlalchemy import select

from app.models import AdminLevel, Invitation, OrganizationModule, OrganizationStatus, SocMode, UserRole
from tests.helpers import auth, login, make_admin, make_organization, make_user

ADMIN_BASE = "/api/v1/admin/organizations"


async def _super_admin_token(client, db_session, email="root@example.com"):
    await make_admin(db_session, email=email, admin_level=AdminLevel.super_admin)
    return await login(client, email)


async def test_non_super_admin_cannot_reach_admin_organizations(client, db_session):
    org = await make_organization(db_session)
    owner = await make_admin(db_session, email="owner@example.com", organization_id=org.id)
    soc = await make_admin(db_session, email="soc@example.com", admin_level=AdminLevel.platform_soc_analyst)

    owner_token = await login(client, owner.email)
    soc_token = await login(client, soc.email)

    assert (await client.get(ADMIN_BASE, headers=auth(owner_token))).status_code == 403
    assert (await client.get(ADMIN_BASE, headers=auth(soc_token))).status_code == 403


async def test_create_organization_seeds_modules_and_sends_owner_invitation(client, db_session):
    token = await _super_admin_token(client, db_session)

    resp = await client.post(
        ADMIN_BASE,
        json={"name": "Aurora Health", "owner_email": "new.owner@example.com", "soc_mode": "managed"},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Aurora Health"
    assert body["status"] == "active"
    assert body["soc_mode"] == "managed"
    assert body["owner"] is None  # invited, not yet accepted

    org_id = body["id"]
    modules = (
        await db_session.execute(select(OrganizationModule).where(OrganizationModule.organization_id == org_id))
    ).scalars().all()
    assert len(modules) == 9
    assert all(m.enabled for m in modules)

    invitation = (
        await db_session.execute(select(Invitation).where(Invitation.email == "new.owner@example.com"))
    ).scalar_one()
    assert invitation.kind == "owner"
    assert invitation.status == "pending"
    assert str(invitation.organization_id) == org_id


async def test_create_organization_rejects_already_registered_owner_email(client, db_session):
    token = await _super_admin_token(client, db_session)
    org = await make_organization(db_session)
    await make_admin(db_session, email="taken@example.com", organization_id=org.id)

    resp = await client.post(
        ADMIN_BASE,
        json={"name": "New Org", "owner_email": "taken@example.com", "soc_mode": "managed"},
        headers=auth(token),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "email_already_registered"


async def test_create_organization_rejects_invalid_soc_mode(client, db_session):
    token = await _super_admin_token(client, db_session)
    resp = await client.post(
        ADMIN_BASE,
        json={"name": "New Org", "owner_email": "owner2@example.com", "soc_mode": "not-a-mode"},
        headers=auth(token),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_soc_mode"


async def test_list_organizations_filters_and_search(client, db_session):
    token = await _super_admin_token(client, db_session)
    org_a = await make_organization(db_session, name="Aurora Health", status=OrganizationStatus.active, soc_mode=SocMode.managed)
    await make_organization(db_session, name="Blackridge Logistics", status=OrganizationStatus.archived, soc_mode=SocMode.in_house)
    await make_admin(db_session, email="owner.a@example.com", organization_id=org_a.id)

    all_orgs = (await client.get(ADMIN_BASE, headers=auth(token))).json()
    assert all_orgs["total"] == 2

    by_status = (await client.get(ADMIN_BASE, params={"status": "archived"}, headers=auth(token))).json()
    assert by_status["total"] == 1
    assert by_status["organizations"][0]["name"] == "Blackridge Logistics"

    by_soc_mode = (await client.get(ADMIN_BASE, params={"soc_mode": "managed"}, headers=auth(token))).json()
    assert by_soc_mode["total"] == 1
    assert by_soc_mode["organizations"][0]["name"] == "Aurora Health"

    by_query = (await client.get(ADMIN_BASE, params={"q": "aurora"}, headers=auth(token))).json()
    assert by_query["total"] == 1

    by_owner_email = (await client.get(ADMIN_BASE, params={"q": "owner.a@example.com"}, headers=auth(token))).json()
    assert by_owner_email["total"] == 1
    assert by_owner_email["organizations"][0]["name"] == "Aurora Health"


async def test_get_organization_detail_not_found(client, db_session):
    token = await _super_admin_token(client, db_session)
    resp = await client.get(f"{ADMIN_BASE}/00000000-0000-0000-0000-000000000000", headers=auth(token))
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "organization_not_found"


async def test_patch_organization_updates_fields(client, db_session):
    token = await _super_admin_token(client, db_session)
    org = await make_organization(db_session, name="Old Name")

    resp = await client.patch(
        f"{ADMIN_BASE}/{org.id}",
        json={"name": "New Name", "max_members": 25},
        headers=auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New Name"
    assert body["max_members"] == 25


async def test_approve_endpoint_was_removed_with_self_signup(client, db_session):
    """Invite-only: organizations are born active, so the approve
    endpoint is gone entirely (docs/DECISIONS.md)."""
    token = await _super_admin_token(client, db_session)
    org = await make_organization(db_session, status=OrganizationStatus.active)

    resp = await client.post(f"{ADMIN_BASE}/{org.id}/approve", headers=auth(token))
    assert resp.status_code == 404


async def test_suspend_requires_a_reason_and_sets_fields(client, db_session):
    token = await _super_admin_token(client, db_session)
    org = await make_organization(db_session, status=OrganizationStatus.active)

    empty_reason = await client.post(f"{ADMIN_BASE}/{org.id}/suspend", json={"reason": "   "}, headers=auth(token))
    assert empty_reason.status_code == 400
    assert empty_reason.json()["detail"]["code"] == "suspension_reason_required"

    resp = await client.post(f"{ADMIN_BASE}/{org.id}/suspend", json={"reason": "Non-payment"}, headers=auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"


async def test_reactivate_only_from_suspended(client, db_session):
    token = await _super_admin_token(client, db_session)
    org = await make_organization(db_session, status=OrganizationStatus.active)

    resp = await client.post(f"{ADMIN_BASE}/{org.id}/reactivate", headers=auth(token))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "invalid_status_transition"

    await client.post(f"{ADMIN_BASE}/{org.id}/suspend", json={"reason": "test"}, headers=auth(token))
    ok = await client.post(f"{ADMIN_BASE}/{org.id}/reactivate", headers=auth(token))
    assert ok.status_code == 200
    assert ok.json()["status"] == "active"


async def test_archive_allowed_from_active_and_suspended_but_not_twice(client, db_session):
    token = await _super_admin_token(client, db_session)
    for status in (OrganizationStatus.active, OrganizationStatus.suspended):
        org = await make_organization(db_session, name=f"Org {status.value}", status=status)
        resp = await client.post(f"{ADMIN_BASE}/{org.id}/archive", headers=auth(token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "archived"

        again = await client.post(f"{ADMIN_BASE}/{org.id}/archive", headers=auth(token))
        assert again.status_code == 409


async def test_update_modules_requires_the_complete_key_set(client, db_session):
    token = await _super_admin_token(client, db_session)
    org = await make_organization(db_session)

    missing = await client.put(f"{ADMIN_BASE}/{org.id}/modules", json={"modules": {"assets": True}}, headers=auth(token))
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "incomplete_module_list"

    full = {
        "assets": True, "soc": True, "incidents": True, "it_tickets": True, "approvals": True,
        "ai_agents": True, "device_agents": True, "reports": True, "audit_logs": True,
    }
    unknown_payload = dict(full)
    unknown_payload.pop("assets")
    unknown_payload["not_a_module"] = True
    unknown = await client.put(f"{ADMIN_BASE}/{org.id}/modules", json={"modules": unknown_payload}, headers=auth(token))
    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "unknown_module_key"

    full["it_tickets"] = False
    resp = await client.put(f"{ADMIN_BASE}/{org.id}/modules", json={"modules": full}, headers=auth(token))
    assert resp.status_code == 200
    assert resp.json()["changed"] == {"it_tickets": False}

    row = (
        await db_session.execute(
            select(OrganizationModule).where(
                OrganizationModule.organization_id == org.id, OrganizationModule.module_key == "it_tickets"
            )
        )
    ).scalar_one()
    assert row.enabled is False


async def test_update_soc_mode_warns_and_messages(client, db_session):
    token = await _super_admin_token(client, db_session)

    org_with_analyst = await make_organization(db_session, soc_mode=SocMode.in_house)
    await make_user(db_session, email="analyst@example.com", role=UserRole.soc_analyst, organization_id=org_with_analyst.id)

    to_managed = await client.put(
        f"{ADMIN_BASE}/{org_with_analyst.id}/soc-mode", json={"soc_mode": "managed"}, headers=auth(token)
    )
    assert to_managed.status_code == 200
    body = to_managed.json()
    assert body["soc_analyst_count"] == 1
    assert "message" in body

    org_without_analyst = await make_organization(db_session, soc_mode=SocMode.managed)
    to_in_house = await client.put(
        f"{ADMIN_BASE}/{org_without_analyst.id}/soc-mode", json={"soc_mode": "in_house"}, headers=auth(token)
    )
    assert to_in_house.status_code == 200
    assert "warning" in to_in_house.json()


async def test_deactivate_member_protects_the_last_active_owner(client, db_session):
    token = await _super_admin_token(client, db_session)
    org = await make_organization(db_session)
    only_owner = await make_admin(db_session, email="only.owner@example.com", organization_id=org.id)

    resp = await client.post(
        f"{ADMIN_BASE}/{org.id}/members/admin/{only_owner.id}/deactivate", headers=auth(token)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "last_owner_protected"

    second_owner = await make_admin(db_session, email="second.owner@example.com", organization_id=org.id)
    first_deactivate = await client.post(
        f"{ADMIN_BASE}/{org.id}/members/admin/{only_owner.id}/deactivate", headers=auth(token)
    )
    assert first_deactivate.status_code == 200
    assert first_deactivate.json()["is_active"] is False

    last_one_left = await client.post(
        f"{ADMIN_BASE}/{org.id}/members/admin/{second_owner.id}/deactivate", headers=auth(token)
    )
    assert last_one_left.status_code == 409


async def test_deactivate_member_rejects_unknown_account_type_and_missing_member(client, db_session):
    token = await _super_admin_token(client, db_session)
    org = await make_organization(db_session)

    bad_type = await client.post(
        f"{ADMIN_BASE}/{org.id}/members/robot/00000000-0000-0000-0000-000000000000/deactivate", headers=auth(token)
    )
    assert bad_type.status_code == 400
    assert bad_type.json()["detail"]["code"] == "invalid_account_type"

    not_found = await client.post(
        f"{ADMIN_BASE}/{org.id}/members/user/00000000-0000-0000-0000-000000000000/deactivate", headers=auth(token)
    )
    assert not_found.status_code == 404


async def test_organization_activity_is_paginated(client, db_session):
    token = await _super_admin_token(client, db_session)
    org = await make_organization(db_session, status=OrganizationStatus.active)

    for reason in ("first", "second", "third"):
        await client.post(f"{ADMIN_BASE}/{org.id}/suspend", json={"reason": reason}, headers=auth(token))
        await client.post(f"{ADMIN_BASE}/{org.id}/reactivate", headers=auth(token))

    page1 = await client.get(f"{ADMIN_BASE}/{org.id}/activity", params={"page": 1, "page_size": 2}, headers=auth(token))
    assert page1.status_code == 200
    body = page1.json()
    assert body["total"] == 6
    assert len(body["entries"]) == 2
