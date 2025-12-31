# Spawn Workers

We're going to tackle tasks described as follows: $ARGUMENTS

## Workflow

### 1. Task Analysis
First, analyze the tasks to understand:
- What beads issues are involved (use `bd show <id>` for details)
- Dependencies between tasks (use `bd dep tree <id>`)
- Which tasks can run in parallel vs must be sequential

**Pay attention to parallelism** — if tasks are blocked by others, hold off on starting blocked ones. Only start as many tasks as make sense given coordination and potential file conflicts.

### 2. Spawn Workers

Use `spawn_workers` to create worker sessions. The tool handles worktree creation automatically when `project_path: "auto"` — or you can create custom worktrees manually if you prefer specific branch naming.

**Derive this from context:** If the user has previously expressed a preference for manual worktree setup (e.g., specific branch naming conventions), use explicit paths. Otherwise, default to automatic worktree creation via the tool.

**Automatic worktrees (recommended default):**
```python
spawn_workers(workers=[
    {"project_path": "auto", "bead": "cic-123", "annotation": "Fix auth bug", "skip_permissions": True},
    {"project_path": "auto", "bead": "cic-456", "annotation": "Add unit tests", "skip_permissions": True},
])
# Creates .worktrees/cic-123-fix-auth-bug/ and .worktrees/cic-456-add-unit-tests/
# Branches named to match, badges show bead + annotation
```

**Custom worktrees (if user prefers specific branch names):**
```bash
# First create the worktrees manually:
git worktree add .worktrees/cic-123 -b cic-123/fix-auth-bug
git worktree add .worktrees/cic-456 -b cic-456/add-unit-tests
```
```python
# Then spawn workers pointing at them:
spawn_workers(workers=[
    {"project_path": ".worktrees/cic-123", "bead": "cic-123", "annotation": "Fix auth bug", "skip_permissions": True},
    {"project_path": ".worktrees/cic-456", "bead": "cic-456", "annotation": "Add unit tests", "skip_permissions": True},
])
```

**Key fields:**
- `project_path`: `"auto"` for automatic worktree, or explicit path
- `bead`: The beads issue ID (shown on badge, used in branch naming)
- `annotation`: Short task description (use the bead title for clarity)
- `skip_permissions`: Set `True` — without this, workers can only read files

**What workers are instructed to do:** When given a bead, workers receive a beads workflow:
1. Mark in progress: `bd --no-db update <bead> --status in_progress`
2. Implement the changes
3. Close issue: `bd --no-db close <bead>`
4. Commit with issue reference: `git commit -m "<bead>: <summary>"`

### 3. Monitor Progress

**Waiting strategies:**

- `wait_idle_workers(session_ids, mode="all")` — Block until all workers finish. Good for batch completion.
- `wait_idle_workers(session_ids, mode="any")` — Return when the first worker finishes. Good for pipelines where you process results incrementally.

**Quick checks (non-blocking):**

- `check_idle_workers(session_ids)` — Poll current idle state without blocking. Returns which workers are done.
- `examine_worker(session_id)` — Detailed status of a single worker.

**Reading completed work:**

- `read_worker_logs(session_id)` — Get the worker's conversation history. See what they did, any errors, their final summary.

**If a worker gets stuck:**
- Review their logs with `read_worker_logs` to understand the issue
- Unblock them with specific directions via `message_workers(session_ids, message="...")`
- If unclear how to help, ask me what to do before proceeding

### 4. Completion & Cleanup

After each worker completes:
1. Review their work with `read_worker_logs(session_id)`
2. Verify they committed (check git log in their worktree)
3. If the work looks good but they forgot to close the bead: `bd close <id>`
   If the work needs fixes, message them with corrections via `message_workers`

**When all tasks are complete:**
1. Terminate worker sessions: `close_workers(session_ids)`
2. Provide a summary:
   - Which issues were completed
   - Any issues encountered
   - Final git log showing commits

**Worktree cleanup:** Worktrees remain in `.worktrees/` for cherry-picking or merging. Use `list_worktrees(repo_path)` to see them. Clean up manually when no longer needed:
```bash
git worktree remove .worktrees/<name>
```
