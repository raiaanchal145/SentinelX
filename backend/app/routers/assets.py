"""
Organization-scoped asset inventory -- everything later (events, alerts,
incidents, tickets) points at an asset, so this is the first real,
non-mock data endpoint in the pipeline.

Reachable by:
  - organization_admin / security_manager / it_developer: write. Module-
    level write is the floor (require_org_assets_write); it_developer
    is additionally row-scoped to assets they own or that belong to
    their team (see _can_write_asset) -- organization_admin and
    security_manager are not.
  - soc_analyst / auditor: read-only, same organization.
  - platform_soc_analyst: read-only, but not "their own organization" --
    they pass an explicit `organization_id` query param, checked against
    soc_visible_organization_ids() (assigned + soc_mode=managed +
    active). See _target_organization().
  - super_admin: does NOT use this router at all -- they read through
    GET /admin/organizations/{id}/assets in admin_organizations.py,
    matching how every other admin-side view of one organization's data
    already works.
"""

import ipaddress
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_active_organization, require_module, soc_visible_organization_ids
from app.audit import audit_from_scope
from app.database import get_db
from app.models import (
    Alert,
    AdminLevel,
    Asset,
    AssetCriticality,
    AssetTag,
    AssetType,
    EventSource,
    Incident,
    IncidentAsset,
    Organization,
    OrganizationStatus,
    SecurityEvent,
    Team,
    User,
    UserRole,
)
from app.scope import Scope

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])

ASSET_ENVIRONMENTS = {"production", "staging", "development"}
ASSET_STATUSES = {"active", "retired"}


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


class AssetCreateRequest(BaseModel):
    name: str
    asset_type: str
    hostname: str | None = None
    ip_address: str | None = None
    operating_system: str | None = None
    environment: str | None = None
    criticality: str = AssetCriticality.medium.value
    owner_user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    description: str | None = None
    tags: list[str] = []


class AssetPatchRequest(BaseModel):
    name: str | None = None
    asset_type: str | None = None
    hostname: str | None = None
    ip_address: str | None = None
    operating_system: str | None = None
    environment: str | None = None
    criticality: str | None = None
    owner_user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    description: str | None = None
    status: str | None = None


class AssetTagsRequest(BaseModel):
    tags: list[str]


async def require_org_assets_write(
    scope: Scope = Depends(require_active_organization),
    _write_floor: Scope = Depends(require_module("assets", write=True)),
) -> Scope:
    """
    Combines "organization is active" with "this role's module-level
    assets access is write" -- both require_active_organization and
    require_module deliberately let a platform account (organization_id
    is None) sail through unchecked, since each was written for
    endpoints platform accounts are allowed to reach. Assets' write
    endpoints are not one of those, so reject explicitly here.
    """
    if scope.organization_id is None:
        raise _err(
            "platform_admin_not_supported",
            "Platform accounts cannot write assets directly.",
            status_code=403,
        )
    return scope


async def require_org_assets_read(
    scope: Scope = Depends(require_active_organization),
    _read_floor: Scope = Depends(require_module("assets", write=False)),
) -> Scope:
    """Same idea as require_org_assets_write, but for read: lets a real
    organization account through only with at least read-level assets
    access, while a platform account (super_admin, platform_soc_analyst)
    passes through unchecked here so _target_organization() below can
    apply their own, different visibility rule."""
    return scope


async def _target_organization(
    scope: Scope, db: AsyncSession, organization_id: uuid.UUID | None
) -> tuple[uuid.UUID, bool]:
    """
    Returns (organization_id, is_read_only_platform_soc). A real
    organization account (owner or `users`) always reads/writes its own
    organization -- the organization_id query param is ignored for them,
    never trusted as a way to pick a different one. A platform_soc_analyst
    has no organization_id of their own, so they must pass one, and it's
    checked against soc_visible_organization_ids() (assigned + managed +
    active) -- 404, not 403, for one they can't see, so a guessed id
    reveals nothing. A super_admin never reaches here (rejected below)
    -- see GET /admin/organizations/{id}/assets instead.
    """
    if scope.organization_id is not None:
        return scope.organization_id, False

    if scope.role == AdminLevel.platform_soc_analyst.value:
        if organization_id is None:
            raise _err(
                "organization_id_required",
                "organization_id is required for a platform SOC analyst.",
                status_code=400,
            )
        visible = await soc_visible_organization_ids(db, scope)
        if visible is not None and organization_id not in visible:
            raise _err("organization_not_found", "Organization not found.", status_code=404)
        return organization_id, True

    raise _err(
        "platform_admin_not_supported",
        "Use GET /admin/organizations/{id}/assets instead.",
        status_code=403,
    )


