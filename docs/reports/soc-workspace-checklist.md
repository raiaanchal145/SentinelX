# Manual test checklist — SOC workspace on real alerts

Run the stack (dev launcher or: Postgres + Redis via docker compose,
`uvicorn app.main:app`, the worker, `npm run dev`), then feed events
with the **simulator** so alerts actually exist (brute-force scenario
produces the built-in detections and the correlated alert).

## Platform SOC analyst (assigned to a managed organization)

1. Log in as a `platform_soc_analyst` assigned to at least one
   `managed` + `active` organization. You land on `/admin/soc-queue`.
2. The queue shows only your assigned organizations' alerts; the
   Organization column and org filter list exactly those orgs.
3. Per-organization counts (the "open" numbers on the org buttons)
   match the alerts visible for each org in the loaded page.
4. Selecting one org filters the table to it; selecting it again clears.
5. Unassigned analyst variant: log in as a platform SOC analyst with no
   assignments — the queue is empty and the page says no organizations
   are assigned (no error, no other org's data).
6. Open an alert (click/Enter): drawer shows summary, why it fired,
   supporting events (click one — the event drawer opens in place),
   correlation reasoning (for the correlated alert) and history.
7. Acknowledge a `new` alert (button or `a` on a focused row):
   confirmation appears, status becomes acknowledged, history gains a
   row, the list refreshes.
8. Dismiss an alert: the reason is REQUIRED (confirm disabled while
   empty); after dismissal the Reopen button appears in the drawer and
   works (status back to new, reason cleared).
9. Assign: the drawer's "Assign to…" lists you; assigning succeeds and
   history records it.

## In-house SOC analyst

10. Log in as a `soc_analyst` of an `in_house` organization with the
    `soc` module. `/soc` shows the KPI row (open, unacknowledged, median
    age, by severity) computed from real alerts, the triage queue
    (severity → asset criticality → age), real event volume sparkline,
    and the disabled "Agent & device health" / "AI insights"
    placeholder panels.
11. `/soc/alerts` lists ONLY your organization's alerts; filters
    (status, severity, time range, assigned-to-me) refetch from the API.
12. Keyboard: `j`/`k` move through the triage queue rows, Enter opens
    the alert drawer, `a` opens the acknowledge confirmation.
13. Empty state: with no alerts, the page says "No alerts right now --
    the last event arrived N minutes ago" (or the no-events-yet text).
14. Error state: stop the backend, reload — the queue shows the error
    with a working "Try again" once the backend is back.

## Managed-mode oversight (read-only)

15. Log in as the OWNER of the managed organization: the Sidebar has
    "Security activity" (`/organization/security-activity`). Alert
    counts and the table show the org's alerts; there are NO action
    buttons anywhere (drawer included), and the page carries the
    "Handled by the platform SOC team" note + read-only chip.
16. Same for the managed org's `security_manager` via the top-nav item
    (`/manager/security-activity`).
17. An in-house org's owner/security_manager also see the page (no
    "managed" note), still read-only — actions live on the analyst
    pages, not here.

## General states / a11y

18. Responsive: at 360px width the KPI grid, filter bar and tables
    remain usable (no horizontal page scroll; table scrolls internally).
19. Drawers: focus is trapped, Escape closes, title/labels announced.
20. Demo chips: none of the SOC workspace pages (`/soc`, `/soc/alerts`,
    `/admin/soc-queue`, security activity) shows a "Demo data" chip.
