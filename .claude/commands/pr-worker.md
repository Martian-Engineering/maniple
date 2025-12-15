# PR Worker

Create a pull request from a worker's branch: $ARGUMENTS

## Process

1. Identify the worker session or branch from $ARGUMENTS
   - Can be session ID (e.g., "worker-1") or branch name (e.g., "cic-abc/feature")

2. If session ID provided:
   - Get session info via `get_session_status`
   - Find the worktree/branch from project path

3. Gather PR information:
   - Get commits on branch: `git log main..<branch> --oneline`
   - Get changed files: `git diff main..<branch> --stat`
   - Extract issue ID from branch name if present

4. Push branch if not already pushed:
   ```bash
   git push -u origin <branch>
   ```

5. Create PR using gh CLI:
   ```bash
   gh pr create --title "<issue-id>: <summary>" --body "$(cat <<'EOF'
   ## Summary
   <bullet points from commits>

   ## Changes
   <list of changed files>

   ## Testing
   - [ ] Tests pass
   - [ ] Manual verification

   ---
   Related: <issue-id>
   EOF
   )"
   ```

6. Report the PR URL

## Output Format

```
## Pull Request Created

**Branch:** cic-abc/feature-name
**PR:** https://github.com/org/repo/pull/42
**Title:** cic-abc: Implement feature X

### Commits
- <sha> Add new endpoint
- <sha> Update tests

### Files Changed
- src/api/endpoint.py
- tests/test_endpoint.py

**Next steps:**
- Review PR at <url>
- After merge, run `/cleanup-worktrees` to remove worktree
```

## Notes

- Requires `gh` CLI to be authenticated
- Branch must have commits ahead of main
- Does not close the worker session (do that separately if desired)
