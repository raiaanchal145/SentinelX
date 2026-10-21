# Manual Test Checklist — Windows Endpoint Telemetry Agent (P21)

Verify end-to-end enrollment, DPAPI credential protection, real Windows Event Log collection, alert generation on failed logins, service operation, and kill-switch revocation.

---

## 1. Environment & Pre-requisite Check

1. Verify Python 3.11 environment on Windows:
   ```powershell
   python -m agent.main status
   ```
2. Verify that the agent outputs machine name, operating system (`Windows 10/11`), un-enrolled status, and SQLite buffer size (capped at 50 MB).

---

## 2. Enrollment & Consent Authorization

1. Log in to SentinelX as Security Manager or IT Developer (`/devices` or `/organization/devices`).
2. Click **Add Device**:
   - Target Asset: select your laptop asset or create one.
   - Device Name: e.g. `Laptop-Admin`.
   - OS: `Windows 11 Pro`.
   - Click **Generate Enrollment Token**.
3. Open the User Consent link (`/consent/enroll?token=sxe_...`):
   - Review the 6 category disclosures and prohibited data guarantees.
   - Keep `authentication`, `process_activity`, and `system_integrity` selected.
   - Click **Authorize & Register Endpoint**.
4. In an elevated or standard PowerShell terminal, enroll the agent:
   ```powershell
   python -m agent.main enroll --server http://localhost:8000/api/v1 --token sxe_<token>
   ```
5. Verify output:
   - `[+] ENROLLMENT SUCCESSFUL!`
   - Device ID is displayed.
   - Stored credentials are encrypted via Windows DPAPI in `C:\ProgramData\SentinelX\agent\device_key.dat`.
   - Run `python -m agent.main status` to confirm `Enrolled: True` with active categories.

---

## 3. Real Windows Event Log Ingestion & Liveness

1. Start the agent in foreground mode:
   ```powershell
   python -m agent.main run --foreground
   ```
2. Verify initial output:
   - `Initial heartbeat confirmed. Active categories: ['authentication', 'process_activity', ...]`
   - Heartbeat repeats every 30 seconds.
3. Open the SentinelX Web UI:
   - Navigate to **Devices** (`/devices`).
   - Confirm your laptop status is **Connected (< 2m)** with a green pulsing dot.
   - In **SOC Overview** (`/soc`), verify the **Agent & Device Health** widget shows `Connected: 1`.

---

## 4. Safe Failed Logon Generation & Brute Force Alert Trigger

1. In a separate PowerShell window, run the safe test script:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\agent\tools\test_failed_logon.ps1 -Count 25
   ```
2. Observe script progress:
   - Triggers 25 non-destructive logon failures for dummy user `SentinelXTestUser`.
   - Confirms that Windows Security Log generated real Event ID 4625 entries.
3. Observe agent terminal:
   - Within 3–5 seconds, the agent polls the 25 new events from the `Security` channel.
   - Events are buffered into `queue.db` and delivered to `/api/v1/events`.
   - Delivery log reports: `Delivered 25 events to SentinelX.`
4. In the SentinelX Web UI:
   - Navigate to **SOC Overview** (`/soc`) or **Alerts** (`/soc/alerts`).
   - Verify that the **Repeated failed logins** detection rule fired (threshold $\ge 20$ within 10m).
   - Click the alert to open the Alert Drawer:
     - Cited events link directly to the genuine 4625 events produced on your laptop.
     - Event details show user `SentinelXTestUser`, source type `windows`, event type `logon_failure`.

---

## 5. Windows Service Management

1. In an Administrator PowerShell terminal:
   ```powershell
   # 1. Install service
   python -m agent.main service install

   # 2. Check task status
   python -m agent.main service status

   # 3. Start task
   python -m agent.main service start

   # 4. Check log file output
   Get-Content C:\ProgramData\SentinelX\agent\logs\agent.log -Tail 20

   # 5. Stop task
   python -m agent.main service stop

   # 6. Uninstall task
   python -m agent.main service uninstall
   ```
2. Confirm that the task installs under `NT AUTHORITY\SYSTEM` and removes cleanly without leftover registry artifacts.

---

## 6. Immediate Kill-Switch Verification

1. With the agent running, open the device detail page in SentinelX (`/devices/{id}`).
2. Click **Revoke Device**, enter reason: *"Decommissioning laptop"*, and confirm.
3. Watch the agent terminal:
   - On the next 30-second heartbeat (or next batch ingestion attempt), the server responds with revocation.
   - The agent immediately logs:
     `[CRITICAL] KILL SWITCH TRIGGERED: Device authorization revoked by administrator. Ceasing collection and exiting.`
   - Local DPAPI credentials are wiped.
   - Process halts with exit code 2.
   - Subsequent event sends are rejected by SentinelX with `403 Forbidden: device_revoked`.

