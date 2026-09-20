"""
First auth tests: register -> verify -> login -> me, plus a couple of
failure paths and a check that the two endpoints app/routers/organizations.py
and app/routers/stats.py just had auth added to actually enforce it.

Run with: pytest (from backend/), after `createdb sentinelx_test`.
"""

from sqlalchemy import select

from app.models import PendingRegistration


async def test_register_verify_login_me(client, db_session):
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Test Analyst",
            "email": "test.analyst@example.com",
            "password": "correct-horse-battery",
            "role": "soc_analyst",
        },
    )
    assert register_resp.status_code == 200
    assert register_resp.json()["email"] == "test.analyst@example.com"

    # No SMTP configured in tests, so the code never actually gets emailed
    # -- read it straight from the pending row, same as the backend prints
    # to its own console in dev.
    pending = (
        await db_session.execute(
            select(PendingRegistration).where(
                PendingRegistration.email == "test.analyst@example.com"
            )
        )
    ).scalar_one()
    code = pending.verification_code
    assert code

    verify_resp = await client.post(
        "/api/v1/auth/verify-email",
        json={"email": "test.analyst@example.com", "code": code},
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["account_type"] == "user"

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "test.analyst@example.com", "password": "correct-horse-battery"},
    )
    assert login_resp.status_code == 200
    body = login_resp.json()
    assert body["user"]["email"] == "test.analyst@example.com"
    token = body["access_token"]

    me_resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "test.analyst@example.com"


async def test_login_wrong_password_is_rejected(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Another User",
            "email": "another.user@example.com",
            "password": "correct-horse-battery",
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
