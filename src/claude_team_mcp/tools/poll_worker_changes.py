"""
Poll worker changes tool.

Provides poll_worker_changes for reading worker event log updates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from claude_team import events as events_module
from claude_team.events import WorkerEvent

if TYPE_CHECKING:
    from ..server import AppContext

from ..utils import error_response


# Parse ISO timestamps for query filtering and event handling.
def _parse_iso_timestamp(value: str) -> datetime | None:
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


# Convert a WorkerEvent into a JSON-serializable payload.
def _serialize_event(event: WorkerEvent) -> dict:
    return {
        "ts": event.ts,
        "type": event.type,
        "worker_id": event.worker_id,
        "data": event.data,
    }


# Extract a worker display name from event data.
def _event_name(event: WorkerEvent) -> str:
    data = event.data or {}
    for key in ("name", "worker_name", "session_name"):
        value = data.get(key)
        if value:
            return str(value)
    return event.worker_id or "unknown"


# Extract a project identifier from event data.
def _event_project(event: WorkerEvent) -> str | None:
    data = event.data or {}
    for key in ("project", "project_path"):
        value = data.get(key)
        if value:
            return str(value)
    return None


# Extract a bead/issue reference from event data.
def _event_bead(event: WorkerEvent) -> str | None:
    data = event.data or {}
    for key in ("bead", "issue", "issue_id"):
        value = data.get(key)
        if value:
            return str(value)
    return None


# Compute duration in minutes for a closed worker event.
def _duration_minutes(
    event: WorkerEvent,
    started_at: dict[str, datetime],
) -> int:
    data = event.data or {}
    # Use explicit duration fields when provided by the poller.
    duration = data.get("duration_min")
    if duration is not None:
        try:
            return max(0, int(duration))
        except (TypeError, ValueError):
            pass

    # Convert seconds to minutes when available.
    duration_seconds = data.get("duration_seconds") or data.get("duration_sec")
    if duration_seconds is not None:
        try:
            return max(0, int(float(duration_seconds) / 60))
        except (TypeError, ValueError):
            pass

    # Fall back to timestamps if we can derive both endpoints.
    started_raw = data.get("started_at") or data.get("start_ts") or data.get("started_ts")
    started_ts = _parse_iso_timestamp(str(started_raw)) if started_raw else None
    if not started_ts and event.worker_id:
        started_ts = started_at.get(event.worker_id)

    end_ts = _parse_iso_timestamp(event.ts) if event.ts else None
    if started_ts and end_ts:
        return max(0, int((end_ts - started_ts).total_seconds() / 60))
    return 0


def register_tools(mcp: FastMCP) -> None:
    """Register poll_worker_changes tool on the MCP server."""

    @mcp.tool()
    async def poll_worker_changes(
        ctx: Context[ServerSession, "AppContext"],
        since: str | None = None,
        stale_threshold_minutes: int = 20,
        include_snapshots: bool = False,
    ) -> dict:
        """
        Poll worker event changes since a timestamp.

        Reads the worker events log, summarizes started/completed/stuck workers,
        and returns current idle/active counts.

        Args:
            since: ISO timestamp to filter events from (inclusive), or None for latest.
            stale_threshold_minutes: Minutes without activity before a worker is marked stuck.
            include_snapshots: Whether to include snapshot events in the response.

        Returns:
            Dict with:
                - events: List of worker events since timestamp (filtered by include_snapshots)
                - summary: started/completed/stuck worker summaries
                - active_count: Count of active (non-idle) workers
                - idle_count: Count of idle workers
                - poll_ts: Timestamp when poll was generated
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Validate inputs before reading the log.
        if stale_threshold_minutes <= 0:
            return error_response(
                "stale_threshold_minutes must be greater than 0",
                hint="Use a value like 20 to detect stuck workers",
            )

        parsed_since = None
        if since is not None and since.strip():
            parsed_since = _parse_iso_timestamp(since)
            if parsed_since is None:
                return error_response(
                    f"Invalid since timestamp: {since}",
                    hint="Use ISO format like 2026-01-27T11:40:00Z",
                )

        # Read recent events from the log (capped by events module defaults).
        events = events_module.read_events_since(parsed_since)

        # Optionally drop snapshot events to keep responses lighter.
        if not include_snapshots:
            events = [event for event in events if event.type != "snapshot"]

        # Track start times to estimate durations for closures.
        started_at: dict[str, datetime] = {}
        for event in events:
            if event.type == "worker_started" and event.worker_id:
                ts = _parse_iso_timestamp(event.ts)
                if ts:
                    started_at[event.worker_id] = ts

        # Build summary lists from event stream.
        started: list[dict] = []
        completed: list[dict] = []
        for event in events:
            if event.type == "worker_started":
                started.append({
                    "name": _event_name(event),
                    "project": _event_project(event),
                })
            elif event.type == "worker_closed":
                completed.append({
                    "name": _event_name(event),
                    "bead": _event_bead(event),
                    "duration_min": _duration_minutes(event, started_at),
                })

        # Compute current idle/active counts and detect stuck workers.
        stuck: list[dict] = []
        idle_count = 0
        active_count = 0
        now = datetime.now()
        threshold = stale_threshold_minutes
        for session in registry.list_all():
            is_idle = session.is_idle()
            if is_idle:
                idle_count += 1
            else:
                active_count += 1

            inactive_minutes = int((now - session.last_activity).total_seconds() / 60)
            if not is_idle and inactive_minutes >= threshold:
                stuck.append({
                    "name": session.name or session.session_id,
                    "inactive_minutes": inactive_minutes,
                })

        poll_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "events": [_serialize_event(event) for event in events],
            "summary": {
                "completed": completed,
                "stuck": stuck,
                "started": started,
            },
            "active_count": active_count,
            "idle_count": idle_count,
            "poll_ts": poll_ts,
        }
