"""
The layered access-control model.

Effective access of a `users` account (soc_analyst, security_manager,
it_developer, auditor) = organization_modules(enabled) AND role default
map AND organization_role_access AND user_access_overrides, evaluated in
that order -- each layer can only remove, never add back what an
earlier layer already took away. See get_effective_access() for the
exact algorithm.

The organization owner (organization_admin) is an admin_level, not a
UserRole, and organization_role_access/user_access_overrides don't
apply to them (their `role`/`user_id` columns are scoped to `users`
accounts). An owner's effective access is: every module the platform
enabled, at "write", except soc/incidents drop to "read" (oversight
only) while the organization's soc_mode is "managed" -- the owner isn't
running their own SOC in that mode, platform SOC staff are.

Platform accounts (super_admin, platform_soc_analyst) don't have
organization-scoped module access in this sense; they reach
organization data through the dedicated /admin/* endpoints and the
require_* dependencies below, never through get_effective_access().

Error shape: every business-rule rejection in this module (and, by
convention, every new endpoint built on it) raises HTTPException with
`detail={"code": "<stable_code>", "message": "<human string>"}` rather
than a bare string, so the frontend can switch on `code` instead of
parsing `message` -- see docs/API_CONTRACT.md's error code table.
"""

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    Admin,
    AdminLevel,
    Organization,
    OrganizationModule,
    OrganizationRoleAccess,
    OrganizationStatus,
    SocMode,
    SocOrganizationAssignment,
    User,
    UserAccessOverride,
    UserRole,
)
from app.modules import ALL_MODULE_KEYS, ModuleKey
from app.scope import Scope, org_scope

# org_scope itself is defined once, in app/scope.py -- re-exported here
# so callers can pull every access-control dependency from this one
# module, per how the spec groups them.
__all__ = [
    "ACCESS_READ",
    "ACCESS_WRITE",
    "ROLE_DEFAULT_MODULES",
    "get_effective_access",
    "require_platform_admin",
    "require_super_admin",
    "require_org_owner",
    "require_platform_soc",
    "require_module",
    "require_active_organization",
    "org_scope",
    "soc_visible_organization_ids",
]

ACCESS_READ = "read"
ACCESS_WRITE = "write"

# A module key absent from a role's map is never available to that
# role, regardless of what the organization or the owner enabled.
ROLE_DEFAULT_MODULES: dict[UserRole, dict[str, str]] = {
    UserRole.security_manager: {
        ModuleKey.assets.value: ACCESS_WRITE,
        ModuleKey.soc.value: ACCESS_READ,
        ModuleKey.incidents.value: ACCESS_WRITE,
        ModuleKey.it_tickets.value: ACCESS_WRITE,
        ModuleKey.approvals.value: ACCESS_WRITE,
        ModuleKey.reports.value: ACCESS_WRITE,
    },
    UserRole.soc_analyst: {
        ModuleKey.assets.value: ACCESS_WRITE,
        ModuleKey.soc.value: ACCESS_WRITE,
        ModuleKey.incidents.value: ACCESS_WRITE,
        ModuleKey.ai_agents.value: ACCESS_WRITE,
        ModuleKey.reports.value: ACCESS_WRITE,
    },
    UserRole.it_developer: {
        ModuleKey.assets.value: ACCESS_READ,
        ModuleKey.it_tickets.value: ACCESS_WRITE,
    },
    UserRole.auditor: {
        ModuleKey.assets.value: ACCESS_READ,
        ModuleKey.reports.value: ACCESS_WRITE,
        ModuleKey.audit_logs.value: ACCESS_WRITE,
    },
}

# Modules that additionally require the organization to be running its
# own SOC (soc_mode == in_house) before the given role can be granted
# them -- independent of organization_modules/organization_role_access/
# user_access_overrides, and independent of the owner's oversight rule
# above (which is its own, separate branch in get_effective_access()).
SOC_MODE_GATED_MODULES: dict[UserRole, set[str]] = {
    UserRole.soc_analyst: {ModuleKey.soc.value, ModuleKey.incidents.value},
}


async def get_effective_access(
    db: AsyncSession, account: Admin | User, organization: Organization
) -> dict[str, dict[str, str]]:
    """
    Returns {"modules": {module_key: "read"|"write"}} for an
    organization_admin owner or a `users` account. Never call this for
    a super_admin or platform_soc_analyst -- see the module docstring.
    """
    org_module_rows = (
        await db.execute(
            select(OrganizationModule).where(OrganizationModule.organization_id == organization.id)
        )
    ).scalars().all()
    org_enabled = {row.module_key: row.enabled for row in org_module_rows}

    if isinstance(account, Admin):
        modules: dict[str, str] = {}
        for key in ALL_MODULE_KEYS:
            if not org_enabled.get(key, False):
                continue
            if key in (ModuleKey.soc.value, ModuleKey.incidents.value) and organization.soc_mode == SocMode.managed:
                modules[key] = ACCESS_READ
            else:
                modules[key] = ACCESS_WRITE
        return {"modules": modules}

    role_defaults = ROLE_DEFAULT_MODULES.get(account.role, {})
    gated = SOC_MODE_GATED_MODULES.get(account.role, set())

    role_access_rows = (
        await db.execute(
            select(OrganizationRoleAccess).where(
                OrganizationRoleAccess.organization_id == organization.id,
                OrganizationRoleAccess.role == account.role,
            )
        )
    ).scalars().all()
    # A row with enabled=False narrows; a row with enabled=True (or no
    # row at all) means "use the role default" -- never grants beyond it.
    role_access_denied = {row.module_key for row in role_access_rows if not row.enabled}

    user_override_rows = (
        await db.execute(
            select(UserAccessOverride).where(UserAccessOverride.user_id == account.id)
        )
    ).scalars().all()
    # Same shape: allowed=False narrows; allowed=True is a no-op.
    user_denied = {row.module_key for row in user_override_rows if not row.allowed}

    modules = {}
    for key, level in role_defaults.items():
        if not org_enabled.get(key, False):
            continue
        if key in gated and organization.soc_mode != SocMode.in_house:
            continue
        if key in role_access_denied:
            continue
        if key in user_denied:
            continue
        modules[key] = level

    return {"modules": modules}


