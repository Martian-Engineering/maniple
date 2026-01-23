# Smart Forking Proposal

## Goal
Let a user describe what they want to implement, semantically search past Claude Code sessions, and fork from a selected session to inherit relevant context.

## Relevant Architecture (claude-team)
- MCP server lives in `src/claude_team_mcp/` with tools under `src/claude_team_mcp/tools/`.
- Session metadata and JSONL parsing live in `src/claude_team_mcp/registry.py` and `src/claude_team_mcp/session_state.py`.
- Claude CLI backend is `src/claude_team_mcp/cli_backends/claude.py`.
- Session logs are stored in `~/.claude/projects/<project-slug>/<session-id>.jsonl`.
  - `session_state.get_project_dir(project_path)` computes the project slug.

## qmd Reality Check
I verified qmd behavior against the `claude-sessions` collection:
- `qmd collection list` shows `claude-sessions` exists, but `qmd collection show claude-sessions` is not a supported subcommand.
- `qmd search "smart forking" -c claude-sessions --json` works and returns Markdown session exports.
- `qmd vsearch "smart forking" -c claude-sessions --json` fails with:
  - `SQLiteError: no such column: claude` (inside qmd `searchVec`).
- `qmd query "smart forking" -c claude-sessions --json` fails with the same error and then crashes Bun with a segfault.

The Markdown session exports include metadata like:
- `Session ID: <uuid>`
- `Working Directory: <path>`
- `Date: <timestamp>`

Implication: semantic search via `qmd query` is currently unreliable in this environment, so the Smart Fork implementation should:
- Prefer `qmd query` for full semantic + rerank when it works
- Gracefully fall back to `qmd vsearch`, then `qmd search` (BM25) if query/vsearch fail
- Surface the qmd error (and whether a fallback was used) in the response payload

## Proposed MCP Tool: `smart_fork`

### Tool Signature
```
smart_fork(
  intent: str,
  limit: int = 5,
  project_path: str | None = None,
  collection: str = "claude-sessions",
  min_score: float | None = None,
  include_snippets: bool = True,
  auto_fork: bool = False,
  fork_index: int | None = None
) -> dict
```

### Behavior
1. **Embed + search**
   - Prefer: `qmd query <intent> -c <collection> --json -n <limit>`
   - If that errors (currently does), fall back to:
     - `qmd vsearch <intent> -c <collection> --json -n <limit>`
     - If that errors, final fallback: `qmd search <intent> -c <collection> --json -n <limit>`
   - If qmd is not installed or collection is missing, skip qmd and return a guidance payload (see below).

2. **Parse results**
   - Each result is a Markdown file that includes `Session ID`, `Working Directory`, and `Date`.
   - Extract:
     - `session_id`
     - `working_directory`
     - `date`
     - `snippet` (from qmd result)
     - `score`
     - `source_path` (qmd doc path)
   - Optionally map to JSONL path:
     - `~/.claude/projects/<slug>/<session-id>.jsonl` via `session_state.get_project_dir()`.

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

## Integration with `spawn_workers`

### Option A: Extend WorkerConfig
Add optional fields:
```
resume_session_id: str | None
fork_session: bool = False
continue_session: bool = False
```
Then in `spawn_workers`, pass these through to the CLI backend to build args:
- `--resume <id>` when `resume_session_id` is present
- `--fork-session` when `fork_session` is true
- `--continue` when `continue_session` is true and no resume id is given

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
- If a session’s JSONL file doesn’t exist, include `can_fork=false` and a warning.
- Include a `qmd_error` field if query/vsearch fails so users understand fallback behavior.
- Add minimal CLI checks to ensure `claude` is on PATH and supports `--fork-session`.

## qmd Not Installed / Missing Collection Handling
If `qmd` is not available (`shutil.which("qmd")` is None) or the `claude-sessions`
collection isn’t configured, the tool should:
- Return a structured error response with a short, actionable setup guide.
- Provide a manual fallback option: list the most recent N Claude sessions
  (from `~/.claude/projects/**.jsonl`) so the user can still choose a session ID.

Suggested guidance payload:
```
{
  "error": "qmd_not_available",
  "message": "qmd is not installed or the claude-sessions collection is missing.",
  "next_steps": [
    "Install qmd and add a claude-sessions collection",
    "Run the claude-code-sessions converter to generate markdown exports",
    "Re-run smart_fork once indexing completes"
  ],
  "fallback_sessions": [
    {"session_id": "...", "project_path": "...", "last_modified": "..."}
  ]
}
```

## Ongoing Indexing Setup (claude-code-sessions skill)
There is an existing skill at `/Users/phaedrus/clawd/skills/claude-code-sessions` with
`scripts/convert.py` that converts `~/.claude/projects/**/*.jsonl` into Markdown for qmd.

Recommended workflow:
1. **Initial export:**
   - `python3 ~/clawd/skills/claude-code-sessions/scripts/convert.py ~/claude-sessions-md`
2. **Add qmd collection (once):**
   - `qmd collection add claude-sessions ~/claude-sessions-md --pattern "**/*.md"`
3. **Keep the index fresh:**
   - `qmd update` (re-index) + `qmd embed claude-sessions` (vectorize)
   - Or use `convert.py --index`, which runs `qmd update` and `qmd embed` after conversion.

The skill mentions a cron job every ~6 hours; we can either recommend
that schedule or add a `launchd` job to run the converter + `qmd update`
periodically (no caching or retry loops needed).

## Open Questions
- Do we want to support smart forking from Codex sessions (different log format)?
- Should we add a small cache of qmd results per query (I assume no, per project guidelines)?
- Should the user-facing tool return short snippets or full context?
