# Manual checklist: the remediation workflow (P13 tickets)

Run against a dev stack (`npm run dev`, or uvicorn + worker + Postgres
+ Redis manually). Login as each actor below; a managed organization
plus an in-house organization covers both SOC modes.

## Actors

- Platform SOC analyst assigned to the managed organization
  (invited via `/admin/soc-analysts`, assigned via
  `PUT /admin/soc-analysts/{id}/organizations`).
- The managed organization's owner (read-only oversight expected).
- An in-house organization's soc_analyst, owner, security_manager.
- IT developers (it_developer) in both organizations, on a team.

## Creation

1. POST /api/v1/tickets as the in-house soc_analyst (no
   organization_id): 201, `status=OPEN`, `ticket_number=TICK-1`,
   priority computed from severity/asset/confidence per the formula in
   docs/API_CONTRACT.md "Tickets".
2. Same as the assigned platform SOC analyst for the managed org, with
   `organization_id`: 201. The managed org's owner sees it read-only.
3. As an IT developer: 403 (IT never creates).
4. As a platform SOC analyst with no organization_id in the payload:
   400 `organization_id_required`.
5. With `priority: "P1"` as the SOC: 201 with the override; the audit
   log shows `ticket.priority_override`.
6. Auto-creation: set `auto_ticket_threshold=high` and
   `auto_ticket_min_confidence=0.7` on the org's settings, create a
   high-severity incident with confidence >= 0.7 and a primary asset
   (incident module) -> a `[Auto]` ticket appears, linked to the
   incident, with a `ticket_created` timeline entry. Re-run with
   another incident of the same asset while the first ticket is open:
   no second ticket (duplicate guard).
7. Leave one threshold NULL: no auto ticket (feature off).

## Priority

8. critical incident + critical asset + confidence 0.95 -> P1;
   medium + medium + none -> P4 (formula table in the contract).

## Assignment

9. Create two assignment rules (owner or security_manager,
   /api/v1/assignment-rules) where the FIRST by priority_order matches
   only P4; a P1 ticket auto-assigns to the second rule's team
   (order respected).
10. Auto-assign twice on equal load: the same dev gets it (name
    tie-break); after that dev holds an open ticket, the other one is
    chosen (least-loaded).
11. Assign a user from another organization: 422
    `assignee_not_in_scope`. ticket_assignments gains one row per
    hand-off.

## The lifecycle

12. Walk OPEN -> ASSIGNED -> INVESTIGATING -> REMEDIATION ->
    VERIFICATION as IT: each 200. Attempt RESOLVED as IT: 403
    `it_cannot_close`. Attempt CLOSED as IT: 403
    `it_cannot_close`.
13. As the SOC: POST /{id}/verify {result: "failed"} -> back to
    INVESTIGATING (a verifications row exists); walk IT back to
    VERIFICATION; verify "verified" -> RESOLVED; transition CLOSED ->
    200; reopen -> OPEN.
14. Invalid move (e.g. OPEN -> CLOSED directly): 409
    `invalid_ticket_transition` with `allowed_next_states`.
15. Every step: one ticket_status_history row, one audit_logs row
    (`ticket.transition`/`ticket.verify`), and -- when linked to an
    incident -- one incident_timeline entry.

## Critical close gate

16. Create a P1 (critical) ticket, walk to VERIFICATION as IT, verify
    as SOC, attempt CLOSED: 403 `close_approval_required`.
17. POST /{id}/close-request as the SOC: 201. Again: 409
    `close_request_already_pending`. On a P4 ticket: 422
    `close_approval_not_required`. As IT: 403.
18. Decide the approval as the org's security_manager or owner
    (POST /api/v1/approvals/{id}/decision, decision=approved): 200. As
    a soc_analyst: 403 `approvals_decide_not_allowed`.
19. Now CLOSED as the SOC: 200. A rejected approval leaves the gate
    shut.

## SLA

20. A P1 ticket's `ack_due_at`/`resolve_due_at` are stamped from the
    org's P1 policy (15/240 minutes). With the worker running, watch a
    test policy (e.g. resolve 5 minutes): `sla.state` flips
    `on_track` -> `at_risk` (~80%) -> `breached`, and ONE escalations
    row appears per ticket (the GET /tickets list filters by
    `sla_state`).

## Comments, tasks, evidence, visibility

21. SOC posts an internal comment; IT's GET /{id} shows only shared
    comments (the internal one is absent from the response, not
    greyed out). IT posts a comment: it is shared (internal is 403).
22. IT creates/updates/completes tasks under the ticket; the SOC sees
    the same rows. Evidence links attach via /{id}/evidence.

## Isolation

23. Another organization's ticket id from any endpoint: 404
    `ticket_not_found` (for IT, SOC, everyone). A managed org's own
    soc_analyst (no platform assignment) has no ticket access at all
    (`soc_not_visible` / module gate).
24. An unassigned platform SOC analyst sees an empty queue.

## DONE-WHEN (end to end)

25. Managed org: platform SOC creates a ticket from an incident -> IT
    developer (same org) works and hands off at VERIFICATION ->
    platform SOC verifies (verified) -> (P1: owner approves the
    close-request) -> SOC closes. Check the incident's timeline
    recorded every step.
