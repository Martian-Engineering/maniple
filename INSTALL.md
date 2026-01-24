# Launchd Setup (macOS)

This repository can run as a persistent HTTP server for Smart Fork indexing.
The launchd setup installs a LaunchAgent that runs:

```
uv run python -m claude_team_mcp --http --port 5111
```

It also sets `CLAUDE_TEAM_QMD_INDEXING=true` and defaults
`CLAUDE_TEAM_INDEX_CRON=1h`.

## Install

1. Ensure dependencies are installed (uv + repo dependencies):

   ```bash
   uv sync
   ```

2. Install and load the LaunchAgent:

   ```bash
   scripts/install-launchd.sh
   ```

This writes `~/Library/LaunchAgents/com.claude-team.plist`, creates
`~/.claude-team/logs/`, and loads the service with `launchctl`.

### Customize

- Override the indexing cadence before install:

  ```bash
  CLAUDE_TEAM_INDEX_CRON=30m scripts/install-launchd.sh
  ```

- Edit `~/Library/LaunchAgents/com.claude-team.plist` to change port,
  log paths, or working directory. After editing, reload the agent:

  ```bash
  launchctl bootout "gui/${UID}" ~/Library/LaunchAgents/com.claude-team.plist
  launchctl bootstrap "gui/${UID}" ~/Library/LaunchAgents/com.claude-team.plist
  ```

### Verify

- Check status:

  ```bash
  launchctl print gui/${UID}/com.claude-team
  ```

- View logs:

  ```bash
  tail -f ~/.claude-team/logs/claude-team.out.log
  tail -f ~/.claude-team/logs/claude-team.err.log
  ```

## Uninstall

```bash
scripts/uninstall-launchd.sh
```

Logs are left in `~/.claude-team/logs/` for inspection.

## Example plist

See `examples/com.claude-team.plist` for a commented template.
