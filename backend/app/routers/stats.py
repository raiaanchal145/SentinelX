"""
Dashboard stats endpoints.

Split out of app/main.py. GET /stats/overview used to return
platform-wide counts to anyone merely authenticated -- a real
tenant-isolation gap on top of the missing auth check: an
organization_admin (or any `users` account) could see every
organization's user/asset counts, not just their own. It's now scoped
through app/scope.py: a super_admin still gets the platform-wide totals
(organization_id=None means "all"), everyone else gets counts for their
own organization only, and "organizations" becomes 1 (their own) rather
than the platform total.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Asset, Organization, User
from app.scope import Scope, org_scope, scoped_to_org

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("/overview")
async def stats_overview(
    db: AsyncSession = Depends(get_db),
    scope: Scope = Depends(org_scope),
):
    """Real counts pulled straight from the database, for the dashboard stat cards.

    `users` counts now exclude admins (they moved to their own table).
    admins isn't in this response -- the dashboard cards this feeds were
    built around "how many analysts/assets/orgs" and don't have an admin
    card yet. The full pipeline tables (alerts/incidents/tickets/...) exist
    as of this migration but have no endpoints yet, so they're still left
    out here rather than always reporting 0.
    """
    users_count = (
        await db.execute(scoped_to_org(select(func.count(User.id)), User, scope))
    ).scalar()
    # Retired assets are excluded to match compute_org_counts() in
    # app/org_summary.py (the owner dashboard's and platform admin's
    # "Assets" count) -- the two surfaces must agree on what a count
    # means, and a soft-deleted (retired) asset is not inventory anymore.
    assets_count = (
        await db.execute(
            scoped_to_org(
                select(func.count(Asset.id)).where(Asset.status != "retired"), Asset, scope
            )
        )
    ).scalar()

    if scope.organization_id is None:
        organizations_count = (await db.execute(select(func.count(Organization.id)))).scalar()
    else:
        # Organization's own primary key IS the organization id, so the
        # scoped count is just "does my organization exist" -- see the
        # same note in app/routers/organizations.py.
        organizations_count = 1

    return {
        "users": users_count,
        "assets": assets_count,
        "organizations": organizations_count,
    }
