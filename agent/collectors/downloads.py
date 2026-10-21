"""
Downloads Folder Collector with Zone.Identifier and SHA-256 Hashing.

Inspects new files in user Downloads directories for NTFS Alternate Data Stream
Zone.Identifier (ZoneId=3: Internet Zone) and computes binary SHA-256 hashes.
Strictly disabled unless 'file_downloads' category is consented.
"""

from __future__ import annotations

import glob
import hashlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from agent.schema import create_event_record

logger = logging.getLogger("sentinelx.agent.downloads")

EXECUTABLE_EXTENSIONS = {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".dll", ".iso", ".scr", ".zip", ".tar.gz"}


def compute_sha256(path: Path) -> str | None:
    """Computes SHA-256 hash in 64 KB blocks."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


def read_zone_identifier(path: Path) -> dict[str, str] | None:
    """
    Reads NTFS Zone.Identifier Alternate Data Stream if present.
    Returns parsed dictionary of ZoneTransfer keys (ZoneId, HostUrl, ReferrerUrl).
    """
    if sys.platform != "win32":
        return None

    ads_path = f"{path}:Zone.Identifier"
    if not os.path.exists(ads_path):
        return None

    props: dict[str, str] = {}
    try:
        with open(ads_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
        return props
    except (OSError, PermissionError):
        return None


class DownloadsCollector:
    """Monitors user Downloads folders for newly downloaded files."""

    def __init__(self, check_all_users: bool = True) -> None:
        self.check_all_users = check_all_users
        self.seen_files: dict[str, float] = {}  # filepath -> last_seen_mtime

    def get_watch_directories(self) -> list[Path]:
        """Finds candidate Downloads directories across system."""
        dirs: list[Path] = []
        home_dl = Path.home() / "Downloads"
        if home_dl.exists():
            dirs.append(home_dl)

        if self.check_all_users and sys.platform == "win32":
            user_base = Path(os.environ.get("SystemDrive", "C:")) / "Users"
            if user_base.exists():
                for dl in user_base.glob("*/Downloads"):
                    if dl.is_dir() and dl not in dirs:
                        dirs.append(dl)

        return dirs

    def poll_new_downloads(
        self,
        enabled_categories: set[str] | list[str],
        max_files: int = 25,
    ) -> list[dict[str, Any]]:
        """
        Scans Downloads directories for new files.
        Only executes if 'file_downloads' category is granted.
        """
        if "file_downloads" not in enabled_categories:
            return []

        results: list[dict[str, Any]] = []
        now = time.time()

        for folder in self.get_watch_directories():
            try:
                for entry in folder.iterdir():
                    if not entry.is_file():
                        continue

                    file_key = str(entry.resolve())
                    try:
                        mtime = entry.stat().st_mtime
                    except (OSError, PermissionError):
                        continue

                    # Only examine files seen for the first time or modified recently (past 1 hour)
                    if file_key in self.seen_files:
                        if self.seen_files[file_key] == mtime:
                            continue

                    self.seen_files[file_key] = mtime

                    # If file is older than 2 hours upon agent first startup, don't spam historical files
                    if now - mtime > 7200 and len(self.seen_files) > max_files:
                        continue

                    # Inspect file
                    zone_info = read_zone_identifier(entry)
                    sha256 = compute_sha256(entry)
                    ext = entry.suffix.lower()

                    is_internet_zone = bool(zone_info and zone_info.get("ZoneId") == "3")
                    severity = "medium" if ext in EXECUTABLE_EXTENSIONS else "info"

                    msg = f"New file in Downloads: '{entry.name}'"
                    if is_internet_zone:
                        msg += " (Origin: Internet Zone 3)"
                    if sha256:
                        msg += f" [SHA256: {sha256[:16]}...]"

                    raw_data: dict[str, Any] = {
                        "filename": entry.name,
                        "path": str(entry),
                        "extension": ext,
                        "sha256": sha256,
                        "size_bytes": entry.stat().st_size if entry.exists() else 0,
                        "zone_identifier": zone_info,
                    }

                    record = create_event_record(
                        event_type="custom",
                        message=msg,
                        process="downloads_collector",
                        severity_hint=severity,
                        raw=raw_data,
                    )
                    results.append(record)

                    if len(results) >= max_files:
                        break

            except (OSError, PermissionError) as exc:
                logger.debug("Failed scanning folder %s: %s", folder, exc)

        return results
