# Rename Audit: `claude-team` -> `maniple`

Date: 2026-02-06

This document captures an audit of references to `claude-team` / `claude_team` in the
`Martian-Engineering/claude-team` repository to scope a comprehensive rename to `maniple`.

## How This Audit Was Run

Requested command (as provided):

```bash
grep -rn "claude.team\|claude_team" \
  --include="*.py" --include="*.md" --include="*.toml" --include="*.json" \
  --include="*.plist" --include="*.yaml" --include="*.yml" --include="*.txt" \
  --include="*.cfg" \
  /Users/phaedrus/Projects/claude-team/
```

Notes:
- Running that command against `/Users/phaedrus/Projects/claude-team/` includes nested
  copies under `.worktrees/`, which massively duplicates results.
- For a “single source of truth” view of the repo, the same grep was rerun excluding
  `.worktrees/`, `.git/`, `dist/`, etc. That filtered run produced ~297 matches.

## Summary Of High-Signal Identifiers

These are the main “names” in use today:
- PyPI distribution: `claude-team-mcp` (`pyproject.toml`, `uv.lock`)
- Console script / CLI: `claude-team` (`pyproject.toml`, `src/claude_team_mcp/__init__.py`, `src/claude_team_mcp/server.py`)
- Python packages:
  - `claude_team_mcp` (`src/claude_team_mcp/`, imports throughout tests)
  - `claude_team` (`src/claude_team/`, imported by the MCP server)
- MCP server key: `claude-team` (`.mcp.json`, `.claude.json`, plugin metadata)
- tmux session prefix: `claude-team` (`src/claude_team_mcp/terminal_backends/tmux.py`)
- JSONL markers: `<!claude-team-...!>` (`src/claude_team_mcp/session_state.py`)
- Config/data dir: `~/.claude-team/` (`src/claude_team_mcp/config.py`, `src/claude_team/events.py`, etc.)
- Settings dir: `~/.claude/claude-team-settings/` (`src/claude_team_mcp/iterm_utils.py`)
- Env vars: `CLAUDE_TEAM_*` (code, docs, tests)

## Findings By Category

### 1. Python Package Name (`claude_team_mcp`, imports, `__init__.py`)

Primary packages:
- `src/claude_team_mcp/` (MCP server + tools)
- `src/claude_team/` (events/poller/idle detection helpers)

Notable references:
- `pyproject.toml` wheel packages list includes `src/claude_team` + `src/claude_team_mcp`.
- Tests import `claude_team_mcp.*` and `claude_team.*` heavily (and patch via dotted paths).

Example files:
- `src/claude_team_mcp/__init__.py` (docstring + `main()` “Entry point for the claude-team command”)
- `src/claude_team/__init__.py` (“Core modules for the claude-team tooling.”)
- `tests/test_*` (imports + patch paths)

### 2. PyPI / `pyproject.toml` (package name, project metadata)

Distribution name and metadata live in:
- `pyproject.toml`
  - `[project].name = "claude-team-mcp"`
  - `[project.urls]` all point at `https://github.com/Martian-Engineering/claude-team`
  - `[tool.hatch.build.targets.wheel].packages = ["src/claude_team", "src/claude_team_mcp"]`
- `uv.lock` contains `name = "claude-team-mcp"` (generated)

### 3. CLI Entrypoints (console_scripts, command names)

Entrypoints and CLI naming:
- `pyproject.toml`: `[project.scripts] claude-team = "claude_team_mcp:main"`
- `src/claude_team_mcp/server.py`: argparse help strings: “Claude Team MCP Server”, config subcommands “Manage claude-team configuration”
- `src/claude_team_mcp/__main__.py`: supports `python -m claude_team_mcp`

### 4. MCP Server Name (tool registration, server identity)

Server “key” and identity appear in:
- `.mcp.json`:
  - `mcpServers["claude-team"]`
  - args include `--from claude-team-mcp@latest` and command `claude-team`
- `.claude.json`:
  - `mcpServers["claude-team"]` runs `python -m claude_team_mcp` from repo dir
- `src/claude_team_mcp/server.py`:
  - `FastMCP("Claude Team Manager", ...)` (server display name)
- `.claude/settings.local.json`:
  - `enabledMcpjsonServers: ["claude-team"]`
  - allowlist entries include `mcp__claude-team__...` tool namespaces (these will need updating if the server key changes)
- `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`:
  - plugin name and repo references embed `claude-team`
- `scripts/team-status.sh` calls `mcporter call claude-team-http.list_workers`

### 5. tmux Session Names + Markers

tmux session naming:
- `src/claude_team_mcp/terminal_backends/tmux.py`
  - `TMUX_SESSION_PREFIX = "claude-team"`
  - session name format: `claude-team-{project-slug}`

