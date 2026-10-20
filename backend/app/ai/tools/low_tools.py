"""Low-risk tools (P19). Risk tier `low`: real writes to SentinelX's
own tables, each bounded to one reversible-at-the-data-level action.
The policy engine allows them only when the organization turned
`low_risk_automation_enabled` on; with the default (off) every one of
these comes back `needs_approval` -- fail closed like ai_enabled.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.models import ApprovalRiskLevel, Asset, AssetTag, Incident
from app.modules import ModuleKey

from .base import ToolContext, ToolError, ToolSpec, register


class IncidentCommentArgs(BaseModel):
    incident_id: uuid.UUID
    body: str = Field(min_length=1, max_length=4000)
    visibility: str = Field(default="shared")


class AssetTagArgs(BaseModel):
    asset_id: uuid.UUID
    tag: str = Field(min_length=1, max_length=80)


class NotifyArgs(BaseModel):
    incident_id: uuid.UUID
    message: str = Field(min_length=1, max_length=2000)
    audience: str = Field(default="soc")  # "soc" or "owner"


_PRIORITY_LADDER = ["P4", "P3", "P2", "P1"]


class AdjustPriorityArgs(BaseModel):
    incident_id: uuid.UUID
    direction: str  # "increase" (more urgent) or "decrease"


def _comment_visibility(value: str) -> str:
    if value not in ("shared", "internal"):
        raise ToolError("invalid_visibility", "visibility must be 'shared' or 'internal'.")
    return value


async def _incident_comment(ctx: ToolContext, args: IncidentCommentArgs) -> dict:
    from app.models import IncidentTimeline

    visibility = _comment_visibility(args.visibility)
    incident: Incident | None = await ctx.db.get(Incident, args.incident_id)
    if incident is None or incident.organization_id != ctx.organization.id:
        raise ToolError("incident_not_found", f"No incident {args.incident_id} in this organization.")
    entry = IncidentTimeline(
        incident_id=incident.id,
        entry_type="comment",
        description=args.body,
        actor_type=ctx.actor.actor_type,
        actor_id=ctx.actor.actor_id,
        entry_metadata={"visibility": visibility},
    )
    ctx.db.add(entry)
    await ctx.db.flush()
    return {"added": True, "timeline_entry_id": str(entry.id), "visibility": visibility}


async def _asset_tag(ctx: ToolContext, args: AssetTagArgs) -> dict:
    from sqlalchemy import select

    asset: Asset | None = await ctx.db.get(Asset, args.asset_id)
    if asset is None or asset.organization_id != ctx.organization.id:
        raise ToolError("asset_not_found", f"No asset {args.asset_id} in this organization.")
    existing = (
        (
            await ctx.db.execute(
                select(AssetTag).where(AssetTag.asset_id == asset.id, AssetTag.tag == args.tag)
            )
        )
        .scalars()
        .first()
    )
    if existing is None:
        ctx.db.add(AssetTag(asset_id=asset.id, tag=args.tag))
        return {"added": True, "asset_id": str(asset.id), "tag": args.tag}
    return {"added": False, "asset_id": str(asset.id), "tag": args.tag}


async def _notify(ctx: ToolContext, args: NotifyArgs) -> dict:
    from app.notifications import notify as send_notification

    incident: Incident | None = await ctx.db.get(Incident, args.incident_id)
    if incident is None or incident.organization_id != ctx.organization.id:
        raise ToolError("incident_not_found", f"No incident {args.incident_id} in this organization.")
    written = await send_notification(
        ctx.db,
        "tool.notify",
        organization_id=ctx.organization.id,
        payload={
            "audience": args.audience,
            "message": args.message,
            "incident_id": str(incident.id),
            "incident_title": incident.title,
            "related_type": "incident",
            "related_id": incident.id,
        },
    )
    return {"notified": written}


async def _adjust_priority(ctx: ToolContext, args: AdjustPriorityArgs) -> dict:
    incident: Incident | None = await ctx.db.get(Incident, args.incident_id)
    if incident is None or incident.organization_id != ctx.organization.id:
        raise ToolError("incident_not_found", f"No incident {args.incident_id} in this organization.")
    if incident.priority not in _PRIORITY_LADDER:
        raise ToolError("priority_not_set", "This incident has no P1..P4 priority to adjust.")
    index = _PRIORITY_LADDER.index(incident.priority)
    if args.direction == "increase":
        new_index = max(index - 1, 0)  # P1 is the top of the ladder
    elif args.direction == "decrease":
        new_index = min(index + 1, len(_PRIORITY_LADDER) - 1)
    else:
        raise ToolError("invalid_direction", "direction must be 'increase' or 'decrease'.")
    old = incident.priority
    incident.priority = _PRIORITY_LADDER[new_index]
    return {"changed": old != incident.priority, "from": old, "to": incident.priority}


register(
    ToolSpec(
        name="incident.add_comment",
        description="Append a comment to an incident's timeline (shared or internal).",
        risk_level=ApprovalRiskLevel.low,
        required_module=ModuleKey.incidents.value,
        input_schema={
            "type": "object",
            "required": ["incident_id", "body"],
            "properties": {
                "incident_id": {"type": "string", "format": "uuid"},
                "body": {"type": "string", "maxLength": 4000},
                "visibility": {"type": "string", "enum": ["shared", "internal"]},
            },
        },
        allowed_executors=("ai_agent", "organization_admin", "security_manager", "soc_analyst", "platform_soc_analyst"),
        args_model=IncidentCommentArgs,
        executor=_incident_comment,
    )
)

register(
    ToolSpec(
        name="asset.add_tag",
        description="Add an inventory tag to an asset.",
        risk_level=ApprovalRiskLevel.low,
        required_module=ModuleKey.assets.value,
        input_schema={
            "type": "object",
            "required": ["asset_id", "tag"],
            "properties": {
                "asset_id": {"type": "string", "format": "uuid"},
                "tag": {"type": "string", "maxLength": 80},
            },
        },
        allowed_executors=("ai_agent", "organization_admin", "security_manager", "it_developer"),
        args_model=AssetTagArgs,
        executor=_asset_tag,
    )
)

register(
    ToolSpec(
        name="user.notify",
        description="Send an in-app (and where enabled, emailed) notification about an incident to the organization's SOC or owner.",
        risk_level=ApprovalRiskLevel.low,
        required_module=ModuleKey.soc.value,
        input_schema={
            "type": "object",
            "required": ["incident_id", "message"],
            "properties": {
                "incident_id": {"type": "string", "format": "uuid"},
                "message": {"type": "string", "maxLength": 2000},
                "audience": {"type": "string", "enum": ["soc", "owner"]},
            },
        },
        allowed_executors=("ai_agent", "organization_admin", "security_manager", "soc_analyst", "platform_soc_analyst"),
        args_model=NotifyArgs,
        executor=_notify,
    )
)

register(
    ToolSpec(
        name="incident.adjust_priority",
        description="Move an incident's priority ONE level (towards P1 or towards P4). Nothing else changes.",
        risk_level=ApprovalRiskLevel.low,
        required_module=ModuleKey.incidents.value,
        input_schema={
            "type": "object",
            "required": ["incident_id", "direction"],
            "properties": {
                "incident_id": {"type": "string", "format": "uuid"},
                "direction": {"type": "string", "enum": ["increase", "decrease"]},
            },
        },
        allowed_executors=("ai_agent", "organization_admin", "security_manager", "soc_analyst", "platform_soc_analyst"),
        args_model=AdjustPriorityArgs,
        executor=_adjust_priority,
    )
)
