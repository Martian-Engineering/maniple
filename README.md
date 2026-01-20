# Claude Team MCP Server

An MCP server that allows one Claude Code session to spawn and manage a team of other Claude Code sessions via iTerm2.

## Introduction

`claude-team` is an MCP server and a set of slash commands for allowing Claude Code to orchestrate a "team" of other Claude Code sessions. It uses the iTerm2 API to spawn new terminal sessions and run Claude Code within them.

### Why?

- **Parallelism:** Many development tasks can be logically parallelized, but managing that parallelism is difficult for humans with limited attention spans. Claude, meanwhile, is very effective at it.
- **Context management:** Offloading implementation to a worker gives the implementing agent a fresh context window (smarter), and keeps the manager's context free of implementation details.
- **Background work:** Sometimes you want to have Claude Code go research something or answer a question without blocking the main thread of work.
- **Visibility:** `claude-team` spawns real Claude Code sessions. You can watch them, interrupt and take control, or close them out.

But, *why not just use Claude Code sub-agents*, you ask? They're opaque -- they go off and do things and you, the user, cannot effectively monitor their work, interject, or continue a conversation with them. Using a full Claude Code session obviates this problem.

### Git Worktrees: Isolated Branches per Worker

A key feature of `claude-team` is **git worktree support**. When spawning workers with `use_worktrees: true`, each worker gets:

- **Its own working directory** - A dedicated git worktree at `~/.claude-team/worktrees/{repo-hash}/{worker-name}/`
- **Its own branch** - Automatically created branch named `{WorkerName}-{hash}` (e.g., `Groucho-a1b2c3`)
- **Shared repository history** - All worktrees share the same `.git` database, so commits are immediately visible across workers

This means workers can make commits, run tests, and modify files without conflicting with each other or the main working directory. When work is complete, branches can be merged or submitted as PRs.

## Features

- **Spawn Workers**: Create new Claude Code sessions in iTerm2 with multi-pane layouts
- **Git Worktrees**: Isolate each worker in its own branch and working directory
- **Send Messages**: Inject prompts into managed workers (single or broadcast)
- **Read Logs**: Retrieve conversation history from worker JSONL files
- **Monitor Status**: Check if workers are idle, processing, or waiting for input
- **Idle Detection**: Wait for workers to complete using stop-hook markers
- **Visual Identity**: Each worker gets a unique tab color and themed name (Marx Brothers, Beatles, etc.)
- **Session Recovery**: Discover and adopt orphaned Claude Code sessions

## Requirements

- macOS with iTerm2 installed
- iTerm2 Python API enabled (Preferences → General → Magic → Enable Python API)
- Python 3.11+
- uv package manager

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

Once published, install via:

```bash
uvx --from claude-team-mcp@latest claude-team
```

### From Source

```bash
# Clone the repository
git clone https://github.com/Martian-Engineering/claude-team.git
cd claude-team

# Install with uv
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

After adding the configuration, restart Claude Code for it to take effect.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_TEAM_COMMAND` | `claude` | Override the command used to start Claude Code in worker sessions. Useful for running alternative CLI implementations like `happy`. |
| `CLAUDE_TEAM_CODEX_COMMAND` | `codex` | Override the command used to start Codex in worker sessions. Useful for running wrapped Codex (e.g., `happy codex`). |
| `CLAUDE_TEAM_PROJECT_DIR` | (none) | When set, allows using `"project_path": "auto"` in worker configs to automatically use this path. |

Example using an alternative CLI:

```bash
# For Claude Code workers
export CLAUDE_TEAM_COMMAND=happy

# For Codex workers
export CLAUDE_TEAM_CODEX_COMMAND="happy codex"
```

## MCP Tools

### Worker Management

| Tool | Description |
|------|-------------|
| `spawn_workers` | Create workers in a new window with multi-pane layout (single, vertical, horizontal, quad, triple_vertical) |
| `list_workers` | List all managed workers with status |
| `examine_worker` | Get detailed worker status including conversation stats and last response preview |
| `close_workers` | Gracefully terminate one or more workers |
| `discover_workers` | Find existing Claude Code sessions running in iTerm2 |
| `adopt_worker` | Import a discovered iTerm2 session into the managed registry |

### Communication

| Tool | Description |
|------|-------------|
| `message_workers` | Send a message to one or more workers (supports wait modes: none, any, all) |
| `read_worker_logs` | Get paginated conversation history from a worker's JSONL file |
| `annotate_worker` | Add a coordinator note to a worker (visible in list_workers output) |

### Idle Detection

| Tool | Description |
|------|-------------|
| `check_idle_workers` | Quick non-blocking check if workers are idle |
| `wait_idle_workers` | Block until workers are idle (supports "any" or "all" modes) |

### Utilities

| Tool | Description |
|------|-------------|
| `list_worktrees` | List git worktrees created by claude-team for a repository |
| `bd_help` | Beads quick reference (use `pb help` for Pebbles projects) |

### Worker Identification

Workers can be referenced by any of three identifiers:
- **Internal ID**: Short hex string (e.g., `3962c5c4`)
- **Terminal ID**: Prefixed iTerm UUID (e.g., `iterm:6D2074A3-2D5B-4823-B257-18721A7F5A04`)
- **Worker name**: Human-friendly name (e.g., `Groucho`, `Aragorn`)

All tools accept any of these formats.

### Tool Details

#### spawn_workers

