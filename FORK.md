# Fork: AxiomSynth/maniple

**Upstream:** [Martian-Engineering/maniple](https://github.com/Martian-Engineering/maniple)
**Fork point:** v0.13.0 (commit `2acd8c1`, ~2026-03-01)
**Local version:** 0.14.0-fork

## Why a fork?

The upstream maniple provides the core MCP server for managing Claude Code sessions via tmux/iTerm. This fork adds features specific to the Nexus orchestration system: per-worker tmux sessions with iTerm window grouping, session resume/recovery, and configuration enhancements for automated multi-project workflows.

## Custom changes (26 commits)

### iTerm window/tab management (7 commits)
| Commit | Description |
|--------|-------------|
| `a437fdc` | Add `target_window` parameter to `spawn_workers` for project-based window targeting |
| `1e606ca` | Per-worker tmux sessions for independent iTerm windows |
| `3e7efe5` | Open iTerm windows for per-worker tmux sessions |
| `17ef0e5` | Fix: search for existing project window on spawn |
| `5b9f5c0` | Fix: lowercase slug for case-sensitive AppleScript `contains` |
| `95d7b07` | Fix: extract issue ID from worker name for window grouping |
| `1d9eefd` | Fix: remove nexus exclusion from iTerm window opening |

### Session continuity + recovery (4 commits)
| Commit | Description |
|--------|-------------|
| `36eee65` | Add `reconnect_recovered_sessions()` for crash recovery |
| `2253781` | Add `--resume` support to `spawn_workers` for session continuity |
| `5397456` | Pass `--name` alongside `--resume` for Claude CLI |
| `6e8ded7` | Add `--name` flag support for Claude Code 2.1.76+ |

### Registry hardening (2 commits)
| Commit | Description |
|--------|-------------|
| `bb0c3fb` | Write-through registry and immediate spawn events |
| `d9f8724` | Fix naive/aware datetime mismatch in registry |

### Configuration enhancements (7 commits)
| Commit | Description |
|--------|-------------|
| `244c38a` | Add configurable iTerm profile for spawned sessions |
| `c7c1323` | Fix config parsing for `iterm_profile` field |
| `8f297cf` | Skip appearance color override when custom iTerm profile is set |
| `a57a46a` | Add `message_hints` config to disable issue tracker hints |
| `f2e1fb6` | Add `skip_worker_prompt` option to suppress THE DEAL prompt |
| `5387a03` | Add `skip_worker_prompt` to WorkerConfig TypedDict |
| `5bcd522` | Default `skip_worker_prompt` to true in config |
| `b09cf08` | Enforce `skip_permissions` config as ceiling, not just default |

### Idle detection + UI (3 commits)
| Commit | Description |
|--------|-------------|
| `b61d4f5` | Replace TUI pattern matching with process-based agent detection |
| `6ae743a` | Clean iTerm title bar via tmux `set-titles` and window naming |
| `51de99c` | Fix three idle detection and log capture bugs |
| `5dba22d` | Skip iTerm window for nexus session (later reverted in `1d9eefd`) |

### Security (1 commit)
| Commit | Description |
|--------|-------------|
| `371a138` | Fix shell injection via `shlex.quote` on all user-controlled paths |

### Message delivery (1 commit)
| Commit | Description |
|--------|-------------|
| (in `message_workers.py`) | `wait_idle_workers` + message flush improvements |

## Files modified (from upstream)

| File | Insertions | Focus |
|------|-----------|-------|
| `registry.py` | +355 | Write-through persistence, recovery, reconnect |
| `tmux.py` | +262 | Per-worker sessions, iTerm window management |
| `message_workers.py` | +94 | Idle wait, flush handling |
| `spawn_workers.py` | +92 | Resume, name, target_window, skip_worker_prompt |
| `wait_idle_workers.py` | +54 | Multi-session idle coordination |
| `iterm_utils.py` | +40 | Window search, profile support |
| `server.py` | +32 | Recovery startup sequence |
| `config.py` | +21 | New config fields |
| `claude.py` | +14 | --name flag, process detection |
| `base.py` | +11 | CLI backend interface changes |
| `iterm.py` | +6 | Backend delegation |

## Merge policy

### DO NOT revert these changes on upstream merge:
- **Shell injection fix** (`371a138`) — security-critical
- **Write-through registry** (`bb0c3fb`) — prevents data loss on crash
- **Per-worker tmux sessions** (`1e606ca`) — architectural foundation for Nexus
- **Session recovery** (`36eee65`) — crash resilience

### Safe to accept upstream changes in:
- Files we haven't modified (tests, docs, new tools)
- Additive changes to files we modified (new functions, new config fields)

### Requires careful merge:
- `registry.py` — our heaviest modification (355 lines added)
- `tmux.py` — per-worker session logic interleaved with upstream code
- `spawn_workers.py` — resume/name parameters added to upstream function signatures

## Upstream tracking

Check for upstream updates:
```bash
bash scripts/check-upstream.sh
```

If upstream has new commits:
1. Review changes: `git log --oneline upstream/main..HEAD` (our commits) vs `git log --oneline HEAD..upstream/main` (their new commits)
2. Check file overlap: `git diff --name-only upstream/main HEAD`
3. If no overlap: `git merge upstream/main` is safe
4. If overlap in modified files: cherry-pick individual upstream commits, test each
5. Never `git pull upstream main` blindly — always review first

## Running from source

The fork runs from source via `uv run` in a LaunchAgent:
```
WorkingDirectory: ~/maniple
Command: /usr/bin/env uv run python -m maniple_mcp --http --port 5111
```

After code changes: `pkill -f maniple_mcp` — LaunchAgent restarts automatically.
