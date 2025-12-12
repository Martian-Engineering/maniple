# Claude Code iTerm2 Controller - Technical Notes

## Overview

This library provides programmatic control of Claude Code sessions via iTerm2's Python API, combined with state access through Claude's JSONL session files.

## Key Discoveries

### 1. Enter Key: Use `\x0d`, NOT `\n`

**This is the most important finding.**

When sending text to iTerm2 via `async_send_text()`:
- `\n` (line feed, 0x0A) creates a newline character in the input buffer
- `\x0d` (carriage return, 0x0D, Ctrl+M) triggers the actual Enter key

```python
# WRONG - adds newline to input, doesn't submit
await session.async_send_text("hello\n")

# CORRECT - sends text then presses Enter
await session.async_send_text("hello")
await session.async_send_text("\x0d")
```

This applies to Claude Code and most CLI applications expecting Enter to submit.

### 2. Claude Session State Lives in JSONL Files

Location: `~/.claude/projects/{slug}/{session-id}.jsonl`

Where `{slug}` is the project path with `/` replaced by `-`:
- `/Users/josh/code` → `-Users-josh-code`

JSONL structure (one JSON object per line):
```json
{
  "type": "user",
  "sessionId": "uuid",
  "uuid": "message-uuid",
  "parentUuid": "parent-uuid",
  "message": {
    "role": "user",
    "content": "What files are here?"
  },
  "timestamp": "2025-12-12T05:30:00.000Z",
  "cwd": "/Users/josh/code"
}
```

Assistant messages have `content` as an array:
```json
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "content": [
      {"type": "text", "text": "Here are the files..."},
      {"type": "tool_use", "name": "Bash", "input": {...}}
    ]
  }
}
```

### 3. Session Linking Strategy

To connect an iTerm2 session to its JSONL state:

1. **By timing**: The most recently modified `.jsonl` file in the project directory likely corresponds to an active session
2. **By screen content**: Search iTerm2 screens for project name + Claude indicators
3. **By explicit tracking**: Store session IDs when you create them

```python
# Find by timing
session_id = find_active_session("/path/to/project", max_age_seconds=60)

# Find by screen content
iterm_session = await find_claude_session(app, "/path/to/project")
```

### 4. Response Detection

Claude is "done responding" when:
- The JSONL file stops being modified
- We use an idle threshold (e.g., 2 seconds of no changes)

```python
async def wait_for_response(timeout=120, idle_threshold=2.0):
    last_mtime = 0
    last_change = time.time()

    while time.time() - start < timeout:
        state = parse_session(jsonl_path)
        if state.last_modified > last_mtime:
            last_mtime = state.last_modified
            last_change = time.time()
        elif time.time() - last_change > idle_threshold:
            return state.last_assistant_message
        await asyncio.sleep(0.5)
```

### 5. iTerm2 API Key Patterns

Enable API: iTerm2 → Preferences → General → Magic → Enable Python API

```python
import iterm2

# All iTerm2 scripts need this wrapper
async def main(connection):
    app = await iterm2.async_get_app(connection)
    # ... your code ...

iterm2.run_until_complete(main)
```

Key methods:
- `Window.async_create(connection)` - create window
- `window.async_create_tab()` - create tab
- `session.async_split_pane(vertical=True)` - split pane
- `session.async_send_text(text)` - send keystrokes
- `session.async_get_screen_contents()` - read screen

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Your Script                            │
├─────────────────────────────────────────────────────────────┤
│  LinkedSession (the core primitive)                         │
│  ├── iterm_session ──── iTerm2 Session object              │
│  ├── project_path ───── Where Claude is running            │
│  ├── session_id ─────── UUID from JSONL filename           │
│  ├── send() ─────────── Inject prompts (uses \x0d)         │
│  ├── read_screen() ──── Get terminal content               │
│  ├── refresh_state() ── Reload from JSONL                  │
│  └── wait_for_response() ── Poll until Claude done         │
├─────────────────────────────────────────────────────────────┤
│  Primitives                                                 │
│  ├── Session Discovery: list_sessions, find_active_session │
│  ├── State Parsing: parse_session, watch_session           │
│  ├── Terminal Control: send_text, send_key, read_screen    │
│  ├── Window Mgmt: create_window, split_pane               │
│  └── Lifecycle: start_claude, create_claude_session        │
└─────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
    iTerm2 API                  ~/.claude/projects/
    (async_send_text,           ({project-slug}/
     async_get_screen_contents)  {session-id}.jsonl)
