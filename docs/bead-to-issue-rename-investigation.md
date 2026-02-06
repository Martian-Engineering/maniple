# Investigation: Rename `bead` to `issue` for Issue Tracker Agnosticism

## Executive Summary

The `bead` parameter name is specific to the Beads/Pebbles issue tracker, but claude-team now supports multiple issue trackers (Beads, Pebbles, and extensible). The parameter should be renamed to `issue` or `issue_id` for clarity and consistency.

**Current State:** The codebase is already **inconsistent** - some parts use `issue_id`, some use `bead`, and some use `bead_id`.

**Recommendation:** Standardize on `issue_id` (not just `issue`) to match existing patterns in terminal backends and formatting utilities.

## Current Usage Analysis

### Files Using `bead` Parameter

| File | Usage | Lines | Impact |
|------|-------|-------|--------|
| `spawn_workers.py` | WorkerConfig field, parameter | 48, 125-131, 280, 323, 374, 380, 391, 744-765, 804-811 | **HIGH** - Public API |
| `worker_prompt.py` | Function parameter | 89, 100, 118, 127, 137, 152 | **MEDIUM** - Internal |
| `formatting.py` | `format_badge_text()` parameter | 58, 64, 67, 72, 83, 100, 103-104 | **MEDIUM** - Internal |
| `worktree.py` | `bead_id` parameter | 16, 273, 282, 291, 298, 314, 319, 333-338 | **MEDIUM** - Internal |
| `poll_worker_changes.py` | Helper function | 74 | **LOW** - Internal helper |

### Files Already Using `issue_id`

| File | Usage | Notes |
|------|-------|-------|
| `terminal_backends/tmux.py` | create_session parameter | Lines 136, 147-148, 193-194 |
| `terminal_backends/iterm.py` | create_session parameter | Line 91 |
| `formatting.py` | `format_session_title()` parameter | Lines 13, 24, 43-46 |

### Documentation Files

- `docs/coordinator-annotation.md` - 18 references to "bead"
- `docs/task-delivery-quick-reference.md` - 12 references to "bead"
- `docs/README.md` - 1 reference to "bead"
- `commands/spawn-workers.md` - Multiple references
- `README.md` - Multiple references
- `CHANGELOG.md` - Historical references (keep as-is)

### Test Files

- `tests/test_formatting.py` - 21 references (test `format_badge_text` with `bead` param)
- `tests/test_worker_prompt.py` - Multiple references
- `tests/test_worktree_detection.py` - References to `bead_id`
- `tests/test_config.py` - References to "beads" tracker name (different - keep these)
- `tests/test_issue_tracker.py` - References to "beads" tracker (different - keep these)

## Naming Consistency Issues

The codebase currently has three different naming patterns:

1. **`bead`** - Used in spawn_workers, worker_prompt, format_badge_text
2. **`bead_id`** - Used in worktree.py
3. **`issue_id`** - Used in terminal backends, format_session_title

**Proposed Standard:** `issue_id` (most descriptive, matches existing conventions)

## Backward Compatibility Considerations

### Breaking Change: MCP Tool API

The `spawn_workers` tool's `WorkerConfig` TypedDict has `bead` as a public field. Renaming this is a **breaking change** for:

1. **Coordinator agents** calling the tool
2. **User scripts** using the MCP API
3. **Documentation** and examples

### Migration Strategy Options

#### Option 1: Immediate Breaking Change (Recommended)
- Rename `bead` → `issue_id` everywhere
- Update all documentation
- Bump major version (0.x → 1.0 or maintain 0.x with breaking change notice)
- No backward compatibility layer

**Pros:**
- Clean codebase
- Consistent naming
- No technical debt

**Cons:**
- Breaks existing coordinator agents
- Requires documentation updates

#### Option 2: Deprecation Period
- Accept both `bead` and `issue_id` in WorkerConfig
- Log deprecation warning when `bead` is used
- Remove `bead` in next major version

**Pros:**
- Gradual migration
- Less disruptive

**Cons:**
- Adds complexity
- Two code paths to maintain
- Still requires eventual breaking change

#### Option 3: Alias with Preference
- Internally use `issue_id` everywhere
- Accept `bead` as an alias in WorkerConfig (map to `issue_id`)
- Document `issue_id` as preferred, `bead` as legacy

**Pros:**
- No breaking change
- Gradual adoption

**Cons:**
- Perpetuates confusion
- Two names for same concept
- Documentation complexity

### Recommendation

**Use Option 1** - Immediate breaking change. The project is early (0.x versions) and used primarily by coordinators that can be updated. A clean break is better than technical debt.

## Implementation Plan

### Phase 1: Core Parameter Rename

1. **spawn_workers.py**
   - Rename `WorkerConfig.bead` → `WorkerConfig.issue_id`
   - Update all `w.get("bead")` → `w.get("issue_id")`
   - Update all docstring references
   - Update variable names: `bead = ...` → `issue_id = ...`

2. **worker_prompt.py**
   - Rename parameter `bead` → `issue_id` in:
     - `generate_worker_prompt()`
     - `_generate_claude_worker_prompt()`
     - `_generate_codex_worker_prompt()`
     - `_build_tracker_workflow_section()`
   - Update all internal references

3. **formatting.py**
   - Rename `format_badge_text(bead=...)` → `format_badge_text(issue_id=...)`
   - Update docstring and examples
   - Update internal logic: `first_line = bead if bead else name` → `first_line = issue_id if issue_id else name`

4. **worktree.py**
   - Rename `bead_id` → `issue_id` in `create_local_worktree()`
   - Update docstring and examples
   - Update branch naming logic