JSONL marker prefixes used for session recovery:
- `src/claude_team_mcp/session_state.py`
  - `MARKER_PREFIX = "<!claude-team-session:"`
  - `ITERM_MARKER_PREFIX = "<!claude-team-iterm:"`
  - `TMUX_MARKER_PREFIX = "<!claude-team-tmux:"`
  - `PROJECT_MARKER_PREFIX = "<!claude-team-project:"`
  - `unslugify_path()` also special-cases `--claude-team` -> `-.claude-team`

### 6. Config Paths (`~/.claude-team/`, `config.json`, etc.)

Known paths:
- `src/claude_team_mcp/config.py`:
  - `CONFIG_DIR = Path.home() / ".claude-team"`
  - `CONFIG_PATH = ~/.claude-team/config.json`
- `src/claude_team/events.py`:
  - `get_events_path()` returns `~/.claude-team/events.jsonl`
- `src/claude_team_mcp/utils/constants.py`:
  - `CODEX_JSONL_DIR = ~/.claude-team/codex`
- `src/claude_team_mcp/worktree.py`:
  - `WORKTREE_BASE_DIR = ~/.claude-team/worktrees`
- `src/claude_team_mcp/iterm_utils.py`:
  - settings dir: `~/.claude/claude-team-settings`
- `src/claude_team_mcp/server.py`:
  - recovery docstring references `~/.claude-team/events.jsonl`
  - debug log file: `/tmp/claude-team-debug.log`

### 7. Launchd Plist / Service References

Audit results:
- No `*.plist` files exist in the repo currently.
- There are references to launchd integration in `CHANGELOG.md` and in historical
  pebbles issue descriptions (`.pebbles/events.jsonl`, append-only).

Implication for rename:
- If a launchd installer exists/is added later, it likely needs to generate a label
  like `com.maniple.*` and use `~/.maniple/` paths.

### 8. Environment Variables (`CLAUDE_TEAM_*`)

Observed env vars and constants include:
- `CLAUDE_TEAM_COMMAND` (Claude CLI override)
- `CLAUDE_TEAM_CODEX_COMMAND` (Codex CLI override)
- `CLAUDE_TEAM_TERMINAL_BACKEND` (backend override)
- `CLAUDE_TEAM_ISSUE_TRACKER` (tracker override)
- `CLAUDE_TEAM_PROJECT_DIR` (spawn_workers: `project_path="auto"`)
- `CLAUDE_TEAM_EVENTS_MAX_SIZE_MB`, `CLAUDE_TEAM_EVENTS_RECENT_HOURS`
- `CLAUDE_TEAM_STALE_THRESHOLD_MINUTES`
- `CLAUDE_TEAM_READY_7f3a9c` (shell-ready marker constant)

Example files:
- `src/claude_team_mcp/config_cli.py`
- `src/claude_team_mcp/cli_backends/claude.py`
- `src/claude_team_mcp/cli_backends/codex.py`
- `src/claude_team_mcp/terminal_backends/__init__.py`
- `src/claude_team_mcp/issue_tracker/__init__.py`
- `src/claude_team/events.py`
- `README.md` (env var documentation table)
- `tests/test_*.py` (monkeypatches)

### 9. Documentation (README, CHANGELOG, docstrings, comments)

High-signal docs with many references:
- `README.md`
- `CHANGELOG.md`
- `CLAUDE.md` (and `AGENTS.md` symlink)
- `docs/ISSUE_TRACKER_ABSTRACTION.md`
- `docs/design/unified-worker-state.md`
- `HAPPY_INTEGRATION_RESEARCH.md`
- `commands/*.md` (slash command help text references tool names, “claude-team”, etc.)

### 10. GitHub Repo References

Locations that embed the repo name:
- `pyproject.toml` `[project.urls]` all reference `Martian-Engineering/claude-team`
- `CHANGELOG.md` compare/release links reference `Martian-Engineering/claude-team`
- `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`
- `README.md` (install/invoke strings reference `claude-team-mcp` and `claude-team`)

### 11. Test Files (references, fixtures)

Tests reference:
- import paths for `claude_team_mcp` / `claude_team`
- env vars `CLAUDE_TEAM_*`
- config paths `~/.claude-team/*`
- marker prefixes `<!claude-team-...!>`
- logger names `claude-team-mcp`

Example files:
- `tests/test_cli_backends.py`
- `tests/test_config_cli.py`
- `tests/test_events.py`
- `tests/test_iterm_utils.py`
- `tests/test_session_state.py`
- `tests/test_terminal_backends.py`

### 12. Log Messages (hardcoded strings)

Known logger namespaces and strings:
- `logging.getLogger("claude-team-mcp")` and variants throughout `src/`
- `/tmp/claude-team-debug.log` in `src/claude_team_mcp/server.py`
- start/shutdown messages: “Claude Team MCP Server …”

## Implementation Work Tracking

Pebbles epic: `cic-652` (“Rename claude-team to maniple”).

