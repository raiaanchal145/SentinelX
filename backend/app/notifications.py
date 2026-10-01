"""
Notifications (P16, docs/API_CONTRACT.md "Notifications").

One service (`notify`) other code calls instead of ad-hoc sends:

    await notify(db, "ticket.assigned", organization_id=..., payload={...})

The service resolves the event's RECIPIENTS (routing differs by soc
mode: a managed org's ticket events go to the assigned platform SOC
analysts, an in-house org's to its own soc_analyst -- plus the owner
and the ticket's IT assignee where the event says so), consults each
recipient's preferences (opt-out: a missing preference row means all
channels ON), writes the in-app rows, and enqueues the emails through
the worker. Email failures NEVER fail the action -- enqueue_work
already swallows Redis errors, and the worker's send job retries then
logs.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Admin,
    AdminLevel,
    ActorType,
    Notification,
    NotificationChannel,
    NotificationPreference,
    SocMode,
    SocOrganizationAssignment,
    User,
    UserRole,
)
from app.worker.queue import enqueue_work

logger = logging.getLogger("sentinelx.notifications")

# ---------------------------------------------------------------------------
# Event templates. One entry per event key: who gets it (a routing rule),
# and how to render title/body from the payload. Adding an event = adding
# a row here + calling notify() from the code that causes it.
# ---------------------------------------------------------------------------


@dataclass
class EventTemplate:
    title: str  # a format string over the payload
    body: str | None = None
    # Extra recipients beyond the base SOC-of-the-org route, by role tag.
    with_owner: bool = False
    with_it_assignee: bool = False


EVENTS: dict[str, EventTemplate] = {
    "ticket.assigned": EventTemplate(
        title="Ticket {ticket_number} assigned to you",
        body="{ticket_title}",
        with_it_assignee=True,
    ),
    "ticket.needs_verification": EventTemplate(
        title="Ticket {ticket_number} awaits verification",
        body="{ticket_title} -- IT submitted the fix for verification.",
        with_owner=True,
    ),
    "ticket.verification_failed": EventTemplate(
        title="Ticket {ticket_number} failed verification",
        body="{ticket_title} -- back to INVESTIGATING.",
        with_it_assignee=True,
        with_owner=True,
    ),
    "ticket.reopened": EventTemplate(
        title="Ticket {ticket_number} reopened",
        body="{ticket_title} -- the resolve clock restarts.",
        with_it_assignee=True,
        with_owner=True,
    ),
    "ticket.sla_at_risk": EventTemplate(
        title="Ticket {ticket_number} SLA at risk",
        body="{ticket_title} -- 80% of the resolve window elapsed.",
        with_owner=True,
    ),
    "ticket.sla_breached": EventTemplate(
        title="Ticket {ticket_number} SLA breached",
        body="{ticket_title} -- the resolve deadline passed.",
        with_owner=True,
    ),
    "approval.requested": EventTemplate(
        title="Approval requested: {action_type}",
        body="A {action_type} approval for {organization_name} needs a decision.",
    ),
    "approval.decided": EventTemplate(
        title="Approval {decision}: {action_type}",
        body=None,
    ),
    "invitation.resend": EventTemplate(
        title="Invitation re-sent",
        body="An invitation to join {organization_name} was re-sent to {email}.",
    ),
    "alert.high_severity": EventTemplate(
        title="{severity} alert: {alert_title}",
        body="{alert_description}",
    ),
}

PREFERENCE_EVENT_KEYS = sorted(EVENTS.keys())


@dataclass
class ResolvedRecipients:
    """Who an event goes to: (actor_type, account_id) pairs for in-app
    rows, and email addresses for the worker's send job."""

    in_app: list[tuple[ActorType, uuid.UUID]] = field(default_factory=list)
    emails: dict[str, tuple[ActorType, uuid.UUID]] = field(default_factory=dict)  # email -> owner-of-that-inbox


async def _org_soc_recipients(db: AsyncSession, organization_id: uuid.UUID) -> list[tuple[ActorType, uuid.UUID]]:
    """The SOC of the organization, by soc mode: a MANAGED org's events
    go to the platform SOC analysts assigned to it; an IN_HOUSE org's
    to its own soc_analyst users."""
    from app.models import Organization

    org = await db.get(Organization, organization_id)
    if org is None:
        return []

    recipients: list[tuple[ActorType, uuid.UUID]] = []
    if org.soc_mode == SocMode.managed:
        rows = (
            await db.execute(
                select(SocOrganizationAssignment.admin_id).where(
                    SocOrganizationAssignment.organization_id == organization_id
                )
            )
        ).scalars().all()
        recipients = [(ActorType.admin, admin_id) for admin_id in rows]
    else:
        rows = (
            await db.execute(
                select(User.id).where(
                    User.organization_id == organization_id,
                    User.role == UserRole.soc_analyst,
                    User.is_active.is_(True),
                )
            )
        ).scalars().all()
        recipients = [(ActorType.user, user_id) for user_id in rows]
    return recipients


