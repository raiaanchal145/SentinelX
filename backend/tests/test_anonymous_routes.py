"""
The anonymous surface of the API, enumerated. SentinelX is invite-only
(docs/DECISIONS.md): no anonymous endpoint may create an account or an
organization, or list organizations. This test walks every route in the
app and fails when an unauthenticated route appears that is not on the
allowed list -- so any future anonymous account-creation path trips the
suite, not a security review.

Allowed anonymous endpoints (docs/API_CONTRACT.md):
  login, forgot-password, reset-password, verify-email,
  resend-verification, invitations validate/accept, health.
FastAPI's own /docs, /redoc and /openapi.json are documentation, not
data; they are excluded here.

POST /api/v1/events (P07) is listed here too, but it is NOT anonymous
in practice: it authenticates with an event-source API key (P06's
get_event_source_from_api_key), which is not part of the user-token
chain this scanner recognizes. It is allow-listed with an explicit
companion test below that pins 401 without a valid key, so the route
can never silently become truly anonymous.
"""

from fastapi.routing import APIRoute

from app.main import app

ALLOWED_ANONYMOUS = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/reset-password"),
    ("POST", "/api/v1/auth/verify-email"),
    ("POST", "/api/v1/auth/resend-verification"),
    ("GET", "/api/v1/invitations/{token}"),
    ("POST", "/api/v1/invitations/accept"),
    ("GET", "/api/v1/health"),
    # Key-authenticated (not user-token) -- see the docstring + the
    # companion test pinning 401 without a valid key.
    ("POST", "/api/v1/events"),
}


def _all_dependency_names(dependant, seen: set[int] | None = None) -> set[str]:
    """Every callable name in a route's FULL dependency tree -- auth
    deps are usually wrapped (require_super_admin -> org_scope ->
    get_current_account), so the root dependency itself is nested and a
    one-level scan would misread protected routes as anonymous."""
    names: set[str] = set()
    seen = seen or set()
    if id(dependant) in seen:
        return names
    seen.add(id(dependant))
    for dep in dependant.dependencies:
        call = dep.call
        names.add(getattr(call, "__name__", repr(call)))
        names |= _all_dependency_names(dep, seen)
    return names


def _registered_paths() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue  # mounts, docs (removed below), etc.
        if route.dependant is None:
            continue
        for method in route.methods or set():
            if method == "HEAD":
                continue  # automatic HEAD mirrors of GETs
            path = route.path
            if path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
                continue
            # A route is "anonymous" when no callable anywhere in its
            # dependency tree is the auth chain root (org_scope, or
            # get_current_account directly). Every protected route in
            # this app builds on those two; anonymous ones only use get_db.
            names = _all_dependency_names(route.dependant)
            if names & {"org_scope", "get_current_account"}:
                continue
            found.add((method, path))
    return found


async def test_no_unknown_anonymous_routes_exist(client):
    found = _registered_paths()
    unexpected = found - ALLOWED_ANONYMOUS
    missing = ALLOWED_ANONYMOUS - found
    assert not unexpected, f"Anonymous routes not on the allowed list: {sorted(unexpected)}"
    assert not missing, f"Allowed anonymous routes missing from the app: {sorted(missing)}"


async def test_no_anonymous_route_creates_accounts(client):
    """The register endpoint is gone; nothing anonymous can create an
    account or an organization."""
    register = await client.post(
        "/api/v1/auth/register",
        json={"name": "Ghost", "email": "ghost@example.com", "password": "correct-horse-battery", "organization_name": "Ghost Org"},
    )
    assert register.status_code == 404

    org_create = await client.post(
        "/api/v1/organizations",
        json={"name": "Ghost Org"},
    )
    assert org_create.status_code == 404

    admin_org_create = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Ghost Org", "owner_email": "ghost@example.com", "soc_mode": "managed"},
    )
    assert admin_org_create.status_code == 401, "creating an organization must require authentication"


async def test_health_is_anonymous(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_event_ingestion_is_key_gated(client):
    """POST /api/v1/events is allow-listed above only because its auth
    is an event-source API key, not the user-token chain the scanner
    knows. This pins that it is NOT actually anonymous: garbage/missing
    keys get 401 invalid_api_key and nothing is stored."""
    resp = await client.post("/api/v1/events", json={})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "invalid_api_key"

    resp = await client.post(
        "/api/v1/events", json={}, headers={"Authorization": "Bearer sx_bogus_0000"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "invalid_api_key"
