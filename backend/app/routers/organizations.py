"""
Legacy organization endpoints, superseded by the platform/owner surfaces
in admin_organizations.py and organization.py but kept for whatever
still points at them.

Both are now super_admin-only: an organization owner reads their own
organization through GET /organization (organization.py), and a
platform admin manages every organization through /admin/organizations
(admin_organizations.py) -- there is no remaining legitimate caller for
"list every organization" or "create a bare organization with no owner"
below super_admin. GET used to return every organization in the
platform to anyone merely authenticated (a real tenant-isolation gap,
fixed once already by scoping it to the caller's own organization); it's
now closed further per the spec's "no anonymous endpoint may list
organizations" -- scoped is still one org too many for a non-platform
caller to reach through this path when a dedicated one exists.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import require_super_admin, seed_default_modules
from app.database import get_db
from app.models import Organization
from app.scope import Scope

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
    scope: Scope = Depends(require_super_admin),
):
    """
    super_admin-only. Creates an already-active, platform-created
    organization with every module enabled and no owner -- prefer
    POST /admin/organizations, which also sends the owner an
    invitation; this bare version is kept only for compatibility.
    """
    org = Organization(
        name=payload.name,
        industry=payload.industry,
        environment=payload.environment,
        timezone=payload.timezone,
        created_by_admin_id=scope.account.id,
        created_via="platform_admin",
    )
    db.add(org)
    await db.flush()
    await seed_default_modules(db, org.id)
    await db.commit()
    await db.refresh(org)
    return OrganizationOut(
        id=str(org.id),
        name=org.name,
        industry=org.industry,
        environment=org.environment,
        timezone=org.timezone,
        status=org.status.value,
    )


@router.get("")
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(require_super_admin),
):
    stmt = select(Organization).order_by(Organization.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(org.id),
            "name": org.name,
            "industry": org.industry,
            "environment": org.environment,
            "timezone": org.timezone,
            "status": org.status.value,
            "created_at": org.created_at.isoformat() if org.created_at else None,
        }
        for org in rows
    ]
