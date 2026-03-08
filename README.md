# Maniple MCP Server

An MCP server that allows one Claude Code session to spawn and manage a team of other Claude Code (or Codex) sessions via terminal backends (tmux or iTerm2).

## Introduction

`maniple` is an MCP server and a set of slash commands for allowing Claude Code to orchestrate a "team" of other Claude Code or Codex sessions. It uses terminal backends (tmux or iTerm2) to spawn new terminal sessions and run Claude Code or Codex within them.

### Why?

- **Parallelism:** Many development tasks can be logically parallelized, but managing that parallelism is difficult for humans with limited attention spans. Claude, meanwhile, is very effective at it.
- **Context management:** Offloading implementation to a worker gives the implementing agent a fresh context window (smarter), and keeps the manager's context free of implementation details.
- **Background work:** Sometimes you want to have Claude Code go research something or answer a question without blocking the main thread of work.
- **Visibility:** `maniple` spawns real Claude Code or Codex sessions. You can watch them, interrupt and take control, or close them out.

But, *why not just use Claude Code sub-agents*, you ask? They're opaque -- they go off and do things and you, the user, cannot effectively monitor their work, interject, or continue a conversation with them. Using a full Claude Code session obviates this problem.

### Terminal Backends

`maniple` supports two terminal backends:

| Backend | Platform | Status |
|---------|----------|--------|
| **tmux** | macOS, Linux | Primary. Auto-selected when running inside tmux. |
| **iTerm2** | macOS only | Fully supported. Requires Python API enabled. |

Backend selection order:
1. `MANIPLE_TERMINAL_BACKEND` environment variable (`tmux` or `iterm`)
2. Config file setting (`terminal.backend`)
3. Auto-detect: if `TMUX` env var is set, use tmux; otherwise iTerm2

### Git Worktrees: Isolated Branches per Worker

A key feature of `maniple` is **git worktree support**. When spawning workers with `use_worktree: true` (the default), each worker gets:

- **Its own working directory** - A git worktree at `{repo}/.worktrees/{name}/`
- **Its own branch** - Automatically created from the current HEAD
- **Shared repository history** - All worktrees share the same `.git` database, so commits are immediately visible across workers

Worktree naming depends on how workers are spawned:
- With an issue ID: `{repo}/.worktrees/{issue_id}-{badge}/`
- Without: `{repo}/.worktrees/{worker-name}-{uuid}-{badge}/`

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
- **Config File**: Centralized configuration at `~/.maniple/config.json`

### HTTP Mode

Minimal service command:

```bash
uv run python -m maniple_mcp \
  --http \
  --host 100.64.0.45 \
  --port 8766 \
  --allow-host 100.64.0.45:8766
```

Use `--host` to change the bind address for streamable HTTP mode:

```bash
uv run python -m maniple_mcp --http --host 0.0.0.0 --port 8766
```

If you want DNS rebinding protection enabled for non-localhost clients, add
repeatable `--allow-host` entries and optional `--allow-origin` entries:

```bash
uv run python -m maniple_mcp \
  --http \
  --host 100.64.0.45 \
  --port 8766 \
  --allow-host 100.64.0.45:8766 \
  --allow-host my-tailnet-host.ts.net:8766
```

For temporary experiments on a trusted network, you can disable the protection:

```bash
uv run python -m maniple_mcp \
  --http \
  --host 100.64.0.45 \
  --port 8766 \
  --disable-dns-rebinding-protection
```

## Requirements

- Python 3.11+
- `uv` package manager
- **tmux backend**: tmux installed (macOS or Linux)
- **iTerm2 backend**: macOS with iTerm2 and Python API enabled (Preferences > General > Magic > Enable Python API)
- **Claude workers** (optional): Claude Code CLI installed
- **Codex workers** (optional): OpenAI Codex CLI installed
- **Linux service mode** (optional): `systemd --user` available
- **Provider wrapper mode** (optional): a local `claude-switch`-style wrapper installation if you want multiple Claude-compatible providers

## Installation

### Linux Quick Start

For a Debian/Ubuntu-style source checkout with `systemd --user` and provider
presets, the fastest path is:

```bash
git clone https://github.com/Martian-Engineering/maniple.git
cd maniple
uv sync --group dev

# Install/update ~/bin/claude-maniple-switch and create starter files:
bash scripts/setup-provider-presets.sh

# Install/update ~/.config/systemd/user/maniple.service for this checkout:
bash scripts/install-systemd-user.sh
```

