# Claude Team MCP Server

An MCP server that enables a "manager" Claude Code session to spawn and orchestrate multiple "worker" Claude Code sessions via iTerm2.

## ⚠️ IMPORTANT: Running Tests

**Always use `uv run pytest` to run tests.** Do NOT use `pytest` directly.

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_tmux_backend.py

# Run with verbose output
uv run pytest -v
```

If you get "pytest not found" or similar errors, run `uv sync` first to install dependencies.

**DO NOT use:** `pytest`, `python -m pytest`, or `python3 -m pytest` — these will fail.

## Project Structure

```
src/claude_team_mcp/
├── server.py                  # FastMCP server entry point, registers all tools
├── registry.py                # Worker tracking (ManagedSession, SessionRegistry)
├── session_state.py           # JSONL parsing for Claude conversation logs
├── iterm_utils.py             # Low-level iTerm2 API wrappers
├── idle_detection.py          # Stop hook completion detection
├── issue_tracker/             # Issue tracker abstraction + detection
├── profile.py                 # iTerm2 profile/theme management
├── colors.py                  # Golden ratio tab color generation
├── formatting.py              # Title/badge formatting utilities
├── names.py                   # Worker name generation (themed name sets)
├── worker_prompt.py           # Worker system prompt generation
├── worktree.py                # Git worktree management
├── subprocess_cache.py        # Cached subprocess calls
├── tools/                     # MCP tool implementations (one per file)
│   ├── spawn_workers.py       # Create worker sessions
│   ├── list_workers.py        # List managed workers
│   ├── examine_worker.py      # Get detailed worker status
│   ├── message_workers.py     # Send prompts to workers
│   ├── check_idle_workers.py  # Check if workers are idle
│   ├── wait_idle_workers.py   # Wait for workers to finish
│   ├── read_worker_logs.py    # Get conversation history
│   ├── annotate_worker.py     # Add coordinator notes
│   ├── close_workers.py       # Terminate workers
│   ├── discover_workers.py    # Find orphaned iTerm sessions
│   ├── adopt_worker.py        # Import orphaned sessions
│   ├── list_worktrees.py      # List git worktrees
│   └── bd_help.py             # Beads quick reference (Pebbles uses pb help)
└── utils/                     # Shared utilities
    ├── constants.py           # Shared constants
    ├── errors.py              # Error response helpers
    └── worktree_detection.py  # Worktree path detection

commands/                      # Slash commands for Claude Code
scripts/                       # Utility scripts
tests/                         # Pytest unit tests
```

## Makefile Targets

```bash
make help                  # Show available targets
make install-commands      # Install slash commands to ~/.claude/commands/
make install-commands-force # Overwrite existing commands
make test                  # Run pytest
make sync                  # Sync dependencies
```

## Key Modules

| Module | Purpose |
|--------|---------|
| `server.py` | Entry point; registers all MCP tools from `tools/` directory |
| `registry.py` | Tracks workers, states: SPAWNING → READY → BUSY → CLOSED. `resolve()` accepts internal ID, terminal ID, or name |
| `session_state.py` | Parses Claude's JSONL files at `~/.claude/projects/{slug}/{session}.jsonl` |
| `iterm_utils.py` | Terminal control: `send_text`, `send_prompt`, window/pane creation |
| `idle_detection.py` | Stop hook completion detection via JSONL markers |
| `names.py` | Themed name sets (Marx Brothers, LOTR, etc.) for worker identification |
| `worktree.py` | Git worktree creation/cleanup for isolated worker branches |

## Critical Implementation Details

### Worker Identification
Workers can be referenced by any of three identifiers:
- **Internal ID**: Short hex string (e.g., `3962c5c4`)
- **Terminal ID**: Prefixed iTerm UUID (e.g., `iterm:6D2074A3-2D5B-4823-B257-18721A7F5A04`)
- **Worker name**: Human-friendly name (e.g., `Groucho`, `Aragorn`)

All tools accept any of these formats via `registry.resolve()`.

### Enter Key Handling
**Use `\x0d` (carriage return) for Enter, NOT `\n`**
- `\n` creates a newline in input buffer but doesn't submit
- `\x0d` triggers actual Enter keypress
- Multi-line text requires delays before Enter (bracketed paste mode)

### JSONL Session Discovery
Claude stores conversations at:
```
~/.claude/projects/{project-slug}/{session-id}.jsonl
```
Where `{project-slug}` = project path with `/` → `-` (e.g., `/Users/josh/code` → `-Users-josh-code`)

### Idle Detection (Stop Hooks)
Workers are spawned with a stop hook that fires when Claude finishes responding. The hook writes a marker to the JSONL file that `idle_detection.py` watches for. This is the primary completion detection mechanism.

### Layout Options
- `single`: 1 pane, full window (main)
- `vertical`: 2 panes side by side (left, right)
- `horizontal`: 2 panes stacked (top, bottom)
- `quad`: 4 panes in 2x2 grid (top_left, top_right, bottom_left, bottom_right)
- `triple_vertical`: 3 panes side by side (left, middle, right)

## Running & Testing

```bash
# Sync dependencies (with dev tools)
uv sync --group dev

# Run tests
uv run --group dev pytest

# Run server directly (debugging)
uv run python -m claude_team_mcp
```

## Requirements
- macOS with iTerm2 (Python API enabled)
- Python 3.11+
- uv package manager

