# SentinelX Windows Endpoint Agent

Privacy-preserving, consent-gated security telemetry agent for Windows endpoints.

---

## 1. Principles & Privacy Guarantees

- **No Secret Collection**: The agent does not monitor or transmit events until explicit consent has been authorized by the endpoint user.
- **Strict Data Boundaries**: Prohibited data categories (keystrokes, personal messages, web browser history/cookies, personal documents, and passwords) are **never** inspected or read.
- **Consent-Gated Subscriptions**: If a category (e.g. `file_downloads` or `process_activity`) is not authorized in the server's consent configuration, the agent excludes its Event IDs at the Windows kernel level (XPath filtering) and never queries those events.
- **Encrypted Local Storage**: Device API keys are encrypted at rest using Windows DPAPI (`CryptProtectData` with `CRYPTPROTECT_LOCAL_MACHINE` isolation). Keys and enrollment tokens are never logged.
- **Automatic Kill Switch**: If an organization administrator revokes the device or its consent, the heartbeat response (`terminate: true` / `status: "revoked"`) immediately causes the agent to erase local credentials and halt execution.

---

## 2. Monitored Windows Event IDs & Schema Mapping

All collected telemetry is mapped into SentinelX Normalized Event Schema v1.0:

| Event ID | Channel | Description | SentinelX `event_type` | Required Category | Severity |
|---|---|---|---|---|---|
| **4624** | Security | Successful Logon | `logon_success` | `authentication` | `info` |
| **4625** | Security | Failed Logon Attempt | `logon_failure` | `authentication` | `medium` |
| **4634** | Security | User Logoff | `logon_success` | `authentication` | `info` |
| **4672** | Security | Special Privileges Assigned | `logon_success` | `authentication` | `info` |
| **4688** | Security | Process Creation (CommandLine) | `process_create` | `process_activity` | `info` |
| **4720** | Security | User Account Created | `account_created` | `system_integrity` | `medium` |
| **4722** | Security | User Account Enabled | `policy_change` | `system_integrity` | `info` |
| **4724** | Security | Password Reset Attempt | `policy_change` | `system_integrity` | `medium` |
| **4726** | Security | User Account Deleted | `user_delete` | `system_integrity` | `medium` |
| **4740** | Security | Account Locked Out | `account_lockout` | `authentication` | `high` |
| **7045** | System | New Service Installed | `service_install` | `process_activity` | `medium` |
| **1102** | Security | Security Audit Log Cleared | `log_cleared` | `system_integrity` | `high` |
| **1116** | Defender | Malware Detected | `ids_alert` | `security_defenses` | `high` |
| **1117** | Defender | Malware Action Taken | `ids_alert` | `security_defenses` | `medium` |
| **Downloads** | File System | Downloaded File (Zone 3 + SHA256) | `custom` | `file_downloads` | `info` / `medium` |

---

## 3. Installation & Enrollment Workflow

### Step 1: Generate Enrollment Token
In the SentinelX Web UI, an Owner, Security Manager, or IT Developer navigates to **Devices** (`/devices`) and clicks **Add Device**. This generates a single-use token valid for 30 minutes (`sxe_...`) and a consent review link.

### Step 2: User Authorization (Consent Screen)
The device user opens the consent link (`/consent/enroll?token=sxe_...`), reviews the explicit data disclosures, selects authorized categories, and signs the agreement.

### Step 3: Enroll Agent
On the Windows device (Administrator terminal recommended):
```powershell
python -m agent.main enroll --server http://<sentinelx-host>:8000/api/v1 --token sxe_<token>
```
The agent verifies consent, swaps the token for an encrypted per-device API key, and stores it in `C:\ProgramData\SentinelX\agent\device_key.dat` using Windows DPAPI.

---

## 4. Running the Agent

### Automatic Mode (Integrated Developer Launcher):
When developing locally, `npm run dev` automatically detects if the endpoint agent is enrolled and starts it in a dedicated window or inline with the backend, worker, and frontend:
```powershell
npm run dev
# Or run agent standalone:
npm run dev:agent
```
If the agent has not yet been enrolled, `npm run dev` skips it cleanly and prints an informative prompt.

### Foreground Mode (Testing / Development):
```powershell
python -m agent.main run --foreground
```

### Windows Service / Startup Task Mode:
Install as an elevated background task running under `NT AUTHORITY\SYSTEM`:
```powershell
# In an elevated Administrator PowerShell:
python -m agent.main service install
python -m agent.main service start
python -m agent.main service status
```

To stop or uninstall:
```powershell
python -m agent.main service stop
python -m agent.main service uninstall
```

### Checking Agent Status:
```powershell
python -m agent.main status
```

---

## 5. Reliability & Buffer Design

- **Windows Event Bookmarks**: Uses `EvtCreateBookmark` / `EvtUpdateBookmark` to track read positions, stored in `bookmarks.json`. Restarts resume reading without dropping or duplicating events.
- **Persistent Local Queue**: Telemetry is buffered in an SQLite WAL queue (`queue.db`) capped at **50 MB** (approx. 50,000 events). If the server is offline and the cap is reached, FIFO eviction drops the oldest events to protect endpoint disk space.
- **Exponential Backoff**: Ingestion retries use exponential backoff (1s, 2s, 4s, up to 60s) on network failures and respect HTTP 429 `Retry-After` headers.
- **Heartbeat**: Sent every 30 seconds to update liveness (`connected` $\le 2$m, `stale` $2\text{--}10$m, `offline` $> 10$m).

---

## 6. Resource Consumption

Measured on Windows 11 Pro (x64) during active telemetry collection:
- **Idle Memory Footprint**: ~28 MB – 36 MB RAM.
- **CPU Utilization**: < 0.2% on quad-core CPU.
- **Disk Footprint**: ~45 KB executable script footprint; SQLite buffer capped at 50 MB.

---

## 7. Testing & Verification

### Running Automated Unit Tests:
```powershell
pytest agent/tests
```

### Generating Safe Test Failed Logons:
To test detection of failed logons (Event ID 4625) without risking real account lockouts:
```powershell
# Generates 5 safe failed logons:
powershell -ExecutionPolicy Bypass -File .\agent\tools\test_failed_logon.ps1 -Count 5

# Generates 25 failed logons (triggers the SentinelX 'repeated-failed-logins' brute force rule):
powershell -ExecutionPolicy Bypass -File .\agent\tools\test_failed_logon.ps1 -Count 25
```
After running, check the SentinelX SOC Overview dashboard (`/soc`) to observe the alert firing with real citations from your device.

