"""Deterministic rule-based triage fallback (AI SOC Analyst milestone).

When AI is disabled, over budget or unavailable, the alert pipeline
must still produce an analysis -- so the SAME TriageResult shape is
filled from deterministic signals and marked source="rules". A fallback
analysis is honest about what it is: no confidence theater, generic
actions, and reasoning that names why the model was not used.
"""

from __future__ import annotations

from app.ai.schemas import TriageResult
from app.models import Alert


def build_fallback_result(alert: Alert, *, reason: str) -> TriageResult:
    """A rules-only triage for `alert`. `reason` names WHY the model was
    not used ("ai_disabled", "over_budget", "ai_unavailable: ...") and
    lands in the reasoning text and the run's error field, so an
    auditor never has to guess."""
    rule_summary = alert.summary or ""
    text = f"{alert.title} {rule_summary}".lower()

    # The rule's own severity is the only deterministic severity signal
    # available without the model -- restating it beats inventing one.
    severity = alert.severity

    if any(m in text for m in ("brute", "privilege", "escalation", "audit log cleared", "cleared")):
        actions = [
            "Review the matching events in the alert detail view.",
            "Confirm with the asset owner whether the activity was expected.",
        ]
    else:
        actions = ["Review the matching events in the alert detail view."]

    return TriageResult(
        severity=severity,
        confidence=0.0,  # a rule restatement carries no model confidence
        summary=(
            f"[rules] {rule_summary or alert.title} "
            f"({alert.event_count or 0} event(s); rule '{alert.rule_name}'). "
            f"AI triage not used ({reason}); severity restates the detection rule's rating."
        ),
        reasoning=f"Deterministic fallback -- {reason}. No model was called.",
        evidence_ids=[],  # never cite what the rules never verified
        recommended_actions=actions,
        false_positive_likelihood=0.0,
        source="rules",
    )
