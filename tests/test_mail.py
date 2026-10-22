"""
SentinelX QA Test Suite: Phishing Email Ingestion & Analysis.

Module: MAIL
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

import re
import pytest
from tc import tc


def analyze_email_payload(email_record: dict) -> dict:
    """
    Simulated SentinelX email threat analyzer heuristics:
    Inspects sender domain, urgent keywords, suspicious URLs, and attachment extensions.
    """
    subject = email_record.get("subject", "").lower()
    body = email_record.get("body", "").lower()
    attachments = email_record.get("attachments", [])
    sender = email_record.get("sender", "").lower()

    indicators = []
    is_phishing = False
    severity = "low"

    # Check suspicious executable attachments (dual extension, .exe, .scr, .iso)
    for att in attachments:
        filename = att.lower()
        if re.search(r"\.(exe|scr|bat|vbs|cmd|iso|hta)$", filename) or re.search(r"\.[a-z0-9]+\.(exe|scr|bat)$", filename):
            indicators.append(f"Malicious executable attachment detected: {att}")
            is_phishing = True
            severity = "high"

    # Check credential harvesting links and urgency keywords
    urgent_keywords = ["urgent", "immediate action required", "password expired", "account suspended", "verify your account"]
    has_urgency = any(kw in subject or kw in body for kw in urgent_keywords)

    suspicious_urls = [
        r"http:\/\/[^\/]+\/(login|verify|update-password)",
        r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}",
        r"\b(bit\.ly|tinyurl\.com|free-login-sec)\b",
    ]
    has_suspicious_url = any(re.search(pat, body) for pat in suspicious_urls)

    if has_urgency and has_suspicious_url:
        indicators.append("Credential harvesting lure with spoofed urgency and suspicious URL")
        is_phishing = True
        severity = "critical"
    elif has_suspicious_url:
        indicators.append("Suspicious URL detected in body")
        is_phishing = True
        severity = "medium"

    return {
        "is_phishing": is_phishing,
        "severity": severity if is_phishing else None,
        "indicators": indicators,
    }


@tc(
    id="MAIL-01",
    module="EmailAnalysis",
    description="Analyze phishing email with urgency lure and fake login URL",
    preconditions="Email analyzer heuristics ready",
    steps="Pass email payload containing credential harvester link to analyzer",
    expected="Analyzer flags is_phishing=True with Critical severity and indicator list",
    type="automated",
    owner="Aanchal Rai",
)
def test_mail_01_credential_harvester_detected():
    email = {
        "sender": "security-support@paypa1-update.com",
        "recipient": "employee@targetcorp.com",
        "subject": "URGENT: Your account has been suspended",
        "body": "Your access will be revoked within 2 hours. Please verify your credentials at http://192.168.1.50/login immediately.",
        "attachments": [],
    }

    result = analyze_email_payload(email)
    assert result["is_phishing"] is True
    assert result["severity"] == "critical"
    assert len(result["indicators"]) > 0
    assert any("Credential harvesting" in ind for ind in result["indicators"])


@tc(
    id="MAIL-02",
    module="EmailAnalysis",
    description="Analyze phishing email with dual-extension executable attachment",
    preconditions="Email analyzer heuristics ready",
    steps="Pass email payload with attachment 'Invoice_October_2026.pdf.exe'",
    expected="Analyzer flags is_phishing=True with High severity and attachment warning",
    type="automated",
    owner="Ansh",
)
def test_mail_02_executable_attachment_flagged():
    email = {
        "sender": "accounts-billing@external-vendor.com",
        "recipient": "finance@targetcorp.com",
        "subject": "Overdue invoice for review",
        "body": "Please find attached the past due balance statement.",
        "attachments": ["Invoice_October_2026.pdf.exe"],
    }

    result = analyze_email_payload(email)
    assert result["is_phishing"] is True
    assert result["severity"] == "high"
    assert any("Malicious executable attachment" in ind for ind in result["indicators"])


@tc(
    id="MAIL-03",
    module="EmailAnalysis",
    description="Analyze benign corporate newsletter email without threat indicators",
    preconditions="Email analyzer heuristics ready",
    steps="Pass benign internal all-hands announcement email",
    expected="Analyzer returns is_phishing=False with no indicators",
    type="automated",
    owner="Riteka Singh",
)
def test_mail_03_benign_newsletter_cleared():
    email = {
        "sender": "internal-communications@targetcorp.com",
        "recipient": "all-staff@targetcorp.com",
        "subject": "Company Town Hall Meeting This Friday",
        "body": "Join us on Friday at 3 PM in the auditorium for quarterly updates and team recognition.",
        "attachments": ["TownHall_Agenda.pdf"],
    }

    result = analyze_email_payload(email)
    assert result["is_phishing"] is False
    assert result["severity"] is None
    assert len(result["indicators"]) == 0

