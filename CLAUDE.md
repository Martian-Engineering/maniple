# Claude Team MCP Server

An MCP server that enables a "manager" Claude Code session to spawn and orchestrate multiple "worker" Claude Code sessions via iTerm2.

## Project Structure

```
src/claude_team_mcp/           # Main MCP server package
├── server.py                  # FastMCP server with all 15 MCP tool implementations
├── registry.py                # Session tracking (ManagedSession, SessionRegistry)
├── session_state.py           # JSONL parsing for Claude conversation logs
├── iterm_utils.py             # Low-level iTerm2 API wrappers
├── idle_detection.py          # Stop hook completion detection
├── profile.py                 # iTerm2 profile/theme management
├── colors.py                  # Golden ratio tab color generation
└── formatting.py              # Title/badge formatting utilities

scripts/                       # Utility scripts
└── install-commands.py        # Install slash commands to ~/.claude/commands/

tests/                         # Pytest unit tests
```

## Makefile Targets

```bash
make help                  # Show available targets
make install-commands      # Install slash commands to ~/.claude/commands/
make install-commands-force # Overwrite existing commands
make test                  # Run pytest
make sync                  # Sync dependencies
```

## Key Modules

| Module | Purpose |
|--------|---------|
| `server.py` | Entry point; defines all MCP tools (`spawn_team`, `send_message`, `get_response`, etc.) |
| `registry.py` | Tracks managed sessions, states: SPAWNING → READY → BUSY → CLOSED |
| `session_state.py` | Parses Claude's JSONL files at `~/.claude/projects/{slug}/{session}.jsonl` |
| `iterm_utils.py` | Terminal control: `send_text`, `send_prompt`, window/pane creation |
| `idle_detection.py` | Stop hook completion detection |
| `profile.py` | Auto dark/light mode, screen dimensions, font configuration |

## Critical Implementation Details

### Enter Key Handling
**Use `\x0d` (carriage return) for Enter, NOT `\n`**
- `\n` creates a newline in input buffer but doesn't submit
- `\x0d` triggers actual Enter keypress
- Multi-line text requires delays before Enter (bracketed paste mode)

### JSONL Session Discovery
Claude stores conversations at:
```
~/.claude/projects/{project-slug}/{session-id}.jsonl
```
Where `{project-slug}` = project path with `/` → `-` (e.g., `/Users/josh/code` → `-Users-josh-code`)

### Completion Detection Strategies
1. **Stop hooks** (primary): Automatic detection when Claude finishes responding — highest confidence
2. **Git commits**: New commits since task started
3. **Beads issues**: Issue status changed to closed
4. **Idle detection**: Fallback when other signals unavailable

### Layout Options
- `single`: 1 pane, full window (main)
- `vertical`: 2 panes side by side (left, right)
- `horizontal`: 2 panes stacked (top, bottom)
- `quad`: 4 panes in 2x2 grid (top_left, top_right, bottom_left, bottom_right)
- `triple_vertical`: 3 panes side by side (left, middle, right)

## Running & Testing

```bash
# Sync dependencies
uv sync

# Run tests
uv run pytest

# Run server directly (debugging)
uv run python -m claude_team_mcp
```

## Requirements
- macOS with iTerm2 (Python API enabled)
- Python 3.11+
- uv package manager

## Development Workflow

This project uses **Beads** for issue tracking instead of markdown todos. Key commands:

```bash
bd list                    # List all issues
bd ready                   # Show issues ready to work (no blockers)
bd show <issue-id>         # Show issue details
bd update <issue-id> --status in_progress
bd close <issue-id>
bd dep tree <issue-id>     # Visualize dependencies
```

Current epics are tracked with dependencies. Check `bd list` to see all issues and `bd ready` for unblocked work.

### Beginning Work

IMPORTANT: Before doing any work, always create a beads issue or, if appropriate, epic.

### Plan Mode Workflow

When working on complex features that require planning (via `EnterPlanMode`), follow this workflow:

