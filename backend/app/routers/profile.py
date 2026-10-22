"""
Profile, sessions, and account self-service endpoints -- P25.
Reachable by any authenticated account (super_admin, organization_admin,
soc_analyst, it_developer, security_manager, auditor).
"""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_from_scope
from app.database import get_db
from app.email_utils import generate_verification_code, send_two_factor_code_email
from app.models import Admin, Organization, Session, User
from app.scope import Scope, org_scope
from app.security import decode_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


def _parse_ua(ua: str | None) -> str:
    if not ua:
        return "Unknown Device"
    ua_lower = ua.lower()

    # Browser
    browser = "Browser"
    if "edg/" in ua_lower or "edge/" in ua_lower:
        browser = "Edge"
    elif "chrome/" in ua_lower and "chromium" not in ua_lower:
        browser = "Chrome"
    elif "firefox/" in ua_lower:
        browser = "Firefox"
    elif "safari/" in ua_lower and "chrome/" not in ua_lower:
        browser = "Safari"
    elif "postman" in ua_lower:
        browser = "Postman"
    elif "curl" in ua_lower:
        browser = "cURL"

    # OS
    platform = "Unknown OS"
    if "windows" in ua_lower:
        platform = "Windows"
    elif "macintosh" in ua_lower or "mac os" in ua_lower:
        platform = "macOS"
    elif "iphone" in ua_lower:
        platform = "iPhone"
    elif "ipad" in ua_lower:
        platform = "iPad"
    elif "android" in ua_lower:
        platform = "Android"
    elif "linux" in ua_lower:
        platform = "Linux"

    return f"{browser} on {platform}"


class ProfileOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    account_type: str
    organization_id: str | None = None
    organization_name: str | None = None
    two_factor_enabled: bool = False
    created_at: str | None = None


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)
    revoke_other_sessions: bool = True


class SessionItem(BaseModel):
    id: str
    device: str
    user_agent: str
    ip: str
    last_seen_at: str | None = None
    created_at: str | None = None
    is_current: bool = False


class SessionsResponse(BaseModel):
    sessions: list[SessionItem]


class TwoFactorToggleRequest(BaseModel):
    enable: bool
    code: str


@router.get("", response_model=ProfileOut)
async def get_profile(
    scope: Scope = Depends(org_scope),
    db: AsyncSession = Depends(get_db),
):
    account = scope.account
    org_name = None
    if scope.organization_id:
        org = await db.get(Organization, scope.organization_id)
        if org:
            org_name = org.name

    return ProfileOut(
        id=str(account.id),
        name=account.name,
        email=account.email,
        role=scope.role,
        account_type=scope.account_type,
        organization_id=str(scope.organization_id) if scope.organization_id else None,
        organization_name=org_name,
        two_factor_enabled=getattr(account, "two_factor_enabled", False),
        created_at=account.created_at.isoformat() if account.created_at else None,
    )


@router.put("", response_model=ProfileOut)
async def update_profile(
    payload: ProfileUpdateRequest,
    request: Request,
    scope: Scope = Depends(org_scope),
    db: AsyncSession = Depends(get_db),
):
    account = scope.account
    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty.")

    old_name = account.name
    account.name = new_name

    await audit_from_scope(
        db,
        scope,
        "profile.update_name",
        target_type=scope.account_type,
        target_id=account.id,
        request=request,
        organization_id=scope.organization_id,
        before={"name": old_name},
        after={"name": new_name},
    )

    await db.commit()
    await db.refresh(account)

    return await get_profile(scope, db)


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    scope: Scope = Depends(org_scope),
    db: AsyncSession = Depends(get_db),
):
    account = scope.account

    if not verify_password(payload.old_password, account.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect current password.")

    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must contain at least 6 characters.")

    if payload.old_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from your current password.")

    account.password_hash = hash_password(payload.new_password)

    # If requested, revoke other sessions
    current_sid_uuid = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        try:
            tok_data = decode_access_token(token)
            sid = tok_data.get("sid")
            if sid:
                current_sid_uuid = uuid.UUID(sid)
        except Exception:
            pass

    if payload.revoke_other_sessions:
        now = datetime.now(timezone.utc)
        stmt = (
            select(Session)
            .where(
                Session.account_id == account.id,
                Session.account_type == scope.account_type,
                Session.revoked_at.is_(None),
            )
        )
        if current_sid_uuid:
            stmt = stmt.where(Session.id != current_sid_uuid)
        other_sessions = (await db.execute(stmt)).scalars().all()
        for s in other_sessions:
            s.revoked_at = now

    await audit_from_scope(
        db,
        scope,
        "profile.change_password",
        target_type=scope.account_type,
        target_id=account.id,
        request=request,
        organization_id=scope.organization_id,
        after={"revoked_other_sessions": payload.revoke_other_sessions},
    )

    await db.commit()

    return {"message": "Password changed successfully."}


@router.get("/sessions", response_model=SessionsResponse)
async def list_sessions(
    authorization: str | None = Header(default=None),
    scope: Scope = Depends(org_scope),
    db: AsyncSession = Depends(get_db),
):
    current_sid_uuid = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        try:
            tok_data = decode_access_token(token)
            sid = tok_data.get("sid")
            if sid:
                current_sid_uuid = uuid.UUID(sid)
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(Session)
            .where(
                Session.account_id == scope.account.id,
                Session.account_type == scope.account_type,
                Session.revoked_at.is_(None),
                Session.expires_at > now,
            )
            .order_by(Session.created_at.desc())
        )
    ).scalars().all()

    items = [
        SessionItem(
            id=str(s.id),
            device=_parse_ua(s.user_agent),
            user_agent=s.user_agent or "Unknown",
            ip=s.ip or "Unknown",
            last_seen_at=(s.last_seen_at or s.created_at).isoformat(),
            created_at=s.created_at.isoformat() if s.created_at else None,
            is_current=(current_sid_uuid is not None and s.id == current_sid_uuid),
        )
        for s in rows
    ]

    return SessionsResponse(sessions=items)


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    scope: Scope = Depends(org_scope),
    db: AsyncSession = Depends(get_db),
):
    sess = (
        await db.execute(
            select(Session).where(
                Session.id == session_id,
                Session.account_id == scope.account.id,
                Session.account_type == scope.account_type,
            )
        )
    ).scalar_one_or_none()

    if not sess:
        raise HTTPException(status_code=404, detail="Session not found.")

    if sess.revoked_at is not None:
        return {"id": str(sess.id), "revoked": True}

    sess.revoked_at = datetime.now(timezone.utc)

    await audit_from_scope(
        db,
        scope,
        "session.revoke",
        target_type="session",
        target_id=sess.id,
        request=request,
        organization_id=scope.organization_id,
        after={"session_id": str(sess.id)},
    )

    await db.commit()
    return {"id": str(sess.id), "revoked": True}


