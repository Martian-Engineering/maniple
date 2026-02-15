# claude-team Documentation

## Task Delivery Documentation

**New to claude-team?** Start here:

- **[Task Delivery Quick Reference](./task-delivery-quick-reference.md)** - Fast lookup for common patterns
- **[Coordinator Badge Explained](./coordinator-annotation.md)** - Full explanation of badge vs task delivery

### Common Confusion: badge vs task delivery

A common mistake is using `badge` to pass tasks to workers. **This doesn't work** because badge text is just coordinator metadata (for badges, branches, and tracking).

**Quick fix:**
- ❌ Don't use: `"badge": "Do this task"`
- ✅ Do use: `"issue_id": "issue-id"` or `"prompt": "Do this task"`
- ℹ️ Backward compatibility: `"annotation"` is still accepted as an alias for `"badge"`.
- ℹ️ Older docs may still show `"bead"`; use `"issue_id"` in new worker configs.

See the [Quick Reference](./task-delivery-quick-reference.md) for examples.

## Other Documentation

*(Add additional documentation sections here as the project grows)*
