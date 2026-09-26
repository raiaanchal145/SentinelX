# Manual test checklist — incidents lifecycle

Run the stack (dev launcher or: Postgres + Redis via docker compose,
`uvicorn app.main:app`, the worker, `npm run dev`), then feed events
with the **simulator** (brute-force scenario) and triage the resulting
alerts so real alerts exist to build incidents from. Automated
coverage: `backend/tests/test_incidents.py` — this checklist is the
human pass over the same rules.

## Create

1. Log in as an in-house org's `soc_analyst`. `POST /incidents` with
   title/severity/priority/category — the response shows
   `status: "NEW"` and a `created` timeline row exists in the detail.
2. `POST /incidents/from-alerts` with two alerts of the same org —
   the incident links both alerts plus their supporting events, and
   both alerts flip to `TRIAGED` in the alerts queue.
3. Try `from-alerts` with alerts from two different organizations →
   `400 alerts_from_multiple_organizations`.
4. As a platform SOC analyst: create without `organization_id` →
   `400 organization_id_required`; with an org you're not assigned to
   → `404 organization_not_found`.

## The lifecycle

5. Walk NEW → TRIAGED → INVESTIGATING → CONTAINMENT → REMEDIATION →
   VERIFICATION → RESOLVED → CLOSED with the transition button — each
   step lands, and the timeline shows one `status_change` row per step.
6. Try to close from NEW (skipping the path) → 409 with the allowed
   next states listed in the error detail.
7. Close without a resolution summary → `422
   resolution_summary_required`; with one → CLOSED, `closed_at` set.
8. Step back one stage (e.g. VERIFICATION → REMEDIATION) — allowed;
   NEW → ESCALATED is refused (triage first).
9. As the security_manager: every write is 403 EXCEPT requesting
   ESCALATED from an active state, which succeeds.
10. FALSE_POSITIVE with a reason → terminal; REOPENED afterwards is
    409. DUPLICATE requires reason + parent incident id; the merged
    duplicate's links move to the parent (check the parent's alerts).

## Roles and isolation

11. Managed org: assigned platform SOC analyst works incidents; the
    org's owner and security_manager see read-only views and get 403
    on every write; a soc_analyst of another org gets 404 on the id.
12. Cross-org isolation everywhere: another org's incident id is 404,
    never 403, from every account shape.

## Comments and visibility

13. Post an `internal` and a `shared` comment as the analyst.
14. Log in as the org's `it_developer`: the incident list/detail is
    readable, but ONLY the shared comment appears in the timeline;
    every write button/endpoint fails with 403.

## Side effects

15. Resolve an incident built from alerts — its alerts become
    `CONVERTED` (they leave the working queue).
16. Close another incident as FALSE_POSITIVE — its alerts become
    `DISMISSED` with the incident's reason, and each alert's history
    shows the dismissal made via the incident transition.