Then edit:
- `~/.maniple/config.json`
- `~/.maniple/.env`

After changing provider settings:

```bash
systemctl --user restart maniple
```

For the full Debian/Linux walkthrough, see [Running as a Service](#running-as-a-service).

### As Claude Code Plugin (recommended)

```bash
# Add the Martian Engineering marketplace
/plugin marketplace add Martian-Engineering/maniple

# Install the plugin
/plugin install maniple@martian-engineering
```

This automatically configures the MCP server - no manual setup needed.

### From PyPI

```bash
uvx --from maniple-mcp@latest maniple
```

### From Source

```bash
git clone https://github.com/Martian-Engineering/maniple.git
cd maniple
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
    "maniple": {
      "command": "uvx",
      "args": ["--from", "maniple-mcp@latest", "maniple"]
    }
  }
}
```

### Using local clone

```json
{
  "mcpServers": {
    "maniple": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/maniple", "python", "-m", "maniple_mcp"]
    }
  }
}
```

### Project-level with auto project path

For project-scoped `.mcp.json` files, use `MANIPLE_PROJECT_DIR` so workers inherit the project path:

```json
{
  "mcpServers": {
    "maniple": {
      "command": "uvx",
      "args": ["--from", "maniple-mcp@latest", "maniple"],
      "env": { "MANIPLE_PROJECT_DIR": "${PWD}" }
    }
  }
}
```

After adding the configuration, restart Claude Code for it to take effect.

## Running as a Service

For a persistent Linux deployment, run `maniple` under `systemd --user` and keep
logs under `~/.maniple/logs/`.

### Debian/Ubuntu From-Source Setup

This is the recommended path when you want a user-level `systemd` service that
runs directly from your local checkout and automatically picks up source
changes after a service restart.

1. Install system packages:

```bash
sudo apt update
sudo apt install -y git tmux curl
```

2. Install `uv` if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

3. Clone and sync the project:

```bash
git clone https://github.com/Martian-Engineering/maniple.git
cd maniple
uv sync --group dev
```

4. Verify the CLI works from the checkout:

```bash
uv run maniple --help
```

Quick-start helpers from this repo:

```bash
# Install/update ~/bin/claude-maniple-switch and create starter files:
bash scripts/setup-provider-presets.sh

# Install/update ~/.config/systemd/user/maniple.service for this checkout:
bash scripts/install-systemd-user.sh
```

These scripts create the files for you and keep existing user config files in
place. After they run, you still need to edit `~/.maniple/config.json` and
`~/.maniple/.env` with your actual provider choices and credentials.

5. Create the user service directories:

```bash
mkdir -p ~/.maniple/logs ~/.config/systemd/user
```

6. Create `~/.config/systemd/user/maniple.service`:

```ini
[Unit]
Description=Maniple MCP Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/you/path/to/maniple
Environment=MANIPLE_TERMINAL_BACKEND=tmux
ExecStart=/home/you/.local/bin/uv run --project /home/you/path/to/maniple maniple --http --host 100.64.0.45 --port 8766 --allow-host 100.64.0.45:8766
Restart=always
RestartSec=3
StandardOutput=append:%h/.maniple/logs/maniple.out.log
StandardError=append:%h/.maniple/logs/maniple.err.log

[Install]
WantedBy=default.target
```

7. Load and start the user service:

```bash
systemctl --user daemon-reload
systemctl --user enable --now maniple
systemctl --user status maniple
```

8. Enable lingering so the service survives reboot without an active desktop login:

```bash
loginctl enable-linger "$USER"
```

9. After editing Python source code in the checkout, restart the service:

```bash
systemctl --user restart maniple
```

10. After editing the unit file itself, reload systemd and restart:

```bash
systemctl --user daemon-reload
systemctl --user restart maniple
```

11. Tail logs while debugging:

```bash
journalctl --user -u maniple -n 100 --no-pager
tail -f ~/.maniple/logs/maniple.out.log ~/.maniple/logs/maniple.err.log
```

Example unit file at `~/.config/systemd/user/maniple.service`:

```ini
[Unit]
Description=Maniple MCP Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/path/to/maniple
Environment=MANIPLE_TERMINAL_BACKEND=tmux
ExecStart=/path/to/uv run --project /path/to/maniple maniple --http --host 100.64.0.45 --port 8766 --allow-host 100.64.0.45:8766
Restart=always
RestartSec=3
StandardOutput=append:%h/.maniple/logs/maniple.out.log
StandardError=append:%h/.maniple/logs/maniple.err.log

[Install]
WantedBy=default.target
```

Enable and start it:

```bash
mkdir -p ~/.maniple/logs ~/.config/systemd/user
systemctl --user daemon-reload
systemctl --user enable --now maniple
systemctl --user status maniple
```

To keep the service running after reboot without an active graphical login:

```bash
loginctl enable-linger "$USER"
```

Useful log commands:

```bash
journalctl --user -u maniple -n 100 --no-pager
tail -f ~/.maniple/logs/maniple.out.log ~/.maniple/logs/maniple.err.log
```

## Config File

`maniple` reads configuration from `~/.maniple/config.json`. Manage it with the CLI:

```bash
maniple config init          # Create default config
maniple config init --force  # Overwrite existing config
maniple config show          # Show effective config (file + env overrides)
maniple config get <key>     # Get value by dotted path (e.g. defaults.layout)
maniple config set <key> <value>  # Set and persist a value
```

### Migration Notes (from `claude-team`)

- Config directory: `~/.claude-team/` is auto-migrated to `~/.maniple/` on first run.
- Environment variables: `MANIPLE_*` takes precedence; `CLAUDE_TEAM_*` is supported as a fallback and may emit a deprecation warning to stderr.

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
    "provider": null,
    "skip_permissions": false,
    "use_worktree": true,
    "layout": "auto"
  },
  "terminal": {
    "backend": null,
    "auto_accept_startup_prompts": false
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
| `defaults.provider` | string or null | Default named provider preset for `spawn_workers` when a worker omits `provider` |
| `defaults.skip_permissions` | bool | Default Claude permission mode (`--permission-mode bypassPermissions`) |
| `defaults.use_worktree` | bool | Create git worktrees by default |
| `defaults.layout` | `"auto"` or `"new"` | Default layout mode for spawn_workers |
| `terminal.backend` | `"tmux"` or `"iterm"` | Terminal backend override (null = auto-detect) |
| `terminal.auto_accept_startup_prompts` | bool | Auto-confirm known Claude startup prompts during worker launch |
| `events.max_size_mb` | int | Max event log file size before rotation |
| `events.recent_hours` | int | Hours of events to retain |
| `issue_tracker.override` | `"beads"` or `"pebbles"` | Force a specific issue tracker |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MANIPLE_TERMINAL_BACKEND` | (auto-detect) | Force terminal backend: `tmux` or `iterm`. Highest precedence. |
| `MANIPLE_PROJECT_DIR` | (none) | Enables `"project_path": "auto"` in worker configs. |
| `MANIPLE_COMMAND` | `claude` | Override the CLI command for Claude Code workers. |
| `MANIPLE_CLAUDE_SUPPORTS_SETTINGS` | auto | Force custom Claude wrappers to receive `--settings` so stop hooks still work. |
| `MANIPLE_CODEX_COMMAND` | `codex` | Override the CLI command for Codex workers. |

### Provider Presets

For multiple Claude-compatible providers, keep the files separated like this:

- Main config: `~/.maniple/config.json`
- Provider credentials: `~/.maniple/.env`
- Wrapper executable: `~/bin/claude-maniple-switch`

The wrapper can source an existing `claude-switch` installation, but it reads
provider credentials from `~/.maniple/.env` so users do not need to depend on
`~/.claude-switch/.env` or the repository checkout for secrets.

Minimal setup:

1. Put provider credentials in `~/.maniple/.env`
2. Install `~/bin/claude-maniple-switch`
3. Add named presets under `providers` in `~/.maniple/config.json`
4. Call `spawn_workers` with `provider: "minimax"` or `provider: "kimi"` or `provider: "local"`

Bootstrap these files automatically:

```bash
bash scripts/setup-provider-presets.sh
```

That script will:
- install `~/bin/claude-maniple-switch`
- create `~/.maniple/config.json` if it does not exist
- create `~/.maniple/.env` if it does not exist
- leave existing files untouched and print the next manual steps

Define named presets in `~/.maniple/config.json` and reference them per worker:

```json
{
  "providers": {
    "minimax": {
      "command": "/home/you/bin/claude-maniple-switch",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "minimax"
      }
    },
    "kimi": {
      "command": "/home/you/bin/claude-maniple-switch",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "kimi"
      }
    },
    "local": {
      "command": "/home/you/bin/claude-maniple-switch",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "local"
      }
    }
  }
}
```

Example `~/.maniple/.env`:

```bash
export MINIMAX_API_KEY="replace-me"
export MINIMAX_BASE_URL="https://api.minimaxi.com/anthropic"
export MINIMAX_MODEL="MiniMax-M2.1"

