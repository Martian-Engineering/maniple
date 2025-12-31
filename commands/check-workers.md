# Check Workers

Check status of all active workers and report in a consistent format.

## Process

1. Call `list_workers` to get all managed sessions
2. For workers needing investigation, call `read_worker_logs` to understand their state
3. Determine status based on `is_idle`, `status`, and log content

## Output Format

Report status in this exact format:

```
## Worker Status Report

| Worker | Status | Bead/Task | Duration | Notes |
|--------|--------|-----------|----------|-------|
| Groucho | ACTIVE | cic-xyz | 12m | Working on feature |
| Harpo | READY | - | 5m | Idle, no assignment |
| Chico | COMPLETED | cic-abc | 8m | Logs indicate task done |
| Zeppo | STUCK | cic-def | 20m | Reported blocker |

### Summary
- Active: X workers (currently working)
- Completed: Y workers (believe they're done)
- Ready: Z workers (idle, awaiting task)
- Stuck: W workers (blocked or unclear)

### Attention Needed
- Zeppo: Reported blocker - needs coordinator input
```

## Status Determination

- **ACTIVE**: `is_idle: false` — worker is currently processing
- **READY**: `is_idle: true` with no prior assignment or work completed — waiting for instructions
- **COMPLETED**: `is_idle: true` and worker logs indicate the worker believes it has completed its task
- **STUCK**: `is_idle: true` but logs show the worker is blocked or status is otherwise unclear

To distinguish COMPLETED from STUCK, use `read_worker_logs` to check the worker's final messages for completion language vs. blocker language.

## Notes

- If no workers exist, report "No active workers" and suggest checking `discover_workers` if the user believes there should be some workers
- The Bead/Task column comes from `coordinator_annotation` in `list_workers` output
- Flag workers that may need attention (stuck, expressing blockers)
