# Spawn Workers

We're going to tackle tasks described as follows: $ARGUMENTS

## Workflow

### 1. Task Analysis
First, analyze the tasks to understand:
- What issue tracker issues are involved (use `pb show <id>` or `bd --no-db show <id>` for details)
- Dependencies between tasks (use `pb dep tree <id>` or `bd --no-db dep tree <id>`)
- Which tasks can run in parallel vs must be sequential

**Pay attention to parallelism** — if tasks are blocked by others, hold off on starting blocked ones. Only start as many tasks as make sense given coordination and potential file conflicts.

### 2. Spawn Workers

Use `spawn_workers` to create worker sessions. The tool handles worktree creation automatically (default behavior).

**Standard spawn (recommended):**
```python
spawn_workers(workers=[
    {"project_path": "/path/to/repo", "bead": "cic-123", "annotation": "Fix auth bug", "skip_permissions": True},
    {"project_path": "/path/to/repo", "bead": "cic-456", "annotation": "Add unit tests", "skip_permissions": True},
])
# Creates .worktrees/<name>-<uuid>-<annotation>/ automatically
# Branches isolated per worker, badges show issue ID + annotation
```

**Spawn Codex workers (for OpenAI Codex CLI):**
```python
spawn_workers(workers=[
    {"project_path": "/path/to/repo", "agent_type": "codex", "bead": "cic-123", "annotation": "Fix auth bug", "skip_permissions": True},
])
# Codex workers end responses with "COMPLETED" or "BLOCKED: <reason>"
```

**Spawn without worktree (work directly in repo):**
```python
spawn_workers(workers=[
    {"project_path": "/path/to/repo", "bead": "cic-123", "use_worktree": False, "skip_permissions": True},
])
```

**Key fields:**
- `project_path`: Path to the repository (required)
- `agent_type`: `"claude"` (default) or `"codex"` for OpenAI Codex CLI
- `bead`: The issue ID (Beads or Pebbles; shown on badge, used in branch naming)
- `annotation`: Short task description (use the issue title for clarity)
- `skip_permissions`: Set `True` — without this, workers can only read files
- `use_worktree`: Set `False` to skip worktree creation (default `True`)

**What workers are instructed to do:** When given an issue ID, workers receive the
issue tracker workflow using the detected CLI (`pb` or `bd --no-db`):
1. Mark in progress: `pb update <issue-id> --status in_progress` or `bd --no-db update <issue-id> --status in_progress`
2. Implement the changes
3. Close issue: `pb close <issue-id>` or `bd --no-db close <issue-id>`
4. Commit with issue reference: `git add -A && git commit -m "<issue-id>: <summary>"`

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

**Note on Codex workers:** Codex idle detection uses JSONL polling instead of Stop hooks. Check their output for "COMPLETED" or "BLOCKED: <reason>" status markers.

### 4. Completion & Cleanup

After each worker completes:
1. Review their work with `read_worker_logs(session_id)`
2. Verify they committed (check git log in their worktree)
3. If the work looks good but they forgot to close the issue:
   `pb close <id>` or `bd --no-db close <id>`
   If the work needs fixes, message them with corrections via `message_workers`

**When all tasks are complete:**
1. Review commits in worktrees
2. Terminate worker sessions: `close_workers(session_ids)` — removes worktree directories but keeps branches
3. Merge or cherry-pick commits from worker branches to main
4. Delete worker branches when done: `git branch -d <branch-name>`
5. Provide a summary:
   - Which issues were completed
   - Any issues encountered
   - Final git log showing commits

**Note:** `close_workers` removes worktree directories but preserves branches. Commits remain accessible until you explicitly delete the branch.

To see existing worktrees: `list_worktrees(repo_path)`
