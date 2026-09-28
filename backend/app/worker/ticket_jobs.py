"""Ticket SLA worker jobs (P13).

ticket_sla_check (cron, every minute): walks open tickets with
deadlines, marks sla_at_risk (>=80% of the running window elapsed) and
sla_breached (deadline passed), and writes one escalations row per
fresh breach (docs/DECISIONS.md -- at_risk is a flag, breach is an
event). The clock is injectable (`now`) so tests control time
directly; no Redis/asyncio mocking.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select

from app.models import (
    ActorType,
    Escalation,
    Ticket,
    TicketStatus,
)

logger = logging.getLogger("sentinelx.worker")

TERMINAL = {TicketStatus.resolved, TicketStatus.closed}


async def ticket_sla_check(
    ctx: dict[str, Any],
    session_factory=None,
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """One SLA sweep. `now` defaults to the real current time; tests
    pass their own clock. Idempotent: flags are only set (never
    cleared) here, and a breach escalation is written once per ticket
    (guard: sla_breached was still False)."""
    from app.tickets import evaluate_sla_state

    if session_factory is None:
        session_factory = ctx.get("session_factory")
    if session_factory is None:
        from app.database import AsyncSessionLocal

        session_factory = AsyncSessionLocal
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)

    marked_at_risk = 0
    marked_breached = 0
    escalations = 0

    async with session_factory() as db:
        rows = (
            await db.execute(
                select(Ticket).where(
                    Ticket.status.notin_(TERMINAL),
                    Ticket.resolve_due_at.isnot(None),
                )
            )
        ).scalars().all()

        for ticket in rows:
            at_risk, breached = evaluate_sla_state(
                created_at=ticket.created_at or now,
                acknowledged_at=ticket.acknowledged_at,
                ack_due_at=ticket.ack_due_at,
                resolve_due_at=ticket.resolve_due_at,
                resolved_at=ticket.resolved_at,
                now=now,
            )
            if breached and not ticket.sla_breached:
                ticket.sla_breached = True
                ticket.sla_at_risk = True
                marked_breached += 1
                # A breach is an event: one escalation record per ticket.
                already = (
                    await db.execute(
                        select(Escalation.id).where(
                            Escalation.ticket_id == ticket.id,
                            Escalation.reason.like("SLA breach:%"),
                        )
                    )
                ).scalar_one_or_none()
                if already is None:
                    db.add(
                        Escalation(
                            ticket_id=ticket.id,
                            incident_id=ticket.incident_id,
                            reason=f"SLA breach: resolve deadline {ticket.resolve_due_at.isoformat()} passed",
                        )
                    )
                    escalations += 1
            elif at_risk and not ticket.sla_at_risk:
                ticket.sla_at_risk = True
                marked_at_risk += 1

        await db.commit()

    if marked_at_risk or marked_breached:
        logger.info(
            "ticket_sla_check: at_risk=%d breached=%d escalations=%d",
            marked_at_risk,
            marked_breached,
            escalations,
        )
    return {
        "checked": len(rows),
        "marked_at_risk": marked_at_risk,
        "marked_breached": marked_breached,
        "escalations": escalations,
    }
