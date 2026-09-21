"""
Tenant-isolation matrix and role-guard tests for app/scope.py.

Two kinds of test here:

1. Dependency unit tests (require_admin / require_roles) -- call the
   dependency functions directly with a hand-built Scope, no HTTP or
   database involved. Fast, and pins down the guard logic itself.
2. The tenant-isolation matrix -- seeds two real organizations (plus a
   super_admin, who spans both) and drives every existing
   organization-scoped endpoint through the real HTTP client, asserting
   org A never sees org B's data and vice versa. Add a case here for
   every new organization-scoped endpoint as it's built -- that's what
   "done when every endpoint uses the scope helpers" is actually
   checking.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.models import AccountEmail, Admin, AdminLevel, Asset, AssetType, Organization, User, UserRole
from app.scope import Scope, require_admin, require_roles
from app.security import hash_password

TEST_PASSWORD = "correct-horse-battery"


def _scope(account_type: str, role: str, organization_id=None) -> Scope:
    """A Scope with no real backing account -- fine for the pure guard
    checks below, which only look at account_type/role."""
    return Scope(
        account=None,
        account_type=account_type,
        role=role,
        organization_id=organization_id,
        user_id=uuid.uuid4(),
    )


# ---------------------------------------------------------------------------
# Dependency unit tests
# ---------------------------------------------------------------------------


async def test_require_admin_allows_admin():
    scope = _scope("admin", "organization_admin", organization_id=uuid.uuid4())
    assert await require_admin(scope=scope) is scope


async def test_require_admin_rejects_user():
    scope = _scope("user", "soc_analyst", organization_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(scope=scope)
    assert exc_info.value.status_code == 403


async def test_require_roles_allows_matching_role():
    scope = _scope("user", "soc_analyst", organization_id=uuid.uuid4())
    check = require_roles("soc_analyst", "it_developer")
    assert await check(scope=scope) is scope


async def test_require_roles_rejects_non_matching_role():
    scope = _scope("user", "auditor", organization_id=uuid.uuid4())
    check = require_roles("soc_analyst", "it_developer")
    with pytest.raises(HTTPException) as exc_info:
        await check(scope=scope)
    assert exc_info.value.status_code == 403


async def test_require_roles_admin_always_passes():
    """Admins aren't restricted by UserRole -- an admin passes require_roles
    regardless of which roles were listed."""
    scope = _scope("admin", "super_admin", organization_id=None)
    check = require_roles("soc_analyst")
    assert await check(scope=scope) is scope


# ---------------------------------------------------------------------------
# Tenant-isolation matrix (real endpoints, real database, real JWTs)
# ---------------------------------------------------------------------------


async def _seed_admin(db_session, *, email, name, admin_level, organization_id=None):
    admin = Admin(
        name=name,
        email=email,
        password_hash=hash_password(TEST_PASSWORD),
        admin_level=admin_level,
        organization_id=organization_id,
        is_active=True,
        is_verified=True,
    )
    db_session.add(admin)
    await db_session.flush()
    db_session.add(AccountEmail(email=email, account_type="admin", account_id=admin.id))
    await db_session.commit()
    return admin


async def _seed_user(db_session, *, email, name, role, organization_id):
    user = User(
        name=name,
        email=email,
        password_hash=hash_password(TEST_PASSWORD),
        role=role,
        organization_id=organization_id,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(AccountEmail(email=email, account_type="user", account_id=user.id))
    await db_session.commit()
    return user


async def _login(client, email) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_organizations_list_is_isolated_by_tenant(client, db_session):
    org_a = Organization(name="Aurora Health")
    org_b = Organization(name="Blackridge Logistics")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    await _seed_admin(
        db_session, email="admin.a@example.com", name="Admin A",
        admin_level=AdminLevel.organization_admin, organization_id=org_a.id,
    )
    await _seed_admin(
        db_session, email="admin.b@example.com", name="Admin B",
        admin_level=AdminLevel.organization_admin, organization_id=org_b.id,
    )
    await _seed_admin(
        db_session, email="root@example.com", name="Root",
        admin_level=AdminLevel.super_admin, organization_id=None,
    )
    await _seed_user(
        db_session, email="analyst.a@example.com", name="Analyst A",
        role=UserRole.soc_analyst, organization_id=org_a.id,
    )

    token_a = await _login(client, "admin.a@example.com")
    token_b = await _login(client, "admin.b@example.com")
    token_root = await _login(client, "root@example.com")
    token_analyst_a = await _login(client, "analyst.a@example.com")

    names_a = {o["name"] for o in (await client.get("/api/v1/organizations", headers=_auth(token_a))).json()}
    names_b = {o["name"] for o in (await client.get("/api/v1/organizations", headers=_auth(token_b))).json()}
    names_root = {o["name"] for o in (await client.get("/api/v1/organizations", headers=_auth(token_root))).json()}
    names_analyst_a = {o["name"] for o in (await client.get("/api/v1/organizations", headers=_auth(token_analyst_a))).json()}

    assert names_a == {"Aurora Health"}
    assert names_b == {"Blackridge Logistics"}
    assert names_root == {"Aurora Health", "Blackridge Logistics"}
    assert names_analyst_a == {"Aurora Health"}


async def test_stats_overview_counts_are_isolated_by_tenant(client, db_session):
    org_a = Organization(name="Aurora Health")
    org_b = Organization(name="Blackridge Logistics")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    await _seed_admin(
        db_session, email="admin.a@example.com", name="Admin A",
        admin_level=AdminLevel.organization_admin, organization_id=org_a.id,
    )
    await _seed_admin(
        db_session, email="admin.b@example.com", name="Admin B",
        admin_level=AdminLevel.organization_admin, organization_id=org_b.id,
    )
    await _seed_admin(
        db_session, email="root@example.com", name="Root",
        admin_level=AdminLevel.super_admin, organization_id=None,
    )

    db_session.add_all([
        Asset(organization_id=org_a.id, hostname="org-a-web-1", asset_type=AssetType.server),
        Asset(organization_id=org_a.id, hostname="org-a-web-2", asset_type=AssetType.server),
        Asset(organization_id=org_b.id, hostname="org-b-db-1", asset_type=AssetType.database),
    ])
    await db_session.commit()

    token_a = await _login(client, "admin.a@example.com")
    token_b = await _login(client, "admin.b@example.com")
    token_root = await _login(client, "root@example.com")

    stats_a = (await client.get("/api/v1/stats/overview", headers=_auth(token_a))).json()
    stats_b = (await client.get("/api/v1/stats/overview", headers=_auth(token_b))).json()
    stats_root = (await client.get("/api/v1/stats/overview", headers=_auth(token_root))).json()

    assert stats_a["assets"] == 2
    assert stats_a["organizations"] == 1

    assert stats_b["assets"] == 1
    assert stats_b["organizations"] == 1

    assert stats_root["assets"] == 3
    assert stats_root["organizations"] == 2


async def test_non_admin_cannot_create_an_organization(client, db_session):
    """Role guard: POST /organizations requires an admin account (any
    organization) -- a plain `users` account, in any organization, is
    rejected before it ever gets to write a new row."""
    org_a = Organization(name="Aurora Health")
    db_session.add(org_a)
    await db_session.flush()
    await _seed_user(
        db_session, email="analyst.a@example.com", name="Analyst A",
        role=UserRole.soc_analyst, organization_id=org_a.id,
    )

    token_analyst_a = await _login(client, "analyst.a@example.com")

    resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Shouldn't Exist"},
        headers=_auth(token_analyst_a),
    )
    assert resp.status_code == 403


async def test_organizations_and_stats_reject_unauthenticated_requests(client):
    """Regression coverage for the pre-scope-module bug: both endpoints
    used to be readable with no token at all."""
    assert (await client.get("/api/v1/organizations")).status_code == 401
    assert (await client.get("/api/v1/stats/overview")).status_code == 401
