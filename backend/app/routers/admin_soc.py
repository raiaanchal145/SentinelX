"""
Platform SOC team management -- creating platform_soc_analyst accounts
(via invitation, same as every other new account type in this feature)
and assigning them to managed organizations. super_admin-only.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_super_admin
from app.audit import audit_from_scope
from app.config import settings
from app.database import get_db
from app.email_utils import send_invitation_email
from app.invite_service import check_invitation_rate_limit, create_invitation
from app.models import AccountEmail, Admin, AdminLevel, Organization, OrganizationStatus, SocMode, SocOrganizationAssignment
from app.scope import Scope

router = APIRouter(prefix="/api/v1/admin/soc-analysts", tags=["admin-soc"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


class InviteSocAnalystRequest(BaseModel):
    email: str


class SocAnalystPatchRequest(BaseModel):
    is_active: bool


class SocAnalystOrganizationsRequest(BaseModel):
    organization_ids: list[uuid.UUID]


async def _assigned_organizations(db: AsyncSession, admin_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            select(Organization)
            .join(SocOrganizationAssignment, SocOrganizationAssignment.organization_id == Organization.id)
            .where(SocOrganizationAssignment.admin_id == admin_id)
        )
    ).scalars().all()
    return [{"id": str(o.id), "name": o.name, "status": o.status.value, "soc_mode": o.soc_mode.value} for o in rows]


@router.post("", status_code=201)
async def invite_soc_analyst(
    payload: InviteSocAnalystRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
):
    email = payload.email.strip().lower()
    existing_email = (await db.execute(select(AccountEmail).where(AccountEmail.email == email))).scalar_one_or_none()
    if existing_email:
        raise _err("email_already_registered", "An account already exists with this email.", status_code=409)

    await check_invitation_rate_limit(db, organization_id=None)
    invitation, raw_token = await create_invitation(
        db, organization_id=None, email=email, kind="platform_soc", invited_by_admin_id=scope.account.id,
    )

    await audit_from_scope(
        db, scope, "soc_analyst.invite", target_type="invitation", target_id=invitation.id, request=request,
        after={"email": email},
    )
    await db.commit()

    invite_link = f"{settings.frontend_url}/accept-invite?token={raw_token}"
    try:
        send_invitation_email(email, "SentinelX", "platform SOC analyst", invite_link, invitation.expires_at)
    except Exception as exc:
        print(f"[SentinelX] Failed to send invitation email to {email}: {exc}")

    return {"id": str(invitation.id), "email": email, "status": invitation.status}


@router.get("")
async def list_soc_analysts(db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_super_admin)):
    analysts = (
        await db.execute(select(Admin).where(Admin.admin_level == AdminLevel.platform_soc_analyst))
    ).scalars().all()
    return {
        "soc_analysts": [
            {
                "id": str(a.id), "name": a.name, "email": a.email, "is_active": a.is_active,
                "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None,
                "assigned_organizations": await _assigned_organizations(db, a.id),
            }
            for a in analysts
        ]
    }


@router.patch("/{admin_id}")
async def patch_soc_analyst(
    admin_id: uuid.UUID,
    payload: SocAnalystPatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
):
    admin = (
        await db.execute(select(Admin).where(Admin.id == admin_id, Admin.admin_level == AdminLevel.platform_soc_analyst))
    ).scalar_one_or_none()
    if admin is None:
        raise _err("soc_analyst_not_found", "Platform SOC analyst not found.", status_code=404)

    before = admin.is_active
    admin.is_active = payload.is_active
    await audit_from_scope(
        db, scope, "soc_analyst.status_update", target_type="admin", target_id=admin.id, request=request,
        before={"is_active": before}, after={"is_active": admin.is_active},
    )
    await db.commit()
    return {"id": str(admin.id), "is_active": admin.is_active}


@router.put("/{admin_id}/organizations")
async def update_soc_analyst_organizations(
    admin_id: uuid.UUID,
    payload: SocAnalystOrganizationsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
):
    admin = (
        await db.execute(select(Admin).where(Admin.id == admin_id, Admin.admin_level == AdminLevel.platform_soc_analyst))
    ).scalar_one_or_none()
    if admin is None:
        raise _err("soc_analyst_not_found", "Platform SOC analyst not found.", status_code=404)

    requested_ids = set(payload.organization_ids)
    if requested_ids:
        valid_orgs = (
            await db.execute(
                select(Organization.id).where(
                    Organization.id.in_(requested_ids),
                    Organization.soc_mode == SocMode.managed,
                    Organization.status != OrganizationStatus.archived,
                )
            )
        ).scalars().all()
        invalid_ids = requested_ids - set(valid_orgs)
        if invalid_ids:
            raise _err(
                "invalid_organization_assignment",
                "Only managed, non-archived organizations can be assigned to a platform SOC analyst: "
                f"{', '.join(str(i) for i in invalid_ids)}.",
            )

    existing = (
        await db.execute(select(SocOrganizationAssignment).where(SocOrganizationAssignment.admin_id == admin_id))
    ).scalars().all()
    existing_ids = {row.organization_id for row in existing}

    for row in existing:
        if row.organization_id not in requested_ids:
            await db.delete(row)
    for org_id in requested_ids - existing_ids:
        db.add(
            SocOrganizationAssignment(admin_id=admin_id, organization_id=org_id, assigned_by_admin_id=scope.account.id)
        )

    await audit_from_scope(
        db, scope, "soc_analyst.organizations_update", target_type="admin", target_id=admin.id, request=request,
        before={"organization_ids": [str(i) for i in existing_ids]},
        after={"organization_ids": [str(i) for i in requested_ids]},
    )
    await db.commit()
    return {"id": str(admin.id), "assigned_organizations": await _assigned_organizations(db, admin.id)}