async def _org_owner(db: AsyncSession, organization_id: uuid.UUID) -> tuple[ActorType, uuid.UUID] | None:
    owner = (
        await db.execute(
            select(Admin.id).where(
                Admin.organization_id == organization_id,
                Admin.admin_level == AdminLevel.organization_admin,
            )
        )
    ).scalar_one_or_none()
    return (ActorType.admin, owner) if owner else None


async def _it_assignee(db: AsyncSession, ticket_id: uuid.UUID) -> tuple[ActorType, uuid.UUID] | None:
    from app.models import Ticket

    ticket = await db.get(Ticket, ticket_id)
    if ticket is None or ticket.assigned_user_id is None:
        return None
    return (ActorType.user, ticket.assigned_user_id)


async def resolve_recipients(
    db: AsyncSession,
    event_key: str,
    *,
    organization_id: uuid.UUID,
    payload: dict[str, Any],
) -> ResolvedRecipients:
    """The routing table. The base route is the org's SOC (by soc mode);
    templates add the owner and/or the ticket's IT assignee."""
    template = EVENTS[event_key]
    resolved = ResolvedRecipients()

    seen: set[tuple[ActorType, uuid.UUID]] = set()
    for recipient in await _org_soc_recipients(db, organization_id):
        if recipient not in seen:
            seen.add(recipient)
            resolved.in_app.append(recipient)

    if template.with_owner:
        owner = await _org_owner(db, organization_id)
        if owner and owner not in seen:
            seen.add(owner)
            resolved.in_app.append(owner)

    if template.with_it_assignee and payload.get("ticket_id"):
        assignee = await _it_assignee(db, payload["ticket_id"])
        if assignee and assignee not in seen:
            seen.add(assignee)
            resolved.in_app.append(assignee)

    # Email addresses: look each recipient up once. Admins have Admin.email,
    # users have User.email.
    for actor_type, account_id in resolved.in_app:
        email = await _account_email(db, actor_type, account_id)
        if email:
            resolved.emails[email] = (actor_type, account_id)
    return resolved


async def _account_email(db: AsyncSession, actor_type: ActorType, account_id: uuid.UUID) -> str | None:
    if actor_type == ActorType.admin:
        row = await db.get(Admin, account_id)
    else:
        row = await db.get(User, account_id)
    return getattr(row, "email", None)


async def _preferences_for(
    db: AsyncSession, actor_type: ActorType, account_id: uuid.UUID
) -> dict[str, NotificationPreference]:
    rows = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.account_type == actor_type,
                NotificationPreference.account_id == account_id,
            )
        )
    ).scalars().all()
    return {row.event_key: row for row in rows}


def _channel_enabled(prefs: dict[str, NotificationPreference], event_key: str, channel: NotificationChannel) -> bool:
    """Opt-out: a missing row means ON; an explicit row decides."""
    pref = prefs.get(event_key)
    if pref is None:
        return True
    return pref.in_app if channel == NotificationChannel.in_app else pref.email


def render_event(event_key: str, payload: dict[str, Any]) -> tuple[str, str | None]:
    template = EVENTS[event_key]
    safe_payload: dict[str, Any] = {k: ("" if v is None else v) for k, v in payload.items()}
    title = template.title.format(**{**safe_payload, "event_key": event_key})
    body = template.body.format(**safe_payload) if template.body else None
    return title[:200], body


async def notify(
    db: AsyncSession,
    event_key: str,
    *,
    organization_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
) -> int:
    """The one door. Returns the number of in-app rows written. Safe to
    call from request handlers and worker jobs alike: rendering issues
    or a down Redis log and return instead of raising, because a
    notification must never fail the action that caused it."""
    payload = payload or {}
    if event_key not in EVENTS:
        logger.warning("Unknown notification event key %r -- skipping.", event_key)
        return 0

    try:
        title, body = render_event(event_key, payload)
        recipients = await resolve_recipients(db, event_key, organization_id=organization_id, payload=payload)

        written = 0
        email_jobs: list[dict[str, Any]] = []
        for actor_type, account_id in recipients.in_app:
            prefs = await _preferences_for(db, actor_type, account_id)
            if _channel_enabled(prefs, event_key, NotificationChannel.in_app):
                db.add(
                    Notification(
                        organization_id=organization_id,
                        recipient_type=actor_type,
                        recipient_id=account_id,
                        channel=NotificationChannel.in_app,
                        title=title,
                        body=body,
                        template_key=event_key,
                        related_type=payload.get("related_type"),
                        related_id=payload.get("related_id"),
                    )
                )
                written += 1
            if _channel_enabled(prefs, event_key, NotificationChannel.email):
                email = next(
                    (e for e, owner in recipients.emails.items() if owner == (actor_type, account_id)),
                    None,
                )
                if email:
                    email_jobs.append(
                        {
                            "organization_id": str(organization_id),
                            "to_email": email,
                            "event_key": event_key,
                            "title": title,
                            "body": body,
                        }
                    )

        if email_jobs:
            for job in email_jobs:
                await enqueue_work("send_notification_email", **job)

        return written
    except Exception:  # noqa: BLE001 -- notifications must never raise
        logger.exception("notify(%s) failed -- the action continues.", event_key)
        return 0
