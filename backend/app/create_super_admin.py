"""
One-time, server-side command that creates the FIRST super_admin.

    python -m app.create_super_admin

SentinelX is invite-only and has no public registration (see
docs/DECISIONS.md); the platform's bootstrap account is created here,
on the server, never through a public page or endpoint. Run it once on
a fresh deployment; every later platform SOC analyst and organization
owner is created through the invitation flow by that super_admin.

Behavior:
- Interactive: prompts for email, full name and password (getpass -- the
  password is never on the command line, in argv, or printed back).
- Non-interactive (CI/dev): reads SEED_SUPER_ADMIN_EMAIL /
  SEED_SUPER_ADMIN_PASSWORD / SEED_SUPER_ADMIN_NAME from the
  environment. The password variable is popped from os.environ after
  reading so it can't linger longer than necessary.
- Same password policy as every other account-creation path (minimum 6
  characters; the email/name allow-list validators).
- Writes the admins row (admin_level=super_admin, organization_id NULL,
  is_verified, is_active) and the account_emails row in ONE transaction.
- Refuses to run twice for the same email (account_emails is the
  cross-table uniqueness authority) and refuses if the platform already
  has an active super_admin and you pass a different email -- "the first
  super_admin" is a bootstrap step, not a general admin factory.
- Writes an audit entry with actor_type=system. Never prints the
  password; the summary output shows the email and the account id only.
"""

import asyncio
import getpass
import os
import sys

from sqlalchemy import func, select

from app.models import AccountEmail, ActorType, Admin, AdminLevel, AuditLog
from app.security import hash_password
from app.validators import is_valid_email_format, is_valid_name_format

MIN_PASSWORD_LENGTH = 6


def _prompt_email() -> str:
    raw = input("Super admin email: ").strip().lower()
    if not is_valid_email_format(raw):
        print("Error: please enter a valid email address (letters, numbers, and . _ % + - only).")
        sys.exit(2)
    return raw


def _prompt_name() -> str:
    raw = input("Full name: ").strip()
    if not raw or not is_valid_name_format(raw):
        print("Error: name can only contain letters, spaces, apostrophes and hyphens.")
        sys.exit(2)
    return raw


def _prompt_password() -> str:
    raw = getpass.getpass("Password (input hidden): ")
    if len(raw) < MIN_PASSWORD_LENGTH:
        print(f"Error: password must contain at least {MIN_PASSWORD_LENGTH} characters.")
        sys.exit(2)
    confirm = getpass.getpass("Confirm password: ")
    if raw != confirm:
        print("Error: passwords do not match.")
        sys.exit(2)
    return raw


async def _create(db, *, email: str, name: str, password: str) -> Admin:
    """
    All writes in one transaction: the admins row, the account_emails
    reservation (the cross-table uniqueness check that makes "one email,
    one account" race-safe), and the system audit entry.
    """
    existing = (
        await db.execute(select(AccountEmail).where(AccountEmail.email == email))
    ).scalar_one_or_none()
    if existing:
        print(f"Error: an account already exists with the email {email}. Nothing was created.")
        sys.exit(1)

    super_admins = (
        await db.execute(
            select(func.count(Admin.id)).where(
                Admin.admin_level == AdminLevel.super_admin, Admin.is_active.is_(True)
            )
        )
    ).scalar() or 0
    if super_admins > 0:
        print(
            "Error: an active super_admin already exists. This command bootstraps the FIRST "
            "super_admin only; manage further platform accounts through the app."
        )
        sys.exit(1)

    admin = Admin(
        organization_id=None,
        name=name,
        email=email,
        password_hash=hash_password(password),
        admin_level=AdminLevel.super_admin,
        is_active=True,
        is_verified=True,
    )
    db.add(admin)
    await db.flush()

    db.add(AccountEmail(email=email, account_type="admin", account_id=admin.id))

    db.add(
        AuditLog(
            organization_id=None,
            actor_type=ActorType.system,
            actor_id=None,
            action="super_admin.bootstrap",
            target_type="admin",
            target_id=admin.id,
            details={"created_via": "create_super_admin_command"},
        )
    )

    await db.commit()
    await db.refresh(admin)
    return admin


async def _main() -> None:
    env_email = os.environ.pop("SEED_SUPER_ADMIN_EMAIL", None)
    env_password = os.environ.pop("SEED_SUPER_ADMIN_PASSWORD", None)
    env_name = os.environ.pop("SEED_SUPER_ADMIN_NAME", None)

    if env_email and env_password:
        email = env_email.strip().lower()
        name = (env_name or "Platform Administrator").strip()
        if not is_valid_email_format(email):
            print("Error: SEED_SUPER_ADMIN_EMAIL is not a valid email address.")
            sys.exit(2)
        if len(env_password) < MIN_PASSWORD_LENGTH:
            print(f"Error: SEED_SUPER_ADMIN_PASSWORD must contain at least {MIN_PASSWORD_LENGTH} characters.")
            sys.exit(2)
        print(f"Non-interactive mode: creating super_admin for {email} from SEED_SUPER_ADMIN_* variables.")
    elif env_email or env_password:
        print("Error: SEED_SUPER_ADMIN_EMAIL and SEED_SUPER_ADMIN_PASSWORD must be set together.")
        sys.exit(2)
    else:
        email = _prompt_email()
        name = _prompt_name()
        password = _prompt_password()

    # Imported here so importing this module (e.g. in tests, which call
    # _create directly against their own session) never opens the real
    # configured database engine.
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        admin = await _create(db, email=email, name=name, password=password)
        print("")
        print("Super admin created.")
        print(f"  email: {admin.email}")
        print(f"  id:    {admin.id}")
        print("Sign in at the usual login page with this email and the password you set.")


if __name__ == "__main__":
    asyncio.run(_main())
