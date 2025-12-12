# Spawn Workers

We're going to tackle tasks described as follows: $ARGUMENTS

## Workflow

### 1. Task Analysis
First, analyze the tasks to understand:
- What beads issues are involved (use `bd show <id>` for details)
- Dependencies between tasks (use `bd dep tree <id>`)
- Which tasks can run in parallel vs must be sequential

**Pay attention to parallelism** — if tasks are blocked by others, hold off on starting blocked ones. Only start as many tasks as make sense given coordination and potential file conflicts.

### 2. Worktree Setup
For each task that's ready to start:
1. Create a dedicated git worktree: `git worktree add .worktrees/<issue-id> -b <issue-id>/<short-description>`
2. Track the worktree path for later cleanup (the `.worktrees/` directory is gitignored)

### 3. Spawn Workers
Use the claude-team MCP tools to spawn workers:
- Use `spawn_session` or `spawn_team` depending on count
- Set `skip_permissions: true` for autonomous work
- Send each worker a task prompt that includes the **full workflow**:

**Task prompt template:**
```
Work on <issue-id>: <description>

Workflow (follow exactly):
1. Mark in progress: bd --no-db update <issue-id> --status in_progress
2. Implement the changes
3. Close issue: bd --no-db close <issue-id>
4. Commit with issue reference: git add -A && git commit -m "<issue-id>: <summary>"

Use bd --no-db for all beads commands (required in worktrees).
```

### 4. Monitor Progress
Periodically check on workers using `get_session_status`:
- Watch for stuck workers (long processing times, errors in screen)
- Check if they've made commits
- Look for completion signals in their output

**If a worker gets stuck:**
- Try to unblock them with specific directions via `send_message`
- If unclear how to help, ask me what to do before proceeding

### 5. Completion & Cleanup
After each worker completes:
1. Verify they committed their work (check git log in worktree)
2. Close the session using `close_session`
3. Merge the worktree branch: `git merge <branch-name>`
4. Remove the worktree: `git worktree remove .worktrees/<issue-id>`
5. Delete the branch: `git branch -d <branch-name>`
6. Close the beads issue if not already closed: `bd --no-db close <id>`

Handle any merge conflicts by resolving them or asking for guidance.

### 6. Summary
When all tasks are complete, provide a summary:
- Which issues were completed
- Any issues encountered
- Final git log showing merged commits
