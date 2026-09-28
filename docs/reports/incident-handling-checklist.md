# Manual test checklist — incident handling on real data (P14)

Run the stack (dev launcher or: Postgres + Redis via docker compose,
`uvicorn app.main:app`, the worker, `npm run dev`), then feed events
with the **simulator** (brute-force scenario) and triage the resulting
alerts so real alerts exist to build incidents from. Automated
coverage: `backend/tests/test_incidents.py` (including the three new
caller-shape tests); this is the human pass over the whole UI flow.

## In-house SOC analyst (`/soc/alerts`, `/soc/incidents`)

1. `/soc/alerts`: select two alerts (checkboxes; select-all works).
   A selection bar appears with "Create incident (N)". Click it, give a
   title, confirm — you land on the new incident's detail; both alerts
   are TRIAGED in the alerts queue and linked on the Overview tab.
2. Alternative path: open one alert's drawer and use "Create incident" —
   same dialog with one alert pre-selected.
3. Try selecting alerts — the selection bar clears when the queue
   refreshes after any action (acknowledge/dismiss empties stale ids).
4. `/soc/incidents`: the list shows severity + status badges, age,
   alert count, linked ticket column (empty until step 8), assignee.
   Filters (status/severity/range/assigned-to-me) refetch from the API.
5. "Load more" appends the next keyset page when the backend reports
   `next_cursor`.
6. Open the incident: the header shows the status badge and one button
   per `allowed_next_states` entry (NEW → Triaged / Investigating /
   False positive / Duplicate — no Close button from NEW; nothing
   hard-coded client-side).
7. Move through the lifecycle one step at a time to VERIFICATION. Every
   step lands with a success toast and one new Timeline row.
8. On the Ticket tab: the priority preview matches the documented
   formula for the incident's severity/asset/confidence. Create a
   ticket (title required) — it appears with number/status/SLA badges.
   "Suggest assignee" runs the org's assignment rules.
9. Verification step: from VERIFICATION move to RESOLVED, then CLOSED —
   the close dialog REQUIRES the resolution summary (confirm disabled
   while empty) and, being destructive, typing CONFIRM. The timeline
   shows every step plus the ticket_created/ticket_status entries.
10. FALSE_POSITIVE path (on a second incident): reason required,
    CONFIRM required; the linked alerts become DISMISSED with the
    incident's reason.
11. Add an internal note and a shared note from the header — both land
    on the Timeline, the internal one carrying the "Internal" badge.
12. "Assign to me" stamps the assignee (visible in the list's Assignee
    column after refresh).
13. Overview tab: linked alerts open... the alerts live in their queue;
    linked EVENTS open the event drawer in place (Escape closes).
    Evidence tab shows the P15 placeholder. Response actions tab shows
    disabled placeholder buttons with the P19 note.
14. Empty state: a filter combination with no matches shows the
    empty-state panel; clearing filters restores the list.
15. Error state: stop the backend, reload — the error panel with a
    working "Try again" once it's back.

## Security manager (managed org, `/manager/incidents`)

16. The list renders read-only: no create bar anywhere, ReadOnlyChip +
    "Handled by the platform SOC team" note (managed mode only).
17. Open an incident: NO transition buttons render at all
    (`allowed_next_states` is `[]` for this caller), no note button, no
    assign. The timeline shows SHARED entries only — internal SOC notes
    are absent (server-side filtered).
18. Log in as the security_manager of an IN-HOUSE org instead: the
    managed note is gone, the full timeline (internal notes included)
    is visible, and the header offers exactly one action — the
    ESCALATED request — straight from `allowed_next_states`.

## Organization owner (`/organization/incidents`)

19. The new sidebar item lists the org's incidents read-only; row
    click opens the read-only detail. Same shared components as the
    manager view, no write controls, and for a managed org the
    shared-only timeline applies to the owner too.

## Platform SOC analyst (`/admin/soc-queue`)

20. The workspace now has Alerts and Incidents tabs. The Incidents tab
    shows the multi-org queue with the Organization column and an org
    filter listing exactly your assigned organizations.
21. Open an incident from the tab — the detail page's back-link returns
    to the queue; transition buttons work (this caller is a writer for
    managed orgs) and the full flow of steps 6–13 is available here.

## General states / a11y

22. At 360px width: the incident table scrolls internally, the filter
    bar wraps, dialogs stay within the viewport and scroll internally.
23. Every destructive dialog (CLOSED / FALSE_POSITIVE / DUPLICATE):
    focus trapped, Escape cancels, confirm disabled until required
    fields AND the typed CONFIRM are present.
24. Demo chips: none of the incident surfaces (`/soc/incidents`,
    incident detail, `/manager/incidents`,
    `/organization/incidents`, the queue's Incidents tab) shows a
    "Demo data" chip.

## The DONE-WHEN walk

25. One continuous pass as the in-house analyst: from an alert →
    create the incident → add a note → work it to REMEDIATION → create
    the ticket for IT → (as it_developer: work the ticket to
    VERIFICATION) → verify the fix from the incident's Ticket tab →
    RESOLVED → CLOSED with a resolution summary → the Timeline shows
    every step: created, each status change, the note, the ticket
    creation, the ticket's verification, and the closure.
