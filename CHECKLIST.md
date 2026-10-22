# SentinelX QA Test Automation & Excel Sync Checklist

**Project:** SentinelX (SOC/SIEM Security Platform)  
**Team:** Ansh (TL), Riteka Singh, Aanchal Rai  
**Target Branch:** `ansh-dev`  

---

## 1. Setup & Configuration
- [ ] Initialize repository test structure (`pytest.ini`, `.gitattributes`, `requirements.txt`, `.env.example`)
- [ ] Configure `config.py` with strict Database Safety Guard (refuse hosted DBs, enforce "test" naming)
- [ ] Implement `@tc` decorator (`tc.py`) with strict field and regex ID validation (`^[A-Z]{2,6}-\d{2,4}$`)
- [ ] Setup `conftest.py` with collection validator (stop on duplicate IDs or bad formats), result makereport hook, and mock mailer

---

## 2. Test Suites Implementation
- [ ] **AUTH**: Authentication & Session Management (`tests/test_auth.py` - AUTH-01 to AUTH-08)
- [ ] **ORG**: Organization Lifecycle & Invitations (`tests/test_org.py` - ORG-01 to ORG-07)
- [ ] **RBAC**: Multi-Tenancy & Role-Based Access Control (`tests/test_rbac.py` - RBAC-01 to RBAC-04)
- [ ] **LOG**: Log Ingestion & Rate Limiting (`tests/test_log_ingest.py` - LOG-01 to LOG-04)
- [ ] **NET**: Network Signal & Port Scan Detection (`tests/test_network.py` - NET-01 to NET-04)
- [ ] **MAIL**: Phishing Email Ingestion & Analysis (`tests/test_mail.py` - MAIL-01 to MAIL-03)
- [ ] **ALR**: Alert Generation & Criticality Lifecycle (`tests/test_alerts.py` - ALR-01 to ALR-04)
- [ ] **REM**: AI Remedy & Playbook Suggestions (`tests/test_remedy.py` - REM-01 to REM-02)
- [ ] **TKT**: Ticket Creation & SLA Assignment (`tests/test_tickets.py` - TKT-01 to TKT-03)
- [ ] **DASH**: SOC & IT Oversight Dashboards (`tests/test_dashboard.py` - DASH-01 to DASH-02)
- [ ] **SEC**: Security Hardening: SQL Injection, XSS, Bcrypt (`tests/test_security.py` - SEC-01 to SEC-04)
- [ ] **DB**: Test Database Schema & Migration Safety (`tests/test_db.py` - DB-01 to DB-02)

---

## 3. Labelled Dataset & Detection Accuracy
- [ ] Create labelled security dataset in `tests/data/` (logs, network, emails) with ground-truth manifest
- [ ] Implement `tests/test_detection_accuracy.py` computing confusion matrix (TP, FP, TN, FN)
- [ ] Calculate accuracy, precision, recall, and F1 score with threshold >= 0.80 assertion

---

## 4. Excel Sync Engine (`excel_sync.py`)
- [ ] Create initial `test_cases.xlsx` with standard columns and formatted styling
- [ ] Implement automatic sync hook in pytest (`pytest_sessionfinish`)
- [ ] Implement natural ID sorting (`AUTH-02` before `AUTH-10`)
- [ ] Ensure user remarks in `Remarks` column are NEVER overwritten
- [ ] Implement backup rotation in `backups/` (keep last 5 timestamped copies)
- [ ] Handle locked Excel file (`PermissionError`) with safe fallback save and warning
- [ ] Implement safety check: add/delete only on full run; subset run updates results only
- [ ] Rebuild auxiliary sheets:
  - [ ] `Run_History` (timestamp, totals, pass/fail counts, pass rate %, git commit hash)
  - [ ] `Summary` (per-module counts and pass rates)
  - [ ] `Detection_Metrics` (confusion matrix, precision, recall, F1, per-severity breakdown)
  - [ ] `Removed_Cases` (deleted cases archive with removal timestamp and reason)

---

## 5. CLI Automation Tools
- [ ] Create `sync_excel.py` supporting `--sync-only` and `--dry-run`
- [ ] Create `new_test.py` auto-allocating next available TC ID for any module

---

## 6. Sync Logic Unit Tests (`tests/test_excel_sync.py`)
- [ ] SYNC-01: Auto-generate `test_cases.xlsx` if missing
- [ ] SYNC-02: Add new test from code with status `NOT RUN`
- [ ] SYNC-03: Move deleted test to `Removed_Cases`
- [ ] SYNC-04: Preserve user remarks on re-sync
- [ ] SYNC-05: Handle locked Excel file gracefully
- [ ] SYNC-06: Database safety guard refuses execution on hosted/shared DBs

---

## 7. Verification & Team Documentation
- [ ] Full test execution (`pytest -v`) passes cleanly and updates `test_cases.xlsx`
- [ ] Verified `sync_excel.py --dry-run` and `sync_excel.py --sync-only`
- [ ] Verified `new_test.py` generates boilerplate test with next ID
- [ ] Update documentation (`README.md`, team rules, Git workflow)
