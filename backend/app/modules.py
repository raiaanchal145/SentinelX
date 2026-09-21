"""
Single source of truth for module keys -- the pluggable capabilities a
platform admin turns on/off per organization, that an organization owner
can further restrict per role or per person, in backend/app/access.py.

Members, teams, access and settings pages are always available to the
organization owner and are NOT modules -- they aren't listed here.
"""

from enum import Enum


class ModuleKey(str, Enum):
    assets = "assets"
    soc = "soc"  # alerts, events, investigation
    incidents = "incidents"
    it_tickets = "it_tickets"
    approvals = "approvals"
    ai_agents = "ai_agents"
    device_agents = "device_agents"
    reports = "reports"
    audit_logs = "audit_logs"


ALL_MODULE_KEYS: list[str] = [m.value for m in ModuleKey]


def is_valid_module_key(key: str) -> bool:
    return key in ALL_MODULE_KEYS
