"""
AI analyses API (AI triage milestone, part 2 -- incident drafting,
analyst feedback and metrics).

POST  /api/v1/ai-analyses/{id}/decision   -- accepted | edited |
                                             rejected (+reason). Stores
                                             the acceptance data the
                                             /ai/metrics endpoint reads.
GET   /api/v1/ai/metrics                  -- acceptance rate, average
                                             confidence, override rate
                                             and spend, scoped EXACTLY
                                             like the alerts router
                                             (soc_visible_organizations).

GET  /api/v1/ai/incidents/{incident_id}/analysis  -- the current
       incident-agent draft (one per incident, latest run wins).

Visibility: the alerts router's matrix is THE matrix -- the same
asset worked by the same analyzer gets the same eyes. A caller who
cannot see an organization's alerts never sees its ai_analyses rows
either, and a guessed id is 404 (never a leak), per the org-scoped
endpoint convention (docs/DECISIONS.md).

Isolation: every decision row is written within the SAME transaction
that validated the caller's scope; a caller can only ever reach rows
whose organization passes `_ai_visibility`, so a cross-org decision
is structurally impossible from the API surface.

Who decides: exactly the callers the alerts router lets WRITE (a
managed org's owner/security_manager stay read-only there too).
Everyone else gets 403 -- acceptance is an analyst act, never a read.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_module, soc_visible_organization_ids
from app.audit import audit_from_scope
from app.database import get_db
from app.models import (
    ActorType,
    Admin,
    AdminLevel,
    AiAnalysis,
    AgentRun,
    Alert,
    Incident,
    Organization,
    SocMode,
    SocOrganizationAssignment,
    User,
    UserRole,
)
from app.scope import Scope

router = APIRouter(prefix="/api/v1", tags=["ai"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


_require_soc_read = require_module("soc", write=False)


def _actor(scope: Scope) -> tuple[ActorType, uuid.UUID]:
    return (ActorType.admin if scope.account_type == "admin" else ActorType.user, scope.user_id)


async def _ai_visibility(db: AsyncSession, scope: Scope) -> tuple[str, list[uuid.UUID] | None]:
    """The alerts router's visibility matrix, verbatim for shape: what
    it says about who sees an organization's alerts is exactly what it
    should say about who sees that organization's AI analyses (same
    analyst, same asset, same queue -- the analysis rides the alert)."""
    visible = await soc_visible_organization_ids(db, scope)
    if visible is None:
        return "all", None

    if scope.account_type == "admin" and scope.role == AdminLevel.organization_admin.value:
        return "orgs", [scope.organization_id]

    if scope.role == UserRole.security_manager.value and scope.organization_id is not None:
        return "orgs", [scope.organization_id]

    if visible:
        return "orgs", list(visible)

    if scope.account_type == "admin" and scope.role == AdminLevel.platform_soc_analyst.value:
        return "empty", None
    if scope.role == UserRole.soc_analyst.value and scope.organization_id is not None:
        return "orgs", [scope.organization_id]
    return "forbidden", None


async def _require_ai_write(db: AsyncSession, scope: Scope, organization_id: uuid.UUID) -> None:
    """Who may record an acceptance decision: exactly the alerts
    router's write set (a managed org's owner/manager stay read-only;
    a guessed id is 404, never a leak)."""
    if scope.role == AdminLevel.super_admin.value:
        return
    if scope.account_type == "admin" and scope.role == AdminLevel.platform_soc_analyst.value:
        assigned = (
            await db.execute(
                select(SocOrganizationAssignment.organization_id).where(
                    SocOrganizationAssignment.admin_id == scope.user_id,
                    SocOrganizationAssignment.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        if assigned is None:
            raise _err("analysis_not_found", "Analysis not found.", 404)  # never leaked
        return
    if scope.account_type == "admin" or scope.role == UserRole.security_manager.value:
        if scope.organization_id != organization_id:
            raise _err("analysis_not_found", "Analysis not found.", 404)
        org = await db.get(Organization, organization_id)
        if org is not None and org.soc_mode == SocMode.in_house:
            return
        raise _err(
            "ai_write_not_allowed",
            "This organization's SOC is managed by the platform; its own accounts cannot record AI decisions.",
            403,
        )
    if scope.role == UserRole.soc_analyst.value and scope.organization_id == organization_id:
        return
    raise _err("ai_write_not_allowed", "You do not have permission to record AI decisions.", 403)


async def _visible_analysis(
    db: AsyncSession, scope: Scope, analysis_id: uuid.UUID
) -> AiAnalysis:
    """Load one analysis or 404 it (never leak existence across orgs)."""
    analysis = (
        await db.execute(select(AiAnalysis).where(AiAnalysis.id == analysis_id))
    ).scalar_one_or_none()
    if analysis is None:
        raise _err("analysis_not_found", "Analysis not found.", 404)

    mode, org_ids = await _ai_visibility(db, scope)
    if mode == "forbidden":
        raise _err("analysis_not_found", "Analysis not found.", 404)
    if mode == "orgs" and analysis.organization_id not in (org_ids or []):
        raise _err("analysis_not_found", "Analysis not found.", 404)
    return analysis


class DecisionPayload(BaseModel):
    decision: str = Field(pattern="^(accepted|edited|rejected)$")
    reason: str | None = Field(default=None, max_length=2000)
    # An "edited" decision carries the analyst's corrections; stored on
    # the analysis row so the acceptance-rate metric can tell how much
    # of the model output survived.
    edits: dict | None = None


@router.post("/ai-analyses/{analysis_id}/decision")
async def decide_analysis(
    analysis_id: uuid.UUID,
    payload: DecisionPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
):
    """Analyst feedback on an AI analysis. Stores: decision, reason,
    edits, who decided and when -- the acceptance data
    GET /ai/metrics aggregates. One decision per analysis (the latest
    write wins; the audit trail keeps the history)."""
    analysis = await _visible_analysis(db, scope, analysis_id)
    await _require_ai_write(db, scope, analysis.organization_id)

    if payload.decision == "rejected" and not (payload.reason or "").strip():
        raise _err("reason_required", "A rejection requires a reason.", 422)
    if payload.decision == "accepted" and payload.reason and payload.reason.strip():
        # An acceptance with prose is really an edit; keep the semantics
        # honest rather than letting accepted rows carry unexplained text.
        payload.decision = "edited"

    reason = (payload.reason or "").strip() or None
    edits = payload.edits if isinstance(payload.edits, dict) else None

    analysis.accepted_by_user_id = scope.user_id
    analysis.accepted_at = dt.datetime.now(dt.timezone.utc)
    # The decision + any edits ride in recommended_actions (JSONB) --
    # existing columns only, no migration for this milestone.
    current = analysis.recommended_actions if isinstance(analysis.recommended_actions, dict) else {}
    analysis.recommended_actions = {
        **current,
        "decision": {
            "decision": payload.decision,
            "reason": reason,
            "edits": edits,
            "decided_by": str(scope.user_id),
            "decided_at": analysis.accepted_at.isoformat(),
        },
    }

    actor_type, actor_id = _actor(scope)
    await audit_from_scope(
        db,
        scope,
        f"ai_analysis.{payload.decision}",
        organization_id=analysis.organization_id,
        target_type="ai_analysis",
        target_id=analysis.id,
        after={"decision": payload.decision, "reason": reason},
    )
    await db.commit()
    await db.refresh(analysis)
    return _shape_analysis(analysis)


@router.get("/ai/alerts/{alert_id}/analysis")
async def get_alert_analysis(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
):
    """The alert's latest AI analysis. 404 on a hidden/unknown alert.
    None when the alert simply has not been triaged yet."""
    from app.models import Alert

    alert = (await db.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
    if alert is None:
        raise _err("alert_not_found", "Alert not found.", 404)
    mode, org_ids = await _ai_visibility(db, scope)
    if mode == "forbidden" or (mode == "orgs" and alert.organization_id not in (org_ids or [])):
        raise _err("alert_not_found", "Alert not found.", 404)

    analysis = (
        await db.execute(
            select(AiAnalysis)
            .where(AiAnalysis.target_type == "alert", AiAnalysis.target_id == alert_id)
            .order_by(AiAnalysis.created_at.desc(), AiAnalysis.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if analysis is None:
        return {"analysis": None}
    return {"analysis": _shape_analysis(analysis)}


@router.post("/ai/alerts/{alert_id}/regenerate")
async def regenerate_alert_analysis(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
):
    """Re-runs triage for one alert under cost caps, scoped to callers with
    alert write permissions."""
    from app.ai.service import run_triage_for_alert

    alert = (await db.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
    if alert is None:
        raise _err("alert_not_found", "Alert not found.", 404)
    mode, org_ids = await _ai_visibility(db, scope)
    if mode == "forbidden" or (mode == "orgs" and alert.organization_id not in (org_ids or [])):
        raise _err("alert_not_found", "Alert not found.", 404)
    await _require_ai_write(db, scope, alert.organization_id)

    run = await run_triage_for_alert(db, alert_id)
    if run is None:
        raise _err("alert_not_found", "Alert not found.", 404)

    analysis = (
        await db.execute(
            select(AiAnalysis)
            .where(AiAnalysis.target_type == "alert", AiAnalysis.target_id == alert_id)
            .order_by(AiAnalysis.created_at.desc(), AiAnalysis.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {"analysis": _shape_analysis(analysis) if analysis else None}


@router.post("/ai/incidents/{incident_id}/regenerate")
async def regenerate_incident_analysis(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
):
    """Re-runs incident drafting under cost caps, scoped to callers with
    incident write permissions."""
    from app.ai.incident_service import run_incident_draft_for_incident

    incident = (await db.execute(select(Incident).where(Incident.id == incident_id))).scalar_one_or_none()
    if incident is None:
        raise _err("incident_not_found", "Incident not found.", 404)
    mode, org_ids = await _ai_visibility(db, scope)
    if mode == "forbidden" or (mode == "orgs" and incident.organization_id not in (org_ids or [])):
        raise _err("incident_not_found", "Incident not found.", 404)
    await _require_ai_write(db, scope, incident.organization_id)

    run = await run_incident_draft_for_incident(db, incident_id)
    if run is None:
        raise _err("incident_not_found", "Incident not found.", 404)

    analysis = (
        await db.execute(
            select(AiAnalysis)
            .join(AgentRun, AgentRun.id == AiAnalysis.agent_run_id)
            .where(AiAnalysis.target_type == "incident", AiAnalysis.target_id == incident_id)
            .order_by(AiAnalysis.created_at.desc(), AiAnalysis.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {"analysis": _shape_analysis(analysis) if analysis else None}


@router.get("/ai/incidents/{incident_id}/analysis")
async def get_incident_analysis(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
):
    """The current incident-agent draft (the latest ai_analyses row of
    target_type='incident' for this incident). 404 when none exists --
    including when the caller cannot see the incident's organization,
    so a guessed id leaks nothing."""
    incident = (
        await db.execute(select(Incident).where(Incident.id == incident_id))
    ).scalar_one_or_none()
    if incident is None:
        raise _err("incident_not_found", "Incident not found.", 404)
    mode, org_ids = await _ai_visibility(db, scope)
    if mode == "forbidden" or (mode == "orgs" and incident.organization_id not in (org_ids or [])):
        raise _err("incident_not_found", "Incident not found.", 404)

    analysis = (
        await db.execute(
            select(AiAnalysis)
            .join(AgentRun, AgentRun.id == AiAnalysis.agent_run_id)
            .where(AiAnalysis.target_type == "incident", AiAnalysis.target_id == incident_id)
            .order_by(AiAnalysis.created_at.desc(), AiAnalysis.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if analysis is None:
        return {"analysis": None}
    return {"analysis": _shape_analysis(analysis)}


@router.get("/ai/metrics")
async def ai_metrics(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_require_soc_read),
    organization_id: uuid.UUID | None = None,
):
    """Acceptance rate, average confidence, override rate and spend --
    scoped exactly like the alerts endpoints (the same analyst, the
    same asset). An optional organization_id works like the alerts
    router's org filter: one the caller cannot see is 404."""
    mode, org_ids = await _ai_visibility(db, scope)
    if mode == "forbidden":
        raise _err("soc_not_visible", "You do not have access to AI metrics.", 403)
    scope_ids: list[uuid.UUID] | None = None  # all orgs
    if mode == "orgs":
        scope_ids = list(org_ids or [])
    if organization_id is not None:
        if mode == "all":
            scope_ids = [organization_id]
        else:
            if organization_id not in scope_ids:
                raise _err("organization_not_found", "Organization not found.", 404)
            scope_ids = [organization_id]

    rows = []
    if scope_ids:
        result = await db.execute(
            select(AiAnalysis).where(AiAnalysis.organization_id.in_(scope_ids))
        )
        rows = result.scalars().all()
    elif mode == "all":
        result = await db.execute(select(AiAnalysis))
        rows = result.scalars().all()

    total = len(rows)
    decided = [r for r in rows if isinstance(r.recommended_actions or {}, dict) and (r.recommended_actions or {}).get("decision")]
    accepted = [r for r in decided if r.recommended_actions["decision"]["decision"] == "accepted"]
    edited = [r for r in decided if r.recommended_actions["decision"]["decision"] == "edited"]
    rejected = [r for r in decided if r.recommended_actions["decision"]["decision"] == "rejected"]
    ai_rows = [r for r in rows if (r.source or "") == "ai"]

    def _conf(row: AiAnalysis) -> float:
        return float(row.confidence) if row.confidence is not None else 0.0

    # Override rate: the fraction of "edited" decisions among all
    # AI-analysis decisions (the analyst kept the verdict but had to
    # correct it). Rejections count against acceptance, not override.
    override_rate = round(len(edited) / len(decided), 3) if decided else 0.0

    spend_rows = []
    if scope_ids:
        run_ids = {r.agent_run_id for r in rows}
        if run_ids:
            spend_rows = (
                await db.execute(
                    select(AgentRun.cost_usd).where(
                        AgentRun.id.in_(run_ids), AgentRun.cost_usd.is_not(None)
                    )
                )
            ).scalars().all()
    total_spend = round(sum(float(c) for c in spend_rows if c is not None), 6)

    return {
        "organization_id": str(organization_id) if organization_id else None,
        "total_analyses": total,
        "ai_analyses": len(ai_rows),
        "rules_analyses": total - len(ai_rows),
        "decisions": {
            "total_decisions": total and len(decided),
            "accepted": len(accepted),
            "edited": len(edited),
            "rejected": len(rejected),
            "acceptance_rate": round((len(accepted) + len(edited)) / len(decided), 3) if decided else 0.0,
            "override_rate": override_rate,
            "average_confidence": round(sum(_conf(r) for r in ai_rows) / len(ai_rows), 3) if ai_rows else 0.0,
        },
        "cost": {
            "total_spend_usd": total_spend,
        },
    }


def _shape_analysis(a: AiAnalysis) -> dict:
    actions = a.recommended_actions if isinstance(a.recommended_actions, dict) else {}
    decision = actions.get("decision") if isinstance(actions, dict) else None
    return {
        "id": str(a.id),
        "organization_id": str(a.organization_id),
        "agent_run_id": str(a.agent_run_id),
        "target_type": a.target_type,
        "target_id": str(a.target_id),
        "source": a.source,
        "summary": a.summary,
        "reasoning": a.reasoning,
        "confidence": a.confidence,
        "severity_suggestion": a.severity_suggestion.value if a.severity_suggestion is not None and hasattr(a.severity_suggestion, "value") else a.severity_suggestion,
        "recommended_actions": actions,
        "evidence_ids": a.evidence_ids or [],
        "false_positive_likelihood": a.false_positive_likelihood,
        "accepted_by_user_id": str(a.accepted_by_user_id) if a.accepted_by_user_id else None,
        "accepted_at": a.accepted_at.isoformat() if a.accepted_at else None,
        "decision": decision,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
