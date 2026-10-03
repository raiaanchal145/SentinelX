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

`run_demo` (DONE WHEN): builds a fixture organization + alert + events
directly in the dev database, runs the REAL service entry point
(run_triage_for_alert) with the fake provider, and prints the stored
agent_runs and ai_analyses rows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

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
    """DONE WHEN check: fixture alert -> run_triage_for_alert (fake
    provider) -> agent_runs + ai_analyses rows in the dev database."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.ai.fake import FakeProvider as _Fake
    from app.ai.service import run_triage_for_alert
    from app.models import (
        AgentRun,
        AiAnalysis,
        Alert,
        AlertEvent,
        AlertStatus,
        EventSeverity,
        EventSource,
        EventSourceType,
        Organization,
        OrganizationModule,
        OrganizationSettings,
        SecurityEvent,
        SocMode,
        OrganizationStatus,
    )
    from app.database import AsyncSessionLocal

    provider = provider or _Fake()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        org = Organization(
            name="AI Eval Demo Org",
            industry="technology",
            environment="lab",
            status=OrganizationStatus.active,
            soc_mode=SocMode.in_house,
        )
        db.add(org)
        await db.flush()
        db.add(OrganizationSettings(organization_id=org.id, ai_enabled=True))
        db.add(OrganizationModule(organization_id=org.id, module_key="ai_agents", enabled=True))

        # SecurityEvent requires a real EventSource (NOT NULL FK); the
        # human-readable fields live in normalized_data, not columns.
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
            first_seen_at=now - timedelta(minutes=5),
            last_seen_at=now,
            event_count=2,
            group_key="user=alice.analyst",
            username="alice.analyst",
            source_ip="203.0.113.66",
            dedup_key="eval:demo:1",
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
                occurred_at=now - timedelta(seconds=60 - i),
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

        run = await run_triage_for_alert(db, alert.id, provider=provider)

        stored_run = (await db.execute(select(AgentRun).where(AgentRun.id == run.id))).scalar_one()
        stored_analysis = (
            await db.execute(select(AiAnalysis).where(AiAnalysis.agent_run_id == run.id))
        ).scalar_one()
        out = {
            "agent_run": {
                "id": str(stored_run.id),
                "status": stored_run.status,
                "input_hash": stored_run.input_hash,
                "tokens_used": stored_run.tokens_used,
                "cost_usd": stored_run.cost_usd,
                "latency_ms": stored_run.latency_ms,
                "error": stored_run.error,
            },
            "ai_analysis": {
                "id": str(stored_analysis.id),
                "source": stored_analysis.source,
                "severity_suggestion": stored_analysis.severity_suggestion.value
                if hasattr(stored_analysis.severity_suggestion, "value")
                else stored_analysis.severity_suggestion,
                "confidence": stored_analysis.confidence,
                "summary": stored_analysis.summary,
                "evidence_ids": stored_analysis.evidence_ids,
                "false_positive_likelihood": stored_analysis.false_positive_likelihood,
                "recommended_actions": stored_analysis.recommended_actions,
            },
        }
        # Leave the demo org behind? No -- clean up: this is a demo, not
        # data anyone needs. (The dev DB stays as it was found.) Core-level
        # deletes in explicit child-first order: the ORM unit of work has
        # no relationship() edges between e.g. agent_runs and ai_analyses,
        # so one ORM flush can emit the parent DELETE first, the DB ON
        # DELETE CASCADE eats the children, and the child DELETEs then
        # match 0 rows (SAWarning noise). Executed Core deletes are
        # ordered, deterministic, and silent. The soc-triage Agent row
        # created by ensure_triage_agent is a global definition and is
        # intentionally kept.
        from sqlalchemy import delete as _delete

        await db.execute(_delete(AiAnalysis).where(AiAnalysis.agent_run_id == run.id))
        await db.execute(_delete(AgentRun).where(AgentRun.id == run.id))
        await db.execute(_delete(AlertEvent).where(AlertEvent.alert_id == alert.id))
        await db.execute(_delete(SecurityEvent).where(SecurityEvent.id.in_([e.id for e in shown])))
        await db.execute(_delete(Alert).where(Alert.id == alert.id))
        await db.execute(_delete(EventSource).where(EventSource.id == source.id))
        await db.execute(
            _delete(OrganizationSettings).where(OrganizationSettings.organization_id == org.id)
        )
        await db.execute(
            _delete(OrganizationModule).where(
                OrganizationModule.organization_id == org.id,
                OrganizationModule.module_key == "ai_agents",
            )
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
