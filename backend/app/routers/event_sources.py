"""
Registered event sources and their ingestion API keys.

An event source is a thing that ships security events into SentinelX (a
linux_auth collector on a box, an application, docker, a network probe,
or a custom JSON feed). Each source can have API keys -- collectors
authenticate with `Authorization: Bearer sx_<prefix>_<secret>` -- and
ingestion (P07) resolves the source (and through it the organization)
from the key, never from a client-supplied org id.

Access (docs/DECISIONS.md "Event sources are managed by
organization_admin + security_manager"):
  - organization_admin (owner) and security_manager: full CRUD + keys.
    Deliberately NOT the `assets`-write rule: minting ingestion keys is
    security administration, not device management.
  - soc_analyst / auditor: read-only list/detail.
  - platform accounts (super_admin, platform_soc_analyst): NOT here --
    super_admin reads a per-organization list through
    GET /admin/organizations/{id}/event-sources (admin_organizations.py),
    matching every other admin-side view.

Keys: generated once (secrets.token_urlsafe, 32+ bytes of entropy), the
full key `sx_<prefix>_<secret>` is returned exactly once at creation,
only a SHA-256 hash and a short display prefix are stored, keys are
revocable (never deletable -- revocation keeps the audit trail), record
last_used_at, and never appear in logs or audit summaries.
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_active_organization
from app.audit import audit_from_scope
from app.database import get_db
from app.models import ApiKey, EventSource, EventSourceType, Organization, UserRole
from app.scope import Scope

router = APIRouter(prefix="/api/v1/event-sources", tags=["event-sources"])

logger = logging.getLogger(__name__)


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


# --------------------------------------------------------------------------
# Access dependencies (dedicated role check -- see module docstring).
# --------------------------------------------------------------------------

async def require_event_sources_write(
    scope: Scope = Depends(require_active_organization),
) -> Scope:
    if scope.organization_id is None:
        raise _err("platform_admin_not_supported", "Platform accounts cannot manage event sources here.", 403)
    if scope.account_type == "admin":
        return scope  # organization_admin
    if scope.role == UserRole.security_manager.value:
        return scope
    raise _err("event_sources_write_required", "Only the organization owner or a security manager can manage event sources.", 403)


async def require_event_sources_read(
    scope: Scope = Depends(require_active_organization),
) -> Scope:
    if scope.organization_id is None:
        raise _err("platform_admin_not_supported", "Use GET /admin/organizations/{id}/event-sources instead.", 403)
    return scope  # any active-org account (soc_analyst/auditor get read-only rows via can_manage)


# --------------------------------------------------------------------------
# Key generation / verification.
# --------------------------------------------------------------------------

# 24 url-safe chars ~= 144 bits of entropy for the visible prefix part;
# the secret part is 43 chars (~256 bits). Combined well above the 32-byte
# floor the spec requires.
_PREFIX_CHARS = 24
_SECRET_CHARS = 43


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, sha256_hex_hash, short_display_prefix)."""
    prefix = secrets.token_urlsafe(_PREFIX_CHARS)[:_PREFIX_CHARS]
    secret = secrets.token_urlsafe(_SECRET_CHARS)[:_SECRET_CHARS]
    full_key = f"sx_{prefix}_{secret}"
    key_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
    display_prefix = f"sx_{prefix[:8]}"
    return full_key, key_hash, display_prefix


def hash_api_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


async def rate_limit_for_key(db: AsyncSession, api_key: ApiKey) -> None:
    """
    Per-key rate limit (P07): a fixed window in Redis -- one counter per
    api_keys.id per calendar minute, settings.events_rate_limit_per_minute
    events (default 600). A Redis outage does not block ingestion: the
    limit degrades to "no limit" for that request, matching enqueue_work's
    stance that background infrastructure is optional to a request's
    success. Raises 429 rate_limited when the window's quota is exhausted.

    The client is a module-level lazy singleton: one pool for the process,
    reused across requests, closed with the app.
    """
    from app.config import settings
    from app.event_ingestion import KeyRateLimited, enforce_key_rate_limit

    client = await _get_rate_limit_redis()
    if client is None:
        return
    try:
        await enforce_key_rate_limit(client, str(api_key.id), settings.events_rate_limit_per_minute)
    except KeyRateLimited as exc:
        raise _err(
            "rate_limited",
            "Too many events for this API key this minute.",
            429,
        ) from exc


_rate_limit_redis = None


async def _get_rate_limit_redis():
    """Lazily create the shared rate-limit Redis client. Returns None (and
    logs once) when Redis is unreachable -- rate limiting degrades to a
    no-op rather than failing ingestion."""
    global _rate_limit_redis
    if _rate_limit_redis is not None:
        return _rate_limit_redis

    import redis.asyncio as aioredis

    from app.config import settings

    try:
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _rate_limit_redis = client
        return client
    except Exception:  # noqa: BLE001 -- a down Redis must not 500 ingestion
        logger.warning("Redis unreachable for event rate limiting -- limit disabled this request")
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass
        return None


