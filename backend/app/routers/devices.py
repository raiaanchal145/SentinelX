"""
Device management, enrollment tokens, and consent records (P20).

Enforces consent-based monitoring:
- Enrollment tokens (sxe_...) are single-use, 30-minute expiration.
- The person using the device explicitly selects monitoring categories on the consent screen
  and accepts the versioned consent text (v1.0).
- Only AFTER consent is accepted can the agent swap the token for an ingestion API key.
- Revoking a device or its consent immediately halts event ingestion.
- Modifying consent writes a NEW consent_records row; history is never mutated.
- Platform SOC has read-only visibility for assigned managed orgs; can NEVER grant consent.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_active_organization, require_module
from app.audit import audit_from_scope
from app.consent import ALL_CATEGORY_KEYS, CONSENT_CATEGORIES, CONSENT_TEXT_VERSION
from app.database import get_db
from app.models import (
    AdminLevel,
    ApiKey,
    Asset,
    ConsentRecord,
    DeviceEnrollment,
    EventSource,
    EventSourceType,
    Organization,
    UserRole,
)
from app.scope import Scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_enrollment_token() -> tuple[str, str, str]:
    """Generates (token, token_hash, prefix)."""
    raw = secrets.token_urlsafe(32)
    token = f"sxe_{raw}"
    token_hash = _hash_token(token)
    prefix = f"sxe_{raw[:6]}"
    return token, token_hash, prefix


def compute_device_status(enrollment: DeviceEnrollment, active_consent: ConsentRecord | None, now_utc: datetime) -> str:
    if enrollment.status == "revoked" or (active_consent is not None and active_consent.revoked_at is not None):
        return "revoked"
    if enrollment.status != "enrolled":
        if enrollment.expires_at < now_utc:
            return "expired"
        return enrollment.status  # "pending_consent"
    if enrollment.last_heartbeat_at is None:
        return "offline"
    age = (now_utc - enrollment.last_heartbeat_at).total_seconds()
    if age <= 120:
        return "connected"
    if age <= 600:
        return "stale"
    return "offline"


# --------------------------------------------------------------------------
# Permission Helpers
# --------------------------------------------------------------------------

async def _can_manage_devices(db: AsyncSession, scope: Scope) -> bool:
    """Owner (admin), security_manager, or it_developer with write access."""
    if scope.organization_id is None:
        return False
    if scope.account_type == "admin":
        return True
    if scope.role == UserRole.security_manager.value:
        return True
    if scope.role == UserRole.it_developer.value:
        org = await db.get(Organization, scope.organization_id)
        if org:
            from app.access import get_effective_access
            access = await get_effective_access(db, scope.account, org)
            return access["modules"].get("device_agents") == "write"
    return False


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class CreateEnrollmentTokenRequest(BaseModel):
    asset_id: uuid.UUID
    device_name: str | None = None
    operating_system: str | None = None


class GrantConsentRequest(BaseModel):
    categories: list[str] = Field(..., min_length=1)
    consent_text_version: str = Field(default=CONSENT_TEXT_VERSION)


class RevokeDeviceRequest(BaseModel):
    reason: str = Field(default="Revoked by administrator", min_length=1, max_length=2000)


# --------------------------------------------------------------------------
# Public / Preview Endpoints
# --------------------------------------------------------------------------

@router.get("/consent-categories")
async def get_consent_categories() -> dict:
    """Returns all available consent categories and version disclosure."""
    return {
        "version": CONSENT_TEXT_VERSION,
        "categories": list(CONSENT_CATEGORIES.values()),
    }


@router.get("/enrollment-tokens/{token}/preview")
async def preview_enrollment_token(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Preview enrollment token for the consent screen."""
    token_hash = _hash_token(token)
    row = (
        await db.execute(
            select(DeviceEnrollment, Asset, Organization)
            .join(Asset, Asset.id == DeviceEnrollment.asset_id)
            .join(Organization, Organization.id == DeviceEnrollment.organization_id)
            .where(DeviceEnrollment.token_hash == token_hash)
        )
    ).first()

    if row is None:
        raise _err("token_not_found", "Enrollment token is invalid or does not exist.", 404)

    enrollment, asset, org = row
    now_utc = datetime.now(timezone.utc)
    if enrollment.status == "revoked":
        raise _err("token_revoked", "This device enrollment has been revoked.", 410)
    if enrollment.expires_at < now_utc:
        raise _err("token_expired", "This enrollment token has expired (30-minute limit).", 410)
    if enrollment.status == "enrolled":
        raise _err("token_already_enrolled", "This device has already been enrolled.", 409)

    return {
        "token_prefix": enrollment.token_prefix,
        "status": enrollment.status,
        "expires_at": enrollment.expires_at.isoformat(),
        "organization_name": org.name,
        "asset": {
            "id": str(asset.id),
            "name": asset.name,
            "asset_type": asset.asset_type.value if hasattr(asset.asset_type, "value") else str(asset.asset_type),
            "operating_system": asset.operating_system or enrollment.operating_system,
        },
        "consent_version": CONSENT_TEXT_VERSION,
        "categories": list(CONSENT_CATEGORIES.values()),
    }


