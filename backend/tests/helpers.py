"""
Shared seed/login helpers for the org-management/access-control test
suite (tests/test_access.py, test_admin_organizations.py,
test_admin_soc.py, test_organization_owner.py,
test_invitations_public.py, test_org_lifecycle.py).

tests/test_scope.py and tests/test_auth.py predate this feature and keep
their own small local helpers -- not worth churning working tests just
to switch which module a private helper lives in.
"""

from app.access import seed_default_modules
from app.models import (
    AccountEmail,
    Admin,
    AdminLevel,
    Organization,
    OrganizationStatus,
    SocMode,
    User,
    UserRole,
)
from app.security import hash_password

TEST_PASSWORD = "correct-horse-battery"


async def make_organization(
    db_session,
    *,
    name="Aurora Health",
    status=OrganizationStatus.active,
    soc_mode=SocMode.managed,
    seed_modules=True,
    max_members=None,
    industry=None,
):
    org = Organization(
        name=name,
        status=status,
        soc_mode=soc_mode,
        max_members=max_members,
        industry=industry,
    )
    db_session.add(org)
    await db_session.flush()
    if seed_modules:
        await seed_default_modules(db_session, org.id)
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def make_admin(
    db_session,
    *,
    email,
    name="Admin",
    admin_level=AdminLevel.organization_admin,
    organization_id=None,
    is_active=True,
    password=TEST_PASSWORD,
):
    admin = Admin(
        name=name,
        email=email,
        password_hash=hash_password(password),
        admin_level=admin_level,
        organization_id=organization_id,
        is_active=is_active,
        is_verified=True,
    )
    db_session.add(admin)
    await db_session.flush()
    db_session.add(AccountEmail(email=email, account_type="admin", account_id=admin.id))
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


async def make_user(
    db_session,
    *,
    email,
    name="User",
    role=UserRole.soc_analyst,
    organization_id,
    is_active=True,
    password=TEST_PASSWORD,
):
    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=role,
        organization_id=organization_id,
        is_active=is_active,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(AccountEmail(email=email, account_type="user", account_id=user.id))
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def login(client, email, password=TEST_PASSWORD) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
