"""The DONE-WHEN walkthrough, pinned end to end (AI SOC Analyst milestone).

One test walks the exact brief's acceptance path over the REAL HTTP
surface with the fake provider (no network):

  simulated brute-force alert
    -> header/cited triage analysis (run_triage_for_alert, fake provider)
    -> analyst ACCEPTS via POST /ai-analyses/{id}/decision
    -> incident created FROM THE ALERT via POST /incidents/from-alerts
       (the alert becomes TRIAGED)
    -> incident agent drafts title/summary/timeline/ticket
    -> the analyst reviews the draft and creates the ticket through the
       normal ticket API, linked to the incident
    -> GET /ai/metrics shows one DECIDED, ACCEPTED analysis.

Nothing here asserts specific model wording -- the fake provider is
deterministic, so the structural contract is what the test pins (this
is the same provider the eval harness runs, per docs/testing.md).
"""

from __future__ import annotations

from sqlalchemy import select

from app.ai.fake import FakeProvider
from app.ai.incident_service import run_incident_draft_for_incident
from app.ai.service import run_triage_for_alert
from app.models import AlertStatus, SocMode, UserRole
from tests.helpers import auth, login, make_user
from tests.test_ai_triage import _alert_with_events, _org_with_ai


async def test_done_flow_triage_accept_incident_ticket_metrics(client, db_session):
    org = await _org_with_ai(db_session, name="Done Flow Org")
    alert, events = await _alert_with_events(
        db_session, org, n_events=2, rule="brute_force"
    )
    soc = await make_user(
        db_session,
        email=f"soc-{org.id}@x.io",
        role=UserRole.soc_analyst,
        organization_id=org.id,
    )
    token = await login(client, soc.email)
    shown_event_ids = {str(e.id) for e in events}

    # ------------------------------------------------------------------
    # 1. Triage: the simulated brute-force alert gets an AI analysis.
    # ------------------------------------------------------------------
    run = await run_triage_for_alert(db_session, alert.id, provider=FakeProvider())
    assert run is not None

    resp = await client.get(
        f"/api/v1/ai/alerts/{alert.id}/analysis", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    analysis = resp.json()["analysis"]
    assert analysis is not None
    assert analysis["source"] == "ai"  # not the rules fallback
    assert analysis["severity_suggestion"] in ("medium", "high", "critical")
    assert 0.0 < analysis["confidence"] <= 1.0
    assert analysis["summary"]
    cited = analysis["evidence_ids"]
    assert cited, "a real analysis cites evidence"
    # Grounding: every citation refers to a record the model actually saw.
    assert set(cited) <= shown_event_ids

    # ------------------------------------------------------------------
    # 2. The analyst accepts the analysis.
    # ------------------------------------------------------------------
    resp = await client.post(
        f"/api/v1/ai-analyses/{analysis['id']}/decision",
        json={"decision": "accepted"},
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text
    decided = resp.json()
    assert decided["decision"]["decision"] == "accepted"
    assert decided["accepted_by_user_id"] == str(soc.id)

    # ------------------------------------------------------------------
    # 3. An incident is created from the accepted alert.
    # ------------------------------------------------------------------
    resp = await client.post(
        "/api/v1/incidents/from-alerts",
        json={
            "alert_ids": [str(alert.id)],
            "title": "SSH brute force -- alice.analyst",
        },
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    incident = resp.json()
    incident_id = incident["id"]
    assert incident["status"] == "NEW"

    await db_session.refresh(alert)
    assert alert.status == AlertStatus.triaged  # alert follows the incident

    # ------------------------------------------------------------------
    # 4. The incident agent drafts title/summary/timeline/ticket.
    # ------------------------------------------------------------------
    draft_run = await run_incident_draft_for_incident(
        db_session, incident_id, provider=FakeProvider()
    )
    assert draft_run is not None

    resp = await client.get(
        f"/api/v1/ai/incidents/{incident_id}/analysis", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    draft = resp.json()["analysis"]
    assert draft is not None and draft["source"] == "ai"
    draft_actions = draft["recommended_actions"]
    assert draft_actions.get("title")
    assert draft_actions.get("timeline_entries")
    ticket_draft = draft_actions.get("ticket_draft")
    assert ticket_draft and ticket_draft["description"]
    # The draft's timeline citations are grounded too.
    for entry in draft_actions.get("timeline_entries", []):
        assert set(entry.get("evidence_ids", [])) <= shown_event_ids

    # ------------------------------------------------------------------
    # 5. The analyst reviews the draft and creates the ticket by hand,
    #    using the draft's description and priority.
    # ------------------------------------------------------------------
    resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": draft_actions["title"],
            "description": ticket_draft["description"],
            "severity": "high",
            "priority": ticket_draft["suggested_priority"],
            "incident_id": incident_id,
        },
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    ticket = resp.json()
    assert ticket["incident_id"] == incident_id
    assert ticket["status"] in ("OPEN", "NEW")  # whatever the API's open state is

    # The incident list row now carries the open-ticket stub.
    listing = await client.get("/api/v1/incidents", headers=auth(token))
    assert listing.status_code == 200, listing.text
    listed = next(
        row for row in listing.json()["incidents"] if row["id"] == incident_id
    )
    assert listed.get("open_ticket", {}).get("id") == ticket["id"]

    # ------------------------------------------------------------------
    # 6. Metrics: ONE accepted analysis, scoped like the alerts API.
    # ------------------------------------------------------------------
    resp = await client.get(
        f"/api/v1/ai/metrics?organization_id={org.id}", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    metrics = resp.json()
    assert metrics["total_analyses"] == 2  # the triage + the incident draft
    assert metrics["ai_analyses"] == 2
    assert metrics["decisions"]["total_decisions"] == 1
    assert metrics["decisions"]["accepted"] == 1
    assert metrics["decisions"]["acceptance_rate"] == 1.0
    assert metrics["decisions"]["average_confidence"] > 0.0
    assert metrics["cost"]["total_spend_usd"] >= 0.0

    # ------------------------------------------------------------------
    # 7. Regeneration: re-running triage/incident draft under cost caps.
    # ------------------------------------------------------------------
    regen_resp = await client.post(
        f"/api/v1/ai/alerts/{alert.id}/regenerate", headers=auth(token)
    )
    assert regen_resp.status_code == 200, regen_resp.text
    assert regen_resp.json()["analysis"] is not None

    regen_inc_resp = await client.post(
        f"/api/v1/ai/incidents/{incident_id}/regenerate", headers=auth(token)
    )
    assert regen_inc_resp.status_code == 200, regen_inc_resp.text
    assert regen_inc_resp.json()["analysis"] is not None
