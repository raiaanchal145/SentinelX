"""
The P19 policy engine -- the one door every tool call goes through,
AI or human, API or worker.

`authorize_tool_call()` is the pure decision: given who is calling,
which tool, what arguments and a resolved ToolContext, it returns
allow | needs_approval | deny (+ reason). It reads nothing but the
registry, the organization, the org's settings and the caller's
effective access -- it never touches an executor and never writes a
row.

`run_tool_call()` is the operational wrapper around it, and the ONLY
code path in this codebase that invokes a tool executor:
1. resolve org context (explicit organization > incident > actor scope)
2. validate arguments against the tool's registered Args model
   (before logging, so the log row's arguments are already canonical)
3. authorize
4. write the tool_call_logs row (every attempt: allowed, blocked or
   pending) -- this is the evidence layer, `arguments_hash` is the
   sha-256 of the canonical validated arguments
5. act: allow -> execute + result; needs_approval -> approvals row +
   notification; deny -> nothing beyond the log + audit.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import get_effective_access, soc_visible_organization_ids
from app.models import (
    ActorType,
    Approval,
    ApprovalRiskLevel,
    ApprovalStatus,
    Organization,
    OrganizationSettings,
    OrganizationModule,
)
from app.modules import ModuleKey
from app.scope import Scope

from .tools import (
    Decision,
    ToolActor,
    ToolContext,
    ToolError,
    canonical_arguments,
    get_tool,
)

logger = logging.getLogger("sentinelx.policy")

VERDICT_ALLOW = "allow"
VERDICT_NEEDS_APPROVAL = "needs_approval"
VERDICT_DENY = "deny"

# Requested risk -> the access level the caller needs on the module.
_RISK_MIN_ACCESS = {
    ApprovalRiskLevel.read_only: "read",
    ApprovalRiskLevel.low: "write",
    ApprovalRiskLevel.high: "write",
}


def actor_from_scope(scope: Scope) -> ToolActor:
    """A human caller into a ToolActor. The kind matched against
    allowed_executors is the caller's role value; super_admin's kind
    is never in any tool's allowed list, so it fails closed."""
    from app.models import ActorType as _AT

    return ToolActor(
        actor_type=_AT.admin if scope.account_type == "admin" else _AT.user,
        actor_id=scope.user_id if scope.user_id else None,
        kind=scope.role,
        role=scope.role,
        scope=scope,
        organization_id=scope.organization_id,
    )


async def _module_access_level(
    db: AsyncSession, actor: ToolActor, organization: Organization, module_key: str
) -> str | None:
    """The caller's effective access level on `module_key` for THIS
    organization, or None. Organization people resolve through
    get_effective_access() (role defaults, role overrides, person
    overrides, soc-mode gating, the owner's oversight rule) -- the same
    source every router uses, so the policy layer cannot drift from the
    API's permission matrix. Platform SOC analysts have no organization
    of their own: they get "write" when the module is enabled at the org
    and their assignment covers it (decided: they may trigger actions,
    but can never approve them)."""
    if actor.actor_type == ActorType.admin:
        if actor.role == "organization_admin":
            access = await get_effective_access(db, actor.scope.account, organization)
            return access["modules"].get(module_key)
        # super_admin / platform_soc_analyst: assignment-based.
        if actor.role == "platform_soc_analyst":
            if actor.scope is None:
                return None
            visible = await soc_visible_organization_ids(db, actor.scope)
            if organization.id not in visible:
                return None
            module_row = (
                await db.execute(
                    select(OrganizationModule).where(
                        OrganizationModule.organization_id == organization.id,
                        OrganizationModule.module_key == module_key,
                    )
                )
            ).scalar_one_or_none()
            return "write" if module_row is not None and module_row.enabled else None
        return None  # super_admin: no tool executors, fail closed.

    if actor.actor_type == ActorType.ai_agent:
        # An AI agent acts under the organization's AI feature: the
        # caller (ai service) only runs while ai_enabled + the ai_agents
        # module are on, and the engine already required the TOOL'S
        # module to be enabled on the org. The AI's further constraint
        # is not module-based but risk-based: high tools always go to
        # needs_approval regardless of anything set here.
        return "write"

    # A user of the organization.
    access = await get_effective_access(db, actor.scope.account, organization)
    return access["modules"].get(module_key)


