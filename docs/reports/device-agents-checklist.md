# Manual Test Checklist — Consented Device Monitoring & Enrollment (P20)

Verify end-to-end token generation, user consent authorization, single-use key exchange, telemetry filtering, liveness tracking, and immutable audit logging.

---

## 1. Enrollment Token Generation

1. **Log in as Security Manager or IT Developer** (`security_manager` or `it_developer` with `device_agents` write access).
2. Navigate to **Devices** (`/devices` or `/organization/devices`).
3. Click **Add Device**:
   - The dialog opens with the asset selector seeded from your organization's active assets.
   - Select a target asset (e.g. `Workstation-Alice`).
   - Enter/verify the device name and operating system (e.g., `Windows 11 Pro`).
   - Click **Generate Enrollment Token**.
4. Verify token creation:
   - Success view displays a 30-minute token (`sxe_...`) and full User Consent URL (`http://<host>/consent/enroll?token=sxe_...`).
   - Copy buttons for token and URL function with toast feedback.
   - Setup command is presented: `python -m agent.main enroll --token <token>`.
   - The new device appears in the device table with status `pending_consent`.

---

## 2. Consent Screen Review & Authorization

1. Open the generated consent URL in a browser (or navigate to `/consent/enroll` and paste the token).
2. The page loads without requiring an active employee login (token-authenticated):
   - Target asset name, type, operating system, and organization name are verified.
   - Agreement version is stamped (e.g. `Agreement v1.0`).
   - All 6 monitoring categories are displayed with clear disclosures:
     - **Authentication & Sign-in**: Sign-in successes/failures, MFA prompts, lock events.
     - **Process & Service Executions**: Process spawns, command-line hashes, process termination.
     - **System & Host Integrity**: Service installs, registry modifications, driver loads.
     - **Network Connections**: Socket connections, remote IP addresses, DNS resolutions.
     - **Security Defenses & Antivirus**: AV detections, firewall state toggles, tamper protection.
     - **File Downloads & Hashes**: Browser downloads, file writes, SHA-256 hashes.
   - Prohibited data boundaries are explicitly listed for each (keystrokes, personal messages, browser history/cookies, and documents are never monitored).
3. Deselect one category (e.g. uncheck `Network Connections`).
4. Check the acknowledgment box and click **Authorize & Register Endpoint**.
5. Verify success:
   - Confirmation displays a permanent consent record ID.
   - The command `python -m agent.main enroll --token <token>` is shown.
   - The device status on `/devices` changes to `offline` (awaiting first heartbeat) with active consent stamped.

---

## 3. Agent Enrollment & Single-Use Token Swap

1. Run the simulator or curl command with the enrollment token:
   ```bash
   python -m tools.simulator --api-url http://localhost:8000/api/v1 --device --enroll-token sxe_<token> --events 5
   ```
2. Verify agent swap:
   - Agent swaps the token at `POST /agent/enroll` and receives a revocable per-device API key (`sxa_...`).
   - Re-running enrollment with the same token is rejected (`409 Conflict: enrollment_token_used`).
   - Submitting an agent enrollment before consent is granted is rejected (`403 Forbidden: consent_required`).

---

## 4. Telemetry Filtering & Ingestion Enforcement

1. While the device agent is streaming events:
   - Events belonging to authorized categories (e.g. `authentication`, `process_activity`) are accepted and stored.
   - Events belonging to non-consented categories (e.g. `network_connections`) are rejected at the server:
     - The ingestion response reports `rejected_no_consent: 1`.
     - The non-consented event is discarded immediately and NOT saved in the database.
2. In the SOC workspace, verify that only consented event types appear in the events explorer.

---

## 5. Agent Liveness & Real-Time Status

1. In `/devices`:
   - While the agent sends heartbeats (`POST /agent/heartbeat`), verify the status displays **Connected (< 2m)** with a green pulsing indicator.
   - Stop the agent. After 2 minutes, verify the status transitions to **Stale (2-10m)** with an amber badge.
   - After 10 minutes without heartbeats, verify the status transitions to **Offline (> 10m)**.
2. In the SOC Dashboard (`/soc`):
   - Verify the **Agent & Device Health** widget displays live counts for connected, stale, and offline endpoints.
   - Clicking "View all &rarr;" routes directly to `/devices`.
3. In the Asset Inventory (`/soc/assets`, `/it/assets`, `/manager/assets`):
   - Verify the **Agent** column displays a status badge for assets that have an enrolled agent, linking to the device detail view.

---

## 6. Immutable Consent Updates & Audit Ledger

1. Open the device detail page (`/devices/{id}`).
2. Verify:
   - Header displays device name, hostname, asset link, OS, agent version, and last heartbeat.
   - Active Policy panel shows which of the 6 categories are consented vs prohibited.
   - Consent Audit Ledger displays the initial consent record (`v1.0`, signatory account, client IP, timestamp).
3. Click **Update Consent Policy**:
   - Check the previously excluded category (e.g., `Network Connections`).
   - Click **Sign & Save Policy**.
4. Verify immutability:
   - A NEW consent record is added to the Consent Audit Ledger.
   - The previous record remains in the ledger with status `Superseded`.
   - Ingestion immediately begins accepting network connection telemetry from this endpoint.

---

## 7. Immediate Revocation Enforcement

1. On the device detail page (`/devices/{id}`), click **Revoke Device**.
2. Enter a mandatory reason: *"Workstation decommissioned by IT"*.
3. Click **Confirm Revoke**:
   - The device status immediately transitions to `Revoked`.
   - Active consent is terminated and stamped in the audit ledger with the revocation reason and timestamp.
4. Verify immediate ingestion halt:
   - Any further events sent using this device key are rejected with `403 Forbidden: device_revoked`.
   - Heartbeat attempts return `403 Forbidden: device_revoked`.