@router.post("/enrollment-tokens/{token}/consent")
async def submit_token_consent(
    token: str,
    payload: GrantConsentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_active_organization),
) -> dict:
    """
    Submits user consent for an enrollment token.
    Records an immutable row in consent_records. Platform SOC can NEVER consent.
    """
    if scope.account_type == "admin" and scope.organization_id is None:
        raise _err("platform_soc_forbidden", "Platform SOC cannot grant device consent.", 403)
    if scope.role == AdminLevel.platform_soc_analyst.value:
        raise _err("platform_soc_forbidden", "Platform SOC cannot grant device consent.", 403)

    # Validate categories
    invalid = [c for c in payload.categories if c not in ALL_CATEGORY_KEYS]
    if invalid:
        raise _err("invalid_categories", f"Unknown consent categories: {', '.join(invalid)}", 400)

    token_hash = _hash_token(token)
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

    if enrollment.organization_id != scope.organization_id:
        raise _err("token_not_found", "Enrollment token does not exist.", 404)
    if enrollment.status == "revoked":
        raise _err("token_revoked", "This device enrollment has been revoked.", 410)
    if enrollment.expires_at < now_utc:
        raise _err("token_expired", "This enrollment token has expired.", 410)

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Create immutable consent record
    consent = ConsentRecord(
        organization_id=enrollment.organization_id,
        asset_id=enrollment.asset_id,
        account_type=scope.account_type,
        account_id=scope.account.id,
        categories_granted=payload.categories,
        consent_text_version=payload.consent_text_version,
        ip=client_ip,
        user_agent=user_agent,
    )
    db.add(consent)
    await db.flush()

    enrollment.consent_record_id = consent.id

    await audit_from_scope(
        db,
        scope,
        action="device.consent_granted",
        target_type="device",
        target_id=enrollment.id,
        after={
            "asset_id": str(asset.id),
            "asset_name": asset.name,
            "categories": payload.categories,
            "version": payload.consent_text_version,
        },
    )
    await db.commit()

    return {
        "status": "consent_recorded",
        "consent_id": str(consent.id),
        "asset_id": str(asset.id),
        "categories_granted": payload.categories,
        "message": "Consent recorded. The device agent may now be enrolled.",
    }


# --------------------------------------------------------------------------
# Authenticated Management Endpoints
# --------------------------------------------------------------------------

@router.get("")
async def list_devices(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_module("device_agents", write=False)),
    organization_id: uuid.UUID | None = Query(default=None),
) -> dict:
    """Lists devices for the organization with live health status."""
    target_org_id = scope.organization_id or organization_id
    if target_org_id is None:
        raise _err("organization_required", "organization_id is required for platform accounts.", 400)

    # If platform SOC viewing managed org, verify visibility
    if scope.organization_id is None:
        from app.access import soc_visible_organization_ids
        visible = await soc_visible_organization_ids(db, scope)
        if target_org_id not in visible:
            raise _err("organization_not_found", "Organization not found.", 404)

    now_utc = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(DeviceEnrollment, Asset, ConsentRecord)
            .join(Asset, Asset.id == DeviceEnrollment.asset_id)
            .outerjoin(ConsentRecord, ConsentRecord.id == DeviceEnrollment.consent_record_id)
            .where(DeviceEnrollment.organization_id == target_org_id)
            .order_by(DeviceEnrollment.created_at.desc())
        )
    ).all()

    devices = []
    for enrollment, asset, consent in rows:
        status = compute_device_status(enrollment, consent, now_utc)
        devices.append({
            "id": str(enrollment.id),
            "asset_id": str(asset.id),
            "asset_name": asset.name,
            "asset_type": asset.asset_type.value if hasattr(asset.asset_type, "value") else str(asset.asset_type),
            "hostname": asset.hostname,
            "ip_address": asset.ip_address,
            "status": status,
            "raw_status": enrollment.status,
            "device_name": enrollment.device_name or asset.name,
            "operating_system": enrollment.operating_system or asset.operating_system,
            "agent_version": enrollment.agent_version,
            "last_seen_at": enrollment.last_seen_at.isoformat() if enrollment.last_seen_at else None,
            "last_heartbeat_at": enrollment.last_heartbeat_at.isoformat() if enrollment.last_heartbeat_at else None,
            "categories_granted": consent.categories_granted if (consent and consent.revoked_at is None) else [],
            "created_at": enrollment.created_at.isoformat() if enrollment.created_at else None,
        })

    return {"devices": devices}


