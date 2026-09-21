"""
Unit tests for the layered effective-access calculation in app/access.py
and for soc_visible_organization_ids()'s assignment matrix -- no HTTP
involved, just seeded rows and direct calls, so these pin down the
narrowing rules precisely: organization_modules AND role defaults AND
organization_role_access AND user_access_overrides, each layer only
ever removing, never granting back, what an earlier layer took away.
"""

from sqlalchemy import select

from app.access import (
    ACCESS_READ,
    ACCESS_WRITE,
    get_effective_access,
    soc_visible_organization_ids,
)
from app.models import (
    AdminLevel,
    OrganizationModule,
    OrganizationRoleAccess,
    SocMode,
    SocOrganizationAssignment,
    UserAccessOverride,
    UserRole,
)
from app.scope import Scope
from tests.helpers import make_admin, make_organization, make_user


async def test_role_default_only_grants_exactly_its_map(db_session):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    dev = await make_user(db_session, email="dev@example.com", role=UserRole.it_developer, organization_id=org.id)

    access = await get_effective_access(db_session, dev, org)
    assert access["modules"] == {"assets": ACCESS_READ, "it_tickets": ACCESS_WRITE}


async def test_org_module_disabled_narrows_role_default(db_session):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    dev = await make_user(db_session, email="dev@example.com", role=UserRole.it_developer, organization_id=org.id)

    row = (
        await db_session.execute(
            select(OrganizationModule).where(
                OrganizationModule.organization_id == org.id, OrganizationModule.module_key == "it_tickets"
            )
        )
    ).scalar_one()
    row.enabled = False
    await db_session.commit()

    access = await get_effective_access(db_session, dev, org)
    assert access["modules"] == {"assets": ACCESS_READ}


async def test_org_role_access_denial_narrows_but_does_not_touch_other_modules(db_session):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    manager = await make_user(
        db_session, email="mgr@example.com", role=UserRole.security_manager, organization_id=org.id
    )

    db_session.add(
        OrganizationRoleAccess(
            organization_id=org.id, role=UserRole.security_manager, module_key="reports", enabled=False
        )
    )
    await db_session.commit()

    access = await get_effective_access(db_session, manager, org)
    assert "reports" not in access["modules"]
    assert access["modules"]["assets"] == ACCESS_WRITE
    assert access["modules"]["soc"] == ACCESS_READ
    assert access["modules"]["incidents"] == ACCESS_WRITE


async def test_user_override_denies_only_that_user(db_session):
    org = await make_organization(db_session)
    auditor_a = await make_user(db_session, email="auditor.a@example.com", role=UserRole.auditor, organization_id=org.id)
    auditor_b = await make_user(db_session, email="auditor.b@example.com", role=UserRole.auditor, organization_id=org.id)

    db_session.add(
        UserAccessOverride(user_id=auditor_a.id, organization_id=org.id, module_key="reports", allowed=False)
    )
    await db_session.commit()

    access_a = await get_effective_access(db_session, auditor_a, org)
    access_b = await get_effective_access(db_session, auditor_b, org)

    assert "reports" not in access_a["modules"]
    assert access_a["modules"] == {"assets": ACCESS_READ, "audit_logs": ACCESS_WRITE}
    assert access_b["modules"] == {"assets": ACCESS_READ, "reports": ACCESS_WRITE, "audit_logs": ACCESS_WRITE}


async def test_user_override_can_never_grant_beyond_role_default(db_session):
    """allowed=True on a UserAccessOverride is documented as a no-op --
    it can never grant a module the role doesn't already have by
    default, no matter what the row says."""
    org = await make_organization(db_session)
    dev = await make_user(db_session, email="dev@example.com", role=UserRole.it_developer, organization_id=org.id)

    db_session.add(
        UserAccessOverride(user_id=dev.id, organization_id=org.id, module_key="soc", allowed=True)
    )
    await db_session.commit()

    access = await get_effective_access(db_session, dev, org)
    assert "soc" not in access["modules"]
    assert access["modules"] == {"assets": ACCESS_READ, "it_tickets": ACCESS_WRITE}


async def test_soc_mode_gates_soc_analyst_soc_and_incidents_only(db_session):
    org = await make_organization(db_session, soc_mode=SocMode.managed)
    analyst = await make_user(db_session, email="analyst@example.com", role=UserRole.soc_analyst, organization_id=org.id)

    managed_access = await get_effective_access(db_session, analyst, org)
    assert "soc" not in managed_access["modules"]
    assert "incidents" not in managed_access["modules"]
    assert managed_access["modules"]["assets"] == ACCESS_WRITE
    assert managed_access["modules"]["ai_agents"] == ACCESS_WRITE
    assert managed_access["modules"]["reports"] == ACCESS_WRITE

    org.soc_mode = SocMode.in_house
    await db_session.commit()
    await db_session.refresh(org)

    in_house_access = await get_effective_access(db_session, analyst, org)
    assert in_house_access["modules"]["soc"] == ACCESS_WRITE
    assert in_house_access["modules"]["incidents"] == ACCESS_WRITE


