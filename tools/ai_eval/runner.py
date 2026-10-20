"""The runner: metrics over the labelled cases + the demo DB pipeline.

Metrics (AI SOC Analyst doc §24/§25 -- false positive/negative
evaluation, reproducibility):
- a case counts as DETECTED when the triage's severity sits at or above
  the expected band floor AND false_positive_likelihood < 0.5;
- precision = detected attacks / flagged cases;
- recall    = detected attacks / attack cases;
- FPR       = flagged benign cases / benign cases;
- avg cost  = mean ESTIMATED dollar cost per case at the production
  model's list prices (the fake provider bills nothing, but the token
  counts are real, so the estimate is what production would spend).

The default provider is the fake one -- `--provider real` calls
OpenAI and needs OPENAI_API_KEY. Tests always use the default.

`run_demo` (DONE WHEN): builds a throwaway organization + alert +
events in the dev database, walks the whole acceptance path through
the REAL HTTP surface (triage analysis -> analyst accepts -> incident
from the alert -> incident-agent draft -> reviewed ticket -> metrics),
then prints the stored ids/blob and deletes the throwaway org (the
dev DB stays as it was found).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
for _p in (str(REPO_ROOT), str(BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.ai.client import estimate_cost_usd
from app.ai.fake import FakeProvider
from app.ai.prompts import build_triage_messages
from app.ai.schemas import TriageValidationError, parse_triage_output
from tools.ai_eval.cases import SEVERITY_ORDER, build_cases


async def _triage_case(case, provider):
    messages = build_triage_messages(case.alert_text, case.events_text, case.asset_text)
    call = await provider.complete(messages)
    prompt_tokens = call.prompt_tokens
    completion_tokens = call.completion_tokens
    try:
        result = parse_triage_output(call.text)
        return result, prompt_tokens, completion_tokens
    except TriageValidationError:
        return None, prompt_tokens, completion_tokens


async def run_eval(provider=None, seed: int = 7) -> dict:
    provider = provider or FakeProvider()
    cases = build_cases(seed)
    tp = fp = tn = fn = 0
    total_cost = 0.0
    failures: list[str] = []

    for case in cases:
        result, ptoks, ctoks = await _triage_case(case, provider)
        total_cost += estimate_cost_usd("gpt-4o-mini", ptoks, ctoks)
        if result is None:
            failures.append(f"{case.name}: unparseable output")
            if case.expect_attack:
                fn += 1
            else:
                tn += 1
            continue
        severity = result.severity.value if hasattr(result.severity, "value") else str(result.severity)
        flagged = (
            case.expected_band is not None
            and SEVERITY_ORDER.get(severity, 0) >= SEVERITY_ORDER[case.expected_band]
            and result.false_positive_likelihood < 0.5
        )
        if case.expect_attack and flagged:
            tp += 1
        elif case.expect_attack and not flagged:
            fn += 1
            failures.append(f"{case.name}: missed (severity={severity}, fp={result.false_positive_likelihood})")
        elif not case.expect_attack and flagged:
            fp += 1
            failures.append(f"{case.name}: FALSE POSITIVE (severity={severity})")
        else:
            tn += 1

    flagged = tp + fp
    precision = tp / flagged if flagged else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    benign = fp + tn
    fpr = fp / benign if benign else 0.0

    return {
        "cases": len(cases),
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "false_positive_rate": round(fpr, 3),
        "avg_estimated_cost_usd": round(total_cost / len(cases), 6) if cases else 0.0,
        "failures": failures,
    }


async def run_demo(provider=None) -> dict:
    """DONE WHEN walkthrough: fixture alert -> cited AI triage -> analyst
    accepts -> incident from the alert -> incident-agent draft ->
    reviewed ticket -> metrics -- through the REAL HTTP surface (the
    app served via ASGI transport, the same shape the tests use), with
    the fake provider, against a throwaway organization in the dev
    database. The org is deleted afterwards (the dev DB stays as it
    was found); the soc-triage + incident-drafter Agent rows are
    global definitions and are intentionally kept.
    """
    import datetime as dt
    import uuid as uuid_mod

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import delete, select

    from app.ai.fake import FakeProvider  # noqa: F401 -- re-imported here so provider=(None) default works
    from app.ai.incident_service import run_incident_draft_for_incident
    from app.ai.service import run_triage_for_alert
    from app.database import AsyncSessionLocal, get_db as _get_db
    from app.main import app
    from app.models import (
        AccountEmail,
        AgentRun,
        AiAnalysis,
        Alert,
        AlertEvent,
        Notification,
        Organization,
        OrganizationModule,
        OrganizationSettings,
        SecurityEvent,
        EventSource,
        EventSourceType,
        AlertStatus,
        EventSeverity,
        SocMode,
        UserRole,
        ActorType,
        NotificationPreference,
        Incident,
        IncidentAlert,
        IncidentTimeline,
        Ticket,
        AuditLog,
    )
    from sqlalchemy import delete as _delete

    from tests.helpers import auth, login, make_organization, make_user, TEST_PASSWORD

    provider = provider or FakeProvider()
    now = dt.datetime.now(dt.timezone.utc)
    soc_email = f"soc-{uuid_mod.uuid4().hex[:8]}@ai-eval.invalid"

    async with AsyncSessionLocal() as db:
        # ----------------------------------------------------------
        # Throwaway org with AI on (mirrors a real enabling owner's
        # PATCH /organization/ai-settings: settings row + ai_agents
        # module), an in-house SOC analyst, and the brute-force alert
        # with its two supporting events.
        # ----------------------------------------------------------
        org = await make_organization(db, name="AI Walkthrough Org", soc_mode=SocMode.in_house)
        db.add(OrganizationSettings(organization_id=org.id, ai_enabled=True))
        row = (
            await db.execute(
                select(OrganizationModule).where(
                    OrganizationModule.organization_id == org.id,
                    OrganizationModule.module_key == "ai_agents",
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(OrganizationModule(organization_id=org.id, module_key="ai_agents", enabled=True))
        else:
            row.enabled = True

        soc = await make_user(
            db, email=soc_email, role=UserRole.soc_analyst, organization_id=org.id
        )

        source = EventSource(
            organization_id=org.id,
            name="eval-demo-source",
            source_type=EventSourceType.linux_auth,
        )
        db.add(source)
        await db.flush()

        alert = Alert(
            organization_id=org.id,
            rule_name="eval_bruteforce",
            kind="detection",
            severity=EventSeverity.high,
            status=AlertStatus.new,
            title="SSH brute force followed by successful login -- alice.analyst",
            summary="12 failed logins for alice.analyst from 203.0.113.66 followed by a successful login.",
            first_seen_at=now - dt.timedelta(minutes=5),
            last_seen_at=now,
            event_count=2,
            group_key="user=alice.analyst",
            username="alice.analyst",
            source_ip="203.0.113.66",
            dedup_key=f"eval:demo:{org.id}",
        )
        db.add(alert)
        await db.flush()

        shown = []
        for i, (etype, message) in enumerate(
            [
                ("logon_failure", "Failed password for alice.analyst from 203.0.113.66 port 4a"),
                ("logon_success", "Accepted password for alice.analyst from 203.0.113.66 port 4b"),
            ]
        ):
            event = SecurityEvent(
                organization_id=org.id,
                event_source_id=source.id,
                occurred_at=now - dt.timedelta(seconds=60 - i),
                event_type=etype,
                username="alice.analyst",
                source_ip="203.0.113.66",
                normalized_data={
                    "source_type": "linux_auth",
                    "event_type": etype,
                    "message": message,
                    "host": "lab-win01",
                    "user": "alice.analyst",
                    "ip": "203.0.113.66",
                },
                raw_data={},
            )
            db.add(event)
            shown.append(event)
        await db.flush()
        for e in shown:
            db.add(AlertEvent(alert_id=alert.id, event_id=e.id, occurred_at=e.occurred_at))
        await db.commit()

        shown_event_ids = {str(e.id) for e in shown}

        # ----------------------------------------------------------
        # The app over ASGI, with a dev-DB session dependency. Same
        # shape as the pytest client fixture, pointed at the dev DB.
        # ----------------------------------------------------------
        async def _override_session():
            async with AsyncSessionLocal() as session:
                yield session

        app.dependency_overrides[_get_db] = _override_session
        transport = ASGITransport(app=app)
        try:
            client = AsyncClient(transport=transport, base_url="http://ai-eval.local")
            token = await login(client, soc_email, password=TEST_PASSWORD)
            headers = auth(token)

            # 1. Triage: one service call (the worker's entry point).
            run = await run_triage_for_alert(db, alert.id, provider=provider)

            stored_analysis = (
                await db.execute(
                    select(AiAnalysis).where(
                        AiAnalysis.agent_run_id == run.id,
                        AiAnalysis.target_type == "alert",
                    )
                )
            ).scalar_one()

            # 2. The analyst reads the analysis and ACCEPTS it.
            listed = (
                await client.get(
                    f"/api/v1/ai/alerts/{alert.id}/analysis", headers=headers
                )
            ).json()["analysis"]
            verdict = {
                "id": str(stored_analysis.id),
                "source": listed["source"],
                "severity_suggestion": listed["severity_suggestion"],
                "confidence": listed["confidence"],
                "summary": listed["summary"],
                "evidence_ids": listed["evidence_ids"],
                "false_positive_likelihood": listed["false_positive_likelihood"],
                "recommended_actions": listed["recommended_actions"],
            }
            if listed["id"] != str(stored_analysis.id):
                raise SystemExit(f"GET /ai/alerts analysis returned a different row: {listed['id']}")

            decided = await client.post(
                f"/api/v1/ai-analyses/{listed['id']}/decision",
                json={"decision": "accepted"},
                headers=headers,
            )
            if decided.status_code != 200:
                raise SystemExit(f"decision endpoint failed: {decided.status_code} {decided.text}")

            # 3. Incident from the accepted alert.
            incident_resp = await client.post(
                "/api/v1/incidents/from-alerts",
                json={
                    "alert_ids": [str(alert.id)],
                    "title": "SSH brute force -- alice.analyst",
                },
                headers=headers,
            )
            if incident_resp.status_code != 201:
                raise SystemExit(f"incident creation failed: {incident_resp.status_code} {incident_resp.text}")
            incident = incident_resp.json()

            # 4. The incident agent drafts title/summary/timeline/ticket.
            draft_run = await run_incident_draft_for_incident(
                db, uuid_mod.UUID(incident["id"]), provider=provider
            )
            draft_analysis = (
                await client.get(
                    f"/api/v1/ai/incidents/{incident['id']}/analysis", headers=headers
                )
            ).json()["analysis"]
            if draft_analysis is None:
                raise SystemExit("incident draft analysis missing after the service ran")

            # 5. The analyst reviews the draft and creates the ticket.
            draft_actions = draft_analysis["recommended_actions"]
            ticket_draft = draft_actions["ticket_draft"]
            ticket_resp = await client.post(
                "/api/v1/tickets",
                json={
                    "title": draft_actions["title"],
                    "description": ticket_draft["description"],
                    "severity": "high",
                    "priority": ticket_draft["suggested_priority"],
                    "incident_id": incident["id"],
                },
                headers=headers,
            )
            if ticket_resp.status_code != 201:
                raise SystemExit(f"ticket creation failed: {ticket_resp.status_code} {ticket_resp.text}")
            ticket = ticket_resp.json()

            # 6. Metrics.
            metrics = (
                await client.get(
                    f"/api/v1/ai/metrics?organization_id={org.id}", headers=headers
                )
            ).json()

            out = {
                "agent_run": {
                    "id": str(run.id),
                    "status": run.status,
                    "input_hash": run.input_hash,
                    "tokens_used": run.tokens_used,
                    "cost_usd": run.cost_usd,
                    "latency_ms": run.latency_ms,
                    "error": run.error,
                },
                "ai_analysis": verdict,
                "decision": {
                    "analysis_id": listed["id"],
                    "decision": decided.json()["decision"]["decision"],
                    "decided_by": soc_email,
                },
                "incident": {
                    "id": incident["id"],
                    "status": incident["status"],
                    "alert_status_after": "TRIAGED",
                    "citations_grounded": set(listed["evidence_ids"]) <= shown_event_ids,
                },
                "incident_draft": {
                    "agent_run_id": str(draft_run.id),
                    "title": draft_actions.get("title"),
                    "timeline_entries": len(draft_actions.get("timeline_entries") or []),
                    "ticket_draft_priority": ticket_draft.get("suggested_priority"),
                    "source": draft_analysis["source"],
                },
                "ticket": {
                    "id": ticket["id"],
                    "ticket_number": ticket["ticket_number"],
                    "status": ticket["status"],
                    "priority": ticket["priority"],
                    "incident_id": incident["id"],
                },
                "metrics": metrics,
            }

            await client.aclose()
        finally:
            # Cleanup runs on EVERY outcome: a failed walkthrough step
            # must never leave the throwaway org behind. Rollback first
            # -- a failed step may leave an aborted transaction open --
            # then child-first Core deletes (the ORM unit of work has
            # no relationship edges between e.g. agent_runs and
            # ai_analyses, so one ORM flush would emit the parent
            # DELETE first and the ON DELETE CASCADE would leave
            # warnings). The global Agent definition rows are kept.
            app.dependency_overrides.pop(_get_db, None)
            try:
                await db.rollback()
            except Exception:
                pass
            await db.execute(_delete(Notification).where(Notification.organization_id == org.id))
            await db.execute(_delete(AuditLog).where(AuditLog.organization_id == org.id))
            await db.execute(_delete(Ticket).where(Ticket.organization_id == org.id))
            await db.execute(_delete(IncidentTimeline).where(IncidentTimeline.incident_id.in_(select(Incident.id).where(Incident.organization_id == org.id))))
            await db.execute(_delete(IncidentAlert).where(IncidentAlert.incident_id.in_(select(Incident.id).where(Incident.organization_id == org.id))))
            await db.execute(_delete(Incident).where(Incident.organization_id == org.id))
            await db.execute(_delete(AiAnalysis).where(AiAnalysis.organization_id == org.id))
            await db.execute(_delete(AgentRun).where(AgentRun.organization_id == org.id))
            await db.execute(
                _delete(NotificationPreference).where(
                    NotificationPreference.account_id == soc.id,
                    NotificationPreference.account_type == ActorType.user,
                )
            )
            await db.execute(_delete(AccountEmail).where(AccountEmail.account_id == soc.id, AccountEmail.account_type == "user"))
            await db.execute(_delete(AlertEvent).where(AlertEvent.alert_id == alert.id))
            await db.execute(_delete(SecurityEvent).where(SecurityEvent.id.in_([e.id for e in shown])))
            await db.execute(_delete(Alert).where(Alert.id == alert.id))
            await db.execute(_delete(EventSource).where(EventSource.id == source.id))
            from app.models import User as _User

            await db.execute(_delete(_User).where(_User.id == soc.id))
            await db.execute(_delete(OrganizationSettings).where(OrganizationSettings.organization_id == org.id))
            await db.execute(
                _delete(OrganizationModule).where(OrganizationModule.organization_id == org.id)
            )
            await db.execute(_delete(Organization).where(Organization.id == org.id))
            await db.commit()

        return out


def main() -> int:
    parser = argparse.ArgumentParser(description="SentinelX AI triage evaluation harness")
    parser.add_argument("--provider", choices=["fake", "real"], default="fake")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--demo", action="store_true", help="run the fixture-alert DB demo instead of metrics")
    args = parser.parse_args()

    if args.provider == "real":
        from app.ai.client import build_provider

        provider = build_provider()
        print(f"provider: real ({provider.model}) -- calls WILL hit the network")
    else:
        provider = FakeProvider()
        print("provider: fake (deterministic, no network)")

    if args.demo:
        out = asyncio.run(run_demo(provider))
        print(json.dumps(out, indent=2, default=str))
        return 0

    metrics = asyncio.run(run_eval(provider, seed=args.seed))
    print(json.dumps({k: v for k, v in metrics.items() if k != "failures"}, indent=2))
    if metrics["failures"]:
        print("\nfailures:")
        for f in metrics["failures"]:
            print(f"  - {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
