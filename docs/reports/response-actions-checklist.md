# Manual Test Checklist — Response Actions & Approval Governance (P19)

Verify end-to-end authorization, anti-self-approval, worker execution, and evidence logging.

---

## 1. High-Risk Containment Request (Incident Detail)

1. **Log in as SOC Analyst** (`soc_analyst` in an in-house organization).
2. Navigate to an incident with linked assets (`/soc/incidents/{id}`).
3. Open the **Response actions** tab.
4. Click **Isolate Host**:
   - The confirmation dialog opens with a High Risk warning banner explaining that manual authorization is required.
   - Select the target asset.
   - Enter a justification reason (e.g., "Active brute force command-and-control connection detected.").
   - Check "Submit as AI Agent suggestion" to simulate an AI-suggested action, or leave unchecked for human analyst attribution.
   - Click **Submit for Authorization**.
5. Verify that:
   - A banner appears: *"Pending Authorization (1) - Waiting for Security Manager Authorization"*.
   - The action is listed with badge `high risk` and tool `host.isolate`.

---

## 2. Anti-Self-Approval Enforcement

1. While still logged in as the requester, attempt to open `/manager/approvals`.
   - Access is restricted (only Security Managers and Organization Admins have write access).
2. If a Security Manager requests an action directly from the incident:
   - Opening `/manager/approvals` displays their request under **My Requests** and **Pending Queue**.
   - Attempting to click **Approve** on their own request is rejected by the backend with status `403 Forbidden` (`self_approval_not_allowed`).

---

## 3. Security Manager Queue & Approval

1. **Log in as Security Manager** (`security_manager` in the same organization).
2. Notice the Topbar badge:
   - A shield badge displays the pending count: *"1 Pending Approval"*.
3. Click the badge or navigate to **Authorizations & Approvals** (`/manager/approvals`):
   - The request appears in the **Pending Queue** with:
     - Tool: `host.isolate`
     - Risk badge: `high risk` (danger tone)
     - Status: `pending` (brand tone)
     - Requester badge: `AI Agent` (with Bot icon) or `Analyst`
     - Expiration countdown / timestamp
4. Click **Details**:
   - The detail modal shows the full JSON argument payload preview, risk explanation, target incident link, and justification.
5. Click **Approve**:
   - Enter an optional authorization note (e.g. "Isolation approved per incident runbook").
   - Click **Confirm & Authorize**.
   - A success toast confirms authorization.
   - The item disappears from the Pending Queue and moves to **History** marked `approved`.

---

## 4. Exactly-Once Execution & Evidence Verification

1. In the database or audit logs:
   - Check `tool_call_logs`:
     - Row 1: `decision="needs_approval"`, `allowed=false`, `approval_id=<uuid>`, actor type matching requester.
     - Row 2: `decision="allow"`, `allowed=true`, `approval_id=<uuid>`, `result={"status": "simulated", "action": "isolate_host", ...}`.
     - `arguments_hash` is the canonical SHA-256 hash matching the executed arguments.
   - Check `incidents.incident_timeline`:
     - A timeline entry records: *"Executed host.isolate (risk: high) ... Requested earlier; executed on approval."*
2. Verify that double-execution is impossible:
   - Attempting to re-invoke `execute_approved_action` on the same approval row returns `already_executed`.

---

## 5. Rejection Flow

1. From an incident, submit a containment action (e.g., **Disable Account**).
2. In the Security Manager's queue, click **Reject**:
   - The dialog requires a justification reason.
   - Clicking Confirm without a reason is blocked.
   - Enter reason: *"Account is an automated service principal. Manual credential rotation required."*
   - Click **Confirm Rejection**.
3. Verify that:
   - The approval status becomes `rejected`.
   - The action NEVER executes (no mock device call, no timeline entry).
   - The rejection reason is recorded in the decision record and audit log.

---

## 6. Automated Low-Risk Actions Toggle

1. In organization settings:
   - When `low_risk_automation_enabled` is `false`: Low-risk actions (comments, tags, priority nudges) require approval (`needs_approval`).
   - When `low_risk_automation_enabled` is `true`: Low-risk actions run automatically (`allow`) without queuing an approval.
