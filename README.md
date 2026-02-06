# Claude Team MCP Server

An MCP server that allows one Claude Code session to spawn and manage a team of other Claude Code (or Codex) sessions via terminal backends (tmux or iTerm2).

## Introduction

`claude-team` is an MCP server and a set of slash commands for allowing Claude Code to orchestrate a "team" of other Claude Code sessions. It uses terminal backends (tmux or iTerm2) to spawn new terminal sessions and run Claude Code within them.

### Why?

- **Parallelism:** Many development tasks can be logically parallelized, but managing that parallelism is difficult for humans with limited attention spans. Claude, meanwhile, is very effective at it.
- **Context management:** Offloading implementation to a worker gives the implementing agent a fresh context window (smarter), and keeps the manager's context free of implementation details.
- **Background work:** Sometimes you want to have Claude Code go research something or answer a question without blocking the main thread of work.
- **Visibility:** `claude-team` spawns real Claude Code sessions. You can watch them, interrupt and take control, or close them out.

But, *why not just use Claude Code sub-agents*, you ask? They're opaque -- they go off and do things and you, the user, cannot effectively monitor their work, interject, or continue a conversation with them. Using a full Claude Code session obviates this problem.

### Terminal Backends

`claude-team` supports two terminal backends:

| Backend | Platform | Status |
|---------|----------|--------|
| **tmux** | macOS, Linux | Primary. Auto-selected when running inside tmux. |
| **iTerm2** | macOS only | Fully supported. Requires Python API enabled. |

Backend selection order:
1. `CLAUDE_TEAM_TERMINAL_BACKEND` environment variable (`tmux` or `iterm`)
2. Config file setting (`terminal.backend`)
3. Auto-detect: if `TMUX` env var is set, use tmux; otherwise iTerm2

### Git Worktrees: Isolated Branches per Worker

A key feature of `claude-team` is **git worktree support**. When spawning workers with `use_worktree: true` (the default), each worker gets:

- **Its own working directory** - A git worktree at `{repo}/.worktrees/{name}/`
- **Its own branch** - Automatically created from the current HEAD
- **Shared repository history** - All worktrees share the same `.git` database, so commits are immediately visible across workers

Worktree naming depends on how workers are spawned:
- With a bead (issue tracker ID): `{repo}/.worktrees/{bead}-{annotation}/`
- Without: `{repo}/.worktrees/{worker-name}-{uuid}-{annotation}/`

The `.worktrees` directory is automatically added to `.gitignore`.

### Codex Support

Workers can run either Claude Code or OpenAI Codex. Set `agent_type: "codex"` in the worker config (or set the default in the config file) to spawn Codex workers instead of Claude Code workers.

## Features

- **Spawn Workers**: Create Claude Code or Codex sessions with multi-pane layouts
- **Terminal Backends**: tmux (cross-platform) and iTerm2 (macOS)
- **Git Worktrees**: Isolate each worker in its own branch and working directory
- **Send Messages**: Inject prompts into managed workers (single or broadcast)
- **Read Logs**: Retrieve conversation history from worker JSONL files
- **Monitor Status**: Check if workers are idle, processing, or waiting for input
- **Idle Detection**: Wait for workers to complete using stop-hook markers
- **Event Polling**: Track worker lifecycle events (started, completed, stuck)
- **Visual Identity**: Each worker gets a unique tab color and themed name (Marx Brothers, Beatles, etc.)
- **Session Recovery**: Discover and adopt orphaned sessions after MCP server restarts
- **HTTP Mode**: Run as a persistent service with streamable-http transport
- **Config File**: Centralized configuration at `~/.claude-team/config.json`

## Requirements

- Python 3.11+
- `uv` package manager
- **tmux backend**: tmux installed (macOS or Linux)
- **iTerm2 backend**: macOS with iTerm2 and Python API enabled (Preferences > General > Magic > Enable Python API)
- **Codex workers** (optional): OpenAI Codex CLI installed

## Installation

### As Claude Code Plugin (recommended)

```bash
# Add the Martian Engineering marketplace
/plugin marketplace add Martian-Engineering/claude-team

# Install the plugin
/plugin install claude-team@martian-engineering
```

This automatically configures the MCP server - no manual setup needed.

### From PyPI

```bash
uvx --from claude-team-mcp@latest claude-team
```

### From Source

```bash
git clone https://github.com/Martian-Engineering/claude-team.git
cd claude-team
uv sync
```

## Configuration for Claude Code

Add to your Claude Code MCP settings. You can configure this at:
- **Global**: `~/.claude/settings.json`
- **Project**: `.claude/settings.json` in your project directory

### Using PyPI package