```

## Key Codes Reference

```python
KEYS = {
    'enter': '\x0d',      # THE IMPORTANT ONE - actual Enter key
    'escape': '\x1b',
    'tab': '\t',
    'backspace': '\x7f',
    'up': '\x1b[A',
    'down': '\x1b[B',
    'right': '\x1b[C',
    'left': '\x1b[D',
    'ctrl-c': '\x03',
    'ctrl-u': '\x15',     # Clear line
    'ctrl-d': '\x04',     # EOF
}
```

## Common Patterns

### Create and interact with a Claude session

```python
async def main(connection):
    # Create new session
    linked = await create_claude_session(
        connection,
        project_path="/path/to/project",
        in_new_window=True
    )

    # Send prompt and wait for response
    await linked.send("What files are here?")
    response = await linked.wait_for_response()
    print(response.content)
```

### Attach to existing session

```python
async def main(connection):
    app = await iterm2.async_get_app(connection)

    # Find the iTerm2 session
    iterm_session = await find_claude_session(app, "/path/to/project")

    # Link it
    linked = await link_session(iterm_session, "/path/to/project")

    # Now you can interact
    await linked.send("Continue from where we left off")
```

### Monitor a session

```python
def monitor():
    project_path = "/path/to/project"
    session_id = find_active_session(project_path)
    jsonl_path = get_project_dir(project_path) / f"{session_id}.jsonl"

    for state in watch_session(jsonl_path):
        if state.last_assistant_message:
            print(f"Claude: {state.last_assistant_message.content[:100]}...")
```

## Troubleshooting

### "Enter isn't working"
Use `\x0d`, not `\n`. See Key Discoveries #1.

For long pastes (multi-line text), the delay before Enter must scale with
text length. iTerm2's bracketed paste mode needs time to process large buffers.
The `send_prompt()` function handles this automatically with a formula:
- Base: 0.1s for bracketed paste overhead
- +0.01s per line
- +0.05s per 1000 characters
- Maximum: 2.0s

### "Can't find session JSONL"
Check the slug conversion. Run:
```python
print(get_project_dir("/your/path"))
```

### "iTerm2 connection refused"
Enable: iTerm2 → Preferences → General → Magic → Enable Python API

### "Screen contents are empty"
The screen might not have rendered yet. Add a small delay:
```python
await asyncio.sleep(0.5)
screen = await read_screen(session)
```

## Window Splitting

iTerm2 supports splitting panes both vertically (side by side) and horizontally (stacked):

```python
# Split an existing session
pane2 = await session.async_split_pane(vertical=True, before=False)
#   vertical=True  → side by side (left/right)
#   vertical=False → stacked (top/bottom)
#   before=True    → new pane appears before/above
#   before=False   → new pane appears after/below
```

The library provides layout helpers:

```python
# Create a quad layout
layout = await create_split_layout(connection, "quad")
# Returns PaneLayout with panes: top_left, top_right, bottom_left, bottom_right

# Start Claude in each pane
await layout.start_claude_in_pane("top_left", "/path/to/frontend")
await layout.start_claude_in_pane("top_right", "/path/to/backend")

# Or use the combined helper
layout = await create_multi_claude_layout(connection, {
    "left": "/path/to/frontend",
    "right": "/path/to/backend"
}, layout="vertical")
```

Available layouts:
- `vertical`: 2 panes [left, right]
- `horizontal`: 2 panes [top, bottom]
- `quad`: 4 panes [top_left, top_right, bottom_left, bottom_right]
- `triple_vertical`: 3 panes [left, center, right]

## Primitives Summary

| Category | Primitives |
|----------|------------|
| **Session Discovery** | `list_sessions()`, `find_active_session()`, `get_project_dir()` |
| **State Parsing** | `parse_session()`, `watch_session()`, `SessionState`, `Message` |
| **Terminal Control** | `send_text()`, `send_key()`, `send_prompt()`, `read_screen()` |
| **Session Linking** | `LinkedSession`, `link_session()`, `find_claude_session()` |
| **Window Management** | `create_window()`, `create_tab()`, `split_pane()` |
| **Layouts** | `create_split_layout()`, `create_multi_claude_layout()`, `PaneLayout` |
| **Lifecycle** | `start_claude()`, `create_claude_session()` |

## Files in This Project

- `primitives.py` - Core building blocks (start here)
- `session_parser.py` - JSONL parsing (standalone, no iterm2 dep)
- `claude_controller.py` - Higher-level session management
- `orchestrator.py` - CLI tools
- `test_controller.py` - Working demo
- `test_split.py` - Window splitting demo
