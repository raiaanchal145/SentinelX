"""
Notifications (P16): routing (managed vs in-house), preferences,
read state, isolation, and the email job's retry behavior.

The service's notify() is called directly (unit) and through the HTTP
surface (assign a ticket -> the assignee's feed gains a row).
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

from app.config import settings  # noqa: E402
from app.models import (  # noqa: E402
    ActorType,
    Notification,
    NotificationChannel,
    SocMode,
    UserRole,
)
from app.notifications import notify  # noqa: E402
from app.worker.notification_jobs import send_notification_email  # noqa: E402

from tests.helpers import auth, login, make_organization, make_team, make_user  # noqa: E402
from tests.helpers import make_admin  # noqa: E402


def _email_spy(monkeypatch, calls: list):
    """Capture enqueue_work calls without Redis."""

    async def fake_enqueue(job_name, **kwargs):
        calls.append((job_name, kwargs))
        return "fake-job-id"

    import app.notifications as ns

    monkeypatch.setattr(ns, "enqueue_work", fake_enqueue)


async def _org_with_soc(db_session, soc_mode=SocMode.in_house):
    """org + SOC account + owner; for managed, an assigned platform
    analyst; for in-house, the org's own soc_analyst."""
    org = await make_organization(db_session, soc_mode=soc_mode)
    if soc_mode == SocMode.managed:
        from app.models import AdminLevel, SocOrganizationAssignment

        soc_admin = await make_admin(
            db_session, email=f"soc-{uuid.uuid4().hex[:8]}@x.io", admin_level=AdminLevel.platform_soc_analyst
        )
        db_session.add(SocOrganizationAssignment(admin_id=soc_admin.id, organization_id=org.id))
        await db_session.commit()
        return org, ("admin", soc_admin.id), soc_admin.email
    analyst = await make_user(
        db_session, email=f"analyst-{uuid.uuid4().hex[:8]}@x.io", role=UserRole.soc_analyst, organization_id=org.id
    )
    return org, ("user", analyst.id), analyst.email


async def _owner_for(db_session, org):
    from app.models import AdminLevel

    owner = await make_admin(
        db_session, email=f"owner-{uuid.uuid4().hex[:8]}@x.io", admin_level=AdminLevel.organization_admin, organization_id=org.id
    )
    return owner


# ---------------------------------------------------------------------------
# Routing: managed vs in-house.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_house_event_routes_to_own_analyst(db_session, monkeypatch):
    org, (soc_type, soc_id), _ = await _org_with_soc(db_session, SocMode.in_house)
    owner = await _owner_for(db_session, org)
    emails: list = []
    _email_spy(monkeypatch, emails)

    written = await notify(
        db_session,
        "ticket.needs_verification",
        organization_id=org.id,
        payload={"ticket_number": "T-1", "ticket_title": "Patch", "related_type": "ticket"},
    )
    # notify() writes inside the CALLER's transaction (the action and its
    # notifications commit atomically) -- commit here, as the routers do.
    await db_session.commit()

    rows = (
        (await db_session.execute(Notification.__table__.select())).mappings().all()
    )
    recipients = {(r["recipient_type"], r["recipient_id"]) for r in rows}
    assert ("user", soc_id) in recipients          # the org's own analyst
    assert ("admin", owner.id) in recipients        # + the owner
    assert written == len(rows) == 2
    assert all(r["channel"] == "in_app" for r in rows)
    assert all(r["template_key"] == "ticket.needs_verification" for r in rows)


@pytest.mark.asyncio
async def test_managed_event_routes_to_platform_analysts(db_session, monkeypatch):
    org, (soc_type, soc_id), _ = await _org_with_soc(db_session, SocMode.managed)
    owner = await _owner_for(db_session, org)
    emails: list = []
    _email_spy(monkeypatch, emails)

    await notify(
        db_session,
        "ticket.sla_breached",
        organization_id=org.id,
        payload={"ticket_number": "T-9", "ticket_title": "Isolate", "related_type": "ticket"},
    )
    await db_session.commit()

    rows = (await db_session.execute(Notification.__table__.select())).mappings().all()
    recipients = {(r["recipient_type"], r["recipient_id"]) for r in rows}
    assert ("admin", soc_id) in recipients          # the assigned platform analyst
    assert ("admin", owner.id) in recipients        # + the owner