def _can_write_asset(scope: Scope, asset: Asset) -> bool:
    """Row-level write check, on top of the module-level floor
    require_org_assets_write already enforced. organization_admin and
    security_manager are unrestricted; it_developer only their own or
    their team's; nothing else ever reaches a write endpoint at all."""
    if scope.account_type == "admin":
        return True
    if scope.role == UserRole.security_manager.value:
        return True
    if scope.role == UserRole.it_developer.value:
        if asset.owner_user_id is not None and asset.owner_user_id == scope.user_id:
            return True
        caller_team_id = getattr(scope.account, "team_id", None)
        if caller_team_id is not None and asset.team_id is not None and caller_team_id == asset.team_id:
            return True
        return False
    return False


def _validate_asset_type(value: str) -> AssetType:
    try:
        return AssetType(value)
    except ValueError:
        raise _err("invalid_asset_type", f"Unknown asset type '{value}'.")


def _validate_criticality(value: str) -> AssetCriticality:
    try:
        return AssetCriticality(value)
    except ValueError:
        raise _err("invalid_criticality", f"Unknown criticality '{value}'.")


def _validate_environment(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in ASSET_ENVIRONMENTS:
        raise _err("invalid_environment", f"environment must be one of {sorted(ASSET_ENVIRONMENTS)}.")
    return value


def _validate_status(value: str) -> str:
    if value not in ASSET_STATUSES:
        raise _err("invalid_status", f"status must be one of {sorted(ASSET_STATUSES)}.")
    return value


def _validate_ip_address(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        raise _err("invalid_ip_address", f"'{value}' is not a valid IP address.")
    return value


async def _assert_hostname_available(
    db: AsyncSession, organization_id: uuid.UUID, hostname: str | None, exclude_asset_id: uuid.UUID | None = None
) -> None:
    if not hostname:
        return
    stmt = select(Asset.id).where(
        Asset.organization_id == organization_id, func.lower(Asset.hostname) == hostname.strip().lower()
    )
    if exclude_asset_id is not None:
        stmt = stmt.where(Asset.id != exclude_asset_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise _err(
            "duplicate_hostname",
            f"An asset with hostname '{hostname}' already exists in this organization.",
            status_code=409,
        )


async def _assert_owner_in_org(db: AsyncSession, organization_id: uuid.UUID, owner_user_id: uuid.UUID | None) -> None:
    if owner_user_id is None:
        return
    owner = (
        await db.execute(select(User.id).where(User.id == owner_user_id, User.organization_id == organization_id))
    ).scalar_one_or_none()
    if owner is None:
        raise _err("owner_not_found", "Owner not found in this organization.", status_code=404)


async def _assert_team_in_org(db: AsyncSession, organization_id: uuid.UUID, team_id: uuid.UUID | None) -> None:
    if team_id is None:
        return
    team = (
        await db.execute(select(Team.id).where(Team.id == team_id, Team.organization_id == organization_id))
    ).scalar_one_or_none()
    if team is None:
        raise _err("team_not_found", "Team not found in this organization.", status_code=404)


async def _get_org_asset(db: AsyncSession, organization_id: uuid.UUID, asset_id: uuid.UUID) -> Asset:
    asset = (
        await db.execute(select(Asset).where(Asset.id == asset_id, Asset.organization_id == organization_id))
    ).scalar_one_or_none()
    if asset is None:
        raise _err("asset_not_found", "Asset not found.", status_code=404)
    return asset


async def _rows_for(db: AsyncSession, scope: Scope, assets: list[Asset], can_edit_all_false: bool) -> list[dict]:
    if not assets:
        return []

    asset_ids = [a.id for a in assets]
    owner_ids = {a.owner_user_id for a in assets if a.owner_user_id is not None}
    team_ids = {a.team_id for a in assets if a.team_id is not None}

    owners = {}
    if owner_ids:
        rows = (await db.execute(select(User.id, User.name).where(User.id.in_(owner_ids)))).all()
        owners = {row[0]: row[1] for row in rows}

    teams = {}
    if team_ids:
        rows = (await db.execute(select(Team.id, Team.name).where(Team.id.in_(team_ids)))).all()
        teams = {row[0]: row[1] for row in rows}

    tag_rows = (await db.execute(select(AssetTag).where(AssetTag.asset_id.in_(asset_ids)))).scalars().all()
    tags_by_asset: dict[uuid.UUID, list[str]] = {}
    for row in tag_rows:
        tags_by_asset.setdefault(row.asset_id, []).append(row.tag)

    out = []
    for asset in assets:
        can_edit = False if can_edit_all_false else _can_write_asset(scope, asset)
        out.append(
            {
                "id": str(asset.id),
                "name": asset.name,
                "hostname": asset.hostname,
                "ip_address": asset.ip_address,
                "asset_type": asset.asset_type.value,
                "criticality": asset.criticality.value,
                "operating_system": asset.operating_system,
                "environment": asset.environment,
                "description": asset.description,
                "owner_user_id": str(asset.owner_user_id) if asset.owner_user_id else None,
                "owner_name": owners.get(asset.owner_user_id),
                "team_id": str(asset.team_id) if asset.team_id else None,
                "team_name": teams.get(asset.team_id),
                "status": asset.status,
                "last_seen_at": asset.last_seen_at.isoformat() if asset.last_seen_at else None,
                "created_at": asset.created_at.isoformat() if asset.created_at else None,
                "tags": sorted(tags_by_asset.get(asset.id, [])),
                "can_edit": can_edit,
            }
        )
    return out


@router.get("/summary")
async def get_assets_summary(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_org_assets_read),
    organization_id: uuid.UUID | None = Query(default=None),
):
    org_id, _soc_readonly = await _target_organization(scope, db, organization_id)

    async def _counts(column) -> dict[str, int]:
        rows = (
            await db.execute(
                select(column, func.count(Asset.id)).where(Asset.organization_id == org_id).group_by(column)
            )
        ).all()
        result: dict[str, int] = {}
        for key, count in rows:
            key_value = key.value if hasattr(key, "value") else key
            result[key_value] = count
        return result

    return {
        "by_type": await _counts(Asset.asset_type),
        "by_criticality": await _counts(Asset.criticality),
        "by_status": await _counts(Asset.status),
    }


@router.get("/lookup")
async def get_assets_lookup(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_org_assets_read),
    organization_id: uuid.UUID | None = Query(default=None),
):
    """Lightweight {users, teams} for the create/edit form's owner/team
    pickers -- GET /organization/members and GET /organization/teams
    are organization_admin-only, so an it_developer or security_manager
    filling out this form has no other endpoint that can give them this
    list for their own organization."""
    org_id, _soc_readonly = await _target_organization(scope, db, organization_id)

    users = (
        await db.execute(
            select(User.id, User.name)
            .where(User.organization_id == org_id, User.is_active.is_(True))
            .order_by(User.name)
        )
    ).all()
    teams = (
        await db.execute(select(Team.id, Team.name).where(Team.organization_id == org_id).order_by(Team.name))
    ).all()

    return {
        "users": [{"id": str(row[0]), "name": row[1]} for row in users],
        "teams": [{"id": str(row[0]), "name": row[1]} for row in teams],
    }


@router.get("")
async def list_assets(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_org_assets_read),
    organization_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    criticality: str | None = Query(default=None),
    status: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    owner_user_id: uuid.UUID | None = Query(default=None),
    team_id: uuid.UUID | None = Query(default=None),
    sort: str = Query(default="created_at_desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    org_id, soc_readonly = await _target_organization(scope, db, organization_id)

    stmt = select(Asset).where(Asset.organization_id == org_id)

    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            (Asset.name.ilike(like)) | (Asset.hostname.ilike(like)) | (Asset.ip_address.ilike(like))
        )
    if asset_type:
        stmt = stmt.where(Asset.asset_type == _validate_asset_type(asset_type))
    if criticality:
        stmt = stmt.where(Asset.criticality == _validate_criticality(criticality))
    if status:
        stmt = stmt.where(Asset.status == _validate_status(status))
    if owner_user_id:
        stmt = stmt.where(Asset.owner_user_id == owner_user_id)
    if team_id:
        stmt = stmt.where(Asset.team_id == team_id)
    if tag:
        stmt = stmt.where(Asset.id.in_(select(AssetTag.asset_id).where(AssetTag.tag == tag)))

    sort_map = {
        "created_at_desc": Asset.created_at.desc(),
        "created_at_asc": Asset.created_at.asc(),
        "name_asc": Asset.name.asc(),
        "name_desc": Asset.name.desc(),
    }
    stmt = stmt.order_by(sort_map.get(sort, Asset.created_at.desc()))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    assets = (await db.execute(stmt)).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "assets": await _rows_for(db, scope, list(assets), can_edit_all_false=soc_readonly),
    }


