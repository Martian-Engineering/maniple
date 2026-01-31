# Unified Worker State: list_workers recovery + worker_events API

Status: Proposed
Date: 2026-01-31
Issue: cic-bbd

## Context

Today we have two sources of worker state:

- `SessionRegistry` (in-memory, cleared on restart) drives `list_workers`.
- `events.jsonl` (persistent) stores snapshots + transitions from `WorkerPoller` in
  `src/claude_team/poller.py`, with helpers in `src/claude_team/events.py`.

After restart, `list_workers` returns empty even though workers may still exist.
External consumers resort to parsing `events.jsonl` because MCP exposes no event API.

## Goals

- `list_workers` should return a useful view after restart by recovering from the
  latest persisted events.
- Expose event log data via an MCP tool (`worker_events`) with a stable response
  schema for consumers.
- Keep changes additive and avoid breaking existing client expectations.

## Non-Goals

- Perfect real-time accuracy after restart (terminal liveness still requires
  backend adoption).
- Changing polling cadence or event log format.
- Backfilling old historical events beyond what exists in `events.jsonl`.

## Part 1: list_workers recovery API surface

### Proposed recovery entry point

Add a registry-level recovery API that merges the event log into the registry
state without overwriting live sessions.

Suggested API shape (names illustrative):

- `SessionRegistry.recover_from_events(snapshot: dict | None, events: list[WorkerEvent]) -> RecoveryReport`
  - **Input:**
    - `snapshot`: output of `get_latest_snapshot()` (may be `None`).
    - `events`: `read_events_since(snapshot_ts)` (may be empty).
  - **Behavior:**
    - If a session already exists in the registry, do not override it.
    - If a session is only in the event log, create a lightweight recovered entry.
    - If a session is closed by events, mark it closed in recovered state.
  - **Output:**
    - `RecoveryReport` with counts (added, updated, ignored) and timestamp used.

### Recovered session representation

Recovered entries should be distinguishable and safe for read-only usage.

Proposed interface (implementation can vary):

- A new lightweight `RecoveredSession` object that implements:
  - `session_id`, `name`, `project_path`, `terminal_id`, `agent_type` (from snapshot)
  - `status` mapped from event state (see mapping below)
  - `last_activity` / `created_at` from snapshot when available
  - `to_dict()` for MCP output
  - `is_idle()` returns `None` or uses snapshot state only (never touches JSONL)
- `SessionRegistry.list_all()` returns a merged list of:
  - live `ManagedSession` objects, plus
  - recovered entries not present in the registry

### State mapping

Event log snapshots record:

- `state`: `"idle"` or `"active"` (from `detect_worker_idle`)
- `status`: `"spawning" | "ready" | "busy"` (from `ManagedSession.to_dict()`)

Recommended mapping rules:

- Prefer snapshot `state` for consistency across restarts.
- Map `state` -> `SessionStatus` for output:
  - `idle` -> `ready`
  - `active` -> `busy`
  - `closed` -> (new virtual state or keep `busy` + `state="closed"`)

To preserve backwards compatibility, keep the existing `status` field but add
new fields so clients can detect recovery state explicitly:

- `source`: `"registry" | "event_log"`
- `event_state`: `"idle" | "active" | "closed"` (when recovered)
- `recovered_at`: ISO timestamp when recovery occurred
- `last_event_ts`: ISO timestamp of the last applied event

### Recovery timing

Two compatible entry points:

1. **Eager (startup):** in server boot, call recovery once and seed the registry.
2. **Lazy (first list):** in `list_workers`, if registry is empty, perform recovery
   then return merged output.

Recommendation: **eager** recovery at startup for predictable behavior, plus a
lazy fallback in `list_workers` for safety if startup recovery fails.

### Tradeoffs (list_workers recovery)

- **Pros:** `list_workers` no longer empty after restart; preserves metadata and
  session IDs for monitoring tools.
- **Cons:** recovered entries may be stale; terminal handles are missing, so
  control actions (send/close) still require adoption.
- **Risk mitigation:** mark `source=event_log` and include `last_event_ts` to
  communicate staleness to clients.

## Part 2: worker_events MCP tool API surface

### Proposed tool signature

Tool name: `worker_events`

Parameters:

- `since` (string | null): ISO 8601 timestamp; returns events at or after this
  time. If omitted, returns most recent events (bounded by `limit`).
- `limit` (int, default 1000): maximum number of events returned.
- `include_snapshot` (bool, default false): if true, include the latest snapshot
  event (even if it predates `since`) in the response.
- `include_summary` (bool, default false): include summary aggregates.
- `stale_threshold_minutes` (int, default 10): used only when
  `include_summary=true` to classify “stuck” workers.

### Proposed response shape

```
{
  "events": [
    {"ts": "...", "type": "snapshot|worker_started|worker_idle|worker_active|worker_closed",
     "worker_id": "...", "data": { ... }}
  ],
  "count": 123,
  "summary": {
    "started": ["id1", "id2"],
    "closed": ["id3"],
    "idle": ["id4"],
    "active": ["id5"],
    "stuck": ["id6"],
    "last_event_ts": "..."
  },
  "snapshot": {
    "ts": "...",
    "data": {"count": 2, "workers": [ ... ]}
  }
}
```

### Summary semantics

- **started/closed/idle/active** lists come from the returned event window.
- **stuck** is derived from the latest known state (snapshot + events) where:
  - worker is `active`, and
  - last activity is older than `stale_threshold_minutes`.
- **last_event_ts** is the newest event timestamp in the response.

This aligns with the intent of the former `poll_worker_changes` output while
exposing the raw events for richer client-side handling.

### Tradeoffs (worker_events)

- **Pros:** simple API around existing persistence; consumers can poll with a
  timestamp cursor instead of parsing JSONL.
- **Cons:** no stable event IDs; clients should track the last timestamp and may
  receive duplicates if multiple events share the same timestamp.
- **Mitigation:** include `last_event_ts` and recommend clients request
  `since=last_event_ts` and de-duplicate by `(ts, type, worker_id)`.

## Open Questions

- Do we want a new explicit `SessionStatus.CLOSED` for recovered entries, or is
  `status` plus `event_state="closed"` sufficient?
- Should recovery include an opt-in `include_closed` flag to hide sessions that
  have closed since the last snapshot?
- Should `worker_events` support an optional `project_filter` (parity with
  `list_workers`)?

## Recommendation

Implement recovery as an additive merge from `events.get_latest_snapshot()` plus
`events.read_events_since(snapshot_ts)`, surfaced via a registry recovery helper
and a new `RecoveredSession` type. Add explicit `source` and `event_state` fields
in `list_workers` output to communicate provenance and staleness.

Expose a new `worker_events` MCP tool with a minimal `since/limit` API and an
optional summary section for consumers that want quick status deltas.
