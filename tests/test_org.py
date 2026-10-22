"""
SentinelX QA Test Suite: Organization Lifecycle & Invitations.

Module: ORG
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

from datetime import timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.invite_service import create_invitation
from app.models import AdminLevel, OrganizationStatus, SocMode, UserRole
from app.timeutils import utcnow
from backend.tests.helpers import auth, login, make_admin, make_organization
from tc import tc


@tc(
    id="ORG-01",
    module="Organization",
    description="Create active organization with default security modules enabled",
    preconditions="Database ready",
    steps="Create Organization row and seed default modules",
    expected="Organization saved with active status and modules seeded",
    type="automated",
    owner="Aanchal Rai",
)
@pytest.mark.asyncio
async def test_org_01_create_org_with_modules(db_session: AsyncSession):
    org = await make_organization(
        db_session,
        name="CyberShield Corp",
        status=OrganizationStatus.active,
        soc_mode=SocMode.managed,
        seed_modules=True,
    )
    assert org.id is not None
    assert org.name == "CyberShield Corp"
    assert org.status == OrganizationStatus.active
    assert org.soc_mode == SocMode.managed


@tc(
    id="ORG-02",
    module="Organization",
    description="Send organization invitation creates invitation record and email link",
    preconditions="Org admin authenticated and org is in_house soc_mode",
    steps="POST /api/v1/organization/invitations with invitee email and role",
    expected="Response status 201 with invitation details and token generated",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_org_02_send_invitation(client: AsyncClient, db_session: AsyncSession, mock_mailer):
    org = await make_organization(db_session, name="OrgInvites", soc_mode=SocMode.in_house)
    admin = await make_admin(
        db_session,
        email="admin_inv@example.com",
        admin_level=AdminLevel.organization_admin,
        organization_id=org.id,
    )
    token = await login(client, admin.email)

    resp = await client.post(
        "/api/v1/organization/invitations",
        headers=auth(token),
        json={"email": "analyst_new@example.com", "role": "soc_analyst"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "analyst_new@example.com"
    assert data["role"] == "soc_analyst"



@tc(
    id="ORG-03",
    module="Organization",
    description="Accept valid invitation creates user with correct role and marks invitation accepted",
    preconditions="Valid invitation token exists",
    steps="POST /api/v1/invitations/accept with token, full_name and password",
    expected="Response status 200 with access token and user info",
    type="automated",
    owner="Riteka Singh",
)
@pytest.mark.asyncio
async def test_org_03_accept_invitation(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="AcceptOrg")
    invitation, raw_token = await create_invitation(
        db_session,
        organization_id=org.id,
        email="invitee_success@example.com",
        kind="member",
        role=UserRole.soc_analyst,
        invited_by_admin_id=None,
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": raw_token,
            "full_name": "Jane Analyst",
            "password": "SecurePassword123!",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "invitee_success@example.com"


@tc(
    id="ORG-04",
    module="Organization",
    description="Accepting expired invitation token returns 404/400 error",
    preconditions="Expired invitation token exists",
    steps="POST /api/v1/invitations/accept on expired invitation",
    expected="Response status 404 or 400 with expired token explanation",
    type="automated",
    owner="Aanchal Rai",
)
@pytest.mark.asyncio
async def test_org_04_expired_invitation_rejected(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="ExpiredOrg")
    invitation, raw_token = await create_invitation(
        db_session,
        organization_id=org.id,
        email="expired_invitee@example.com",
        kind="member",
        role=UserRole.soc_analyst,
        invited_by_admin_id=None,
    )
    invitation.expires_at = utcnow() - timedelta(days=2)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": raw_token,
            "full_name": "Late User",
            "password": "SecurePassword123!",
        },
    )
    assert resp.status_code in {400, 404}


@tc(
    id="ORG-05",
    module="Organization",
    description="Reusing already accepted invitation token is rejected",
    preconditions="Invitation marked as already accepted",
    steps="POST /api/v1/invitations/accept on consumed token",
    expected="Response status 404 rejecting non-pending invitation",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_org_05_reused_invitation_rejected(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="ReusedOrg")
    invitation, raw_token = await create_invitation(
        db_session,
        organization_id=org.id,
        email="already_accepted@example.com",
        kind="member",
        role=UserRole.soc_analyst,
        invited_by_admin_id=None,
    )
    invitation.status = "accepted"
    await db_session.commit()

    resp = await client.post(
        "/api/v1/invitations/accept",
        json={
            "token": raw_token,
            "full_name": "Duplicate User",
            "password": "SecurePassword123!",
        },
    )
    assert resp.status_code in {400, 404}


@tc(
    id="ORG-06",
    module="Organization",
    description="Super admin updates organization status to suspended",
    preconditions="Super admin authenticated",
    steps="POST /api/v1/admin/organizations/{id}/suspend with reason",
    expected="Response status 200 with updated organization status 'suspended'",
    type="automated",
    owner="Riteka Singh",
)
@pytest.mark.asyncio
async def test_org_06_super_admin_status_update(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="StatusOrg")
    super_admin = await make_admin(
        db_session,
        email="super_status@example.com",
        admin_level=AdminLevel.super_admin,
    )
    token = await login(client, super_admin.email)

    resp = await client.post(
        f"/api/v1/admin/organizations/{org.id}/suspend",
        headers=auth(token),
        json={"reason": "Security audit requested suspension"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"


@tc(
    id="ORG-07",
    module="Organization",
    description="Toggle organization SOC mode between managed and in_house",
    preconditions="Super admin authenticated",
    steps="PUT /api/v1/admin/organizations/{id}/soc-mode with soc_mode='in_house'",
    expected="Response status 200 reflecting soc_mode update to in_house",
    type="automated",
    owner="Aanchal Rai",
)
@pytest.mark.asyncio
async def test_org_07_soc_mode_toggle(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="SocModeOrg", soc_mode=SocMode.managed)
    super_admin = await make_admin(
        db_session,
        email="super_mode@example.com",
        admin_level=AdminLevel.super_admin,
    )
    token = await login(client, super_admin.email)

    resp = await client.put(
        f"/api/v1/admin/organizations/{org.id}/soc-mode",
        headers=auth(token),
        json={"soc_mode": "in_house"},
    )
    assert resp.status_code == 200
    assert resp.json()["organization"]["soc_mode"] == "in_house"