@router.post("", status_code=201)
async def create_asset(
    payload: AssetCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_org_assets_write),
):
    if not payload.name.strip():
        raise _err("name_required", "Asset name is required.")

    asset_type = _validate_asset_type(payload.asset_type)
    criticality = _validate_criticality(payload.criticality)
    environment = _validate_environment(payload.environment)
    ip_address = _validate_ip_address(payload.ip_address)
    hostname = payload.hostname.strip() if payload.hostname else None

    await _assert_hostname_available(db, scope.organization_id, hostname)
    await _assert_owner_in_org(db, scope.organization_id, payload.owner_user_id)
    await _assert_team_in_org(db, scope.organization_id, payload.team_id)

    # An it_developer's own row-level write access is "owns it or is on
    # its team" (_can_write_asset) -- if they create an asset without
    # picking an owner or a team, it would come out the other end
    # immediately uneditable by them. Default the owner to themselves in
    # that one case so creating an asset never orphans it from its
    # creator; every other write role (organization_admin,
    # security_manager) has unrestricted row-level write anyway, so this
    # default only ever changes behavior for it_developer.
    owner_user_id = payload.owner_user_id
    if owner_user_id is None and payload.team_id is None and scope.role == UserRole.it_developer.value:
        owner_user_id = scope.user_id

    asset = Asset(
        organization_id=scope.organization_id,
        name=payload.name.strip(),
        asset_type=asset_type,
        hostname=hostname,
        ip_address=ip_address,
        operating_system=payload.operating_system,
        environment=environment,
        criticality=criticality,
        owner_user_id=owner_user_id,
        team_id=payload.team_id,
        description=payload.description,
        status="active",
    )
    db.add(asset)
    await db.flush()

    for tag in dict.fromkeys(t.strip() for t in payload.tags if t.strip()):
        db.add(AssetTag(asset_id=asset.id, tag=tag))

    await audit_from_scope(
        db, scope, "asset.create", target_type="asset", target_id=asset.id, request=request,
        after={"name": asset.name, "asset_type": asset_type.value},
    )
    await db.commit()

    rows = await _rows_for(db, scope, [asset], can_edit_all_false=False)
    return rows[0]