export KIMI_API_KEY="replace-me"
export KIMI_BASE_URL="https://api.moonshot.cn/anthropic"
export KIMI_MODEL="kimi-k2-thinking-turbo"

export LOCAL_API_KEY="replace-me"
export LOCAL_BASE_URL="http://127.0.0.1:4000"
export LOCAL_MODEL="claude-3-5-sonnet"
```

Recommended convention for `~/.maniple/.env`:

```bash
export MANIPLE_PROVIDER_MINIMAX_API_KEY="replace-me"
export MANIPLE_PROVIDER_MINIMAX_BASE_URL="https://api.minimaxi.com/anthropic"
export MANIPLE_PROVIDER_MINIMAX_MODEL="MiniMax-M2.1"

export MANIPLE_PROVIDER_KIMI_API_KEY="replace-me"
export MANIPLE_PROVIDER_KIMI_BASE_URL="https://api.moonshot.cn/anthropic"
export MANIPLE_PROVIDER_KIMI_MODEL="kimi-k2-thinking-turbo"

export MANIPLE_PROVIDER_LOCAL_API_KEY="replace-me"
export MANIPLE_PROVIDER_LOCAL_BASE_URL="http://127.0.0.1:4000"
export MANIPLE_PROVIDER_LOCAL_MODEL="claude-3-5-sonnet"
```

The wrapper maps these namespaced variables automatically based on the selected
provider name. The convention is:

```text
provider name in config:     local
CLAUDE_SWITCH_PROVIDER:      local
~/.maniple/.env prefix:      MANIPLE_PROVIDER_LOCAL_
provider env aliases loaded: LOCAL_API_KEY / LOCAL_BASE_URL / LOCAL_MODEL
```

Examples:
- `provider: "kimi"` -> reads `MANIPLE_PROVIDER_KIMI_*`
- `provider: "minimax"` -> reads `MANIPLE_PROVIDER_MINIMAX_*`
- `provider: "local2"` -> reads `MANIPLE_PROVIDER_LOCAL2_*`

This keeps provider selection in `~/.maniple/config.json` and provider secrets
in `~/.maniple/.env`, with a predictable naming rule between them.

### Adding or Removing Providers

To add a provider:

1. Ensure your wrapper supports it in the `case "$provider" in ... esac` block.
2. Add a preset under `providers` in `~/.maniple/config.json`.
3. Add matching `MANIPLE_PROVIDER_<NAME>_*` values to `~/.maniple/.env`.
4. Restart the MCP service if it is running under `systemd --user`.

Example: add `local2`

`~/.maniple/config.json`

```json
{
  "providers": {
    "local2": {
      "command": "/home/you/bin/claude-maniple-switch",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "local2"
      }
    }
  }
}
```

`~/.maniple/.env`

```bash
export MANIPLE_PROVIDER_LOCAL2_API_KEY="replace-me"
export MANIPLE_PROVIDER_LOCAL2_BASE_URL="http://127.0.0.1:4001"
export MANIPLE_PROVIDER_LOCAL2_MODEL="claude-3-5-sonnet"
```

To remove a provider:

1. Delete its preset from `~/.maniple/config.json`
2. Optionally delete its `MANIPLE_PROVIDER_<NAME>_*` lines from `~/.maniple/.env`
3. Restart the MCP service if needed

Service reload after provider changes:

```bash
systemctl --user restart maniple
```

Set a default provider for workers that do not specify one explicitly:

```bash
maniple config set defaults.provider local
```

Clear the default provider:

```bash
maniple config set defaults.provider null
```

Example wrapper at `~/bin/claude-maniple-switch`:

```bash
#!/usr/bin/env bash
set -euo pipefail

