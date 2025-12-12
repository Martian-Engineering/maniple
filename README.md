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
cd /path/to/claude-iterm-controller

# Install with uv
uv sync

# Or install in development mode
uv pip install -e .
```

## Usage with Claude Code

Add to your Claude Code MCP settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "claude-team": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/claude-iterm-controller", "python", "-m", "claude_team_mcp"]
    }
  }
}
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `spawn_session` | Create a new Claude Code session |
| `list_sessions` | List all managed sessions |
| `send_message` | Send a prompt to a session |
| `get_response` | Get/wait for a response |
| `get_session_status` | Get detailed session status |
| `close_session` | Terminate a session |

## Development

```bash
# Run tests
uv run pytest

# Run the server directly
uv run python -m claude_team_mcp
```

## License

MIT