async def authorize_tool_call(
    actor: ToolActor,
    tool_name: str,
    args: dict,
    context: ToolContext,
) -> Decision:
    """THE policy function. allow | needs_approval | deny with a
    reason. Pure reads only: nothing here writes."""
    tool = get_tool(tool_name)
    if tool is None:
        return Decision(VERDICT_DENY, "tool_unknown")

    if actor.kind not in tool.allowed_executors:
        return Decision(VERDICT_DENY, "executor_not_allowed")

    organization = context.organization
    if organization is None:
        return Decision(VERDICT_DENY, "organization_unknown")
    status = organization.status.value if hasattr(organization.status, "value") else organization.status
    if status != "active":
        return Decision(VERDICT_DENY, "organization_not_active")

    # Run context integrity: an incident-scoped call must be about an
    # incident that actually belongs to the org.
    if context.incident is not None and context.incident.organization_id != organization.id:
        return Decision(VERDICT_DENY, "incident_mismatch")

    module_row = (
        await context.db.execute(
            select(OrganizationModule).where(
                OrganizationModule.organization_id == organization.id,
                OrganizationModule.module_key == tool.required_module,
            )
        )
    ).scalar_one_or_none()
    if module_row is None or not module_row.enabled:
        return Decision(VERDICT_DENY, "module_disabled")

    level = await _module_access_level(context.db, actor, organization, tool.required_module)
    needed = _RISK_MIN_ACCESS[tool.risk_level]
    if level is None or (needed == "write" and level != "write") or (needed == "read" and level not in ("read", "write")):
        return Decision(VERDICT_DENY, "module_access_denied")

    if tool.risk_level == ApprovalRiskLevel.read_only:
        return Decision(VERDICT_ALLOW)

    if tool.risk_level == ApprovalRiskLevel.low:
        settings = context.settings
        if settings is not None and settings.low_risk_automation_enabled:
            return Decision(VERDICT_ALLOW)
        return Decision(VERDICT_NEEDS_APPROVAL, "low_risk_automation_disabled")

    # high: unconditionally to a human. No setting, no role, no
    # context ever passes this -- approvals only ever PERSON grant it.
    return Decision(VERDICT_NEEDS_APPROVAL, "high_risk_requires_approval")


APPROVAL_TTL_SECONDS = 24 * 3600


