"""
Consent categories, versioning, and event-type mappings (P20).

Enforces consent-based monitoring with strict transparency and zero secret collection:
- Each category explicitly states what is monitored and what is strictly prohibited.
- Events ingested from enrolled device agents are checked against active consent records.
- If an event's type belongs to a non-consented category, it is discarded at ingestion
  and counted in `rejected_no_consent`.
"""

from __future__ import annotations

from typing import Any

CONSENT_TEXT_VERSION = "v1.0"

CONSENT_CATEGORIES: dict[str, dict[str, Any]] = {
    "authentication": {
        "key": "authentication",
        "label": "Sign-in & Authentication Events",
        "description": "Logon success/failure, lockouts, sudo executions, and session activity to detect unauthorized access.",
        "event_types": [
            "logon_success",
            "logon_failure",
            "account_lockout",
            "auth_success",
            "auth_failure",
            "sudo_command",
            "app_login",
            "app_login_failed",
        ],
        "prohibited": "Keystrokes, passwords, clipboard contents, biometric data.",
    },
    "process_activity": {
        "key": "process_activity",
        "label": "Process & Service Activity",
        "description": "Creation and termination of processes, service installations, and background daemon execution.",
        "event_types": [
            "process_create",
            "service_install",
            "scheduled_task",
            "container_start",
            "container_stop",
            "container_kill",
            "container_create",
            "container_destroy",
        ],
        "prohibited": "Window titles of personal apps, private document names, browser history.",
    },
    "system_integrity": {
        "key": "system_integrity",
        "label": "System & Account Changes",
        "description": "User account modifications, local security policy edits, log clearance, and package installations.",
        "event_types": [
            "account_created",
            "account_disabled",
            "user_add",
            "user_delete",
            "group_change",
            "log_cleared",
            "policy_change",
            "package_install",
            "config_change",
            "permission_change",
        ],
        "prohibited": "Personal file contents, private configurations, encryption keys.",
    },
    "network_connections": {
        "key": "network_connections",
        "label": "Network & Connection Signals",
        "description": "Connection flow logs, firewall blocks, and DNS lookups to identify C2 communication.",
        "event_types": [
            "connection_allowed",
            "connection_blocked",
            "firewall_allow",
            "firewall_deny",
            "dns_query",
            "dns_response",
            "port_scan",
            "ids_alert",
        ],
        "prohibited": "Packet capture (PCAP) payloads, unencrypted communication content.",
    },
    "security_defenses": {
        "key": "security_defenses",
        "label": "Antivirus & Defender Signals",
        "description": "Endpoint antivirus triggers, malware detections, and security agent status.",
        "event_types": ["ids_alert", "app_warning", "app_error"],
        "prohibited": "Non-malicious personal files and private directories.",
    },
    "file_downloads": {
        "key": "file_downloads",
        "label": "File Downloads & Executable Hashes",
        "description": "Origin URLs and SHA-256 hashes of downloaded binaries and executables.",
        "event_types": ["custom", "image_pull", "image_push"],
        "prohibited": "Personal photos, personal documents, webcam, audio, or desktop contents.",
    },
}

ALL_CATEGORY_KEYS: frozenset[str] = frozenset(CONSENT_CATEGORIES.keys())

# Build mapping from event_type to category key
EVENT_TO_CATEGORY: dict[str, str] = {}
for _cat_key, _info in CONSENT_CATEGORIES.items():
    for _etype in _info["event_types"]:
        # Only assign if not already assigned (first match wins)
        if _etype not in EVENT_TO_CATEGORY:
            EVENT_TO_CATEGORY[_etype] = _cat_key

# Diagnostic/test event type mapping: allowed if any category is granted
ALWAYS_ALLOWED_TYPES = {"test_event"}


def get_category_for_event(event_type: str) -> str | None:
    """Returns the consent category required for an event type, or None if uncategorized."""
    if event_type in ALWAYS_ALLOWED_TYPES:
        return "test_event"
    return EVENT_TO_CATEGORY.get(event_type)


def is_event_consented(event_type: str, granted_categories: list[str] | set[str]) -> bool:
    """Check if an event type is permitted under the given set of granted categories."""
    if event_type in ALWAYS_ALLOWED_TYPES and granted_categories:
        return True
    cat = get_category_for_event(event_type)
    if cat is None:
        # Unknown or custom event types map to file_downloads / custom category or require custom grant
        return "file_downloads" in granted_categories
    return cat in granted_categories
