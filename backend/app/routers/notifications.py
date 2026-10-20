"""
Notifications API (P16, docs/API_CONTRACT.md "Notifications").

GET   /api/v1/notifications           -- the caller's in-app feed (cursor
                                        pagination, unread first).
POST  /api/v1/notifications/{id}/read -- mark one read (own only).
POST  /api/v1/notifications/read-all  -- mark everything read.
GET   /api/v1/notifications/preferences -- the caller's channel switches
                                        (missing rows resolve to all-on).
PUT   /api/v1/notifications/preferences -- upsert per-event switches.

Isolation is absolute: every query filters on (recipient_type,
recipient_id) == the caller's own account, so a notification is only
ever readable by the account it was written for.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    ActorType,
    Notification,
    NotificationChannel,
    NotificationPreference,
)
from app.notifications import PREFERENCE_EVENT_KEYS
from app.scope import Scope, org_scope

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

PAGE_SIZE = 30


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


# FastAPI needs the name imported at module scope; local alias to keep
# the router block tidy.
from fastapi import HTTPException  # noqa: E402


def _caller(scope: Scope) -> tuple[ActorType, uuid.UUID]:
    """The polymorphic account pair for the caller -- notifications are
    keyed by the same (actor_type, actor_id) the service writes."""
    return (
        ActorType.admin if scope.account_type == "admin" else ActorType.user,
        scope.user_id,
    )


def _encode_cursor(created_at: datetime, id_: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{id_}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_at_raw, id_raw = raw.split("|", 1)
        return datetime.fromisoformat(created_at_raw), uuid.UUID(id_raw)
    except Exception as exc:  # noqa: BLE001 -- any malformed cursor is 400
        raise _err("invalid_cursor", "Invalid pagination cursor.", 400) from exc


@router.get("")
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(org_scope),
    unread_only: bool = Query(default=False),
    cursor: str | None = None,
    limit: int = Query(default=PAGE_SIZE, ge=1, le=100),
):
    """The caller's in-app feed. Unread first (ordered oldest-first so
    the oldest unread surfaces at the top of the badge queue), then read
    (newest-first) -- the keyset cursor runs over (read_at NULLS FIRST
    ordering, created_at, id)."""
    actor_type, account_id = _caller(scope)

    stmt = select(Notification).where(
        Notification.recipient_type == actor_type,
        Notification.recipient_id == account_id,
        Notification.channel == NotificationChannel.in_app,
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))

    if cursor:
        # The cursor pins the position in the (is_read, created_at, id)
        # keyset; fetching continues strictly after it.
        cursor_created_at, cursor_id = _decode_cursor(cursor)
        cursor_row = (
            await db.execute(
                select(Notification).where(Notification.id == cursor_id)
            )
        ).scalar_one_or_none()
        if cursor_row is None:
            raise _err("invalid_cursor", "The cursor's notification no longer exists.", 400)
        cursor_is_read = cursor_row.read_at is not None

        # Order key: (is_read ASC -- unread first, created_at DESC within
        # each group, id DESC as tiebreaker).
        if cursor_is_read:
            stmt = stmt.where(
                (Notification.read_at.isnot(None))
                & (
                    (Notification.created_at < cursor_row.created_at)
                    | (
                        (Notification.created_at == cursor_row.created_at)
                        & (Notification.id < cursor_id)
                    )
                )
            )
        else:
            stmt = stmt.where(
                (Notification.read_at.is_(None))
                & (
                    (Notification.created_at < cursor_row.created_at)
                    | (
                        (Notification.created_at == cursor_row.created_at)
                        & (Notification.id < cursor_id)
                    )
                )
            )

        # When the cursor sits in the read section, unread rows (which
        # sort before every read row) would be skipped by the filter
        # above -- the caller has already seen them, so that's correct.

    stmt = stmt.order_by(
        Notification.read_at.isnot(None).asc(),  # unread (NULL) first
        Notification.created_at.desc(),
        Notification.id.desc(),
    )
    rows = (await db.execute(stmt.limit(limit + 1))).scalars().all()

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    unread_count = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.recipient_type == actor_type,
                Notification.recipient_id == account_id,
                Notification.channel == NotificationChannel.in_app,
                Notification.read_at.is_(None),
            )
        )
    ).scalar_one()

    return {
        "notifications": [_row(n) for n in rows],
        "unread_count": unread_count,
        "next_cursor": next_cursor,
    }


def _row(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "title": n.title,
        "body": n.body,
        "template_key": n.template_key,
        "related_type": n.related_type,
        "related_id": str(n.related_id) if n.related_id else None,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(org_scope),
):
    actor_type, account_id = _caller(scope)
    notification = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.recipient_type == actor_type,
                Notification.recipient_id == account_id,
            )
        )
    ).scalar_one_or_none()
    if notification is None:
        raise _err("notification_not_found", "Notification not found.", 404)

    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        await db.commit()
    return _row(notification)


@router.post("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(org_scope),
):
    actor_type, account_id = _caller(scope)
    rows = (
        await db.execute(
            select(Notification).where(
                Notification.recipient_type == actor_type,
                Notification.recipient_id == account_id,
                Notification.read_at.is_(None),
            )
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for notification in rows:
        notification.read_at = now
    await db.commit()
    return {"updated": len(rows)}


# ---------------------------------------------------------------------------
# Preferences.
# ---------------------------------------------------------------------------


class PreferencePayload(BaseModel):
    event_key: str = Field(min_length=1, max_length=80)
    in_app: bool
    email: bool

    @field_validator("event_key")
    @classmethod
    def _known_event(cls, value: str) -> str:
        if value not in PREFERENCE_EVENT_KEYS:
            raise ValueError(f"Unknown event key '{value}'.")
        return value


class PreferencesPayload(BaseModel):
    preferences: list[PreferencePayload]


@router.get("/preferences")
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(org_scope),
):
    """The caller's switches, as the UI should show them: every known
    event key, resolving missing rows to the all-on default."""
    actor_type, account_id = _caller(scope)
    stored = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.account_type == actor_type,
                NotificationPreference.account_id == account_id,
            )
        )
    ).scalars().all()
    by_key = {p.event_key: p for p in stored}

    return {
        "preferences": [
            {
                "event_key": key,
                "in_app": by_key[key].in_app if key in by_key else True,
                "email": by_key[key].email if key in by_key else True,
            }
            for key in PREFERENCE_EVENT_KEYS
        ]
    }


@router.put("/preferences")
async def put_preferences(
    payload: PreferencesPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(org_scope),
):
    """Upsert the caller's switches. Only explicit rows are stored --
    resetting to all-on deletes the row (the default needs no storage)."""
    actor_type, account_id = _caller(scope)
    from app.models import Organization

    organization_id = scope.organization_id
    if organization_id is None:
        raise _err("organization_required", "Notifications are organization-scoped.", 400)
    if await db.get(Organization, organization_id) is None:
        raise _err("organization_not_found", "Organization not found.", 404)

    stored = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.account_type == actor_type,
                NotificationPreference.account_id == account_id,
            )
        )
    ).scalars().all()
    by_key = {p.event_key: p for p in stored}

    updated = 0
    for pref_payload in payload.preferences:
        existing = by_key.get(pref_payload.event_key)
        default_on = pref_payload.in_app and pref_payload.email
        if default_on and existing is not None:
            # Back to the default: drop the row.
            await db.delete(existing)
            updated += 1
            continue
        if default_on:
            continue  # nothing to store
        if existing is not None:
            existing.in_app = pref_payload.in_app
            existing.email = pref_payload.email
            updated += 1
        else:
            db.add(
                NotificationPreference(
                    organization_id=organization_id,
                    account_type=actor_type,
                    account_id=account_id,
                    event_key=pref_payload.event_key,
                    in_app=pref_payload.in_app,
                    email=pref_payload.email,
                )
            )
            updated += 1
    await db.commit()

    # Respond with the resolved view (same shape as GET).
    stored = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.account_type == actor_type,
                NotificationPreference.account_id == account_id,
            )
        )
    ).scalars().all()
    by_key = {p.event_key: p for p in stored}
    return {
        "updated": updated,
        "preferences": [
            {
                "event_key": key,
                "in_app": by_key[key].in_app if key in by_key else True,
                "email": by_key[key].email if key in by_key else True,
            }
            for key in PREFERENCE_EVENT_KEYS
        ],
    }