async def run_tool_call(
    db: AsyncSession,
    *,
    actor: ToolActor,
    tool_name: str,
    args: dict,
    organization: Organization | None = None,
    incident_id: uuid.UUID | None = None,
    agent_run_id: uuid.UUID | None = None,
    requested_reason: str | None = None,
    commit: bool = True,
) -> dict:
    """The only way anything reaches an executor. Returns a dict the
    API/worker layers can turn into a response. All-or-nothing per
    call: the log, decision, approval and audit rows commit together."""
    from app.audit import write_audit_log

    # ---- 1. resolve context ----
    incident = None
    if incident_id is not None:
        from app.models import Incident

        incident = (await db.execute(select(Incident).where(Incident.id == incident_id))).scalar_one_or_none()
        if incident is not None and actor.organization_id is None:
            actor = ToolActor(
                actor_type=actor.actor_type, actor_id=actor.actor_id, kind=actor.kind,
                role=actor.role, scope=actor.scope, organization_id=incident.organization_id,
            )
        organization = organization or (
            await db.get(Organization, incident.organization_id) if incident is not None else None
        )
    organization = organization or (
        await db.get(Organization, actor.organization_id)
        if actor.organization_id is not None
        else None
    )
    if organization is None:
        return {"decision": VERDICT_DENY, "reason": "organization_unknown", "tool": tool_name}

    settings = (
        await db.execute(
            select(OrganizationSettings).where(OrganizationSettings.organization_id == organization.id)
        )
    ).scalar_one_or_none()

    context = ToolContext(
        db=db, actor=actor, organization=organization, settings=settings, incident=incident
    )

    # ---- 2. validate arguments (the logged set is the canonical one) ----
    tool = get_tool(tool_name)
    validated: Any = None
    if tool is not None:
        try:
            validated = tool.args_model(**args)
        except Exception as exc:  # pydantic ValidationError etc.
            return await _log_and_hit(
                db, actor, tool_name, tool.risk_level, args=args, validated=None,
                org=organization, incident=incident, agent_run_id=agent_run_id,
                verdict=VERDICT_DENY, reason="invalid_arguments",
                result={"error": str(exc)[:200]}, commit=commit,
            )
    else:
        validated = None

    # ---- 3. authorize ----
    decision = await authorize_tool_call(actor, tool_name, args, context)

    if decision.verdict == VERDICT_DENY:
        return await _log_and_hit(
            db, actor, tool_name,
            tool.risk_level if tool else ApprovalRiskLevel.read_only,
            args=args, validated=validated, org=organization, incident=incident,
            agent_run_id=agent_run_id, verdict=VERDICT_DENY,
            reason=decision.reason, commit=commit,
        )

    if decision.verdict == VERDICT_NEEDS_APPROVAL:
        # ---- approval row: the request enters the queue ----
        approval = Approval(
            organization_id=organization.id,
            requested_by_type=actor.actor_type,
            requested_by_id=actor.actor_id,
            action_type=f"tool:{tool_name}",
            action_payload={"tool": tool_name, "arguments": validated.model_dump(mode="json") if validated is not None else args},
            risk_level=tool.risk_level,
            status=ApprovalStatus.pending,
            requested_reason=requested_reason or decision.reason,
            expires_at=_expires_from_now(),
            incident_id=incident.id if incident is not None else None,
        )
        db.add(approval)
        await db.flush()

        result = await _log_and_hit(
            db, actor, tool_name, tool.risk_level, args=args, validated=validated,
            org=organization, incident=incident, agent_run_id=agent_run_id,
            verdict=VERDICT_NEEDS_APPROVAL, reason=decision.reason,
            approval_id=approval.id, commit=False,
        )

        await write_audit_log(
            db,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            action="approval.requested",
            organization_id=organization.id,
            target_type="approval",
            target_id=approval.id,
            after={
                "action_type": approval.action_type,
                "risk_level": tool.risk_level.value,
                "incident_id": str(incident.id) if incident is not None else None,
            },
        )
        await _notify_request(db, approval, organization, incident)
        if commit:
            await db.commit()
        result["approval_id"] = str(approval.id)
        return result

    # ---- 4. ALLOWED: execute ----
    try:
        execution = await tool.executor(context, validated)
        error_code = None
    except ToolError as exc:
        logger.info("policy: tool %s execution refused: %s", tool_name, exc.code)
        execution, error_code = None, exc.code

    args_dict = validated.model_dump(mode="json") if validated is not None else args
    result = {
        **(execution or {}),
        **({"error": error_code} if error_code else {}),
    }
    if error_code:
        # An execution failure (asset gone mid-flight etc.) is recorded,
        # audited, and reported -- but it is not a permission event: the
        # caller was ALLOWED. decision stays "allow".
        await _log_and_hit(
            db, actor, tool_name, tool.risk_level, args=args, validated=validated,
            org=organization, incident=incident, agent_run_id=agent_run_id,
            verdict=VERDICT_ALLOW, reason=None, outcome="error", result=result,
            commit=commit,
        )
        return {"decision": VERDICT_ALLOW, "executed": False, "error": error_code, "detail": result}

    await _log_and_hit(
        db, actor, tool_name, tool.risk_level, args=args, validated=validated,
        org=organization, incident=incident, agent_run_id=agent_run_id,
        verdict=VERDICT_ALLOW, reason=None, outcome="executed", result=result,
        commit=commit,
    )
    if incident is not None:
        await _timeline_entry(db, incident, f"Executed {tool_name} (risk: {tool.risk_level.value}) as part of the response actions.")
    if commit:
        await db.commit()
    return {"decision": VERDICT_ALLOW, "executed": True, "result": result}


