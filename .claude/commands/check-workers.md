# Check Workers

Check status of all active workers and report in a consistent format.

## Process

1. Call `list_sessions` to get all managed sessions
2. For each session, call `get_session_status` to get details
3. Check for completion signals (TASK_COMPLETE in screen preview)
4. Check for recent git commits in the worker's project path

## Output Format

Report status in this exact format:

```
## Worker Status Report

| Session | Status | Task | Duration | Last Activity |
|---------|--------|------|----------|---------------|
| worker-1 | BUSY | cic-xyz | 12m | Working on feature |
| worker-2 | READY | - | 5m | Idle |
| worker-3 | COMPLETED | cic-abc | 8m | TASK_COMPLETE |

### Summary
- Active: X workers
- Completed: Y workers
- Idle: Z workers

### Attention Needed
- worker-4: No activity for 15+ minutes (may be stuck)
```

## Status Determination

- **BUSY**: `is_processing: true` or recent activity
- **READY**: `is_processing: false`, no task assigned
- **COMPLETED**: TASK_COMPLETE marker in screen or response
- **STUCK**: No activity for 10+ minutes while supposedly working

## Notes

- If no workers exist, report "No active workers"
- Flag workers that may need attention (stuck, errors in screen)
- Include task/issue ID if available from session metadata
