"""Deterministic fake provider -- CI and the eval harness NEVER call
the network (AI SOC Analyst doc §24: reproducibility).

It implements the same AiProvider protocol as OpenAICompatProvider and
mimics a plausible triage analyst with pure string rules over the user
message, so the same input always yields the same verdict:

- escalation-flavored event types  -> critical/high severity
- auth failure storms              -> high
- downloads / policy events        -> medium
- benign markers (routine, backup) -> low/info + high FP likelihood

The fake deliberately IGNORES anything that looks like an instruction
inside the data block (it only reads data-shape cues), which makes the
injection tests meaningful end-to-end: even a provider that "obeys"
would still be bounded by the wrapper, and the pipeline's grounding
check rejects any evidence id that was not shown.

Nothing was billed, but the returned AiCallResult still carries token
counts (len/4) priced at the default model rates -- so the service's
cost ledger and the eval's cost estimates exercise the same math.
"""

from __future__ import annotations

import re
import time

from app.ai.client import AiCallResult, AiProvider

# Event-type markers the simulator scenarios emit (tools/simulator)
# plus generic variants -- checked in this order: critical, high, medium,
# then benign (benign only counts when NO escalation marker matched).
_CRITICAL_MARKERS = ("privilege_escalation", "audit_log_cleared", "log_cleared")
_HIGH_MARKERS = ("bruteforce", "brute_force", "logon_failure", "failed logon", "logon failed")
_MEDIUM_MARKERS = (
    "suspicious_download",
    "policy_violation",
    "service_install",
    "user_add",
    "account_created",
    "new user",
)
_BENIGN_MARKERS = ("benign", "routine", "scheduled", "backup", "planned")

_EVENT_ID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
# Only ids introduced as EVENT ids count as citable evidence -- the
# prompt also contains the alert's own id, which must never be cited.
_EVENT_ID_LINE_RE = re.compile(r"event_id:\s*([0-9a-f-]{36})", re.IGNORECASE)


class FakeProvider(AiProvider):
    """Deterministic, network-free AiProvider for tests and evals."""

    def __init__(self, *, model: str = "fake-triage") -> None:
        self.model = model

    async def complete(self, messages: list[dict[str, str]]) -> AiCallResult:
        user_text = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        # The shape selector needs the whole conversation: the incident
        # agent's shape marker ('ticket_draft') lives in the SYSTEM
        # prompt, and the untrusted data sits in the user message. The
        # verdict keywords only ever match data-shape cues -- never
        # instructions -- so reading the system text introduces no new
        # injection surface.
        shape_text = "\n".join(m.get("content", "") for m in messages)
        verdict = self._verdict(shape_text, user_text)
        prompt_tokens = len(shape_text) // 4
        completion_tokens = len(verdict) // 4
        return AiCallResult(
            text=verdict,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=self.model,
            attempts=1,
            latency_ms=0,
        )  # cost_usd: estimated at default prices -- nothing was actually billed

    def _verdict(self, shape_text: str, user_text: str) -> str:
        lowered = user_text.lower()
        event_ids = _EVENT_ID_LINE_RE.findall(user_text)

        critical = any(m in lowered for m in _CRITICAL_MARKERS)
        high = any(m in lowered for m in _HIGH_MARKERS)
        medium = any(m in lowered for m in _MEDIUM_MARKERS)
        benign = any(m in lowered for m in _BENIGN_MARKERS)

        if critical:
            severity, confidence, fp = "critical", 0.9, 0.05
            summary = "Escalation-flavored activity consistent with an active intrusion attempt."
        elif high:
            severity, confidence, fp = "high", 0.8, 0.1
            summary = "Repeated logon failures followed by a success suggesting a brute-force pattern."
        elif medium:
            severity, confidence, fp = "medium", 0.75, 0.3
            summary = "Suspicious but contained activity; analyst review recommended."
        elif benign:
            severity, confidence, fp = "low", 0.7, 0.8
            summary = "Activity matches routine scheduled behavior; likely false positive."
        else:
            severity, confidence, fp = "low", 0.6, 0.5
            summary = "No strong attack signals in the provided data; low priority."

        reasoning = (
            f"Fake provider: deterministic keyword verdict from {len(event_ids)} seen event(s); "
            "injection-like text in the data block was ignored."
        )
        actions = (
            ["Verify with the asset owner whether the activity was expected."]
            if severity != "low"
            else ["No action needed; close if the pattern is known-benign."]
        )
        import json

        # The prompt's shape marker decides the verdict shape: the
        # incident agent's prompt interpolates INCIDENT_JSON_SHAPE, which
        # is the only prompt mentioning "ticket_draft". Same keyword
        # verdict, but emitted in the shape the caller's parser needs --
        # one provider must serve both agents (triage + incident draft).
        if "ticket_draft" in shape_text.lower():
            priority = {"critical": "P1", "high": "P2", "medium": "P3"}.get(severity, "P4")
            status_suggestion = "investigating" if severity in ("critical", "high") else "triaged"
            return json.dumps(
                {
                    "title": summary[:200],
                    "summary": summary,
                    "timeline_entries": [
                        {
                            "description": f"Agency verdict recorded from {len(event_ids)} seen event(s): {summary}",
                            "evidence_ids": event_ids[:5],
                        }
                    ],
                    "ticket_draft": {
                        "description": (
                            f"Remediation for the reviewed activity: {summary} "
                            "(fake provider draft -- analyst reviews before creation)."
                        ),
                        "remediation_steps": actions,
                        "suggested_priority": priority,
                        "suggested_team": None,
                    },
                    "severity": severity,
                    "status_suggestion": status_suggestion,
                    "confidence": confidence,
                    "false_positive_likelihood": fp,
                    "reasoning": reasoning,
                }
            )

        return json.dumps(
            {
                "severity": severity,
                "confidence": confidence,
                "summary": summary,
                "reasoning": reasoning,
                "evidence_ids": event_ids[:5],
                "recommended_actions": actions,
                "false_positive_likelihood": fp,
            }
        )


class ScriptedProvider(AiProvider):
    """Test double that returns CANNED outputs in order -- for pinning
    the repair path (first invalid, then valid) without any logic."""

    def __init__(self, outputs: list[str | Exception]) -> None:
        self.outputs = list(outputs)
        self.calls = 0
        self.last_messages: list[dict[str, str]] | None = None

    async def complete(self, messages: list[dict[str, str]]) -> AiCallResult:
        self.calls += 1
        self.last_messages = messages
        item = self.outputs.pop(0) if self.outputs else ""
        if isinstance(item, Exception):
            raise item
        return AiCallResult(
            text=item,
            prompt_tokens=len(str(messages)) // 4,
            completion_tokens=len(item) // 4,
            model="scripted",
            attempts=self.calls,
            latency_ms=0,
        )
