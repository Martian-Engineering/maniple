# Remove Issue Tracker Integration Spec

## Summary
Remove all built-in Beads/Pebbles issue tracker integration from claude-team. The
coordinator will handle issue tracking externally. The only remaining trace is
the optional `bead` parameter used for labeling (badge/branch/prompt context).

## Current integration points to remove

### Core code

| Area | File | Functions/Refs | Action |
| --- | --- | --- | --- |
| Issue tracker abstraction | src/claude_team_mcp/issue_tracker/__init__.py | `IssueTrackerBackend`, `BeadsBackend`, `PebblesBackend`, `BACKEND_REGISTRY`, `detect_issue_tracker` | Delete module entirely |
| Worker prompts | src/claude_team_mcp/worker_prompt.py | `_resolve_issue_tracker_backend`, `_format_tracker_command`, `_supported_tracker_list`, `_build_tracker_workflow_section`, issue-tracker-specific branches in `_generate_claude_worker_prompt` and `_generate_codex_worker_prompt`, `get_coordinator_guidance` issue tracker text | Modify to remove detection and tracker workflow. Keep `bead` for labeling and assignment text only |
| Message hints | src/claude_team_mcp/utils/constants.py | `ISSUE_TRACKER_HELP_TOOL`, `_format_tracker_command`, `_supported_trackers_summary`, `build_issue_tracker_help_text`, `build_issue_tracker_quick_commands`, `build_worker_message_hint` | Delete functions and constant |
| Worktree tracker env | src/claude_team_mcp/utils/worktree_detection.py | `get_worktree_tracker_dir` uses `.beads`/`.pebbles` markers and `BEADS_DIR`/`PEBBLES_DIR` env vars | Delete module or function |
| Utils exports | src/claude_team_mcp/utils/__init__.py | issue tracker helpers and `get_worktree_tracker_dir` in exports | Modify to remove exports |
| Issue tracker help tool | src/claude_team_mcp/tools/issue_tracker_help.py | `issue_tracker_help` tool | Delete file |
| Tool registration | src/claude_team_mcp/tools/__init__.py | registers `issue_tracker_help` | Modify to remove registration |
| Message workers | src/claude_team_mcp/tools/message_workers.py | `detect_issue_tracker`, `build_worker_message_hint`, `build_worker_message_hint` usage | Modify to send plain message without tracker hint |
| Spawn workers | src/claude_team_mcp/tools/spawn_workers.py | Docstrings mention `bd`/`pb`; `get_worktree_tracker_dir` + env var injection; `generate_worker_prompt` uses tracker path | Modify to remove tracker env var logic and update docstrings/prompts. Keep `bead` parameter for labeling |

### Docs and command references

| Area | File | Refs | Action |
| --- | --- | --- | --- |
| README | README.md | Beads/Pebbles support section | Update to remove tracker integration |
| Contributor docs | CLAUDE.md | Tracker workflow, pb/bd commands | Update or remove sections |
| Tracker architecture doc | docs/ISSUE_TRACKER_ABSTRACTION.md | Entire document | Remove or replace with removal note |
| Commands | commands/spawn-workers.md | pb/bd workflow and tracker guidance | Update to coordinator-managed tracking |
| Commands | commands/team-summary.md | pb/bd closed issue query | Update to coordinator-managed tracking |

### Tests

| Area | File | Refs | Action |
| --- | --- | --- | --- |
| Issue tracker tests | tests/test_issue_tracker.py | `detect_issue_tracker`, backend command templates | Delete |
| Worktree tracker env tests | tests/test_worktree_detection.py | `get_worktree_tracker_dir` and BEADS_DIR/PEBBLES_DIR | Delete or rewrite for new behavior |
| Worker prompts | tests/test_worker_prompt.py | Tracker workflow text, show commands, backend hints | Update expectations |
| Formatting | tests/test_formatting.py | Bead badge formatting | Keep (bead label still needed) |

### False positives to ignore

| File | Note |
| --- | --- |
| uv.lock | Contains "bd" in a package URL; not issue tracker integration |

## What stays vs goes

### Keep
- `bead` parameter in `spawn_workers` and `WorkerConfig` for labeling.
- Bead-based badge formatting and worktree branch naming.
- Coordinator guidance summaries that mention the bead id, but no tracker workflow.

### Remove
- Issue tracker detection (`.beads`/`.pebbles`) and backend registry.
- `BEADS_DIR`/`PEBBLES_DIR` env var injection for worktrees.
- `issue_tracker_help` tool and all issue tracker quick-reference helpers.
- Tracker commands in worker prompts (no pb/bd instructions).
- Message worker hinting that points to `issue_tracker_help` or tracker CLI.
- Docs that instruct pb/bd workflows as part of claude-team.

## Simplified architecture

- `spawn_workers` accepts `prompt` and optional `bead` id for labeling only.
- Worker prompt includes the assignment and any custom prompt. It never
  detects or references trackers and never injects tracker CLI commands.
- No `BEADS_DIR` or `PEBBLES_DIR` env vars are set for worker sessions.
- Coordinator calls pb/bd (or any tracker) directly outside the MCP server.

## Implementation phases (estimates)

| Phase | Scope | Effort |
| --- | --- | --- |
| 1 | Remove issue tracker module, tool, constants, exports | 1-2 hours |
| 2 | Update worker prompts, spawn_workers, message_workers to remove tracker logic | 2-3 hours |
| 3 | Update docs and command references; delete tracker docs | 1-2 hours |
| 4 | Update or remove tests that assert tracker behavior | 1-2 hours |
| 5 | Sanity check and documentation sweep | 0.5-1 hour |

## Migration notes

### What breaks
- `issue_tracker_help` tool no longer exists.
- `.beads`/`.pebbles` detection is removed.
- `BEADS_DIR`/`PEBBLES_DIR` env vars are no longer set in worker sessions.
- Worker prompts will no longer instruct pb/bd workflows or provide show/update
  commands.
- Tests and docs that assume tracker support will fail until updated.

### How to adapt
- Coordinators should run pb/bd commands externally (outside MCP) and pass
  only the issue id via `bead` for labeling.
- Update any tooling or scripts that rely on `issue_tracker_help` or tracker
  env vars to use direct CLI calls instead.
- Remove or revise documentation references to Beads/Pebbles integration.

