"""
Agent endpoints for enrolled endpoint devices (P20).

Handles:
- POST /api/v1/agent/enroll: Swap single-use enrollment token for device ApiKey (after consent).
- POST /api/v1/agent/heartbeat: Periodic liveness heartbeat and dynamic category config.
- GET /api/v1/agent/config: Read consent-aware configuration and active categories.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    ApiKey,
    Asset,
    ConsentRecord,
    DeviceEnrollment,
    EventSource,
    EventSourceType,
)
from app.routers.event_sources import generate_api_key, hash_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


class AgentEnrollRequest(BaseModel):
    enrollment_token: str = Field(..., min_length=10)
    device_name: str | None = None
    operating_system: str | None = None
    agent_version: str | None = "1.0.0"


class AgentHeartbeatRequest(BaseModel):
    agent_version: str | None = None
    device_name: str | None = None
    operating_system: str | None = None


async def _resolve_device_agent(
    authorization: str | None,
    db: AsyncSession,
) -> tuple[DeviceEnrollment, ApiKey, ConsentRecord | None]:
    """Resolves Authorization: Bearer sx_... to device enrollment, api_key, and active consent."""
    if not authorization or not authorization.startswith("Bearer "):
        raise _err("invalid_api_key", "A valid device agent API key is required.", 401)
    token = authorization[len("Bearer "):].strip()
    key_hash = hash_api_key(token)

    row = (
        await db.execute(
            select(DeviceEnrollment, ApiKey)
            .join(ApiKey, ApiKey.id == DeviceEnrollment.api_key_id)
            .where(ApiKey.key_hash == key_hash)
        )
    ).first()

    if row is None:
        raise _err("invalid_api_key", "Device agent API key not found or invalid.", 401)

    enrollment, api_key = row
    if api_key.revoked_at is not None:
        raise _err("api_key_revoked", "This device API key has been revoked.", 401)

    active_consent = None
    if enrollment.consent_record_id:
        active_consent = await db.get(ConsentRecord, enrollment.consent_record_id)
        if active_consent and active_consent.revoked_at is not None:
            active_consent = None

    return enrollment, api_key, active_consent


@router.post("/enroll", status_code=201)
async def agent_enroll(
    payload: AgentEnrollRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Swaps single-use enrollment token (sxe_...) for an ingestion API key.
    Requires that consent has ALREADY been accepted for this token.
    """
    token_hash = hashlib.sha256(payload.enrollment_token.encode("utf-8")).hexdigest()
    row = (
        await db.execute(
            select(DeviceEnrollment, Asset)
            .join(Asset, Asset.id == DeviceEnrollment.asset_id)
            .where(DeviceEnrollment.token_hash == token_hash)
        )
    ).first()

    if row is None:
        raise _err("token_not_found", "Enrollment token is invalid or does not exist.", 404)

    enrollment, asset = row
    now_utc = datetime.now(timezone.utc)

    if enrollment.status == "revoked":
        raise _err("token_revoked", "This enrollment token has been revoked.", 410)
    if enrollment.expires_at < now_utc:
        raise _err("token_expired", "This enrollment token has expired (30-minute limit).", 410)
    if enrollment.status == "enrolled":
        raise _err("token_already_used", "This enrollment token has already been used.", 409)

    # Consent gate: Must have an active consent record attached
    if not enrollment.consent_record_id:
        raise _err("consent_required", "User must review and accept consent text before agent enrollment.", 400)

    consent = await db.get(ConsentRecord, enrollment.consent_record_id)
    if consent is None or consent.revoked_at is not None:
        raise _err("consent_revoked", "Monitoring consent for this device has been revoked or is missing.", 403)

    # Provision EventSource for this device
    event_source = EventSource(
        organization_id=enrollment.organization_id,
        name=f"Device Agent - {asset.name}",
        source_type=EventSourceType.application,
        asset_id=asset.id,
        status="active",
        config={"device_enrollment_id": str(enrollment.id), "os": payload.operating_system or asset.operating_system},
    )
    db.add(event_source)
    await db.flush()

    # Generate ingestion ApiKey (shown once)
    full_key, key_hash, prefix = generate_api_key()
    api_key = ApiKey(
        organization_id=enrollment.organization_id,
        event_source_id=event_source.id,
        key_hash=key_hash,
        prefix=prefix,
    )
    db.add(api_key)
    await db.flush()

    # Mark enrollment completed & single-used
    enrollment.status = "enrolled"
    enrollment.enrolled_at = now_utc
    enrollment.last_seen_at = now_utc
    enrollment.last_heartbeat_at = now_utc
    enrollment.api_key_id = api_key.id
    enrollment.event_source_id = event_source.id
    if payload.device_name:
        enrollment.device_name = payload.device_name
    if payload.operating_system:
        enrollment.operating_system = payload.operating_system
    if payload.agent_version:
        enrollment.agent_version = payload.agent_version

    asset.last_seen_at = now_utc
    await db.commit()

    return {
        "status": "enrolled",
        "api_key": full_key,
        "device_id": str(enrollment.id),
        "asset_id": str(asset.id),
        "organization_id": str(enrollment.organization_id),
        "enabled_categories": consent.categories_granted,
        "heartbeat_interval_seconds": 30,
    }


@router.post("/heartbeat")
async def agent_heartbeat(
    payload: AgentHeartbeatRequest | None = None,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Agent heartbeat confirming liveness and receiving current consent categories."""
    enrollment, api_key, consent = await _resolve_device_agent(authorization, db)
    now_utc = datetime.now(timezone.utc)

    if enrollment.status == "revoked" or consent is None:
        return {
            "status": "revoked",
            "terminate": True,
            "message": "Device monitoring or consent has been revoked.",
            "enabled_categories": [],
        }

    enrollment.last_heartbeat_at = now_utc
    enrollment.last_seen_at = now_utc
    api_key.last_used_at = now_utc

    if payload:
        if payload.agent_version:
            enrollment.agent_version = payload.agent_version
        if payload.device_name:
            enrollment.device_name = payload.device_name
        if payload.operating_system:
            enrollment.operating_system = payload.operating_system

    asset = await db.get(Asset, enrollment.asset_id)
    if asset:
        asset.last_seen_at = now_utc

    await db.commit()

    return {
        "status": "ok",
        "device_id": str(enrollment.id),
        "enabled_categories": consent.categories_granted,
        "heartbeat_interval_seconds": 30,
    }


@router.get("/config")
async def agent_config(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Agent queries active configuration and granted categories."""
    enrollment, _api_key, consent = await _resolve_device_agent(authorization, db)

    if enrollment.status == "revoked" or consent is None:
        return {
            "status": "revoked",
            "terminate": True,
            "enabled_categories": [],
        }

    return {
        "status": "ok",
        "device_id": str(enrollment.id),
        "asset_id": str(enrollment.asset_id),
        "organization_id": str(enrollment.organization_id),
        "enabled_categories": consent.categories_granted,
        "consent_version": consent.consent_text_version,
    }

