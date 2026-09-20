"""
Organization endpoints.

Split out of app/main.py. GET /organizations now requires an
authenticated account (any admin or user) -- it used to be open to
anyone, which leaked every organization's name/industry/environment to
unauthenticated callers. POST already required an admin.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Admin, Organization, User
from app.routers.auth import get_current_admin, get_current_user

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


class OrganizationCreate(BaseModel):
    name: str
    industry: str | None = None
    environment: str | None = None
    timezone: str | None = None


class OrganizationOut(BaseModel):
    id: str
    name: str
    industry: str | None
    environment: str | None
    timezone: str | None
    status: str

    class Config:
        from_attributes = True



@router.post("", response_model=OrganizationOut)
async def create_organization(
    payload: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """
    Admin-only. Per the schema split, every organization should know
    which admin created it (organizations.created_by_admin_id) -- this
    endpoint used to be open with no such link; now that `admins` exists,
    it requires an authenticated admin and records them as the creator.
    """
    org = Organization(
        name=payload.name,
        industry=payload.industry,
        environment=payload.environment,
        timezone=payload.timezone,
        created_by_admin_id=current_admin.id,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return OrganizationOut(
        id=str(org.id),
        name=org.name,
        industry=org.industry,
        environment=org.environment,
        timezone=org.timezone,
        status=org.status,
    )


@router.get("")
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    current_account: Admin | User = Depends(get_current_user),
):
    result = await db.execute(
        text(
            "SELECT id, name, industry, environment, timezone, status, created_at "
            "FROM organizations ORDER BY created_at DESC"
        )
    )
    rows = result.mappings().all()
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "industry": r["industry"],
            "environment": r["environment"],
            "timezone": r["timezone"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]

