# Cleanup Worktrees

Clean up worktrees that are no longer needed (merged branches only).

## Process

1. List all worktrees:
   ```bash
   git worktree list
   ```

2. For each worktree in `.worktrees/`:
   - Extract branch name
   - Check if branch is merged to main: `git branch --merged main | grep <branch>`
   - Check if associated PR is merged (if applicable): `gh pr list --head <branch> --state merged`

3. Categorize worktrees:
   - **Safe to remove**: Branch merged to main
   - **Keep**: Branch has open PR or unmerged commits
   - **Orphaned**: No branch exists (worktree is stale)

4. Remove safe worktrees:
   ```bash
   git worktree remove .worktrees/<id>
   git branch -d <branch>  # Only if fully merged
   ```

5. Report results

## Output Format

```
## Worktree Cleanup Report

### Removed (merged)
| Worktree | Branch | Reason |
|----------|--------|--------|
| .worktrees/cic-abc | cic-abc/feature | Merged to main |
| .worktrees/cic-def | cic-def/bugfix | PR #42 merged |

### Kept (not merged)
| Worktree | Branch | Reason |
|----------|--------|--------|
| .worktrees/cic-xyz | cic-xyz/wip | Has unmerged commits |
| .worktrees/cic-123 | cic-123/feature | PR #45 open |

### Summary
- Removed: X worktrees
- Kept: Y worktrees
- Space freed: ~Z MB
```

## Safety Rules

- NEVER remove worktrees with unmerged commits
- NEVER delete branches that aren't fully merged
- If unsure, keep the worktree and report it
- Orphaned worktrees (no branch) can be removed with `git worktree remove --force`

## Notes

- Run `/team-summary` first to see what's pending
- Use `/merge-worker` or `/pr-worker` for unmerged branches
- This command is conservative - it only removes definitely-safe worktrees
