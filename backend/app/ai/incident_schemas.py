"""Pydantic models for the incident agent's output (AI triage milestone,
part 2 -- incident drafting).

The model's raw text is NEVER trusted: `parse_incident_output()`
coerces it into `IncidentDraft` or raises `TriageValidationError`
(same family as the triage parser -- one repair attempt shows that
message back). Everything the model produces here is a DRAFT for a
human analyst to review: nothing in this file creates rows.

Shaped per AI SOC Analyst doc §16/§13: an incident agent that drafts
title/summary/timeline/ticket proposals -- never creates (§12: writes
go through the permission layer and the ticket service, audit-marked).
Citations follow the same grounding rule as triage: a timeline entry's
`evidence_ids` must refer to ids the model was actually shown;
service.py, which knows the shown set, does the validation.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models import EventSeverity, IncidentStatus, TicketStatus as TicketStatusEnum


class IncidentDraftValidationError(ValueError):
    """The model's output could not be parsed into a valid IncidentDraft."""


# The JSON shape the prompt asks the model for (and the fake provider
# emits). Sources of truth: this constant, the system prompt
# (INCIDENT_JSON_SHAPE is interpolated there) and the repair message.
INCIDENT_JSON_SHAPE = """{
  "title": "short incident title, <= 250 chars",
  "summary": "one-paragraph, analyst-friendly incident summary",
  "timeline_entries": [
    {"description": "what happened", "evidence_ids": ["<event id from the data block>"]}
  ],
  "ticket_draft": {
    "description": "what should be remediated and why",
    "remediation_steps": ["step 1", "step 2"],
    "suggested_priority": "P1|P2|P3|P4",
    "suggested_team": "team name or null if unknowable from the data"
  },
  "severity": "info|low|medium|high|critical",
  "status_suggestion": "triaged|investigating",
  "confidence": 0.0,
  "false_positive_likelihood": 0.0,
  "reasoning": "why these drafts, citing specific events"
}"""


class TimelineEntry(BaseModel):
    """One proposed timeline entry. `evidence_ids` must cite ids the
    model was shown (validated against the grounding set in the
    service)."""

    description: str = Field(min_length=1, max_length=2000)
    # Event ids this entry is based on. Empty list is allowed (some
    # entries, like the creation note, cite nothing) -- non-empty ids
    # must all be in the grounding set.
    evidence_ids: list[str] = Field(default_factory=list, max_length=25)

    @field_validator("description")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class TicketDraft(BaseModel):
    """A ticket proposal -- the analyst reviews and edits every field
    before anything is created through the ticket service."""

    description: str = Field(min_length=1, max_length=4000)

    @field_validator("description")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    remediation_steps: list[str] = Field(default_factory=list, max_length=15)
    # P1..P4 (the ticket module's own vocabulary, no severity enum here).
    suggested_priority: str = Field(default="P3", pattern=r"^P[1-4]$")
    # Free text; mapping to a real team is the analyst's (or the
    # assignment rules') job at create time, never automatic.
    suggested_team: str | None = Field(default=None, max_length=120)