CLAUDE_SWITCH_DIR="${CLAUDE_SWITCH_DIR:-$HOME/.local/bin/claude-switch}"
CLAUDE_SWITCH_SCRIPT="${CLAUDE_SWITCH_SCRIPT:-$CLAUDE_SWITCH_DIR/claude-providers-v3.sh}"
MANIPLE_PROVIDER_ENV_FILE="${MANIPLE_PROVIDER_ENV_FILE:-$HOME/.maniple/.env}"
provider="${CLAUDE_SWITCH_PROVIDER:-official}"

source "$CLAUDE_SWITCH_SCRIPT" >/dev/null 2>&1

if [[ -f "$MANIPLE_PROVIDER_ENV_FILE" ]]; then
  set -a
  source "$MANIPLE_PROVIDER_ENV_FILE" >/dev/null 2>&1
  set +a
fi

case "$provider" in
  minimax) claude-minimax "$@" ;;
  kimi) claude-kimi "$@" ;;
  local) claude-local "$@" ;;
  official) claude-official "$@" ;;
  *) echo "Unknown CLAUDE_SWITCH_PROVIDER: $provider" >&2; exit 1 ;;
esac
```

Then use either a named `provider` preset or direct `command` / `env` overrides:

```json
{
  "workers": [
    {
      "project_path": "/repo",
      "provider": "kimi"
    },
    {
      "project_path": "/repo",
      "command": "/home/you/bin/claude-maniple-switch",
      "env": {
        "CLAUDE_SWITCH_PROVIDER": "local"
      }
    }
  ]
}
```

Minimal `spawn_workers` example:

```json
{
  "workers": [
    {
      "project_path": "/repo",
      "provider": "kimi",
      "skip_permissions": true
    }
  ],
  "layout": "new"
}
```

### MCP Client Usage

Recommended client flow:

1. Call `list_providers` to discover available named provider presets.
2. Call `spawn_workers` with `provider: "<name>"`.
3. Put the actual task in the worker `prompt`.

Structured example:

```json
{
  "workers": [
    {
      "project_path": "/repo",
      "provider": "kimi",
      "prompt": "Inspect the training pipeline and fix the failing evaluation step.",
      "skip_permissions": true
    }
  ],
  "layout": "new"
}
```

Minimal natural-language prompt examples for MCP-capable clients:

```text
先调用 list_providers，告诉我当前可用的 provider 名字。
```

```text
调用 spawn_workers，在 /repo 启动 1 个 Claude worker，provider 用 kimi，skip_permissions=true，prompt 用“检查训练脚本报错并修复”。
```

```text
调用 spawn_workers，在 /repo 启动 1 个 Claude worker，provider 用 local2，layout 用 new，prompt 用“检查 API 服务启动失败的原因并修复”。
```

Prompt-writing guidance for reliable tool invocation:
- Name the MCP tool explicitly: `list_providers` or `spawn_workers`
- Specify the provider name exactly as returned by `list_providers`
- Put the worker's assignment into the `prompt` field
- Include `project_path` explicitly
- Use `skip_permissions: true` when the worker needs to edit files or run commands

`spawn_work` is not a valid tool name; use `spawn_workers`.

### First-Run Notes for Claude Workers

When testing autonomous Claude workers, the MCP service itself may be healthy but
Claude Code can still pause on local interactive confirmations. Common examples:

- trusting a newly opened project folder
- approving local `.mcp.json` servers discovered in the target repo
- confirming Claude permission-mode / bypass mode warnings when the CLI requires it

If this happens, the worker will appear to time out during startup even though
the tmux pane is alive. Check the pane directly and clear the confirmation once.
After that, service-mode orchestration is much smoother.

If you want unattended worker startup in a trusted local environment, set
`terminal.auto_accept_startup_prompts` to `true`. This only auto-confirms
known startup blockers during launch, currently:

- the project `.mcp.json` trust prompt
- the Claude bypass-permissions startup confirmation

This is intentionally opt-in because it accepts security prompts on your behalf.

For the same project, MCP trust is usually a one-time confirmation. After you
accept the `.mcp.json` server for that project, future workers in the same
project normally stop hitting that prompt. It can reappear if you reset Claude
state, change the project's MCP config, or open a different project.

The bypass-permissions warning is also a Claude-side interactive confirmation.
After you accept it once, repeated prompts are less likely in the same local
setup, but you should not assume that it is permanently suppressed across CLI
upgrades, config resets, or entirely new environments.

For tmux-backed workers, you can jump straight to the blocked worker pane and
clear the prompt manually:

```bash
# Open the smoke-test worker that was blocked on the .mcp.json trust prompt
tmux attach-session -t maniple-maniple-smoke \; select-window -t 2