@router.post("/sessions/revoke-all")
async def revoke_all_sessions(
    request: Request,
    keep_current: bool = True,
    authorization: str | None = Header(default=None),
    scope: Scope = Depends(org_scope),
    db: AsyncSession = Depends(get_db),
):
    current_sid_uuid = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        try:
            tok_data = decode_access_token(token)
            sid = tok_data.get("sid")
            if sid:
                current_sid_uuid = uuid.UUID(sid)
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    stmt = select(Session).where(
        Session.account_id == scope.account.id,
        Session.account_type == scope.account_type,
        Session.revoked_at.is_(None),
    )
    if keep_current and current_sid_uuid:
        stmt = stmt.where(Session.id != current_sid_uuid)

    sessions = (await db.execute(stmt)).scalars().all()
    for s in sessions:
        s.revoked_at = now

    await audit_from_scope(
        db,
        scope,
        "session.revoke_all",
        target_type="session",
        target_id=scope.account.id,
        request=request,
        organization_id=scope.organization_id,
        after={"revoked_count": len(sessions), "keep_current": keep_current},
    )

    await db.commit()
    return {"revoked_count": len(sessions), "keep_current": keep_current}


@router.post("/2fa/send-code")
async def send_2fa_setup_code(
    scope: Scope = Depends(org_scope),
    db: AsyncSession = Depends(get_db),
):
    account = scope.account
    code = generate_verification_code()
    account.two_factor_code = code
    account.two_factor_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db.commit()

    try:
        await asyncio.to_thread(send_two_factor_code_email, account.email, account.name, code)
    except Exception as exc:
        print(f"[SentinelX] Failed to send 2FA setup email to {account.email}: {exc}")

    return {"message": f"A verification code has been sent to {account.email}."}


@router.post("/2fa/toggle")
async def toggle_2fa(
    payload: TwoFactorToggleRequest,
    request: Request,
    scope: Scope = Depends(org_scope),
    db: AsyncSession = Depends(get_db),
):
    account = scope.account
    now = datetime.now(timezone.utc)

    if not account.two_factor_code or not account.two_factor_code_expires_at:
        raise HTTPException(status_code=400, detail="No verification code on file. Please request a new code.")

    if now > account.two_factor_code_expires_at:
        raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new code.")

    if payload.code.strip() != account.two_factor_code:
        raise HTTPException(status_code=400, detail="Incorrect verification code.")

    account.two_factor_code = None
    account.two_factor_code_expires_at = None
    account.two_factor_enabled = payload.enable

    await audit_from_scope(
        db,
        scope,
        "profile.2fa_toggle",
        target_type=scope.account_type,
        target_id=account.id,
        request=request,
        organization_id=scope.organization_id,
        after={"two_factor_enabled": payload.enable},
    )

    await db.commit()
    await db.refresh(account)

    action = "enabled" if payload.enable else "disabled"
    return {
        "two_factor_enabled": account.two_factor_enabled,
        "message": f"Two-factor authentication has been {action}.",
    }
