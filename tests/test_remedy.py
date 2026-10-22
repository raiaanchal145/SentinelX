"""
SentinelX QA Test Suite: AI Remedy & Playbook Suggestions.

Module: REM
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

import pytest
from tc import tc


def generate_ai_remedy_plan(alert_context: dict) -> dict:
    """
    Simulates SentinelX AI remediation advisor engine:
    Evaluates alert context, threat classification, and recommends containment steps.
    """
    rule_name = alert_context.get("rule_name", "").lower()
    source_ip = alert_context.get("source_ip")
    username = alert_context.get("username")
    severity = alert_context.get("severity", "medium").lower()

    is_credential_threat = "brute" in rule_name or "logon" in rule_name or "failed logins" in rule_name

    actions = []
    if is_credential_threat:
        if username:
            actions.append({"action": "lock_user_account", "target": username, "requires_approval": True})
        if source_ip:
            actions.append({"action": "block_firewall_ip", "target": source_ip, "requires_approval": True})
        actions.append({"action": "force_password_reset", "target": username or "affected_users", "requires_approval": False})

    elif "malware" in rule_name or "beacon" in rule_name or "c2" in rule_name:
        actions.append({"action": "isolate_endpoint_host", "target": alert_context.get("host", "unknown-host"), "requires_approval": True})
        actions.append({"action": "kill_process_tree", "target": alert_context.get("process", "unknown-pid"), "requires_approval": True})

    else:
        actions.append({"action": "monitor_session", "target": username or source_ip or "target", "requires_approval": False})

    return {
        "playbook": "Credential Defense Playbook" if is_credential_threat else "Host Containment Playbook",
        "recommended_actions": actions,
        "requires_human_approval": any(a["requires_approval"] for a in actions),
        "priority": "P1-Immediate" if severity in {"critical", "high"} else "P3-Standard",
    }



@tc(
    id="REM-01",
    module="Remedy",
    description="AI remedy generates targeted containment steps for brute force attack",
    preconditions="Brute force alert context provided",
    steps="Pass brute force alert context to AI remedy generator",
    expected="Playbook generated with lock_user_account and block_firewall_ip recommendations",
    type="automated",
    owner="Riteka Singh",
)
def test_rem_01_brute_force_remedy_generation():
    alert = {
        "rule_name": "Repeated failed logins",
        "username": "victim.developer",
        "source_ip": "198.51.100.77",
        "severity": "high",
    }

    remedy = generate_ai_remedy_plan(alert)
    assert remedy["playbook"] == "Credential Defense Playbook"
    assert remedy["priority"] == "P1-Immediate"
    action_types = [a["action"] for a in remedy["recommended_actions"]]
    assert "lock_user_account" in action_types
    assert "block_firewall_ip" in action_types
    assert remedy["requires_human_approval"] is True


@tc(
    id="REM-02",
    module="Remedy",
    description="Remedy approval workflow flags sensitive containment actions for human sign-off",
    preconditions="Malware C2 beacon alert context",
    steps="Evaluate remedy plan for host isolation and verify requires_human_approval=True",
    expected="High-impact actions marked with requires_approval=True to prevent disruption",
    type="automated",
    owner="Aanchal Rai",
)
def test_rem_02_remedy_approval_guard():
    alert = {
        "rule_name": "Malware C2 beacon detected",
        "host": "srv-db-primary",
        "process": "svchost_fake.exe",
        "severity": "critical",
    }

    remedy = generate_ai_remedy_plan(alert)
    assert remedy["requires_human_approval"] is True
    sensitive_actions = [a for a in remedy["recommended_actions"] if a["requires_approval"]]
    assert len(sensitive_actions) >= 1
    assert any(a["action"] == "isolate_endpoint_host" for a in sensitive_actions)