```json
{
  "mcpServers": {
    "claude-team": {
      "command": "uvx",
      "args": ["--from", "claude-team-mcp@latest", "claude-team"]
    }
  }
}
```

### Using local clone

```json
{
  "mcpServers": {
    "claude-team": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/claude-team", "python", "-m", "claude_team_mcp"]
    }
  }
}
```

### Project-level with auto project path

For project-scoped `.mcp.json` files, use `CLAUDE_TEAM_PROJECT_DIR` so workers inherit the project path:

```json
{
  "mcpServers": {
    "claude-team": {
      "command": "uvx",
      "args": ["--from", "claude-team-mcp@latest", "claude-team"],
      "env": { "CLAUDE_TEAM_PROJECT_DIR": "${PWD}" }
    }
  }
}
```

After adding the configuration, restart Claude Code for it to take effect.

## Config File

`claude-team` reads configuration from `~/.claude-team/config.json`. Manage it with the CLI:

```bash
claude-team config init          # Create default config
claude-team config init --force  # Overwrite existing config
claude-team config show          # Show effective config (file + env overrides)
claude-team config get <key>     # Get value by dotted path (e.g. defaults.layout)
claude-team config set <key> <value>  # Set and persist a value
```

### Config Schema

```json
{
  "version": 1,
  "commands": {
    "claude": null,
    "codex": null
  },
  "defaults": {
    "agent_type": "claude",
    "skip_permissions": false,
    "use_worktree": true,
    "layout": "auto"
  },
  "terminal": {
    "backend": null
  },
  "events": {
    "max_size_mb": 1,
    "recent_hours": 24
  },
  "issue_tracker": {
    "override": null
  }
}
```

| Section | Key | Description |
|---------|-----|-------------|
| `commands.claude` | string | Override Claude CLI command (e.g. `"happy"`) |
| `commands.codex` | string | Override Codex CLI command (e.g. `"happy codex"`) |
| `defaults.agent_type` | `"claude"` or `"codex"` | Default agent type for new workers |
| `defaults.skip_permissions` | bool | Default `--dangerously-skip-permissions` flag |
| `defaults.use_worktree` | bool | Create git worktrees by default |
| `defaults.layout` | `"auto"` or `"new"` | Default layout mode for spawn_workers |
| `terminal.backend` | `"tmux"` or `"iterm"` | Terminal backend override (null = auto-detect) |
| `events.max_size_mb` | int | Max event log file size before rotation |
| `events.recent_hours` | int | Hours of events to retain |
| `issue_tracker.override` | `"beads"` or `"pebbles"` | Force a specific issue tracker |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_TEAM_TERMINAL_BACKEND` | (auto-detect) | Force terminal backend: `tmux` or `iterm`. Highest precedence. |
| `CLAUDE_TEAM_PROJECT_DIR` | (none) | Enables `"project_path": "auto"` in worker configs. |
| `CLAUDE_TEAM_COMMAND` | `claude` | Override the CLI command for Claude Code workers. |
| `CLAUDE_TEAM_CODEX_COMMAND` | `codex` | Override the CLI command for Codex workers. |

## MCP Tools

### Worker Management

| Tool | Description |
|------|-------------|
| `spawn_workers` | Create workers with multi-pane layouts. Supports Claude Code and Codex agents. |
| `list_workers` | List all managed workers with status. Filter by status or project. |
| `examine_worker` | Get detailed worker status including conversation stats and last response preview. |
| `close_workers` | Gracefully terminate one or more workers. Worktree branches are preserved. |
| `discover_workers` | Find existing Claude Code/Codex sessions running in tmux or iTerm2. |
| `adopt_worker` | Import a discovered session into the managed registry. |

### Communication

| Tool | Description |
|------|-------------|
| `message_workers` | Send a message to one or more workers. Supports wait modes: `none`, `any`, `all`. |
| `read_worker_logs` | Get paginated conversation history from a worker's JSONL file. |
| `annotate_worker` | Add a coordinator note to a worker (visible in `list_workers` output). |

### Monitoring

| Tool | Description |
|------|-------------|
| `check_idle_workers` | Quick non-blocking check if workers are idle. |
| `wait_idle_workers` | Block until workers are idle. Modes: `all` (fan-out/fan-in) or `any` (pipeline). |
| `poll_worker_changes` | Read worker event log for started/completed/stuck workers since a timestamp. |

### Utilities

| Tool | Description |
|------|-------------|
| `list_worktrees` | List git worktrees created by claude-team for a repository. Supports orphan cleanup. |
| `issue_tracker_help` | Quick reference for the detected issue tracker (Beads or Pebbles). |

### Worker Identification

Workers can be referenced by any of three identifiers:
- **Internal ID**: Short hex string (e.g., `3962c5c4`)
- **Terminal ID**: Prefixed terminal session ID (e.g., `iterm:UUID` or `tmux:%1`)
- **Worker name**: Human-friendly name (e.g., `Groucho`, `Aragorn`)

All tools accept any of these formats.

### Tool Details

#### spawn_workers

```
WorkerConfig fields:
  project_path: str         - Required. Explicit path or "auto" (uses CLAUDE_TEAM_PROJECT_DIR)
  agent_type: str           - "claude" (default) or "codex"
  name: str                 - Optional worker name override (auto-picked from themed sets if omitted)
  annotation: str           - Task description (shown in badge, used in branch names)
  bead: str                 - Issue tracker ID (for badge, branch naming, and workflow instructions)
  prompt: str               - Additional instructions (combined with standard worker prompt)
  skip_permissions: bool    - Start with --dangerously-skip-permissions
  use_worktree: bool        - Create isolated git worktree (default: true)
  worktree: WorktreeConfig  - Optional worktree settings:
                              branch: Explicit branch name (auto-generated if omitted)
                              base: Ref/branch to branch FROM (default: HEAD). Set this
                                    when subtask workers need a feature branch's commits
                                    (e.g. {"base": "epic-id/feature-branch"})

