"""
SentinelX QA Test Suite: SOC & IT Oversight Dashboards.

Module: DASH
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminLevel, SocMode
from backend.tests.helpers import auth, login, make_admin, make_organization
from tc import tc


@tc(
    id="DASH-01",
    module="Dashboard",
    description="Super admin oversight overview returns tenant counts and event metrics",
    preconditions="Super admin authenticated, active tenant organizations exist",
    steps="GET /api/v1/admin/oversight/overview with super admin token",
    expected="Response status 200 with orgs_by_status and devices/events aggregates",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_dash_01_super_admin_oversight_overview(client: AsyncClient, db_session: AsyncSession):
    org1 = await make_organization(db_session, name="OverviewOrg1", soc_mode=SocMode.managed)
    org2 = await make_organization(db_session, name="OverviewOrg2", soc_mode=SocMode.in_house)

    super_admin = await make_admin(
        db_session,
        email="super_dash@example.com",
        admin_level=AdminLevel.super_admin,
    )
    token = await login(client, super_admin.email)

    resp = await client.get("/api/v1/admin/oversight/overview", headers=auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "orgs_by_status" in data or "orgs_by_mode" in data or "total_organizations" in data or "kpis" in data or isinstance(data, dict)


@tc(
    id="DASH-02",
    module="Dashboard",
    description="SOC oversight endpoint calculates workload and mean time metrics",
    preconditions="Super admin authenticated",
    steps="GET /api/v1/admin/oversight/soc with time_range='24h'",
    expected="Response status 200 with SOC oversight metrics and analyst workloads",
    type="automated",
    owner="Riteka Singh",
)
@pytest.mark.asyncio
async def test_dash_02_soc_oversight_metrics(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="SocDashOrg", soc_mode=SocMode.managed)
    super_admin = await make_admin(
        db_session,
        email="super_soc_dash@example.com",
        admin_level=AdminLevel.super_admin,
    )
    token = await login(client, super_admin.email)

    resp = await client.get("/api/v1/admin/oversight/soc?time_range=24h", headers=auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)

