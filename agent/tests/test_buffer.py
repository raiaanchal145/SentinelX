"""
Unit Tests for Local Persistent Buffer, FIFO Eviction, and Backoff Retries.
"""

import tempfile
from pathlib import Path
import pytest
from agent.buffer import LocalBuffer


def test_buffer_push_and_pop():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_queue.db"
        buf = LocalBuffer(db_path=db_path)

        events = [
            {"event_type": "logon_failure", "message": f"attempt {i}", "timestamp": "2026-10-21T08:00:00Z"}
            for i in range(10)
        ]
        pushed = buf.push(events)
        assert pushed == 10
        assert buf.count() == 10

        # Pop batch of 5
        batch = buf.pop_batch(limit=5)
        assert len(batch) == 5
        assert batch[0][1]["message"] == "attempt 0"

        # Delete popped
        deleted = buf.delete([item[0] for item in batch])
        assert deleted == 5
        assert buf.count() == 5

        # Pop remaining
        remaining = buf.pop_batch(limit=10)
        assert len(remaining) == 5
        assert remaining[0][1]["message"] == "attempt 5"


def test_buffer_retry_backoff():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_queue.db"
        buf = LocalBuffer(db_path=db_path)

        events = [{"event_type": "logon_failure", "message": "fail1", "timestamp": "2026-10-21T08:00:00Z"}]
        buf.push(events)

        batch = buf.pop_batch(limit=1)
        event_id = batch[0][0]

        # Schedule retry in 30 seconds
        buf.schedule_retry([event_id], delay_seconds=30.0)

        # Should NOT be returned immediately since next_attempt_at is in future
        ready = buf.pop_batch(limit=1)
        assert len(ready) == 0


def test_buffer_fifo_item_limit_pruning():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_queue.db"
        # Set small max_items of 5
        buf = LocalBuffer(db_path=db_path, max_items=5)

        events = [
            {"event_type": "logon_failure", "message": f"item_{i}", "timestamp": "2026-10-21T08:00:00Z"}
            for i in range(10)
        ]
        buf.push(events)

        # Pruning should keep only the 5 newest items
        assert buf.count() == 5
        batch = buf.pop_batch(limit=10)
        assert len(batch) == 5
        # The first 5 (item_0 .. item_4) were pruned; items 5..9 remain
        assert batch[0][1]["message"] == "item_5"
        assert batch[-1][1]["message"] == "item_9"

