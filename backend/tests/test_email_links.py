"""
Invitation links must be built from settings.frontend_url at send time --
never from a baked-in constant -- so the dev launcher's share mode can
repoint every emailed link at the LAN IP / tunnel URL for one session
(FRONTEND_URL env var), and a teammate's phone can open the invitation.

(Why a test for a one-line f-string: the launcher can only make email
links reachable if EVERY invite-creation path reads the setting when it
sends. Pinning it here means a future call site that hardcodes
localhost instead of calling build_invite_link() fails the suite.)
"""

from datetime import datetime, timezone

from app.config import settings
from app.email_utils import send_invitation_email
from app.invite_service import build_invite_link


def _any_expiry():
    return datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_invite_link_reflects_frontend_url_at_send_time(monkeypatch):
    """The launcher changes FRONTEND_URL per session; the built link must
    follow without any code change."""
    monkeypatch.setattr(settings, "frontend_url", "http://192.168.1.20:5173")
    link = build_invite_link("tok123")
    assert link == "http://192.168.1.20:5173/accept-invite?token=tok123"

    monkeypatch.setattr(settings, "frontend_url", "https://demo.example.trycloudflare.com")
    assert build_invite_link("tok123") == "https://demo.example.trycloudflare.com/accept-invite?token=tok123"


def test_invite_link_default_is_localhost_dev_url():
    assert build_invite_link("tok123") == "http://localhost:5173/accept-invite?token=tok123"


def test_invite_link_tolerates_trailing_slash(monkeypatch):
    monkeypatch.setattr(settings, "frontend_url", "http://192.168.1.20:5173/")
    assert "/accept-invite?token=tok123" in build_invite_link("tok123")
    assert "//accept-invite" not in build_invite_link("tok123")


def test_console_fallback_prints_the_live_link(monkeypatch, capsys):
    """No SMTP configured (the dev default): the invitation link goes to
    the backend console -- and must show the CURRENT frontend_url, so
    the printed link is the one that actually opens from another device
    while sharing is active."""
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_password", "")
    monkeypatch.setattr(settings, "frontend_url", "https://demo.example.trycloudflare.com")

    send_invitation_email(
        "newowner@example.com",
        "Acme Corp",
        "organization owner",
        build_invite_link("tok123"),
        expires_at=_any_expiry(),
    )

    out = capsys.readouterr().out
    assert "[SentinelX] SMTP not configured" in out
    assert "https://demo.example.trycloudflare.com/accept-invite?token=tok123" in out


def test_console_fallback_changes_with_frontend_url(monkeypatch, capsys):
    """Share mode off -> on: the printed link follows FRONTEND_URL at
    send time, not a constant captured at import."""
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_password", "")
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:5173")

    send_invitation_email("a@example.com", "Org", "organization owner", build_invite_link("t1"), _any_expiry())
    assert "http://localhost:5173/accept-invite?token=t1" in capsys.readouterr().out

    monkeypatch.setattr(settings, "frontend_url", "http://192.168.1.20:5173")
    send_invitation_email("a@example.com", "Org", "organization owner", build_invite_link("t2"), _any_expiry())
    assert "http://192.168.1.20:5173/accept-invite?token=t2" in capsys.readouterr().out