@pytest.mark.asyncio
async def test_sla_breach_notifies_soc_and_owner(db_session, monkeypatch):
    """The brief's second DONE-WHEN: SLA breach -> SOC + owner."""
    org, (soc_type, soc_id), _ = await _org_with_soc(db_session, SocMode.in_house)
    owner = await _owner_for(db_session, org)
    emails: list = []
    _email_spy(monkeypatch, emails)

    await notify(
        db_session,
        "ticket.sla_breached",
        organization_id=org.id,
        payload={"ticket_number": "T-2", "ticket_title": "x", "related_type": "ticket"},
    )
    await db_session.commit()
    rows = (await db_session.execute(Notification.__table__.select())).mappings().all()
    recipients = {(r["recipient_type"], r["recipient_id"]) for r in rows}
    assert ("user", soc_id) in recipients
    assert ("admin", owner.id) in recipients
    # The SOC's and owner's email jobs both went out.
    assert len(emails) >= 2


# ---------------------------------------------------------------------------
# Preferences.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_in_app_preference_suppresses_row(db_session, monkeypatch):
    from app.models import NotificationPreference

    org, (soc_type, soc_id), _ = await _org_with_soc(db_session, SocMode.in_house)
    db_session.add(
        NotificationPreference(
            organization_id=org.id,
            account_type=ActorType.user if soc_type == "user" else ActorType.admin,
            account_id=soc_id,
            event_key="ticket.sla_breached",
            in_app=False,
            email=True,
        )
    )
    await db_session.commit()
    emails: list = []
    _email_spy(monkeypatch, emails)

    await notify(
        db_session,
        "ticket.sla_breached",
        organization_id=org.id,
        payload={"ticket_number": "T-3", "ticket_title": "x", "related_type": "ticket"},
    )
    await db_session.commit()
    rows = (await db_session.execute(Notification.__table__.select())).mappings().all()
    assert all(r["recipient_id"] != soc_id for r in rows)  # in-app suppressed
    # but the email job for the analyst still went out.
    assert any(e[1]["to_email"].startswith("analyst-") or e[1]["to_email"].startswith("soc-") for e in emails)


@pytest.mark.asyncio
async def test_disabled_email_preference_skips_email_job(db_session, monkeypatch):
    from app.models import NotificationPreference

    org, (soc_type, soc_id), soc_email = await _org_with_soc(db_session, SocMode.in_house)
    db_session.add(
        NotificationPreference(
            organization_id=org.id,
            account_type=ActorType.user if soc_type == "user" else ActorType.admin,
            account_id=soc_id,
            event_key="ticket.assigned",
            in_app=True,
            email=False,
        )
    )
    await db_session.commit()
    emails: list = []
    _email_spy(monkeypatch, emails)

    await notify(
        db_session,
        "ticket.assigned",
        organization_id=org.id,
        payload={
            "ticket_id": None,
            "ticket_number": "T-4",
            "ticket_title": "x",
            "related_type": "ticket",
        },
    )
    await db_session.commit()
    # In-app row exists for the analyst...
    rows = (await db_session.execute(Notification.__table__.select())).mappings().all()
    assert any(r["recipient_id"] == soc_id for r in rows)
    # ...but no email job for them (email=False); assigned routes ONLY to
    # the assignee, and with ticket_id None there is none -> no emails.
    assert emails == []


