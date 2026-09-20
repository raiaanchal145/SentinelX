import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.email_utils import generate_verification_code, send_verification_email
from app.models import Organization, PendingRegistration, User, UserRole
from app.security import create_access_token, decode_access_token, hash_password, verify_password
from app.validators import is_valid_email_format, is_valid_name_format

app = FastAPI(title="SentinelX API")

# Allows the React dev server (Vite, running on port 5173) to call this API
# directly from the browser during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    """Basic hardening headers applied to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# Emails that are always assigned the super_admin role, no matter what role
# they pick at registration. Decided on the server so it can't be bypassed
# from the browser.
SUPER_ADMIN_EMAILS = {
    "anchal01@gmail.com",
    "anshpatel4204@gmail.com",
    "retika03@gmail.com",
}


@app.get("/api/v1/health")
async def health(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    return {"status": "ok", "db": result.scalar() == 1}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str = "soc_analyst"


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str


class RegisterResponse(BaseModel):
    email: str
    message: str


class VerifyEmailRequest(BaseModel):
    email: str
    code: str


class ResendVerificationRequest(BaseModel):
    email: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated.")

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")

    return user


@app.post("/api/v1/auth/register", response_model=RegisterResponse)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Stores the submission as a pending registration and emails an OTP.

    No row is created in `users` here -- that only happens in
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

    existing_user = await db.execute(select(User).where(User.email == email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="An account already exists with this email.")

    if email in SUPER_ADMIN_EMAILS:
        role = UserRole.super_admin
    else:
        try:
            role = UserRole(payload.role)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid account role.")
        if role == UserRole.super_admin:
            # Nobody can self-assign super_admin through the role dropdown.
            role = UserRole.soc_analyst

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
        pending.role = role
        pending.verification_code = code
        pending.verification_code_expires_at = expires_at
    else:
        pending = PendingRegistration(
            name=name,
            email=email,
            password_hash=password_hash,
            role=role,
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


@app.post("/api/v1/auth/verify-email", response_model=UserOut)
async def verify_email(payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email.strip().lower()
    code = payload.code.strip()

    result = await db.execute(
        select(PendingRegistration).where(PendingRegistration.email == email)
    )
    pending = result.scalar_one_or_none()

    if not pending:
        existing_user = await db.execute(select(User).where(User.email == email))
        if existing_user.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="This account is already verified.")
        raise HTTPException(
            status_code=404,
            detail="No pending registration found for this email. Please register again.",
        )

    if datetime.now(timezone.utc) > pending.verification_code_expires_at:
        raise HTTPException(status_code=400, detail="This code has expired. Please request a new one.")

    if code != pending.verification_code:
        raise HTTPException(status_code=400, detail="Incorrect verification code.")

    # The code is correct -- this is the moment the real account is created.
    user = User(
        name=pending.name,
        email=pending.email,
        password_hash=pending.password_hash,
        role=pending.role,
        is_verified=True,
    )
    db.add(user)
    await db.delete(pending)
    await db.commit()
    await db.refresh(user)

    return UserOut(id=str(user.id), name=user.name, email=user.email, role=user.role.value)


@app.post("/api/v1/auth/resend-verification")
async def resend_verification(payload: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email.strip().lower()

    result = await db.execute(
        select(PendingRegistration).where(PendingRegistration.email == email)
    )
    pending = result.scalar_one_or_none()

    if not pending:
        existing_user = await db.execute(select(User).where(User.email == email))
        if existing_user.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="This account is already verified.")
        raise HTTPException(
            status_code=404,
            detail="No pending registration found for this email. Please register again.",
        )

    code = generate_verification_code()
    pending.verification_code = code
    pending.verification_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db.commit()

    try:
        await asyncio.to_thread(send_verification_email, pending.email, pending.name, code)
    except Exception as exc:
        print(f"[SentinelX] Failed to send verification email to {pending.email}: {exc}")

    return {"message": "A new verification code has been sent."}


@app.post("/api/v1/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email.strip().lower()

    if not is_valid_email_format(email):
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid email address (letters, numbers, and . _ % + - only).",
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated.")

    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in.")

    token = create_access_token({"sub": str(user.id), "role": user.role.value})

    return LoginResponse(
        access_token=token,
        user=UserOut(id=str(user.id), name=user.name, email=user.email, role=user.role.value),
    )


@app.get("/api/v1/auth/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=str(current_user.id),
        name=current_user.name,
        email=current_user.email,
        role=current_user.role.value,
    )


# ---------------------------------------------------------------------------
# Organizations (used earlier to prove the DB connection works end to end)
# ---------------------------------------------------------------------------


class OrganizationCreate(BaseModel):
    name: str
    industry: str | None = None
    environment: str | None = None
    timezone: str | None = None


class OrganizationOut(BaseModel):
    id: str
    name: str
    industry: str | None
    environment: str | None
    timezone: str | None
    status: str

    class Config:
        from_attributes = True


@app.post("/api/v1/organizations", response_model=OrganizationOut)
async def create_organization(payload: OrganizationCreate, db: AsyncSession = Depends(get_db)):
    org = Organization(
        name=payload.name,
        industry=payload.industry,
        environment=payload.environment,
        timezone=payload.timezone,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return OrganizationOut(
        id=str(org.id),
        name=org.name,
        industry=org.industry,
        environment=org.environment,
        timezone=org.timezone,
        status=org.status,
    )


@app.get("/api/v1/organizations")
async def list_organizations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text(
            "SELECT id, name, industry, environment, timezone, status, created_at "
            "FROM organizations ORDER BY created_at DESC"
        )
    )
    rows = result.mappings().all()
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "industry": r["industry"],
            "environment": r["environment"],
            "timezone": r["timezone"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------


@app.get("/api/v1/stats/overview")
async def stats_overview(db: AsyncSession = Depends(get_db)):
    """Real counts pulled straight from the database, for the dashboard stat cards.

    Only users/assets/organizations exist as real tables today. Incidents,
    alerts and events aren't modeled yet, so those dashboard cards stay at 0
    until that schema is added -- this endpoint doesn't fabricate numbers for
    them.
    """
    users_count = (await db.execute(text("SELECT COUNT(*) FROM users"))).scalar()
    assets_count = (await db.execute(text("SELECT COUNT(*) FROM assets"))).scalar()
    organizations_count = (await db.execute(text("SELECT COUNT(*) FROM organizations"))).scalar()

    return {
        "users": users_count,
        "assets": assets_count,
        "organizations": organizations_count,
    }
