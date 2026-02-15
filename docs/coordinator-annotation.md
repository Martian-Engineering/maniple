# Coordinator Badge vs Task Delivery

## Overview

This document clarifies the distinction between `coordinator_badge` (metadata) and actual task delivery mechanisms in claude-team.

## The Problem

Coordinators were mistakenly using `badge` in spawn configurations to pass task information to workers. However, **badges are never sent to workers** - they're purely metadata for the coordinator's tracking.

## What `coordinator_badge` Actually Does

The `badge` field in `WorkerConfig` (which becomes `coordinator_badge` on the `ManagedSession` object) is used for:

1. **iTerm badge display** - Shows on the worker's terminal badge (2nd line)
2. **Git branch naming** - Used in worktree branch names (e.g., `Groucho-abc123-fix-auth-bug`)
3. **Coordinator tracking** - Appears in `list_workers` output for coordinator reference
4. **Session metadata** - Stored on the session object, never sent as a message

### Example Usage

```python
# badge is for coordinator tracking only
spawn_workers(
    workers=[{
        "project_path": "auto",
        "issue_id": "cic-123",
        "badge": "Fix authentication bug"  # <-- Badge/branch name only!
    }]
)
```

The worker will **NOT** receive "Fix authentication bug" as their task. They only see what's in the `issue_id` or `prompt` parameters.

## How to Actually Deliver Tasks to Workers

There are **four correct ways** to deliver tasks to workers:

### Method 1: Using `issue_id` Parameter (Recommended for tracked work)

When you provide an `issue_id` (issue tracker ID), the worker receives a prompt telling them their assignment:

```python
spawn_workers(
    workers=[{
        "project_path": "auto",
        "issue_id": "cic-123",              # <-- Worker receives this as their assignment
        "badge": "Fix auth bug"    # <-- Optional: for badges/tracking only
    }]
)
```

**What the worker receives:**
```
=== YOUR ASSIGNMENT ===

Your assignment is `cic-123`. Use `pb show cic-123` for details. Get to work!
```

The worker is instructed to:
1. Run `pb show cic-123` (or equivalent tracker command) to see task details
2. Mark it in progress
3. Implement the changes
4. Close the issue
5. Commit with issue reference

### Method 2: Using `prompt` Parameter (For custom instructions)

When you provide a `prompt`, the worker receives your custom instructions directly:

```python
spawn_workers(
    workers=[{
        "project_path": "/path/to/repo",
        "prompt": "Review the auth module for security vulnerabilities. Focus on input validation and session management."
    }]
)
```

**What the worker receives:**
```
=== YOUR ASSIGNMENT ===

The coordinator assigned you the following task:

Review the auth module for security vulnerabilities. Focus on input validation
and session management.

Get to work!
```

### Method 3: Using `message_workers()` After Spawn

When you spawn without `issue_id` or `prompt`, the worker spawns idle and you must immediately send them a task:

```python
# Spawn idle worker
result = spawn_workers(
    workers=[{"project_path": "/path/to/repo"}]
)

# IMPORTANT: Immediately send them their task
message_workers(
    session_ids=["Groucho"],  # or use the session ID from result
    message="Review the auth module for security issues and document your findings."
)
```

**What the worker receives first:**
```
Alright, you're all set. The coordinator will send your first task shortly.
```

Then your message arrives as their actual task.

⚠️ **Warning:** If you spawn without `issue_id`/`prompt`, you'll get a warning in the response:
```json
{
    "workers_awaiting_task": ["Groucho"],
    "coordinator_guidance": "... AWAITING TASK - send them instructions now"
}
```

### Method 4: Combining `issue_id` + `prompt` (For additional context)

You can combine both to give issue-tracked work with extra context:

```python
spawn_workers(
    workers=[{
        "project_path": "auto",
        "issue_id": "cic-123",
        "prompt": "Focus on the login endpoint. Check both password and OAuth flows.",
        "badge": "Auth bug - login"  # Optional: for tracking
    }]
)
```

**What the worker receives:**
```
=== YOUR ASSIGNMENT ===

The coordinator assigned you `cic-123` (Use `pb show cic-123` for details.) and included
the following instructions:

Focus on the login endpoint. Check both password and OAuth flows.

Get to work!
```

## Code References

