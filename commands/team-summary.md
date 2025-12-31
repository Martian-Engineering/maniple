# Team Summary

Generate an end-of-session summary of all worker activity.

## Process

1. Get all workers via `list_workers` (includes active and closed)
2. For each worker's worktree path, check git log for commits
3. Check beads issues that were closed: `bd list --status closed`
4. Get worktree status via `list_worktrees(repo_path)`
5. Compile summary of work completed

## Output Format

```
## Team Session Summary

### Completed Work

| Bead | Worker | Branch | Status |
|------|--------|--------|--------|
| cic-abc | Groucho | cic-abc-feature-name | Merged |
| cic-xyz | Harpo | cic-xyz-bug-fix | PR Open |
| cic-123 | Chico | cic-123-refactor | Ready to merge |

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
| .worktrees/cic-abc-feature-name | cic-abc-feature-name | Can remove (merged) |
| .worktrees/cic-xyz-bug-fix | cic-xyz-bug-fix | Keep (PR open) |

### Statistics
- Workers spawned: X
- Beads completed: Y
- PRs opened: Z
- Branches merged: W
```

## Notes

- Run this at end of session before cleanup
- Helps identify what still needs review/merge
- Suggest `/cleanup-worktrees` for merged branches
- Suggest `/pr-worker` or `/merge-worker` for unmerged work
