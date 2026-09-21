"""
Auth tests: register -> verify -> login -> me for the self-signup
organization-owner flow, plus a couple of failure paths and a check
that GET /organizations and GET /stats/overview both require auth.

Self-signup is organization-owner-only as of the org-management feature
(see app/routers/auth.py's RegisterRequest) -- there's no more "pick a
role" registration; every self-signup becomes an organization_admin with
a brand-new pending organization. See tests/test_org_lifecycle.py for
the full pending -> approved -> staffed end-to-end flow.

Run with: pytest (from backend/), after `createdb sentinelx_test`.
"""

from sqlalchemy import select

from app.models import Organization, OrganizationStatus, PendingRegistration


async def test_register_verify_login_me(client, db_session):
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Olivia Owner",
            "email": "olivia@example.com",
            "password": "correct-horse-battery",
            "organization_name": "Aurora Health",
        },
    )
    assert register_resp.status_code == 200
    assert register_resp.json()["email"] == "olivia@example.com"

    # No SMTP configured in tests, so the code never actually gets emailed
    # -- read it straight from the pending row, same as the backend prints
    # to its own console in dev.
    pending = (
        await db_session.execute(
            select(PendingRegistration).where(
                PendingRegistration.email == "olivia@example.com"
            )
        )
    ).scalar_one()
    code = pending.verification_code
    assert code

    verify_resp = await client.post(
        "/api/v1/auth/verify-email",
        json={"email": "olivia@example.com", "code": code},
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["account_type"] == "admin"
    assert verify_resp.json()["role"] == "organization_admin"

    org = (
        await db_session.execute(select(Organization).where(Organization.name == "Aurora Health"))
    ).scalar_one()
    assert org.status == OrganizationStatus.pending

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "olivia@example.com", "password": "correct-horse-battery"},
    )
    assert login_resp.status_code == 200
    body = login_resp.json()
    assert body["user"]["email"] == "olivia@example.com"
    token = body["access_token"]

    me_resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_resp.status_code == 200
    me_body = me_resp.json()
    assert me_body["email"] == "olivia@example.com"
    assert me_body["organization"]["status"] == "pending"


async def test_register_requires_an_organization_name(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "No Org",
            "email": "no.org@example.com",
            "password": "correct-horse-battery",
            "organization_name": "   ",
        },
    )
    assert resp.status_code == 400


async def test_register_rejects_an_already_registered_email(client, db_session):
    first = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "First Owner",
            "email": "dup@example.com",
            "password": "correct-horse-battery",
            "organization_name": "First Org",
        },
    )
    assert first.status_code == 200

    pending = (
        await db_session.execute(select(PendingRegistration).where(PendingRegistration.email == "dup@example.com"))
    ).scalar_one()
    await client.post(
        "/api/v1/auth/verify-email", json={"email": "dup@example.com", "code": pending.verification_code}
    )

    second = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Second Owner",
            "email": "dup@example.com",
            "password": "correct-horse-battery",
            "organization_name": "Second Org",
        },
    )
    assert second.status_code == 400


async def test_login_wrong_password_is_rejected(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Another User",
            "email": "another.user@example.com",
            "password": "correct-horse-battery",
            "organization_name": "Another Org",
        },
    )

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "another.user@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401


async def test_login_unknown_email_is_rejected(client):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever"},
    )
    assert resp.status_code == 401


async def test_me_requires_a_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_organizations_list_requires_auth(client):
    """GET /organizations used to be open; this is the regression test
    for that fix."""
    resp = await client.get("/api/v1/organizations")
    assert resp.status_code == 401


async def test_stats_overview_requires_auth(client):
    """GET /stats/overview used to be open; this is the regression test
    for that fix."""
    resp = await client.get("/api/v1/stats/overview")
    assert resp.status_code == 401