@router.get("/summary")
async def devices_summary(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_active_organization),
    organization_id: uuid.UUID | None = Query(default=None),
) -> dict:
    """Summary counts for SOC and IT overview widgets."""
    target_org_id = scope.organization_id or organization_id
    if target_org_id is None:
        raise _err("organization_required", "organization_id is required.", 400)

    now_utc = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(DeviceEnrollment, ConsentRecord)
            .outerjoin(ConsentRecord, ConsentRecord.id == DeviceEnrollment.consent_record_id)
            .where(DeviceEnrollment.organization_id == target_org_id)
        )
    ).all()

    counts = {"connected": 0, "stale": 0, "offline": 0, "revoked": 0, "pending_consent": 0, "total": len(rows)}
    for enrollment, consent in rows:
        st = compute_device_status(enrollment, consent, now_utc)
        if st in counts:
            counts[st] += 1

    return counts


@router.post("/enrollment-tokens")
async def create_enrollment_token(
    payload: CreateEnrollmentTokenRequest,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_active_organization),
) -> dict:
    """Mints a single-use 30-minute enrollment token for an asset."""
    if not await _can_manage_devices(db, scope):
        raise _err("forbidden", "Only owners, security managers, or authorized IT developers can create enrollment tokens.", 403)

    asset = await db.get(Asset, payload.asset_id)
    if asset is None or asset.organization_id != scope.organization_id:
        raise _err("asset_not_found", "Asset not found.", 404)

    token, token_hash, prefix = _generate_enrollment_token()
    now_utc = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(minutes=30)

    enrollment = DeviceEnrollment(
        organization_id=scope.organization_id,
        asset_id=asset.id,
        token_hash=token_hash,
        token_prefix=prefix,
        status="pending_consent",
        expires_at=expires_at,
        device_name=payload.device_name or asset.name,
        operating_system=payload.operating_system or asset.operating_system,
        created_by_account_type=scope.account_type,
        created_by_account_id=scope.account.id,
    )
    db.add(enrollment)

    await audit_from_scope(
        db,
        scope,
        action="device.enrollment_token_created",
        target_type="device",
        target_id=enrollment.id,
        after={
            "asset_id": str(asset.id),
            "asset_name": asset.name,
            "token_prefix": prefix,
            "expires_at": expires_at.isoformat(),
        },
    )
    await db.commit()

    return {
        "id": str(enrollment.id),
        "token": token,
        "token_prefix": prefix,
        "expires_at": expires_at.isoformat(),
        "asset_id": str(asset.id),
        "asset_name": asset.name,
        "enrollment_url": f"/consent/enroll?token={token}",
    }


@router.get("/{id}")
async def get_device_detail(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_module("device_agents", write=False)),
) -> dict:
    """Returns device detail, active categories, and full immutable consent history."""
    row = (
        await db.execute(
            select(DeviceEnrollment, Asset, ConsentRecord)
            .join(Asset, Asset.id == DeviceEnrollment.asset_id)
            .outerjoin(ConsentRecord, ConsentRecord.id == DeviceEnrollment.consent_record_id)
            .where(DeviceEnrollment.id == id)
        )
    ).first()

    if row is None:
        raise _err("device_not_found", "Device not found.", 404)

    enrollment, asset, active_consent = row
    if scope.organization_id and enrollment.organization_id != scope.organization_id:
        raise _err("device_not_found", "Device not found.", 404)

    # Fetch all consent records for this asset
    consent_rows = (
        await db.execute(
            select(ConsentRecord)
            .where(ConsentRecord.asset_id == enrollment.asset_id)
            .order_by(ConsentRecord.consented_at.desc())
        )
    ).scalars().all()

    now_utc = datetime.now(timezone.utc)
    status = compute_device_status(enrollment, active_consent, now_utc)

    return {
        "id": str(enrollment.id),
        "organization_id": str(enrollment.organization_id),
        "asset": {
            "id": str(asset.id),
            "name": asset.name,
            "hostname": asset.hostname,
            "ip_address": asset.ip_address,
            "asset_type": asset.asset_type.value if hasattr(asset.asset_type, "value") else str(asset.asset_type),
            "criticality": asset.criticality.value if hasattr(asset.criticality, "value") else str(asset.criticality),
            "operating_system": asset.operating_system,
        },
        "status": status,
        "raw_status": enrollment.status,
        "device_name": enrollment.device_name,
        "operating_system": enrollment.operating_system,
        "agent_version": enrollment.agent_version,
        "last_seen_at": enrollment.last_seen_at.isoformat() if enrollment.last_seen_at else None,
        "last_heartbeat_at": enrollment.last_heartbeat_at.isoformat() if enrollment.last_heartbeat_at else None,
        "enrolled_at": enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else None,
        "active_consent": {
            "id": str(active_consent.id),
            "categories": active_consent.categories_granted,
            "version": active_consent.consent_text_version,
            "consented_at": active_consent.consented_at.isoformat(),
        } if (active_consent and active_consent.revoked_at is None) else None,
        "consent_history": [
            {
                "id": str(c.id),
                "account_type": c.account_type,
                "account_id": str(c.account_id),
                "categories": c.categories_granted,
                "version": c.consent_text_version,
                "ip": c.ip,
                "consented_at": c.consented_at.isoformat(),
                "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
                "revocation_reason": c.revocation_reason,
            }
            for c in consent_rows
        ],
    }


