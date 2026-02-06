# Launchd Setup (macOS)

This repository can run as a persistent HTTP server for Smart Fork indexing.
The launchd setup installs a LaunchAgent that runs:

```
uv run python -m maniple_mcp --http --port 5111
```

It also sets `MANIPLE_QMD_INDEXING=true` and defaults
`MANIPLE_INDEX_CRON=1h`.

## Install

1. Ensure dependencies are installed (uv + repo dependencies):

   ```bash
   uv sync
   ```

2. Install and load the LaunchAgent:

   ```bash
   scripts/install-launchd.sh
   ```

This writes `~/Library/LaunchAgents/com.maniple.plist`, creates
`~/.maniple/logs/`, and loads the service with `launchctl`.

If an old `com.claude-team` agent is present, the installer will stop it
before loading the new agent.

### Customize

- Override the indexing cadence before install:

  ```bash
  MANIPLE_INDEX_CRON=30m scripts/install-launchd.sh
  ```

- Edit `~/Library/LaunchAgents/com.maniple.plist` to change port,
  log paths, or working directory. After editing, reload the agent:

  ```bash
  launchctl bootout "gui/${UID}" ~/Library/LaunchAgents/com.maniple.plist
  launchctl bootstrap "gui/${UID}" ~/Library/LaunchAgents/com.maniple.plist
  ```

### Verify

- Check status:

  ```bash
  launchctl print gui/${UID}/com.maniple
  ```

- View logs:

  ```bash
  tail -f ~/.maniple/logs/maniple.out.log
  tail -f ~/.maniple/logs/maniple.err.log
  ```

## Uninstall

```bash
scripts/uninstall-launchd.sh
```

Logs are left in `~/.maniple/logs/` for inspection.

## Example plist

See `examples/com.maniple.plist` for a commented template.
