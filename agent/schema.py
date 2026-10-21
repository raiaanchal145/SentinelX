"""
Event Schema and Category Mappings for SentinelX Windows Endpoint Agent.

Validates outgoing records against SentinelX Event Ingestion API schema v1.0
and maps Windows Event IDs to fixed event_type vocabulary and consent categories.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"
SOURCE_TYPE = "windows"

# Mapping from Windows Event ID to SentinelX event_type vocabulary
EVENT_ID_TO_VOCABULARY: dict[int, str] = {
    4624: "logon_success",
    4625: "logon_failure",
    4634: "logon_success",      # Standard logoff
    4672: "logon_success",      # Special privileges assigned (elevated logon)
    4688: "process_create",
    4720: "account_created",
    4722: "policy_change",       # User account enabled
    4724: "policy_change",       # Password reset attempt
    4726: "user_delete",         # User account deleted
    4740: "account_lockout",
    7045: "service_install",
    1102: "log_cleared",         # Security audit log cleared
    1116: "ids_alert",           # Windows Defender malware detected
    1117: "ids_alert",           # Windows Defender action taken
}

# Mapping from Windows Event ID to required Consent Category
EVENT_ID_TO_CATEGORY: dict[int, str] = {
    4624: "authentication",
    4625: "authentication",
    4634: "authentication",
    4672: "authentication",
    4740: "authentication",
    4688: "process_activity",
    7045: "process_activity",
    4720: "system_integrity",
    4722: "system_integrity",
    4724: "system_integrity",
    4726: "system_integrity",
    1102: "system_integrity",
    1116: "security_defenses",
    1117: "security_defenses",
}

# Channels by category
CATEGORY_CHANNELS: dict[str, list[str]] = {
    "authentication": ["Security"],
    "process_activity": ["Security", "System"],
    "system_integrity": ["Security"],
    "security_defenses": ["Microsoft-Windows-Windows Defender/Operational"],
    "file_downloads": [],  # Handled by downloads collector
}

# Severity hints for events
EVENT_ID_SEVERITY: dict[int, str] = {
    4624: "info",
    4625: "medium",
    4634: "info",
    4672: "info",
    4688: "info",
    4720: "medium",
    4722: "info",
    4724: "medium",
    4726: "medium",
    4740: "high",
    7045: "medium",
    1102: "high",
    1116: "high",
    1117: "medium",
}


def get_event_category(event_id: int) -> str | None:
    """Returns the consent category required for a Windows event ID."""
    return EVENT_ID_TO_CATEGORY.get(event_id)


def is_collector_consented(event_id: int, granted_categories: set[str] | list[str]) -> bool:
    """Checks whether an event ID is permitted under the active consent categories."""
    category = get_event_category(event_id)
    if not category:
        return False
    return category in granted_categories


def format_utc_timestamp(dt: datetime | None = None) -> str:
    """Formats datetime as ISO-8601 UTC string (e.g. 2026-10-21T08:00:00.000000Z)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def create_event_record(
    *,
    event_type: str,
    message: str,
    timestamp: str | None = None,
    host: str | None = None,
    user: str | None = None,
    ip: str | None = None,
    process: str | None = None,
    severity_hint: str | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Constructs a compliant SentinelX event dictionary."""
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_type": SOURCE_TYPE,
        "event_type": event_type,
        "message": message,
        "timestamp": timestamp or format_utc_timestamp(),
    }
    if host:
        record["host"] = str(host)
    if user:
        record["user"] = str(user)
    if ip:
        record["ip"] = str(ip)
    if process:
        record["process"] = str(process)
    if severity_hint:
        record["severity_hint"] = severity_hint
    if raw is not None:
        record["raw"] = raw
    return record

