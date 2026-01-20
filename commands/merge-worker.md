# Merge Worker

Directly merge a worker's branch back to its parent branch: $ARGUMENTS

Use this for small/internal changes that don't need PR review.
For changes that need review, use `/pr-worker` instead.

## Process

1. Identify the worker session or branch from $ARGUMENTS
   - Can be worker name (e.g., "Groucho") or branch name (e.g., "cic-abc-feature")

2. Detect the parent branch (branch the worktree diverged from):
   ```bash
   # Find the merge base with common branches
   git merge-base --fork-point main <branch> || \
   git merge-base --fork-point $(git branch --show-current) <branch>
   ```
   Or check git reflog for the branch point. If unclear, ask user.

3. Verify the work is complete:
   - Check worker logs via `read_worker_logs` or verify the issue is closed
   - Review commits: `git log <parent>..<branch> --oneline`
   - If not clearly complete, ask user to confirm before merging

4. Ensure parent branch is up to date:
   ```bash
   git checkout <parent-branch>
   git pull
   ```

5. Merge the branch:
   ```bash
   git merge <branch> --no-ff -m "Merge <branch>: <summary>"
   ```

6. Handle merge conflicts if any:
   - Report conflicts to user
   - Do NOT auto-resolve without user confirmation

7. Push parent branch:
   ```bash
   git push
   ```

8. Clean up:
   - If worker session still open: `close_workers([session_id])` — this automatically removes the worktree
   - If only worktree remains (worker already closed):
     - Remove worktree: `git worktree remove .worktrees/<name>`
     - Delete branch: `git branch -d <branch>`

## Output Format

```
## Merge Complete

**Branch:** cic-abc/feature-name
**Merged to:** <parent-branch>
**Commits:** 3

### Changes Merged
- <sha> Add new endpoint
- <sha> Update tests
- <sha> Fix lint errors

### Cleanup
- Worktree removed: .worktrees/cic-abc-feature-name
- Branch deleted: cic-abc-feature-name
- Worker closed: Groucho

**<parent-branch> pushed to origin.**
```

## Notes

- This is for quick internal merges where the coordinator is the reviewer
- Always verify work is complete before merging

## If Large Merge

**Stop and notify the user** if the merge is substantial (many files changed, significant code additions, or architectural changes). Let them know they may want to use `/pr-worker` instead to get a proper review.

Allow the user flexibility to proceed with direct merge if they prefer — this is a suggestion, not a hard block.