def _expires_from_now():
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=APPROVAL_TTL_SECONDS)


async def _log_and_hit(
    db, actor, tool_name, risk_level, *, args, validated, org, incident, agent_run_id,
    verdict, reason, approval_id=None, outcome=None, result=None, commit=True,
) -> dict:
    from app.audit import write_audit_log

    from .tools import ToolSpec  # noqa: F401

    validated_dict = (
        validated.model_dump(mode="json")
        if validated is not None and hasattr(validated, "model_dump")
        else (args if isinstance(args, dict) else None)
    )
    hash_input = validated_dict if validated_dict is not None else {}
    arguments_hash = hashlib.sha256(
        canonical_arguments(hash_input).encode("utf-8")
    ).hexdigest()

    from app.models import ToolCallLog

    db.add(
        ToolCallLog(
            organization_id=org.id,
            agent_run_id=agent_run_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            tool_name=tool_name,
            arguments=validated_dict,
            arguments_hash=arguments_hash,
            risk_level=risk_level,
            decision=verdict,
            deny_reason=reason,
            allowed=verdict == VERDICT_ALLOW and outcome != "error",
            approval_id=approval_id,
            incident_id=incident.id if incident is not None else None,
            result=result,
        )
    )
    if verdict == VERDICT_DENY:
        await write_audit_log(
            db,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            action="tool.denied",
            organization_id=org.id,
            target_type="incident" if incident is not None else "tool_call",
            target_id=incident.id if incident is not None else None,
            after={"tool": tool_name, "reason": reason},
        )
    if commit:
        await db.commit()
    return {"decision": verdict, "reason": reason}


async def _timeline_entry(db, incident, description: str) -> None:
    from app.models import IncidentTimeline

    db.add(
        IncidentTimeline(
            incident_id=incident.id,
            entry_type="action",
            description=description,
            actor_type=ActorType.system,
            actor_id=None,
            entry_metadata={"via": "policy_engine"},
        )
    )


async def _notify_request(db, approval, organization, incident) -> None:
    from app.notifications import notify

    tool_name = approval.action_payload.get("tool") if approval.action_payload else approval.action_type
    await notify(
        db,
        "approval.requested",
        organization_id=organization.id,
        payload={
            "action_type": tool_name or approval.action_type,
            "risk_level": approval.risk_level.value if hasattr(approval.risk_level, "value") else approval.risk_level,
            "organization_name": organization.name,
            "incident_id": str(incident.id) if incident is not None else None,
            "related_type": "approval",
            "related_id": approval.id,
        },
    )


