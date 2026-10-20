"""Read-only tools (P19). Risk tier `read_only`: asking questions about
existing data -- never writing anything. The policy engine allows them
straight through (calmer path than the P19 test suite's expectations:
see test_tool_governance.py) once the actor is allowed + the module is
readable.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.models import Alert, ApprovalRiskLevel, Asset, SecurityEvent
from app.modules import ModuleKey

from .base import ToolContext, ToolError, ToolSpec, register


class EventsSearchArgs(BaseModel):
    """Same shape the events API already exposes; org scope comes from
    the context, never the arguments."""

    event_type: str | None = None
    username: str | None = None
    source_ip: str | None = None
    asset_id: uuid.UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)


class AssetGetArgs(BaseModel):
    asset_id: uuid.UUID


class AlertHistoryArgs(BaseModel):
    alert_id: uuid.UUID


_EVENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "event_type": {"type": "string"},
        "username": {"type": "string"},
        "source_ip": {"type": "string"},
        "asset_id": {"type": "string", "format": "uuid"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    },
}


async def _events_search(ctx: ToolContext, args: EventsSearchArgs) -> dict:
    from sqlalchemy import select

    org_id = ctx.organization.id
    stmt = select(SecurityEvent).where(SecurityEvent.organization_id == org_id)
    if args.event_type:
        stmt = stmt.where(SecurityEvent.event_type == args.event_type)
    if args.username:
        stmt = stmt.where(SecurityEvent.username == args.username)
    if args.source_ip:
        stmt = stmt.where(SecurityEvent.source_ip == args.source_ip)
    if args.asset_id:
        stmt = stmt.where(SecurityEvent.asset_id == args.asset_id)
    events = (
        (await ctx.db.execute(stmt.order_by(SecurityEvent.occurred_at.desc()).limit(args.limit)))
        .scalars()
        .all()
    )
    return {
        "count": len(events),
        "events": [
            {
                "id": str(e.id),
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                "event_type": e.event_type,
                "username": e.username,
                "source_ip": e.source_ip,
                "asset_id": str(e.asset_id) if e.asset_id else None,
                "message": (e.normalized_data or {}).get("message") or (e.raw_data or {}).get("message"),
            }
            for e in events
        ],
    }


async def _asset_get(ctx: ToolContext, args: AssetGetArgs) -> dict:
    asset: Asset | None = await ctx.db.get(Asset, args.asset_id)
    if asset is None or asset.organization_id != ctx.organization.id:
        raise ToolError("asset_not_found", f"No asset {args.asset_id} in this organization.")
    return {
        "asset": {
            "id": str(asset.id),
            "name": asset.name,
            "hostname": asset.hostname,
            "asset_type": asset.asset_type if hasattr(asset.asset_type, "value") else asset.asset_type,
            "criticality": asset.criticality if hasattr(asset.criticality, "value") else asset.criticality,
            "environment": asset.environment,
            "status": asset.status if hasattr(asset.status, "value") else asset.status,
        }
    }


async def _alert_history(ctx: ToolContext, args: AlertHistoryArgs) -> dict:
    from sqlalchemy import select

    from app.models import AlertHistory

    alert: Alert | None = await ctx.db.get(Alert, args.alert_id)
    if alert is None or alert.organization_id != ctx.organization.id:
        raise ToolError("alert_not_found", f"No alert {args.alert_id} in this organization.")
    rows = (
        (
            await ctx.db.execute(
                select(AlertHistory)
                .where(AlertHistory.alert_id == alert.id)
                .order_by(AlertHistory.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "alert": {"id": str(alert.id), "title": alert.title, "status": alert.status.value if hasattr(alert.status, "value") else alert.status},
        "history": [
            {
                "id": str(h.id),
                "status_from": h.status_from if hasattr(h, "status_from") else None,
                "status_to": (h.status_to if hasattr(h, "status_to") else None)
                or (h.status.value if getattr(h, "status", None) is not None and hasattr(h.status, "value") else (h.status if hasattr(h, "status") else None)),
                "detail": h.detail if hasattr(h, "detail") else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in rows
        ],
    }


register(
    ToolSpec(
        name="events.search",
        description='Search the organization\'s ingested security events (event text, user, source IP, asset). Read-only.',
        risk_level=ApprovalRiskLevel.read_only,
        required_module=ModuleKey.soc.value,
        input_schema=_EVENTS_SCHEMA,
        allowed_executors=("ai_agent", "organization_admin", "security_manager", "soc_analyst", "platform_soc_analyst"),
        args_model=EventsSearchArgs,
        executor=_events_search,
    )
)

register(
    ToolSpec(
        name="asset.get",
        description="Read one asset's inventory record (name, host, criticality, environment). Read-only.",
        risk_level=ApprovalRiskLevel.read_only,
        required_module=ModuleKey.assets.value,
        input_schema={
            "type": "object",
            "required": ["asset_id"],
            "properties": {"asset_id": {"type": "string", "format": "uuid"}},
        },
        allowed_executors=("ai_agent", "organization_admin", "security_manager", "soc_analyst", "it_developer", "auditor", "platform_soc_analyst"),
        args_model=AssetGetArgs,
        executor=_asset_get,
    )
)

register(
    ToolSpec(
        name="alert.history",
        description="Read one alert and its full status history. Read-only.",
        risk_level=ApprovalRiskLevel.read_only,
        required_module=ModuleKey.soc.value,
        input_schema={
            "type": "object",
            "required": ["alert_id"],
            "properties": {"alert_id": {"type": "string", "format": "uuid"}},
        },
        allowed_executors=("ai_agent", "organization_admin", "security_manager", "soc_analyst", "platform_soc_analyst"),
        args_model=AlertHistoryArgs,
        executor=_alert_history,
    )
)
