"""
Evidence file storage (P15, docs/API_CONTRACT.md "Evidence").

Files are stored OUTSIDE the web root under a per-organization
directory. The path on disk is never derived from the uploaded
filename -- each file gets a random uuid name -- and the original
filename survives only as database metadata. Content type is decided
by SNIFFING the first bytes (the client's declared content-type is
never trusted), the SHA-256 is computed from the same bytes we stored,
and nothing is ever deleted: evidence is part of the record (the
model's FK is ON DELETE RESTRICT for a reason).

Allowed types (docs/DECISIONS.md "Evidence upload policy"):
  - log / text: text-like files (utf-8 decodable, no NUL bytes)
  - screenshot: PNG or JPEG (magic bytes)
  - pdf:        PDF (magic bytes)
  - zip:        ZIP archive (magic bytes) -- stored INERT: never
                extracted, never executed, only downloaded back
Storage layout: {evidence_storage_dir}/{organization_id}/{uuid} (no
extension), written atomically (tmp file + os.replace).
"""

from __future__ import annotations

import hashlib
import os
import uuid as uuid_module
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

# ---------------------------------------------------------------------------
# The policy (mirrored in docs/API_CONTRACT.md; change both together).
# ---------------------------------------------------------------------------

EVIDENCE_MAX_BYTES = settings.evidence_max_upload_mb * 1024 * 1024

SUPPORTED_KINDS = ("log", "text", "screenshot", "pdf", "zip")

# The sniffed kind -> the EvidenceType enum member recorded on the row.
# The enum (models.py) has log|file|screenshot|note|command_output and is
# frozen by migrations -- the precise kind (pdf vs zip vs generic binary
# file) lives in the row's content metadata instead.
EVIDENCE_TYPE_BY_KIND = {
    "log": "log",
    "text": "log",
    "screenshot": "screenshot",
    "pdf": "file",
    "zip": "file",
}

# (kind, sniffer) tried in order; the first match wins.
_MAGIC_SNAPPERS: tuple[tuple[str, object], ...] = (
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("pdf", b"%PDF-"),
    ("zip", b"PK\x03\x04"),
)


@dataclass(frozen=True)
class SniffedFile:
    kind: str  # one of SUPPORTED_KINDS
    content_type: str  # what the download endpoint will announce
    size: int
    sha256: str


def sniff_and_hash(data: bytes) -> SniffedFile:
    """Decide what the bytes really are, and hash what we will store."""
    if len(data) == 0:
        raise ValueError("The file is empty.")

    sha = hashlib.sha256(data).hexdigest()

    for magic_kind, magic in _MAGIC_SNAPPERS:
        if data.startswith(magic):
            if magic_kind == "png":
                return SniffedFile("screenshot", "image/png", len(data), sha)
            if magic_kind == "pdf":
                return SniffedFile("pdf", "application/pdf", len(data), sha)
            return SniffedFile("zip", "application/zip", len(data), sha)

    # JPEG: FF D8 FF (the third byte varies by marker).
    if data.startswith(b"\xff\xd8\xff"):
        return SniffedFile("screenshot", "image/jpeg", len(data), sha)

    # Text-like: utf-8 decodable, no NUL bytes, printable-ish.
    if b"\x00" not in data[:4096]:
        try:
            data.decode("utf-8")
            return SniffedFile("log", "text/plain; charset=utf-8", len(data), sha)
        except UnicodeDecodeError:
            pass

    raise ValueError(
        "Unsupported file type. Allowed: log/text, screenshot (png/jpg), pdf, zip."
    )


def evidence_org_dir(organization_id: uuid_module.UUID) -> Path:
    """{storage_dir}/{organization_id} -- created on demand, 0o700."""
    base = Path(settings.evidence_storage_dir)
    org_dir = base / str(organization_id)
    org_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(org_dir, 0o700)
    except OSError:
        pass  # best-effort on filesystems without POSIX perms
    return org_dir


def store_evidence_file(
    organization_id: uuid_module.UUID,
    filename: str,
    data: bytes,
) -> tuple[str, SniffedFile]:
    """
    Validate, sniff, hash and write one evidence file. Returns
    (storage_ref, sniffed). Raises ValueError for policy violations
    (type, empty) and FileTooLargeError for size.

    The storage_ref is "{organization_id}/{random_uuid}" -- the client's
    filename NEVER reaches the filesystem (path-traversal filenames like
    "../../etc/passwd" are inert by construction); it is kept as
    metadata on the Evidence row only.
    """
    if not filename or not filename.strip():
        raise ValueError("A filename is required.")

    # Zip bombs are not a download concern (we never extract), but a
    # single-file cap still applies before anything is written.
    if len(data) > EVIDENCE_MAX_BYTES:
        raise FileTooLargeError(
            f"The file is {len(data)} bytes; the limit is {EVIDENCE_MAX_BYTES} bytes "
            f"({settings.evidence_max_upload_mb} MB)."
        )

    sniffed = sniff_and_hash(data)

    storage_ref = f"{organization_id}/{uuid_module.uuid4()}"
    target = evidence_org_dir(organization_id) / storage_ref.split("/")[-1]
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)  # atomic on the same filesystem
    return storage_ref, sniffed


class FileTooLargeError(ValueError):
    pass


def open_evidence_file(storage_ref: str) -> tuple[Path, bytes]:
    """
    Read one stored evidence file back for download. storage_ref is
    ALWAYS "{org_id}/{uuid}" as we wrote it (never user input shaped);
    any other shape is rejected before it can touch the filesystem.
    """
    parts = storage_ref.split("/")
    if len(parts) != 2:
        raise ValueError("Malformed storage reference.")
    org_part, file_part = parts
    # Both components must be uuids -- kills traversal ("../") and any
    # absolute path components outright.
    for part in (org_part, file_part):
        uuid_module.UUID(part)  # raises ValueError if not a uuid
    base = Path(settings.evidence_storage_dir).resolve()
    target = (base / org_part / file_part).resolve()
    if base not in target.parents:
        raise ValueError("Storage reference escapes the evidence root.")
    return target, target.read_bytes()


def delete_evidence_file(storage_ref: str) -> None:
    """Retire-time cleanup ONLY (rows are never deleted through the
    API). Not called by any endpoint today."""
    try:
        target, _ = open_evidence_file(storage_ref)
        target.unlink(missing_ok=True)
    except (ValueError, OSError):
        pass
