# Manual test checklist — AI triage + incident drafting (AI SOC Analyst milestone)

Run the stack (dev launcher, or Postgres + Redis via docker compose,
`uvicorn app.main:app`, the worker, `npm run dev`). You need an
in-house organization with a SOC analyst, and an owner to flip
`ai_enabled`. Automated coverage: `backend/tests/test_ai_triage.py`,
`backend/tests/test_ai_incident_agent.py` and the end-to-end pin
`backend/tests/test_ai_done_flow.py`; the harness
(`tools/ai_eval/runner.py --demo`) walks the whole DONE path against
the dev DB with printed ids. This is the human pass over the UI flow.

## Enabling AI

1. As the owner, open the organization's AI settings (the ai-settings
   GET/PATCH endpoint the UI surfaces): `ai_enabled` is OFF by default,
   and the resolved cost caps ($2/day, $10/month) plus live spend are
   visible before any key exists.
2. With AI still OFF, ingest an alert and open its drawer: the AI panel
   shows the deterministic summary with a plain "AI unavailable" note —
   never an empty box, never a fake-looking verdict.
3. Flip `ai_enabled` on (owner-only; the PATCH is audited and the
   page shows who/when on next view). Re-open the alert: within the
   first seconds the panel swaps to the real analysis.

## The DONE walk (in-house SOC mode, real UI)

4. Feed the brute-force scenario through the simulator (or any alert
   with supporting events). Open the alert drawer's AI panel:
   - the "AI-generated — verify before acting" label is visible;
   - the confidence bar shows the confidence (no red/green traffic
     light — a 0.7-critical must not look safe);
   - the reasoning cites events; clicking a citation opens that event;
   - recommended actions and the false-positive likelihood are shown.
5. Accept the analysis (Accept button): the panel marks it accepted
   (who + when).
6. Create the incident from the alert. The alert moves TRIAGED; the
   incident opens. The incident detail's AI panel drafts title,
   summary, timeline entries and the ticket draft — every editable
   before anything happens.
7. Review/edit the ticket draft, then create the ticket from the
   panel: a real ticket row appears through the normal ticket service
   (assignment rules, audit row). The incident's timeline records no
   AI-created rows unless the analyst acted: the model path never
   creates tickets by itself (auto-creation only when the org's
   `auto_ticket_*` policy allows it: severity <= medium, confidence
   >= 0.9, FP likelihood < 0.3 — audit then marks actor_type
   `ai_agent`).
8. Regenerate: the panel's regenerate action re-runs the draft; when
   the org is over its daily cap the panel says so (the run is refused
   BEFORE any provider call) instead of a silent failure.

## Metrics

9. `/soc` metrics (owner/security manager read-only — they see the
   accepted summaries but no decision buttons): GET /ai/metrics shows
   acceptance rate, average confidence, override (edited) rate and
   spend. After the walk above: 2 analyses, 1 accepted, acceptance
   rate 1.0.
10. Record one reject-without-reason: the endpoint answers 422
    `reason_required`; a rejection WITH a reason drops the acceptance
    rate and shows on the panel.

## Managed mode sanity

11. In a managed organization the platform SOC sees the same panels in
    its queue; the org's owner/security manager keep the read-only view
    (labels, accepted summaries) with the decision buttons absent —
    mirroring the backend 403s rather than offering buttons that fail.

## Checking the "verify" story on the wire

12. `docker compose logs worker` after step 4: the `ai_triage_alert`
    job ran (status succeeded) and the cost ($0.0002-ish against the
    default gpt-4o-mini price table) is on `agent_runs.cost_usd`.
13. Repeat the manager's view of a rejected case: the acceptance-rate
    metric reflects it without any UI refresh trickery (poll the
    metrics endpoint again).
