"""AI triage worker job (AI SOC Analyst milestone).

`ai_triage_alert` runs one alert's triage through app/ai/service.py.
Enqueued by the event pipeline right AFTER the batch's alert commit, so
the job only ever sees committed rows; if Redis is down the enqueue is
dropped (enqueue_work logs it) and the alert simply has no analysis --
ingestion and the queue are never blocked by AI.

The job itself is a thin wrapper on purpose: ALL gating (module flag,
org opt-in, cost caps) and ALL failure handling (fallback analysis,
marked rules) live in the service so the API, the worker and the eval
harness share one code path.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.ai.service import run_triage_for_alert
from app.ai.incident_service import run_incident_draft_for_incident
from app.worker.queue import enqueue_work  # noqa: F401 -- re-exported for tests to patch

logger = logging.getLogger("sentinelx.ai")


async def enqueue_triage_for_alerts(alert_ids: list[uuid.UUID]) -> None:
    """Fire one triage job per NEW alert. Best-effort by contract:
    enqueue failures (Redis down) are logged inside enqueue_work."""
    for alert_id in alert_ids:
        await enqueue_work("ai_triage_alert", alert_id=str(alert_id))


async def ai_triage_alert(ctx: dict[str, Any], *, alert_id: str) -> dict[str, Any]:
    """Worker entry: triage one alert. A vanished alert is a no-op, the
    same resilience every other job here has."""
    from app.database import AsyncSessionLocal

    try:
        alert_uuid = uuid.UUID(alert_id)
    except ValueError:
        logger.warning("ai: triage job got a non-UUID alert_id %r -- dropping", alert_id)
        return {"status": "dropped"}

    async with AsyncSessionLocal() as db:
        run = await run_triage_for_alert(db, alert_uuid)
        if run is None:
            return {"status": "missing_alert"}
        return {"status": run.status, "run_id": str(run.id), "cost_usd": run.cost_usd}


async def enqueue_incident_draft(incident_id: str) -> None:
    """Fire one incident-draft job. Best-effort: an enqueue failure
    (Redis down) only delays the draft, never blocks the incident."""
    await enqueue_work("ai_incident_draft", incident_id=incident_id)


async def ai_incident_draft(ctx: dict[str, Any], *, incident_id: str) -> dict[str, Any]:
    """Worker entry: draft one incident's AI analysis. A vanished
    incident is a no-op. The service is draft-only: nothing is created
    from the model output here."""
    from app.database import AsyncSessionLocal

    try:
        incident_uuid = uuid.UUID(incident_id)
    except ValueError:
        logger.warning("ai: incident job got a non-UUID incident_id %r -- dropping", incident_id)
        return {"status": "dropped"}

    async with AsyncSessionLocal() as db:
        run = await run_incident_draft_for_incident(db, incident_uuid)
        if run is None:
            return {"status": "missing_incident"}
        return {"status": run.status, "run_id": str(run.id), "cost_usd": run.cost_usd}
