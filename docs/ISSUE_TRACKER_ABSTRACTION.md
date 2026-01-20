# Issue Tracker Abstraction Plan

## Current Beads Integration Points

- Worker prompts include Beads-only instructions, commands, and wording in `src/claude_team_mcp/worker_prompt.py`.
- Worktree detection assumes `.beads` in `src/claude_team_mcp/utils/worktree_detection.py` and sets `BEADS_DIR` when spawning workers.
- `spawn_workers` docstrings and behavior reference Beads in `src/claude_team_mcp/tools/spawn_workers.py`.
- The worker message hint and help text are Beads-specific in `src/claude_team_mcp/utils/constants.py` and `src/claude_team_mcp/tools/bd_help.py`.
- `message_workers` always appends a Beads hint in `src/claude_team_mcp/tools/message_workers.py`.
- Tests assert Beads command strings in `tests/test_worker_prompt.py`.
- Docs and command guides hard-code Beads instructions: `CLAUDE.md`, `README.md`, `commands/*.md`.

## Issue Tracker Operations Currently Used

These appear in prompts, help text, docs, or tests:

- List: `bd list`
- Ready: `bd ready`
- Show: `bd show <issue-id>`
- Update status: `bd update <issue-id> --status in_progress`
- Comment: `bd comment <issue-id> "..."`
- Close: `bd close <issue-id>`
- Create: `bd create --title ... --type ... --priority ... --description ...`
- Search: `bd search <query>`
- Blocked: `bd blocked`
- Dependencies: `bd dep add`, `bd dep tree`
- Worktrees: `bd --no-db ...` (required today)

## Proposed Abstraction Interface

Create a small issue tracker abstraction layer that provides:

- A backend registry with two implementations: Beads (bd) and Pebbles (pb).
- A capability surface used by prompts/help/docs (not yet direct CLI calls).
- A detection method that chooses the backend based on repo state or config.

### Suggested Module Layout

- `src/claude_team_mcp/issue_tracker.py` (or `src/claude_team_mcp/issue_tracker/__init__.py`)
  - `IssueTrackerBackend` protocol or dataclass:
    - `name` ("beads" | "pebbles")
    - `cli` ("bd" | "pb")
    - `marker_dir` (".beads" | ".pebbles")
    - `env_var` (e.g., `BEADS_DIR`, TBD for Pebbles)
    - `requires_no_db_flag` (bool)
    - `commands` (templates for operations below)
    - `supports` (capabilities: search, blocked, dep_types)
  - `detect_issue_tracker(project_path: str) -> IssueTrackerBackend`:
    - Auto-detect via marker dirs in repo root or main repo (worktree-aware).
    - Optional override via env `CLAUDE_TEAM_ISSUE_TRACKER=beads|pebbles`.
    - If both `.beads` and `.pebbles` exist, log and pick deterministic behavior (prefer override).
  - `get_worktree_issue_tracker_dir(project_path: str) -> dict | None`:
    - Returns `{env_var: path}` for the tracker in the main repo.

### Command Templates to Centralize

The interface should surface command strings used in prompts and help:

- `list`, `ready`, `show`, `update_status`, `comment`, `close`, `create`,
  `dep_add`, `dep_rm`, `dep_tree`, `search`, `blocked`.

Commands should be parameterized in one place and reused by:

- `worker_prompt.py`
- `utils/constants.py` (help text)
- `tools/bd_help.py` (rename or alias to `issue_tracker_help`)
- docs and command templates

If a command is unsupported (e.g., Pebbles `search`), return `None` and omit
it from help text or provide the closest alternative.

## Detection Strategy (.beads vs .pebbles)

- Use the current `git rev-parse --git-common-dir` approach to locate the main repo.
- Look for `.pebbles` or `.beads` in the main repo root.
- If both exist:
  - Prefer `CLAUDE_TEAM_ISSUE_TRACKER` env var.
  - Otherwise log a warning and choose a default (recommend `.pebbles`).
- If neither exists:
  - Return `None` and avoid appending tracker instructions.

## Feature Gaps Between Beads and Pebbles

Based on `pb --help` output:

- Pebbles lacks `search`, `blocked`, and `dep cycles` commands.
- Pebbles dependency types appear limited to `blocks` and `parent-child`.
  Beads adds `related` and `discovered-from`.
- Pebbles does not expose a `--no-db` flag; Beads uses `--no-db` for worktrees.
- Pebbles includes `log`, `rename`, `rename-prefix`, `prefix set`, and `import beads`.
- Pebbles `create`/`update` use short flags (`-title`, `-description`, etc.).

Open questions to confirm:

- Pebbles project discovery and env var name (if any) for locating `.pebbles`.
- Pebbles status values (should align with Beads `open`/`in_progress`/`closed`).

## Implementation Plan (No Code Changes Yet)

1. Add issue tracker abstraction module and backend registry.
   - Define command templates, capabilities, and detection logic.
   - Estimated effort: 1-2 hours.
2. Update worktree detection to return tracker-specific env var.
   - Replace `get_worktree_beads_dir` with generalized function.
   - Estimated effort: 1 hour.
3. Replace Beads-specific prompt/help strings with backend data.
   - Update `worker_prompt.py`, `constants.py`, `bd_help.py`, and
     `message_workers.py` to use the abstraction.
   - Estimated effort: 2-3 hours.
4. Update docs/tests to be tracker-neutral.
   - Adjust `tests/test_worker_prompt.py`, `CLAUDE.md`, `README.md`, and
     `commands/*.md`.
   - Estimated effort: 1-2 hours.

## Concerns / Blockers

- Need confirmation on Pebbles env var or CLI flags for pointing to a project
  directory in worktrees (Beads currently relies on `BEADS_DIR`).
- Some Beads guidance (search/blocked/related deps) has no Pebbles equivalent;
  documentation and prompts must omit or adapt those sections.
- If both `.beads` and `.pebbles` exist in a repo, detection order must be
  explicitly defined to avoid silent misrouting.
