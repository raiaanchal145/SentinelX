"""
Auth tests for the invite-only platform (docs/DECISIONS.md): there is no
register endpoint, and verify-email / resend-verification exist for
exactly one flow -- the 3-wrong-passwords lockout, where login flips
is_verified to False, emails a 10-minute one-time code, and the account
must verify before it can log in again.

Every test that probes the anonymous verify/resend surface with an
unknown email asserts the response is byte-identical to the response for
a known email in the same situation -- nothing on that surface may
reveal whether an address has an account.

Also pins the fact that GET /organizations and GET /stats/overview both
require auth (both were once-open holes).

No SMTP is configured in tests, so codes are read straight off the
account row, same as the backend prints to its own console in dev.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Admin
from tests.helpers import make_admin, make_organization

AUTH_BASE = "/api/v1/auth"
TEST_PASSWORD = "correct-horse-battery"


async def _locked_admin(db_session, client, *, email="locked@example.com"):
    """A verified admin put through the full lockout: the 3rd wrong
    password trips it (counter resets, is_verified flips, code sent)."""
    org = await make_organization(db_session)
    await make_admin(db_session, email=email, organization_id=org.id)
    for _ in range(2):
        wrong = await client.post(f"{AUTH_BASE}/login", json={"email": email, "password": "not-the-password"})
        assert wrong.status_code == 401

    third = await client.post(f"{AUTH_BASE}/login", json={"email": email, "password": "not-the-password"})
    assert third.status_code == 403
    assert "verify" in third.json()["detail"].lower()

    admin = (await db_session.execute(select(Admin).where(Admin.email == email))).scalar_one()
    await db_session.refresh(admin)
    assert admin.is_verified is False
    assert admin.verification_code, "the lockout must generate a code"
    assert admin.failed_login_attempts == 0, "the counter resets when the lockout trips"
    return admin


async def test_register_endpoint_no_longer_exists(client):
    """Invite-only: the self-signup endpoint was removed entirely."""
    resp = await client.post(
        f"{AUTH_BASE}/register",
        json={"name": "Ghost", "email": "ghost@example.com", "password": TEST_PASSWORD, "organization_name": "Ghost Org"},
    )
    assert resp.status_code in (404, 405)


async def test_verify_email_lockout_full_flow(client, db_session):
    admin = await _locked_admin(db_session, client, email="flow@example.com")

    # Even the CORRECT password is refused until the account is verified.
    unverified_login = await client.post(f"{AUTH_BASE}/login", json={"email": "flow@example.com", "password": TEST_PASSWORD})
    assert unverified_login.status_code == 403

    # A wrong code answers with the generic 400...
    wrong = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "flow@example.com", "code": "000000"})
    assert wrong.status_code == 400

    # ...and the right one clears the lockout.
    ok = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "flow@example.com", "code": admin.verification_code})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["account_type"] == "admin"
    assert body["email"] == "flow@example.com"

    await db_session.refresh(admin)
    assert admin.is_verified is True
    assert admin.verification_code is None
    assert admin.verification_code_expires_at is None

    login = await client.post(f"{AUTH_BASE}/login", json={"email": "flow@example.com", "password": TEST_PASSWORD})
    assert login.status_code == 200
    assert login.json()["user"]["email"] == "flow@example.com"


async def test_verification_code_expires_after_ten_minutes(client, db_session):
    admin = await _locked_admin(db_session, client, email="expire@example.com")

    admin.verification_code_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    expired = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "expire@example.com", "code": admin.verification_code})
    assert expired.status_code == 400

    # Resend mints a fresh code (and stays silent about the account).
    resend = await client.post(f"{AUTH_BASE}/resend-verification", json={"email": "expire@example.com"})
    assert resend.status_code == 200

    await db_session.refresh(admin)
    assert admin.verification_code
    assert admin.verification_code_expires_at > datetime.now(timezone.utc)

    ok = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "expire@example.com", "code": admin.verification_code})
    assert ok.status_code == 200


async def test_verification_code_is_single_use(client, db_session):
    admin = await _locked_admin(db_session, client, email="once@example.com")
    code = admin.verification_code

    first = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "once@example.com", "code": code})
    assert first.status_code == 200

    replay = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "once@example.com", "code": code})
    assert replay.status_code == 400


async def test_resend_verification_rotates_the_code(client, db_session):
    admin = await _locked_admin(db_session, client, email="rotate@example.com")
    first_code = admin.verification_code

    resend = await client.post(f"{AUTH_BASE}/resend-verification", json={"email": "rotate@example.com"})
    assert resend.status_code == 200
    assert resend.json() == {"message": "If a verification code was sent to this email, it is in your inbox."}

    await db_session.refresh(admin)
    assert admin.verification_code != first_code

    stale = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "rotate@example.com", "code": first_code})
    assert stale.status_code == 400

    fresh = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "rotate@example.com", "code": admin.verification_code})
    assert fresh.status_code == 200


async def test_verify_email_never_reveals_whether_an_email_exists(client, db_session):
    """Unknown email + wrong code on a real account -> identical bodies."""
    admin = await _locked_admin(db_session, client, email="quiet@example.com")

    known = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "quiet@example.com", "code": "000000"})
    unknown = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "nobody@example.com", "code": "000000"})

    assert known.status_code == unknown.status_code == 400
    assert known.json() == unknown.json()
    assert admin.email not in unknown.text


async def test_resend_verification_never_reveals_whether_an_email_exists(client, db_session):
    await _locked_admin(db_session, client, email="quiet2@example.com")

    known = await client.post(f"{AUTH_BASE}/resend-verification", json={"email": "quiet2@example.com"})
    unknown = await client.post(f"{AUTH_BASE}/resend-verification", json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


async def test_verify_email_attempts_are_capped_per_email(client, db_session):
    """Five wrong codes blow the anonymous attempt budget for that
    email -- even the correct code is refused until the window clears."""
    admin = await _locked_admin(db_session, client, email="hammer@example.com")

    for _ in range(5):
        wrong = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "hammer@example.com", "code": "000000"})
        assert wrong.status_code == 400

    correct = await client.post(f"{AUTH_BASE}/verify-email", json={"email": "hammer@example.com", "code": admin.verification_code})
    assert correct.status_code == 400


async def test_login_wrong_password_is_rejected(client, db_session):
    org = await make_organization(db_session)
    await make_admin(db_session, email="solid@example.com", organization_id=org.id)

    resp = await client.post(f"{AUTH_BASE}/login", json={"email": "solid@example.com", "password": "wrong-password"})
    assert resp.status_code == 401


async def test_login_unknown_email_is_rejected(client):
    resp = await client.post(f"{AUTH_BASE}/login", json={"email": "nobody@example.com", "password": "whatever"})
    assert resp.status_code == 401


async def test_me_requires_a_token(client):
    resp = await client.get(f"{AUTH_BASE}/me")
    assert resp.status_code == 401


async def test_organizations_list_requires_auth(client):
    """GET /organizations was once an open endpoint; now the legacy
    router is deleted entirely (invite-only, docs/DECISIONS.md), so it
    is gone (404) rather than merely guarded."""
    resp = await client.get("/api/v1/organizations")
    assert resp.status_code in (401, 404, 405)


async def test_stats_overview_requires_auth(client):
    """GET /stats/overview used to be open; this is the regression test
    for that fix."""
    resp = await client.get("/api/v1/stats/overview")
    assert resp.status_code == 401