5. **poll_worker_changes.py**
   - Rename `_event_bead()` → `_event_issue_id()` (if it matters)

### Phase 2: Update All Call Sites

6. **spawn_workers.py** (internal calls)
   - Line 323: `bead_id=bead` → `issue_id=issue_id`
   - Line 380: `issue_id=bead` → `issue_id=issue_id` (already uses issue_id!)
   - Line 391: `bead=bead` → `issue_id=issue_id`
   - Line 765: `bead=bead` → `issue_id=issue_id`

### Phase 3: Tests

7. **test_formatting.py**
   - Update all `format_badge_text(bead=...)` calls
   - Rename test methods:
     - `test_badge_with_bead_and_annotation` → `test_badge_with_issue_id_and_annotation`
     - `test_badge_with_bead_only` → `test_badge_with_issue_id_only`
     - etc.

8. **test_worker_prompt.py**
   - Update all calls with `bead=...` parameter

9. **test_worktree_detection.py**
   - Update references to `bead_id`

10. **Other test files**
    - Search and update any remaining references

### Phase 4: Documentation

11. **docs/coordinator-annotation.md**
    - Replace all "bead" → "issue_id" or "issue ID"
    - Update code examples

12. **docs/task-delivery-quick-reference.md**
    - Replace all "bead" → "issue_id" or "issue"
    - Update code examples

13. **docs/README.md**
    - Update references

14. **commands/spawn-workers.md**
    - Update examples

15. **README.md**
    - Update examples and descriptions

16. **CLAUDE.md** (project instructions)
    - Update references to "bead" parameter

### Phase 5: Verification

17. **Run full test suite**
    ```bash
    uv run pytest -v
    ```

18. **Test manually**
    - Spawn worker with `issue_id`
    - Verify badge shows issue_id
    - Verify branch naming works
    - Verify worker prompt correct

19. **Update CHANGELOG.md**
    - Document breaking change
    - Provide migration guidance

### Phase 6: Version Bump

20. **Update version**
    - Bump version to indicate breaking change
    - Update marketplace.json and plugin.json if applicable

## Detailed Change Checklist

### Code Changes

- [ ] `spawn_workers.py` - WorkerConfig TypedDict
- [ ] `spawn_workers.py` - All internal usage
- [ ] `spawn_workers.py` - Docstring
- [ ] `worker_prompt.py` - generate_worker_prompt()
- [ ] `worker_prompt.py` - _generate_claude_worker_prompt()
- [ ] `worker_prompt.py` - _generate_codex_worker_prompt()
- [ ] `worker_prompt.py` - _build_tracker_workflow_section()
- [ ] `formatting.py` - format_badge_text()
- [ ] `formatting.py` - Docstring and examples
- [ ] `worktree.py` - create_local_worktree()
- [ ] `worktree.py` - Docstring and examples
- [ ] `poll_worker_changes.py` - _event_bead() function

### Test Changes

- [ ] `test_formatting.py` - All bead parameter usage
- [ ] `test_formatting.py` - Test method names
- [ ] `test_worker_prompt.py` - All bead parameter usage
- [ ] `test_worktree_detection.py` - bead_id references
- [ ] Run full test suite and fix any failures

### Documentation Changes

- [ ] `docs/coordinator-annotation.md`
- [ ] `docs/task-delivery-quick-reference.md`
- [ ] `docs/README.md`
- [ ] `commands/spawn-workers.md`
- [ ] `README.md`
- [ ] `CLAUDE.md` (both global and project-specific)

### Version and Release

- [ ] Update CHANGELOG.md with breaking change notice
- [ ] Bump version number
- [ ] Update marketplace.json (if applicable)
- [ ] Update plugin.json (if applicable)

## Important Notes

### DO NOT Change

1. **Issue tracker names**: References to "beads" or "pebbles" as **tracker names** should remain
   - Example: `issue_tracker.override = "beads"` - this is correct
   - Example: `BACKEND_REGISTRY["beads"]` - this is correct
   - These refer to the tracker itself, not the issue ID parameter

2. **CHANGELOG.md historical entries**: Keep historical references to "bead" parameter as-is

3. **Comments about Beads**: Comments that say "Beads issue ID" can stay or be updated to "issue tracker ID" or just "issue ID"

### Terminology

After the rename:
- **"issue ID"** or **"issue identifier"** - the value (e.g., "cic-123")
- **"beads"** or **"pebbles"** - the tracker name (proper noun)
- **`issue_id`** - the parameter/variable name

## Risk Assessment

**Low Risk:**
- Project is in active development (0.x version)
- Primary users are coordinator agents that can be updated
- No external API consumers (yet)
- Change is straightforward find-replace with test coverage

**Mitigation:**
- Comprehensive test coverage
- Clear migration notes in CHANGELOG
- Update all documentation simultaneously
- Version bump to signal breaking change

## Estimated Effort

- **Code changes**: 2-3 hours
- **Test updates**: 1-2 hours
- **Documentation updates**: 1-2 hours
- **Testing and verification**: 1 hour
- **Total**: 5-8 hours

## Next Steps

1. Get approval for Option 1 (immediate breaking change)
2. Create a branch for the rename: `refactor/rename-bead-to-issue-id`
3. Execute implementation plan systematically
4. Run full test suite after each phase
5. Review all changes before committing
6. Update version and CHANGELOG
7. Merge to main

## Questions for Review

1. **Naming preference**: `issue_id` vs `issue`? (Recommend `issue_id` for consistency)
2. **Backward compatibility**: Confirm Option 1 (breaking change) is acceptable?
3. **Version bump**: What version scheme? (0.9.x → 0.10.0? or 0.9.x → 1.0.0?)
4. **Documentation**: Any other docs to update?
