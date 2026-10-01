# Manual test checklist — IT workspace on real data + evidence handling (P15)

Run the stack (dev launcher, or Postgres + Redis via docker compose,
`uvicorn app.main:app`, the worker, `npm run dev`). You need a managed
organization with the platform SOC assigned and an `it_developer`
member, or an in-house org with its own SOC analyst + IT developer.
Automated coverage: `backend/tests/test_evidence.py` (19 tests); this
is the human pass over the whole UI flow.

## Evidence, over the API first (already automated, spot-check here)

1. Upload a log file to a ticket WITH a linked incident, as the IT
   developer — 201, the row shows `sha256`, `size_bytes`, the sniffed
   `content_type`, and a `storage_ref` that does NOT contain the
   filename.
2. On disk: `backend/data/evidence/{org_id}/{uuid}` — one file, random
   name, no extension, the original filename nowhere in the tree.
3. Upload `..\..\..\windows\system32\config\SAM` as a filename — 201,
   stored inert under the org dir as a uuid; nothing escaped.
4. Upload an .exe (MZ magic) — 415 `evidence_unsupported_type`. Upload
   a 11 MB file — 413 `evidence_too_large` (set
   `EVIDENCE_MAX_UPLOAD_MB` to 1 for a quick test).
5. Download as the IT developer — 200 with
   `Content-Disposition: attachment` (the original filename),
   `X-Content-Type-Options: nosniff`, and the exact bytes back; the
   sha256 of the download matches the row.
6. Another org's IT developer tries the same download/upload — 404,
   never a leak.
7. A standalone ticket (no incident): both the JSON and the multipart
   evidence paths return 422 `evidence_requires_incident`.
8. Evidence has NO delete endpoint anywhere in the API — retirement is
   a future, audited flow.

## IT developer (`/it`)

9. Dashboard: KPI cards show real counts (open, due within 4h, at
   risk, breached, awaiting verification) from GET /tickets; the work
   board's five columns move a ticket correctly when you work it.
10. Empty state: a fresh IT developer with no tickets sees the
    empty-state panel, no mock rows, no demo chip.
11. `/it/tickets`: scope segmented control (Mine / Team / All in
    scope) filters rows client-side over the org-scoped API list;
    status and priority selects refetch from the API; SLA badges show
    on_track/at_risk/breached; row click opens the detail.
12. Ticket detail: the header shows severity/status/priority/SLA and
    exactly the buttons `allowed_next_states` grants — OPEN offers
    Triaged/Acknowledged/Investigating, never Resolved/Closed; NO
    transition buttons render when the SOC has the ball
    (VERIFICATION/RESOLVED/CLOSED rows show none for IT).
13. Work the lifecycle: Acknowledge → Investigating → Remediation —
    every step lands with a toast and a new status_history row (the
    Incident context tab counts them).
14. Checklist: add tasks, toggle them done, remove one; the counter in
    the tab label updates.
15. Comments: post one — it appears for the SOC; the SOC's internal
    comments never appear here (server-side filter).
16. Evidence: attach a screenshot and a log — rows show filename,
    hash, size; Download returns the file; the file lands in the org's
    evidence directory with a random name.
17. "Submit for verification": the dialog REQUIRES the fix summary
    (submit disabled while empty); the note field is optional on other
    transitions. After submit the status is VERIFICATION and the
    resolve clock keeps running (CountdownChip counts down).
18. As IT, attempt RESOLVED/CLOSED via the API while in VERIFICATION —
    403 `it_cannot_close` (the UI never offers the button).
19. The SOC verifies (verified → RESOLVED) from the incident's Ticket
    tab (P14 flow) — the IT detail then shows the RESOLVED status and
    the verification in Incident context.

## Keyboard / responsive

20. At 360px: the tickets table scrolls internally, filter bars wrap,
    dialogs stay within the viewport and scroll internally.
21. Keyboard: every dashboard card, list row and drawer control is
    reachable by Tab; Enter/Space opens cards and rows; dialogs trap
    focus and Escape cancels.

## The DONE-WHEN walk

22. One continuous pass: platform SOC raises a ticket from an incident
    → the IT developer opens it from `/it/tickets` → works the
    checklist → attaches a file as evidence → submits for verification
    with a fix summary → the SOC verifies and closes from the incident
    panel → the IT developer, back on the detail, sees CLOSED with the
    verification recorded and can do nothing further (no buttons) —
    and the incident's timeline shows every step.
