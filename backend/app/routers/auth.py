"""
Auth endpoints: verify-email/resend-verification/login/me/forgot-password/
reset-password.

SentinelX is invite-only (see docs/DECISIONS.md): accounts are created
exclusively by accepting an invitation (app/routers/invitations.py) or by
the one-time `python -m app.create_super_admin` command. There is no
public registration.

verify-email and resend-verification exist for exactly one flow: the
3-wrong-passwords lockout. Login flips is_verified to False, emails a
10-minute one-time code, and the account (admin or user, either table)
must verify with that code before it can log in again.

Every endpoint here that takes an email answers unknown/known emails with
the same generic response shapes -- none of them reveal whether an
address has an account. verify/resend are additionally rate-limited
(per-email resend throttle + capped verify attempts) since they are
anonymous.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import get_effective_access
from app.database import get_db
from app.email_utils import (
    generate_verification_code,
    send_password_reset_email,
    send_verification_email,
)
from app.models import (
    AccountEmail,
    Admin,
    Organization,
    OrganizationStatus,
    User,
)
from app.scope import Scope, org_scope
from app.security import create_access_token, hash_password, verify_password
from app.validators import is_valid_email_format

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

CODE_TTL_MINUTES = 10
RESEND_THROTTLE_SECONDS = 60
MAX_VERIFY_ATTEMPTS = 5

# Anonymous, in-memory, best-effort throttles -- enough to blunt code
# guessing and email-bombing from this surface without introducing a
# dependency. Codes are 6 random digits, single-use and short-lived, so
# the real brute-force defense is the code itself; this only stops a
# client from hammering resend/verify in a tight loop.
_resend_last_sent: dict[str, float] = {}
_verify_attempts: dict[str, tuple[int, float]] = {}


class LoginRequest(BaseModel):
    email: str
    password: str


class OrganizationSummaryOut(BaseModel):
    id: str
    name: str
    status: str
    soc_mode: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    # For a user account this is the UserRole value; for an admin account
    # this is the AdminLevel value (super_admin/organization_admin/
    # platform_soc_analyst) -- kept under the same field name for frontend
    # compatibility (existing code already checks role == "super_admin").
    # account_type disambiguates.
    role: str
    account_type: str  # "admin" | "user"
    # Only set for an organization_admin owner or a `users` account --
    # None for super_admin/platform_soc_analyst, who aren't scoped to a
    # single organization. The frontend builds its navigation from
    # effective_modules, per docs/API_CONTRACT.md.
    organization: OrganizationSummaryOut | None = None
    effective_modules: dict[str, str] | None = None


class VerifyEmailRequest(BaseModel):
    email: str
    code: str


class ResendVerificationRequest(BaseModel):
    email: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# The ONE generic message every unknown-email / no-code-on-file /
# wrong-code answer on the anonymous verify/resend surface uses. Deliberately
# identical across every failure shape so an attacker probing emails learns
# nothing -- same principle as login's generic invalid-credentials message
# (docs/DECISIONS.md).
_GENERIC_CODE_RESPONSE = {"message": "If a verification code was sent to this email, it is in your inbox."}
_GENERIC_CODE_400 = HTTPException(status_code=400, detail=_GENERIC_CODE_RESPONSE["message"])


async def _account_by_email(db: AsyncSession, email: str) -> tuple[Admin | User | None, str | None]:
    """
    Looks up the single account (admin or user) that owns `email`, via
    account_emails -- the table that enforces "one email, one account,
    whichever table it's in" (see AccountEmail's docstring in models.py).
    Returns (account, account_type) or (None, None).
    """
    mapping = (await db.execute(select(AccountEmail).where(AccountEmail.email == email))).scalar_one_or_none()
    if not mapping:
        return None, None

    model = Admin if mapping.account_type == "admin" else User
    account = (await db.execute(select(model).where(model.id == mapping.account_id))).scalar_one_or_none()
    return account, mapping.account_type


def _role_value(account: Admin | User, account_type: str) -> str:
    return account.admin_level.value if account_type == "admin" else account.role.value


def _throttled(key: str, table: dict[str, float], seconds: int) -> bool:
    """True when `key` fired within the last `seconds` (records this fire)."""
    now = time.monotonic()
    last = table.get(key)
    table[key] = now
    return last is not None and (now - last) < seconds


def _verify_attempts_exhausted(email: str) -> bool:
    """Capped verify attempts per email within a 10-minute window."""
    now = time.monotonic()
    count, window_start = _verify_attempts.get(email, (0, now))
    if now - window_start > CODE_TTL_MINUTES * 60:
        count, window_start = 0, now
    count += 1
    _verify_attempts[email] = (count, window_start)
    return count > MAX_VERIFY_ATTEMPTS


@router.post("/verify-email", response_model=UserOut)
async def verify_email(payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    """
    Re-verifies an existing account (either table) after the
    3-failed-attempts lockout in login() flipped is_verified back to
    False: checks the emailed one-time code and clears the lockout.

    This is deliberately the ONLY thing this endpoint does now -- it no
    longer creates accounts (invite-only; see the module docstring).
    Unknown emails, verified accounts, missing codes and wrong codes all
    answer with the same generic 400 so nothing here reveals whether an
    email exists.
    """
    email = payload.email.strip().lower()
    code = payload.code.strip()

    if _verify_attempts_exhausted(email):
        raise _GENERIC_CODE_400

    account, account_type = await _account_by_email(db, email)

    # Generic on every failure path -- same response for a known and an
    # unknown email, for a wrong code and a missing one.
    if not account:
        raise _GENERIC_CODE_400
    if account.is_verified:
        raise _GENERIC_CODE_400
    if not account.verification_code or not account.verification_code_expires_at:
        raise _GENERIC_CODE_400
    if datetime.now(timezone.utc) > account.verification_code_expires_at:
        raise _GENERIC_CODE_400
    if code != account.verification_code:
        raise _GENERIC_CODE_400

    account.is_verified = True
    account.verification_code = None
    account.verification_code_expires_at = None
    account.failed_login_attempts = 0
    _verify_attempts.pop(email, None)
    await db.commit()
    await db.refresh(account)

    return UserOut(
        id=str(account.id), name=account.name, email=account.email,
        role=_role_value(account, account_type), account_type=account_type,
    )


@router.post("/resend-verification")
async def resend_verification(payload: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    """
    Emails a fresh 10-minute code to a locked (is_verified=False)
    account -- the resend half of the lockout flow. Throttled per email
    and deliberately silent about whether the email has an account:
    every outcome a client can observe is the same generic message.
    """
    email = payload.email.strip().lower()

    if _throttled(email, _resend_last_sent, RESEND_THROTTLE_SECONDS):
        # Identical body to the success path -- the throttle itself must
        # not be observable (and definitely must not confirm existence).
        return _GENERIC_CODE_RESPONSE

    account, _account_type = await _account_by_email(db, email)

    if account and not account.is_verified:
        code = generate_verification_code()
        account.verification_code = code
        account.verification_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MINUTES)
        await db.commit()

        try:
            await asyncio.to_thread(send_verification_email, account.email, account.name, code)
        except Exception as exc:
            print(f"[SentinelX] Failed to send verification email to {account.email}: {exc}")

    return _GENERIC_CODE_RESPONSE


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email.strip().lower()

    if not is_valid_email_format(email):
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid email address (letters, numbers, and . _ % + - only).",
        )

    account, account_type = await _account_by_email(db, email)

    if not account or not verify_password(payload.password, account.password_hash):
        # Only track wrong-password attempts against a real, currently
        # loggable-into account -- an unverified/deactivated account is
        # already blocked below, so there's nothing to lock further.
        if account and account.is_active and account.is_verified:
            account.failed_login_attempts += 1

            if account.failed_login_attempts >= 3:
                # The lockout: counter resets, the account is flipped to
                # unverified, and a fresh 10-minute one-time code goes
                # out -- the account must verify before logging in again.
                account.failed_login_attempts = 0
                account.is_verified = False
                code = generate_verification_code()
                account.verification_code = code
                account.verification_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MINUTES)
                await db.commit()

                try:
                    await asyncio.to_thread(send_verification_email, account.email, account.name, code)
                except Exception as exc:
                    print(f"[SentinelX] Failed to send verification email to {account.email}: {exc}")

                raise HTTPException(
                    status_code=403,
                    detail=(
                        "Too many failed login attempts. We've emailed a new "
                        "verification code -- please verify your account before "
                        "logging in again."
                    ),
                )

            await db.commit()

        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not account.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated.")

    if not account.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in.")

    # Organization status rules: suspended/archived block login outright.
    # Only relevant for an organization_admin or a `users` account --
    # super_admin/platform_soc_analyst aren't scoped to one organization.
    organization: Organization | None = None
    if account_type == "admin" or account_type == "user":
        organization = await db.get(Organization, account.organization_id) if account.organization_id else None

    if organization is not None:
        if organization.status == OrganizationStatus.suspended:
            raise HTTPException(
                status_code=401,
                detail={"code": "organization_suspended", "message": "Your organization has been suspended."},
            )
        if organization.status == OrganizationStatus.archived:
            raise HTTPException(
                status_code=401,
                detail={"code": "organization_archived", "message": "Your organization has been archived."},
            )

    if account.failed_login_attempts:
        # Clear a stale count (e.g. 1-2 prior misses) on a successful login.
        account.failed_login_attempts = 0

    account.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    role_value = _role_value(account, account_type)

    token = create_access_token({
        "sub": str(account.id),
        "account_type": account_type,
        "role": role_value,
    })

    return LoginResponse(
        access_token=token,
        user=UserOut(
            id=str(account.id), name=account.name, email=account.email,
            role=role_value, account_type=account_type,
        ),
    )


@router.get("/me", response_model=UserOut)
async def me(scope: Scope = Depends(org_scope), db: AsyncSession = Depends(get_db)):
    """
    Deliberately does NOT depend on require_active_organization -- this
    is one of the two endpoints (with the owner's GET /organization
    overview) that must keep working for a suspended/archived
    organization, so the frontend has something to read in order to
    show the right screen at all.
    """
    organization_out = None
    effective_modules = None

    if scope.organization_id is not None:
        organization = await db.get(Organization, scope.organization_id)
        if organization is not None:
            organization_out = OrganizationSummaryOut(
                id=str(organization.id),
                name=organization.name,
                status=organization.status.value,
                soc_mode=organization.soc_mode.value,
            )
            access = await get_effective_access(db, scope.account, organization)
            effective_modules = access["modules"]

    return UserOut(
        id=str(scope.account.id),
        name=scope.account.name,
        email=scope.account.email,
        role=scope.role,
        account_type=scope.account_type,
        organization=organization_out,
        effective_modules=effective_modules,
    )


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """
    Emails a 10-minute password-reset code. Deliberately answers a
    known and an unknown email with the same generic message -- the old
    explicit 404 "No account found with this email" enabled email
    enumeration on an anonymous endpoint.
    """
    email = payload.email.strip().lower()

    account, _account_type = await _account_by_email(db, email)

    if account and account.is_verified:
        code = generate_verification_code()
        account.password_reset_code = code
        account.password_reset_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MINUTES)
        await db.commit()

        try:
            await asyncio.to_thread(send_password_reset_email, account.email, account.name, code)
        except Exception as exc:
            print(f"[SentinelX] Failed to send password reset email to {account.email}: {exc}")

    return {"message": "If that email has an account, a password reset code is in your inbox."}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email.strip().lower()
    code = payload.code.strip()

    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must contain at least 6 characters.")

    account, _account_type = await _account_by_email(db, email)

    if not account:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")

    if not account.password_reset_code or not account.password_reset_code_expires_at:
        raise HTTPException(
            status_code=400,
            detail="No password reset code on file. Please request a new one.",
        )

    if datetime.now(timezone.utc) > account.password_reset_code_expires_at:
        raise HTTPException(status_code=400, detail="This code has expired. Please request a new one.")

    if code != account.password_reset_code:
        raise HTTPException(status_code=400, detail="Incorrect verification code.")

    account.password_hash = hash_password(payload.new_password)
    account.password_reset_code = None
    account.password_reset_code_expires_at = None
    account.failed_login_attempts = 0
    await db.commit()

    return {"message": "Password reset. You can now log in with your new password."}
