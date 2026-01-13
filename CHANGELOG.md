# Changelog

All notable changes to claude-team will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Multi-agent CLI abstraction layer
- Codex support: spawn, message, and monitor Codex workers
- `CLAUDE_TEAM_CODEX_COMMAND` env var for custom Codex binary
- Codex JSONL schema and parsing
- Codex idle detection

### Fixed
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

[Unreleased]: https://github.com/Martian-Engineering/claude-team/compare/v0.3.2...HEAD
[0.3.2]: https://github.com/Martian-Engineering/claude-team/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/Martian-Engineering/claude-team/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Martian-Engineering/claude-team/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Martian-Engineering/claude-team/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Martian-Engineering/claude-team/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Martian-Engineering/claude-team/releases/tag/v0.1.0
