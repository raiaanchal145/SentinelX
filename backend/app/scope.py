"""
The one place "who is calling, what role, which organization" is
resolved and enforced for every endpoint.

Mirrors the shape of the frontend's src/lib/scope.ts (see
docs/architecture.md) -- except this one is real: the frontend's copy
only decides what the UI shows, and explicitly says so in its own
comments. This module is what actually stops one organization's admin
or analyst from reading or writing another organization's data, so
every endpoint that touches organization-scoped rows must depend on
org_scope (or require_admin / require_roles, which build on it) and
filter its queries with scoped_to_org() -- never trust a client-supplied
organization id.

Exports:
- Scope            resolved (account, role, organization_id) for a request.
                   organization_id is None for a super_admin, meaning
                   "every organization", not "no organization".
- get_current_account   dependency: bearer token -> Admin|User row.
- org_scope        dependency: current account -> full Scope. The base
                   dependency every organization-scoped endpoint should use.
- require_admin    dependency: like org_scope, but 403s a non-admin.
- require_roles(*roles)  dependency factory: like org_scope, but 403s a
                   `users` account whose role isn't one of `roles`
                   (admins always pass -- they aren't restricted by
                   UserRole).
- scoped_to_org(stmt, model, scope)   adds an organization_id filter to
                   a SQLAlchemy select() unless scope.organization_id is
                   None (super_admin).
"""

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Admin, User
from app.security import decode_access_token


@dataclass(frozen=True)
class Scope:
    account: Admin | User
    account_type: str  # "admin" | "user"
    role: str  # AdminLevel or UserRole value
    organization_id: uuid.UUID | None
    user_id: uuid.UUID


async def get_current_account(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Admin | User:
    """
    Resolves the bearer token to whichever table (admins or users) its
    account_type claim points into. This is the one place a token
    becomes a database row -- org_scope wraps the result into a full
    Scope; use that (or require_admin/require_roles) in endpoints rather
    than this directly, unless you genuinely only need "whoever is
    logged in" with no role/org check at all.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated.")

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = decode_access_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")

    account_id = payload.get("sub")
    account_type = payload.get("account_type")

    if not account_id or account_type not in ("admin", "user"):
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")

    model = Admin if account_type == "admin" else User
    result = await db.execute(select(model).where(model.id == account_id))
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")

    return account


async def org_scope(current_account: Admin | User = Depends(get_current_account)) -> Scope:
    """
    The base dependency for any endpoint that reads or writes
    organization-scoped data. super_admin's organization_id is always
    NULL at the database level (enforced by a check constraint on
    admins) -- here that becomes organization_id=None, meaning "every
    organization", never "no organization". organization_admin and every
    `users` role always have a real organization_id.
    """
    if isinstance(current_account, Admin):
        account_type = "admin"
        role = current_account.admin_level.value
        organization_id = current_account.organization_id
    else:
        account_type = "user"
        role = current_account.role.value
        organization_id = current_account.organization_id

    return Scope(
        account=current_account,
        account_type=account_type,
        role=role,
        organization_id=organization_id,
        user_id=current_account.id,
    )


async def require_admin(scope: Scope = Depends(org_scope)) -> Scope:
    """Like org_scope, but rejects anything that isn't an admin account."""
    if scope.account_type != "admin":
        raise HTTPException(status_code=403, detail="This action requires an administrator account.")
    return scope


def require_roles(*roles: str):
    """
    Dependency factory restricting an endpoint to `users` accounts whose
    role is one of `roles` (UserRole values, e.g. "soc_analyst"). Admin
    accounts always pass -- they aren't restricted by UserRole.
    """

    async def _check(scope: Scope = Depends(org_scope)) -> Scope:
        if scope.account_type == "admin":
            return scope
        if scope.role in roles:
            return scope
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")

    return _check


def scoped_to_org(stmt, model, scope: Scope):
    """
    Adds `.where(model.organization_id == scope.organization_id)` to a
    SQLAlchemy select() unless scope.organization_id is None (a
    super_admin, who can see every organization). `model` is the mapped
    class being selected from (or joined in) -- it must have an
    organization_id column, which is true of every organization-scoped
    table in app/models.py.
    """
    if scope.organization_id is None:
        return stmt
    return stmt.where(model.organization_id == scope.organization_id)