### spawn_workers.py

**Where badge text is stored:**
```python
# Set badge from worker config (if provided)
managed.coordinator_badge = workers[i].get("badge") or workers[i].get("annotation")
```

**Where tasks are actually sent (lines 735-775):**
```python
worker_prompt = generate_worker_prompt(
    managed.session_id,
    resolved_names[i],
    agent_type=managed.agent_type,
    use_worktree=use_worktree,
    issue_id=issue_id,                      # <-- Task parameter 1
    project_path=tracker_path,
    custom_prompt=custom_prompt,    # <-- Task parameter 2
)

await backend.send_prompt_for_agent(
    pane_sessions[i],
    worker_prompt,                  # <-- This is what worker receives
    agent_type=managed.agent_type,
)
```

### worker_prompt.py

**Prompt generation logic (lines 83-241):**

The `generate_worker_prompt()` function creates the actual message the worker receives based on:
- `issue_id`: Issue tracker ID (if provided)
- `custom_prompt`: Custom instructions (if provided)

The closing section has 4 cases:
1. `issue_id` only → "Your assignment is `<issue_id>`"
2. `issue_id` + `custom_prompt` → Assignment + custom instructions
3. `custom_prompt` only → Custom instructions
4. Neither → "The coordinator will send your first task shortly"

**Note:** `badge` is NOT a parameter to `generate_worker_prompt()` and is never included in the worker prompt.

### annotate_worker.py

**What annotate_worker actually does (lines 22-57):**
```python
@mcp.tool()
async def annotate_worker(
    ctx: Context[ServerSession, "AppContext"],
    session_id: str,
    badge: str,
) -> dict:
    """
    Add a coordinator badge to a worker.

    Coordinators use this to track what task each worker is assigned to.
    These badges appear in list_workers output.
    """
    session.coordinator_badge = badge  # <-- Just metadata!
    # ... returns confirmation
```

This tool is for **updating** coordinator tracking metadata after spawn. It does **not** send any message to the worker.

## Summary

| Field/Parameter | Purpose | Sent to Worker? |
|----------------|---------|-----------------|
| `badge` | Badge text, branch names, coordinator tracking | ❌ No |
| `issue_id` | Issue tracker ID - worker's assignment | ✅ Yes |
| `prompt` | Custom instructions - worker's task | ✅ Yes |
| `message_workers()` | Send message after spawn | ✅ Yes |

**Key Takeaway:** If you want a worker to know about something, use `issue_id`, `prompt`, or `message_workers()`. The `badge` field is only for your own tracking and visual identification.
Backward compatibility: `annotation` is still accepted as an alias for `badge`.

## Best Practices

### 1. Don't Specify `agent_type` Unless Explicitly Requested

The `agent_type` parameter defaults to `"claude"` and should **not** be specified unless the user explicitly requests a different agent type.

**Why?** The default behavior is intentional and covers most use cases. Unnecessarily specifying `agent_type` adds noise to the configuration and may override intended defaults.

**Examples:**

```python
# ❌ AVOID: Unnecessary agent_type specification
spawn_workers(workers=[{
    "project_path": "auto",
    "agent_type": "claude",  # Redundant - this is already the default!
    "issue_id": "cic-123"
}])

# ✅ CORRECT: Use the default
spawn_workers(workers=[{
    "project_path": "auto",
    "issue_id": "cic-123"
}])

# ✅ CORRECT: Only specify when user explicitly requests it
# Example: User says "Spawn a Codex worker for this task"
spawn_workers(workers=[{
    "project_path": "auto",
    "agent_type": "codex",  # OK - user explicitly requested Codex
    "prompt": "Review the authentication module for vulnerabilities"
}])
```

### 2. Use `badge` for Tracking, Not Task Delivery

Always remember: `badge` is for **your** reference, not **their** instructions.

```python
# ✅ GOOD: badge helps you track, issue_id delivers task
spawn_workers(workers=[{
    "project_path": "auto",
    "issue_id": "cic-123",
    "badge": "Auth bug - login flow"  # Your note for tracking
}])

# ❌ BAD: badge alone won't deliver the task
spawn_workers(workers=[{
    "project_path": "auto",
    "badge": "Fix the authentication bug"  # Worker never receives this!
}])
```
