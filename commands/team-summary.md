# Team Summary

Generate an end-of-session summary of all worker activity.

## Process

1. Get all workers via `list_workers` (includes active and closed)
2. For each worker's worktree path, check git log for commits
3. Check issues that were closed: `pb list --status closed` or `bd --no-db list --status closed`
4. Get worktree status via `list_worktrees(repo_path)`
5. Compile summary of work completed

## Output Format

```
## Team Session Summary

### Completed Work

| Issue | Worker | Type | Branch | Status |
|------|--------|------|--------|--------|
| cic-abc | Groucho | claude | groucho-a1b2-feature | Merged |
| cic-xyz | Harpo | codex | harpo-c3d4-bugfix | PR Open |
| cic-123 | Chico | claude | chico-e5f6-refactor | Ready to merge |

### Git Activity

**Commits this session:**
```
<sha> cic-abc: Implement feature X
<sha> cic-xyz: Fix authentication bug
```

**Branches:**
- `cic-abc-feature-name` - merged to main
- `cic-xyz-bug-fix` - PR #42 open
- `cic-123-refactor` - awaiting review

### Worktrees

| Path | Branch | Status |
|------|--------|--------|
| .worktrees/groucho-a1b2-feature | groucho-a1b2-feature | Can remove (merged) |
| .worktrees/harpo-c3d4-bugfix | harpo-c3d4-bugfix | Keep (PR open) |

**Note:** Worktrees are automatically removed when workers are closed. Remaining worktrees are from workers that weren't closed or had PRs open.

### Statistics
- Workers spawned: X
- Issues completed: Y
- PRs opened: Z
- Branches merged: W
```

## Notes

- Run this at end of session before cleanup
- Helps identify what still needs review/merge
- Suggest `/cleanup-worktrees` for merged branches
- Suggest `/pr-worker` or `/merge-worker` for unmerged work
