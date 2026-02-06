# claude-team Documentation

## Task Delivery Documentation

**New to claude-team?** Start here:

- **[Task Delivery Quick Reference](./task-delivery-quick-reference.md)** - Fast lookup for common patterns
- **[Coordinator Annotation Explained](./coordinator-annotation.md)** - Full explanation of annotation vs task delivery

### Common Confusion: annotation vs task delivery

A common mistake is using `annotation` to pass tasks to workers. **This doesn't work** because annotation is just coordinator metadata (for badges, branches, and tracking).

**Quick fix:**
- ❌ Don't use: `"annotation": "Do this task"`
- ✅ Do use: `"bead": "issue-id"` or `"prompt": "Do this task"`

See the [Quick Reference](./task-delivery-quick-reference.md) for examples.

## Other Documentation

*(Add additional documentation sections here as the project grows)*
