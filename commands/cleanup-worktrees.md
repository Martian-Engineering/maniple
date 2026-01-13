# Cleanup Worktrees

Clean up worktrees that are no longer needed (merged branches only).

## Process

1. Call `list_worktrees(repo_path)` to get all worktrees in `.worktrees/`

2. For each worktree, check if the branch is merged:
   ```bash
   git branch --merged main | grep <branch>
   ```

3. Optionally check if associated PR is merged:
   ```bash
   gh pr list --head <branch> --state merged
   ```

4. Categorize worktrees:
   - **Safe to remove**: Branch merged to main
   - **Keep**: Branch has open PR or unmerged commits
   - **Orphaned**: `registered: false` in list_worktrees output (stale)

5. Remove safe worktrees:
   ```bash
   git worktree remove .worktrees/<name>
   git branch -d <branch>  # Only if fully merged
   ```

6. For orphaned worktrees, use `list_worktrees(repo_path, remove_orphans=True)` to clean them up

## Output Format

```
## Worktree Cleanup Report

### Removed (merged)
| Worktree | Branch | Reason |
|----------|--------|--------|
| cic-abc-feature | cic-abc-feature | Merged to main |
| cic-def-bugfix | cic-def-bugfix | PR #42 merged |

### Kept (not merged)
| Worktree | Branch | Reason |
|----------|--------|--------|
| cic-xyz-wip | cic-xyz-wip | Has unmerged commits |
| cic-123-feature | cic-123-feature | PR #45 open |

### Summary
- Removed: X worktrees
- Kept: Y worktrees
```

## Safety Rules

- NEVER remove worktrees with unmerged commits
- NEVER delete branches that aren't fully merged
- If unsure, keep the worktree and report it
- Orphaned worktrees (not registered with git) can be removed via `remove_orphans=True`

## Notes

- Worktrees are stored in `.worktrees/` within the repository
- Directory names follow format: `<worker-name>-<uuid>-<annotation>` (e.g., `.worktrees/groucho-a1b2c3d4-fix-auth-bug`)
- Branch names match directory names
- This command is conservative — it only removes definitely-safe worktrees
- **Note:** `close_workers` automatically removes worktrees. This command is for cleaning up worktrees that remain after workers were closed (e.g., from crashed sessions or manual branch creation)

## Before You Start

If the user hasn't already, suggest they run `/team-summary` first to get an overview of pending work before cleanup.

## If Unmerged Work Exists

**Stop and notify the user** if any worktrees have unmerged commits or open PRs. Let them know:
- They may use `/merge-worker` to merge completed work directly
- They may use `/pr-worker` to create a PR for review

Do not proceed with cleanup until the user confirms how to handle unmerged branches.
