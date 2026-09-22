"""
CORS behaviour around the dev-sharing feature (npm run dev:share).

The launcher sets DEV_SHARE_ORIGINS for one session when a LAN IP or a
cloudflared tunnel URL is active; main.py folds those into the allow-list
ONLY when ENV=dev, on top of the permanent localhost origin. Pinned here:

- the share origin IS allowed while sharing is active (so a phone on the
  LAN can talk to the API directly, if it ever bypasses the Vite proxy);
- any OTHER origin stays rejected even while sharing is active -- sharing
  never widens the list beyond the origins the launcher chose, and
  "*" must never appear;
- with no share origins set (plain npm run dev) the list is exactly what
  it always was.
"""

from fastapi import FastAPI

from app.main import _cors_allow_origins, app, configure_cors


def test_default_allow_list_is_localhost_only(monkeypatch):
    monkeypatch.setattr("app.config.settings.dev_share_origins", "")
    assert _cors_allow_origins() == ["http://localhost:5173"]


def test_share_origin_is_added_in_dev(monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.dev_share_origins",
        "http://192.168.1.20:5173",
    )
    origins = _cors_allow_origins()
    assert origins == ["http://localhost:5173", "http://192.168.1.20:5173"]


def test_share_origins_parse_comma_list_and_strip(monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.dev_share_origins",
        " http://192.168.1.20:5173 , https://demo.example.trycloudflare.com/ ,",
    )
    origins = _cors_allow_origins()
    assert origins == [
        "http://localhost:5173",
        "http://192.168.1.20:5173",
        "https://demo.example.trycloudflare.com",
    ]


def test_wildcard_is_never_accepted(monkeypatch):
    monkeypatch.setattr("app.config.settings.dev_share_origins", "*")
    assert "*" not in _cors_allow_origins()


async def test_unknown_origin_rejected_even_while_sharing(client, monkeypatch):
    """A preflight from an origin the launcher never chose must get no
    CORS grant -- sharing is opt-in per origin, not a wildcard."""
    monkeypatch.setattr(
        "app.config.settings.dev_share_origins",
        "http://192.168.1.20:5173",
    )    # CORSMiddleware snapshots allow_origins when it's added, so build a
    # scratch app carrying the same configuration the real app gets with
    # sharing active (mutating the real app's stack after it has served
    # requests is not allowed).
    scratch = FastAPI()
    configure_cors(scratch)

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=scratch), base_url="http://test") as scratch_client:
        stranger = await scratch_client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in stranger.headers

        shared = await scratch_client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://192.168.1.20:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert shared.headers.get("access-control-allow-origin") == "http://192.168.1.20:5173"
