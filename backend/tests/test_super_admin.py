"""
python -m app.create_super_admin -- the one-time bootstrap command for
the first super_admin (invite-only platform, docs/DECISIONS.md: the
platform's first account is created server-side, never through a public
page or endpoint).

Covered at two levels: the transaction itself (_create against the test
session) and the non-interactive SEED_SUPER_ADMIN_* entry point
(_main with a test-bound session factory). The password must never
appear in any output.
"""

import pytest
from sqlalchemy import select

from app.create_super_admin import _create, _main
from app.models import AccountEmail, ActorType, Admin, AdminLevel, AuditLog
from app.security import verify_password
from tests.conftest import TestSessionLocal

PASSWORD = "correct-horse-battery"


async def test_creates_the_first_super_admin_with_account_email_and_audit(db_session):
    admin = await _create(db_session, email="root@example.com", name="Root", password=PASSWORD)

    assert admin.admin_level == AdminLevel.super_admin
    assert admin.organization_id is None
    assert admin.is_active is True
    assert admin.is_verified is True
    assert verify_password(PASSWORD, admin.password_hash)

    # The cross-table email reservation, written in the same transaction.
    mapping = (
        await db_session.execute(select(AccountEmail).where(AccountEmail.email == "root@example.com"))
    ).scalar_one()
    assert mapping.account_type == "admin"
    assert mapping.account_id == admin.id

    # A system-actor audit entry records the bootstrap.
    entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "super_admin.bootstrap"))
    ).scalar_one()
    assert entry.actor_type == ActorType.system
    assert entry.target_id == admin.id


async def test_refuses_an_email_that_already_has_an_account(db_session, capsys):
    await _create(db_session, email="root@example.com", name="Root", password=PASSWORD)

    with pytest.raises(SystemExit) as exc:
        await _create(db_session, email="root@example.com", name="Again", password=PASSWORD)
    assert exc.value.code == 1

    admins = (await db_session.execute(select(Admin).where(Admin.email == "root@example.com"))).scalars().all()
    assert len(admins) == 1, "the refusal must not have created anything"


async def test_refuses_a_second_super_admin_on_a_different_email(db_session):
    await _create(db_session, email="root@example.com", name="Root", password=PASSWORD)

    with pytest.raises(SystemExit) as exc:
        await _create(db_session, email="second@example.com", name="Second", password=PASSWORD)
    assert exc.value.code == 1

    super_admins = (
        await db_session.execute(select(Admin).where(Admin.admin_level == AdminLevel.super_admin))
    ).scalars().all()
    assert len(super_admins) == 1


async def test_create_never_prints_the_password(db_session, capsys):
    await _create(db_session, email="root@example.com", name="Root", password=PASSWORD)

    captured = capsys.readouterr()
    everything = captured.out + captured.err
    assert PASSWORD not in everything


async def test_non_interactive_entry_point_creates_the_account(db_session, monkeypatch, capsys):
    monkeypatch.setattr("app.database.AsyncSessionLocal", TestSessionLocal)
    monkeypatch.setenv("SEED_SUPER_ADMIN_EMAIL", "envroot@example.com")
    monkeypatch.setenv("SEED_SUPER_ADMIN_PASSWORD", "env-secret-password")
    monkeypatch.setenv("SEED_SUPER_ADMIN_NAME", "Env Root")

    await _main()

    captured = capsys.readouterr()
    assert "envroot@example.com" in captured.out
    assert "env-secret-password" not in captured.out + captured.err

    admin = (await db_session.execute(select(Admin).where(Admin.email == "envroot@example.com"))).scalar_one()
    assert admin.admin_level == AdminLevel.super_admin
    assert verify_password("env-secret-password", admin.password_hash)


async def test_non_interactive_entry_point_refuses_a_duplicate(db_session, monkeypatch):
    monkeypatch.setattr("app.database.AsyncSessionLocal", TestSessionLocal)
    monkeypatch.setenv("SEED_SUPER_ADMIN_EMAIL", "envroot2@example.com")
    monkeypatch.setenv("SEED_SUPER_ADMIN_PASSWORD", "env-secret-password")

    await _main()

    monkeypatch.setenv("SEED_SUPER_ADMIN_EMAIL", "envroot2@example.com")
    monkeypatch.setenv("SEED_SUPER_ADMIN_PASSWORD", "another-secret")

    with pytest.raises(SystemExit) as exc:
        await _main()
    assert exc.value.code == 1
