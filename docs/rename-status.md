# Rename Status: claude-team -> maniple

Date: 2026-02-10

## Current Branch State

- Branch: `feature/rename-to-maniple` (worktree branch: `sade-7257da0d-continue-rename-to-maniple`)
- `origin/main` is an ancestor of this branch (rebased / no divergence).
  - `origin/main`: `863ce5f`
  - HEAD: `386385f`
  - Ahead/behind vs `origin/main`: `+23 / -0`

## Most Recent Change (HEAD)

- Commit `386385f` (`chore: normalize uv.lock after rebase`)
  - Only change: `uv.lock`
  - Effect: removed a duplicate `[[package]] maniple` block and normalized the editable project entry to version `0.10.0`.

## What Has Landed So Far (High-Level)

This branch already includes a large portion of the rename/migration work (via merged subtasks), including:

- Packaging/CLI
  - Project renamed to `maniple` in `pyproject.toml`.
  - CLI entrypoint now exposed as `maniple` (points to `maniple_mcp:main`).
  - Python packages live under `src/maniple/` and `src/maniple_mcp/`.

- Migration + config
  - Data/config directory migrated from `~/.claude-team` to `~/.maniple`.
  - Environment variables renamed to `MANIPLE_*` with fallback support for `CLAUDE_TEAM_*` during migration.

- Logging + tmux
  - Logger namespaces renamed to `maniple.*`.
  - tmux session prefix renamed to `maniple-...`.

- Misc
  - MCP server key references updated.
  - Doc and test sweeps merged.

## What Still Looks Incomplete / Inconsistent (Focus: tmux + discovery/adoption)

There are still several places where the system is branded/implemented as "claude-team" even though the package/CLI is now "maniple". The biggest risk area for reliability is session discovery/adoption, especially for tmux.

### 1. JSONL Marker Prefix Migration (Dual Support Required)

- New sessions should emit `<!maniple-...!>` markers:
  - `<!maniple-session:...!>`
  - `<!maniple-iterm:...!>`
  - `<!maniple-tmux:...!>`
  - `<!maniple-project:...!>`
- During the migration window, discovery/adoption should accept both `<!maniple-...!>` and legacy `<!claude-team-...!>` markers when scanning JSONL.

`discover_workers` / `adopt_worker` rely on these markers (via `find_jsonl_by_iterm_id()` / `find_jsonl_by_tmux_id()`).

If we switch worker prompts to emit `<!maniple-...!>` markers, we must update the scanners accordingly or discovery/adoption will break.

### 2. tmux Session Filtering Blocks Migration Adoption

- The tmux backend must consider both `maniple-*` and legacy `claude-team-*` tmux session prefixes during the rename transition.

If a user upgrades while existing workers are still running under the old tmux session prefix (likely `claude-team-...`), `discover_workers` will not see them at all, even if the JSONL contains valid markers.

### 3. `unslugify_path()` Has a `--claude-team` Special Case

- `src/maniple_mcp/session_state.py` has a hard-coded slug rewrite:
  - `slug = slug.replace("--claude-team", "-.claude-team")`

This suggests we hit a real-world ambiguity before. It probably needs re-evaluation for `maniple` (and/or removal if it was only relevant to older project layouts).

## Proposed Next Steps (Concrete, tmux + adoption/discovery reliability)

1. Decide marker migration strategy (recommended: transitional support).
   - Emit `<!maniple-...!>` markers for new sessions.
   - Accept both `<!claude-team-...!>` and `<!maniple-...!>` markers when scanning JSONLs for discovery/adoption for at least one release.
   - Update `discover_workers` / `adopt_worker` docstrings accordingly.

2. Make tmux discovery resilient during the transition.
   - Option A (migration-friendly): treat both `maniple-*` and `claude-team-*` tmux session prefixes as "managed" during the rename window.
   - Option B (hard cutover): keep only `maniple-*` managed; document that older sessions cannot be adopted post-upgrade.

3. Add an end-to-end validation path for tmux recovery.
   - Manual test recipe:
     - Spawn workers under tmux.
     - Restart the MCP server.
     - Run `discover_workers` and confirm sessions are detected.
     - Run `adopt_worker` and confirm registry state becomes READY and messaging works.
   - If feasible, add a focused unit test that exercises tmux marker parsing with `%` pane ids and (if chosen) dual-prefix marker support.

## Test Results

Full test suite:

- Command: `uv run pytest`
- Result: `524 passed in 33.31s`
