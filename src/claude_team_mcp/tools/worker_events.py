"""
Worker events tool.

Provides worker_events for querying the event log with optional summary and snapshot.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from claude_team import events as events_module
from claude_team.events import WorkerEvent

if TYPE_CHECKING:
    from ..server import AppContext


def _parse_iso_timestamp(value: str) -> datetime | None:
    """Parse ISO timestamps for query filtering."""
    value = value.strip()
    if not value:
        return None
    # Normalize Zulu timestamps for fromisoformat.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Default to UTC when no timezone is provided.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_event(event: WorkerEvent) -> dict:
    """Convert a WorkerEvent into a JSON-serializable payload."""
    return {
        "ts": event.ts,
        "type": event.type,
        "worker_id": event.worker_id,
        "data": event.data,
    }


def _event_project(event: WorkerEvent) -> str | None:
    """Extract a project identifier from event data."""
    data = event.data or {}
    for key in ("project", "project_path"):
        value = data.get(key)
        if value:
            return str(value)
    return None


def _filter_by_project(events: list[WorkerEvent], project_filter: str) -> list[WorkerEvent]:
    """Filter events to only those matching the project filter."""
    filtered = []
    for event in events:
        project = _event_project(event)
        # Include events with no project (e.g. snapshots) or matching project.
        if project is None or project_filter in project:
            filtered.append(event)
    return filtered


def _build_summary(
    events: list[WorkerEvent],
    stale_threshold_minutes: int,
) -> dict:
    """
    Build summary from the event window.

    Returns:
        Dict with started, closed, idle, active, stuck lists and last_event_ts.
    """
    # Track worker states from events.
    started: list[str] = []
    closed: list[str] = []
    idle: list[str] = []
    active: list[str] = []

    # Track last known state and activity time per worker.
    last_state: dict[str, str] = {}
    last_activity: dict[str, datetime] = {}

    last_event_ts: str | None = None

    for event in events:
        # Track latest event timestamp.
        last_event_ts = event.ts

        worker_id = event.worker_id
        if not worker_id:
            # Handle snapshot events for state tracking.
            if event.type == "snapshot":
                _process_snapshot_for_summary(
                    event.data,
                    event.ts,
                    last_state,
                    last_activity,
                )
            continue

        # Update activity time.
        ts = _parse_iso_timestamp(event.ts)
        if ts:
            last_activity[worker_id] = ts

        if event.type == "worker_started":
            started.append(worker_id)
            last_state[worker_id] = "active"
        elif event.type == "worker_closed":
            closed.append(worker_id)
            last_state[worker_id] = "closed"
        elif event.type == "worker_idle":
            idle.append(worker_id)
            last_state[worker_id] = "idle"
        elif event.type == "worker_active":
            active.append(worker_id)
            last_state[worker_id] = "active"

    # Compute stuck workers: active with last_activity > threshold.
    stuck: list[str] = []
    now = datetime.now(timezone.utc)
    threshold_seconds = stale_threshold_minutes * 60

    for worker_id, state in last_state.items():
        if state != "active":
            continue
        activity_ts = last_activity.get(worker_id)
        if activity_ts is None:
            continue
        elapsed = (now - activity_ts).total_seconds()
        if elapsed > threshold_seconds:
            stuck.append(worker_id)

    return {
        "started": started,
        "closed": closed,
        "idle": idle,
        "active": active,
        "stuck": stuck,
        "last_event_ts": last_event_ts,
    }


def _process_snapshot_for_summary(
    data: dict,
    event_ts: str,
    last_state: dict[str, str],
    last_activity: dict[str, datetime],
) -> None:
    """Update state tracking from a snapshot event."""
    workers = data.get("workers")
    if not isinstance(workers, list):
        return

    ts = _parse_iso_timestamp(event_ts)

    for worker in workers:
        if not isinstance(worker, dict):
            continue

        # Find worker ID from various possible keys.
        worker_id = None
        for key in ("session_id", "worker_id", "id"):
            value = worker.get(key)
            if value:
                worker_id = str(value)
                break

        if not worker_id:
            continue

        # Extract state from snapshot.
        state = worker.get("state")
        if isinstance(state, str) and state:
            last_state[worker_id] = state
            if ts and state == "active":
                last_activity[worker_id] = ts


def register_tools(mcp: FastMCP) -> None:
    """Register worker_events tool on the MCP server."""

    @mcp.tool()
    async def worker_events(
        ctx: Context[ServerSession, "AppContext"],
        since: str | None = None,
        limit: int = 1000,
        include_snapshot: bool = False,
        include_summary: bool = False,
        stale_threshold_minutes: int = 10,
        project_filter: str | None = None,
    ) -> dict:
        """
        Query worker events from the event log.

        Provides access to the persisted worker event log with optional summary
        aggregation and snapshot inclusion. This is the primary API for external
        consumers to monitor worker lifecycle events.

        Args:
            since: ISO 8601 timestamp; returns events at or after this time.
                If omitted, returns most recent events (bounded by limit).
            limit: Maximum number of events returned (default 1000).
            include_snapshot: If true, include the latest snapshot event in response.
            include_summary: If true, include summary aggregates (started, closed,
                idle, active, stuck lists).
            stale_threshold_minutes: Minutes without activity before a worker is
                marked stuck (only used when include_summary=true, default 10).
            project_filter: Optional project path substring to filter events.

        Returns:
            Dict with:
                - events: List of worker events [{ts, type, worker_id, data}]
                - count: Number of events returned
                - summary: (if include_summary) Aggregates from event window:
                    - started: worker IDs that started
                    - closed: worker IDs that closed
                    - idle: worker IDs that became idle
                    - active: worker IDs that became active
                    - stuck: active workers with last_activity > stale_threshold
                    - last_event_ts: newest event timestamp
                - snapshot: (if include_snapshot) Latest snapshot {ts, data}
        """
        # Parse the since timestamp if provided.
        parsed_since = None
        if since is not None and since.strip():
            parsed_since = _parse_iso_timestamp(since)
            if parsed_since is None:
                return {
                    "error": f"Invalid since timestamp: {since}",
                    "hint": "Use ISO format like 2026-01-27T11:40:00Z",
                }

        # Read events from the log.
        events = events_module.read_events_since(parsed_since, limit=limit)

        # Apply project filter if specified.
        if project_filter:
            events = _filter_by_project(events, project_filter)

        # Build the response.
        response: dict = {
            "events": [_serialize_event(event) for event in events],
            "count": len(events),
        }

        # Add summary if requested.
        if include_summary:
            response["summary"] = _build_summary(events, stale_threshold_minutes)

        # Add snapshot if requested.
        if include_snapshot:
            snapshot_data = events_module.get_latest_snapshot()
            if snapshot_data is not None:
                # Find the timestamp from the snapshot data or use a sentinel.
                snapshot_ts = snapshot_data.get("ts")
                response["snapshot"] = {
                    "ts": snapshot_ts,
                    "data": snapshot_data,
                }
            else:
                response["snapshot"] = None

        return response
