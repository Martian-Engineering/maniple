# Smart Forking Proposal

## Goal
Let a user describe what they want to implement, semantically search past Claude Code
and Codex sessions, and fork from a selected session to inherit relevant context.

## Relevant Architecture (claude-team)
- MCP server lives in `src/claude_team_mcp/` with tools under `src/claude_team_mcp/tools/`.
- Session metadata and JSONL parsing live in `src/claude_team_mcp/registry.py` and `src/claude_team_mcp/session_state.py`.
- Claude CLI backend is `src/claude_team_mcp/cli_backends/claude.py`.
- Codex CLI backend is `src/claude_team_mcp/cli_backends/codex.py`.
- Session logs are stored in `~/.claude/projects/<project-slug>/<session-id>.jsonl`.
  - `session_state.get_project_dir(project_path)` computes the project slug.
- Codex session logs live under `~/.codex/sessions/` (codex CLI).
  - Codex JSONL includes a `session_meta` entry with `payload.id`, `payload.cwd`,
    and `payload.timestamp`.

## qmd Reality Check
I verified qmd behavior against the `claude-sessions` and `codex-sessions`
collections (Jan 23, 2026):
- `qmd collection list` shows `claude-sessions` exists (there is no `collection show` subcommand).
- `qmd search "smart forking" -c claude-sessions --json` works and returns Markdown session exports.
- `qmd vsearch "smart forking" -c claude-sessions --json` works and returns vector-ranked results.
- `qmd query "smart forking" -c claude-sessions --json` works, including reranking output.
- `qmd query "codex session" -c codex-sessions --json` works and returns Codex session exports.

The Markdown session exports include metadata like:
- Claude sessions: `Session ID`, `Working Directory`, `Date`
- Codex sessions: `Session` (session id string) and `Date` today; we should
  include `Working Directory` when we own the exporter.

Implication: prefer `qmd query` for semantic + rerank, with fallbacks to
`qmd vsearch` and `qmd search` if qmd errors or is unavailable.

## Proposed MCP Tool: `smart_fork`

### Tool Signature
```
smart_fork(
  intent: str,
  agent_type: "claude" | "codex" = "claude",
  limit: int = 5,
  project_path: str | None = None,
  collection: str | None = None,
  min_score: float | None = None,
  include_snippets: bool = True,
  auto_fork: bool = False,
  fork_index: int | None = None
) -> dict
```

### Behavior
1. **Embed + search**
   - Pick collection by agent type unless explicitly provided:
     - `claude` → `claude-sessions`
     - `codex` → `codex-sessions`
   - Cross-agent forking is not supported; `agent_type` determines collection and CLI.
   - Prefer: `qmd query <intent> -c <collection> --json -n <limit>`
   - If that errors, fall back to:
     - `qmd vsearch <intent> -c <collection> --json -n <limit>`
     - If that errors, final fallback: `qmd search <intent> -c <collection> --json -n <limit>`
   - If qmd is not installed or collection is missing, skip qmd and return a guidance payload (see below).

2. **Parse results**
   - Each result is a Markdown file that includes `Session ID`, `Working Directory`,
     `Date`, and `Agent`.
   - Extract:
     - `session_id`
     - `working_directory`
     - `date`
     - `agent_type` (`claude` or `codex`)
     - `snippet` (from qmd result)
     - `score`
     - `source_path` (qmd doc path)
   - Optionally map to JSONL path:
     - `~/.claude/projects/<slug>/<session-id>.jsonl` via `session_state.get_project_dir()`.
     - `~/.codex/sessions/**/<session-id>.jsonl` for codex sessions (path includes date folders).
   - Enforce current-repo access control:
     - If `project_path` is not provided, default to the HTTP server’s project root.
     - Any session whose `working_directory` is not within `project_path` is excluded.

3. **Return ranked list**
   - Return top results with scores and a short snippet.

4. **Optional fork**
   - If `auto_fork: true` or `fork_index` is provided, spawn a worker that resumes the chosen session with `--fork-session`.

### Example Response
```
{
  "query": "Add smart forking to claude-team",
  "results": [
    {
      "rank": 1,
      "score": 0.82,
      "session_id": "60309e1e-c4ea-4d6d-8da1-21732781ce4d",
      "agent_type": "claude",
      "working_directory": "/private/tmp",
      "date": "2026-01-07T00:11:47.756Z",
      "snippet": "...smart approach - models pay more attention...",
      "source_path": "qmd://claude-sessions/private-tmp/60309e1e-c4ea-4d6d-8da1-21732781ce4d.md",
      "jsonl_path": "/Users/phaedrus/.claude/projects/-private-tmp/60309e1e-c4ea-4d6d-8da1-21732781ce4d.jsonl"
    }
  ],
  "forked_session": {
    "session_name": "Groucho",
    "terminal_id": "iterm:...",
    "resume_session_id": "60309e1e-c4ea-4d6d-8da1-21732781ce4d"
  }
}
```

## Forking Mechanism
Claude CLI supports:
- `--resume <session-id>`
- `--fork-session` (creates a new session id)
- `--continue` (most recent session)