class IncidentDraft(BaseModel):
    """Structured incident-agent output. Draft-only: no ids of rows this
    milestone creates (the caller routes any accepted ticket draft
    through the ticket service, audited)."""

    title: str = Field(min_length=1, max_length=250)
    summary: str = Field(min_length=1, max_length=4000)
    timeline_entries: list[TimelineEntry] = Field(default_factory=list, max_length=20)
    ticket_draft: TicketDraft
    severity: EventSeverity
    # Where the incident should move next (what the analyst reviews).
    # Only TRIAGED (never deep states -- it hasn't been triaged yet),
    # or INVESTIGATING when the model judges the incident ready.
    status_suggestion: IncidentStatus = IncidentStatus.triaged
    confidence: float = Field(ge=0.0, le=1.0)
    false_positive_likelihood: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(default="", max_length=4000)
    # "ai" or "rules" -- same marking convention as TriageResult.source
    source: str = "ai"

    @field_validator("title", "summary", "reasoning")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("status_suggestion", mode="before")
    @classmethod
    def _coerce_status(cls, v: Any) -> Any:
        # The model names the lifecycle state; only triaged/investigating
        # are legal. Anything else (or an unknown word) is a validation
        # failure -- the repair attempt gets the precise reason.
        if isinstance(v, str):
            lowered = v.strip().lower()
            if lowered in ("triaged", "investigating"):
                # IncidentStatus's .value is UPPERCASE ('INVESTIGATING')
                # while the member NAME is lowercase -- resolve via the
                # name with a fallback to the value.
                try:
                    return IncidentStatus[lowered]
                except KeyError:
                    return IncidentStatus(lowered.upper())
            # Fold the brief's other lifecycle names onto triaged only
            # if the model clearly meant "next step, evidence seen".
            if lowered in ("new", "open", "draft"):
                return IncidentStatus.triaged
            raise ValueError(
                f"status_suggestion {v!r} not in (triaged, investigating)"
            )
        return v

    def grounding_failures(self, shown_event_ids: set[str]) -> list[str]:
        """Timeline-entry evidence ids that were NOT in the data the
        model saw (the same grounding contract as TriageResult)."""
        failures: list[str] = []
        for entry in self.timeline_entries:
            for eid in entry.evidence_ids:
                if eid not in shown_event_ids:
                    failures.append(eid)
        return list(dict.fromkeys(failures))

    def to_analysis_fields(self) -> dict[str, Any]:
        """Flat dict for the ai_analyses row (target_type="incident")."""
        return {
            "severity_suggestion": self.severity,
            "confidence": self.confidence,
            "summary": self.summary,
            "reasoning": self.reasoning or None,
            # Draft title/timeline/ticket ride inside recommended_actions
            # so they persist in the ai_analyses JSONB blob without
            # needing a migration for this milestone.
            "recommended_actions": {
                "title": self.title,
                "timeline_entries": [
                    {"description": e.description, "evidence_ids": e.evidence_ids}
                    for e in self.timeline_entries
                ],
                "ticket_draft": self.ticket_draft.model_dump(mode="json"),
                "status_suggestion": self.status_suggestion.value
                if hasattr(self.status_suggestion, "value")
                else str(self.status_suggestion),
            },
            "evidence_ids": [eid for e in self.timeline_entries for eid in e.evidence_ids],
            "false_positive_likelihood": self.false_positive_likelihood,
            "source": self.source,
        }


def parse_incident_output(raw: str) -> IncidentDraft:
    """Parse the model's raw text into IncidentDraft.

    Same conventions as parse_triage_output: strip tolerable code
    fences, coerce severity case-insensitively, and raise
    IncidentDraftValidationError with a precise failure message (the
    repair attempt shows that message back to the model).
    """
    if not raw or not raw.strip():
        raise IncidentDraftValidationError("output was empty")

    text = raw.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1 and text.rstrip().endswith("```"):
            text = text[first_newline + 1 : text.rstrip().rfind("```")]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IncidentDraftValidationError(f"output is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise IncidentDraftValidationError(
            f"output is not a JSON object (got {type(data).__name__})"
        )

    # Severity: case-insensitive into the enum vocabulary.
    sev_raw = data.get("severity")
    if isinstance(sev_raw, str):
        lowered = sev_raw.strip().lower()
        allowed = {s.value for s in EventSeverity}
        if lowered not in allowed:
            raise IncidentDraftValidationError(
                f"severity {sev_raw!r} not in {sorted(allowed)}"
            )
        data["severity"] = lowered

    # The ticket draft is REQUIRED (it's the point of the call) but
    # tolerates a null/missing by substituting a bare-minimum stub the
    # analyst is guaranteed to edit.
    if not isinstance(data.get("ticket_draft"), dict):
        data["ticket_draft"] = {"description": "(draft to be reviewed)"}

    try:
        return IncidentDraft(**data)
    except Exception as exc:
        raise IncidentDraftValidationError(str(exc)) from exc