def _forbidden(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"code": code, "message": message})


async def require_super_admin(scope: Scope = Depends(org_scope)) -> Scope:
    if scope.role != AdminLevel.super_admin.value:
        raise _forbidden("super_admin_required", "This action requires the platform super admin account.")
    return scope


async def require_platform_admin(scope: Scope = Depends(org_scope)) -> Scope:
    """Either kind of platform-side staff -- super_admin or platform_soc_analyst."""
    if scope.role not in (AdminLevel.super_admin.value, AdminLevel.platform_soc_analyst.value):
        raise _forbidden("platform_admin_required", "This action requires a platform admin account.")
    return scope


async def require_platform_soc(scope: Scope = Depends(org_scope)) -> Scope:
    if scope.role != AdminLevel.platform_soc_analyst.value:
        raise _forbidden("platform_soc_required", "This action requires a platform SOC analyst account.")
    return scope


async def require_org_owner(scope: Scope = Depends(org_scope)) -> Scope:
    if scope.role != AdminLevel.organization_admin.value:
        raise _forbidden("org_owner_required", "This action requires the organization owner account.")
    return scope


async def require_active_organization(
    scope: Scope = Depends(org_scope), db: AsyncSession = Depends(get_db)
) -> Scope:
    """
    403s an organization_admin or `users` account whose own organization
    isn't active. Platform admin accounts (organization_id is always
    None for them) are exempt -- they reach pending/suspended/archived
    organizations through /admin/* endpoints, which don't depend on this.

    GET /auth/me and the owner's GET /organization overview deliberately
    do NOT use this dependency: they're the two endpoints that must keep
    working regardless of status, so the frontend has something to read
    in order to show the right pending/suspended/archived screen at all.
    """
    if scope.organization_id is None:
        return scope

    organization = await db.get(Organization, scope.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail={"code": "organization_not_found", "message": "Organization not found."})

    if organization.status == OrganizationStatus.pending:
        raise _forbidden("organization_pending", "Your organization is awaiting platform approval.")
    if organization.status == OrganizationStatus.suspended:
        raise _forbidden("organization_suspended", "Your organization has been suspended.")
    if organization.status == OrganizationStatus.archived:
        raise _forbidden("organization_archived", "Your organization has been archived.")
    return scope


def require_module(key: str, write: bool = False):
    """
    Dependency factory: 403s unless the caller's effective access
    includes `key` (at "write" level if write=True). super_admin and
    platform_soc_analyst always pass here -- their own /admin/*
    endpoints gate them elsewhere; this is for organization_admin and
    `users` accounts.
    """

    async def _check(
        scope: Scope = Depends(org_scope), db: AsyncSession = Depends(get_db)
    ) -> Scope:
        if scope.account_type == "admin" and scope.role != AdminLevel.organization_admin.value:
            return scope

        organization = await db.get(Organization, scope.organization_id)
        if organization is None:
            raise HTTPException(status_code=404, detail={"code": "organization_not_found", "message": "Organization not found."})

        access = await get_effective_access(db, scope.account, organization)
        level = access["modules"].get(key)
        if level is None or (write and level != ACCESS_WRITE):
            raise _forbidden("module_not_available", "You do not have access to this feature.")
        return scope

    return _check


async def soc_visible_organization_ids(
    db: AsyncSession, scope: Scope
) -> list[uuid.UUID] | None:
    """
    Which organizations' SOC data (alerts/incidents) `scope` may see:
      - super_admin: None, meaning "every organization" (the same
        convention scope.organization_id already uses for them).
      - platform_soc_analyst: their assigned organizations that are
        currently soc_mode=managed and status=active.
      - an organization_admin/`users` account: [their own organization]
        if soc_mode == in_house, else [] -- a managed organization's own
        accounts have no SOC visibility at all, platform SOC staff do.
      - anything else: [].
    """
    if scope.role == AdminLevel.super_admin.value:
        return None

    if scope.role == AdminLevel.platform_soc_analyst.value:
        rows = (
            await db.execute(
                select(SocOrganizationAssignment.organization_id)
                .join(Organization, Organization.id == SocOrganizationAssignment.organization_id)
                .where(
                    SocOrganizationAssignment.admin_id == scope.user_id,
                    Organization.soc_mode == SocMode.managed,
                    Organization.status == OrganizationStatus.active,
                )
            )
        ).scalars().all()
        return list(rows)

    if scope.organization_id is None:
        return []

    organization = await db.get(Organization, scope.organization_id)
    if organization is None or organization.soc_mode != SocMode.in_house:
        return []
    return [scope.organization_id]
