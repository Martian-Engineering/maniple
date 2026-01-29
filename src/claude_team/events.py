"""Event log persistence for worker lifecycle activity."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import logging
import json
import os
from pathlib import Path
from typing import Literal

from claude_team_mcp.config import ConfigError, EventsConfig, load_config

try:
    import fcntl
except ImportError:  # pragma: no cover - platform-specific
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - platform-specific
    msvcrt = None

logger = logging.getLogger("claude-team-mcp")


EventType = Literal[
    "snapshot",
    "worker_started",
    "worker_idle",
    "worker_active",
    "worker_closed",
]


def _int_env(name: str, default: int) -> int:
    # Parse integer environment overrides with a safe fallback.
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _load_rotation_config() -> EventsConfig:
    # Resolve rotation defaults from config, applying env overrides.
    try:
        config = load_config()
        events_config = config.events
    except ConfigError as exc:
        logger.warning(
            "Invalid config file; using default event rotation config: %s", exc
        )
        events_config = EventsConfig()
    return EventsConfig(
        max_size_mb=_int_env("CLAUDE_TEAM_EVENTS_MAX_SIZE_MB", events_config.max_size_mb),
        recent_hours=_int_env("CLAUDE_TEAM_EVENTS_RECENT_HOURS", events_config.recent_hours),
    )


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
    if not path.exists():
        path.touch()
    # Serialize upfront so the file write is a single, ordered block.
    # Use _event_to_dict instead of asdict to avoid deepcopy pickle issues.
    payloads = [json.dumps(_event_to_dict(event), ensure_ascii=False) for event in events]
    block = "\n".join(payloads) + "\n"
    event_ts = _latest_event_timestamp(events)
    rotation_config = _load_rotation_config()

    with path.open("r+", encoding="utf-8") as handle:
        _lock_file(handle)
        try:
            _rotate_events_log_locked(
                handle,
                path,
                current_ts=event_ts,
                max_size_mb=rotation_config.max_size_mb,
                recent_hours=rotation_config.recent_hours,
            )
            # Hold the lock across the entire write and flush cycle.
            handle.seek(0, os.SEEK_END)
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


def rotate_events_log(
    max_size_mb: int | None = None,
    recent_hours: int | None = None,
    now: datetime | None = None,
) -> None:
    """Rotate the log daily or by size, retaining active/recent workers."""
    path = get_events_path()
    if not path.exists():
        return

    current_ts = now or datetime.now(timezone.utc)
    if max_size_mb is None or recent_hours is None:
        rotation_config = _load_rotation_config()
        if max_size_mb is None:
            max_size_mb = rotation_config.max_size_mb
        if recent_hours is None:
            recent_hours = rotation_config.recent_hours

    with path.open("r+", encoding="utf-8") as handle:
        _lock_file(handle)
        try:
            _rotate_events_log_locked(
                handle,
                path,
                current_ts=current_ts,
                max_size_mb=max_size_mb,
                recent_hours=recent_hours,
            )
        finally:
            _unlock_file(handle)


def _rotate_events_log_locked(
    handle,
    path: Path,
    current_ts: datetime,
    max_size_mb: int,
    recent_hours: int,
) -> None:
    # Rotate the log while holding the caller's lock.
    if not _should_rotate(path, current_ts, max_size_mb):
        return

    rotation_day = _rotation_day(path, current_ts)
    backup_path = _backup_path(path, rotation_day)

    last_seen, last_state = _copy_and_collect_activity(handle, backup_path)
    keep_ids = _select_workers_to_keep(last_seen, last_state, current_ts, recent_hours)
    retained_lines = _filter_retained_events(handle, keep_ids)

    # Reset the log to only retained events.
    handle.seek(0)
    handle.truncate(0)
    if retained_lines:
        handle.write("\n".join(retained_lines) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _should_rotate(path: Path, current_ts: datetime, max_size_mb: int) -> bool:
    # Decide whether a daily or size-based rotation is needed.
    if not path.exists():
        return False

    current_day = current_ts.astimezone(timezone.utc).date()
    last_write = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    last_day = last_write.date()
    if last_day != current_day:
        return True

    if max_size_mb <= 0:
        return False
    max_bytes = max_size_mb * 1024 * 1024
    return path.stat().st_size > max_bytes


def _rotation_day(path: Path, current_ts: datetime) -> datetime.date:
    # Use the last write date for backups to align with daily rotations.
    if not path.exists():
        return current_ts.astimezone(timezone.utc).date()
    last_write = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return last_write.date()


def _backup_path(path: Path, rotation_day: datetime.date) -> Path:
    # Build a date-stamped backup path that avoids clobbering older files.
    date_suffix = rotation_day.strftime("%Y-%m-%d")
    candidate = path.with_name(f"{path.stem}.{date_suffix}{path.suffix}")
    if not candidate.exists():
        return candidate
    index = 1
    while True:
        indexed = path.with_name(f"{path.stem}.{date_suffix}.{index}{path.suffix}")
        if not indexed.exists():
            return indexed
        index += 1


def _copy_and_collect_activity(handle, backup_path: Path) -> tuple[dict[str, datetime], dict[str, str]]:
    # Copy the current log to a backup while recording worker activity.
    last_seen: dict[str, datetime] = {}
    last_state: dict[str, str] = {}
    handle.seek(0)
    with backup_path.open("w", encoding="utf-8") as backup:
        for line in handle:
            backup.write(line)
            line = line.strip()
            if not line:
                continue
            # Ignore malformed JSON while copying the raw line.
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = _parse_event(payload)
            _track_event_activity(event, last_seen, last_state)
    return last_seen, last_state


def _track_event_activity(
    event: WorkerEvent,
    last_seen: dict[str, datetime],
    last_state: dict[str, str],
) -> None:
    # Update last-seen and last-state maps from a worker event.
    try:
        event_ts = _parse_timestamp(event.ts)
    except ValueError:
        return

    if event.type == "snapshot":
        _track_snapshot_activity(event.data, event_ts, last_seen, last_state)
        return

    if not event.worker_id:
        return

    last_seen[event.worker_id] = event_ts
    state = _state_from_event_type(event.type)
    if state:
        last_state[event.worker_id] = state


def _track_snapshot_activity(
    data: dict,
    event_ts: datetime,
    last_seen: dict[str, datetime],
    last_state: dict[str, str],
) -> None:
    # Update state from snapshot payloads.
    workers = data.get("workers")
    if not isinstance(workers, list):
        return
    for worker in workers:
        if not isinstance(worker, dict):
            continue
        worker_id = _snapshot_worker_id(worker)
        if not worker_id:
            continue
        state = worker.get("state")
        if isinstance(state, str) and state:
            last_state[worker_id] = state
            if state == "active":
                last_seen[worker_id] = event_ts


def _state_from_event_type(event_type: EventType) -> str | None:
    # Map event types to "active"/"idle"/"closed" state labels.
    if event_type in ("worker_started", "worker_active"):
        return "active"
    if event_type == "worker_idle":
        return "idle"
    if event_type == "worker_closed":
        return "closed"
    return None


def _snapshot_worker_id(worker: dict) -> str | None:
    # Identify a worker id inside snapshot payloads.
    for key in ("session_id", "worker_id", "id"):
        value = worker.get(key)
        if value:
            return str(value)
    return None


def _select_workers_to_keep(
    last_seen: dict[str, datetime],
    last_state: dict[str, str],
    current_ts: datetime,
    recent_hours: int,
) -> set[str]:
    # Build the retention set from active and recently active workers.
    keep_ids = {worker_id for worker_id, state in last_state.items() if state == "active"}
    if recent_hours <= 0:
        return keep_ids
    threshold = current_ts.astimezone(timezone.utc) - timedelta(hours=recent_hours)
    for worker_id, seen in last_seen.items():
        if seen >= threshold:
            keep_ids.add(worker_id)
    return keep_ids


def _filter_retained_events(handle, keep_ids: set[str]) -> list[str]:
    # Filter events to only those associated with retained workers.
    retained: list[str] = []
    handle.seek(0)
    for line in handle:
        line = line.strip()
        if not line:
            continue
        # Skip malformed JSON entries without failing rotation.
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = _parse_event(payload)
        if event.type == "snapshot":
            # Retain only snapshot entries related to preserved workers.
            filtered = _filter_snapshot_event(event, keep_ids)
            if filtered is None:
                continue
            retained.append(json.dumps(_event_to_dict(filtered), ensure_ascii=False))
            continue
        if event.worker_id and event.worker_id in keep_ids:
            retained.append(json.dumps(_event_to_dict(event), ensure_ascii=False))
    return retained


def _filter_snapshot_event(event: WorkerEvent, keep_ids: set[str]) -> WorkerEvent | None:
    # Drop snapshot entries that don't include retained workers.
    data = dict(event.data or {})
    workers = data.get("workers")
    if not isinstance(workers, list):
        return None
    filtered_workers = []
    for worker in workers:
        if not isinstance(worker, dict):
            continue
        worker_id = _snapshot_worker_id(worker)
        if worker_id and worker_id in keep_ids:
            filtered_workers.append(worker)
    if not filtered_workers:
        return None
    data["workers"] = filtered_workers
    data["count"] = len(filtered_workers)
    return WorkerEvent(ts=event.ts, type=event.type, worker_id=None, data=data)


def _latest_event_timestamp(events: list[WorkerEvent]) -> datetime:
    # Use the newest timestamp in a batch to evaluate rotation boundaries.
    latest = datetime.min.replace(tzinfo=timezone.utc)
    for event in events:
        try:
            event_ts = _parse_timestamp(event.ts)
        except ValueError:
            continue
        if event_ts > latest:
            latest = event_ts
    if latest == datetime.min.replace(tzinfo=timezone.utc):
        return datetime.now(timezone.utc)
    return latest


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
