"""
End-to-end coverage of app/routers/assets.py and the read-only nested
GET /admin/organizations/{id}/assets view in admin_organizations.py.

Covers: CRUD, field validation, duplicate-hostname enforcement, tag
replacement, retire (soft-delete) rules, the full role matrix (write
roles, read-only roles, it_developer's row-level own/team scoping),
cross-organization isolation (including by guessing another org's
asset id, which must 404 rather than 403 so existence isn't leaked),
platform_soc_analyst's assigned-vs-unassigned organization visibility,
super_admin's separate admin-side read path, and that every mutating
action writes the audit_logs action string it's supposed to.
"""

from sqlalchemy import select

from app.models import AdminLevel, AuditLog, OrganizationStatus, SocMode, SocOrganizationAssignment, UserRole
from tests.helpers import auth, login, make_admin, make_organization, make_team, make_user

ASSETS_BASE = "/api/v1/assets"
ADMIN_BASE = "/api/v1/admin/organizations"


async def _owner(client, db_session, org, email="owner@example.com"):
    admin = await make_admin(db_session, email=email, organization_id=org.id)
    token = await login(client, email)
    return admin, token


async def _create(client, token, **overrides):
    payload = {"name": "Web Server 1", "asset_type": "server"}
    payload.update(overrides)
    return await client.post(ASSETS_BASE, json=payload, headers=auth(token))


# ---------------------------------------------------------------- CRUD ----

async def test_create_asset_minimal(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)

    resp = await _create(client, token)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Web Server 1"
    assert body["asset_type"] == "server"
    assert body["criticality"] == "medium"
    assert body["status"] == "active"
    assert body["hostname"] is None
    assert body["tags"] == []
    assert body["can_edit"] is True


