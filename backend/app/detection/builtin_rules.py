"""
The built-in detection rules (P23): eight platform-shipped rules, each
with id (stable slug -- the seeding key), name, description, severity,
MITRE ATT&CK technique id, and a one-line "why it matters".

These are DATA: every definition validates against
app/detection/definitions.py, and seeding writes DetectionRule rows
(organization_id NULL) keyed by the slug in `builtin_id`. The worker
seeds idempotently at startup (ON CONFLICT on the partial unique name
index, updating the definition/description so tuned rules ship to
every environment) -- per-organization enable/disable lives in
organization_rule_settings and survives re-seeding.

Tuning note: thresholds/windows are deliberately chosen so the
simulator's benign_noise scenario produces zero hits and the brute
force scenario produces the full expected hit set (pinned by tests).
"""

from __future__ import annotations

from app.detection.definitions import (
    PatternCondition,
    PatternDefinition,
    SequenceDefinition,
    SequenceStep,
    ThresholdDefinition,
)
from app.models import DetectionRuleType, EventSeverity


class BuiltinRule:
    """One built-in rule's full payload -- everything seeding writes."""

    def __init__(
        self,
        *,
        builtin_id: str,
        name: str,
        description: str,
        rule_type: DetectionRuleType,
        condition: dict,
        severity: EventSeverity,
        mitre_technique: str,
        why_it_matters: str,
    ) -> None:
        self.builtin_id = builtin_id
        self.name = name
        self.description = description
        self.rule_type = rule_type
        self.condition = condition
        self.severity = severity
        self.mitre_technique = mitre_technique
        self.why_it_matters = why_it_matters
        self.validate()

    def validate(self) -> None:
        """Fail fast at import time if a definition doesn't validate --
        a broken built-in rule must never reach the seeding loop."""
        from app.detection.definitions import parse_definition

        parse_definition(self.rule_type.value, self.condition)

    def to_row(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "rule_type": self.rule_type,
            "condition": self.condition,
            "severity": self.severity,
            "mitre_technique": self.mitre_technique,
            "enabled": True,
        }