# Open the MolGen worker that was blocked on the bypass-permissions prompt
tmux attach-session -t maniple-MolGen \; select-window -t 35
```

Once attached:
- For the `.mcp.json` prompt, choose `Use this and all future MCP servers in this project` if you trust that repo's MCP config.
- For the bypass-permissions prompt, move to `Yes, I accept` and press Enter if you intentionally launched that worker with `skip_permissions: true`.

## MCP Tools

### Worker Management

| Tool | Description |
|------|-------------|
| `spawn_workers` | Create workers with multi-pane layouts. Supports Claude Code and Codex agents. |
| `list_workers` | List all managed workers with status. Filter by status or project. |
| `examine_worker` | Get detailed worker status including conversation stats and last response preview. |
| `close_workers` | Gracefully terminate one or more workers. Worktree branches are preserved by default, or deleted with `delete_branch: true`. |
| `discover_workers` | Find existing Claude Code/Codex sessions running in tmux or iTerm2. |
| `adopt_worker` | Import a discovered session into the managed registry. |
| `list_providers` | List configured Claude-compatible provider presets from `~/.maniple/config.json`. |

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
| `list_worktrees` | List git worktrees created by maniple for a repository. Supports orphan cleanup. |
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
  project_path: str         - Required. Explicit path or "auto" (uses MANIPLE_PROJECT_DIR)
  agent_type: str           - "claude" (default) or "codex"
  name: str                 - Optional worker name override (auto-picked from themed sets if omitted)
  badge: str                - Task description (shown in badge, used in branch names)
  issue_id: str             - Issue tracker ID (for badge, branch naming, and workflow instructions)
  prompt: str               - Additional instructions (combined with standard worker prompt)
  skip_permissions: bool    - Start Claude with `--permission-mode bypassPermissions`
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

Worker assignment is determined by `issue_id` and/or `prompt`:
- **issue_id only**: Worker follows issue tracker workflow (mark in_progress, implement, close, commit)
- **issue_id + prompt**: Issue tracker workflow plus additional custom instructions
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

#### close_workers

```
Arguments:
  session_ids: list[str]   - Worker IDs to close (accepts any identifier format)
  force: bool              - Force close even if a worker is busy
  delete_branch: bool      - Also delete the worker branch after removing its
                             worktree (default: false)