@router.post("/{id}/revoke")
async def revoke_device(
    id: uuid.UUID,
    payload: RevokeDeviceRequest,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_active_organization),
) -> dict:
    """Revokes device and its consent. Immediately halts event ingestion."""
    if not await _can_manage_devices(db, scope):
        raise _err("forbidden", "Only owners, security managers, or authorized IT developers can revoke devices.", 403)

    enrollment = await db.get(DeviceEnrollment, id)
    if enrollment is None or enrollment.organization_id != scope.organization_id:
        raise _err("device_not_found", "Device not found.", 404)

    now_utc = datetime.now(timezone.utc)
    enrollment.status = "revoked"

    # Revoke API key if present
    if enrollment.api_key_id:
        api_key = await db.get(ApiKey, enrollment.api_key_id)
        if api_key and api_key.revoked_at is None:
            api_key.revoked_at = now_utc

    # Disable event source if present
    if enrollment.event_source_id:
        source = await db.get(EventSource, enrollment.event_source_id)
        if source:
            source.status = "disabled"

    # Revoke active consent record if present
    if enrollment.consent_record_id:
        consent = await db.get(ConsentRecord, enrollment.consent_record_id)
        if consent and consent.revoked_at is None:
            consent.revoked_at = now_utc
            consent.revoked_by_account_type = scope.account_type
            consent.revoked_by_account_id = scope.account.id
            consent.revocation_reason = payload.reason

    await audit_from_scope(
        db,
        scope,
        action="device.revoked",
        target_type="device",
        target_id=enrollment.id,
        after={"reason": payload.reason},
    )
    await db.commit()

    return {"status": "revoked", "device_id": str(enrollment.id)}


@router.post("/{id}/consent")
async def update_device_consent(
    id: uuid.UUID,
    payload: GrantConsentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_active_organization),
) -> dict:
    """Updates device consent. Writes a NEW consent record; never mutates past records."""
    if not await _can_manage_devices(db, scope):
        raise _err("forbidden", "Only owners, security managers, or authorized IT developers can update consent.", 403)

    enrollment = await db.get(DeviceEnrollment, id)
    if enrollment is None or enrollment.organization_id != scope.organization_id:
        raise _err("device_not_found", "Device not found.", 404)

    now_utc = datetime.now(timezone.utc)

    # Revoke previous consent record
    if enrollment.consent_record_id:
        prev = await db.get(ConsentRecord, enrollment.consent_record_id)
        if prev and prev.revoked_at is None:
            prev.revoked_at = now_utc
            prev.revoked_by_account_type = scope.account_type
            prev.revoked_by_account_id = scope.account.id
            prev.revocation_reason = "superseded_by_consent_update"

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Create new consent record
    new_consent = ConsentRecord(
        organization_id=enrollment.organization_id,
        asset_id=enrollment.asset_id,
        account_type=scope.account_type,
        account_id=scope.account.id,
        categories_granted=payload.categories,
        consent_text_version=payload.consent_text_version,
        ip=client_ip,
        user_agent=user_agent,
    )
    db.add(new_consent)
    await db.flush()

    enrollment.consent_record_id = new_consent.id

    await audit_from_scope(
        db,
        scope,
        action="device.consent_updated",
        target_type="device",
        target_id=enrollment.id,
        after={"categories": payload.categories, "version": payload.consent_text_version},
    )
    await db.commit()

    return {
        "status": "updated",
        "consent_id": str(new_consent.id),
        "categories_granted": payload.categories,
    }
