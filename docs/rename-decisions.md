# Rename Decisions: claude-team → maniple

Date: 2026-02-05
Decided by: Josh Lehman

## Naming

| Current | New |
|---------|-----|
| `claude_team_mcp` (Python package) | `maniple_mcp` |
| `claude_team` (Python package) | `maniple` |
| `claude-team-mcp` (PyPI) | `maniple` |
| `claude-team` (CLI command) | `maniple` |
| `claude-team` (MCP server key) | `maniple` |
| `mcp__claude-team__*` (tool namespace) | `mcp__maniple__*` |
| `com.claude-team` (launchd) | `com.maniple` |
| `~/.claude-team/` (config dir) | `~/.maniple/` |
| `CLAUDE_TEAM_*` (env vars) | `MANIPLE_*` |
| `claude-team` (tmux session) | `maniple` |
| `<!claude-team-*!>` (JSONL markers) | `<!maniple-*!>` |

## Migration & Compatibility

### Config directory
- **Auto-migrate** `~/.claude-team/` → `~/.maniple/` on first run
- Move the entire directory, not individual files

### Environment variables
- Check `MANIPLE_*` first
- Fall back to `CLAUDE_TEAM_*` with deprecation warning to stderr
- Document the mapping in README

### JSONL markers
- Parse **both** old (`<!claude-team-*!>`) and new (`<!maniple-*!>`) marker formats
- Write only new format going forward
- Ensures old session files remain recoverable

### MCP server key
- Provide migration guidance in release notes
- Include auto-update script for `.mcp.json` / `config.toml`
- Users will see `mcp__maniple__*` tool names after updating

## GitHub
- Repo rename: **after** PyPI rename is published
- New name: `martian-engineering/maniple`
- GitHub auto-redirects old URLs
