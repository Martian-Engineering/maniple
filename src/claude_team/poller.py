"""Background poller for worker state snapshots."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from . import events
from .idle_detection import detect_worker_idle

logger = logging.getLogger("claude-team-poller")

WorkerState = Literal["idle", "active"]


# Minimal registry interface used by WorkerPoller.
class _RegistryLike(Protocol):
    def list_all(self) -> list["_SessionLike"]:
        ...


# Minimal session interface used by WorkerPoller.
class _SessionLike(Protocol):
    session_id: str
    agent_type: Literal["claude", "codex"]
    project_path: str
    claude_session_id: str | None
    output_path: Path | None
    message_count: int | None
    last_message_count: int | None
    last_message_timestamp: float | None
    pid: int | None
    is_idle: bool

    def to_dict(self) -> dict:
        ...


# Snapshot of a worker at a point in time.
@dataclass(frozen=True)
class _WorkerSnapshot:
    session_id: str
    state: WorkerState
    info: dict


def _isoformat_zulu(value: datetime) -> str:
    # Format timestamps with a Z suffix for UTC.
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sanitize_for_json(obj: object) -> object:
    # Recursively sanitize an object for JSON serialization.
    # Removes non-serializable types like asyncio Futures, methods, etc.
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if callable(obj):
        # Skip methods, functions, lambdas
        return None
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(item) for item in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    # For any other type, try to convert to string, else skip
    try:
        return str(obj)
    except Exception:
        return None


def _build_snapshot(registry: _RegistryLike) -> dict[str, _WorkerSnapshot]:
    # Capture current worker states from the registry.
    snapshots: dict[str, _WorkerSnapshot] = {}
    for session in registry.list_all():
        info = _sanitize_for_json(session.to_dict())
        is_idle, _ = detect_worker_idle(session, idle_threshold_seconds=300)
        info["is_idle"] = is_idle
        state: WorkerState = "idle" if is_idle else "active"
        snapshots[session.session_id] = _WorkerSnapshot(session.session_id, state, info)
    return snapshots


def _snapshot_payload(snapshots: dict[str, _WorkerSnapshot]) -> dict:
    # Build a full snapshot payload for persistence.
    workers = []
    for snapshot in snapshots.values():
        payload = dict(snapshot.info)
        payload["state"] = snapshot.state
        workers.append(payload)
    return {"count": len(workers), "workers": workers}


def _transition_payload(snapshot: _WorkerSnapshot, previous_state: WorkerState | None) -> dict:
    # Build transition data payload for a worker event.
    payload = dict(snapshot.info)
    payload["state"] = snapshot.state
    payload["previous_state"] = previous_state
    return payload


def _closed_payload(snapshot: _WorkerSnapshot) -> dict:
    # Build payload for a worker_closed event using the last known state.
    payload = dict(snapshot.info)
    payload["state"] = "closed"
    payload["previous_state"] = snapshot.state
    return payload


def _build_transition_events(
    previous: dict[str, _WorkerSnapshot],
    current: dict[str, _WorkerSnapshot],
    timestamp: str,
) -> list[events.WorkerEvent]:
    # Compare snapshot sets and emit lifecycle transition events.
    results: list[events.WorkerEvent] = []
    previous_ids = set(previous)
    current_ids = set(current)

    # New sessions -> worker_started events.
    for session_id in current_ids - previous_ids:
        snapshot = current[session_id]
        results.append(events.WorkerEvent(
            ts=timestamp,
            type="worker_started",
            worker_id=session_id,
            data=_transition_payload(snapshot, None),
        ))

    # Removed sessions -> worker_closed events.
    for session_id in previous_ids - current_ids:
        snapshot = previous[session_id]
        results.append(events.WorkerEvent(
            ts=timestamp,
            type="worker_closed",
            worker_id=session_id,
            data=_closed_payload(snapshot),
        ))

    # Existing sessions -> idle/active transitions.
    for session_id in previous_ids & current_ids:
        before = previous[session_id]
        after = current[session_id]
        if before.state == after.state:
            continue
        event_type = "worker_idle" if after.state == "idle" else "worker_active"
        results.append(events.WorkerEvent(
            ts=timestamp,
            type=event_type,
            worker_id=session_id,
            data=_transition_payload(after, before.state),
        ))

    return results


class WorkerPoller:
    """Background poller that snapshots worker state and logs transitions."""

    def __init__(
        self,
        registry: _RegistryLike,
        poll_interval_seconds: int = 60,
        snapshot_interval_seconds: int = 300,
    ) -> None:
        """Initialize the poller with registry and polling cadence."""
        self._registry = registry
        self._poll_interval_seconds = poll_interval_seconds
        self._snapshot_interval_seconds = snapshot_interval_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_snapshot: dict[str, _WorkerSnapshot] = {}
        self._last_snapshot_event_at: float | None = None

    def start(self) -> None:
        """Start the background polling task."""
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="worker-poller")

    async def stop(self) -> None:
        """Stop the background polling task."""
        if not self._task:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        # Poll until stop is requested, logging events along the way.
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Worker poller failed: %s", exc)
            await self._wait_for_next_tick()

    async def _wait_for_next_tick(self) -> None:
        # Wait for either the next poll interval or a stop request.
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval_seconds)
        except asyncio.TimeoutError:
            return

    def _poll_once(self) -> None:
        # Capture a snapshot, diff it, and persist any resulting events.
        # Timestamp both for events and snapshot cadence.
        now_iso = _isoformat_zulu(datetime.now(timezone.utc))
        now_monotonic = time.monotonic()
        # Snapshot current registry and compute transitions.
        current_snapshot = _build_snapshot(self._registry)
        transitions = _build_transition_events(self._last_snapshot, current_snapshot, now_iso)

        # Emit periodic full snapshot for recovery.
        if self._should_emit_snapshot(now_monotonic):
            transitions.append(events.WorkerEvent(
                ts=now_iso,
                type="snapshot",
                worker_id=None,
                data=_snapshot_payload(current_snapshot),
            ))
            self._last_snapshot_event_at = now_monotonic

        # Persist any events in a single batch.
        if transitions:
            events.append_events(transitions)

        # Update the in-memory snapshot for the next diff.
        self._last_snapshot = current_snapshot

    def _should_emit_snapshot(self, now_monotonic: float) -> bool:
        # Decide whether it's time to emit a full snapshot event.
        last = self._last_snapshot_event_at
        if last is None:
            return True
        return (now_monotonic - last) >= self._snapshot_interval_seconds
