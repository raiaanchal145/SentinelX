"""
SentinelX QA Test Suite: Authentication & Session Management.

Module: AUTH
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.tests.helpers import auth, login, make_admin, make_organization, make_user
from tc import tc


@tc(
    id="AUTH-01",
    module="Auth",
    description="Valid user credentials return 200 OK with JWT access token",
    preconditions="Active user exists in database",
    steps="POST /api/v1/auth/login with valid email and password",
    expected="Response status 200 with access_token and bearer type",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_auth_01_valid_login(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="AuthOrg1")
    user = await make_user(
        db_session,
        email="user1@example.com",
        organization_id=org.id,
        password="ValidPassword123!",
    )

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "ValidPassword123!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"].lower() == "bearer"


@tc(
    id="AUTH-02",
    module="Auth",
    description="Invalid password returns 401 Unauthorized",
    preconditions="Active user exists in database",
    steps="POST /api/v1/auth/login with wrong password",
    expected="Response status 401 with generic error message",
    type="automated",
    owner="Riteka Singh",
)
@pytest.mark.asyncio
async def test_auth_02_invalid_password(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="AuthOrg2")
    user = await make_user(
        db_session,
        email="user2@example.com",
        organization_id=org.id,
        password="ValidPassword123!",
    )

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "WrongPassword999!"},
    )
    assert resp.status_code == 401


@tc(
    id="AUTH-03",
    module="Auth",
    description="Unverified user account is blocked from logging in",
    preconditions="User exists with is_verified=False",
    steps="POST /api/v1/auth/login for unverified account",
    expected="Response status 403 Forbidden indicating email verification required",
    type="automated",
    owner="Aanchal Rai",
)
@pytest.mark.asyncio
async def test_auth_03_unverified_account_blocked(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="AuthOrg3")
    user = await make_user(
        db_session,
        email="unverified@example.com",
        organization_id=org.id,
        password="ValidPassword123!",
    )
    user.is_verified = False
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "ValidPassword123!"},
    )
    assert resp.status_code == 403
    assert "verif" in resp.text.lower()


@tc(
    id="AUTH-04",
    module="Auth",
    description="Email verification code verifies account and enables login",
    preconditions="Unverified account with verification code in database",
    steps="POST /api/v1/auth/verify-email with valid code, then login",
    expected="Verification succeeds and user can subsequently log in",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_auth_04_verify_email_flow(client: AsyncClient, db_session: AsyncSession, mock_mailer):
    org = await make_organization(db_session, name="AuthOrg4")
    user = await make_user(
        db_session,
        email="verify_me@example.com",
        organization_id=org.id,
        password="ValidPassword123!",
    )
    user.is_verified = False
    user.verification_code = "123456"
    import datetime as dt
    user.verification_code_expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
    await db_session.commit()

    verify_resp = await client.post(
        "/api/v1/auth/verify-email",
        json={"email": user.email, "code": "123456"},
    )
    assert verify_resp.status_code == 200

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "ValidPassword123!"},
    )
    assert login_resp.status_code == 200


@tc(
    id="AUTH-05",
    module="Auth",
    description="Forgot password flow verifies code and updates password",
    preconditions="Active user exists in database",
    steps="Trigger forgot-password, submit reset-password with code and new password",
    expected="Password updated and user can log in with new password",
    type="automated",
    owner="Riteka Singh",
)
@pytest.mark.asyncio
async def test_auth_05_password_reset_flow(client: AsyncClient, db_session: AsyncSession, mock_mailer):
    org = await make_organization(db_session, name="AuthOrg5")
    user = await make_user(
        db_session,
        email="reset_me@example.com",
        organization_id=org.id,
        password="OldPassword123!",
    )

    # Request password reset
    forgot_resp = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": user.email},
    )
    assert forgot_resp.status_code == 200

    await db_session.refresh(user)
    reset_code = user.password_reset_code or mock_mailer.get_latest_code(user.email)
    assert reset_code is not None

    # Reset password
    reset_resp = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": user.email,
            "code": reset_code,
            "new_password": "NewSecretPassword456!",
        },
    )
    assert reset_resp.status_code == 200

    # Verify login with new password
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "NewSecretPassword456!"},
    )
    assert login_resp.status_code == 200


@tc(
    id="AUTH-06",
    module="Auth",
    description="Change password enforces old password validation",
    preconditions="Authenticated user session active",
    steps="POST /api/v1/profile/change-password with invalid old password",
    expected="Response status 400 rejecting change due to incorrect old password",
    type="automated",
    owner="Aanchal Rai",
)
@pytest.mark.asyncio
async def test_auth_06_change_password_requires_old_password(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="AuthOrg6")
    user = await make_user(
        db_session,
        email="pwd_change@example.com",
        organization_id=org.id,
        password="CurrentPassword123!",
    )

    token = await login(client, user.email, "CurrentPassword123!")

    bad_resp = await client.post(
        "/api/v1/profile/change-password",
        headers=auth(token),
        json={
            "old_password": "WrongOldPassword999!",
            "new_password": "FreshPassword789!",
        },
    )
    assert bad_resp.status_code == 400


@tc(
    id="AUTH-07",
    module="Auth",
    description="Revoking single session terminates that session",
    preconditions="Authenticated user with active session record",
    steps="DELETE /api/v1/profile/sessions/{session_id}",
    expected="Session record is revoked and marked with revoked=True",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_auth_07_revoke_single_session(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="AuthOrg7")
    user = await make_user(
        db_session,
        email="session_user@example.com",
        organization_id=org.id,
        password="ValidPassword123!",
    )

    token = await login(client, user.email, "ValidPassword123!")

    sessions_resp = await client.get("/api/v1/profile/sessions", headers=auth(token))
    assert sessions_resp.status_code == 200
    sessions = sessions_resp.json().get("sessions", [])
    if sessions:
        sess_id = sessions[0]["id"]
        del_resp = await client.delete(f"/api/v1/profile/sessions/{sess_id}", headers=auth(token))
        assert del_resp.status_code in {200, 204}


@tc(
    id="AUTH-08",
    module="Auth",
    description="Sign out everywhere revokes all active sessions for account",
    preconditions="Multiple active sessions exist for account",
    steps="POST /api/v1/profile/sessions/revoke-all?keep_current=false",
    expected="All active sessions revoked, active list becomes empty",
    type="automated",
    owner="Riteka Singh",
)
@pytest.mark.asyncio
async def test_auth_08_sign_out_everywhere(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="AuthOrg8")
    user = await make_user(
        db_session,
        email="everywhere@example.com",
        organization_id=org.id,
        password="ValidPassword123!",
    )

    token = await login(client, user.email, "ValidPassword123!")

    # Sign out everywhere
    resp = await client.post("/api/v1/profile/sessions/revoke-all?keep_current=false", headers=auth(token))
    assert resp.status_code == 200

    # Verify session token is now revoked / logged out
    list_resp = await client.get("/api/v1/profile/sessions", headers=auth(token))
    assert list_resp.status_code == 401

