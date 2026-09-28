"""
Assignment rules API (P13, minimal CRUD per the milestone decision):
the organization's owner or security_manager manages the rules the
auto-assign engine walks in priority_order. Rule bodies are the same
condition shape as detection's: [{field, op, value}] over ticket
columns (severity, priority, category, asset_criticality), with op
eq|ne|in.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_from_scope
from app.database import get_db
from app.models import AssignmentRule, Team, UserRole
from app.scope import Scope, org_scope

router = APIRouter(prefix="/api/v1/assignment-rules", tags=["assignment-rules"])

VALID_FIELDS = {"severity", "priority", "category", "asset_criticality"}
VALID_OPS = {"eq", "ne", "in"}


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def _rules_gate(
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(org_scope)
) -> Scope:
    """Minting assignment rules is security administration (the
    event-sources guard pattern): owner or security_manager only."""
    if scope.account_type == "admin":
        if scope.role == "organization_admin":
            return scope
        raise _err("assignment_rules_write_required", "Only the owner or security manager manage assignment rules.", 403)
    if scope.role == UserRole.security_manager.value:
        return scope
    raise _err("assignment_rules_write_required", "Only the owner or security manager manage assignment rules.", 403)


def _row(r: AssignmentRule) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "match_conditions": r.match_conditions,
        "assign_to_team_id": str(r.assign_to_team_id) if r.assign_to_team_id else None,
        "priority_order": r.priority_order,
        "enabled": r.enabled,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


class RulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    match_conditions: list[dict]
    assign_to_team_id: uuid.UUID
    priority_order: int = Field(default=0, ge=0, le=10000)
    enabled: bool = True

    @field_validator("match_conditions")
    @classmethod
    def _conditions_shape(cls, value: list[dict]) -> list[dict]:
        if not value:
            raise ValueError("at least one condition is required")
        for cond in value:
            if cond.get("field") not in VALID_FIELDS or cond.get("op") not in VALID_OPS:
                raise ValueError(
                    "each condition needs field in " + str(sorted(VALID_FIELDS))
                    + " and op in " + str(sorted(VALID_OPS))
                )
        return value


@router.get("")
async def list_rules(
    db: AsyncSession = Depends(get_db), scope: Scope = Depends(_rules_gate)
):
    rows = (
        await db.execute(
            select(AssignmentRule)
            .where(AssignmentRule.organization_id == scope.organization_id)
            .order_by(AssignmentRule.priority_order, AssignmentRule.created_at)
        )
    ).scalars().all()
    return {"assignment_rules": [_row(r) for r in rows]}


@router.post("", status_code=201)
async def create_rule(
    payload: RulePayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_rules_gate),
):
    team = (
        await db.execute(
            select(Team).where(
                Team.id == payload.assign_to_team_id,
                Team.organization_id == scope.organization_id,
            )
        )
    ).scalar_one_or_none()
    if team is None:
        raise _err("team_not_found", "Team not found in this organization.", 404)

    rule = AssignmentRule(
        organization_id=scope.organization_id,
        name=payload.name,
        match_conditions=payload.match_conditions,
        assign_to_team_id=team.id,
        priority_order=payload.priority_order,
        enabled=payload.enabled,
    )
    db.add(rule)
    await audit_from_scope(
        db, scope, "assignment_rule.create",
        target_type="assignment_rule", target_id=rule.id,
        after={"name": rule.name, "priority_order": rule.priority_order},
    )
    await db.commit()
    await db.refresh(rule)
    return _row(rule)


class RulePatchPayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    assign_to_team_id: uuid.UUID | None = None
    priority_order: int | None = Field(default=None, ge=0, le=10000)
    enabled: bool | None = None


@router.patch("/{rule_id}")
async def patch_rule(
    rule_id: uuid.UUID,
    payload: RulePatchPayload,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_rules_gate),
):
    rule = (
        await db.execute(
            select(AssignmentRule).where(
                AssignmentRule.id == rule_id,
                AssignmentRule.organization_id == scope.organization_id,
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        raise _err("assignment_rule_not_found", "Assignment rule not found.", 404)

    if payload.name is not None:
        rule.name = payload.name
    if payload.priority_order is not None:
        rule.priority_order = payload.priority_order
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    if payload.assign_to_team_id is not None:
        team = (
            await db.execute(
                select(Team).where(
                    Team.id == payload.assign_to_team_id,
                    Team.organization_id == scope.organization_id,
                )
            )
        ).scalar_one_or_none()
        if team is None:
            raise _err("team_not_found", "Team not found in this organization.", 404)
        rule.assign_to_team_id = team.id

    await audit_from_scope(
        db, scope, "assignment_rule.update",
        target_type="assignment_rule", target_id=rule.id,
        after={"name": rule.name, "enabled": rule.enabled},
    )
    await db.commit()
    await db.refresh(rule)
    return _row(rule)


class RulePatchPayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    assign_to_team_id: uuid.UUID | None = None
    priority_order: int | None = Field(default=None, ge=0, le=10000)
    enabled: bool | None = None


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(_rules_gate),
):
    rule = (
        await db.execute(
            select(AssignmentRule).where(
                AssignmentRule.id == rule_id,
                AssignmentRule.organization_id == scope.organization_id,
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        raise _err("assignment_rule_not_found", "Assignment rule not found.", 404)
    await db.delete(rule)
    await audit_from_scope(
        db, scope, "assignment_rule.delete",
        target_type="assignment_rule", target_id=rule.id,
        before={"name": rule.name},
    )
    await db.commit()
