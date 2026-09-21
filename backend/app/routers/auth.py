"""
Auth endpoints: register/verify-email/resend-verification/login/me/
forgot-password/reset-password.

The shared get_current_account/org_scope/require_admin/require_roles
dependencies other routers use now live in app/scope.py, not here --
see that module. This file only keeps the email-lookup helpers
(_account_by_email, _role_value) that its own endpoints use for
password-based login/reset, which is a different lookup path than the
token-based one in app/scope.py.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.email_utils import (
    generate_verification_code,
    send_password_reset_email,
    send_verification_email,
)
from app.models import AccountEmail, Admin, AdminLevel, Organization, PendingRegistration, User, UserRole
from app.scope import Scope, org_scope
from app.security import create_access_token, hash_password, verify_password
from app.validators import is_valid_email_format, is_valid_name_format

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Emails that are always assigned the super_admin role, no matter what role
# they pick at registration. Decided on the server so it can't be bypassed
# from the browser. Since the admins/users split, these become `admins`
# rows with admin_level=super_admin (organization_id NULL) instead of
# `users` rows -- see register()/verify_email() below.
SUPER_ADMIN_EMAILS = {
    "anchal01@gmail.com",
    "anshpatel4204@gmail.com",
    "retika03@gmail.com",
}


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    # One of the UserRole values (soc_analyst/security_manager/it_developer/
    # auditor) for a plain user, or the literal string "organization_admin"
    # to self-register as an admin of a brand-new organization. Never
    # "super_admin" -- that's assigned only via SUPER_ADMIN_EMAILS below.
    role: str = "soc_analyst"
    # Only used when role == "organization_admin" (or for a plain user, as
    # the name of their auto-created personal org, since there's no "pick
    # your org" UI yet). Defaults to "<name>'s Organization" if omitted.
    organization_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    # For a user account this is the UserRole value; for an admin account
    # this is the AdminLevel value (super_admin/organization_admin) -- kept
    # under the same field name for frontend compatibility (existing code
    # already checks role == "super_admin"). account_type disambiguates.
    role: str
    account_type: str  # "admin" | "user"


class RegisterResponse(BaseModel):
    email: str
    message: str


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



@router.post("/register", response_model=RegisterResponse)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Stores the submission as a pending registration and emails an OTP.

    No row is created in `admins` or `users` here -- that only happens in
    verify_email() once the code is confirmed, so an account someone
    never verifies leaves nothing behind but an expired pending row.
    """
    email = payload.email.strip().lower()
    name = payload.name.strip()

    if not name or not email or not payload.password:
        raise HTTPException(status_code=400, detail="Please complete all fields.")

    if not is_valid_name_format(name):
        raise HTTPException(
            status_code=400,
            detail="Name can only contain letters, spaces, apostrophes and hyphens.",
        )

    if not is_valid_email_format(email):
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid email address (letters, numbers, and . _ % + - only).",
        )

    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must contain at least 6 characters.")

    # account_emails is the cross-table ("admins" + "users") uniqueness
    # check -- a plain "does users or admins have this email" query would
    # miss whichever table it's not looking at. See AccountEmail's
    # docstring in models.py.
    existing = await db.execute(select(AccountEmail).where(AccountEmail.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="An account already exists with this email.")

    organization_name: str | None = None

    if email in SUPER_ADMIN_EMAILS:
        # Nobody can self-assign super_admin through the role field --
        # this is decided purely by the configured email allow-list.
        account_type = "admin"
        admin_level: AdminLevel | None = AdminLevel.super_admin
        role: UserRole | None = None
    elif payload.role == "organization_admin":
        account_type = "admin"
        admin_level = AdminLevel.organization_admin
        role = None
        organization_name = (payload.organization_name or "").strip() or f"{name}'s Organization"
    else:
        account_type = "user"
        admin_level = None
        try:
            role = UserRole(payload.role)
        except ValueError:
            role = UserRole.soc_analyst
        # No "pick your org" UI yet -- a self-registered plain user gets a
        # personal organization created at verify time (see verify_email).
        organization_name = (payload.organization_name or "").strip() or f"{name}'s Organization"

    code = generate_verification_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    password_hash = hash_password(payload.password)

    existing_pending = await db.execute(
        select(PendingRegistration).where(PendingRegistration.email == email)
    )
    pending = existing_pending.scalar_one_or_none()

    if pending:
        # Re-registering before verifying just refreshes the pending
        # submission (new details, new code) rather than erroring out.
        pending.name = name
        pending.password_hash = password_hash
        pending.account_type = account_type
        pending.role = role
        pending.admin_level = admin_level
        pending.organization_name = organization_name
        pending.verification_code = code
        pending.verification_code_expires_at = expires_at
    else:
        pending = PendingRegistration(
            name=name,
            email=email,
            password_hash=password_hash,
            account_type=account_type,
            role=role,
            admin_level=admin_level,
            organization_name=organization_name,
            verification_code=code,
            verification_code_expires_at=expires_at,
        )
        db.add(pending)

    await db.commit()

    try:
        await asyncio.to_thread(send_verification_email, email, name, code)
    except Exception as exc:  # SMTP misconfigured/unreachable -- don't block registration
        print(f"[SentinelX] Failed to send verification email to {email}: {exc}")

    return RegisterResponse(
        email=email,
        message="Check your email for a 6-digit verification code to finish creating your account.",
    )


@router.post("/verify-email", response_model=UserOut)
async def verify_email(payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    """
    Handles two different situations with the same code+email form:

    1. Finishing a brand-new registration (a row in pending_registrations
       exists) -- the real `admins` or `users` row gets created here,
       whichever pending.account_type points to.
    2. Re-verifying an existing account (either table) after the
       3-failed-attempts lockout below flipped is_verified back to False
       -- no new row, just clears the lockout.
    """
    email = payload.email.strip().lower()
    code = payload.code.strip()

    result = await db.execute(
        select(PendingRegistration).where(PendingRegistration.email == email)
    )
    pending = result.scalar_one_or_none()

    if pending:
        if datetime.now(timezone.utc) > pending.verification_code_expires_at:
            raise HTTPException(status_code=400, detail="This code has expired. Please request a new one.")

        if code != pending.verification_code:
            raise HTTPException(status_code=400, detail="Incorrect verification code.")

        # The code is correct -- this is the moment the real account (and,
        # for an organization_admin or plain user, its organization) is
        # created.
        if pending.account_type == "admin":
            organization_id = None
            org: Organization | None = None

            if pending.admin_level == AdminLevel.organization_admin:
                # Self-registering as an organization admin always creates
                # a brand-new organization -- there's no "join an existing
                # org" flow yet.
                org = Organization(name=pending.organization_name or f"{pending.name}'s Organization")
                db.add(org)
                await db.flush()  # need org.id before the admin row references it
                organization_id = org.id

            account: Admin | User = Admin(
                organization_id=organization_id,
                name=pending.name,
                email=pending.email,
                password_hash=pending.password_hash,
                admin_level=pending.admin_level,
                is_verified=True,
            )
            db.add(account)
            await db.flush()  # need account.id for organizations.created_by_admin_id

            if org is not None:
                org.created_by_admin_id = account.id

            account_type = "admin"
        else:
            # A plain user has no "pick your org" UI yet either -- give
            # them a personal organization, same as a self-registered
            # organization_admin.
            org = Organization(name=pending.organization_name or f"{pending.name}'s Organization")
            db.add(org)
            await db.flush()

            account = User(
                organization_id=org.id,
                name=pending.name,
                email=pending.email,
                password_hash=pending.password_hash,
                role=pending.role,
                is_verified=True,
            )
            db.add(account)
            await db.flush()  # need account.id for the AccountEmail row below
            account_type = "user"

        db.add(AccountEmail(email=pending.email, account_type=account_type, account_id=account.id))
        await db.delete(pending)
        await db.commit()
        await db.refresh(account)

        return UserOut(
            id=str(account.id), name=account.name, email=account.email,
            role=_role_value(account, account_type), account_type=account_type,
        )

    # No pending registration -- this must be an existing account
    # re-verifying (e.g. after a login lockout). Could be either table.
    account, account_type = await _account_by_email(db, email)

    if not account:
        raise HTTPException(
            status_code=404,
            detail="No pending registration found for this email. Please register again.",
        )

    if account.is_verified:
        raise HTTPException(status_code=400, detail="This account is already verified.")

    if not account.verification_code or not account.verification_code_expires_at:
        raise HTTPException(
            status_code=400,
            detail="No verification code on file. Please request a new one.",
        )

    if datetime.now(timezone.utc) > account.verification_code_expires_at:
        raise HTTPException(status_code=400, detail="This code has expired. Please request a new one.")

    if code != account.verification_code:
        raise HTTPException(status_code=400, detail="Incorrect verification code.")

    account.is_verified = True
    account.verification_code = None
    account.verification_code_expires_at = None
    account.failed_login_attempts = 0
    await db.commit()
    await db.refresh(account)

    return UserOut(
        id=str(account.id), name=account.name, email=account.email,
        role=_role_value(account, account_type), account_type=account_type,
    )


@router.post("/resend-verification")
async def resend_verification(payload: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email.strip().lower()

    result = await db.execute(
        select(PendingRegistration).where(PendingRegistration.email == email)
    )
    pending = result.scalar_one_or_none()

    if pending:
        code = generate_verification_code()
        pending.verification_code = code
        pending.verification_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        await db.commit()

        try:
            await asyncio.to_thread(send_verification_email, pending.email, pending.name, code)
        except Exception as exc:
            print(f"[SentinelX] Failed to send verification email to {pending.email}: {exc}")

        return {"message": "A new verification code has been sent."}

    # No pending registration -- this must be an existing account (either
    # table) that needs to re-verify (e.g. after a login lockout).
    account, _account_type = await _account_by_email(db, email)

    if not account:
        raise HTTPException(
            status_code=404,
            detail="No pending registration found for this email. Please register again.",
        )

    if account.is_verified:
        raise HTTPException(status_code=400, detail="This account is already verified.")

    code = generate_verification_code()
    account.verification_code = code
    account.verification_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db.commit()

    try:
        await asyncio.to_thread(send_verification_email, account.email, account.name, code)
    except Exception as exc:
        print(f"[SentinelX] Failed to send verification email to {account.email}: {exc}")

    return {"message": "A new verification code has been sent."}


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
                account.failed_login_attempts = 0
                account.is_verified = False
                code = generate_verification_code()
                account.verification_code = code
                account.verification_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
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
async def me(scope: Scope = Depends(org_scope)):
    return UserOut(
        id=str(scope.account.id),
        name=scope.account.name,
        email=scope.account.email,
        role=scope.role,
        account_type=scope.account_type,
    )


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email.strip().lower()

    account, _account_type = await _account_by_email(db, email)

    if not account:
        raise HTTPException(status_code=404, detail="No account found with this email.")

    if not account.is_verified:
        raise HTTPException(
            status_code=400,
            detail="Please verify your email before resetting your password.",
        )

    code = generate_verification_code()
    account.password_reset_code = code
    account.password_reset_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db.commit()

    try:
        await asyncio.to_thread(send_password_reset_email, account.email, account.name, code)
    except Exception as exc:
        print(f"[SentinelX] Failed to send password reset email to {account.email}: {exc}")

    return {"message": "Check your email for a 6-digit password reset code."}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email.strip().lower()
    code = payload.code.strip()

    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must contain at least 6 characters.")

    account, _account_type = await _account_by_email(db, email)

    if not account:
        raise HTTPException(status_code=404, detail="No account found with this email.")

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

