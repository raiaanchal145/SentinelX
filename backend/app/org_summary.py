"""
Shared "how busy is this organization" counts, used by both the
platform admin's organization list/detail (admin_organizations.py) and
the owner's own overview (organization.py) so the two surfaces can never
quietly drift apart on what a count means.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Admin,
    AdminLevel,
    Asset,
    AuditLog,
    Incident,
    IncidentStatus,
    Invitation,
    Ticket,
    TicketStatus,
    User,
)

CLOSED_INCIDENT_STATUSES = {
    IncidentStatus.resolved, IncidentStatus.closed,
    IncidentStatus.false_positive, IncidentStatus.duplicate,
}
CLOSED_TICKET_STATUSES = {TicketStatus.resolved, TicketStatus.closed}


async def compute_org_counts(db: AsyncSession, organization_id: uuid.UUID) -> dict:
    members = (
        await db.execute(
            select(func.count(Admin.id)).where(
                Admin.organization_id == organization_id,
                Admin.admin_level == AdminLevel.organization_admin,
                Admin.is_active.is_(True),
            )
        )
    ).scalar() or 0
    members += (
        await db.execute(
            select(func.count(User.id)).where(User.organization_id == organization_id, User.is_active.is_(True))
        )
    ).scalar() or 0
    pending_invitations = (
        await db.execute(
            select(func.count(Invitation.id)).where(
                Invitation.organization_id == organization_id, Invitation.status == "pending"
            )
        )
    ).scalar() or 0
    assets = (
        await db.execute(select(func.count(Asset.id)).where(Asset.organization_id == organization_id))
    ).scalar() or 0
    open_incidents = (
        await db.execute(
            select(func.count(Incident.id)).where(
                Incident.organization_id == organization_id,
                ~Incident.status.in_(CLOSED_INCIDENT_STATUSES),
            )
        )
    ).scalar() or 0
    open_tickets = (
        await db.execute(
            select(func.count(Ticket.id)).where(
                Ticket.organization_id == organization_id,
                ~Ticket.status.in_(CLOSED_TICKET_STATUSES),
            )
        )
    ).scalar() or 0
    last_activity = (
        await db.execute(
            select(func.max(AuditLog.created_at)).where(AuditLog.organization_id == organization_id)
        )
    ).scalar()
    return {
        "members": members,
        "pending_invitations": pending_invitations,
        "assets": assets,
        "open_incidents": open_incidents,
        "open_tickets": open_tickets,
        "last_activity_at": last_activity.isoformat() if last_activity else None,
    }


async def active_owner_count(db: AsyncSession, organization_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count(Admin.id)).where(
                Admin.organization_id == organization_id,
                Admin.admin_level == AdminLevel.organization_admin,
                Admin.is_active.is_(True),
            )
        )
    ).scalar() or 0
