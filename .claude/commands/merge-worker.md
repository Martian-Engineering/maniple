# Merge Worker

Directly merge a worker's branch to main: $ARGUMENTS

Use this for small/internal changes that don't need PR review.
For changes that need review, use `/pr-worker` instead.

## Process

1. Identify the worker session or branch from $ARGUMENTS
   - Can be session ID (e.g., "worker-1") or branch name (e.g., "cic-abc/feature")

2. Verify the work is complete:
   - Check for TASK_COMPLETE marker or closed beads issue
   - Review commits: `git log main..<branch> --oneline`
   - If not clearly complete, ask user to confirm before merging

3. Ensure main is up to date:
   ```bash
   git checkout main
   git pull
   ```

4. Merge the branch:
   ```bash
   git merge <branch> --no-ff -m "Merge <branch>: <summary>"
   ```

5. Handle merge conflicts if any:
   - Report conflicts to user
   - Do NOT auto-resolve without user confirmation

6. Push main:
   ```bash
   git push
   ```

7. Clean up:
   - Remove worktree: `git worktree remove .worktrees/<id>`
   - Delete branch: `git branch -d <branch>`
   - Close session if still open: `close_session`

## Output Format

```
## Merge Complete

**Branch:** cic-abc/feature-name
**Merged to:** main
**Commits:** 3

### Changes Merged
- <sha> Add new endpoint
- <sha> Update tests
- <sha> Fix lint errors

### Cleanup
- Worktree removed: .worktrees/cic-abc
- Branch deleted: cic-abc/feature-name
- Session closed: worker-1

**Main branch pushed to origin.**
```

## Notes

- Prefer `/pr-worker` for changes that need review
- This is for quick internal merges where you are the reviewer
- Always verifies work is complete before merging
