"""Pydantic response models for AI outputs (AI SOC Analyst milestone).

The model's raw text is NEVER trusted: `parse_triage_output()` coerces
it into `TriageResult` or raises `TriageValidationError` (whose message
feeds the one repair attempt). Field rules mirror the AI SOC Analyst
doc §11 (triage agent: likely severity, confidence, reasoning, evidence,
escalation recommendation) and §24 (evidence grounding -- cited ids must
be ids the model was actually shown; validated in service.py, which
knows the shown id set).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models import EventSeverity


class TriageValidationError(ValueError):
    """The model's output could not be parsed into a valid TriageResult."""


# The JSON shape the prompt asks for (and the fake provider emits).
# Kept in ONE place so the prompt, the schema and the repair message
# can never drift apart.
TRIAGE_JSON_SHAPE = """{
  "severity": "info|low|medium|high|critical",
  "confidence": 0.0,
  "summary": "one-paragraph analyst-friendly summary",
  "reasoning": "why this severity, citing evidence",
  "evidence_ids": ["<event id from the data block>"],
  "recommended_actions": ["action 1", "action 2"],
  "false_positive_likelihood": 0.0
}"""


class TriageResult(BaseModel):
    """Structured triage output. `source` distinguishes a model result
    from the deterministic fallback (`build_fallback_result`)."""

    severity: EventSeverity
    # 0.0 .. 1.0 -- how sure the agent is in its own words.
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(min_length=1, max_length=2000)
    reasoning: str = Field(default="", max_length=4000)
    # Event ids the model CITES as evidence. Must reference ids from the
    # data block (grounding check happens in service.py, which knows the
    # shown set); unknown ids fail validation, not silently pass.
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    # What the analyst should do next. STRINGS ONLY -- the model never
    # requests tool executions in this milestone (AI SOC Analyst doc
    # §12: high-risk actions require human approval and go through the
    # permission layer, never through free-text output).
    recommended_actions: list[str] = Field(default_factory=list, max_length=10)
    # 0.0 .. 1.0 chance this is a false positive.
    false_positive_likelihood: float = Field(ge=0.0, le=1.0)
    # "ai" (model produced it) or "rules" (deterministic fallback).
    source: str = "ai"

    @field_validator("summary", "reasoning")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("recommended_actions")
    @classmethod
    def _clean_actions(cls, v: list[str]) -> list[str]:
        cleaned = [a.strip()[:300] for a in v if a and a.strip()]
        return cleaned[:10]

    def grounding_failures(self, shown_event_ids: set[str]) -> list[str]:
        """Cited evidence ids that were NOT in the data the model saw."""
        return [e for e in self.evidence_ids if e not in shown_event_ids]

    def to_analysis_fields(self) -> dict[str, Any]:
        """Flat dict for the ai_analyses row."""
        return {
            "severity_suggestion": self.severity,
            "confidence": self.confidence,
            "summary": self.summary,
            "reasoning": self.reasoning or None,
            "recommended_actions": {"actions": self.recommended_actions},
            "evidence_ids": self.evidence_ids,
            "false_positive_likelihood": self.false_positive_likelihood,
            "source": self.source,
        }


def parse_triage_output(raw: str) -> TriageResult:
    """Parse the model's raw text into TriageResult.

    Raises TriageValidationError with a message that quotes the specific
    failure -- that message is what the repair attempt shows the model,
    so precision here directly improves the retry's odds.
    """
    if not raw or not raw.strip():
        raise TriageValidationError("output was empty")

    text = raw.strip()
    # Tolerate a model wrapping its JSON in a code fence despite
    # instructions not to.
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1 and text.rstrip().endswith("```"):
            text = text[first_newline + 1 : text.rstrip().rfind("```")]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TriageValidationError(f"output is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise TriageValidationError(f"output is not a JSON object (got {type(data).__name__})")

    # Coerce the severity case-insensitively so "CRITICAL" is not a
    # validation failure -- but an unknown word is.
    severity_raw = data.get("severity")
    if isinstance(severity_raw, str):
        lowered = severity_raw.strip().lower()
        allowed = {s.value for s in EventSeverity}
        if lowered not in allowed:
            raise TriageValidationError(
                f"severity {severity_raw!r} not in {sorted(allowed)}"
            )
        data["severity"] = lowered

    for key in ("evidence_ids",):
        value = data.get(key)
        if isinstance(value, list):
            cleaned: list[str] = []
            for item in value:
                s = str(item).strip()
                if not s:
                    continue
                # Accept bare ids with or without a "urn:uuid:" prefix.
                if s.startswith("urn:uuid:"):
                    s = s[len("urn:uuid:") :]
                try:
                    cleaned.append(str(uuid.UUID(s)))
                except ValueError:
                    # Keep the raw string -- grounding validation reports
                    # it as an unknown id rather than crashing.
                    cleaned.append(s)
            data[key] = cleaned

    try:
        result = TriageResult(**data)
    except Exception as exc:  # pydantic.ValidationError and friends
        raise TriageValidationError(str(exc)) from exc
    return result