Proposed approach for Smart Fork:
- Always use `--resume <session-id> --fork-session` to avoid mutating the original session.
- Do not use `--continue` unless the user explicitly asks for “last session”.

Codex CLI supports:
- `codex resume <session-id>` (or `--last`)
- `codex fork <session-id>` (or `--last`)

Proposed approach for Codex Smart Fork:
- Use `codex fork <session-id>` to create a new session with inherited context.
- Use `codex resume <session-id>` only when the user explicitly requests resume.

## Integration with `spawn_workers`

### Option A: Extend WorkerConfig
Add optional fields:
```
resume_session_id: str | None
fork_session: bool = False
continue_session: bool = False
agent_type: "claude" | "codex"
```
Then in `spawn_workers`, pass these through to the CLI backend to build args:
- `--resume <id>` when `resume_session_id` is present
- `--fork-session` when `fork_session` is true
- `--continue` when `continue_session` is true and no resume id is given
- For codex: call `codex fork <id>` or `codex resume <id>` depending on the flags

### Option B: New Tool `smart_fork`
`smart_fork`:
- Runs qmd search
- Returns ranked sessions
- If `auto_fork: true`, calls `spawn_workers` under the hood with `resume_session_id` + `fork_session`

Option B keeps `spawn_workers` stable while encapsulating the qmd + parsing logic.
Option A provides a more general capability for any caller to resume/fork.

## Suggested Implementation Notes
- qmd output should be parsed using `--json` to avoid brittle text parsing.
- Extract `Session ID` from markdown body as a fallback if filename doesn’t match.
- Include an explicit `Agent: claude|codex` header in markdown exports to make agent detection reliable.
- Normalize headers for both agents: `Session ID`, `Working Directory`, `Date`, `Agent`.
- Include `Working Directory` for codex exports using `session_meta.payload.cwd`.
- Consider adding `Repo Root` in exports to make current-repo filtering unambiguous.
- If a session’s JSONL file doesn’t exist, include `can_fork=false` and a warning.
- Include a `qmd_error` field if query/vsearch fails so users understand fallback behavior.
- Add minimal CLI checks to ensure `claude` is on PATH and supports `--fork-session`.

## qmd Not Installed / Missing Collection Handling
If `qmd` is not available (`shutil.which("qmd")` is None) or the relevant
collection (`claude-sessions` or `codex-sessions`) isn’t configured, the tool should:
- Log the error and continue running (HTTP server stays up).
- Return a structured response with a short, actionable setup guide.
- Provide a manual fallback option: list the most recent N sessions for the
  current repo and agent type (from JSONL) so the user can still choose a session ID.

Suggested guidance payload:
```
{
  "error": "qmd_not_available",
  "message": "qmd is not installed or the required collection is missing.",
  "next_steps": [
    "Install qmd and ensure it is on PATH",
    "Start claude-team in HTTP mode with CLAUDE_TEAM_QMD_INDEXING=true",
    "Re-run smart_fork once indexing completes"
  ],
  "fallback_sessions": [
    {"session_id": "...", "project_path": "...", "last_modified": "...", "agent_type": "..."}
  ]
}
```

## Ongoing Indexing Setup (claude-team managed)
Conversation forking is only available when claude-team runs as a persistent
HTTP server. Indexing is opt-in and controlled by an environment flag.
Indexing runs in a background worker so HTTP requests remain responsive.

### Storage location
- Markdown exports live under `~/.claude-team/index/`
  - `~/.claude-team/index/claude/` for Claude sessions
  - `~/.claude-team/index/codex/` for Codex sessions
- qmd collections point at these directories (`claude-sessions`, `codex-sessions`).

### Opt-in and prerequisites
- Enable with `CLAUDE_TEAM_QMD_INDEXING=true` (HTTP mode only).
- On startup, claude-team verifies prerequisites:
  - `qmd` is on PATH
  - `~/.claude/projects` and `~/.codex/sessions` exist
  - It can create/read the markdown export directory and qmd collections
- If any check fails, claude-team logs an actionable error and disables indexing
  (server remains running).

### Indexing lifecycle (self-contained)
When enabled, claude-team owns the full lifecycle:
1. **Bootstrap:** First run converts existing Claude + Codex JSONL logs to Markdown
   (include an `Agent:` field in the header) and initializes two collections:
   `claude-sessions` and `codex-sessions`.
2. **Sync:** Runs `qmd update` and `qmd embed` for both collections after conversion.
3. **Ongoing:** Schedules periodic refreshes to keep the index current.

### Schedule configuration
- Default: hourly.
- Override with `CLAUDE_TEAM_INDEX_CRON` using a simple interval string
  (e.g., `15m`, `1h`, `6h`). Cron expressions can be supported later if needed.

### launchd utility
Provide a small utility/example for running claude-team as a persistent
launchd service in HTTP mode. Recommended deliverable is an installer script
that generates and loads a plist for the user. This is the suggested way to
keep indexing fresh and enable conversation forking.

## Open Questions
- How should result ranking controls be exposed (snippet length, min score)?
- Should the user-facing tool return short snippets or full context?
