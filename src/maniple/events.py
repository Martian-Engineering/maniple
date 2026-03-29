"""Event log persistence for worker lifecycle activity."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import logging
import json
import os
from pathlib import Path
from typing import Literal

from maniple_mcp.config import ConfigError, EventsConfig, load_config
from maniple_mcp.utils.env_vars import get_int_env_with_fallback

try:
    import fcntl
except ImportError:  # pragma: no cover - platform-specific
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - platform-specific
    msvcrt = None

logger = logging.getLogger("maniple")

# Cache rotation config to avoid re-reading config.json on every append_events call.
_rotation_config_cache: tuple[float, EventsConfig] | None = None
_ROTATION_CONFIG_TTL = 60.0  # seconds

EventType = Literal[
    "snapshot",
    "worker_started",
    "worker_idle",
    "worker_active",
    "worker_closed",
]


def _load_rotation_config() -> EventsConfig:
    # Resolve rotation defaults from config, applying env overrides.
    # Cached for _ROTATION_CONFIG_TTL seconds to avoid re-reading config.json
    # on every append_events call (hot write path).
    import time

    global _rotation_config_cache
    now = time.monotonic()
    if _rotation_config_cache is not None:
        cached_at, cached_config = _rotation_config_cache
        if now - cached_at < _ROTATION_CONFIG_TTL:
            return cached_config

    try:
        config = load_config()
        events_config = config.events
    except ConfigError as exc:
        logger.warning(
            "Invalid config file; using default event rotation config: %s", exc
        )
        events_config = EventsConfig()
    result = EventsConfig(
        max_size_mb=get_int_env_with_fallback(
            "MANIPLE_EVENTS_MAX_SIZE_MB",
            "CLAUDE_TEAM_EVENTS_MAX_SIZE_MB",
            default=events_config.max_size_mb,
        ),
        recent_hours=get_int_env_with_fallback(
            "MANIPLE_EVENTS_RECENT_HOURS",
            "CLAUDE_TEAM_EVENTS_RECENT_HOURS",
            default=events_config.recent_hours,
        ),
    )
    _rotation_config_cache = (now, result)
    return result


@dataclass
class WorkerEvent:
    """Represents a persisted worker event."""

    ts: str
    type: EventType
    worker_id: str | None
    data: dict


def get_events_path() -> Path:
    """Returns the events JSONL path, creating parent dir if needed."""
    from maniple.paths import resolve_data_dir

    base_dir = resolve_data_dir()
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
    incoming_bytes = len(block.encode("utf-8"))
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
                incoming_bytes=incoming_bytes,
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
    # Use deque with maxlen for O(1) eviction instead of list.pop(0) which is O(n).
    events: deque[WorkerEvent] = deque(maxlen=limit)

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

    return list(events)


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
                incoming_bytes=0,
            )
        finally:
            _unlock_file(handle)


@dataclass
class EventBackupPruneReport:
    """Summary of pruning rotated event log backups (events.*.jsonl)."""

    deleted_count: int
    deleted_bytes: int
    kept_count: int
    kept_bytes: int
    deleted_paths: list[Path]


def prune_event_backups(
    *,
    keep_days: int | None = None,
    max_total_size_mb: int | None = None,
    now: datetime | None = None,
    dry_run: bool = True,
) -> EventBackupPruneReport:
    """
    Prune rotated event log backups in the events directory.

    This targets backup shards produced by rotation (e.g. events.2026-01-28.jsonl,
    events.2026-01-28.1.jsonl). The live log (events.jsonl) is never removed.

    Args:
        keep_days: If set, delete backups older than this many days (by mtime).
        max_total_size_mb: If set, cap total backup size by deleting oldest files first.
        now: Time reference for keep_days (defaults to current UTC time).
        dry_run: When True, do not delete; only report what would be deleted.
    """
    events_path = get_events_path()
    base_dir = events_path.parent
    current_ts = now or datetime.now(timezone.utc)

    candidates = _list_event_backups(base_dir)
    items: list[tuple[Path, float, int]] = []
    for path in candidates:
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        items.append((path, stat.st_mtime, stat.st_size))

    # Oldest-first ordering for deletion decisions.
    items.sort(key=lambda row: (row[1], row[0].name))

    keep_set: set[Path] = {path for path, _, _ in items}
    delete_set: set[Path] = set()

    if keep_days is not None and keep_days >= 0:
        cutoff = (current_ts - timedelta(days=keep_days)).timestamp()
        for path, mtime, _size in items:
            if mtime < cutoff:
                delete_set.add(path)
                keep_set.discard(path)

    if max_total_size_mb is not None and max_total_size_mb >= 0:
        cap_bytes = max_total_size_mb * 1024 * 1024
        # Compute size after keep_days filtering, then delete oldest until under cap.
        kept_items = [(p, mt, sz) for (p, mt, sz) in items if p in keep_set]
        total = sum(sz for _p, _mt, sz in kept_items)
        for path, _mtime, size in kept_items:
            if total <= cap_bytes:
                break
            delete_set.add(path)
            keep_set.discard(path)
            total -= size

    deleted_paths = sorted(delete_set, key=lambda p: p.name)
    deleted_bytes = 0
    if not dry_run:
        for path in deleted_paths:
            try:
                deleted_bytes += path.stat().st_size
            except FileNotFoundError:
                pass
            try:
                path.unlink()
            except FileNotFoundError:
                continue

    kept_bytes = 0
    for path in keep_set:
        try:
            kept_bytes += path.stat().st_size
        except FileNotFoundError:
            continue

    return EventBackupPruneReport(
        deleted_count=len(deleted_paths),
        deleted_bytes=deleted_bytes,
        kept_count=len(keep_set),
        kept_bytes=kept_bytes,
        deleted_paths=deleted_paths,
    )


def _list_event_backups(base_dir: Path) -> list[Path]:
    # List backup shards produced by rotation (excluding the live events.jsonl).
    backups: list[Path] = []
    for pattern in ("events.*.jsonl", "events.*.jsonl.gz"):
        for path in base_dir.glob(pattern):
            if path.name == "events.jsonl":
                continue
            backups.append(path)
    # De-dup in case a path matches multiple patterns.
    return sorted(set(backups), key=lambda p: p.name)


def _rotate_events_log_locked(
    handle,
    path: Path,
    current_ts: datetime,
    max_size_mb: int,
    recent_hours: int,
    incoming_bytes: int,
) -> None:
    # Rotate the log while holding the caller's lock.
    if not _should_rotate(path, current_ts, max_size_mb, incoming_bytes=incoming_bytes):
        return

    rotation_day = _rotation_day(path, current_ts)
    backup_path = _backup_path(path, rotation_day)

    last_seen, last_state, latest_snapshot = _copy_and_collect_activity(handle, backup_path)
    keep_ids = _select_workers_to_keep(last_seen, last_state, current_ts, recent_hours)
    cutoff_ts: datetime | None = None
    if recent_hours > 0:
        cutoff_ts = current_ts.astimezone(timezone.utc) - timedelta(hours=recent_hours)

    max_bytes = max_size_mb * 1024 * 1024 if max_size_mb > 0 else 0
    retained_lines = _filter_retained_events(
        handle,
        keep_ids,
        latest_snapshot=latest_snapshot,
        cutoff_ts=cutoff_ts,
        max_bytes=max_bytes,
    )

    # Reset the log to only retained events.
    # Truncate+rewrite is safe here: flock prevents concurrent writers, and
    # the backup file was already created above. If the process dies mid-write,
    # the backup has the full history for recovery.
    handle.seek(0)
    handle.truncate(0)
    if retained_lines:
        handle.write("\n".join(retained_lines) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _should_rotate(
    path: Path,
    current_ts: datetime,
    max_size_mb: int,
    incoming_bytes: int = 0,
) -> bool:
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
    current_size = path.stat().st_size
    # Rotate if the file is already too large, or if appending this batch would
    # push it over the threshold.
    return current_size > max_bytes or (
        incoming_bytes > 0 and (current_size + incoming_bytes) > max_bytes
    )


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


def _copy_and_collect_activity(
    handle,
    backup_path: Path,
) -> tuple[dict[str, datetime], dict[str, str], WorkerEvent | None]:
    # Copy the current log to a backup while recording worker activity.
    last_seen: dict[str, datetime] = {}
    last_state: dict[str, str] = {}
    latest_snapshot: WorkerEvent | None = None
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
            if event.type == "snapshot":
                latest_snapshot = event
            _track_event_activity(event, last_seen, last_state)
    return last_seen, last_state, latest_snapshot


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


def _filter_retained_events(
    handle,
    keep_ids: set[str],
    *,
    latest_snapshot: WorkerEvent | None,
    cutoff_ts: datetime | None,
    max_bytes: int,
) -> list[str]:
    # Filter events to those needed for recovery + recent history, bounded by max_bytes.
    #
    # Key behavior: keep only the most recent snapshot. Keeping every snapshot for
    # long-lived active workers prevents the log from shrinking, defeating size
    # rotation and producing endless backup shards.
    snapshot_line: str | None = None
    latest_snapshot_ts: datetime | None = None
    if latest_snapshot is not None:
        try:
            latest_snapshot_ts = _parse_timestamp(latest_snapshot.ts)
        except ValueError:
            latest_snapshot_ts = None
        filtered = _filter_snapshot_event(latest_snapshot, keep_ids)
        if filtered is not None:
            snapshot_line = json.dumps(_event_to_dict(filtered), ensure_ascii=False)

    retained_events: list[tuple[int, str, datetime, str]] = []
    last_by_worker: dict[str, tuple[int, datetime, str]] = {}
    handle.seek(0)
    position = 0
    for line in handle:
        position += 1
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
            continue
        if not event.worker_id or event.worker_id not in keep_ids:
            continue
        try:
            event_ts = _parse_timestamp(event.ts)
        except ValueError:
            continue
        rendered = json.dumps(_event_to_dict(event), ensure_ascii=False)
        last_by_worker[event.worker_id] = (position, event_ts, rendered)

        keep = False
        # Always keep post-snapshot events for recovery (state transitions since baseline).
        if latest_snapshot_ts is not None and event_ts >= latest_snapshot_ts:
            keep = True
        # Also keep recent history for active/recent workers.
        elif cutoff_ts is not None and event_ts >= cutoff_ts:
            keep = True

        if keep:
            retained_events.append((position, event.worker_id, event_ts, rendered))

    retained: list[str] = []
    if snapshot_line is not None:
        retained.append(snapshot_line)

    kept_workers = {worker_id for _pos, worker_id, _ts, _line in retained_events}
    # Ensure each kept worker has at least one event retained (use its last event),
    # even if it falls outside cutoff_ts. This avoids dropping active workers that
    # haven't emitted events recently while still bounding history.
    for worker_id in keep_ids:
        if worker_id in kept_workers:
            continue
        entry = last_by_worker.get(worker_id)
        if entry is None:
            continue
        pos, ts, line = entry
        retained_events.append((pos, worker_id, ts, line))

    # Keep file ordering stable.
    retained_events.sort(key=lambda row: row[0])
    retained.extend([line for _pos, _wid, _ts, line in retained_events])

    if max_bytes <= 0:
        return retained

    def _encoded_size(lines: list[str]) -> int:
        return sum(len(item.encode("utf-8")) + 1 for item in lines)

    if _encoded_size(retained) <= max_bytes:
        return retained

    # Compaction: latest snapshot + last event per worker.
    last_by_worker_compacted: dict[str, str] = {}
    last_ts_by_worker: dict[str, datetime] = {}
    for _pos, worker_id, event_ts, line in retained_events:
        prev_ts = last_ts_by_worker.get(worker_id)
        if prev_ts is None or event_ts >= prev_ts:
            last_ts_by_worker[worker_id] = event_ts
            last_by_worker_compacted[worker_id] = line

    worker_order: list[str] = []
    for _pos, worker_id, _ts, _line in retained_events:
        if worker_id not in worker_order:
            worker_order.append(worker_id)

    compacted: list[str] = []
    if snapshot_line is not None:
        compacted.append(snapshot_line)
    compacted.extend(
        [
            last_by_worker_compacted[wid]
            for wid in worker_order
            if wid in last_by_worker_compacted
        ]
    )

    if _encoded_size(compacted) <= max_bytes:
        return compacted

    # If we still can't fit, fall back to snapshot-only (or empty).
    return [snapshot_line] if snapshot_line is not None else []


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