Top-level arguments:
  workers: list[WorkerConfig]  - 1-4 worker configurations
  layout: str                  - "auto" (reuse windows) or "new" (fresh window)

Returns:
  sessions, layout, count, coordinator_guidance
```

Worker assignment is determined by `bead` and/or `prompt`:
- **bead only**: Worker follows issue tracker workflow (mark in_progress, implement, close, commit)
- **bead + prompt**: Issue tracker workflow plus additional custom instructions
- **prompt only**: Custom task with no issue tracking
- **neither**: Worker spawns idle, waiting for a message

#### message_workers

```
Arguments:
  session_ids: list[str]   - Worker IDs to message (accepts any identifier format)
  message: str             - The prompt to send
  wait_mode: str           - "none" (default), "any", or "all"
  timeout: float           - Max seconds to wait (default: 600)

Returns:
  success, session_ids, results, [idle_session_ids, all_idle, timed_out]
```

#### wait_idle_workers

```
Arguments:
  session_ids: list[str]   - Worker IDs to wait on
  mode: str                - "all" (default) or "any"
  timeout: float           - Max seconds to wait (default: 600)
  poll_interval: float     - Seconds between checks (default: 2)

Returns:
  session_ids, idle_session_ids, all_idle, waiting_on, mode, waited_seconds, timed_out
```

#### poll_worker_changes

```
Arguments:
  since: str                    - ISO timestamp to filter events from (or null for latest)
  stale_threshold_minutes: int  - Minutes without activity before marking stuck (default: 20)
  include_snapshots: bool       - Include periodic snapshot events (default: false)

Returns:
  events, summary (started/completed/stuck), active_count, idle_count, poll_ts
```

## HTTP Server Mode

Run `claude-team` as a persistent HTTP service instead of stdio:

```bash
claude-team --http              # Default port 8766
claude-team --http --port 9000  # Custom port
```

HTTP mode enables:
- **Streamable HTTP transport** for MCP communication
- **Worker poller** that periodically snapshots worker state and emits lifecycle events
- **MCP Resources** for read-only session access:
  - `sessions://list` - List all managed sessions
  - `sessions://{session_id}/status` - Detailed session status
  - `sessions://{session_id}/screen` - Terminal screen content

## Slash Commands

Install slash commands for common workflows:

```bash
make install-commands
```

| Command | Description |
|---------|-------------|
| `/spawn-workers` | Analyze tasks, create worktrees, and spawn workers with appropriate prompts |
| `/check-workers` | Generate a status report for all active workers |
| `/merge-worker` | Directly merge a worker's branch back to parent (for internal changes) |
| `/pr-worker` | Create a pull request from a worker's branch |
| `/team-summary` | Generate end-of-session summary of all worker activity |
| `/cleanup-worktrees` | Remove worktrees for merged branches |

## Issue Tracker Support

`claude-team` supports both Pebbles (`pb`) and Beads (`bd --no-db`).
The tracker is auto-detected by marker directories in the project root:

- `.pebbles` -> Pebbles
- `.beads` -> Beads

If both markers exist, Pebbles is selected by default. This can be overridden in the config file with `issue_tracker.override`. Worker prompts and coordination guidance use the detected tracker commands.

## Usage Patterns

### Basic: Spawn and Message

From your Claude Code session, spawn workers and send them tasks:

