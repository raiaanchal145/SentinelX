"""
Dashboard stats endpoints.

Split out of app/main.py. GET /stats/overview now requires an
authenticated account -- it used to be open to anyone, which leaked
org/user/asset counts to unauthenticated callers.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Admin, User
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("/overview")
async def stats_overview(
    db: AsyncSession = Depends(get_db),
    current_account: Admin | User = Depends(get_current_user),
):
    """Real counts pulled straight from the database, for the dashboard stat cards.

    `users` counts now exclude admins (they moved to their own table).
    admins isn't in this response -- the dashboard cards this feeds were
    built around "how many analysts/assets/orgs" and don't have an admin
    card yet. The full pipeline tables (alerts/incidents/tickets/...) exist
    as of this migration but have no endpoints yet, so they're still left
    out here rather than always reporting 0.
    """
    users_count = (await db.execute(text("SELECT COUNT(*) FROM users"))).scalar()
    assets_count = (await db.execute(text("SELECT COUNT(*) FROM assets"))).scalar()
    organizations_count = (await db.execute(text("SELECT COUNT(*) FROM organizations"))).scalar()

    return {
        "users": users_count,
        "assets": assets_count,
        "organizations": organizations_count,
    }
