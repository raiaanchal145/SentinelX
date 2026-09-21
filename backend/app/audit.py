"""
The one place an audit_logs row gets written. Every state-changing
endpoint calls write_audit_log() (or the audit_from_scope() convenience
wrapper) once it knows the change succeeded -- it only adds the row to
the session; the caller's own db.commit() is what persists it, same as
every other write in this codebase.

audit_logs is append-only (see the model's own docstring) and its
organization_id FK is ON DELETE RESTRICT, so nothing here ever needs to
worry about an organization disappearing out from under its history.
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActorType, AuditLog
from app.scope import Scope


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    # Trust the reverse proxy's forwarded header before falling back to
    # the direct peer -- same precedence used anywhere else in this app
    # that has needed a client IP.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def write_audit_log(
    db: AsyncSession,
    *,
    actor_type: ActorType,
    actor_id: uuid.UUID | None,
    action: str,
    organization_id: uuid.UUID | None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    request: Request | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """
    Adds (does not commit) one audit_logs row. `action` is a short,
    stable, machine-greppable string ("organization.suspend",
    "invitation.revoke", "member.role_change", ...) -- pick one style and
    keep endpoints consistent so docs/API_CONTRACT.md's action list stays
    accurate. `before`/`after` are short plain-dict summaries of what
    changed, not full row dumps -- e.g. {"status": "active"} /
    {"status": "suspended", "reason": "..."}.
    """
    details: dict[str, Any] | None = None
    if before is not None or after is not None:
        details = {}
        if before is not None:
            details["before"] = before
        if after is not None:
            details["after"] = after

    entry = AuditLog(
        organization_id=organization_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent") if request is not None else None,
        details=details,
    )
    db.add(entry)
    return entry


async def audit_from_scope(
    db: AsyncSession,
    scope: Scope,
    action: str,
    *,
    organization_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    request: Request | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """
    Convenience wrapper for the common case: the actor is whoever the
    request's Scope resolved to. Defaults organization_id to the scope's
    own organization_id (right for an owner or a `users` account acting
    on their own organization); pass it explicitly for a platform admin
    acting on a *different* organization's data, since a super_admin's
    or platform_soc_analyst's own scope.organization_id is always None.
    """
    actor_type = ActorType.admin if scope.account_type == "admin" else ActorType.user
    return await write_audit_log(
        db,
        actor_type=actor_type,
        actor_id=scope.user_id,
        action=action,
        organization_id=organization_id if organization_id is not None else scope.organization_id,
        target_type=target_type,
        target_id=target_id,
        request=request,
        before=before,
        after=after,
    )
