"""
Public invitation endpoints -- no authentication. GET validates a token
without revealing anything about *why* it's invalid (unknown, expired
and revoked all look identical from here); POST is the only way to
create a member account, a platform-created owner account, or a
platform_soc_analyst account.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit_log
from app.database import get_db
from app.models import AccountEmail, ActorType, Admin, AdminLevel, Invitation, Organization, User
from app.routers.auth import OrganizationSummaryOut, UserOut
from app.security import create_access_token, hash_invitation_token, hash_password
from app.validators import is_valid_name_format

router = APIRouter(prefix="/api/v1/invitations", tags=["invitations"])

NOT_FOUND = HTTPException(status_code=404, detail={"code": "invitation_not_found", "message": "This invitation link is invalid or has expired."})


class AcceptInvitationRequest(BaseModel):
    token: str
    full_name: str
    password: str


class AcceptInvitationResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


async def _load_valid_invitation(db: AsyncSession, token: str) -> Invitation:
    token_hash = hash_invitation_token(token)
    invitation = (await db.execute(select(Invitation).where(Invitation.token_hash == token_hash))).scalar_one_or_none()

    if invitation is None or invitation.status != "pending":
        raise NOT_FOUND

    # "expires automatically on read" -- a stale pending row is flipped
    # to expired the moment anyone tries to use it, not just at accept.
    if invitation.expires_at <= datetime.now(timezone.utc):
        invitation.status = "expired"
        await db.commit()
        raise NOT_FOUND

    return invitation


@router.get("/{token}")
async def validate_invitation(token: str, db: AsyncSession = Depends(get_db)):
    invitation = await _load_valid_invitation(db, token)

    organization_name = None
    if invitation.organization_id is not None:
        organization = await db.get(Organization, invitation.organization_id)
        organization_name = organization.name if organization else None

    return {
        "kind": invitation.kind,
        "organization_name": organization_name,
        "role": invitation.role.value if invitation.role else None,
        "email": invitation.email,
        "expires_at": invitation.expires_at.isoformat(),
    }


@router.post("/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(payload: AcceptInvitationRequest, request: Request, db: AsyncSession = Depends(get_db)):
    invitation = await _load_valid_invitation(db, payload.token)

    full_name = payload.full_name.strip()
    if not full_name or not is_valid_name_format(full_name):
        raise HTTPException(status_code=400, detail="Name can only contain letters, spaces, apostrophes and hyphens.")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must contain at least 6 characters.")

    existing_email = (await db.execute(select(AccountEmail).where(AccountEmail.email == invitation.email))).scalar_one_or_none()
    if existing_email:
        raise HTTPException(status_code=409, detail={"code": "email_already_registered", "message": "An account already exists with this email."})

    password_hash = hash_password(payload.password)

    if invitation.kind == "owner":
        account: Admin | User = Admin(
            organization_id=invitation.organization_id, name=full_name, email=invitation.email,
            password_hash=password_hash, admin_level=AdminLevel.organization_admin, is_verified=True,
        )
        account_type = "admin"
    elif invitation.kind == "platform_soc":
        account = Admin(
            organization_id=None, name=full_name, email=invitation.email,
            password_hash=password_hash, admin_level=AdminLevel.platform_soc_analyst, is_verified=True,
        )
        account_type = "admin"
    else:  # "member"
        account = User(
            organization_id=invitation.organization_id, name=full_name, email=invitation.email,
            password_hash=password_hash, role=invitation.role, team_id=invitation.team_id, is_verified=True,
        )
        account_type = "user"

    db.add(account)
    await db.flush()

    db.add(AccountEmail(email=invitation.email, account_type=account_type, account_id=account.id))

    invitation.status = "accepted"
    invitation.accepted_at = datetime.now(timezone.utc)
    invitation.accepted_account_type = account_type
    invitation.accepted_account_id = account.id

    await write_audit_log(
        db, actor_type=ActorType.admin if account_type == "admin" else ActorType.user, actor_id=account.id,
        action="invitation.accept", organization_id=invitation.organization_id,
        target_type="invitation", target_id=invitation.id, request=request,
    )
    await db.commit()
    await db.refresh(account)

    role_value = account.admin_level.value if account_type == "admin" else account.role.value
    token = create_access_token({"sub": str(account.id), "account_type": account_type, "role": role_value})

    organization_out = None
    if account.organization_id is not None:
        organization = await db.get(Organization, account.organization_id)
        if organization is not None:
            organization_out = OrganizationSummaryOut(
                id=str(organization.id), name=organization.name,
                status=organization.status.value, soc_mode=organization.soc_mode.value,
            )

    return AcceptInvitationResponse(
        access_token=token,
        user=UserOut(
            id=str(account.id), name=account.name, email=account.email, role=role_value,
            account_type=account_type, organization=organization_out, effective_modules=None,
        ),
    )
