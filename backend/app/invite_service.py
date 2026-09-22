"""
Shared helpers for creating an invitation, used by every router that
creates one (admin_organizations.py's platform-created owner invite,
organization.py's member invite, admin_soc.py's platform SOC invite) so
the token/expiry/rate-limit rules live in exactly one place.

Accepting an invitation (the public GET/POST endpoints) lives in
app/routers/invitations.py, not here -- this module is only the
"create one" side.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Invitation
from app.security import generate_invitation_token

INVITATION_TTL_DAYS = 7
MAX_INVITATIONS_PER_ORG_PER_HOUR = 20


def build_invite_link(raw_token: str) -> str:
    """
    The accept-invitation URL put in invitation emails (and printed to
    the console when SMTP isn't configured).

    Reads settings.frontend_url at send time -- never a baked-in
    constant -- so the dev launcher's share mode can repoint email links
    at the LAN IP or tunnel URL for that session (FRONTEND_URL env var),
    and a phone can open the invitation (see README's "Sharing the dev
    environment"). In production this is just FRONTEND_URL from .env.
    """
    return f"{settings.frontend_url.rstrip('/')}/accept-invite?token={raw_token}"


async def check_invitation_rate_limit(db: AsyncSession, organization_id: uuid.UUID | None) -> None:
    """
    At most 20 invitations per organization per hour, counted straight
    from the invitations table (no Redis yet). organization_id is None
    for a platform_soc invitation -- rate-limited per platform instead,
    using the same threshold, so a runaway loop can't spam that path
    either.
    """
    # Invitation.created_at, like every created_at column in this schema
    # (see app/models.py), is a naive TIMESTAMP WITHOUT TIME ZONE
    # populated by Postgres's own now() -- there's no DateTime(timezone=
    # True) on it. asyncpg refuses to bind a tz-aware Python datetime
    # against that column type ("can't subtract offset-naive and
    # offset-aware datetimes"), so `since` has to be stripped to naive
    # UTC to match, not left as datetime.now(timezone.utc).
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
    stmt = select(func.count(Invitation.id)).where(Invitation.created_at >= since)
    stmt = stmt.where(Invitation.organization_id == organization_id) if organization_id is not None else stmt.where(
        Invitation.organization_id.is_(None)
    )
    count = (await db.execute(stmt)).scalar() or 0
    if count >= MAX_INVITATIONS_PER_ORG_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail={"code": "invitation_rate_limited", "message": "Too many invitations sent recently. Please try again later."},
        )


async def create_invitation(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    email: str,
    kind: str,
    invited_by_admin_id: uuid.UUID | None,
    role=None,
    team_id: uuid.UUID | None = None,
) -> tuple[Invitation, str]:
    """
    Adds (does not commit) a new pending Invitation row and returns it
    together with the raw token -- the only place that raw value ever
    exists; only its SHA-256 hash is stored. Caller is responsible for
    checking check_invitation_rate_limit(), for checking that the email
    isn't already a registered account, and for sending the email.
    """
    raw_token, token_hash = generate_invitation_token()
    invitation = Invitation(
        organization_id=organization_id,
        email=email.strip().lower(),
        kind=kind,
        role=role,
        team_id=team_id,
        token_hash=token_hash,
        status="pending",
        invited_by_admin_id=invited_by_admin_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITATION_TTL_DAYS),
    )
    db.add(invitation)
    return invitation, raw_token


def rotate_invitation_token(invitation: Invitation) -> str:
    """
    Resend: a fresh token/expiry on the SAME row (never a new row), which
    is what "single use" plus "resend rotates the token and invalidates
    the old one" means in practice -- the old raw token, even if someone
    still has the email open, no longer hashes to what's stored.
    """
    raw_token, token_hash = generate_invitation_token()
    invitation.token_hash = token_hash
    invitation.expires_at = datetime.now(timezone.utc) + timedelta(days=INVITATION_TTL_DAYS)
    return raw_token
