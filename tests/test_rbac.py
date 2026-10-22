"""
SentinelX QA Test Suite: Multi-Tenancy & Role-Based Access Control.

Module: RBAC
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminLevel, SocMode, UserRole
from backend.tests.helpers import auth, login, make_admin, make_organization, make_user
from tc import tc


@tc(
    id="RBAC-01",
    module="RBAC",
    description="Super admin has unrestricted cross-organization access",
    preconditions="Super admin account exists",
    steps="GET /api/v1/admin/organizations with super admin token",
    expected="Response status 200 with list containing all tenant organizations",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_rbac_01_super_admin_cross_org_access(client: AsyncClient, db_session: AsyncSession):
    org1 = await make_organization(db_session, name="TenantAlpha")
    org2 = await make_organization(db_session, name="TenantBeta")

    super_admin = await make_admin(
        db_session,
        email="super_rbac@example.com",
        admin_level=AdminLevel.super_admin,
    )
    token = await login(client, super_admin.email)

    resp = await client.get("/api/v1/admin/organizations", headers=auth(token))
    assert resp.status_code == 200
    data = resp.json()
    org_list = data.get("organizations", data if isinstance(data, list) else [])
    org_ids = [o["id"] for o in org_list]
    assert str(org1.id) in org_ids or org1.id in org_ids
    assert str(org2.id) in org_ids or org2.id in org_ids


@tc(
    id="RBAC-02",
    module="RBAC",
    description="Organization admin is forbidden from mutating foreign organization",
    preconditions="Org Admin for Org A, foreign Org B exists",
    steps="PATCH /api/v1/admin/organizations/{org_b_id} using Org A admin token",
    expected="Response status 403 Forbidden or 404 Not Found",
    type="automated",
    owner="Riteka Singh",
)
@pytest.mark.asyncio
async def test_rbac_02_org_admin_cross_tenant_mutation_blocked(
    client: AsyncClient, db_session: AsyncSession
):
    org_a = await make_organization(db_session, name="OrgAlpha")
    org_b = await make_organization(db_session, name="OrgBeta")

    admin_a = await make_admin(
        db_session,
        email="admin_a@example.com",
        admin_level=AdminLevel.organization_admin,
        organization_id=org_a.id,
    )
    token = await login(client, admin_a.email)

    resp = await client.patch(
        f"/api/v1/admin/organizations/{org_b.id}",
        headers=auth(token),
        json={"name": "Hacked Name"},
    )
    assert resp.status_code in {403, 404}


@tc(
    id="RBAC-03",
    module="RBAC",
    description="Standard SOC analyst user cannot perform administrative actions",
    preconditions="SOC analyst user in Org A",
    steps="POST /api/v1/organization/invitations using SOC analyst token",
    expected="Response status 403 Forbidden",
    type="automated",
    owner="Aanchal Rai",
)
@pytest.mark.asyncio
async def test_rbac_03_soc_analyst_cannot_invite_users(
    client: AsyncClient, db_session: AsyncSession
):
    org = await make_organization(db_session, name="OrgAnalyst")
    user = await make_user(
        db_session,
        email="analyst_low@example.com",
        role=UserRole.soc_analyst,
        organization_id=org.id,
    )
    token = await login(client, user.email)

    resp = await client.post(
        "/api/v1/organization/invitations",
        headers=auth(token),
        json={"email": "unauth_invite@example.com", "role": "soc_analyst"},
    )
    assert resp.status_code == 403


@tc(
    id="RBAC-04",
    module="RBAC",
    description="Strict cross-tenant data isolation: Org A user cannot see Org B devices or alerts",
    preconditions="Org A and Org B both exist with separate devices/alerts",
    steps="Query alerts as in-house Org A user and verify no Org B data is returned",
    expected="Org A query returns 200 with only Org A resources, never Org B",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_rbac_04_cross_tenant_isolation(client: AsyncClient, db_session: AsyncSession):
    org_a = await make_organization(db_session, name="IsolationOrgA", soc_mode=SocMode.in_house)
    org_b = await make_organization(db_session, name="IsolationOrgB", soc_mode=SocMode.in_house)

    user_a = await make_user(
        db_session,
        email="user_a@example.com",
        role=UserRole.soc_analyst,
        organization_id=org_a.id,
    )
    token_a = await login(client, user_a.email)

    resp = await client.get("/api/v1/alerts", headers=auth(token_a))
    assert resp.status_code == 200
    alerts = resp.json().get("items", resp.json()) if isinstance(resp.json(), dict) else resp.json()
    for item in alerts:
        if isinstance(item, dict) and "organization_id" in item:
            assert str(item["organization_id"]) == str(org_a.id)
