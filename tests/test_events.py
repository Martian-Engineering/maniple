"""Tests for event log persistence."""

from datetime import datetime, timedelta, timezone
import json
import multiprocessing
import os
from pathlib import Path
import threading
import time

import pytest

from maniple import events
from maniple.events import WorkerEvent
from maniple_mcp.config import ClaudeTeamConfig, ConfigError, EventsConfig


def _hold_lock(path_value: str, ready: multiprocessing.Event, release: multiprocessing.Event) -> None:
    from maniple import events as events_module

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

    def setup_method(self):
        """Clear rotation config cache between tests."""
        events._clear_rotation_config_cache()

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

        rotated = list(path.parent.glob("events.*.jsonl"))
        assert len(rotated) == 1
        assert rotated[0].stat().st_size > 0
        assert path.exists()
        assert path.stat().st_size == 0

    def test_rotate_events_log_daily(self, tmp_path, monkeypatch):
        """rotate_events_log should rotate when the date changes."""
        path = tmp_path / "events.jsonl"
        monkeypatch.setattr(events, "get_events_path", lambda: path)

        old_ts = datetime(2026, 1, 27, 23, 55, tzinfo=timezone.utc)
        old_line = json.dumps({
            "ts": _isoformat_zulu(old_ts),
            "type": "worker_idle",
            "worker_id": "old-worker",
            "data": {"state": "idle"},
        })
        path.write_text(old_line + "\n", encoding="utf-8")
        old_epoch = old_ts.timestamp()
        os.utime(path, (old_epoch, old_epoch))

        new_ts = datetime(2026, 1, 28, 0, 1, tzinfo=timezone.utc)
        events.append_event(WorkerEvent(
            ts=_isoformat_zulu(new_ts),
            type="worker_started",
            worker_id="new-worker",
            data={"state": "active"},
        ))

        backup = path.with_name("events.2026-01-27.jsonl")
        assert backup.exists()
        assert "old-worker" in backup.read_text(encoding="utf-8")
        assert "new-worker" in path.read_text(encoding="utf-8")

    def test_rotate_events_log_retains_active_and_recent(self, tmp_path, monkeypatch):
        """Rotation should retain active and recently active workers."""
        path = tmp_path / "events.jsonl"
        monkeypatch.setattr(events, "get_events_path", lambda: path)

        now = datetime(2026, 1, 28, 12, 0, tzinfo=timezone.utc)
        active_old = datetime(2026, 1, 26, 9, 0, tzinfo=timezone.utc)
        recent_idle = datetime(2026, 1, 28, 11, 0, tzinfo=timezone.utc)
        stale_idle = datetime(2026, 1, 26, 8, 0, tzinfo=timezone.utc)

        lines = [
            json.dumps({
                "ts": _isoformat_zulu(active_old),
                "type": "worker_active",
                "worker_id": "active-old",
                "data": {"state": "active"},
            }),
            json.dumps({
                "ts": _isoformat_zulu(recent_idle),
                "type": "worker_idle",
                "worker_id": "recent-idle",
                "data": {"state": "idle"},
            }),
            json.dumps({
                "ts": _isoformat_zulu(stale_idle),
                "type": "worker_idle",
                "worker_id": "stale-idle",
                "data": {"state": "idle"},
            }),
            json.dumps({
                "ts": _isoformat_zulu(recent_idle),
                "type": "snapshot",
                "worker_id": None,
                "data": {
                    "count": 3,
                    "workers": [
                        {"session_id": "active-old", "state": "active"},
                        {"session_id": "recent-idle", "state": "idle"},
                        {"session_id": "stale-idle", "state": "idle"},
                    ],
                },
            }),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        last_write = datetime(2026, 1, 27, 23, 59, tzinfo=timezone.utc)
        last_epoch = last_write.timestamp()
        os.utime(path, (last_epoch, last_epoch))

        events.rotate_events_log(recent_hours=24, now=now)

        backup = path.with_name("events.2026-01-27.jsonl")
        assert backup.exists()

        retained = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        worker_ids = {
            payload.get("worker_id")
            for payload in retained
            if payload.get("type") != "snapshot"
        }
        assert worker_ids == {"active-old", "recent-idle"}

        snapshot = next(payload for payload in retained if payload.get("type") == "snapshot")
        worker_ids = {worker["session_id"] for worker in snapshot["data"]["workers"]}
        assert worker_ids == {"active-old", "recent-idle"}
        assert snapshot["data"]["count"] == 2

    def test_rotate_events_log_keeps_only_latest_snapshot_and_honors_size_cap(
        self, tmp_path, monkeypatch
    ):
        """Size rotation should not retain unbounded snapshot history for active workers."""
        path = tmp_path / "events.jsonl"
        monkeypatch.setattr(events, "get_events_path", lambda: path)

        now = datetime(2026, 1, 28, 12, 0, tzinfo=timezone.utc)
        base = datetime(2026, 1, 28, 0, 0, tzinfo=timezone.utc)
        filler = "x" * 60_000

        lines = []
        for i in range(30):
            ts = base + timedelta(minutes=i)
            lines.append(
                json.dumps(
                    {
                        "ts": _isoformat_zulu(ts),
                        "type": "snapshot",
                        "worker_id": None,
                        "data": {
                            "count": 1,
                            "workers": [
                                {"session_id": "active-forever", "state": "active", "filler": filler}
                            ],
                        },
                    }
                )
            )

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.utime(path, (now.timestamp(), now.timestamp()))
        assert path.stat().st_size > 1024 * 1024

        events.rotate_events_log(max_size_mb=1, recent_hours=24, now=now)

        retained = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        snapshots = [payload for payload in retained if payload.get("type") == "snapshot"]
        assert len(snapshots) == 1
        assert snapshots[0]["ts"] == _isoformat_zulu(base + timedelta(minutes=29))
        assert path.stat().st_size <= 1024 * 1024

    def test_append_event_rotates_when_incoming_write_would_exceed_cap(
        self, tmp_path, monkeypatch
    ):
        """append_event should rotate before writing if the batch would cross max_size_mb."""
        path = tmp_path / "events.jsonl"
        monkeypatch.setattr(events, "get_events_path", lambda: path)
        monkeypatch.setattr(
            events,
            "_load_rotation_config",
            lambda: EventsConfig(max_size_mb=1, recent_hours=0),
        )

        base = datetime(2026, 1, 28, 10, 0, tzinfo=timezone.utc)
        path.write_bytes(b"x" * (1024 * 1024 - 10))
        os.utime(path, (base.timestamp(), base.timestamp()))

        events.append_event(
            WorkerEvent(
                ts=_isoformat_zulu(base.replace(minute=1)),
                type="worker_started",
                worker_id="new-worker",
                data={"state": "active"},
            )
        )

        backup = path.with_name("events.2026-01-28.jsonl")
        assert backup.exists()
        assert path.read_text(encoding="utf-8").count("\n") == 1

    def test_rotate_events_log_uses_config_defaults(self, tmp_path, monkeypatch):
        """Config should supply rotation defaults when env overrides are missing."""
        config = ClaudeTeamConfig(events=EventsConfig(max_size_mb=2, recent_hours=0))
        monkeypatch.setattr(events, "load_config", lambda: config)

        path = tmp_path / "events.jsonl"
        monkeypatch.setattr(events, "get_events_path", lambda: path)

        base = datetime(2026, 1, 28, 10, 0, tzinfo=timezone.utc)
        line = json.dumps({
            "ts": _isoformat_zulu(base),
            "type": "worker_idle",
            "worker_id": "idle-worker",
            "data": {"state": "idle"},
        })
        filler = "x" * (1024 * 1024 + 512 * 1024)
        path.write_text(line + "\n" + filler + "\n", encoding="utf-8")
        os.utime(path, (base.timestamp(), base.timestamp()))

        events.append_event(WorkerEvent(
            ts=_isoformat_zulu(base.replace(minute=5)),
            type="worker_started",
            worker_id="active-worker",
            data={"state": "active"},
        ))

        rotated = list(path.parent.glob("events.*.jsonl"))
        assert rotated == []
        contents = path.read_text(encoding="utf-8")
        assert "idle-worker" in contents
        assert "active-worker" in contents

    def test_rotate_events_log_env_overrides_config(self, tmp_path, monkeypatch):
        """Env vars should override config-provided rotation defaults."""
        monkeypatch.setenv("MANIPLE_EVENTS_MAX_SIZE_MB", "1")
        monkeypatch.setenv("MANIPLE_EVENTS_RECENT_HOURS", "0")

        config = ClaudeTeamConfig(events=EventsConfig(max_size_mb=2, recent_hours=24))
        monkeypatch.setattr(events, "load_config", lambda: config)

        path = tmp_path / "events.jsonl"
        monkeypatch.setattr(events, "get_events_path", lambda: path)

        base = datetime(2026, 1, 28, 10, 0, tzinfo=timezone.utc)
        line = json.dumps({
            "ts": _isoformat_zulu(base),
            "type": "worker_idle",
            "worker_id": "idle-worker",
            "data": {"state": "idle"},
        })
        filler = "x" * (1024 * 1024 + 512 * 1024)
        path.write_text(line + "\n" + filler + "\n", encoding="utf-8")
        os.utime(path, (base.timestamp(), base.timestamp()))

        events.append_event(WorkerEvent(
            ts=_isoformat_zulu(base.replace(minute=5)),
            type="worker_started",
            worker_id="active-worker",
            data={"state": "active"},
        ))

        backup = path.with_name("events.2026-01-28.jsonl")
        assert backup.exists()
        retained = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert [payload["worker_id"] for payload in retained] == ["active-worker"]

    def test_rotation_config_invalid_config_falls_back(self, monkeypatch, caplog):
        """Invalid config should fall back to default rotation config."""
        def raise_config_error():
            raise ConfigError("invalid config")

        monkeypatch.setattr(events, "load_config", raise_config_error)
        monkeypatch.delenv("MANIPLE_EVENTS_MAX_SIZE_MB", raising=False)
        monkeypatch.delenv("MANIPLE_EVENTS_RECENT_HOURS", raising=False)
        monkeypatch.delenv("CLAUDE_TEAM_EVENTS_MAX_SIZE_MB", raising=False)
        monkeypatch.delenv("CLAUDE_TEAM_EVENTS_RECENT_HOURS", raising=False)

        with caplog.at_level("WARNING"):
            rotation = events._load_rotation_config()

        assert rotation.max_size_mb == 1
        assert rotation.recent_hours == 24
        assert "Invalid config file; using default event rotation config" in caplog.text

    def test_rotation_config_deprecated_env_fallback(self, monkeypatch):
        """Deprecated CLAUDE_TEAM_EVENTS_* env vars are still honored."""
        monkeypatch.setenv("CLAUDE_TEAM_EVENTS_MAX_SIZE_MB", "3")
        monkeypatch.setenv("CLAUDE_TEAM_EVENTS_RECENT_HOURS", "11")

        rotation = events._load_rotation_config()
        assert rotation.max_size_mb == 3
        assert rotation.recent_hours == 11

    def test_prune_event_backups_keep_days(self, tmp_path, monkeypatch):
        """prune_event_backups should delete backups older than keep_days."""
        path = tmp_path / "events.jsonl"
        monkeypatch.setattr(events, "get_events_path", lambda: path)
        path.write_text("", encoding="utf-8")

        b1 = tmp_path / "events.2026-01-01.jsonl"
        b2 = tmp_path / "events.2026-01-02.jsonl"
        b3 = tmp_path / "events.2026-01-03.jsonl"
        b1.write_bytes(b"a" * 10)
        b2.write_bytes(b"b" * 10)
        b3.write_bytes(b"c" * 10)

        os.utime(b1, (datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp(),) * 2)
        os.utime(b2, (datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp(),) * 2)
        os.utime(b3, (datetime(2026, 1, 3, tzinfo=timezone.utc).timestamp(),) * 2)

        report = events.prune_event_backups(
            keep_days=1,
            now=datetime(2026, 1, 4, tzinfo=timezone.utc),
            dry_run=False,
        )

        assert report.deleted_count == 2
        assert not b1.exists()
        assert not b2.exists()
        assert b3.exists()
