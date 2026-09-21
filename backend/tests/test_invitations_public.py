"""
Public invitation endpoints -- app/routers/invitations.py. No
authentication; GET never distinguishes unknown/expired/revoked, and
accepting is the only way to create a member/owner/platform_soc account.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import AccountEmail, Admin, AdminLevel, Invitation, User, UserRole
from app.security import generate_invitation_token, hash_password
from tests.helpers import make_organization

INVITATIONS_BASE = "/api/v1/invitations"


async def _seed_invitation(db_session, *, organization_id, email, kind, role=None, expires_in=timedelta(days=7), status="pending"):
    raw_token, token_hash = generate_invitation_token()
    invitation = Invitation(
        organization_id=organization_id, email=email, kind=kind, role=role,
        token_hash=token_hash, status=status, expires_at=datetime.now(timezone.utc) + expires_in,
    )
    db_session.add(invitation)
    await db_session.commit()
    await db_session.refresh(invitation)
    return invitation, raw_token


async def test_validate_unknown_token_is_404(client):
    resp = await client.get(f"{INVITATIONS_BASE}/not-a-real-token")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "invitation_not_found"


async def test_validate_expired_token_is_404_and_flips_status(client, db_session):
    org = await make_organization(db_session)
    invitation, raw_token = await _seed_invitation(
        db_session, organization_id=org.id, email="late@example.com", kind="member",
        role=UserRole.it_developer, expires_in=timedelta(days=-1),
    )

    resp = await client.get(f"{INVITATIONS_BASE}/{raw_token}")
    assert resp.status_code == 404

    await db_session.refresh(invitation)
    assert invitation.status == "expired"


async def test_validate_revoked_token_is_404(client, db_session):
    org = await make_organization(db_session)
    _invitation, raw_token = await _seed_invitation(
        db_session, organization_id=org.id, email="revoked@example.com", kind="member",
        role=UserRole.it_developer, status="revoked",
    )
    resp = await client.get(f"{INVITATIONS_BASE}/{raw_token}")
    assert resp.status_code == 404


async def test_validate_pending_token_returns_details(client, db_session):
    org = await make_organization(db_session, name="Aurora Health")
    _invitation, raw_token = await _seed_invitation(
        db_session, organization_id=org.id, email="dev@example.com", kind="member", role=UserRole.it_developer,
    )
    resp = await client.get(f"{INVITATIONS_BASE}/{raw_token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["organization_name"] == "Aurora Health"
    assert body["role"] == "it_developer"
    assert body["email"] == "dev@example.com"


async def test_accept_member_invitation_creates_user_and_returns_a_session(client, db_session):
    org = await make_organization(db_session)
    _invitation, raw_token = await _seed_invitation(
        db_session, organization_id=org.id, email="dev@example.com", kind="member", role=UserRole.it_developer,
    )

    resp = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": raw_token, "full_name": "Dana Developer", "password": "correct-horse-battery"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["account_type"] == "user"
    assert body["user"]["role"] == "it_developer"
    assert body["access_token"]

    user = (await db_session.execute(select(User).where(User.email == "dev@example.com"))).scalar_one()
    assert user.organization_id == org.id
    assert user.role == UserRole.it_developer

    account_email = (await db_session.execute(select(AccountEmail).where(AccountEmail.email == "dev@example.com"))).scalar_one()
    assert account_email.account_type == "user"


async def test_accept_owner_invitation_creates_admin(client, db_session):
    org = await make_organization(db_session)
    _invitation, raw_token = await _seed_invitation(db_session, organization_id=org.id, email="owner@example.com", kind="owner")

    resp = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": raw_token, "full_name": "Olivia Owner", "password": "correct-horse-battery"},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["account_type"] == "admin"
    assert resp.json()["user"]["role"] == "organization_admin"

    admin = (await db_session.execute(select(Admin).where(Admin.email == "owner@example.com"))).scalar_one()
    assert admin.admin_level == AdminLevel.organization_admin
    assert admin.organization_id == org.id


async def test_accept_platform_soc_invitation_creates_admin_with_no_organization(client, db_session):
    _invitation, raw_token = await _seed_invitation(db_session, organization_id=None, email="soc@example.com", kind="platform_soc")

    resp = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": raw_token, "full_name": "Sam SOC", "password": "correct-horse-battery"},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "platform_soc_analyst"
    assert resp.json()["user"]["organization"] is None

    admin = (await db_session.execute(select(Admin).where(Admin.email == "soc@example.com"))).scalar_one()
    assert admin.admin_level == AdminLevel.platform_soc_analyst
    assert admin.organization_id is None


async def test_accept_is_single_use(client, db_session):
    org = await make_organization(db_session)
    _invitation, raw_token = await _seed_invitation(
        db_session, organization_id=org.id, email="dev@example.com", kind="member", role=UserRole.it_developer,
    )

    first = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": raw_token, "full_name": "Dana Developer", "password": "correct-horse-battery"},
    )
    assert first.status_code == 200

    second = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": raw_token, "full_name": "Dana Developer", "password": "correct-horse-battery"},
    )
    assert second.status_code == 404


async def test_accept_rejects_weak_password_and_bad_name(client, db_session):
    org = await make_organization(db_session)
    _invitation, raw_token = await _seed_invitation(
        db_session, organization_id=org.id, email="dev@example.com", kind="member", role=UserRole.it_developer,
    )

    weak_password = await client.post(
        f"{INVITATIONS_BASE}/accept", json={"token": raw_token, "full_name": "Dana Developer", "password": "short"}
    )
    assert weak_password.status_code == 400

    bad_name = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": raw_token, "full_name": "D4na!!", "password": "correct-horse-battery"},
    )
    assert bad_name.status_code == 400


async def test_accept_rejects_an_email_that_became_registered_after_the_invite_was_sent(client, db_session):
    org = await make_organization(db_session)
    _invitation, raw_token = await _seed_invitation(
        db_session, organization_id=org.id, email="dev@example.com", kind="member", role=UserRole.it_developer,
    )

    other_org = await make_organization(db_session, name="Other Org")
    db_session.add(User(
        organization_id=other_org.id, name="Already Here", email="dev@example.com",
        password_hash=hash_password("some-other-password"), role=UserRole.it_developer, is_verified=True,
    ))
    await db_session.flush()
    existing_user = (await db_session.execute(select(User).where(User.email == "dev@example.com"))).scalar_one()
    db_session.add(AccountEmail(email="dev@example.com", account_type="user", account_id=existing_user.id))
    await db_session.commit()

    resp = await client.post(
        f"{INVITATIONS_BASE}/accept",
        json={"token": raw_token, "full_name": "Dana Developer", "password": "correct-horse-battery"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "email_already_registered"