BUILTIN_RULES: list[BuiltinRule] = [
    BuiltinRule(
        builtin_id="repeated-failed-logins",
        name="Repeated failed logins",
        description=(
            "20 or more failed logon events for the same user within 10 minutes. "
            "Classic password spraying or brute force against one account."
        ),
        rule_type=DetectionRuleType.threshold,
        condition=ThresholdDefinition(
            event_types=["logon_failure", "auth_failure"],
            threshold=20,
            window_seconds=600,
            group_by="user",
        ).model_dump(),
        severity=EventSeverity.high,
        mitre_technique="T1110",
        why_it_matters=(
            "Attackers guess passwords by volume; the tell is repetition, and the "
            "target user is the one account that needs attention (or locking) first."
        ),
    ),
    BuiltinRule(
        builtin_id="success-after-failures",
        name="Successful login after many failures",
        description=(
            "A successful logon for a user that recorded 10 or more failures in the "
            "previous 15 minutes -- the guess may have just succeeded."
        ),
        rule_type=DetectionRuleType.sequence,
        condition=SequenceDefinition(
            steps=[
                SequenceStep(event_type="logon_failure"),
                SequenceStep(event_type="logon_success"),
            ],
            window_seconds=900,
            group_by="user",
        ).model_dump(),
        severity=EventSeverity.critical,
        mitre_technique="T1110",
        why_it_matters=(
            "Failures followed by success is the strongest single signal of a "
            "compromised password; treat the account as attacker-controlled until "
            "verified."
        ),
    ),
    BuiltinRule(
        builtin_id="privileged-group-change",
        name="Privileged group membership change",
        description=(
            "A group_change event, or a process whose raw record names a privileged "
            "group (sudo, wheel, Domain Admins) -- covering both the clean event and "
            "the raw command line that adds a user to it."
        ),
        rule_type=DetectionRuleType.pattern,
        condition=PatternDefinition(
            match=[
                PatternCondition(
                    field="event_type",
                    op="regex",
                    value="group_change|process_create",
                ),
                PatternCondition(
                    field="normalized.message",
                    op="regex",
                    value=r"(?i)domain admins|\bsudo\b|\bwheel\b|add .* to group|net group",
                ),
            ],
            exclude=[
                # The platform's own service accounts are expected to
                # manage groups; everything else is signal.
                PatternCondition(field="user", op="starts_with", value="svc."),
            ],
        ).model_dump(),
        severity=EventSeverity.high,
        mitre_technique="T1098",
        why_it_matters=(
            "Group membership is persistence: whoever controls a privileged group "
            "membership controls what the account can do next."
        ),
    ),
    BuiltinRule(
        builtin_id="new-local-user",
        name="New local user created",
        description="A user account was created on a Linux host (useradd) or Windows (4720) -- including service accounts, which are exactly what attackers create for persistence.",
        rule_type=DetectionRuleType.pattern,
        condition=PatternDefinition(
            match=[
                PatternCondition(
                    field="event_type",
                    op="regex",
                    value="user_add|account_created",
                ),
            ],
        ).model_dump(),
        severity=EventSeverity.medium,
        mitre_technique="T1136",
        why_it_matters=(
            "Unexpected accounts are a favorite persistence trick; on servers they "
            "should be rare, planned, and traceable to a change request."
        ),
    ),
    BuiltinRule(
        builtin_id="service-installed",
        name="Service installed",
        description="A new Windows service was installed (event 7045) on any host.",
        rule_type=DetectionRuleType.pattern,
        condition=PatternDefinition(
            match=[PatternCondition(field="event_type", op="eq", value="service_install")],
        ).model_dump(),
        severity=EventSeverity.high,
        mitre_technique="T1543.003",
        why_it_matters=(
            "Services run at boot with SYSTEM privileges -- a planted service is "
            "durable malware persistence that survives reboots."
        ),
    ),
    BuiltinRule(
        builtin_id="audit-log-cleared",
        name="Audit log cleared",
        description="The Windows security log was cleared (event 1102).",
        rule_type=DetectionRuleType.pattern,
        condition=PatternDefinition(
            match=[PatternCondition(field="event_type", op="eq", value="log_cleared")],
        ).model_dump(),
        severity=EventSeverity.critical,
        mitre_technique="T1070.001",
        why_it_matters=(
            "Log clearing usually means hiding tracks: whatever happened just before "
            "this event is what the attacker didn't want recorded."
        ),
    ),
    BuiltinRule(
        builtin_id="suspicious-process-path",
        name="Suspicious process from a user-writable path",
        description=(
            "A process created from a user-writable location (Temp, Downloads, AppData) "
            "or flagged with a Zone.Identifier mark of the web."
        ),
        rule_type=DetectionRuleType.pattern,
        condition=PatternDefinition(
            match=[
                PatternCondition(field="event_type", op="eq", value="process_create"),
                PatternCondition(
                    field="raw.process_name",
                    op="regex",
                    value=r"(?i)(^|[\\/])(temp|downloads|appdata)[\\/]",
                ),
            ],
            exclude=[
                PatternCondition(field="raw.process_name", op="ends_with", value="msedge.exe"),
            ],
        ).model_dump(),
        severity=EventSeverity.high,
        mitre_technique="T1059",
        why_it_matters=(
            "Executables don't belong in user-writable folders on servers; this is "
            "where downloaded droppers and living-off-the-land payloads land."
        ),
    ),
    BuiltinRule(
        builtin_id="admin-login-new-ip",
        name="Admin login from a new IP",
        description=(
            "A successful application login followed by privileged activity (sudo) "
            "from the same source IP within 30 minutes."
        ),
        rule_type=DetectionRuleType.sequence,
        condition=SequenceDefinition(
            steps=[
                SequenceStep(event_type="app_login"),
                SequenceStep(event_type="sudo_command"),
            ],
            window_seconds=1800,
            group_by="ip",
        ).model_dump(),
        severity=EventSeverity.high,
        mitre_technique="T1078",
        why_it_matters=(
            "Valid-accounts abuse from an unfamiliar source is how stolen credentials "
            "become incidents; the IP is the pivot for blocking and scoping."
        ),
    ),
]

BUILTIN_BY_ID: dict[str, BuiltinRule] = {rule.builtin_id: rule for rule in BUILTIN_RULES}
