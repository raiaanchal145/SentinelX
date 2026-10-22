"""
Command Palette API (P25).
Provides fast scoped search across alerts, incidents, tickets, and assets.
Respects tenant isolation:
- super_admin: searches across all organizations.
- platform_soc_analyst: alerts and incidents in assigned managed orgs.
- organization accounts: strictly scoped to scope.organization_id.
"""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import cast, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import soc_visible_organization_ids
from app.database import get_db
from app.models import (
    AdminLevel,
    Alert,
    Asset,
    Incident,
    Ticket,
)
from app.scope import Scope, org_scope

router = APIRouter(prefix="/api/v1/palette", tags=["palette"])


class PaletteAlertItem(BaseModel):
    id: str
    title: str
    severity: str
    status: str
    organization_id: str
    created_at: str | None = None


class PaletteIncidentItem(BaseModel):
    id: str
    title: str
    severity: str
    status: str
    organization_id: str
    opened_at: str | None = None


class PaletteTicketItem(BaseModel):
    id: str
    ticket_number: str | None = None
    title: str
    priority: str
    status: str
    organization_id: str
    created_at: str | None = None


class PaletteAssetItem(BaseModel):
    id: str
    name: str
    hostname: str | None = None
    ip_address: str | None = None
    asset_type: str
    status: str
    organization_id: str


class PaletteSearchResponse(BaseModel):
    alerts: list[PaletteAlertItem]
    incidents: list[PaletteIncidentItem]
    tickets: list[PaletteTicketItem]
    assets: list[PaletteAssetItem]


@router.get("/search", response_model=PaletteSearchResponse)
async def palette_search(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(5, ge=1, le=20),
    scope: Scope = Depends(org_scope),
    db: AsyncSession = Depends(get_db),
):
    query_str = f"%{q.strip()}%"

    # 1. Organization filtering scope
    is_super = scope.role == AdminLevel.super_admin.value
    is_platform_soc = scope.role == AdminLevel.platform_soc_analyst.value

    # Alerts & Incidents scope
    soc_org_ids: list[uuid.UUID] | None = None
    if not is_super:
        if is_platform_soc:
            soc_org_ids = await soc_visible_organization_ids(db, scope)
            if soc_org_ids is None:
                soc_org_ids = []
        else:
            soc_org_ids = [scope.organization_id] if scope.organization_id else []

    # Tickets & Assets scope
    tenant_org_id = None if is_super else scope.organization_id

    # 2. Search Alerts
    alerts_res: list[PaletteAlertItem] = []
    if is_super or (soc_org_ids is not None and len(soc_org_ids) > 0):
        stmt = select(Alert).where(
            or_(
                Alert.title.ilike(query_str),
                Alert.rule_name.ilike(query_str),
                cast(Alert.id, String).ilike(query_str),
            )
        )
        if not is_super and soc_org_ids is not None:
            stmt = stmt.where(Alert.organization_id.in_(soc_org_ids))
        stmt = stmt.order_by(Alert.created_at.desc()).limit(limit)
        alerts_rows = (await db.execute(stmt)).scalars().all()
        alerts_res = [
            PaletteAlertItem(
                id=str(a.id),
                title=a.title,
                severity=a.severity.value if hasattr(a.severity, "value") else str(a.severity),
                status=a.status.value if hasattr(a.status, "value") else str(a.status),
                organization_id=str(a.organization_id),
                created_at=a.created_at.isoformat() if a.created_at else None,
            )
            for a in alerts_rows
        ]

    # 3. Search Incidents
    incidents_res: list[PaletteIncidentItem] = []
    if is_super or (soc_org_ids is not None and len(soc_org_ids) > 0):
        stmt = select(Incident).where(
            or_(
                Incident.title.ilike(query_str),
                Incident.summary.ilike(query_str),
                cast(Incident.id, String).ilike(query_str),
            )
        )
        if not is_super and soc_org_ids is not None:
            stmt = stmt.where(Incident.organization_id.in_(soc_org_ids))
        stmt = stmt.order_by(Incident.opened_at.desc()).limit(limit)
        incidents_rows = (await db.execute(stmt)).scalars().all()
        incidents_res = [
            PaletteIncidentItem(
                id=str(inc.id),
                title=inc.title,
                severity=inc.severity.value if hasattr(inc.severity, "value") else str(inc.severity),
                status=inc.status.value if hasattr(inc.status, "value") else str(inc.status),
                organization_id=str(inc.organization_id),
                opened_at=inc.opened_at.isoformat() if inc.opened_at else None,
            )
            for inc in incidents_rows
        ]

    # 4. Search Tickets
    tickets_res: list[PaletteTicketItem] = []
    if is_super or tenant_org_id is not None:
        stmt = select(Ticket).where(
            or_(
                Ticket.title.ilike(query_str),
                Ticket.ticket_number.ilike(query_str),
                cast(Ticket.id, String).ilike(query_str),
            )
        )
        if not is_super and tenant_org_id is not None:
            stmt = stmt.where(Ticket.organization_id == tenant_org_id)
        stmt = stmt.order_by(Ticket.created_at.desc()).limit(limit)
        tickets_rows = (await db.execute(stmt)).scalars().all()
        tickets_res = [
            PaletteTicketItem(
                id=str(t.id),
                ticket_number=t.ticket_number,
                title=t.title,
                priority=t.priority.value if hasattr(t.priority, "value") else str(t.priority),
                status=t.status.value if hasattr(t.status, "value") else str(t.status),
                organization_id=str(t.organization_id),
                created_at=t.created_at.isoformat() if t.created_at else None,
            )
            for t in tickets_rows
        ]

    # 5. Search Assets
    assets_res: list[PaletteAssetItem] = []
    if is_super or tenant_org_id is not None:
        stmt = select(Asset).where(
            or_(
                Asset.name.ilike(query_str),
                Asset.hostname.ilike(query_str),
                Asset.ip_address.ilike(query_str),
                cast(Asset.id, String).ilike(query_str),
            )
        )
        if not is_super and tenant_org_id is not None:
            stmt = stmt.where(Asset.organization_id == tenant_org_id)
        stmt = stmt.order_by(Asset.created_at.desc()).limit(limit)
        assets_rows = (await db.execute(stmt)).scalars().all()
        assets_res = [
            PaletteAssetItem(
                id=str(ast.id),
                name=ast.name,
                hostname=ast.hostname,
                ip_address=ast.ip_address,
                asset_type=ast.asset_type.value if hasattr(ast.asset_type, "value") else str(ast.asset_type),
                status=ast.status.value if hasattr(ast.status, "value") else str(ast.status),
                organization_id=str(ast.organization_id),
            )
            for ast in assets_rows
        ]

    return PaletteSearchResponse(
        alerts=alerts_res,
        incidents=incidents_res,
        tickets=tickets_res,
        assets=assets_res,
    )
