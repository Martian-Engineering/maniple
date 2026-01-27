"""Tests for event log persistence."""

from datetime import datetime, timezone
import multiprocessing
from pathlib import Path
import threading
import time

import pytest

from claude_team import events
from claude_team.events import WorkerEvent


def _hold_lock(path_value: str, ready: multiprocessing.Event, release: multiprocessing.Event) -> None:
    from claude_team import events as events_module

    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        events_module._lock_file(handle)
        ready.set()
        release.wait(5)
        events_module._unlock_file(handle)


def _isoformat_zulu(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestEventLogPersistence:
    """Event log persistence behaviors."""

    def test_append_event_creates_file(self, tmp_path, monkeypatch):
        """append_event should create the log file if missing."""
        path = tmp_path / "events.jsonl"
        monkeypatch.setattr(events, "get_events_path", lambda: path)

        event = WorkerEvent(
            ts=_isoformat_zulu(datetime(2026, 1, 27, 11, 40, tzinfo=timezone.utc)),
            type="worker_started",
            worker_id="abc",
            data={"name": "Liberace"},
        )

        assert not path.exists()
        events.append_event(event)
        assert path.exists()
        assert path.read_text(encoding="utf-8").count("\n") == 1

    def test_read_events_since_filters_by_time(self, tmp_path, monkeypatch):
        """read_events_since should filter and cap results."""
        path = tmp_path / "events.jsonl"
        monkeypatch.setattr(events, "get_events_path", lambda: path)

        base = datetime(2026, 1, 27, 11, 40, tzinfo=timezone.utc)
        event_a = WorkerEvent(
            ts=_isoformat_zulu(base),
            type="worker_started",
            worker_id="abc",
            data={"seq": 1},
        )
        event_b = WorkerEvent(
            ts=_isoformat_zulu(base.replace(minute=41)),
            type="worker_idle",
            worker_id="abc",
            data={"seq": 2},
        )
        event_c = WorkerEvent(
            ts=_isoformat_zulu(base.replace(minute=42)),
            type="worker_active",
            worker_id="abc",
            data={"seq": 3},
        )

        events.append_events([event_a, event_b, event_c])

        filtered = events.read_events_since(base.replace(minute=41), limit=10)
        assert [event.data["seq"] for event in filtered] == [2, 3]

        capped = events.read_events_since(base, limit=2)
        assert [event.data["seq"] for event in capped] == [2, 3]

    def test_concurrent_write_blocks_on_lock(self, tmp_path, monkeypatch):
        """append_event should block when another process holds the lock."""
        if events.fcntl is None and events.msvcrt is None:
            pytest.skip("File locking not supported on this platform.")

        path = tmp_path / "events.jsonl"
        monkeypatch.setattr(events, "get_events_path", lambda: path)

        ready = multiprocessing.Event()
        release = multiprocessing.Event()
        process = multiprocessing.Process(
            target=_hold_lock,
            args=(str(path), ready, release),
        )
        process.start()
        assert ready.wait(timeout=2)

        started = threading.Event()

        def _append() -> None:
            started.set()
            events.append_event(
                WorkerEvent(
                    ts=_isoformat_zulu(datetime(2026, 1, 27, 11, 41, tzinfo=timezone.utc)),
                    type="worker_idle",
                    worker_id="abc",
                    data={"name": "Liberace"},
                )
            )

        thread = threading.Thread(target=_append)
        thread.start()
        assert started.wait(timeout=1)
        time.sleep(0.2)
        assert thread.is_alive()

        release.set()
        thread.join(timeout=2)
        process.join(timeout=2)

        assert not thread.is_alive()
        assert process.exitcode == 0

    def test_rotate_events_log(self, tmp_path, monkeypatch):
        """rotate_events_log should rotate when size exceeds max."""
        path = tmp_path / "events.jsonl"
        monkeypatch.setattr(events, "get_events_path", lambda: path)

        path.write_bytes(b"x" * (1024 * 1024 + 1))
        events.rotate_events_log(max_size_mb=1)

        rotated = list(path.parent.glob("events.jsonl.*"))
        assert len(rotated) == 1
        assert rotated[0].stat().st_size > 0
        assert path.exists()
        assert path.stat().st_size == 0
