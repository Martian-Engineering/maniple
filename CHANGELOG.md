# Changelog

All notable changes to claude-team will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.2] - 2026-01-13

### Fixed
- Codex ready patterns updated for v0.80.0
- Dynamic delay for Codex based on prompt length
- Agent-specific timing in spawn_workers for Codex prompt delivery

## [0.3.1] - 2026-01-10

### Added
- Codex support for `message_workers`
- `CLAUDE_TEAM_CODEX_COMMAND` env var support
- Codex idle detection

### Fixed
- `read_worker_logs` now works for Codex sessions
- Codex interactive mode with session file polling

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
