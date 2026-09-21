"""
Organization owner (organization_admin) endpoints -- always scoped to
the caller's own organization; no endpoint here accepts an organization
id from the client. Everything except the overview requires the
organization to be active (require_active_organization) -- see that
dependency's docstring for why the overview is the one exception,
alongside GET /auth/me.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import (
    ROLE_DEFAULT_MODULES,
    SOC_MODE_GATED_MODULES,
    require_active_organization,
    require_org_owner,
)
from app.audit import audit_from_scope
from app.config import settings
from app.database import get_db
from app.email_utils import send_invitation_email
from app.invite_service import check_invitation_rate_limit, create_invitation, rotate_invitation_token
from app.models import (
    AccountEmail,
    ActorType,
    AuditLog,
    Escalation,
    Invitation,
    Organization,
    OrganizationModule,
    OrganizationRoleAccess,
    OrganizationStatus,
    SocMode,
    Team,
    Ticket,
    User,
    UserAccessOverride,
    UserRole,
)
from app.modules import ALL_MODULE_KEYS
from app.org_summary import compute_org_counts
from app.scope import Scope

router = APIRouter(prefix="/api/v1/organization", tags=["organization"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


class MemberPatchRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    team_id: uuid.UUID | None = None


class InviteMemberRequest(BaseModel):
    email: str
    role: str
    team_id: uuid.UUID | None = None


class TeamCreateRequest(BaseModel):
    name: str
    description: str | None = None


class TeamPatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class TeamMembersRequest(BaseModel):
    user_ids: list[uuid.UUID]


class AccessUpdate(BaseModel):
    role: str
    module_key: str
    enabled: bool


class AccessUpdateRequest(BaseModel):
    updates: list[AccessUpdate]


class MemberAccessRequest(BaseModel):
    denied_modules: list[str]


async def _require_org(db: AsyncSession, scope: Scope) -> Organization:
    org = await db.get(Organization, scope.organization_id)
    if org is None:
        raise _err("organization_not_found", "Organization not found.", status_code=404)
    return org


def _validate_role(value: str) -> UserRole:
    """
    An owner may only invite/assign ordinary member roles -- never
    organization_admin, platform_soc_analyst or super_admin, none of
    which are UserRole values in the first place, so this rejects them
    for free.
    """
    try:
        return UserRole(value)
    except ValueError:
        raise _err("invalid_role", f"'{value}' is not an assignable role.")


async def _assert_soc_mode_allows(db: AsyncSession, org: Organization, role: UserRole) -> None:
    if role == UserRole.soc_analyst and org.soc_mode != SocMode.in_house:
        raise _err(
            "soc_analyst_requires_in_house",
            "SOC Analyst can only be assigned while this organization runs its own SOC (soc_mode = in_house).",
            status_code=422,
        )


async def _assert_under_member_limit(db: AsyncSession, org: Organization) -> None:
    if org.max_members is None:
        return
    counts = await compute_org_counts(db, org.id)
    total = counts["members"] + counts["pending_invitations"]
    if total >= org.max_members:
        raise _err(
            "member_limit_reached",
            f"This organization's member limit ({org.max_members}) has been reached.",
            status_code=409,
        )


# ---------------------------------------------------------------------------
# Overview -- the one member-data endpoint that works while pending.
# ---------------------------------------------------------------------------


@router.get("")
async def get_overview(db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_org_owner)):
    org = await _require_org(db, scope)

    if org.status == OrganizationStatus.pending:
        return {
            "id": str(org.id), "name": org.name, "status": org.status.value,
            "soc_mode": org.soc_mode.value, "message": "Your organization is awaiting platform approval.",
        }

    counts = await compute_org_counts(db, org.id)
    recent_activity = (
        await db.execute(
            select(AuditLog).where(AuditLog.organization_id == org.id).order_by(AuditLog.created_at.desc()).limit(10)
        )
    ).scalars().all()

    return {
        "id": str(org.id),
        "name": org.name,
        "status": org.status.value,
        "soc_mode": org.soc_mode.value,
        "industry": org.industry,
        "max_members": org.max_members,
        **counts,
        "recent_activity": [
            {
                "id": str(entry.id), "action": entry.action,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
            for entry in recent_activity
        ],
    }


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


@router.get("/members")
async def list_members(
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    users = (await db.execute(select(User).where(User.organization_id == scope.organization_id))).scalars().all()
    return {
        "members": [
            {
                "id": str(u.id), "name": u.name, "email": u.email, "role": u.role.value,
                "team_id": str(u.team_id) if u.team_id else None, "is_active": u.is_active,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            }
            for u in users
        ]
    }


@router.patch("/members/{user_id}")
async def patch_member(
    user_id: uuid.UUID, payload: MemberPatchRequest, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    org = await _require_org(db, scope)
    user = (
        await db.execute(select(User).where(User.id == user_id, User.organization_id == scope.organization_id))
    ).scalar_one_or_none()
    if user is None:
        raise _err("member_not_found", "Member not found in this organization.", status_code=404)

    before = {"role": user.role.value, "is_active": user.is_active, "team_id": str(user.team_id) if user.team_id else None}

    if payload.role is not None:
        new_role = _validate_role(payload.role)
        await _assert_soc_mode_allows(db, org, new_role)
        user.role = new_role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.team_id is not None:
        team = (
            await db.execute(select(Team).where(Team.id == payload.team_id, Team.organization_id == scope.organization_id))
        ).scalar_one_or_none()
        if team is None:
            raise _err("team_not_found", "Team not found in this organization.", status_code=404)
        user.team_id = team.id

    after = {"role": user.role.value, "is_active": user.is_active, "team_id": str(user.team_id) if user.team_id else None}
    await audit_from_scope(
        db, scope, "member.update", target_type="user", target_id=user.id, request=request, before=before, after=after,
    )
    await db.commit()
    return after | {"id": str(user.id)}


@router.delete("/members/{user_id}")
async def remove_member(
    user_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    """
    Soft-deletes by default (deactivate -- combined with the is_active
    check on every authenticated request in scope.py, this is what
    actually stops them from doing anything with an existing token, since
    this schema's `sessions` table isn't consulted anywhere on the
    request path to "revoke" individually). Only removes the row outright
    when nothing in the record (audit_logs, tickets, escalations) would
    otherwise be left pointing at a deleted user.
    """
    user = (
        await db.execute(select(User).where(User.id == user_id, User.organization_id == scope.organization_id))
    ).scalar_one_or_none()
    if user is None:
        raise _err("member_not_found", "Member not found in this organization.", status_code=404)

    referenced = (
        (await db.execute(select(AuditLog.id).where(AuditLog.actor_type == ActorType.user, AuditLog.actor_id == user.id).limit(1))).scalar_one_or_none()
        or (await db.execute(select(Ticket.id).where(Ticket.assigned_user_id == user.id).limit(1))).scalar_one_or_none()
        or (
            await db.execute(
                select(Escalation.id).where(
                    (Escalation.escalated_from == user.id) | (Escalation.escalated_to_user_id == user.id)
                ).limit(1)
            )
        ).scalar_one_or_none()
    )

    if referenced is not None:
        user.is_active = False
        await audit_from_scope(
            db, scope, "member.deactivate", target_type="user", target_id=user.id, request=request,
            after={"is_active": False, "reason": "referenced by history -- deactivated instead of removed"},
        )
        await db.commit()
        return {"id": str(user.id), "deleted": False, "deactivated": True}

    await db.execute(AccountEmail.__table__.delete().where(AccountEmail.email == user.email))
    await audit_from_scope(db, scope, "member.remove", target_type="user", target_id=user.id, request=request, before={"email": user.email})
    await db.delete(user)
    await db.commit()
    return {"id": str(user_id), "deleted": True, "deactivated": False}


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


@router.post("/invitations", status_code=201)
async def create_member_invitation(
    payload: InviteMemberRequest, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    org = await _require_org(db, scope)
    role = _validate_role(payload.role)
    await _assert_soc_mode_allows(db, org, role)

    email = payload.email.strip().lower()
    existing_email = (await db.execute(select(AccountEmail).where(AccountEmail.email == email))).scalar_one_or_none()
    if existing_email:
        raise _err("email_already_registered", "An account already exists with this email.", status_code=409)

    existing_pending = (
        await db.execute(
            select(Invitation).where(
                Invitation.organization_id == scope.organization_id, Invitation.email == email, Invitation.status == "pending"
            )
        )
    ).scalar_one_or_none()
    if existing_pending:
        raise _err("invitation_already_pending", "An invitation is already pending for this email.", status_code=409)

    await _assert_under_member_limit(db, org)
    await check_invitation_rate_limit(db, org.id)

    team_id = None
    if payload.team_id is not None:
        team = (
            await db.execute(select(Team).where(Team.id == payload.team_id, Team.organization_id == scope.organization_id))
        ).scalar_one_or_none()
        if team is None:
            raise _err("team_not_found", "Team not found in this organization.", status_code=404)
        team_id = team.id

    invitation, raw_token = await create_invitation(
        db, organization_id=org.id, email=email, kind="member", invited_by_admin_id=scope.user_id, role=role, team_id=team_id,
    )
    await audit_from_scope(
        db, scope, "invitation.create", target_type="invitation", target_id=invitation.id, request=request,
        after={"email": email, "role": role.value},
    )
    await db.commit()

    invite_link = f"{settings.frontend_url}/accept-invite?token={raw_token}"
    try:
        send_invitation_email(email, org.name, role.value, invite_link, invitation.expires_at)
    except Exception as exc:
        print(f"[SentinelX] Failed to send invitation email to {email}: {exc}")

    return {"id": str(invitation.id), "email": email, "role": role.value, "status": invitation.status, "expires_at": invitation.expires_at.isoformat()}


@router.get("/invitations")
async def list_invitations(
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    rows = (
        await db.execute(
            select(Invitation).where(Invitation.organization_id == scope.organization_id).order_by(Invitation.created_at.desc())
        )
    ).scalars().all()
    return {
        "invitations": [
            {
                "id": str(i.id), "email": i.email, "kind": i.kind,
                "role": i.role.value if i.role else None, "status": i.status,
                "created_at": i.created_at.isoformat() if i.created_at else None,
                "expires_at": i.expires_at.isoformat() if i.expires_at else None,
            }
            for i in rows
        ]
    }


@router.post("/invitations/{invitation_id}/resend")
async def resend_invitation(
    invitation_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    invitation = (
        await db.execute(
            select(Invitation).where(Invitation.id == invitation_id, Invitation.organization_id == scope.organization_id)
        )
    ).scalar_one_or_none()
    if invitation is None:
        raise _err("invitation_not_found", "Invitation not found.", status_code=404)
    if invitation.status != "pending":
        raise _err("invitation_not_pending", "Only a pending invitation can be resent.", status_code=409)

    await check_invitation_rate_limit(db, scope.organization_id)
    raw_token = rotate_invitation_token(invitation)

    org = await _require_org(db, scope)
    await audit_from_scope(db, scope, "invitation.resend", target_type="invitation", target_id=invitation.id, request=request)
    await db.commit()

    invite_link = f"{settings.frontend_url}/accept-invite?token={raw_token}"
    role_label = invitation.role.value if invitation.role else invitation.kind
    try:
        send_invitation_email(invitation.email, org.name, role_label, invite_link, invitation.expires_at)
    except Exception as exc:
        print(f"[SentinelX] Failed to send invitation email to {invitation.email}: {exc}")

    return {"id": str(invitation.id), "status": invitation.status, "expires_at": invitation.expires_at.isoformat()}


@router.delete("/invitations/{invitation_id}")
async def revoke_invitation(
    invitation_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    invitation = (
        await db.execute(
            select(Invitation).where(Invitation.id == invitation_id, Invitation.organization_id == scope.organization_id)
        )
    ).scalar_one_or_none()
    if invitation is None:
        raise _err("invitation_not_found", "Invitation not found.", status_code=404)
    if invitation.status != "pending":
        raise _err("invitation_not_pending", "Only a pending invitation can be revoked.", status_code=409)

    invitation.status = "revoked"
    await audit_from_scope(db, scope, "invitation.revoke", target_type="invitation", target_id=invitation.id, request=request)
    await db.commit()
    return {"id": str(invitation.id), "status": invitation.status}


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


@router.get("/teams")
async def list_teams(
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    teams = (await db.execute(select(Team).where(Team.organization_id == scope.organization_id))).scalars().all()
    result = []
    for team in teams:
        member_count = (
            await db.execute(select(User).where(User.team_id == team.id))
        ).scalars().all()
        result.append({"id": str(team.id), "name": team.name, "description": team.description, "member_count": len(member_count)})
    return {"teams": result}


@router.post("/teams", status_code=201)
async def create_team(
    payload: TeamCreateRequest, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    team = Team(organization_id=scope.organization_id, name=payload.name.strip(), description=payload.description)
    db.add(team)
    await db.flush()
    await audit_from_scope(db, scope, "team.create", target_type="team", target_id=team.id, request=request, after={"name": team.name})
    await db.commit()
    return {"id": str(team.id), "name": team.name, "description": team.description}


@router.patch("/teams/{team_id}")
async def patch_team(
    team_id: uuid.UUID, payload: TeamPatchRequest, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    team = (
        await db.execute(select(Team).where(Team.id == team_id, Team.organization_id == scope.organization_id))
    ).scalar_one_or_none()
    if team is None:
        raise _err("team_not_found", "Team not found in this organization.", status_code=404)

    before = {"name": team.name, "description": team.description}
    if payload.name is not None:
        team.name = payload.name.strip()
    if payload.description is not None:
        team.description = payload.description

    await audit_from_scope(
        db, scope, "team.update", target_type="team", target_id=team.id, request=request,
        before=before, after={"name": team.name, "description": team.description},
    )
    await db.commit()
    return {"id": str(team.id), "name": team.name, "description": team.description}


@router.delete("/teams/{team_id}")
async def delete_team(
    team_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    team = (
        await db.execute(select(Team).where(Team.id == team_id, Team.organization_id == scope.organization_id))
    ).scalar_one_or_none()
    if team is None:
        raise _err("team_not_found", "Team not found in this organization.", status_code=404)

    await audit_from_scope(db, scope, "team.delete", target_type="team", target_id=team.id, request=request, before={"name": team.name})
    await db.delete(team)  # users.team_id is ON DELETE SET NULL -- members aren't removed, just unassigned
    await db.commit()
    return {"id": str(team_id), "deleted": True}


@router.put("/teams/{team_id}/members")
async def set_team_members(
    team_id: uuid.UUID, payload: TeamMembersRequest, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    team = (
        await db.execute(select(Team).where(Team.id == team_id, Team.organization_id == scope.organization_id))
    ).scalar_one_or_none()
    if team is None:
        raise _err("team_not_found", "Team not found in this organization.", status_code=404)

    requested_ids = set(payload.user_ids)
    org_users = (await db.execute(select(User).where(User.organization_id == scope.organization_id))).scalars().all()
    org_user_ids = {u.id for u in org_users}
    invalid = requested_ids - org_user_ids
    if invalid:
        raise _err("member_not_found", f"User(s) not in this organization: {', '.join(str(i) for i in invalid)}.", status_code=404)

    for user in org_users:
        if user.id in requested_ids:
            user.team_id = team.id
        elif user.team_id == team.id:
            user.team_id = None

    await audit_from_scope(
        db, scope, "team.members_update", target_type="team", target_id=team.id, request=request,
        after={"user_ids": [str(i) for i in requested_ids]},
    )
    await db.commit()
    return {"id": str(team.id), "member_ids": [str(i) for i in requested_ids]}


# ---------------------------------------------------------------------------
# Access matrix
# ---------------------------------------------------------------------------


@router.get("/access")
async def get_access_matrix(
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    org = await _require_org(db, scope)
    module_rows = (
        await db.execute(select(OrganizationModule).where(OrganizationModule.organization_id == org.id))
    ).scalars().all()
    platform_enabled = {row.module_key: row.enabled for row in module_rows}

    role_access_rows = (
        await db.execute(select(OrganizationRoleAccess).where(OrganizationRoleAccess.organization_id == org.id))
    ).scalars().all()
    owner_settings = {(row.role, row.module_key): row.enabled for row in role_access_rows}

    matrix = {}
    for role in UserRole:
        role_defaults = ROLE_DEFAULT_MODULES.get(role, {})
        gated = SOC_MODE_GATED_MODULES.get(role, set())
        matrix[role.value] = {}
        for key in ALL_MODULE_KEYS:
            has_default = key in role_defaults
            plat_on = platform_enabled.get(key, False)
            owner_on = owner_settings.get((role, key), True)
            soc_gated = key in gated and org.soc_mode != SocMode.in_house
            matrix[role.value][key] = {
                "platform_enabled": plat_on,
                "role_has_default": has_default,
                "owner_enabled": owner_on,
                "soc_gated": soc_gated,
                "effective": bool(has_default and plat_on and owner_on and not soc_gated),
            }
    return {"organization": {"soc_mode": org.soc_mode.value}, "matrix": matrix}


@router.put("/access")
async def update_access_matrix(
    payload: AccessUpdateRequest, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    org = await _require_org(db, scope)
    module_rows = (
        await db.execute(select(OrganizationModule).where(OrganizationModule.organization_id == org.id))
    ).scalars().all()
    platform_enabled = {row.module_key: row.enabled for row in module_rows}

    existing_rows = (
        await db.execute(select(OrganizationRoleAccess).where(OrganizationRoleAccess.organization_id == org.id))
    ).scalars().all()
    by_key = {(row.role, row.module_key): row for row in existing_rows}

    applied = []
    for update in payload.updates:
        role = _validate_role(update.role)
        if update.module_key not in ROLE_DEFAULT_MODULES.get(role, {}):
            raise _err("module_not_default_for_role", f"'{update.module_key}' is not a default module for role '{role.value}'.", status_code=422)
        if not platform_enabled.get(update.module_key, False):
            raise _err("module_disabled_by_platform", f"'{update.module_key}' has been disabled for this organization by the platform.", status_code=422)

        row = by_key.get((role, update.module_key))
        if row is None:
            row = OrganizationRoleAccess(organization_id=org.id, role=role, module_key=update.module_key, enabled=update.enabled)
            db.add(row)
            by_key[(role, update.module_key)] = row
        else:
            row.enabled = update.enabled
        row.updated_by_admin_id = scope.user_id
        applied.append({"role": role.value, "module_key": update.module_key, "enabled": update.enabled})

    await audit_from_scope(db, scope, "organization.access_update", target_type="organization", target_id=org.id, request=request, after={"updates": applied})
    await db.commit()
    return {"updates": applied}


@router.put("/members/{user_id}/access")
async def update_member_access(
    user_id: uuid.UUID, payload: MemberAccessRequest, request: Request,
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(require_active_organization), _owner: Scope = Depends(require_org_owner),
):
    user = (
        await db.execute(select(User).where(User.id == user_id, User.organization_id == scope.organization_id))
    ).scalar_one_or_none()
    if user is None:
        raise _err("member_not_found", "Member not found in this organization.", status_code=404)

    unknown = set(payload.denied_modules) - set(ALL_MODULE_KEYS)
    if unknown:
        raise _err("unknown_module_key", f"Unknown module key(s): {', '.join(sorted(unknown))}.")

    existing_rows = (await db.execute(select(UserAccessOverride).where(UserAccessOverride.user_id == user_id))).scalars().all()
    by_key = {row.module_key: row for row in existing_rows}
    denied = set(payload.denied_modules)

    for row in existing_rows:
        if row.module_key not in denied:
            await db.delete(row)
    for key in denied:
        row = by_key.get(key)
        if row is None:
            db.add(
                UserAccessOverride(
                    user_id=user_id, organization_id=scope.organization_id, module_key=key,
                    allowed=False, set_by_admin_id=scope.user_id,
                )
            )
        else:
            row.allowed = False
            row.set_by_admin_id = scope.user_id

    await audit_from_scope(
        db, scope, "member.access_update", target_type="user", target_id=user_id, request=request,
        after={"denied_modules": sorted(denied)},
    )
    await db.commit()
    return {"id": str(user_id), "denied_modules": sorted(denied)}
