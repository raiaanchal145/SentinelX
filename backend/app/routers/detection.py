"""
Detection rules API (P23, docs/API_CONTRACT.md "Detection rules").

GET    /api/v1/detection/rules        -- module `soc` read: the built-in
                                      rules plus this organization's own
                                      (custom rules arrive in P24), each
                                      row carrying the organization's
                                      EFFECTIVE enabled state.
PATCH  /api/v1/detection/rules/{id}/enabled -- the organization owner
                                      (organization_admin) or a
                                      security_manager toggles a rule for
                                      their organization; audited
                                      (detection_rule.enable /
                                      detection_rule.disable).

Custom rule creation is deliberately NOT here (P24): this router only
reads rules and flips per-organization settings. Platform accounts are
rejected -- a per-organization read view belongs on an admin-side
endpoint in a later milestone (same convention as event sources).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_active_organization
from app.audit import audit_from_scope
from app.database import get_db
from app.models import DetectionRule, OrganizationRuleSetting, UserRole
from app.scope import Scope

router = APIRouter(prefix="/api/v1/detection", tags=["detection"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def require_detection_write(
    scope: Scope = Depends(require_active_organization),
) -> Scope:
    """The event-sources guard pattern: minting/toggling detections is
    security administration, not soc-write -- owner + security_manager
    only (docs/DECISIONS.md)."""
    if scope.organization_id is None:
        raise _err("platform_admin_not_supported", "Platform accounts cannot manage detection rules here.", 403)
    if scope.account_type == "admin":
        return scope  # organization_admin
    if scope.role == UserRole.security_manager.value:
        return scope
    raise _err(
        "detection_rules_write_required",
        "Only the organization owner or a security manager can manage detection rules.",
        403,
    )


async def _rule_for_organization(db: AsyncSession, rule_id: uuid.UUID, scope: Scope) -> DetectionRule:
    """The rule the caller may act on: a built-in (org NULL) or their
    own organization's rule. Anything else is 404 -- existence is never
    leaked across organizations."""
    rule = (
        await db.execute(
            select(DetectionRule).where(
                DetectionRule.id == rule_id,
                (DetectionRule.organization_id.is_(None)) | (DetectionRule.organization_id == scope.organization_id),
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        raise _err("detection_rule_not_found", "Detection rule not found.", 404)
    return rule


def _row(rule: DetectionRule, effective_enabled: bool) -> dict:
    return {
        "id": str(rule.id),
        "name": rule.name,
        "description": rule.description,
        "rule_type": rule.rule_type.value if hasattr(rule.rule_type, "value") else rule.rule_type,
        "condition": rule.condition,
        "severity": rule.severity.value if hasattr(rule.severity, "value") else rule.severity,
        "mitre_technique": rule.mitre_technique,
        "builtin": rule.organization_id is None,
        # The rule row's own flag (what seeding wrote); the effective
        # flag layers the organization's override on top.
        "default_enabled": rule.enabled,
        "enabled": effective_enabled,
        "organization_id": str(rule.organization_id) if rule.organization_id else None,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


@router.get("/rules")
async def list_rules(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_active_organization),
) -> dict:
    """Built-in + this organization's own rules with the organization's
    effective enabled state. The `condition` definitions are included so
    the UI (and tests) can show exactly what each rule matches."""
    if scope.organization_id is None:
        raise _err("platform_admin_not_supported", "Platform accounts cannot read detection rules here.", 403)

    rules = (
        (
            await db.execute(
                select(DetectionRule).where(
                    (DetectionRule.organization_id.is_(None))
                    | (DetectionRule.organization_id == scope.organization_id)
                )
            )
        )
        .scalars()
        .all()
    )
    settings_rows = (
        (
            await db.execute(
                select(OrganizationRuleSetting).where(
                    OrganizationRuleSetting.organization_id == scope.organization_id
                )
            )
        )
        .scalars()
        .all()
    )
    overrides = {row.rule_id: row.enabled for row in settings_rows}

    rows = [
        _row(rule, overrides.get(rule.id, rule.enabled))
        for rule in sorted(rules, key=lambda r: r.name)
    ]
    return {"rules": rows}


class EnabledPatch(BaseModel):
    enabled: bool


@router.patch("/rules/{rule_id}/enabled")
async def patch_rule_enabled(
    rule_id: uuid.UUID,
    payload: EnabledPatch,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_detection_write),
) -> dict:
    """Enable/disable a rule FOR THIS ORGANIZATION. Never touches the
    rule row itself (that's platform data shared by everyone); the
    override lives in organization_rule_settings, so the caller's
    choice survives re-seeding and other organizations are unaffected.
    Audited."""
    rule = await _rule_for_organization(db, rule_id, scope)

    setting = (
        await db.execute(
            select(OrganizationRuleSetting).where(
                OrganizationRuleSetting.organization_id == scope.organization_id,
                OrganizationRuleSetting.rule_id == rule.id,
            )
        )
    ).scalar_one_or_none()

    before = {"enabled": setting.enabled if setting else rule.enabled}
    if setting is None:
        setting = OrganizationRuleSetting(
            organization_id=scope.organization_id,
            rule_id=rule.id,
            enabled=payload.enabled,
            updated_by_admin_id=scope.user_id if scope.account_type == "admin" else None,
        )
        db.add(setting)
    else:
        setting.enabled = payload.enabled
        setting.updated_by_admin_id = scope.user_id if scope.account_type == "admin" else None
    await db.commit()

    await audit_from_scope(
        db,
        scope,
        "detection_rule.enable" if payload.enabled else "detection_rule.disable",
        target_type="detection_rule",
        target_id=rule.id,
        before=before,
        after={"enabled": payload.enabled},
    )
    await db.commit()

    return {"id": str(rule.id), "name": rule.name, "enabled": payload.enabled}