@router.get("/{asset_id}")
async def get_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_org_assets_read),
    organization_id: uuid.UUID | None = Query(default=None),
):
    org_id, soc_readonly = await _target_organization(scope, db, organization_id)
    asset = await _get_org_asset(db, org_id, asset_id)
    rows = await _rows_for(db, scope, [asset], can_edit_all_false=soc_readonly)
    return rows[0]


@router.patch("/{asset_id}")
async def patch_asset(
    asset_id: uuid.UUID,
    payload: AssetPatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_org_assets_write),
):
    asset = await _get_org_asset(db, scope.organization_id, asset_id)
    if not _can_write_asset(scope, asset):
        raise _err("asset_not_editable", "You do not have permission to edit this asset.", status_code=403)

    before = {
        "name": asset.name, "criticality": asset.criticality.value, "status": asset.status,
        "owner_user_id": str(asset.owner_user_id) if asset.owner_user_id else None,
        "team_id": str(asset.team_id) if asset.team_id else None,
    }

    status_changed = False

    # An explicitly-provided null clears the field (the UI's edit dialog
    # needs that to unassign an owner/team or blank a hostname); a field
    # simply absent from the payload is left untouched.
    # model_fields_set is Pydantic v2's "which keys did the client actually
    # send" -- plain `is not None` checks can't tell the two apart.
    provided = payload.model_fields_set

    if "name" in provided:
        if not payload.name or not payload.name.strip():
            raise _err("name_required", "Asset name is required.")
        asset.name = payload.name.strip()
    if "asset_type" in provided and payload.asset_type is not None:
        asset.asset_type = _validate_asset_type(payload.asset_type)
    if "hostname" in provided:
        hostname = (payload.hostname or "").strip() or None
        await _assert_hostname_available(db, scope.organization_id, hostname, exclude_asset_id=asset.id)
        asset.hostname = hostname
    if "ip_address" in provided:
        asset.ip_address = _validate_ip_address(payload.ip_address)
    if "operating_system" in provided:
        asset.operating_system = payload.operating_system
    if "environment" in provided:
        asset.environment = _validate_environment(payload.environment)
    if "criticality" in provided and payload.criticality is not None:
        asset.criticality = _validate_criticality(payload.criticality)
    if "owner_user_id" in provided:
        await _assert_owner_in_org(db, scope.organization_id, payload.owner_user_id)
        asset.owner_user_id = payload.owner_user_id
    if "team_id" in provided:
        await _assert_team_in_org(db, scope.organization_id, payload.team_id)
        asset.team_id = payload.team_id
    if "description" in provided:
        asset.description = payload.description
    if payload.status is not None and payload.status != asset.status:
        asset.status = _validate_status(payload.status)
        status_changed = True

    after = {
        "name": asset.name, "criticality": asset.criticality.value, "status": asset.status,
        "owner_user_id": str(asset.owner_user_id) if asset.owner_user_id else None,
        "team_id": str(asset.team_id) if asset.team_id else None,
    }
    # Only write the audit entry when something actually changed -- a
    # no-op PATCH (or one that just re-sent current values) isn't a
    # state change worth an append-only row.

    if before != after:
        await audit_from_scope(
            db, scope, "asset.update", target_type="asset", target_id=asset.id, request=request,
            before=before, after=after,
        )
    if status_changed:
        await audit_from_scope(
            db, scope, "asset.status_change", target_type="asset", target_id=asset.id, request=request,
            before={"status": before["status"]}, after={"status": after["status"]},
        )
    await db.commit()

    rows = await _rows_for(db, scope, [asset], can_edit_all_false=False)
    return rows[0]