```
Arguments:
  projects: dict[str, str]     - Map of pane names to project paths
  layout: str                  - "auto", "single", "vertical", "horizontal", "quad", or "triple_vertical"
  skip_permissions: bool       - If True, start Claude with --dangerously-skip-permissions
  custom_names: list[str]      - Override automatic themed name selection
  custom_prompt: str           - Custom prompt instead of standard worker pre-prompt
  use_worktrees: bool          - Create isolated git worktree for each worker

Returns:
  sessions, layout, count, name_set, mode, use_worktrees, coordinator_guidance
```

Layout pane names:
- `single`: `["main"]`
- `vertical`: `["left", "right"]`
- `horizontal`: `["top", "bottom"]`
- `quad`: `["top_left", "top_right", "bottom_left", "bottom_right"]`
- `triple_vertical`: `["left", "middle", "right"]`

#### message_workers

```
Arguments:
  session_ids: list[str]   - Worker IDs to message (accepts ID, terminal ID, or name)
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

## Slash Commands

The following slash commands are available for common workflows. Install them with:

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

## Issue Tracker Support

`claude-team` supports both Pebbles (`pb`) and Beads (`bd --no-db`).
The tracker is auto-detected by marker directories in the project root:

- `.pebbles` → Pebbles
- `.beads` → Beads

If both markers exist, Pebbles is selected by default. Worker prompts and
coordination guidance use the detected tracker commands. For quick references:

- Pebbles: `pb help`
- Beads: `bd_help` tool
| `/cleanup-worktrees` | Remove worktrees for merged branches |

## Usage Patterns

### Basic: Spawn and Message

From your Claude Code session, spawn workers and send them tasks:

```
"Spawn two workers for frontend and backend work"
→ Uses spawn_workers with projects={"left": "/path/to/frontend", "right": "/path/to/backend"}
→ Returns workers named e.g. "Simon" and "Garfunkel"

"Send Simon the message: Review the React components"
→ Uses message_workers with session_ids=["Simon"]

"Check on Garfunkel's progress"
→ Uses examine_worker with session_id="Garfunkel"
```

### Parallel Work with Worktrees

Spawn workers in isolated branches for parallel development:

```
"Spawn three workers with worktrees to work on different features"
→ Uses spawn_workers with use_worktrees=true
→ Creates worktrees at ~/.claude-team/worktrees/{repo}/
→ Each worker gets their own branch (e.g., "Larry-a1b2c3", "Curly-d4e5f6", "Moe-g7h8i9")

"Message all workers with their tasks, then wait for completion"
→ Uses message_workers with wait_mode="all"

"Create PRs for each worker's branch"
→ Uses /pr-worker for each completed worker
```

### Coordinated Workflow

Use the manager to coordinate between workers:

```
"Spawn a backend worker to create a new API endpoint"
→ Wait for completion with wait_idle_workers

"Now spawn a frontend worker and tell it about the new endpoint"
→ Pass context from read_worker_logs of the backend worker

"Spawn a test worker to write integration tests"
→ Coordinate based on both previous workers' output
```

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                Manager Claude Code Session                        │
│                (has claude-team MCP server)                       │
├──────────────────────────────────────────────────────────────────┤
│                         MCP Tools                                 │
│  spawn_workers │ message_workers │ wait_idle_workers │ etc.      │
└───────────────────────────┬──────────────────────────────────────┘
                            │
               ┌────────────┼────────────┐
               ▼            ▼            ▼
         ┌──────────┐ ┌──────────┐ ┌──────────┐
         │ Groucho  │ │ Harpo    │ │ Chico    │
         │ (iTerm2) │ │ (iTerm2) │ │ (iTerm2) │
         │          │ │          │ │          │
         │  Claude  │ │  Claude  │ │  Claude  │
         │   Code   │ │   Code   │ │   Code   │
         │          │ │          │ │          │
         │ worktree │ │ worktree │ │ worktree │
         │ branch:  │ │ branch:  │ │ branch:  │
         │ Groucho- │ │ Harpo-   │ │ Chico-   │
         │ a1b2c3   │ │ d4e5f6   │ │ g7h8i9   │
         └──────────┘ └──────────┘ └──────────┘
```

The manager maintains:
- **Session Registry**: Maps worker IDs/names to iTerm2 sessions
- **iTerm2 Connection**: Persistent connection for terminal control
- **JSONL Monitoring**: Reads Claude's session files for conversation state and idle detection
- **Worktree Tracking**: Manages git worktrees for isolated worker branches

## Development

```bash
# Sync dependencies
uv sync

# Run tests
uv run pytest

# Run the server directly (for debugging)
uv run python -m claude_team_mcp

# Install slash commands
make install-commands
```

## Troubleshooting

### "Could not connect to iTerm2"
- Make sure iTerm2 is running
- Enable: iTerm2 → Preferences → General → Magic → Enable Python API

### "Session not found"
- The worker may have been closed externally
- Use `list_workers` to see active workers
- Workers can be referenced by ID, terminal ID, or name

### "No JSONL session file found"
- Claude Code may still be starting up
- Wait a few seconds and try again
- Check that Claude Code is actually running in the worker pane

### Worktree issues
- Use `list_worktrees` to see worktrees for a repository
- Orphaned worktrees can be cleaned up with `list_worktrees` + `remove_orphans=true`
- Worktrees are stored at `~/.claude-team/worktrees/{repo-hash}/`

## License

MIT

## Upgrading to New Versions

After a new version is published to PyPI, you may need to force-refresh the cached version:

```bash
# Stop service first
launchctl bootout gui/$UID/com.claude-team

# Clear cache and reinstall
uv cache clean --force
uv tool install --force --refresh claude-team-mcp

# Restart service
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.claude-team.plist
```

This is necessary because `uvx` aggressively caches tool environments.
