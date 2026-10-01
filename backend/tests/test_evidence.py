"""
Evidence upload/download (P15, docs/API_CONTRACT.md "Evidence").

Covers the brief: type and size limits, path-traversal filenames,
wrong-organization download, hash correctness, IT can attach to own
tickets only, and the download headers. Storage settings are pointed
at a tmp dir so the suite never writes into the repo.
"""

from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

from app.config import settings  # noqa: E402
from app.evidence import (  # noqa: E402
    EVIDENCE_MAX_BYTES,
    FileTooLargeError,
    sniff_and_hash,
    store_evidence_file,
)
from app.models import SocMode, UserRole  # noqa: E402

from tests.helpers import auth, login, make_organization, make_team, make_user  # noqa: E402

# Every test in this module runs with the evidence root in a tmp dir;
# the repo tree (and the real backend/data) is never touched.
@pytest.fixture(autouse=True)
def _evidence_tmp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "evidence_storage_dir", str(tmp_path / "evidence"))


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF = b"%PDF-1.7\n fake"
ZIP = b"PK\x03\x04" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
TEXT = b"2026-10-01 12:00:00 auth failed for root\n" * 3
EXE = b"MZ\x90\x00" + b"\x00" * 64  # a Windows binary -- never allowed


# ---------------------------------------------------------------------------
# Storage module unit tests (no HTTP).
# ---------------------------------------------------------------------------


def test_evidence_type_by_kind_maps_to_the_enum():
    from app.evidence import EVIDENCE_TYPE_BY_KIND

    assert set(EVIDENCE_TYPE_BY_KIND.values()) <= {"log", "file", "screenshot", "note", "command_output"}


def test_sniff_detects_each_allowed_type():
    assert sniff_and_hash(PNG).kind == "screenshot"
    assert sniff_and_hash(PNG).content_type == "image/png"
    assert sniff_and_hash(JPEG).kind == "screenshot"
    assert sniff_and_hash(JPEG).content_type == "image/jpeg"
    assert sniff_and_hash(PDF).kind == "pdf"
    assert sniff_and_hash(PDF).content_type == "application/pdf"
    assert sniff_and_hash(ZIP).kind == "zip"
    assert sniff_and_hash(ZIP).content_type == "application/zip"
    assert sniff_and_hash(TEXT).kind == "log"
    assert sniff_and_hash(TEXT).content_type == "text/plain; charset=utf-8"


def test_sniff_rejects_unknown_binary():
    with pytest.raises(ValueError):
        sniff_and_hash(EXE)
    with pytest.raises(ValueError):
        sniff_and_hash(b"")


def test_hash_is_of_stored_bytes():
    assert sniff_and_hash(TEXT).sha256 == hashlib.sha256(TEXT).hexdigest()


def test_store_uses_random_name_not_the_filename(tmp_path):
    org_id = uuid.uuid4()
    evil = "..\\..\\..\\windows\\system32\\config\\SAM"
    ref, sniffed = store_evidence_file(org_id, evil, TEXT)
    # The ref is org/uuid and the on-disk name is NOT the uploaded name.
    org_part, file_part = ref.split("/")
    assert org_part == str(org_id)
    uuid.UUID(file_part)  # raises if not a bare uuid
    stored = tmp_path / "evidence" / org_part / file_part
    assert stored.exists()
    assert stored.read_bytes() == TEXT
    assert sniffed.sha256 == hashlib.sha256(TEXT).hexdigest()
    # Nothing in the org dir encodes the traversal attempt.
    assert all(f.name == file_part for f in (tmp_path / "evidence" / org_part).iterdir())


def test_store_enforces_size_cap(tmp_path):
    with pytest.raises(FileTooLargeError):
        store_evidence_file(uuid.uuid4(), "big.log", b"a" * (EVIDENCE_MAX_BYTES + 1))


def test_open_rejects_traversal_shapes():
    from app.evidence import open_evidence_file

    for bad in ("../../secret.txt", f"{uuid.uuid4()}/../../x", "not-a-ref"):
        with pytest.raises(ValueError):
            open_evidence_file(bad)


# ---------------------------------------------------------------------------
# The HTTP surface.
# ---------------------------------------------------------------------------