@router.delete("/{asset_id}")
async def retire_asset(
    asset_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_org_assets_write),
):
    """Soft-delete only -- sets status to 'retired'. There is no
    hard-delete path in this API at all (nothing here ever issues a SQL
    DELETE on an assets row), so there is nothing that could orphan an
    event/alert/incident's asset_id; see docs/DECISIONS.md for the
    reasoning."""
    asset = await _get_org_asset(db, scope.organization_id, asset_id)
    if not _can_write_asset(scope, asset):
        raise _err("asset_not_editable", "You do not have permission to retire this asset.", status_code=403)
    if asset.status == "retired":
        raise _err("asset_already_retired", "This asset is already retired.", status_code=409)

    asset.status = "retired"
    await audit_from_scope(
        db, scope, "asset.retire", target_type="asset", target_id=asset.id, request=request,
        before={"status": "active"}, after={"status": "retired"},
    )
    await db.commit()

    rows = await _rows_for(db, scope, [asset], can_edit_all_false=False)
    return rows[0]


@router.put("/{asset_id}/tags")
async def set_asset_tags(
    asset_id: uuid.UUID,
    payload: AssetTagsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_org_assets_write),
):
    asset = await _get_org_asset(db, scope.organization_id, asset_id)
    if not _can_write_asset(scope, asset):
        raise _err("asset_not_editable", "You do not have permission to edit this asset.", status_code=403)

    existing = (await db.execute(select(AssetTag).where(AssetTag.asset_id == asset.id))).scalars().all()
    before_tags = sorted(row.tag for row in existing)
    for row in existing:
        await db.delete(row)

    new_tags = sorted(dict.fromkeys(t.strip() for t in payload.tags if t.strip()))
    for tag in new_tags:
        db.add(AssetTag(asset_id=asset.id, tag=tag))

    await audit_from_scope(
        db, scope, "asset.tags_change", target_type="asset", target_id=asset.id, request=request,
        before={"tags": before_tags}, after={"tags": new_tags},
    )
    await db.commit()

    rows = await _rows_for(db, scope, [asset], can_edit_all_false=False)
    return rows[0]
