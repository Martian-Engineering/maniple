"""Event log persistence for worker lifecycle activity."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Literal

try:
    import fcntl
except ImportError:  # pragma: no cover - platform-specific
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - platform-specific
    msvcrt = None


EventType = Literal[
    "snapshot",
    "worker_started",
    "worker_idle",
    "worker_active",
    "worker_closed",
]


@dataclass
class WorkerEvent:
    """Represents a persisted worker event."""

    ts: str
    type: EventType
    worker_id: str | None
    data: dict


def get_events_path() -> Path:
    """Returns ~/.claude-team/events.jsonl, creating parent dir if needed."""
    base_dir = Path.home() / ".claude-team"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "events.jsonl"


def append_event(event: WorkerEvent) -> None:
    """Append single event to log file (atomic write with file locking)."""
    append_events([event])


def _event_to_dict(event: WorkerEvent) -> dict:
    """Convert WorkerEvent to dict without using asdict (avoids deepcopy issues)."""
    return {
        "ts": event.ts,
        "type": event.type,
        "worker_id": event.worker_id,
        "data": event.data,  # Already sanitized by caller
    }


def append_events(events: list[WorkerEvent]) -> None:
    """Append multiple events atomically."""
    if not events:
        return

    path = get_events_path()
    # Serialize upfront so the file write is a single, ordered block.
    # Use _event_to_dict instead of asdict to avoid deepcopy pickle issues.
    payloads = [json.dumps(_event_to_dict(event), ensure_ascii=False) for event in events]
    block = "\n".join(payloads) + "\n"

    with path.open("a", encoding="utf-8") as handle:
        _lock_file(handle)
        try:
            # Hold the lock across the entire write and flush cycle.
            handle.write(block)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            _unlock_file(handle)


def read_events_since(
    since: datetime | None = None,
    limit: int = 1000,
) -> list[WorkerEvent]:
    """Read events from log, optionally filtered by timestamp."""
    if limit <= 0:
        return []

    path = get_events_path()
    if not path.exists():
        return []

    normalized_since = _normalize_since(since)
    events: list[WorkerEvent] = []

    with path.open("r", encoding="utf-8") as handle:
        # Stream the file so we don't load the entire log into memory.
        for line in handle:
            line = line.strip()
            if not line:
                continue

            event = _parse_event(json.loads(line))
            # Compare timestamps only when a filter is provided.
            if normalized_since is not None:
                event_ts = _parse_timestamp(event.ts)
                if event_ts < normalized_since:
                    continue

            events.append(event)
            # Keep only the most recent events within the requested limit.
            if len(events) > limit:
                events.pop(0)

    return events


def get_latest_snapshot() -> dict | None:
    """Get most recent snapshot event for recovery."""
    path = get_events_path()
    if not path.exists():
        return None

    latest_snapshot: dict | None = None

    with path.open("r", encoding="utf-8") as handle:
        # Walk the log to track the latest snapshot without extra storage.
        for line in handle:
            line = line.strip()
            if not line:
                continue

            event = _parse_event(json.loads(line))
            if event.type == "snapshot":
                latest_snapshot = event.data

    return latest_snapshot


def rotate_events_log(max_size_mb: int = 10) -> None:
    """Rotate log file if it exceeds max size."""
    if max_size_mb <= 0:
        return

    path = get_events_path()
    if not path.exists():
        return

    max_bytes = max_size_mb * 1024 * 1024

    with path.open("a", encoding="utf-8") as handle:
        _lock_file(handle)
        try:
            # Re-check size while locked to avoid races with concurrent writers.
            if path.stat().st_size <= max_bytes:
                return

            rotated_path = _rotated_path(path)
            # Flush buffered writes before rotating the file on disk.
            handle.flush()
            os.fsync(handle.fileno())
            path.replace(rotated_path)
            # Ensure a fresh log file exists after rotation.
            path.touch()
        finally:
            _unlock_file(handle)


def _lock_file(handle) -> None:
    # Acquire an exclusive lock for the file handle.
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    if msvcrt is not None:  # pragma: no cover - platform-specific
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    raise RuntimeError("File locking is not supported on this platform.")


def _unlock_file(handle) -> None:
    # Release any lock held on the file handle.
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    if msvcrt is not None:  # pragma: no cover - platform-specific
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    raise RuntimeError("File locking is not supported on this platform.")


def _normalize_since(since: datetime | None) -> datetime | None:
    # Normalize timestamps for consistent comparisons.
    if since is None:
        return None
    if since.tzinfo is None:
        return since.replace(tzinfo=timezone.utc)
    return since.astimezone(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    # Parse ISO 8601 timestamps, including Zulu suffixes.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_event(payload: dict) -> WorkerEvent:
    # Convert a JSON payload into a WorkerEvent instance.
    return WorkerEvent(
        ts=str(payload["ts"]),
        type=payload["type"],
        worker_id=payload.get("worker_id"),
        data=payload.get("data") or {},
    )


def _rotated_path(path: Path) -> Path:
    # Build a timestamped path to avoid clobbering older rotations.
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return path.with_name(f"{path.name}.{suffix}")
