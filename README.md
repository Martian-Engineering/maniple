# Claude Team MCP Server

An MCP server that allows one Claude Code session to spawn and manage a team of other Claude Code sessions via iTerm2.

## Features

- **Spawn Sessions**: Create new Claude Code sessions in iTerm2 windows or split panes
- **Send Messages**: Inject prompts into managed sessions
- **Read Responses**: Retrieve conversation state from session JSONL files
- **Monitor Status**: Check if sessions are idle, processing, or waiting for input
- **Coordinate Work**: Manage multi-agent workflows from a single Claude Code session

## Requirements

- macOS with iTerm2 installed
- iTerm2 Python API enabled (Preferences → General → Magic → Enable Python API)
- Python 3.11+
- uv package manager

## Installation

```bash
# Clone the repository
cd /path/to/claude-team

# Install with uv
uv sync
```

## Configuration for Claude Code

Add to your Claude Code MCP settings. You can configure this at:
- **Global**: `~/.claude/settings.json`
- **Project**: `.claude/settings.json` in your project directory

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

## MCP Tools

| Tool | Description |
|------|-------------|
| `spawn_session` | Create a new Claude Code session in a new window or split pane |
| `list_sessions` | List all managed sessions with status |
| `send_message` | Send a prompt to a session, optionally wait for response |
| `get_response` | Get the latest response from a session |
| `get_session_status` | Get detailed status including screen preview |
| `close_session` | Gracefully terminate a session |

### Tool Details

#### spawn_session
```
Arguments:
  project_path: str      - Directory where Claude Code should run
  session_name: str      - Optional friendly name for the session
  layout: str            - "new_window", "split_vertical", or "split_horizontal"

Returns:
  session_id, name, project_path, status, claude_session_id
```

#### send_message
```
Arguments:
  session_id: str              - ID of target session
  message: str                 - The prompt to send
  wait_for_response: bool      - If True, wait for Claude to respond
  timeout: float               - Max seconds to wait (default: 120)

Returns:
  success, session_id, message_sent, [response]
```

#### get_response
```
Arguments:
  session_id: str    - ID of target session
  wait: bool         - If True, wait if session is processing
  timeout: float     - Max seconds to wait (default: 60)

Returns:
  session_id, status, is_processing, last_response, tool_uses, message_count
```

## Usage Patterns

### Basic: Spawn and Send

From your Claude Code session, you can spawn workers and send them tasks:

```
"Spawn a new Claude session in /path/to/frontend"
→ Uses spawn_session tool
→ Returns session_id: "worker-1"

"Send worker-1 the message: Review the React components"
→ Uses send_message tool

"Check on worker-1's progress"
→ Uses get_session_status tool
```

### Parallel Work Distribution

Spawn multiple workers for parallel tasks:

```
"Create three worker sessions:
 - worker-frontend in /path/to/frontend
 - worker-backend in /path/to/backend
 - worker-tests in /path/to/tests"

"Send each worker their task:
 - frontend: Update the login page styles
 - backend: Add rate limiting to the API
 - tests: Write integration tests for auth"

"Wait for all workers and collect their responses"
```

### Coordinated Workflow

Use the manager to coordinate between workers:

```
"Spawn a backend worker and have it create a new API endpoint"
→ Wait for response

"Now spawn a frontend worker and tell it about the new endpoint"
→ Pass context from backend worker's response

"Finally, spawn a test worker to write tests for the integration"
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              Manager Claude Code Session                     │
│              (has claude-team MCP server)                    │
├─────────────────────────────────────────────────────────────┤
│                    MCP Tools                                 │
│  spawn_session │ send_message │ get_response │ list_sessions │
└────────────────┬────────────────────────────────────────────┘
                 │
        ┌────────┼────────┐
        ▼        ▼        ▼
   ┌─────────┐ ┌─────────┐ ┌─────────┐
   │Worker 1 │ │Worker 2 │ │Worker 3 │
   │(iTerm2) │ │(iTerm2) │ │(iTerm2) │
   │         │ │         │ │         │
   │ Claude  │ │ Claude  │ │ Claude  │
   │  Code   │ │  Code   │ │  Code   │
   └─────────┘ └─────────┘ └─────────┘
```

The manager maintains:
- **Session Registry**: Maps session IDs to iTerm2 sessions
- **iTerm2 Connection**: Persistent connection for terminal control
- **JSONL Monitoring**: Reads Claude's session files for conversation state

## Development

```bash
# Sync dependencies
uv sync

# Run tests
uv run pytest

# Run the server directly (for debugging)
uv run python -m claude_team_mcp
```

## Troubleshooting

### "Could not connect to iTerm2"
- Make sure iTerm2 is running
- Enable: iTerm2 → Preferences → General → Magic → Enable Python API

### "Session not found"
- The session may have been closed externally
- Use `list_sessions` to see active sessions

### "No JSONL session file found"
- Claude Code may still be starting up
- Wait a few seconds and try again

## License

MIT
