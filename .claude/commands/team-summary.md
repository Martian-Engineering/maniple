# Team Summary

Generate an end-of-session summary of all worker activity.

## Process

1. List all sessions (active and recently closed)
2. For each worker's project path, check git log for commits
3. Check beads issues that were closed: `bd list --status=closed`
4. Compile summary of work completed

## Output Format

```
## Team Session Summary

### Completed Work

| Issue | Worker | Branch | Status |
|-------|--------|--------|--------|
| cic-abc | worker-1 | cic-abc/feature-name | Merged |
| cic-xyz | worker-2 | cic-xyz/bug-fix | PR Open |
| cic-123 | worker-3 | cic-123/refactor | Ready to merge |

### Git Activity

**Commits this session:**
```
<sha> cic-abc: Implement feature X
<sha> cic-xyz: Fix authentication bug
```

**Branches:**
- `cic-abc/feature-name` - merged to main
- `cic-xyz/bug-fix` - PR #42 open
- `cic-123/refactor` - awaiting review

### Worktrees

| Path | Branch | Status |
|------|--------|--------|
| .worktrees/cic-abc | cic-abc/feature-name | Can remove (merged) |
| .worktrees/cic-xyz | cic-xyz/bug-fix | Keep (PR open) |

### Statistics
- Workers spawned: X
- Issues completed: Y
- PRs opened: Z
- Branches merged: W
```

## Notes

- Run this at end of session before cleanup
- Helps identify what still needs review/merge
- Use output to guide `/cleanup-worktrees` or `/pr-worker` commands
