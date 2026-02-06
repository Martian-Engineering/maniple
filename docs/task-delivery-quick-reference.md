# Task Delivery Quick Reference

## TL;DR

**❌ WRONG:**
```python
# This does NOT send the task to the worker!
spawn_workers(workers=[{
    "project_path": "auto",
    "annotation": "Fix the authentication bug in login.py"
}])
```

**✅ CORRECT:**
```python
# Use bead, prompt, or message_workers to send tasks
spawn_workers(workers=[{
    "project_path": "auto",
    "bead": "cic-123",  # Worker gets: "Your assignment is cic-123"
    "annotation": "Auth bug"  # Optional: for your tracking only
}])
```

## Quick Comparison

| What You Want | Use This | Example |
|---------------|----------|---------|
| Assign tracked issue | `bead` parameter | `"bead": "cic-123"` |
| Give custom instructions | `prompt` parameter | `"prompt": "Review auth.py for XSS"` |
| Send task after spawn | `message_workers()` | `message_workers(session_ids=["Groucho"], ...)` |
| Track what worker is doing | `annotation` parameter | `"annotation": "Auth work"` (for badges only) |

## Common Patterns

### Pattern 1: Issue-Tracked Work
```python
spawn_workers(workers=[{
    "project_path": "auto",
    "bead": "cic-123",           # ✅ Worker receives this
    "annotation": "Fix auth"     # ℹ️ Just for badges/branches
}])
```
Worker sees: "Your assignment is `cic-123`. Use `pb show cic-123` for details."

### Pattern 2: Custom Task
```python
spawn_workers(workers=[{
    "project_path": "auto",
    "prompt": "Audit the auth module for SQL injection vulnerabilities"  # ✅ Worker receives this
}])
```
Worker sees: "The coordinator assigned you the following task: Audit the auth module..."

### Pattern 3: Issue + Extra Context
```python
spawn_workers(workers=[{
    "project_path": "auto",
    "bead": "cic-123",           # ✅ Worker receives this
    "prompt": "Focus on OAuth2 flow",  # ✅ Worker receives this too
    "annotation": "Auth - OAuth"      # ℹ️ Just for badges
}])
```
Worker sees both the issue assignment and your custom instructions.

### Pattern 4: Spawn Then Message
```python
# Step 1: Spawn idle
result = spawn_workers(workers=[{"project_path": "auto"}])

# Step 2: Send task immediately
message_workers(
    session_ids=result["sessions"].keys(),
    message="Review PR #456 and suggest improvements"  # ✅ Worker receives this
)
```

## What IS `annotation` For?

The `annotation` field is **coordinator metadata** for:

1. **Visual identification** - Shows in iTerm badge (2nd line)
2. **Branch naming** - Used in worktree branches
3. **List output** - Appears when you call `list_workers()`
4. **Your tracking** - Helps you remember what each worker is doing

It's basically a sticky note for **you**, not instructions for **them**.

## How to Update Annotation Later

```python
# Update tracking note without sending worker a message
annotate_worker(
    session_id="Groucho",
    annotation="Now working on tests"  # ℹ️ Just updates metadata
)
```

This updates your tracking info but does **not** notify the worker.

## Best Practices

### Don't Specify `agent_type` Unless Needed

The `agent_type` parameter defaults to `"claude"` and should **not** be specified unless the user explicitly requests it.

```python
# ❌ AVOID: Unnecessary agent_type specification
spawn_workers(workers=[{
    "project_path": "auto",
    "agent_type": "claude",  # Don't specify if using default!
    "bead": "cic-123"
}])

# ✅ CORRECT: Let it use the default
spawn_workers(workers=[{
    "project_path": "auto",
    "bead": "cic-123"
}])

# ✅ CORRECT: Only specify when explicitly requested
# User: "Spawn a Codex worker to review this code"
spawn_workers(workers=[{
    "project_path": "auto",
    "agent_type": "codex",  # OK - user explicitly requested Codex
    "prompt": "Review auth.py for vulnerabilities"
}])
```

**Why?** The default behavior is intentional and covers most use cases. Only override when the user has a specific reason to use a different agent type.

## See Also

- [Full documentation](./coordinator-annotation.md) - Complete explanation with code references
- `spawn_workers` tool docstring - API reference with all parameters
