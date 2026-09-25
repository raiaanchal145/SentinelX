from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.routers import (
    admin_organizations,
    admin_soc,
    assets,
    auth,
    detection,
    event_sources,
    events,
    invitations,
    organization,
    stats,
)

app = FastAPI(title="SentinelX API")

# Allows the React dev server (Vite, running on port 5173) to call this API
# directly from the browser during development.
#
# Dev sharing (npm run dev:share) may add extra origins (a LAN IP or a
# tunnel URL) via the DEV_SHARE_ORIGINS env var for that one session. The
# extras are applied only when ENV=dev -- never a wildcard, and a non-
# allow-listed origin stays rejected even while sharing is active (see
# tests/test_cors.py).
def _cors_allow_origins() -> list[str]:
    if settings.env.lower() != "dev":
        return ["http://localhost:5173"]
    origins = ["http://localhost:5173"]
    for chunk in settings.dev_share_origins.split(","):
        origin = chunk.strip().rstrip("/")
        # "*" is refused explicitly -- sharing is opt-in per origin, never
        # an open proxy for any site.
        if origin and origin != "*" and origin not in origins:
            origins.append(origin)
    return origins


def configure_cors(target: FastAPI) -> None:
    """Applies the CORS middleware with the current allow-list. A function
    (not inline) so tests can build a scratch app with exactly the same
    configuration instead of mutating the real app's middleware stack."""
    target.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allow_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


configure_cors(app)


@app.middleware("http")
async def add_security_headers(request, call_next):
    """Basic hardening headers applied to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/api/v1/health")
async def health(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    return {"status": "ok", "db": result.scalar() == 1}


app.include_router(auth.router)
app.include_router(stats.router)
app.include_router(admin_organizations.router)
app.include_router(admin_soc.router)
app.include_router(organization.router)
app.include_router(invitations.router)
app.include_router(assets.router)
app.include_router(event_sources.router)
app.include_router(events.router)
app.include_router(detection.router)