async def test_owner_gets_write_everywhere_except_soc_incidents_read_when_managed(db_session):
    org = await make_organization(db_session, soc_mode=SocMode.managed)
    owner = await make_admin(
        db_session, email="owner@example.com", admin_level=AdminLevel.organization_admin, organization_id=org.id
    )

    access = await get_effective_access(db_session, owner, org)
    for key, level in access["modules"].items():
        if key in ("soc", "incidents"):
            assert level == ACCESS_READ
        else:
            assert level == ACCESS_WRITE

    org.soc_mode = SocMode.in_house
    await db_session.commit()
    await db_session.refresh(org)

    access_in_house = await get_effective_access(db_session, owner, org)
    assert access_in_house["modules"]["soc"] == ACCESS_WRITE
    assert access_in_house["modules"]["incidents"] == ACCESS_WRITE


async def test_owner_module_disabled_by_platform_is_fully_removed(db_session):
    org = await make_organization(db_session)
    owner = await make_admin(
        db_session, email="owner@example.com", admin_level=AdminLevel.organization_admin, organization_id=org.id
    )

    row = (
        await db_session.execute(
            select(OrganizationModule).where(
                OrganizationModule.organization_id == org.id, OrganizationModule.module_key == "approvals"
            )
        )
    ).scalar_one()
    row.enabled = False
    await db_session.commit()

    access = await get_effective_access(db_session, owner, org)
    assert "approvals" not in access["modules"]


async def test_soc_visible_organization_ids_super_admin_sees_everything(db_session):
    super_admin = await make_admin(db_session, email="root@example.com", admin_level=AdminLevel.super_admin)
    scope = Scope(account=super_admin, account_type="admin", role=AdminLevel.super_admin.value, organization_id=None, user_id=super_admin.id)
    assert await soc_visible_organization_ids(db_session, scope) is None


async def test_soc_visible_organization_ids_platform_soc_only_assigned_managed_active(db_session):
    soc = await make_admin(db_session, email="soc@example.com", admin_level=AdminLevel.platform_soc_analyst)
    org_managed_active = await make_organization(db_session, name="Managed Active", soc_mode=SocMode.managed)
    org_in_house = await make_organization(db_session, name="In House", soc_mode=SocMode.in_house)
    org_managed_but_unassigned = await make_organization(db_session, name="Managed Unassigned", soc_mode=SocMode.managed)

    db_session.add_all([
        SocOrganizationAssignment(admin_id=soc.id, organization_id=org_managed_active.id),
        SocOrganizationAssignment(admin_id=soc.id, organization_id=org_in_house.id),
    ])
    await db_session.commit()

    scope = Scope(account=soc, account_type="admin", role=AdminLevel.platform_soc_analyst.value, organization_id=None, user_id=soc.id)
    visible = await soc_visible_organization_ids(db_session, scope)

    assert visible == [org_managed_active.id]
    assert org_in_house.id not in visible
    assert org_managed_but_unassigned.id not in visible


async def test_soc_visible_organization_ids_platform_soc_with_no_assignments_sees_none(db_session):
    soc = await make_admin(db_session, email="soc@example.com", admin_level=AdminLevel.platform_soc_analyst)
    scope = Scope(account=soc, account_type="admin", role=AdminLevel.platform_soc_analyst.value, organization_id=None, user_id=soc.id)
    assert await soc_visible_organization_ids(db_session, scope) == []


async def test_soc_visible_organization_ids_org_account_in_house_sees_only_own_org(db_session):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    analyst = await make_user(db_session, email="analyst@example.com", role=UserRole.soc_analyst, organization_id=org.id)
    scope = Scope(account=analyst, account_type="user", role=UserRole.soc_analyst.value, organization_id=org.id, user_id=analyst.id)
    assert await soc_visible_organization_ids(db_session, scope) == [org.id]


async def test_soc_visible_organization_ids_org_account_managed_sees_nothing(db_session):
    org = await make_organization(db_session, soc_mode=SocMode.managed)
    owner = await make_admin(db_session, email="owner@example.com", organization_id=org.id)
    scope = Scope(account=owner, account_type="admin", role=AdminLevel.organization_admin.value, organization_id=org.id, user_id=owner.id)
    assert await soc_visible_organization_ids(db_session, scope) == []