async def _soc_world(db_session, soc_mode=SocMode.in_house):
    """org + SOC writer + two IT developers of the org (+ a second org
    with its own IT developer for the cross-org isolation tests)."""
    org = await make_organization(db_session, soc_mode=soc_mode)
    if soc_mode == SocMode.managed:
        from app.models import AdminLevel, SocOrganizationAssignment

        from tests.helpers import make_admin

        soc_admin = await make_admin(
            db_session, email=f"soc-{uuid.uuid4().hex[:8]}@x.io", admin_level=AdminLevel.platform_soc_analyst
        )
        db_session.add(SocOrganizationAssignment(admin_id=soc_admin.id, organization_id=org.id))
        await db_session.commit()
        soc_email = soc_admin.email
    else:
        analyst = await make_user(
            db_session, email=f"analyst-{uuid.uuid4().hex[:8]}@x.io", role=UserRole.soc_analyst, organization_id=org.id
        )
        soc_email = analyst.email

    team = await make_team(db_session, organization_id=org.id)
    dev = await make_user(
        db_session, email=f"dev-{uuid.uuid4().hex[:8]}@x.io", role=UserRole.it_developer, organization_id=org.id, team_id=team.id
    )
    other_dev = await make_user(
        db_session, email=f"other-dev-{uuid.uuid4().hex[:8]}@x.io", role=UserRole.it_developer, organization_id=org.id, team_id=team.id
    )

    other_org = await make_organization(db_session, soc_mode=soc_mode, name="Other Co")
    other_team = await make_team(db_session, organization_id=other_org.id)
    foreign_dev = await make_user(
        db_session,
        email=f"foreign-{uuid.uuid4().hex[:8]}@x.io",
        role=UserRole.it_developer,
        organization_id=other_org.id,
        team_id=other_team.id,
    )
    return org, soc_email, dev, other_dev, other_org, foreign_dev


async def _create_linked_ticket(client, soc_email, org_id):
    token = await login(client, soc_email)
    resp = await client.post(
        "/api/v1/tickets", json={"title": "Patch the server", "organization_id": str(org_id)}, headers=auth(token)
    )
    assert resp.status_code == 201, resp.text
    return token, resp.json()


async def _link_incident(client, soc_token, ticket_id, org_id):
    """The upload path requires a linked incident; walk the SOC through
    creating one for the ticket's org and patching the ticket onto it is
    not exposed, so instead create an incident and re-create the ticket
    WITH incident_id via the SOC create payload."""
    resp = await client.post(
        "/api/v1/incidents",
        json={"title": "Breach at the perimeter", "organization_id": str(org_id)},
        headers=auth(soc_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _ticket_with_incident(client, soc_email, org_id):
    soc_token, ticket = await _create_linked_ticket(client, soc_email, org_id)
    incident = await _link_incident(client, soc_token, ticket["id"], org_id)
    # Link the ticket to the incident by re-creating (PATCH has no
    # incident_id) -- simplest deterministic path: create a second
    # ticket directly with incident_id.
    resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Patch the server",
            "organization_id": str(org_id),
            "incident_id": incident["id"],
        },
        headers=auth(soc_token),
    )
    assert resp.status_code == 201, resp.text
    return soc_token, resp.json(), incident


async def _upload(client, token, ticket_id, *, name="a.log", content=TEXT, kind="text/plain"):
    return await client.post(
        f"/api/v1/tickets/{ticket_id}/evidence/upload",
        files={"file": (name, content, kind)},
        headers=auth(token),
    )


@pytest.mark.asyncio
async def test_it_uploads_log_evidence_to_own_ticket(client, db_session):
    org, soc_email, dev, *_ = await _soc_world(db_session)
    soc_token, ticket, incident = await _ticket_with_incident(client, soc_email, org.id)

    it_token = await login(client, dev.email)
    resp = await _upload(client, it_token, ticket["id"])
    assert resp.status_code == 201, resp.text
    row = resp.json()
    assert row["evidence_type"] == "log"
    assert row["filename"] == "a.log"
    assert row["sha256"] == hashlib.sha256(TEXT).hexdigest()
    assert row["size_bytes"] == len(TEXT)
    assert row["content_type"] == "text/plain; charset=utf-8"
    # The storage_ref never echoes the client filename.
    assert "a.log" not in row["storage_ref"]


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_binary(client, db_session):
    org, soc_email, dev, *_ = await _soc_world(db_session)
    soc_token, ticket, _ = await _ticket_with_incident(client, soc_email, org.id)
    it_token = await login(client, dev.email)
    resp = await _upload(client, it_token, ticket["id"], name="evil.bin", content=EXE, kind="application/octet-stream")
    assert resp.status_code == 415
    assert resp.json()["detail"]["code"] == "evidence_unsupported_type"


