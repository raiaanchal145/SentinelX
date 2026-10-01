# Manual test checklist — notifications (P16)

Run the stack (dev launcher, or Postgres + Redis via docker compose,
`uvicorn app.main:app`, the worker, `npm run dev`). You need a managed
organization (platform SOC assigned + IT developer) and/or an in-house
org. Automated coverage: `backend/tests/test_notifications.py` (10
tests); this is the human pass over the whole UI flow.

## The DONE-WHEN walks

1. **Assigning a ticket notifies in-app + email.** As the SOC, assign a
   ticket to the IT developer. Open their `/it` page: the bell shows an
   unread badge; the dropdown lists "Ticket T-… assigned to you".
   `docker compose logs worker` (or the uvicorn console if SMTP is off)
   shows the notification email for the assignee; with real SMTP the
   message actually arrives.
2. **SLA breach notifies SOC and owner.** Pick a P1 ticket whose resolve
   window is minutes (or backdate `resolve_due_at` in the DB), let the
   `ticket_sla_check` cron fire, then check the org's SOC account AND
   the owner: both have "Ticket T-… SLA breached" in-app, and both got
   an email (or a logged one in dev). The at-risk path fires once per
   ticket too (no repeats every minute).

## The bell

3. The bell sits in the top bar on every role's pages (SOC, IT,
   manager, auditor); the unread badge counts across pages and updates
   within ~30s of the action (or on open).
4. Dropdown: newest notifications first with their event labels; click
   one -> it is marked read and you land on `/notifications`; "Mark all
   read" clears the badge everywhere.
5. Backend down: the bell stays quiet (no error toast from polling);
   the feed page shows the error panel with Try again.

## The feed page

6. `/notifications`: unread rows carry the dot and a tint; "Unread
   only" narrows the list; the event filter narrows further; "Load
   more" appends the next cursor page.
7. Clicking a row marks it read (dot + badge count drop); "Mark all
   read" empties the unread filter's list.

## Preferences

8. `/notifications/preferences`: every event key with In-app and Email
   switches, all ON for a fresh account. Toggle "Ticket SLA breached"
   email OFF, save (row stored), then trigger a breach: the SOC still
   gets the in-app row but no email job. Toggle back ON, save, trigger
   again: the email returns.
9. Mute BOTH channels for an event -> the row shows a "Muted" badge and
   no notification of that kind appears anywhere.
10. The page survives a reload (switches come back from the API).

## Routing across the boundary (managed vs in-house)

11. Managed org: IT submits for verification -> the assigned platform
    SOC analyst's bell gains "Ticket … awaits verification"; the org's
    owner gains it too. A platform analyst assigned to a DIFFERENT org
    sees nothing.
12. In-house org: same trigger -> the org's own soc_analyst gets it;
    the platform SOC does not exist here.
13. Verification failed / reopened -> the IT assignee (who re-works the
    ticket), the org's SOC, and the owner all hear it.
14. P1 close-request -> the org's owner and security_manager get
    "Approval requested: ticket_close"; the decision comes back to the
    requesting SOC as "Approval decided: …".
15. Critical/high alert (feed the brute-force scenario via the
    simulator) -> the org's SOC gets "{severity} alert: …".

## Isolation + robustness

16. Cross-account: another org's analyst requesting a notification id
    from the feed gets 404; their feed stays empty. `unread_count` is
    per account.
17. Stop Redis and assign a ticket: the assignment still succeeds (the
    enqueue failure is logged, in-app row still written). Restart and
    note the email was simply not queued.
18. Stop SMTP (unset the env): the worker logs the message and the job
    returns ok — no retry storm.
19. Keyboard: the bell, dropdown items, feed rows and preference
    checkboxes are all reachable by Tab; dialogs/menus close on Escape.
20. 360px: the feed rows, filter bar and preferences rows wrap; the
    bell badge stays legible.
