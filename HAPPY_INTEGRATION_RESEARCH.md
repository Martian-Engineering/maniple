# Happy Integration Research

## Problem Statement

When `MANIPLE_COMMAND=happy` is set, sessions spawn and work in iTerm2 but Happy mobile shows them as empty. Running `happy` directly from terminal works fine.

## Root Cause: `--settings` Flag Conflict

### How maniple spawns sessions

In `src/claude_team_mcp/iterm_utils.py:545-552`:

```python
claude_cmd = os.environ.get("MANIPLE_COMMAND", "claude")
if dangerously_skip_permissions:
    claude_cmd += " --dangerously-skip-permissions"
if stop_hook_marker_id:
    settings_file = build_stop_hook_settings_file(stop_hook_marker_id)
    claude_cmd += f" --settings {settings_file}"
```

This creates a command like:
```
happy --dangerously-skip-permissions --settings ~/.claude/maniple-settings/worker-xxx.json
```

**Maniple's settings file** (`~/.claude/maniple-settings/worker-xxx.json`):
```json
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "echo [worker-done:xxx]"
      }]
    }]
  }
}
```

### How Happy processes the command

When Happy receives `--settings <file>`, it treats it as an unknown arg and passes it through to Claude via `options.claudeArgs`. Then in `dist/index-B3gQr6vs.mjs:311-314`:

```javascript
if (opts.claudeArgs) {
  args.push(...opts.claudeArgs);  // Includes maniple's --settings
}
args.push("--settings", opts.hookSettingsPath);  // Happy's own --settings
```

**Happy's settings file** (`~/.happy/tmp/hooks/session-hook-<pid>.json`):
```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "node \".../session_hook_forwarder.cjs\" <port>"
      }]
    }]
  }
}
```

### The Conflict

Claude receives TWO `--settings` flags:
```
claude ... --settings <maniple-file> --settings <happy-file>
```

Claude likely only uses the **first** `--settings` file (standard CLI behavior), meaning:
- Claude has the **Stop hook** (maniple's) - for idle detection
- Claude does **NOT** have the **SessionStart hook** (Happy's) - for session tracking

### Why Happy mobile shows empty sessions

Happy's session tracking relies on the `SessionStart` hook:
1. Hook fires when Claude starts
2. Hook script POSTs session ID to Happy's local hook server (port varies per session)
3. Happy daemon receives session ID and updates session metadata
4. Mobile app displays session

Without the SessionStart hook firing, Happy never learns the Claude session ID, so the session appears empty in the mobile app.

## Key Files

| File | Purpose |
|------|---------|
| `src/claude_team_mcp/iterm_utils.py:459-500` | `build_stop_hook_settings_file()` creates Stop hook settings |
| `src/claude_team_mcp/iterm_utils.py:545-552` | Command building that adds `--settings` |
| Happy `dist/index-B3gQr6vs.mjs:311-314` | Args processing that adds Happy's `--settings` |
| Happy `dist/index-B3gQr6vs.mjs:4928-4953` | `generateHookSettingsFile()` creates SessionStart hook settings |
| Happy `dist/index-B3gQr6vs.mjs:4861-4927` | Hook server that receives session notifications |
| Happy `scripts/session_hook_forwarder.cjs` | Script executed by SessionStart hook |

## Solution Options

### Option A: Don't add `--settings` when using Happy

When `MANIPLE_COMMAND=happy`, skip adding the `--settings` flag entirely:

```python
claude_cmd = os.environ.get("MANIPLE_COMMAND", "claude")
if dangerously_skip_permissions:
    claude_cmd += " --dangerously-skip-permissions"

# Only add stop hook settings when NOT using happy
if stop_hook_marker_id and claude_cmd == "claude":
    settings_file = build_stop_hook_settings_file(stop_hook_marker_id)
    claude_cmd += f" --settings {settings_file}"
```

**Tradeoff:** Loses idle detection for Happy-spawned workers. Maniple would need an alternative mechanism.

### Option B: Merge hooks into one settings file

Create a combined settings file that includes BOTH hooks:

```python
def build_merged_settings_file(marker_id: str, happy_port: int) -> str:
    settings = {
        "hooks": {
            "Stop": [{
                "hooks": [{
                    "type": "command",
                    "command": f"echo [worker-done:{marker_id}]"
                }]
            }],
            "SessionStart": [{
                "matcher": "*",
                "hooks": [{
                    "type": "command",
                    "command": f"node /path/to/session_hook_forwarder.cjs {happy_port}"
                }]
            }]
        }
    }
    # ...
```

**Tradeoff:** Requires knowing Happy's hook server port, which is dynamic and only known after Happy starts its hook server.

### Option C: Coordinate with Happy's hook mechanism

Have maniple discover Happy's hook port and integrate with it, or use Happy's daemon API directly for session tracking.

**Tradeoff:** Complex integration, tight coupling with Happy internals.

### Option D: Request Happy feature - external settings support

Ask Happy to support inheriting/merging external `--settings` files instead of overwriting:

```javascript
// In Happy's args processing
if (arg === "--settings") {
    options.externalSettings = args[++i];  // Store for later merging
}

// When building Claude args
const mergedSettings = mergeSettings(opts.externalSettings, opts.hookSettingsPath);
args.push("--settings", mergedSettings);
```

**Tradeoff:** Requires Happy changes, but cleanest solution.

## Recommended Approach

**Short-term (Option A):** Detect when using Happy and skip the `--settings` flag. Accept the loss of Stop-hook-based idle detection. Use an alternative like polling the JSONL for assistant message patterns.

**Long-term (Option D):** Request Happy add support for merging external settings files, or document how to integrate with Happy's session tracking API directly.

## Testing Verification

To verify the root cause:
1. Run `happy` directly from terminal - check that SessionStart hook fires (session shows in mobile)
2. Run via maniple with `MANIPLE_COMMAND=happy` - SessionStart hook should NOT fire
3. Temporarily remove maniple's `--settings` flag and respawn - session should appear in mobile

## Additional Notes

- Happy's daemon runs in background and must be started for session tracking
- Happy auto-starts daemon if not running (line 6469-6478)
- Session metadata includes `startedBy: "terminal"` vs `"daemon"` - may affect visibility
- Happy's hook server port is ephemeral (assigned at runtime)