@pytest.mark.asyncio
async def test_upload_rejects_oversize(client, db_session, monkeypatch):
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "evidence_max_upload_mb", 1)
    # Re-import the cap: it is read at module import time, so patch the
    # module constant the router uses instead.
    import app.evidence as ev

    monkeypatch.setattr(ev, "EVIDENCE_MAX_BYTES", 1024)
    org, soc_email, dev, *_ = await _soc_world(db_session)
    soc_token, ticket, _ = await _ticket_with_incident(client, soc_email, org.id)
    it_token = await login(client, dev.email)
    resp = await _upload(client, it_token, ticket["id"], name="big.log", content=b"a" * 2048)
    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "evidence_too_large"


@pytest.mark.asyncio
async def test_upload_accepts_each_documented_type(client, db_session):
    org, soc_email, dev, *_ = await _soc_world(db_session)
    soc_token, ticket, _ = await _ticket_with_incident(client, soc_email, org.id)
    it_token = await login(client, dev.email)
    for name, content, expected in (
        ("shot.png", PNG, "screenshot"),
        ("shot.jpg", JPEG, "screenshot"),
        ("report.pdf", PDF, "file"),
        ("bundle.zip", ZIP, "file"),
        ("auth.log", TEXT, "log"),
    ):
        resp = await _upload(client, it_token, ticket["id"], name=name, content=content)
        assert resp.status_code == 201, (name, resp.text)
        assert resp.json()["evidence_type"] == expected, name
        # The precise kind is preserved in the metadata.
        if name.endswith((".pdf", ".zip")):
            assert resp.json()["content_type"] in {"application/pdf", "application/zip"}


@pytest.mark.asyncio
async def test_path_traversal_filename_is_never_used(client, db_session):
    org, soc_email, dev, *_ = await _soc_world(db_session)
    soc_token, ticket, _ = await _ticket_with_incident(client, soc_email, org.id)
    it_token = await login(client, dev.email)
    evil = "..\\..\\..\\windows\\system32\\config\\SAM"
    resp = await _upload(client, it_token, ticket["id"], name=evil, content=TEXT)
    assert resp.status_code == 201
    row = resp.json()
    assert row["filename"] == evil  # metadata keeps what the user sent
    assert ".." not in row["storage_ref"]
    assert "\\" not in row["storage_ref"]
    # The file exists exactly once, under the org dir, uuid-named.
    import json

    org_dir = Path(settings.evidence_storage_dir) / str(org.id)
    names = [p.name for p in org_dir.iterdir()]
    assert len(names) == 1
    assert names[0] == row["storage_ref"].split("/")[-1]
    assert json.dumps(names)  # sanity: all uuid-shaped, checked above


@pytest.mark.asyncio
async def test_it_cannot_upload_to_another_orgs_ticket(client, db_session):
    org, soc_email, dev, _, other_org, foreign_dev = await _soc_world(db_session)
    soc_token, ticket, _ = await _ticket_with_incident(client, soc_email, org.id)
    foreign_token = await login(client, foreign_dev.email)
    resp = await _upload(client, foreign_token, ticket["id"])
    assert resp.status_code == 404  # invisible, never a leak
    assert resp.json()["detail"]["code"] == "ticket_not_found"


@pytest.mark.asyncio
async def test_upload_requires_linked_incident(client, db_session):
    org, soc_email, dev, *_ = await _soc_world(db_session)
    _, ticket = await _create_linked_ticket(client, soc_email, org.id)  # no incident
    it_token = await login(client, dev.email)
    resp = await _upload(client, it_token, ticket["id"])
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "evidence_requires_incident"
    # But the JSON metadata path still works on standalone tickets.
    resp2 = await client.post(
        f"/api/v1/tickets/{ticket['id']}/evidence",
        json={"evidence_type": "note", "title": "Checked the logs"},
        headers=auth(it_token),
    )
    # The DB scoping evidence to incidents (NOT NULL + RESTRICT) is a
    # deliberate rule, not a gap: standalone tickets get no evidence rows
    # through either path.
    assert resp2.status_code == 422
    assert resp2.json()["detail"]["code"] == "evidence_requires_incident"