```
"Spawn two workers for frontend and backend work"
-> Uses spawn_workers with two WorkerConfigs pointing at different project paths
-> Returns workers named e.g. "Simon" and "Garfunkel"

"Send Simon the message: Review the React components"
-> Uses message_workers with session_ids=["Simon"]

"Check on Garfunkel's progress"
-> Uses examine_worker with session_id="Garfunkel"
```

### Parallel Work with Worktrees

Spawn workers in isolated branches for parallel development:

```
"Spawn three workers with worktrees to work on different features"
-> Uses spawn_workers with use_worktree=true (default)
-> Creates worktrees at {repo}/.worktrees/
-> Each worker gets their own branch

"Message all workers with their tasks, then wait for completion"
-> Uses message_workers with wait_mode="all"

"Create PRs for each worker's branch"
-> Uses /pr-worker for each completed worker
```

### Issue Tracker Integration

Assign workers to issue tracker items for structured workflows:

```
"Spawn a worker for issue cic-123"
-> spawn_workers with bead="cic-123", annotation="Fix auth bug"
-> Worker automatically marks issue in_progress, implements, closes, and commits

"Spawn workers for all ready issues"
-> Check `bd ready` or `pb ready` for available work
-> Spawn one worker per issue with bead assignments
```

### Coordinated Workflow

Use the manager to coordinate between workers:

```
"Spawn a backend worker to create a new API endpoint"
-> Wait for completion with wait_idle_workers

"Now spawn a frontend worker and tell it about the new endpoint"
-> Pass context from read_worker_logs of the backend worker

"Spawn a test worker to write integration tests"
-> Coordinate based on both previous workers' output
```

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                Manager Claude Code Session                       │
│                (has claude-team MCP server)                       │
├──────────────────────────────────────────────────────────────────┤
│                         MCP Tools                                │
│  spawn_workers | message_workers | wait_idle_workers | etc.      │
└───────────────────────────┬──────────────────────────────────────┘
                            │
               ┌────────────┼────────────┐
               ▼            ▼            ▼
         ┌──────────┐ ┌──────────┐ ┌──────────┐
         │ Groucho  │ │ Harpo    │ │ Chico    │
         │ (tmux)   │ │ (tmux)   │ │ (tmux)   │
         │          │ │          │ │          │
         │  Claude  │ │  Claude  │ │  Codex   │
         │   Code   │ │   Code   │ │          │
         │          │ │          │ │          │
         │ worktree │ │ worktree │ │ worktree │
         │ .worktrees/ │ .worktrees/ │ .worktrees/ │
         └──────────┘ └──────────┘ └──────────┘
```

The manager maintains:
- **Session Registry**: Maps worker IDs/names to terminal sessions
- **Terminal Backend**: Persistent connection to tmux or iTerm2 for terminal control
- **JSONL Monitoring**: Reads Claude/Codex session files for conversation state and idle detection
- **Worktree Tracking**: Manages git worktrees for isolated worker branches
- **Event Log**: Records worker lifecycle events for polling and diagnostics

## Development

```bash
# Sync dependencies (with dev tools)
uv sync --group dev

# Run tests
uv run pytest

# Run the server directly (for debugging)
uv run python -m claude_team_mcp

# Run in HTTP mode
uv run python -m claude_team_mcp --http

# Install slash commands
make install-commands
```

## Troubleshooting

### tmux backend

**"tmux not found"**
- Install tmux: `brew install tmux` (macOS) or `apt install tmux` (Linux)
- Ensure tmux is in your PATH

**Workers not detected after restart**
- Use `discover_workers` to find orphaned sessions
- Use `adopt_worker` to re-register them
- Sessions are matched via markers written to JSONL files

### iTerm2 backend

**"Could not connect to iTerm2"**
- Make sure iTerm2 is running
- Enable: iTerm2 > Preferences > General > Magic > Enable Python API

### General

**"Session not found"**
- The worker may have been closed externally
- Use `list_workers` to see active workers
- Workers can be referenced by ID, terminal ID, or name

**"No JSONL session file found"**
- Claude Code may still be starting up
- Wait a few seconds and try again
- Check that Claude Code is actually running in the worker pane

**Worktree issues**
- Use `list_worktrees` to see worktrees for a repository
- Orphaned worktrees can be cleaned up with `list_worktrees` + `remove_orphans=true`
- Worktrees are stored at `{repo}/.worktrees/`

## Upgrading

After a new version is published to PyPI, you may need to force-refresh the cached version:

```bash
uv cache clean --force
uv tool install --force --refresh claude-team-mcp
```

This is necessary because `uvx` aggressively caches tool environments.

## License

MIT