async def execute_approved_action(
    db: AsyncSession,
    approval_id: uuid.UUID,
    *,
    origin: str = "",
) -> dict:
    """Execute an APPROVED action exactly once, re-checking the
    approval under a row lock (two workers racing on the same approval
    cannot run it twice: the lock serialises them and the second sees
    executed_at set). Called from the worker job; the approve endpoint
    falls back to calling this inline when Redis is unreachable.

    Every check failure REFUSES to execute and, where the approval has
    gone stale, marks it expired -- rejection/expiration can never
    execute.
    """
    import datetime as dt

    from app.audit import write_audit_log
    from app.models import Incident, IncidentTimeline

    stmt = select(Approval).where(Approval.id == approval_id).with_for_update()
    approval = (await db.execute(stmt)).scalar_one_or_none()
    if approval is None:
        return {"status": "unknown_approval"}

    now = dt.datetime.now(dt.timezone.utc)

    if approval.executed_at is not None:
        return {"status": "already_executed", "executed_at": approval.executed_at.isoformat()}
    if approval.status == ApprovalStatus.approved and approval.expires_at is not None and approval.expires_at <= now:
        approval.status = ApprovalStatus.expired
        await write_audit_log(
            db,
            actor_type=ActorType.system,
            actor_id=None,
            action="approval.expired",
            organization_id=approval.organization_id,
            target_type="approval",
            target_id=approval.id,
            before={"status": "approved"},
            after={"status": "expired"},
        )
        await db.commit()
        return {"status": "refused", "reason": "approval_expired"}
    if approval.status == ApprovalStatus.pending:
        return {"status": "refused", "reason": "still_pending"}
    if approval.status != ApprovalStatus.approved:
        return {"status": "refused", "reason": f"approval_{approval.status.value}"}

    # Registry resolution: action_type is "tool:<name>" for everything
    # this layer creates.
    if not approval.action_type.startswith("tool:"):
        return {"status": "refused", "reason": "not_a_tool_approval"}
    tool_name = approval.action_type.split(":", 1)[1]
    tool = get_tool(tool_name)
    if tool is None:
        return {"status": "refused", "reason": "tool_unknown"}

    organization = await db.get(Organization, approval.organization_id)
    if organization is None:
        return {"status": "refused", "reason": "organization_gone"}

    incident = None
    if approval.incident_id is not None:
        incident = await db.get(Incident, approval.incident_id)

    settings = (
        await db.execute(
            select(OrganizationSettings).where(OrganizationSettings.organization_id == organization.id)
        )
    ).scalar_one_or_none()

    payload = approval.action_payload or {}
    args_dict = payload.get("arguments") or {}

    # Stamp FIRST under the lock: the exactly-once guarantee. The
    # executor's outcome (including a ToolError) is recorded in the
    # tool_call_logs row; a failed device call still consumed the
    # approval and a retry would need a NEW approval.
    approval.executed_at = now

    context = ToolContext(
        db=db,
        actor=ToolActor(
            actor_type=approval.requested_by_type,
            actor_id=approval.requested_by_id,
            kind="approval_executor",
            organization_id=approval.organization_id,
        ),
        organization=organization,
        settings=settings,
        incident=incident,
    )
    validated = None
    try:
        validated = tool.args_model(**args_dict)
        execution = await tool.executor(context, validated)
        error_code = None
    except ToolError as exc:
        execution, error_code = None, exc.code
    except Exception as exc:  # noqa: BLE001 -- a device failure must not wedge the worker
        logger.exception("policy: approval %s executor crashed", approval.id)
        execution, error_code = None, "executor_error"

    args_valid = validated.model_dump(mode="json") if validated is not None else args_dict
    result = {
        **(execution or {}),
        **({"error": error_code} if error_code else {}),
        "origin": origin or "approval",
    }

    from app.models import ToolCallLog

    db.add(
        ToolCallLog(
            organization_id=approval.organization_id,
            actor_type=approval.requested_by_type,
            actor_id=approval.requested_by_id,
            tool_name=tool_name,
            arguments=args_valid,
            arguments_hash=hashlib.sha256(canonical_arguments(args_valid).encode("utf-8")).hexdigest(),
            risk_level=approval.risk_level,
            decision=VERDICT_ALLOW,
            deny_reason=None,
            allowed=error_code is None,
            approval_id=approval.id,
            incident_id=approval.incident_id,
            result=result,
        )
    )
    await write_audit_log(
        db,
        actor_type=ActorType.system,
        actor_id=None,
        action="approval.executed",
        organization_id=approval.organization_id,
        target_type="approval",
        target_id=approval.id,
        before={"status": "approved"},
        after={"executed": error_code is None, "tool": tool_name},
    )
    if incident is not None:
        db.add(
            IncidentTimeline(
                incident_id=incident.id,
                entry_type="action",
                description=(
                    f"Executed {tool_name} (risk: {approval.risk_level.value})"
                    + (" -- failed." if error_code else "")
                    + " Requested earlier; executed on approval."
                ),
                actor_type=ActorType.system,
                actor_id=None,
                entry_metadata={"via": "approval", "approval_id": str(approval.id), "tool": tool_name},
            )
        )
    await db.commit()
    return {
        "status": "executed" if error_code is None else "failed",
        "approval_id": str(approval.id),
        "tool": tool_name,
        "result": result,
    }