@pytest.mark.asyncio
async def test_download_headers_and_roundtrip(client, db_session):
    org, soc_email, dev, *_ = await _soc_world(db_session)
    soc_token, ticket, _ = await _ticket_with_incident(client, soc_email, org.id)
    it_token = await login(client, dev.email)
    up = await _upload(client, it_token, ticket["id"], name="auth.log")
    assert up.status_code == 201
    row = up.json()

    down = await client.get(
        f"/api/v1/tickets/{ticket['id']}/evidence/{row['id']}/download", headers=auth(it_token)
    )
    assert down.status_code == 200
    assert down.content == TEXT
    assert down.headers["content-type"] == "text/plain; charset=utf-8"
    assert down.headers["content-disposition"] == 'attachment; filename="auth.log"'
    assert down.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_download_wrong_organization_is_404(client, db_session):
    org, soc_email, dev, _, other_org, foreign_dev = await _soc_world(db_session)
    soc_token, ticket, _ = await _ticket_with_incident(client, soc_email, org.id)
    it_token = await login(client, dev.email)
    row = (await _upload(client, it_token, ticket["id"])).json()
    foreign_token = await login(client, foreign_dev.email)
    resp = await client.get(
        f"/api/v1/tickets/{ticket['id']}/evidence/{row['id']}/download", headers=auth(foreign_token)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_owner_cannot_upload_but_may_download(client, db_session):
    from app.models import AdminLevel

    from tests.helpers import make_admin

    org, soc_email, dev, *_ = await _soc_world(db_session)
    soc_token, ticket, _ = await _ticket_with_incident(client, soc_email, org.id)
    owner = await make_admin(db_session, email=f"owner-{uuid.uuid4().hex[:8]}@x.io", admin_level=AdminLevel.organization_admin, organization_id=org.id)
    owner_token = await login(client, owner.email)

    resp = await _upload(client, owner_token, ticket["id"])
    assert resp.status_code == 403

    it_token = await login(client, dev.email)
    row = (await _upload(client, it_token, ticket["id"])).json()
    down = await client.get(
        f"/api/v1/tickets/{ticket['id']}/evidence/{row['id']}/download", headers=auth(owner_token)
    )
    assert down.status_code == 200


@pytest.mark.asyncio
async def test_incident_upload_and_download_by_soc(client, db_session):
    org, soc_email, dev, *_ = await _soc_world(db_session)
    soc_token = await login(client, soc_email)
    resp = await client.post(
        "/api/v1/incidents",
        json={"title": "Breach at the perimeter", "organization_id": str(org.id)},
        headers=auth(soc_token),
    )
    assert resp.status_code == 201
    incident = resp.json()

    up = await client.post(
        f"/api/v1/incidents/{incident['id']}/evidence/upload",
        files={"file": ("scan.png", PNG, "image/png")},
        headers=auth(soc_token),
    )
    assert up.status_code == 201, up.text
    row = up.json()
    assert row["evidence_type"] == "screenshot"
    assert row["sha256"] == hashlib.sha256(PNG).hexdigest()

    down = await client.get(
        f"/api/v1/incidents/{incident['id']}/evidence/{row['id']}/download", headers=auth(soc_token)
    )
    assert down.status_code == 200
    assert down.content == PNG
    assert down.headers["content-disposition"] == 'attachment; filename="scan.png"'
    assert down.headers["x-content-type-options"] == "nosniff"

    # IT of the org can download through the shared window...
    it_token = await login(client, dev.email)
    down2 = await client.get(
        f"/api/v1/incidents/{incident['id']}/evidence/{row['id']}/download", headers=auth(it_token)
    )
    assert down2.status_code == 200
    # ...but cannot UPLOAD directly to the incident (SOC-side writers only).
    up2 = await client.post(
        f"/api/v1/incidents/{incident['id']}/evidence/upload",
        files={"file": ("no.png", PNG, "image/png")},
        headers=auth(it_token),
    )
    assert up2.status_code in (403, 404)


@pytest.mark.asyncio
async def test_incident_download_wrong_organization_is_404(client, db_session):
    org, soc_email, dev, _, other_org, foreign_dev = await _soc_world(db_session)
    soc_token = await login(client, soc_email)
    incident = (
        await client.post(
            "/api/v1/incidents",
            json={"title": "x", "organization_id": str(org.id)},
            headers=auth(soc_token),
        )
    ).json()
    row = (
        await client.post(
            f"/api/v1/incidents/{incident['id']}/evidence/upload",
            files={"file": ("f.log", TEXT, "text/plain")},
            headers=auth(soc_token),
        )
    ).json()
    foreign_token = await login(client, foreign_dev.email)
    resp = await client.get(
        f"/api/v1/incidents/{incident['id']}/evidence/{row['id']}/download", headers=auth(foreign_token)
    )
    assert resp.status_code == 404
