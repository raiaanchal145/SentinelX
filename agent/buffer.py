"""
Local SQLite FIFO Buffer with Size Cap and Retry Mechanics.

Buffers normalized events on disk during network partitions or server unavailability,
capped at 50 MB to prevent unbounded disk growth.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

from agent.config import get_data_dir

logger = logging.getLogger("sentinelx.agent.buffer")

DEFAULT_MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
DEFAULT_MAX_ITEMS = 50000


class LocalBuffer:
    """Thread-safe SQLite persistent retry queue."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
        max_items: int = DEFAULT_MAX_ITEMS,
    ) -> None:
        self.db_path = db_path or (get_data_dir() / "queue.db")
        self.max_size_bytes = max_size_bytes
        self.max_items = max_items
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS buffered_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    next_attempt_at REAL DEFAULT 0.0
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_next_attempt ON buffered_events(next_attempt_at, id);")
            conn.commit()

    def push(self, events: list[dict[str, Any]]) -> int:
        """Appends events to the persistent queue."""
        if not events:
            return 0

        now = time.time()
        rows = [(json.dumps(e, separators=(",", ":")), now, 0, now) for e in events]

        with self._get_connection() as conn:
            conn.executemany(
                "INSERT INTO buffered_events (event_json, created_at, attempts, next_attempt_at) VALUES (?, ?, ?, ?);",
                rows,
            )
            conn.commit()

        self.prune_if_exceeded()
        return len(events)

    def pop_batch(self, limit: int = 200) -> list[tuple[int, dict[str, Any]]]:
        """
        Retrieves up to `limit` events that are ready for delivery (next_attempt_at <= now).
        Returns list of (id, event_dict).
        """
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, event_json
                FROM buffered_events
                WHERE next_attempt_at <= ?
                ORDER BY id ASC
                LIMIT ?;
                """,
                (now, limit),
            )
            rows = cursor.fetchall()

        results: list[tuple[int, dict[str, Any]]] = []
        for r in rows:
            try:
                results.append((r["id"], json.loads(r["event_json"])))
            except Exception:
                # Corrupt record: drop it directly
                self.delete([r["id"]])
        return results

    def delete(self, event_ids: list[int]) -> int:
        """Deletes acknowledged events from buffer."""
        if not event_ids:
            return 0
        placeholders = ",".join("?" for _ in event_ids)
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"DELETE FROM buffered_events WHERE id IN ({placeholders});",
                event_ids,
            )
            conn.commit()
            return cursor.rowcount

    def schedule_retry(self, event_ids: list[int], delay_seconds: float) -> None:
        """Marks batch as failed and sets exponential backoff delay."""
        if not event_ids:
            return
        next_attempt = time.time() + delay_seconds
        placeholders = ",".join("?" for _ in event_ids)
        with self._get_connection() as conn:
            conn.execute(
                f"""
                UPDATE buffered_events
                SET attempts = attempts + 1, next_attempt_at = ?
                WHERE id IN ({placeholders});
                """,
                [next_attempt] + event_ids,
            )
            conn.commit()

    def count(self) -> int:
        """Returns total number of queued events."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM buffered_events;")
            return cursor.fetchone()[0]

    def get_size_bytes(self) -> int:
        """Returns current file size of SQLite database in bytes."""
        try:
            return os.path.getsize(self.db_path)
        except OSError:
            return 0

    def prune_if_exceeded(self) -> None:
        """
        Enforces FIFO eviction if size cap (50 MB) or item cap (50,000) is exceeded.
        Deletes the oldest records to preserve buffer stability.
        """
        total_items = self.count()
        file_size = self.get_size_bytes()

        if total_items > self.max_items:
            excess = total_items - self.max_items
            logger.warning("Buffer exceeded max items (%d > %d), pruning %d oldest events.", total_items, self.max_items, excess)
            with self._get_connection() as conn:
                conn.execute(
                    "DELETE FROM buffered_events WHERE id IN (SELECT id FROM buffered_events ORDER BY id ASC LIMIT ?);",
                    (excess,),
                )
                conn.commit()

        if file_size > self.max_size_bytes:
            logger.warning("Buffer exceeded max size (%d > %d bytes), pruning 500 oldest events.", file_size, self.max_size_bytes)
            with self._get_connection() as conn:
                conn.execute(
                    "DELETE FROM buffered_events WHERE id IN (SELECT id FROM buffered_events ORDER BY id ASC LIMIT 500);",
                )
                conn.commit()