Returns:
  session_ids, results, success_count, failure_count
```

Worktree cleanup behavior:
- By default, `close_workers` removes the worker worktree directory and keeps the branch.
- Set `delete_branch: true` to remove both the worktree and its branch in one call.

Example:

```json
{
  "session_ids": ["Hypatia"],
  "delete_branch": true
}
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

#### list_providers

```
Returns:
  config_path, count, provider_names, providers, usage_tip
```

Use this when an MCP client wants to discover which named provider presets are
available before calling `spawn_workers` with `provider: "<name>"`.

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

Run `maniple` as a persistent HTTP service instead of stdio:

```bash
maniple --http              # Default port 8766
maniple --http --port 9000  # Custom port
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

`maniple` supports both Pebbles (`pb`) and Beads (`bd --no-db`).
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
-> spawn_workers with issue_id="cic-123", badge="Fix auth bug"
-> Worker automatically marks issue in_progress, implements, closes, and commits

"Spawn workers for all ready issues"
-> Check `bd ready` or `pb ready` for available work
-> Spawn one worker per issue with issue_id assignments
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
│                (has maniple MCP server)                          │
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
uv run python -m maniple_mcp

# Run in HTTP mode
uv run python -m maniple_mcp --http

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

**Worker startup timed out, but the pane is still alive**
- Claude may be blocked on a first-run confirmation rather than actually failing to start
- Common blockers are:
  - the project `.mcp.json` trust prompt
- the Claude bypass-permissions confirmation
- For tmux sessions, attach directly to the blocked pane:

```bash
tmux attach-session -t <session-name> \; select-window -t <window-index>
```

- Example sessions from local debugging:

```bash
tmux attach-session -t maniple-maniple-smoke \; select-window -t 2
tmux attach-session -t maniple-MolGen \; select-window -t 35
```

- After you clear the confirmation once, retry `spawn_workers`
- For the same project, `.mcp.json` trust is usually a one-time confirmation unless Claude state or project MCP config changes

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
uv tool install --force --refresh maniple
```

This is necessary because `uvx` aggressively caches tool environments.

## License

MIT
