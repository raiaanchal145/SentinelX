"""
State Management and Windows Event Log Bookmarking.

Persists XML bookmarks for channels across agent restarts to prevent event
loss or duplicates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from agent.config import get_data_dir


class BookmarkState:
    """Tracks Event Log bookmarks by channel."""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self.path = storage_path or (get_data_dir() / "bookmarks.json")
        self.bookmarks: dict[str, str] = {}
        self.last_record_ids: dict[str, int] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.bookmarks = data.get("bookmarks", {})
                self.last_record_ids = data.get("last_record_ids", {})
            except Exception:
                self.bookmarks = {}
                self.last_record_ids = {}

    def save(self) -> None:
        try:
            data = {
                "bookmarks": self.bookmarks,
                "last_record_ids": self.last_record_ids,
            }
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def get_bookmark(self, channel: str) -> str | None:
        return self.bookmarks.get(channel)

    def set_bookmark(self, channel: str, xml_string: str) -> None:
        self.bookmarks[channel] = xml_string
        self.save()

    def get_last_record_id(self, channel: str) -> int:
        return self.last_record_ids.get(channel, 0)

    def set_last_record_id(self, channel: str, record_id: int) -> None:
        if record_id > self.last_record_ids.get(channel, 0):
            self.last_record_ids[channel] = record_id
            self.save()
