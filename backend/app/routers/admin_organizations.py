"""
Platform admin endpoints for managing organizations -- see
docs/API_CONTRACT.md for the full request/response shapes. Every
endpoint here requires require_super_admin except where noted; nothing
here ever trusts a client-supplied organization id beyond the path
parameter itself, which is always the thing being acted on.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_super_admin, seed_default_modules
from app.audit import audit_from_scope
from app.config import settings
from app.database import get_db
from app.email_utils import send_invitation_email
from app.models import (
    AccountEmail,
    Admin,
    AdminLevel,
    AuditLog,
    Organization,
    OrganizationModule,
    OrganizationStatus,
    SocMode,
    SocOrganizationAssignment,
    User,
    UserRole,
)
from app.invite_service import check_invitation_rate_limit, create_invitation
from app.modules import ALL_MODULE_KEYS
from app.org_summary import active_owner_count, compute_org_counts
from app.scope import Scope

router = APIRouter(prefix="/api/v1/admin/organizations", tags=["admin-organizations"])



def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


class OrganizationCreateRequest(BaseModel):
    name: str
    owner_email: str
    soc_mode: str
    industry: str | None = None
    max_members: int | None = None


class OrganizationPatchRequest(BaseModel):
    name: str | None = None
    industry: str | None = None
    max_members: int | None = None


class SuspendRequest(BaseModel):
    reason: str


class ModulesUpdateRequest(BaseModel):
    modules: dict[str, bool]


class SocModeUpdateRequest(BaseModel):
    soc_mode: str


async def _owner_admin(db: AsyncSession, organization_id: uuid.UUID) -> Admin | None:
    return (
        await db.execute(
            select(Admin).where(
                Admin.organization_id == organization_id,
                Admin.admin_level == AdminLevel.organization_admin,
            )
        )
    ).scalars().first()


async def _org_row(db: AsyncSession, org: Organization) -> dict:
    owner = await _owner_admin(db, org.id)
    counts = await compute_org_counts(db, org.id)
    return {
        "id": str(org.id),
        "name": org.name,
        "industry": org.industry,
        "status": org.status.value,
        "soc_mode": org.soc_mode.value,
        "max_members": org.max_members,
        "created_via": org.created_via,
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "owner": {"name": owner.name, "email": owner.email} if owner else None,
        **counts,
    }


@router.get("")
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
    q: str | None = Query(default=None, description="Search by name or owner email"),
    status: str | None = Query(default=None),
    soc_mode: str | None = Query(default=None),
    sort: str = Query(default="created_at_desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    stmt = select(Organization)

    if status:
        try:
            stmt = stmt.where(Organization.status == OrganizationStatus(status))
        except ValueError:
            raise _err("invalid_status", f"Unknown status '{status}'.")
    if soc_mode:
        try:
            stmt = stmt.where(Organization.soc_mode == SocMode(soc_mode))
        except ValueError:
            raise _err("invalid_soc_mode", f"Unknown soc_mode '{soc_mode}'.")
    if q:
        like = f"%{q.strip()}%"
        owner_emails = select(Admin.organization_id).where(
            Admin.admin_level == AdminLevel.organization_admin, Admin.email.ilike(like)
        )
        stmt = stmt.where(or_(Organization.name.ilike(like), Organization.id.in_(owner_emails)))

    sort_map = {
        "created_at_desc": Organization.created_at.desc(),
        "created_at_asc": Organization.created_at.asc(),
        "name_asc": Organization.name.asc(),
        "name_desc": Organization.name.desc(),
    }
    stmt = stmt.order_by(sort_map.get(sort, Organization.created_at.desc()))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    orgs = (await db.execute(stmt)).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "organizations": [await _org_row(db, org) for org in orgs],
    }


@router.get("/{organization_id}")
async def get_organization(
    organization_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
):
    org = await db.get(Organization, organization_id)
    if org is None:
        raise _err("organization_not_found", "Organization not found.", status_code=404)

    module_rows = (
        await db.execute(select(OrganizationModule).where(OrganizationModule.organization_id == organization_id))
    ).scalars().all()
    modules = {row.module_key: row.enabled for row in module_rows}

    assignments = (
        await db.execute(
            select(SocOrganizationAssignment, Admin)
            .join(Admin, Admin.id == SocOrganizationAssignment.admin_id)
            .where(SocOrganizationAssignment.organization_id == organization_id)
        )
    ).all()

    recent_activity = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.created_at.desc())
            .limit(20)
        )
    ).scalars().all()

    row = await _org_row(db, org)
    row["modules"] = modules
    row["assigned_soc_analysts"] = [
        {"id": str(admin.id), "name": admin.name, "email": admin.email} for _assignment, admin in assignments
    ]
    row["recent_activity"] = [
        {
            "id": str(entry.id),
            "action": entry.action,
            "actor_type": entry.actor_type.value,
            "actor_id": str(entry.actor_id) if entry.actor_id else None,
            "target_type": entry.target_type,
            "target_id": str(entry.target_id) if entry.target_id else None,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "details": entry.details,
        }
        for entry in recent_activity
    ]
    return row


@router.post("", status_code=201)
async def create_organization(
    payload: OrganizationCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
):
    try:
        soc_mode = SocMode(payload.soc_mode)
    except ValueError:
        raise _err("invalid_soc_mode", f"Unknown soc_mode '{payload.soc_mode}'.")

    owner_email = payload.owner_email.strip().lower()
    existing_email = (
        await db.execute(select(AccountEmail).where(AccountEmail.email == owner_email))
    ).scalar_one_or_none()
    if existing_email:
        raise _err("email_already_registered", "An account already exists with this email.", status_code=409)

    org = Organization(
        name=payload.name.strip(),
        industry=payload.industry,
        status=OrganizationStatus.active,
        soc_mode=soc_mode,
        max_members=payload.max_members,
        created_via="platform_admin",
        created_by_admin_id=scope.account.id,
        approved_by_admin_id=scope.account.id,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(org)
    await db.flush()
    await seed_default_modules(db, org.id)

    await check_invitation_rate_limit(db, org.id)
    invitation, raw_token = await create_invitation(
        db, organization_id=org.id, email=owner_email, kind="owner", invited_by_admin_id=scope.account.id,
    )

    await audit_from_scope(
        db, scope, "organization.create", organization_id=org.id,
        target_type="organization", target_id=org.id, request=request,
        after={"name": org.name, "soc_mode": soc_mode.value},
    )
    await db.commit()

    invite_link = f"{settings.frontend_url}/accept-invite?token={raw_token}"
    try:
        send_invitation_email(owner_email, org.name, "organization owner", invite_link, invitation.expires_at)
    except Exception as exc:
        print(f"[SentinelX] Failed to send invitation email to {owner_email}: {exc}")

    return await _org_row(db, org)


@router.patch("/{organization_id}")
async def patch_organization(
    organization_id: uuid.UUID,
    payload: OrganizationPatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
):
    org = await db.get(Organization, organization_id)
    if org is None:
        raise _err("organization_not_found", "Organization not found.", status_code=404)

    before = {"name": org.name, "industry": org.industry, "max_members": org.max_members}
    if payload.name is not None:
        org.name = payload.name.strip()
    if payload.industry is not None:
        org.industry = payload.industry
    if payload.max_members is not None:
        org.max_members = payload.max_members

    await audit_from_scope(
        db, scope, "organization.update", organization_id=org.id, target_type="organization",
        target_id=org.id, request=request, before=before,
        after={"name": org.name, "industry": org.industry, "max_members": org.max_members},
    )
    await db.commit()
    return await _org_row(db, org)


async def _transition(
    organization_id: uuid.UUID,
    db: AsyncSession,
    scope: Scope,
    request: Request,
    *,
    allowed_from: set[OrganizationStatus],
    to: OrganizationStatus,
    action: str,
    apply: callable,
):
    org = await db.get(Organization, organization_id)
    if org is None:
        raise _err("organization_not_found", "Organization not found.", status_code=404)
    if org.status not in allowed_from:
        raise _err(
            "invalid_status_transition",
            f"Cannot move an organization from '{org.status.value}' to '{to.value}'.",
            status_code=409,
        )
    before_status = org.status.value
    apply(org)
    org.status = to
    await audit_from_scope(
        db, scope, action, organization_id=org.id, target_type="organization",
        target_id=org.id, request=request, before={"status": before_status}, after={"status": to.value},
    )
    await db.commit()
    return await _org_row(db, org)


@router.post("/{organization_id}/approve")
async def approve_organization(
    organization_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_super_admin),
):
    def apply(org: Organization) -> None:
        org.approved_by_admin_id = scope.account.id
        org.approved_at = datetime.now(timezone.utc)

    return await _transition(
        organization_id, db, scope, request,
        allowed_from={OrganizationStatus.pending}, to=OrganizationStatus.active,
        action="organization.approve", apply=apply,
    )


@router.post("/{organization_id}/suspend")
async def suspend_organization(
    organization_id: uuid.UUID, payload: SuspendRequest, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_super_admin),
):
    reason = payload.reason.strip()
    if not reason:
        raise _err("suspension_reason_required", "A suspension reason is required.")

    def apply(org: Organization) -> None:
        org.suspended_at = datetime.now(timezone.utc)
        org.suspension_reason = reason

    return await _transition(
        organization_id, db, scope, request,
        allowed_from={OrganizationStatus.active, OrganizationStatus.pending}, to=OrganizationStatus.suspended,
        action="organization.suspend", apply=apply,
    )


@router.post("/{organization_id}/reactivate")
async def reactivate_organization(
    organization_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_super_admin),
):
    def apply(org: Organization) -> None:
        org.suspended_at = None
        org.suspension_reason = None

    return await _transition(
        organization_id, db, scope, request,
        allowed_from={OrganizationStatus.suspended}, to=OrganizationStatus.active,
        action="organization.reactivate", apply=apply,
    )


@router.post("/{organization_id}/archive")
async def archive_organization(
    organization_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_super_admin),
):
    return await _transition(
        organization_id, db, scope, request,
        allowed_from={OrganizationStatus.active, OrganizationStatus.suspended, OrganizationStatus.pending},
        to=OrganizationStatus.archived,
        action="organization.archive", apply=lambda org: None,
    )


@router.put("/{organization_id}/modules")
async def update_modules(
    organization_id: uuid.UUID,
    payload: ModulesUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
):
    org = await db.get(Organization, organization_id)
    if org is None:
        raise _err("organization_not_found", "Organization not found.", status_code=404)

    given_keys = set(payload.modules.keys())
    unknown = given_keys - set(ALL_MODULE_KEYS)
    if unknown:
        raise _err("unknown_module_key", f"Unknown module key(s): {', '.join(sorted(unknown))}.")
    missing = set(ALL_MODULE_KEYS) - given_keys
    if missing:
        raise _err("incomplete_module_list", f"Missing module key(s): {', '.join(sorted(missing))}.")

    rows = (
        await db.execute(select(OrganizationModule).where(OrganizationModule.organization_id == organization_id))
    ).scalars().all()
    by_key = {row.module_key: row for row in rows}
    before = {key: by_key[key].enabled if key in by_key else True for key in ALL_MODULE_KEYS}
    changed = {}

    for key, enabled in payload.modules.items():
        row = by_key.get(key)
        if row is None:
            row = OrganizationModule(organization_id=organization_id, module_key=key, enabled=enabled)
            db.add(row)
        elif row.enabled != enabled:
            row.enabled = enabled
        else:
            continue
        row.updated_by_admin_id = scope.account.id
        changed[key] = enabled

    if changed:
        await audit_from_scope(
            db, scope, "organization.modules_update", organization_id=organization_id,
            target_type="organization", target_id=organization_id, request=request,
            before={k: before[k] for k in changed}, after=changed,
        )
    await db.commit()
    return {"modules": payload.modules, "changed": changed}


@router.put("/{organization_id}/soc-mode")
async def update_soc_mode(
    organization_id: uuid.UUID,
    payload: SocModeUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
):
    org = await db.get(Organization, organization_id)
    if org is None:
        raise _err("organization_not_found", "Organization not found.", status_code=404)

    try:
        new_mode = SocMode(payload.soc_mode)
    except ValueError:
        raise _err("invalid_soc_mode", f"Unknown soc_mode '{payload.soc_mode}'.")

    soc_analyst_count = (
        await db.execute(
            select(func.count(User.id)).where(
                User.organization_id == organization_id, User.role == UserRole.soc_analyst
            )
        )
    ).scalar() or 0

    before_mode = org.soc_mode.value
    org.soc_mode = new_mode
    await audit_from_scope(
        db, scope, "organization.soc_mode_update", organization_id=organization_id,
        target_type="organization", target_id=organization_id, request=request,
        before={"soc_mode": before_mode}, after={"soc_mode": new_mode.value},
    )
    await db.commit()

    response = {"organization": await _org_row(db, org), "soc_analyst_count": soc_analyst_count}
    if new_mode == SocMode.managed and soc_analyst_count:
        response["message"] = (
            f"{soc_analyst_count} soc_analyst member(s) keep their accounts but lose the "
            "soc/incidents modules until this organization is switched back to in_house."
        )
    if new_mode == SocMode.in_house and not soc_analyst_count:
        response["warning"] = "This organization has no soc_analyst member yet -- invite one to staff its SOC."
    return response


@router.get("/{organization_id}/members")
async def list_members(
    organization_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
):
    org = await db.get(Organization, organization_id)
    if org is None:
        raise _err("organization_not_found", "Organization not found.", status_code=404)

    owners = (
        await db.execute(
            select(Admin).where(
                Admin.organization_id == organization_id, Admin.admin_level == AdminLevel.organization_admin
            )
        )
    ).scalars().all()
    users = (await db.execute(select(User).where(User.organization_id == organization_id))).scalars().all()

    members = [
        {
            "account_type": "admin", "id": str(o.id), "name": o.name, "email": o.email,
            "role": "organization_admin", "is_active": o.is_active,
            "last_login_at": o.last_login_at.isoformat() if o.last_login_at else None,
        }
        for o in owners
    ] + [
        {
            "account_type": "user", "id": str(u.id), "name": u.name, "email": u.email,
            "role": u.role.value, "is_active": u.is_active,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        }
        for u in users
    ]
    return {"members": members}


@router.post("/{organization_id}/members/{account_type}/{account_id}/deactivate")
async def deactivate_member(
    organization_id: uuid.UUID, account_type: str, account_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_super_admin),
):
    if account_type not in ("admin", "user"):
        raise _err("invalid_account_type", "account_type must be 'admin' or 'user'.")

    model = Admin if account_type == "admin" else User
    account = (
        await db.execute(select(model).where(model.id == account_id, model.organization_id == organization_id))
    ).scalar_one_or_none()
    if account is None:
        raise _err("member_not_found", "Member not found in this organization.", status_code=404)

    if account_type == "admin":
        active_owners = await active_owner_count(db, organization_id)
        if active_owners <= 1 and account.is_active:
            raise _err("last_owner_protected", "The last active owner of an organization cannot be deactivated.", status_code=409)

    account.is_active = False
    await audit_from_scope(
        db, scope, "member.deactivate", organization_id=organization_id, target_type=account_type,
        target_id=account.id, request=request, after={"is_active": False},
    )
    await db.commit()
    return {"id": str(account.id), "is_active": account.is_active}


@router.get("/{organization_id}/activity")
async def organization_activity(
    organization_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    org = await db.get(Organization, organization_id)
    if org is None:
        raise _err("organization_not_found", "Organization not found.", status_code=404)

    stmt = select(AuditLog).where(AuditLog.organization_id == organization_id).order_by(AuditLog.created_at.desc())
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "entries": [
            {
                "id": str(entry.id),
                "action": entry.action,
                "actor_type": entry.actor_type.value,
                "actor_id": str(entry.actor_id) if entry.actor_id else None,
                "target_type": entry.target_type,
                "target_id": str(entry.target_id) if entry.target_id else None,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
                "details": entry.details,
            }
            for entry in rows
        ],
    }