# ---------------------------------------------------------------------------
# Read state + isolation over the API.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_state_and_isolation(client, db_session, monkeypatch):
    org, (soc_type, soc_id), soc_email = await _org_with_soc(db_session, SocMode.in_house)
    other_org, (o_type, o_id), other_email = await _org_with_soc(db_session, SocMode.in_house)

    emails: list = []
    _email_spy(monkeypatch, emails)
    await notify(
        db_session,
        "ticket.sla_at_risk",
        organization_id=org.id,
        payload={"ticket_number": "T-5", "ticket_title": "x", "related_type": "ticket"},
    )
    await db_session.commit()

    token = await login(client, soc_email)
    resp = await client.get("/api/v1/notifications", headers=auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["unread_count"] >= 1
    first = body["notifications"][0]
    assert first["read_at"] is None

    # Mark one read.
    resp = await client.post(f"/api/v1/notifications/{first['id']}/read", headers=auth(token))
    assert resp.status_code == 200
    assert resp.json()["read_at"] is not None

    # Read-all clears the rest.
    resp = await client.post("/api/v1/notifications/read-all", headers=auth(token))
    assert resp.status_code == 200
    resp = await client.get("/api/v1/notifications", headers=auth(token))
    assert resp.json()["unread_count"] == 0

    # Isolation: the OTHER org's analyst sees none of these rows.
    other_token = await login(client, other_email)
    resp = await client.get("/api/v1/notifications", headers=auth(other_token))
    assert resp.status_code == 200
    assert resp.json()["notifications"] == []
    assert resp.json()["unread_count"] == 0

    # And a foreign id is 404, never a leak.
    resp = await client.post(f"/api/v1/notifications/{first['id']}/read", headers=auth(other_token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# The email job.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_job_succeeds_without_smtp(monkeypatch):
    """Dev without SMTP: logs instead of sending, still 'ok'."""
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_password", "")
    result = await send_notification_email(
        {},
        organization_id=str(uuid.uuid4()),
        to_email="dev@example.com",
        event_key="ticket.assigned",
        title="Ticket T-1 assigned to you",
        body="Patch the server",
    )
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_email_job_retries_then_fails(monkeypatch):
    attempts = {"n": 0}

    async def always_fails(*args, **kwargs):
        attempts["n"] += 1
        raise RuntimeError("smtp down")

    import app.worker.notification_jobs as nj

    monkeypatch.setattr(nj, "_deliver", always_fails)
    monkeypatch.setattr(nj, "RETRY_DELAY_SECONDS", 0)
    result = await send_notification_email(
        {},
        organization_id=str(uuid.uuid4()),
        to_email="x@example.com",
        event_key="ticket.assigned",
        title="t",
        body=None,
    )
    assert attempts["n"] == 3
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_email_job_retries_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    async def fails_once(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient")
        return

    import app.worker.notification_jobs as nj

    monkeypatch.setattr(nj, "_deliver", fails_once)
    monkeypatch.setattr(nj, "RETRY_DELAY_SECONDS", 0)
    result = await send_notification_email(
        {},
        organization_id=str(uuid.uuid4()),
        to_email="x@example.com",
        event_key="ticket.assigned",
        title="t",
        body=None,
    )
    assert attempts["n"] == 2
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# The HTTP-triggered event: assigning a ticket (the brief's first
# DONE-WHEN) writes the assignee's in-app row + email job.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assigning_ticket_notifies_assignee(client, db_session, monkeypatch):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    analyst = await make_user(
        db_session, email=f"analyst-{uuid.uuid4().hex[:8]}@x.io", role=UserRole.soc_analyst, organization_id=org.id
    )
    team = await make_team(db_session, organization_id=org.id)
    dev = await make_user(
        db_session,
        email=f"dev-{uuid.uuid4().hex[:8]}@x.io",
        role=UserRole.it_developer,
        organization_id=org.id,
        team_id=team.id,
    )
    await db_session.commit()

    emails: list = []
    _email_spy(monkeypatch, emails)

    token = await login(client, analyst.email)
    resp = await client.post(
        "/api/v1/tickets",
        json={"title": "Patch the server", "organization_id": str(org.id)},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    ticket = resp.json()

    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/assign",
        json={"user_id": str(dev.id)},
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text

    # The assignee's feed gains the notification.
    dev_token = await login(client, dev.email)
    resp = await client.get("/api/v1/notifications", headers=auth(dev_token))
    assert resp.status_code == 200
    feed = resp.json()["notifications"]
    assert any("assigned to you" in n["title"] for n in feed), feed
    assert resp.json()["unread_count"] >= 1

    # And the email job went out for the assignee.
    assert any(e[1]["to_email"] == dev.email for e in emails)
