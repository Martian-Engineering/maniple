# Changelog

All notable changes to claude-team will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.0] - 2026-02-06

### Changed
- **Renamed `bead` parameter to `issue_id`**: `spawn_workers` now uses `issue_id` instead of `bead` for tracker-agnostic issue assignment. `bead` is still accepted as a deprecated alias. (#23)

### Documentation
- **`coordinator_annotation` clarified**: Documented that this field is coordinator-facing metadata, not task delivery. Tasks must be sent via follow-up message. (#22)
- **`agent_type` parameter guidance**: Added note that this field should not be specified unless explicitly requested by the user.
- **`worktree.base` documentation improved**: Clearer explanation of base branch resolution for worktrees. (#24)

## [Unreleased]

## [0.9.2] - 2026-02-05

### Fixed
- **Codex worker log discovery**: `read_worker_logs` no longer returns wrong session data (e.g. coordinator's own logs) for Codex workers. Removed blind `find_codex_session_file()` fallback that grabbed the most recent Codex JSONL globally regardless of session ownership.
- **Codex JSONL path caching**: Codex workers now cache their JSONL path at spawn time (parity with Claude workers), via new `await_codex_marker_in_jsonl()` polling.
- **Discovery window**: Increased `max_age_seconds` from 600 (10 min) to 86400 (24h) for Codex session file scanning — workers can run for hours.
- **RecoveredSession crashes**: Fixed `discover_workers`, `adopt_worker`, and `spawn_workers` crashing with `'RecoveredSession' object has no attribute 'terminal_session'` when recovered sessions exist in the registry.

## [0.9.1] - 2026-02-04

### Fixed
- **MCP tool optional param validation**: All 9 MCP tools now accept `null` for optional parameters with defaults. MCP clients (e.g. mcporter) that send explicit `null` for omitted params no longer trigger pydantic validation errors.

## [0.9.0] - 2026-02-03

### Added
- **Event log recovery**: On startup, the registry reconstructs worker state from `events.jsonl`. `list_workers` now shows all known workers (live + recovered) instead of returning empty after restart.
  - `RecoveredSession` dataclass for restored workers (read-only, no terminal handle)
  - `RecoveryReport` with counts of added/skipped/closed sessions
  - Eager recovery at boot + lazy fallback in `list_workers`
- **`worker_events` MCP tool**: Query the event log programmatically with timestamp filters, summaries, stuck worker detection, and project filtering. Replaces shell-script parsing of `events.jsonl`.
- **`stale_threshold_minutes` config**: Configurable via `~/.claude-team/config.json` (`events.stale_threshold_minutes`, default: 10). `poll_worker_changes` reads from config when param not passed, tool param overrides.
- **`source` field in `list_workers`**: Distinguishes `"registry"` (live) vs `"event_log"` (recovered) workers.
- 98 new tests across 6 test files for recovery, worker_events, config, and poll_worker_changes.

### Changed
- **README**: Comprehensive rewrite — documents tmux backend, config file, Codex support, `poll_worker_changes`, HTTP mode, correct worktree paths, updated architecture diagram.

## [0.8.2] - 2026-02-02

### Fixed
- **tmux session naming**: Worktree paths no longer create separate tmux sessions per worker. Removed hash from session names — format is now `claude-team-{slug}` (e.g. `claude-team-pagedrop-infra`). All workers for the same project share one tmux session with separate windows.

## [0.8.0] - 2026-01-30

### Added
- **System-wide config file** (`~/.claude-team/config.json`): Centralized configuration replacing environment variables
  - Typed dataclasses with JSON validation
  - Version field for future migrations
  - Precedence: env var → config file → built-in default
- **Config CLI**: `claude-team config init|show|get|set` commands
- **Per-project tmux sessions**: Each project gets its own tmux session (`claude-team-<slug>-<hash>`) instead of a single shared session
  - Easier local monitoring — `tmux ls` shows projects separately
  - Discovery scans all tmux panes and filters by managed prefix

### Fixed
- Worktree branch/directory names capped at 30 chars to avoid filesystem limits
- Test isolation from user config file (tests no longer affected by `~/.claude-team/config.json`)

### Changed
- Tmux `list_sessions` and discovery now scan all sessions with prefix filter instead of targeting a single session

## [0.7.0] - 2026-01-29

### Added
- **Tmux terminal backend**: Run workers in tmux sessions instead of iTerm2
- Terminal backend abstraction layer (`TerminalBackend` protocol)
- Backend auto-detection: uses tmux if `$TMUX` is set, otherwise iTerm
- `CLAUDE_TEAM_TERMINAL_BACKEND` env var for explicit backend selection
- One tmux window per worker with descriptive naming (`<name> | <project> [<issue>]`)
- Tmux discovery and adoption of orphaned worker sessions
- Codex discovery/adopt fallbacks for tmux
- New test suite: `tests/test_tmux_backend.py`

### Fixed
- Close Codex via Ctrl+C instead of `/exit`
- `wait_idle_workers` Codex idle detection
- Explicit worktree config now fails loudly instead of silent fallback

### Changed
- All tools refactored to operate on `TerminalSession` rather than iTerm-specific handles
- Default behavior (no explicit worktree config) still falls back but returns warnings

## [0.6.1] - 2026-01-21

### Fixed
- Correct Codex skip-permissions flag (use `--dangerously-bypass-approvals-and-sandbox`)

## [0.6.0] - 2026-01-21

### Added
- **Issue tracker abstraction**: Support for both Beads and Pebbles issue trackers
- Auto-detection of issue tracker based on project structure (`.beads/` vs `.pebbles/`)
- `issue_tracker_help` tool replaces `bd_help` with tracker-agnostic guidance
- Comprehensive test suite for issue tracker detection and integration

### Changed
- Worker prompts now use generic issue tracker commands instead of hardcoded Beads
- Worktree detection improved with better branch name parsing

## [0.5.0] - 2026-01-13

### Added
- Handle worktree name collisions with incrementing suffix (e.g., `feature-1`, `feature-2`)

## [0.4.0] - 2026-01-13

### Added
- **Codex support**: spawn, message, and monitor Codex workers
- Multi-agent CLI abstraction layer
- `CLAUDE_TEAM_CODEX_COMMAND` env var for custom Codex binary
- Codex JSONL schema and parsing
- Codex idle detection
- Star Trek duos to worker name sets

### Fixed
- Don't require `claude-team` iTerm2 profile to exist
- Codex ready patterns for v0.80.0
- Dynamic delay for Codex based on prompt length
- `read_worker_logs` now works for Codex sessions

## [0.3.2] - 2026-01-06

### Fixed
- Skip `--settings` flag for custom commands like Happy

## [0.3.1] - 2026-01-06

### Added
- `CLAUDE_TEAM_COMMAND` env var support for custom Claude binaries (e.g., Happy)

## [0.3.0] - 2026-01-05

### Added
- HTTP mode (`--http`) for persistent state across requests
- Streamable HTTP transport for MCP
- launchd integration for running as background service

### Changed
- Server can now run as persistent HTTP service instead of stdio-only

## [0.2.1] - 2026-01-04

### Fixed
- Corrected `close_workers` docstring about branch retention

## [0.2.0] - 2026-01-03

### Added
- Git worktree support for isolated worker branches
- Worker state persistence

## [0.1.0] - 2025-12-15

### Added
- Initial release
- Spawn and manage multiple Claude Code sessions via iTerm2
- Worker monitoring and log reading
- Basic MCP server implementation

[Unreleased]: https://github.com/Martian-Engineering/claude-team/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/Martian-Engineering/claude-team/compare/v0.8.2...v0.9.0
[0.8.2]: https://github.com/Martian-Engineering/claude-team/compare/v0.8.0...v0.8.2
[0.8.0]: https://github.com/Martian-Engineering/claude-team/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Martian-Engineering/claude-team/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/Martian-Engineering/claude-team/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/Martian-Engineering/claude-team/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Martian-Engineering/claude-team/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Martian-Engineering/claude-team/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/Martian-Engineering/claude-team/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/Martian-Engineering/claude-team/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Martian-Engineering/claude-team/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Martian-Engineering/claude-team/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Martian-Engineering/claude-team/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Martian-Engineering/claude-team/releases/tag/v0.1.0