async def test_create_asset_full(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    team = await make_team(db_session, organization_id=org.id, name="Platform")
    dev = await make_user(
        db_session, email="dev@example.com", name="dev", role=UserRole.it_developer, organization_id=org.id
    )

    resp = await _create(
        client, token,
        name="db-primary", hostname="db-primary.internal", ip_address="10.0.0.5",
        operating_system="Ubuntu 22.04", environment="production", criticality="critical",
        owner_user_id=str(dev.id), team_id=str(team.id), description="Primary database",
        tags=["db", "prod", "db"],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["hostname"] == "db-primary.internal"
    assert body["ip_address"] == "10.0.0.5"
    assert body["criticality"] == "critical"
    assert body["owner_user_id"] == str(dev.id)
    assert body["owner_name"] == "dev"
    assert body["team_id"] == str(team.id)
    assert body["team_name"] == "Platform"
    assert body["tags"] == ["db", "prod"]


async def test_get_asset(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    asset_id = (await _create(client, token)).json()["id"]

    resp = await client.get(f"{ASSETS_BASE}/{asset_id}", headers=auth(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == asset_id


async def test_list_assets_search_and_filter(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    await _create(client, token, name="Alpha Web", hostname="alpha-web", asset_type="server", criticality="high")
    await _create(client, token, name="Beta DB", hostname="beta-db", asset_type="database", criticality="low")

    all_resp = await client.get(ASSETS_BASE, headers=auth(token))
    assert all_resp.json()["total"] == 2

    q_resp = await client.get(ASSETS_BASE, params={"q": "alpha"}, headers=auth(token))
    assert [a["name"] for a in q_resp.json()["assets"]] == ["Alpha Web"]

    type_resp = await client.get(ASSETS_BASE, params={"asset_type": "database"}, headers=auth(token))
    assert [a["name"] for a in type_resp.json()["assets"]] == ["Beta DB"]

    crit_resp = await client.get(ASSETS_BASE, params={"criticality": "high"}, headers=auth(token))
    assert [a["name"] for a in crit_resp.json()["assets"]] == ["Alpha Web"]


async def test_patch_asset_updates_fields(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    asset_id = (await _create(client, token)).json()["id"]

    resp = await client.patch(
        f"{ASSETS_BASE}/{asset_id}",
        json={"criticality": "critical", "description": "Now critical"},
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["criticality"] == "critical"
    assert body["description"] == "Now critical"


async def test_patch_asset_rejects_blank_name(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    asset_id = (await _create(client, token)).json()["id"]

    resp = await client.patch(f"{ASSETS_BASE}/{asset_id}", json={"name": "   "}, headers=auth(token))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "name_required"


async def test_retire_asset_soft_deletes_and_rejects_double_retire(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    asset_id = (await _create(client, token)).json()["id"]

    resp = await client.delete(f"{ASSETS_BASE}/{asset_id}", headers=auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "retired"

    again = await client.delete(f"{ASSETS_BASE}/{asset_id}", headers=auth(token))
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "asset_already_retired"


async def test_set_asset_tags_replaces_and_dedupes(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    asset_id = (await _create(client, token, tags=["a", "b"])).json()["id"]

    resp = await client.put(
        f"{ASSETS_BASE}/{asset_id}/tags", json={"tags": ["c", "c", "d"]}, headers=auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["c", "d"]


async def test_assets_summary_counts_by_type_criticality_status(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    a = (await _create(client, token, asset_type="server", criticality="high")).json()["id"]
    await _create(client, token, asset_type="database", criticality="low")
    await client.delete(f"{ASSETS_BASE}/{a}", headers=auth(token))

    resp = await client.get(f"{ASSETS_BASE}/summary", headers=auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["by_type"] == {"server": 1, "database": 1}
    assert body["by_criticality"] == {"high": 1, "low": 1}
    assert body["by_status"] == {"retired": 1, "active": 1}


async def test_assets_lookup_returns_active_users_and_teams(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    await make_team(db_session, organization_id=org.id, name="Platform")
    await make_user(
        db_session, email="dev@example.com", name="dev", role=UserRole.it_developer, organization_id=org.id
    )
    await make_user(
        db_session, email="gone@example.com", name="gone", role=UserRole.it_developer,
        organization_id=org.id, is_active=False,
    )

    resp = await client.get(f"{ASSETS_BASE}/lookup", headers=auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert [t["name"] for t in body["teams"]] == ["Platform"]
    assert [u["name"] for u in body["users"]] == ["dev"]


# --------------------------------------------------------- validation ----

async def test_create_asset_rejects_invalid_asset_type(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    resp = await _create(client, token, asset_type="spaceship")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_asset_type"


async def test_create_asset_rejects_invalid_criticality(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    resp = await _create(client, token, criticality="urgent")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_criticality"


async def test_create_asset_rejects_invalid_environment(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    resp = await _create(client, token, environment="moon")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_environment"


async def test_create_asset_rejects_invalid_ip_address(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    resp = await _create(client, token, ip_address="999.999.999.999")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_ip_address"


async def test_patch_asset_rejects_invalid_status(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    asset_id = (await _create(client, token)).json()["id"]
    resp = await client.patch(f"{ASSETS_BASE}/{asset_id}", json={"status": "deleted"}, headers=auth(token))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_status"


async def test_create_asset_rejects_unknown_owner_or_team(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)

    bad_owner = await _create(client, token, owner_user_id="00000000-0000-0000-0000-000000000000")
    assert bad_owner.status_code == 404
    assert bad_owner.json()["detail"]["code"] == "owner_not_found"

    bad_team = await _create(client, token, team_id="00000000-0000-0000-0000-000000000000")
    assert bad_team.status_code == 404
    assert bad_team.json()["detail"]["code"] == "team_not_found"


# ------------------------------------------------------ duplicate hostname ----

async def test_duplicate_hostname_rejected_case_insensitively(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    await _create(client, token, hostname="Web-1")

    resp = await _create(client, token, name="Second", hostname="web-1")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "duplicate_hostname"


async def test_same_hostname_allowed_across_organizations(client, db_session):
    org_a = await make_organization(db_session, name="Org A")
    org_b = await make_organization(db_session, name="Org B")
    _admin_a, token_a = await _owner(client, db_session, org_a, email="owner.a@example.com")
    _admin_b, token_b = await _owner(client, db_session, org_b, email="owner.b@example.com")

    assert (await _create(client, token_a, hostname="shared-name")).status_code == 201
    assert (await _create(client, token_b, hostname="shared-name")).status_code == 201


async def test_patch_hostname_to_existing_one_rejected(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)
    await _create(client, token, hostname="taken")
    other_id = (await _create(client, token, name="Other", hostname="free")).json()["id"]

    resp = await client.patch(f"{ASSETS_BASE}/{other_id}", json={"hostname": "taken"}, headers=auth(token))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "duplicate_hostname"


# ------------------------------------------------------------ role matrix ----

async def test_security_manager_has_full_write_access(client, db_session):
    org = await make_organization(db_session)
    manager = await make_user(
        db_session, email="mgr@example.com", role=UserRole.security_manager, organization_id=org.id
    )
    token = await login(client, manager.email)

    resp = await _create(client, token)
    assert resp.status_code == 201, resp.text
    assert resp.json()["can_edit"] is True


async def test_it_developer_can_edit_own_asset_but_not_others(client, db_session):
    org = await make_organization(db_session)
    _admin, owner_token = await _owner(client, db_session, org)
    dev1 = await make_user(db_session, email="dev1@example.com", role=UserRole.it_developer, organization_id=org.id)
    dev2 = await make_user(db_session, email="dev2@example.com", role=UserRole.it_developer, organization_id=org.id)
    dev1_token = await login(client, dev1.email)
    dev2_token = await login(client, dev2.email)

    owned = (await _create(client, owner_token, name="Owned by dev1", owner_user_id=str(dev1.id))).json()["id"]

    as_owner = await client.get(f"{ASSETS_BASE}/{owned}", headers=auth(dev1_token))
    assert as_owner.json()["can_edit"] is True
    ok = await client.patch(f"{ASSETS_BASE}/{owned}", json={"description": "mine"}, headers=auth(dev1_token))
    assert ok.status_code == 200

    as_other = await client.get(f"{ASSETS_BASE}/{owned}", headers=auth(dev2_token))
    assert as_other.json()["can_edit"] is False
    forbidden = await client.patch(f"{ASSETS_BASE}/{owned}", json={"description": "not mine"}, headers=auth(dev2_token))
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "asset_not_editable"

    forbidden_retire = await client.delete(f"{ASSETS_BASE}/{owned}", headers=auth(dev2_token))
    assert forbidden_retire.status_code == 403

    forbidden_tags = await client.put(
        f"{ASSETS_BASE}/{owned}/tags", json={"tags": ["x"]}, headers=auth(dev2_token)
    )
    assert forbidden_tags.status_code == 403


async def test_it_developer_can_edit_team_asset(client, db_session):
    org = await make_organization(db_session)
    _admin, owner_token = await _owner(client, db_session, org)
    team = await make_team(db_session, organization_id=org.id, name="Platform")
    other_team = await make_team(db_session, organization_id=org.id, name="Other")
    teammate = await make_user(
        db_session, email="teammate@example.com", role=UserRole.it_developer,
        organization_id=org.id, team_id=team.id,
    )
    outsider = await make_user(
        db_session, email="outsider@example.com", role=UserRole.it_developer,
        organization_id=org.id, team_id=other_team.id,
    )
    teammate_token = await login(client, teammate.email)
    outsider_token = await login(client, outsider.email)

    asset_id = (await _create(client, owner_token, name="Team asset", team_id=str(team.id))).json()["id"]

    ok = await client.patch(f"{ASSETS_BASE}/{asset_id}", json={"description": "team edit"}, headers=auth(teammate_token))
    assert ok.status_code == 200

    forbidden = await client.patch(
        f"{ASSETS_BASE}/{asset_id}", json={"description": "nope"}, headers=auth(outsider_token)
    )
    assert forbidden.status_code == 403


async def test_it_developer_can_create_asset_despite_no_ownership_yet(client, db_session):
    org = await make_organization(db_session)
    dev = await make_user(db_session, email="dev@example.com", role=UserRole.it_developer, organization_id=org.id)
    token = await login(client, dev.email)

    resp = await _create(client, token)
    assert resp.status_code == 201, resp.text
    assert resp.json()["can_edit"] is True


async def test_soc_analyst_is_read_only(client, db_session):
    org = await make_organization(db_session)
    _admin, owner_token = await _owner(client, db_session, org)
    asset_id = (await _create(client, owner_token)).json()["id"]

    analyst = await make_user(db_session, email="analyst@example.com", role=UserRole.soc_analyst, organization_id=org.id)
    token = await login(client, analyst.email)

    listing = await client.get(ASSETS_BASE, headers=auth(token))
    assert listing.status_code == 200
    assert listing.json()["assets"][0]["can_edit"] is False

    create_resp = await _create(client, token)
    assert create_resp.status_code == 403
    assert create_resp.json()["detail"]["code"] == "module_not_available"

    patch_resp = await client.patch(f"{ASSETS_BASE}/{asset_id}", json={"description": "x"}, headers=auth(token))
    assert patch_resp.status_code == 403


async def test_auditor_is_read_only(client, db_session):
    org = await make_organization(db_session)
    _admin, owner_token = await _owner(client, db_session, org)
    await _create(client, owner_token)

    auditor = await make_user(db_session, email="auditor@example.com", role=UserRole.auditor, organization_id=org.id)
    token = await login(client, auditor.email)

    listing = await client.get(ASSETS_BASE, headers=auth(token))
    assert listing.status_code == 200

    create_resp = await _create(client, token)
    assert create_resp.status_code == 403


# ---------------------------------------------------- cross-org isolation ----

async def test_cannot_list_another_organizations_assets(client, db_session):
    org_a = await make_organization(db_session, name="Org A")
    org_b = await make_organization(db_session, name="Org B")
    _admin_a, token_a = await _owner(client, db_session, org_a, email="owner.a@example.com")
    _admin_b, token_b = await _owner(client, db_session, org_b, email="owner.b@example.com")

    await _create(client, token_a, name="A's asset")
    await _create(client, token_b, name="B's asset")

    resp_a = await client.get(ASSETS_BASE, headers=auth(token_a))
    assert [a["name"] for a in resp_a.json()["assets"]] == ["A's asset"]


async def test_cannot_read_or_write_another_organizations_asset_by_guessing_id(client, db_session):
    org_a = await make_organization(db_session, name="Org A")
    org_b = await make_organization(db_session, name="Org B")
    _admin_a, token_a = await _owner(client, db_session, org_a, email="owner.a@example.com")
    _admin_b, token_b = await _owner(client, db_session, org_b, email="owner.b@example.com")

    b_asset_id = (await _create(client, token_b, name="B's asset")).json()["id"]

    get_resp = await client.get(f"{ASSETS_BASE}/{b_asset_id}", headers=auth(token_a))
    assert get_resp.status_code == 404
    assert get_resp.json()["detail"]["code"] == "asset_not_found"

    patch_resp = await client.patch(f"{ASSETS_BASE}/{b_asset_id}", json={"description": "hijacked"}, headers=auth(token_a))
    assert patch_resp.status_code == 404

    delete_resp = await client.delete(f"{ASSETS_BASE}/{b_asset_id}", headers=auth(token_a))
    assert delete_resp.status_code == 404

    tags_resp = await client.put(f"{ASSETS_BASE}/{b_asset_id}/tags", json={"tags": ["x"]}, headers=auth(token_a))
    assert tags_resp.status_code == 404


# ------------------------------------------------------------ platform SOC ----

async def test_platform_soc_analyst_sees_only_assigned_organizations(client, db_session):
    assigned_org = await make_organization(db_session, name="Assigned Co", soc_mode=SocMode.managed)
    unassigned_org = await make_organization(db_session, name="Unassigned Co", soc_mode=SocMode.managed)
    _admin_assigned, assigned_owner_token = await _owner(client, db_session, assigned_org, email="owner.assigned@example.com")
    _admin_unassigned, _unassigned_owner_token = await _owner(client, db_session, unassigned_org, email="owner.unassigned@example.com")

    await _create(client, assigned_owner_token, name="Visible asset")

    soc = await make_admin(db_session, email="soc@example.com", admin_level=AdminLevel.platform_soc_analyst)
    db_session.add(SocOrganizationAssignment(admin_id=soc.id, organization_id=assigned_org.id))
    await db_session.commit()
    soc_token = await login(client, soc.email)

    no_org_param = await client.get(ASSETS_BASE, headers=auth(soc_token))
    assert no_org_param.status_code == 400
    assert no_org_param.json()["detail"]["code"] == "organization_id_required"

    visible = await client.get(ASSETS_BASE, params={"organization_id": str(assigned_org.id)}, headers=auth(soc_token))
    assert visible.status_code == 200
    assets = visible.json()["assets"]
    assert [a["name"] for a in assets] == ["Visible asset"]
    assert assets[0]["can_edit"] is False

    hidden = await client.get(ASSETS_BASE, params={"organization_id": str(unassigned_org.id)}, headers=auth(soc_token))
    assert hidden.status_code == 404
    assert hidden.json()["detail"]["code"] == "organization_not_found"

    write_attempt = await _create(client, soc_token)
    assert write_attempt.status_code == 403
    assert write_attempt.json()["detail"]["code"] == "platform_admin_not_supported"


# --------------------------------------------------------------- super_admin ----

async def test_super_admin_rejected_from_org_router_uses_admin_endpoint_instead(client, db_session):
    org = await make_organization(db_session)
    _admin, owner_token = await _owner(client, db_session, org)
    await _create(client, owner_token, name="Visible to admin")

    root = await make_admin(db_session, email="root@example.com", admin_level=AdminLevel.super_admin)
    root_token = await login(client, root.email)

    direct = await client.get(ASSETS_BASE, params={"organization_id": str(org.id)}, headers=auth(root_token))
    assert direct.status_code == 403
    assert direct.json()["detail"]["code"] == "platform_admin_not_supported"

    nested = await client.get(f"{ADMIN_BASE}/{org.id}/assets", headers=auth(root_token))
    assert nested.status_code == 200
    body = nested.json()
    assert [a["name"] for a in body["assets"]] == ["Visible to admin"]
    assert body["assets"][0]["can_edit"] is False


async def test_admin_nested_assets_endpoint_requires_super_admin(client, db_session):
    org = await make_organization(db_session)
    _admin, owner_token = await _owner(client, db_session, org)

    resp = await client.get(f"{ADMIN_BASE}/{org.id}/assets", headers=auth(owner_token))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "super_admin_required"


async def test_admin_nested_assets_endpoint_404s_for_unknown_organization(client, db_session):
    root = await make_admin(db_session, email="root@example.com", admin_level=AdminLevel.super_admin)
    root_token = await login(client, root.email)

    resp = await client.get(
        f"{ADMIN_BASE}/00000000-0000-0000-0000-000000000000/assets", headers=auth(root_token)
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "organization_not_found"


# -------------------------------------------------------------------- audit ----

async def test_mutating_actions_write_audit_entries(client, db_session):
    org = await make_organization(db_session)
    _admin, token = await _owner(client, db_session, org)

    asset_id = (await _create(client, token)).json()["id"]
    await client.patch(f"{ASSETS_BASE}/{asset_id}", json={"criticality": "high"}, headers=auth(token))
    await client.patch(f"{ASSETS_BASE}/{asset_id}", json={"status": "retired"}, headers=auth(token))
    await client.put(f"{ASSETS_BASE}/{asset_id}/tags", json={"tags": ["x"]}, headers=auth(token))

    second_id = (await _create(client, token, name="Second", hostname="second-host")).json()["id"]
    await client.delete(f"{ASSETS_BASE}/{second_id}", headers=auth(token))

    actions = (
        await db_session.execute(select(AuditLog.action).where(AuditLog.target_type == "asset"))
    ).scalars().all()

    assert actions.count("asset.create") == 2
    assert actions.count("asset.update") == 2
    assert actions.count("asset.status_change") == 1
    assert actions.count("asset.tags_change") == 1
    assert actions.count("asset.retire") == 1


async def test_organization_pending_blocks_assets_access(client, db_session):
    org = await make_organization(db_session, status=OrganizationStatus.pending)
    admin = await make_admin(db_session, email="owner@example.com", organization_id=org.id)
    token = await login(client, admin.email)

    resp = await client.get(ASSETS_BASE, headers=auth(token))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "organization_pending"