1. **During plan mode**: Explore the codebase, understand patterns, and write a detailed plan to the plan file
2. **Before exiting plan mode**: Ensure the plan captures all subtasks, configuration decisions, and dependencies
3. **First implementation step**: After exiting plan mode, **always** create beads issues before writing any code:
   - Create an **epic** for the overall feature/deployment
   - Create **subtasks** as individual beads issues, one per discrete piece of work
   - Each issue description should capture relevant context from the plan (what to implement, key decisions, file paths)
   - Set up **dependencies** using `bd dep add <epic-id> <subtask-id>` so the epic depends on its subtasks
   - Subtasks that depend on each other should also have dependencies set

4. **Then proceed with implementation**: Work through the subtasks using the normal task workflow

This ensures planning context is preserved in trackable issues rather than lost when the plan file is no longer referenced.

**Example**:
```bash
# After exiting plan mode for "RDS Deployment" epic:
bd create --title="RDS Deployment & pg-sync Service" --type=epic --description="..."
bd create --title="Create RDS Terraform module" --type=task --description="Create terraform/modules/rds/ with..."
bd create --title="Add RDS to dev environment" --type=task --description="..."
bd dep add <epic-id> <task1-id>
bd dep add <epic-id> <task2-id>
bd dep add <task2-id> <task1-id>  # task2 depends on task1
```

### Prioritizing Work

Always start by checking for in-progress work:

1. **Check for in-progress epics**: Run `bd list --status in_progress` to see which epics are currently being worked on
2. **Focus on epic tasks**: If an epic is in-progress, prioritize tasks that block that epic
3. **Check ready work**: Use `bd ready` to see unblocked tasks, then choose tasks related to in-progress epics
4. **Mark epics in-progress**: When starting work on an epic's tasks, mark the epic as `in_progress` if not already marked

### Task Workflow

When working on individual issues, follow this workflow:

1. **Start work**: `bd update <issue-id> --status in_progress` (for both epics and tasks)
2. **Complete the work**: Implement the feature/fix
3. **Close the issue**: `bd close <issue-id>`
4. **Commit immediately**: Create a git commit after closing each issue with:
   - Summary of completed issue(s) in the commit message
   - List of changes made
   - Reference to issue IDs that were closed

This ensures a clean audit trail where commits map directly to completed work items.

### Discovering Issues During Development

When bugs, inconsistencies, or improvements are discovered during development:

1. **Create an issue immediately**: Use `bd create` to document the problem as soon as it's discovered
2. **Err on the side of creating issues**: Better to have tracked issues than forgotten problems
3. **Link to relevant epics**: Use `bd dep add <epic-id> <issue-id>` to link the new issue to related epics
4. **Don't let issues block current work**: If the discovered issue isn't critical, create it and continue with the current task
5. **Document what was found**: Include enough detail in the issue description for someone else (or future you) to understand the problem

Examples of when to create issues:
- User testing reveals unexpected behavior
- Inconsistent UI/UX patterns across screens
- Missing functionality that should be added for completeness
- Technical debt or code that needs refactoring
- Documentation that needs updating

### Git Workflow

⚠️ **NEVER make code changes directly on main.** All work happens on branches.

**BEFORE making any code changes:**

1. **Check current state** - Run `git status` and `git branch --show-current`
   - If there's uncommitted work or you're not on `main`, ask for instructions

2. **Determine the branch strategy:**
   - **For epic subtasks**: Check if an epic branch already exists (format: `<epic-id>/<description>`). If so, switch to it. If not, create it.
   - **For standalone issues** (tasks/bugs not part of an epic): Create a branch with format `<issue-id>/<description>`

   Examples:
   - Epic branch: `64o/repo-setup`
   - Standalone issue branch: `1n7/package-installation`

3. **Create/switch to the branch**, then begin implementation

4. **Work on the branch** - All subtasks of an epic happen on the same epic branch

5. **Await approval** - When epic/issue is complete, wait for explicit confirmation before merging to main

Whenever you create new branches or worktrees, hold off on merging them until you get my explicit approval.

