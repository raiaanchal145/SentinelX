"""
Organization endpoints.

Split out of app/main.py. Both endpoints now go through app/scope.py:

- POST requires an admin (require_admin) and records the creator, same
  as before.
- GET used to return every organization in the platform to anyone
  merely authenticated -- a real tenant-isolation gap, since an
  organization_admin (or any `users` account) could see every other
  organization's name/industry/environment. It's now filtered by the
  caller's own organization_id: a super_admin still sees all of them,
  everyone else sees only their own.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Organization
from app.scope import Scope, org_scope, require_admin

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
    scope: Scope = Depends(require_admin),
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
        created_by_admin_id=scope.account.id,
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
    scope: Scope = Depends(org_scope),
):
    # scoped_to_org() doesn't apply here: it filters child tables by their
    # organization_id foreign key, but Organization's own primary key IS
    # the organization id -- so the equivalent filter is `Organization.id
    # == scope.organization_id` directly, not scoped_to_org().
    stmt = select(Organization).order_by(Organization.created_at.desc())
    if scope.organization_id is not None:
        stmt = stmt.where(Organization.id == scope.organization_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(org.id),
            "name": org.name,
            "industry": org.industry,
            "environment": org.environment,
            "timezone": org.timezone,
            "status": org.status,
            "created_at": org.created_at.isoformat() if org.created_at else None,
        }
        for org in rows
    ]