async def close_rate_limit_redis() -> None:
    global _rate_limit_redis
    if _rate_limit_redis is not None:
        try:
            await _rate_limit_redis.aclose()
        except Exception:  # noqa: BLE001
            pass
        _rate_limit_redis = None


async def get_event_source_from_api_key(
    db: AsyncSession,
    authorization: str | None,
) -> tuple[EventSource, ApiKey]:
    """
    Authenticate an ingestion request: resolve `Authorization: Bearer
    sx_...` to (event_source, api_key), or raise. 401 for any failure
    shape (missing/garbled/unknown/revoked key) with the same message so
    the endpoint reveals nothing about which part failed; 403 only for a
    valid key whose source has been disabled.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise _err("invalid_api_key", "A valid event-source API key is required.", 401)
    token = authorization[len("Bearer "):].strip()
    if not token.startswith("sx_") or token.count("_") < 2:
        raise _err("invalid_api_key", "A valid event-source API key is required.", 401)

    key_hash = hash_api_key(token)
    row = (
        await db.execute(
            select(ApiKey, EventSource)
            .join(EventSource, EventSource.id == ApiKey.event_source_id)
            .where(ApiKey.key_hash == key_hash)
        )
    ).first()

    if row is None:
        raise _err("invalid_api_key", "A valid event-source API key is required.", 401)
    api_key, event_source = row

    if api_key.revoked_at is not None:
        raise _err("invalid_api_key", "A valid event-source API key is required.", 401)
    if event_source.status != "active":
        raise _err("event_source_disabled", "This event source has been disabled.", 403)

    # Hash-compare as a final belt-and-braces (the lookup is already by
    # hash; this also future-proofs a move to a KMS/HMAC scheme).
    if not constant_time_equals(api_key.key_hash, key_hash):
        raise _err("invalid_api_key", "A valid event-source API key is required.", 401)

    api_key.last_used_at = datetime.now(timezone.utc)
    await rate_limit_for_key(db, api_key)
    return event_source, api_key


# --------------------------------------------------------------------------
# Schemas.
# --------------------------------------------------------------------------

class EventSourceCreateRequest(BaseModel):
    name: str
    source_type: str
    asset_id: uuid.UUID | None = None
    enabled: bool = True
    config: dict | None = None


class EventSourcePatchRequest(BaseModel):
    name: str | None = None
    asset_id: uuid.UUID | None = None
    enabled: bool | None = None
    config: dict | None = None


def _validate_source_type(value: str) -> EventSourceType:
    try:
        return EventSourceType(value)
    except ValueError:
        raise _err("invalid_source_type", f"Unknown event source type '{value}'.")


def _row_for(source: EventSource, can_manage: bool) -> dict:
    return {
        "id": str(source.id),
        "name": source.name,
        "source_type": source.source_type.value,
        "asset_id": str(source.asset_id) if source.asset_id else None,
        "enabled": source.status == "active",
        "status": source.status,
        "last_event_at": source.last_event_at.isoformat() if source.last_event_at else None,
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "can_manage": can_manage,
    }


def _key_row(key: ApiKey) -> dict:
    # Deliberately omits key_hash -- hashes never leave the server.
    return {
        "id": str(key.id),
        "prefix": key.prefix,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked": key.revoked_at is not None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
    }


async def _get_org_source(
    db: AsyncSession, organization_id: uuid.UUID, source_id: uuid.UUID
) -> EventSource:
    source = (
        await db.execute(
            select(EventSource).where(EventSource.id == source_id, EventSource.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if source is None:
        raise _err("event_source_not_found", "Event source not found.", 404)
    return source


# --------------------------------------------------------------------------
# Source CRUD.
# --------------------------------------------------------------------------

@router.get("")
async def list_event_sources(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_event_sources_read),
):
    can_manage = scope.account_type == "admin" or scope.role == UserRole.security_manager.value
    sources = (
        await db.execute(
            select(EventSource)
            .where(EventSource.organization_id == scope.organization_id)
            .order_by(EventSource.created_at.desc())
        )
    ).scalars().all()
    return {"event_sources": [_row_for(s, can_manage) for s in sources]}


@router.post("", status_code=201)
async def create_event_source(
    payload: EventSourceCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_event_sources_write),
):
    if not payload.name.strip():
        raise _err("name_required", "Event source name is required.")
    source_type = _validate_source_type(payload.source_type)

    if payload.asset_id is not None:
        from app.models import Asset  # local import: avoids a cycle at module load
        asset = (
            await db.execute(
                select(Asset.id).where(Asset.id == payload.asset_id, Asset.organization_id == scope.organization_id)
            )
        ).scalar_one_or_none()
        if asset is None:
            raise _err("asset_not_found", "Asset not found in this organization.", 404)

    source = EventSource(
        organization_id=scope.organization_id,
        name=payload.name.strip(),
        source_type=source_type,
        asset_id=payload.asset_id,
        config=payload.config,
        status="active" if payload.enabled else "disabled",
    )
    db.add(source)
    await db.flush()

    await audit_from_scope(
        db, scope, "event_source.create", target_type="event_source", target_id=source.id, request=request,
        after={"name": source.name, "source_type": source_type.value, "enabled": payload.enabled},
    )
    await db.commit()
    return _row_for(source, can_manage=True)


@router.get("/{source_id}")
async def get_event_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_event_sources_read),
):
    source = await _get_org_source(db, scope.organization_id, source_id)
    can_manage = scope.account_type == "admin" or scope.role == UserRole.security_manager.value
    return _row_for(source, can_manage)


@router.patch("/{source_id}")
async def patch_event_source(
    source_id: uuid.UUID,
    payload: EventSourcePatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_event_sources_write),
):
    source = await _get_org_source(db, scope.organization_id, source_id)
    before = {"name": source.name, "status": source.status, "asset_id": str(source.asset_id) if source.asset_id else None}
    disabled_now = False

    provided = payload.model_fields_set
    if "name" in provided:
        if not payload.name or not payload.name.strip():
            raise _err("name_required", "Event source name is required.")
        source.name = payload.name.strip()
    if "asset_id" in provided:
        if payload.asset_id is not None:
            from app.models import Asset
            asset = (
                await db.execute(
                    select(Asset.id).where(Asset.id == payload.asset_id, Asset.organization_id == scope.organization_id)
                )
            ).scalar_one_or_none()
            if asset is None:
                raise _err("asset_not_found", "Asset not found in this organization.", 404)
        source.asset_id = payload.asset_id
    if "config" in provided and payload.config is not None:
        source.config = payload.config
    if "enabled" in provided and payload.enabled is not None:
        new_status = "active" if payload.enabled else "disabled"
        if new_status != source.status:
            source.status = new_status
            disabled_now = new_status == "disabled"

    after = {"name": source.name, "status": source.status, "asset_id": str(source.asset_id) if source.asset_id else None}
    if before != after:
        await audit_from_scope(
            db, scope, "event_source.update", target_type="event_source", target_id=source.id, request=request,
            before=before, after=after,
        )
    if disabled_now:
        await audit_from_scope(
            db, scope, "event_source.disable", target_type="event_source", target_id=source.id, request=request,
            before={"status": "active"}, after={"status": "disabled"},
        )
    await db.commit()
    return _row_for(source, can_manage=True)


@router.delete("/{source_id}")
async def disable_event_source(
    source_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_event_sources_write),
):
    """Soft-disable (never a hard delete): the source's keys and its
    identity in past events/alerts must keep resolving. Its keys stop
    working immediately (status check in get_event_source_from_api_key)."""
    source = await _get_org_source(db, scope.organization_id, source_id)
    if source.status == "disabled":
        raise _err("event_source_already_disabled", "This event source is already disabled.", 409)
    source.status = "disabled"
    await audit_from_scope(
        db, scope, "event_source.disable", target_type="event_source", target_id=source.id, request=request,
        before={"status": "active"}, after={"status": "disabled"},
    )
    await db.commit()
    return _row_for(source, can_manage=True)


# --------------------------------------------------------------------------
# Keys.
# --------------------------------------------------------------------------

@router.post("/{source_id}/keys", status_code=201)
async def create_api_key(
    source_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_event_sources_write),
):
    """Generates the key, stores only the hash + short prefix, and returns
    the FULL key exactly once -- the only response in the API that ever
    contains it."""
    source = await _get_org_source(db, scope.organization_id, source_id)
    full_key, key_hash, display_prefix = generate_api_key()

    api_key = ApiKey(
        organization_id=scope.organization_id,
        event_source_id=source.id,
        key_hash=key_hash,
        prefix=display_prefix,
        created_by_admin_id=scope.account.id if scope.account_type == "admin" else None,
    )
    db.add(api_key)
    await db.flush()

    await audit_from_scope(
        db, scope, "api_key.create", target_type="event_source", target_id=source.id, request=request,
        after={"key_prefix": display_prefix},  # prefix only -- never the key itself
    )
    await db.commit()

    row = _key_row(api_key)
    row["key"] = full_key  # exactly-once return
    row["source_id"] = str(source.id)
    return row


@router.get("/{source_id}/keys")
async def list_api_keys(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_event_sources_write),
):
    source = await _get_org_source(db, scope.organization_id, source_id)
    keys = (
        await db.execute(
            select(ApiKey).where(ApiKey.event_source_id == source.id).order_by(ApiKey.created_at.desc())
        )
    ).scalars().all()
    return {"keys": [_key_row(k) for k in keys]}


@router.delete("/{source_id}/keys/{key_id}")
async def revoke_api_key(
    source_id: uuid.UUID,
    key_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_event_sources_write),
):
    source = await _get_org_source(db, scope.organization_id, source_id)
    api_key = (
        await db.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.event_source_id == source.id)
        )
    ).scalar_one_or_none()
    if api_key is None:
        raise _err("api_key_not_found", "API key not found.", 404)
    if api_key.revoked_at is not None:
        raise _err("api_key_already_revoked", "This API key is already revoked.", 409)

    api_key.revoked_at = datetime.now(timezone.utc)
    await audit_from_scope(
        db, scope, "api_key.revoke", target_type="event_source", target_id=source.id, request=request,
        after={"key_prefix": api_key.prefix},
    )
    await db.commit()
    return _key_row(api_key)
