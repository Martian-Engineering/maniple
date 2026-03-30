"""
Tmux terminal backend adapter.

Provides a TerminalBackend implementation backed by tmux CLI commands.
"""

from __future__ import annotations

import asyncio
import re
import shlex
import subprocess
import uuid
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .base import TerminalBackend, TerminalSession
from ..iterm_manager import ItermManager

if TYPE_CHECKING:
    from ..cli_backends import AgentCLI


KEY_MAP: dict[str, str] = {
    "enter": "C-m",
    "return": "C-m",
    "newline": "C-j",
    "escape": "Escape",
    "tab": "Tab",
    "backspace": "BSpace",
    "delete": "DC",
    "up": "Up",
    "down": "Down",
    "right": "Right",
    "left": "Left",
    "home": "Home",
    "end": "End",
    "ctrl-c": "C-c",
    "ctrl-d": "C-d",
    "ctrl-u": "C-u",
    "ctrl-l": "C-l",
    "ctrl-z": "C-z",
}

ISSUE_ID_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*-[A-Za-z0-9]*\d[A-Za-z0-9]*\b")

SHELL_READY_MARKER = "MANIPLE_READY_7f3a9c"
CODEX_PRE_ENTER_DELAY = 0.5
TMUX_SESSION_PREFIX = "maniple"
LEGACY_TMUX_SESSION_PREFIX = "claude-team"
TMUX_SESSION_SLUG_MAX = 32
TMUX_SESSION_FALLBACK = "project"
TMUX_SESSION_PREFIXED = f"{TMUX_SESSION_PREFIX}-"
LEGACY_TMUX_SESSION_PREFIXED = f"{LEGACY_TMUX_SESSION_PREFIX}-"
MANAGED_TMUX_SESSION_PREFIXES = (TMUX_SESSION_PREFIXED, LEGACY_TMUX_SESSION_PREFIXED)

LAYOUT_PANE_NAMES = {
    "single": ["main"],
    "vertical": ["left", "right"],
    "triple_vertical": ["left", "middle", "right"],
    "horizontal": ["top", "bottom"],
    "quad": ["top_left", "top_right", "bottom_left", "bottom_right"],
}

LAYOUT_SELECT = {
    "vertical": "even-horizontal",
    "triple_vertical": "even-horizontal",
    "horizontal": "even-vertical",
    "quad": "tiled",
}


# Normalize a project name into a tmux-safe slug.
def _tmux_safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    slug = slug.strip("-_")
    if not slug:
        return TMUX_SESSION_FALLBACK
    if len(slug) > TMUX_SESSION_SLUG_MAX:
        slug = slug[:TMUX_SESSION_SLUG_MAX].rstrip("-_")
    return slug or TMUX_SESSION_FALLBACK


def project_name_from_path(project_path: str | None) -> str | None:
    """Return a display name for a project path, handling worktree paths."""
    if not project_path:
        return None
    path = Path(project_path)
    parts = path.parts
    if ".worktrees" in parts:
        worktrees_index = parts.index(".worktrees")
        if worktrees_index > 0:
            return parts[worktrees_index - 1]
    return path.name


def tmux_session_name_for_project(project_path: str | None) -> str:
    """Return the per-project tmux session name for a given project path.

    Worktree paths produce the same session name as their main repository
    since project_name_from_path extracts the project name from the path.
    Session names follow the format: maniple-{project-slug}
    """
    project_name = project_name_from_path(project_path) or TMUX_SESSION_FALLBACK
    slug = _tmux_safe_slug(project_name)
    return f"{TMUX_SESSION_PREFIXED}{slug}"


# Determine whether a tmux session is managed by maniple (or legacy claude-team).
def _is_managed_session_name(session_name: str) -> bool:
    return session_name.startswith(MANAGED_TMUX_SESSION_PREFIXES)


def build_stop_hook_settings_file(marker_id: str) -> str:
    """Build a settings file for Stop hook injection.

    The hook embeds a marker in the command text itself, which gets logged
    to the JSONL in the stop_hook_summary's hookInfos array. This provides
    reliable completion detection without needing stderr or exit code hacks.

    Args:
        marker_id: Unique ID to embed in the marker (typically session_id)

    Returns:
        Path to the settings file (suitable for --settings flag)
    """
    import json as _json
    from pathlib import Path as _Path

    settings_dir = _Path.home() / ".claude" / "claude-team-settings"
    settings_dir.mkdir(parents=True, exist_ok=True)

    settings = {
        "hooks": {
            "Stop": [{
                "hooks": [{
                    "type": "command",
                    "command": f"echo [worker-done:{marker_id}]"
                }]
            }]
        }
    }

    settings_file = settings_dir / f"worker-{marker_id}.json"
    settings_file.write_text(_json.dumps(settings, indent=2))
    return str(settings_file)


class TmuxBackend(TerminalBackend):
    """Terminal backend adapter for tmux."""

    backend_id = "tmux"

    def __init__(self, socket_path: str | None = None) -> None:
        """Initialize the backend with an optional tmux socket path."""
        self._socket_path = socket_path
        self._iterm = ItermManager()

    def wrap_session(self, handle: Any) -> TerminalSession:
        """Wrap a tmux pane id in a TerminalSession."""
        pane_id = str(handle)
        return TerminalSession(
            backend_id=self.backend_id,
            native_id=pane_id,
            handle=pane_id,
        )

    def unwrap_session(self, session: TerminalSession) -> str:
        """Extract the tmux pane id from a TerminalSession."""
        return str(session.handle)

    async def create_session(
        self,
        name: str | None = None,
        *,
        project_path: str | None = None,
        issue_id: str | None = None,
        coordinator_badge: str | None = None,
        profile: str | None = None,
        profile_customizations: Any | None = None,
    ) -> TerminalSession:
        """Create a worker in its own tmux session.

        Each named worker gets a dedicated tmux session (``maniple-{name}``),
        so it can be attached in its own iTerm window/tab independently.
        Unnamed workers fall back to a shared per-project session.
        """
        if profile or profile_customizations:
            raise ValueError("tmux backend does not support profiles")

        base_name = name or self._generate_window_name()
        project_name = project_name_from_path(project_path)
        resolved_issue_id = self._resolve_issue_id(issue_id, coordinator_badge, name)
        window_name = self._format_window_name(base_name, project_name, resolved_issue_id)
        # Named workers get their own tmux session so each can have an
        # independent iTerm window.  Unnamed workers share a per-project session.
        if name:
            session_name = f"{TMUX_SESSION_PREFIXED}{_tmux_safe_slug(name)}"
        else:
            session_name = tmux_session_name_for_project(project_path)

        # Named workers always get a fresh session.  If a stale session with
        # the same name exists (leftover from a prior spawn), kill it first.
        # Unnamed workers add windows to a shared per-project session.
        try:
            await self._run_tmux(["has-session", "-t", session_name])
            if name:
                # Stale session — kill it so we can create a clean one.
                await self._run_tmux(["kill-session", "-t", session_name])
                raise subprocess.CalledProcessError(1, "has-session")  # fall through to new-session
            else:
                output = await self._run_tmux(
                    [
                        "new-window",
                        "-t",
                        session_name,
                        "-n",
                        window_name,
                        "-P",
                        "-F",
                        "#{pane_id}\t#{window_id}\t#{window_index}",
                    ]
                )
        except subprocess.CalledProcessError:
            output = await self._run_tmux(
                [
                    "new-session",
                    "-d",
                    "-s",
                    session_name,
                    "-n",
                    window_name,
                    "-P",
                    "-F",
                    "#{pane_id}\t#{window_id}\t#{window_index}",
                ]
            )

        pane_id, window_id, window_index = self._parse_window_output(output)
        if not pane_id:
            raise RuntimeError("Failed to determine tmux pane id for new window")

        # For named workers with their own session, open an iTerm
        # window/tab so the session is visible. First worker for a
        # project gets a new window; subsequent workers get tabs.
        # Skip for nexus — it already runs in an attached tmux session.
        #
        # Use issue_id prefix to determine project grouping for iTerm windows.
        # This ensures DEV-26 workers in ~/cognitive-cache still group under
        # the dev-ops window with the dev-reviewer.
        if name:
            window_group = project_name
            if resolved_issue_id:
                prefix = resolved_issue_id.split("-")[0].lower() if "-" in resolved_issue_id else None
                prefix_to_project = {"sie": "sieve", "pra": "prakasha", "tre": "trendiculosa", "dev": "dev-ops"}
                if prefix and prefix in prefix_to_project:
                    window_group = prefix_to_project[prefix]
            await self._iterm.open_session(
                session_name,
                window_group,
                tab_title=window_name,
                tab_badge=coordinator_badge or resolved_issue_id,
                tab_color_index=self._iterm.next_color_index(),
            )

        # Register pane-exited hook for crash detection.
        # When the process in the pane exits (crash, OOM, manual kill),
        # write a sentinel file that the idle detector and registry can check.
        #
        # Note: pane-exited does NOT fire when a -CC native tab is closed
        # (PAT-075). For -CC sessions, the idle detector falls back to
        # tmux has-session checks (~5s poll), which is acceptable latency.
        # The after-kill-pane global hook cannot be used because #{pane_id}
        # reports the surviving pane, not the killed one.
        sentinel_dir = Path.home() / ".maniple" / "sentinels"
        sentinel_dir.mkdir(parents=True, exist_ok=True)
        safe_pane_id = pane_id.replace("%", "pane")
        sentinel_path = sentinel_dir / f"{safe_pane_id}.exited"
        try:
            await self._run_tmux([
                "set-hook", "-t", session_name,
                "pane-exited",
                f"run-shell 'touch {sentinel_path}'",
            ])
        except subprocess.CalledProcessError:
            logger.debug("Failed to set pane-exited hook for %s — non-fatal", pane_id)

        metadata = {
            "session_name": session_name,
            "window_id": window_id,
            "window_index": window_index,
            "window_name": window_name,
            "sentinel_path": str(sentinel_path),
        }
        if project_name:
            metadata["project_name"] = project_name
        if resolved_issue_id:
            metadata["issue_id"] = resolved_issue_id

        return TerminalSession(
            backend_id=self.backend_id,
            native_id=pane_id,
            handle=pane_id,
            metadata=metadata,
        )

    async def send_text(self, session: TerminalSession, text: str) -> None:
        """Send raw text to a tmux pane.

        For multi-line text, uses load-buffer + paste-buffer which is more
        reliable than send-keys -l for long content. The -p flag on
        paste-buffer omits the trailing newline so Enter can be sent separately.
        """
        pane_id = self.unwrap_session(session)
        if "\n" in text:
            buf_name = f"maniple-{uuid.uuid4().hex[:8]}"
            proc = await asyncio.create_subprocess_exec(
                "tmux", "load-buffer", "-b", buf_name, "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate(input=text.encode("utf-8"))
            await self._run_tmux(["paste-buffer", "-b", buf_name, "-t", pane_id, "-p"])
            try:
                await self._run_tmux(["delete-buffer", "-b", buf_name])
            except subprocess.CalledProcessError:
                pass
        else:
            await self._run_tmux(["send-keys", "-t", pane_id, "-l", text])

    async def send_key(self, session: TerminalSession, key: str) -> None:
        """Send a special key to a tmux pane."""
        pane_id = self.unwrap_session(session)
        tmux_key = KEY_MAP.get(key.lower())
        if tmux_key is None:
            raise ValueError(f"Unknown key: {key}. Available: {list(KEY_MAP.keys())}")
        await self._run_tmux(["send-keys", "-t", pane_id, tmux_key])

    async def send_prompt(
        self, session: TerminalSession, text: str, submit: bool = True
    ) -> None:
        """Send a prompt to a tmux pane, optionally submitting it."""
        await self.send_text(session, text)
        if not submit:
            return
        # Delay to allow tmux to finish pasting before sending Enter.
        delay = self._compute_paste_delay(text)
        await asyncio.sleep(delay)
        await self.send_key(session, "enter")

    async def send_prompt_for_agent(
        self,
        session: TerminalSession,
        text: str,
        agent_type: str = "claude",
        submit: bool = True,
    ) -> None:
        """Send a prompt with agent-specific handling (Claude vs Codex)."""
        await self.send_text(session, text)
        if not submit:
            return
        # Codex needs a longer pre-Enter delay; use the max of paste vs minimum.
        delay = self._compute_paste_delay(text)
        if agent_type == "codex":
            delay = max(CODEX_PRE_ENTER_DELAY, delay)
        await asyncio.sleep(delay)
        await self.send_key(session, "enter")

    async def read_screen_text(self, session: TerminalSession) -> str:
        """Read visible screen content from a tmux pane."""
        pane_id = self.unwrap_session(session)
        return await self._run_tmux(["capture-pane", "-p", "-t", pane_id])

    async def split_pane(
        self,
        session: TerminalSession,
        *,
        vertical: bool = True,
        before: bool = False,
        profile: str | None = None,
        profile_customizations: Any | None = None,
    ) -> TerminalSession:
        """Split a tmux pane and return the new pane."""
        if profile or profile_customizations:
            raise ValueError("tmux backend does not support profiles")

        pane_id = self.unwrap_session(session)
        args = ["split-window", "-t", pane_id]
        args.append("-h" if vertical else "-v")
        if before:
            args.append("-b")
        # -P prints the new pane id, -F controls the output format.
        args.extend(["-P", "-F", "#{pane_id}"])

        output = await self._run_tmux(args)
        new_pane_id = self._first_non_empty_line(output)
        if not new_pane_id:
            raise RuntimeError("Failed to determine tmux pane id for split")

        metadata = dict(session.metadata) if session.metadata else {}
        return TerminalSession(
            backend_id=self.backend_id,
            native_id=new_pane_id,
            handle=new_pane_id,
            metadata=metadata,
        )

    async def close_session(self, session: TerminalSession, force: bool = False) -> None:
        """Close a tmux window (or its pane) for this worker.

        For named workers with their own tmux session and a -CC gateway,
        also cleans up the gateway tab via ItermManager.

        Order matters: kill tmux first (which disconnects -CC and unburies
        the gateway tab), then close the gateway. Closing gateway first
        doesn't work because iTerm unburies it when -CC disconnects.
        """
        pane_id = self.unwrap_session(session)
        _ = force
        session_name = session.metadata.get("session_name")

        # Kill tmux window/pane first
        window_id = session.metadata.get("window_id")
        if not window_id:
            window_id = await self._window_id_for_pane(pane_id)
        if window_id:
            await self._run_tmux(["kill-window", "-t", window_id])
        else:
            await self._run_tmux(["kill-pane", "-t", pane_id])

        # Clean up -CC gateway tab AFTER tmux kill (best-effort).
        # Must be after kill because killing tmux disconnects -CC, which
        # causes iTerm to unbury the gateway tab. We close it post-unbury.
        if session_name:
            await asyncio.sleep(0.5)  # allow iTerm to process -CC disconnect
            await self._iterm.close_session(session_name)

    async def create_multi_pane_layout(
        self,
        layout: str,
        *,
        profile: str | None = None,
        profile_customizations: dict[str, Any] | None = None,
    ) -> dict[str, TerminalSession]:
        """Create a multi-pane layout in a new tmux window."""
        if profile or profile_customizations:
            raise ValueError("tmux backend does not support profiles")
        if layout not in LAYOUT_PANE_NAMES:
            raise ValueError(f"Unknown layout: {layout}. Valid: {list(LAYOUT_PANE_NAMES.keys())}")

        # Start a new window for this layout within the dedicated session.
        initial = await self.create_session()
        session_name = initial.metadata.get("session_name")
        window_id = initial.metadata.get("window_id")

        panes: dict[str, TerminalSession] = {}

        if layout == "single":
            panes["main"] = initial
        elif layout == "vertical":
            panes["left"] = initial
            panes["right"] = await self.split_pane(initial, vertical=True)
        elif layout == "triple_vertical":
            panes["left"] = initial
            panes["middle"] = await self.split_pane(initial, vertical=True)
            panes["right"] = await self.split_pane(panes["middle"], vertical=True)
        elif layout == "horizontal":
            panes["top"] = initial
            panes["bottom"] = await self.split_pane(initial, vertical=False)
        elif layout == "quad":
            panes["top_left"] = initial
            panes["top_right"] = await self.split_pane(initial, vertical=True)
            panes["bottom_left"] = await self.split_pane(initial, vertical=False)
            panes["bottom_right"] = await self.split_pane(panes["top_right"], vertical=False)

        if layout in LAYOUT_SELECT:
            target = window_id or session_name
            if target:
                await self._run_tmux(["select-layout", "-t", target, LAYOUT_SELECT[layout]])

        return panes

    async def list_sessions(self) -> list[TerminalSession]:
        """List all tmux panes in maniple-managed sessions (including legacy prefixes)."""
        try:
            output = await self._run_tmux(
                [
                    "list-panes",
                    "-a",
                    "-F",
                    "#{session_name}\t#{window_id}\t#{window_name}\t#{window_index}\t#{pane_index}\t#{pane_id}",
                ]
            )
        except subprocess.CalledProcessError:
            return []

        sessions: list[TerminalSession] = []

        # Each line includes session/window/pane metadata and pane id.
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 6:
                continue
            session_name, window_id, window_name, window_index, pane_index, pane_id = parts
            if not _is_managed_session_name(session_name):
                continue
            sessions.append(
                TerminalSession(
                    backend_id=self.backend_id,
                    native_id=pane_id,
                    handle=pane_id,
                    metadata={
                        "session_name": session_name,
                        "window_id": window_id,
                        "window_name": window_name,
                        "window_index": window_index,
                        "pane_index": pane_index,
                    },
                )
            )

        return sessions

    async def find_available_window(
        self,
        max_panes: int = 4,
        managed_session_ids: set[str] | None = None,
    ) -> tuple[str, str, TerminalSession] | None:
        """Find a tmux window with space for additional panes."""
        # Query panes across all tmux sessions/windows with enough metadata
        # to group panes and select a reasonable split target.
        try:
            output = await self._run_tmux(
                [
                    "list-panes",
                    "-a",
                    "-F",
                    "#{session_name}\t#{window_id}\t#{window_index}\t#{pane_index}\t#{pane_active}\t#{pane_id}",
                ]
            )
        except subprocess.CalledProcessError:
            return None

        panes_by_window: dict[tuple[str, str, str], list[dict[str, str]]] = {}

        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 6:
                continue
            session_name, window_id, window_index, pane_index, pane_active, pane_id = parts
            if not _is_managed_session_name(session_name):
                continue
            panes_by_window.setdefault((session_name, window_id, window_index), []).append(
                {
                    "pane_id": pane_id,
                    "pane_index": pane_index,
                    "pane_active": pane_active,
                }
            )

        for (session_name, window_id, window_index), panes in panes_by_window.items():
            # Respect the managed-session filter when provided (including empty set).
            if managed_session_ids is not None:
                if not any(p["pane_id"] in managed_session_ids for p in panes):
                    continue

            # Only consider windows that have room for more panes.
            if len(panes) >= max_panes:
                continue

            # Prefer the active pane as the split target when available.
            target = next((p for p in panes if p["pane_active"] == "1"), panes[0])
            return (
                session_name,
                window_index,
                TerminalSession(
                    backend_id=self.backend_id,
                    native_id=target["pane_id"],
                    handle=target["pane_id"],
                    metadata={
                        "session_name": session_name,
                        "window_id": window_id,
                        "window_index": window_index,
                        "pane_index": target["pane_index"],
                    },
                ),
            )

        return None

    async def start_agent_in_session(
        self,
        handle: TerminalSession,
        cli: "AgentCLI",
        project_path: str,
        dangerously_skip_permissions: bool = False,
        env: dict[str, str] | None = None,
        shell_ready_timeout: float = 10.0,
        agent_ready_timeout: float = 30.0,
        stop_hook_marker_id: str | None = None,
        output_capture_path: str | None = None,
        plugin_dir: str | None = None,
        session_name: str | None = None,
        resume_session: str | None = None,
    ) -> None:
        """Start a CLI agent in an existing tmux pane."""
        # Ensure the shell is responsive before we send the launch command.
        shell_ready = await self._wait_for_shell_ready(
            handle, timeout_seconds=shell_ready_timeout
        )
        if not shell_ready:
            raise RuntimeError(
                f"Shell not ready after {shell_ready_timeout}s in {project_path}. "
                "Terminal may still be initializing."
            )

        # Optionally inject a Stop hook using a settings file (Claude only).
        settings_file = None
        if stop_hook_marker_id and cli.supports_settings_file():
            settings_file = build_stop_hook_settings_file(stop_hook_marker_id)

        # Build the CLI command (with env vars and settings) for this agent.
        agent_cmd = cli.build_full_command(
            dangerously_skip_permissions=dangerously_skip_permissions,
            settings_file=settings_file,
            plugin_dir=plugin_dir,
            session_name=session_name,
            resume_session=resume_session,
            env_vars=env,
        )

        # Capture stdout/stderr if requested (useful for JSONL idle detection).
        if output_capture_path:
            agent_cmd = f"{agent_cmd} 2>&1 | tee {shlex.quote(output_capture_path)}"

        # Launch in one atomic command to avoid races between cd and exec.
        cmd = f"cd {shlex.quote(project_path)} && {agent_cmd}"
        await self.send_prompt(handle, cmd, submit=True)

        # Wait for the agent to become ready before returning.
        # Use shorter timeout for resume attempts — if the session is expired,
        # Claude Code falls back to fresh start quickly. No need to wait 30s.
        effective_timeout = min(agent_ready_timeout, 15.0) if resume_session else agent_ready_timeout
        agent_ready = await self._wait_for_agent_ready(
            handle,
            cli,
            timeout_seconds=effective_timeout,
        )
        if not agent_ready:
            raise RuntimeError(
                f"{cli.engine_id} failed to start in {project_path} within "
                f"{agent_ready_timeout}s. Check that '{cli.command()}' is "
                "available and authentication is configured."
            )

    async def start_claude_in_session(
        self,
        handle: TerminalSession,
        project_path: str,
        dangerously_skip_permissions: bool = False,
        env: dict[str, str] | None = None,
        shell_ready_timeout: float = 10.0,
        claude_ready_timeout: float = 30.0,
        stop_hook_marker_id: str | None = None,
    ) -> None:
        """Start Claude Code in an existing tmux pane."""
        from ..cli_backends import claude_cli

        await self.start_agent_in_session(
            handle=handle,
            cli=claude_cli,
            project_path=project_path,
            dangerously_skip_permissions=dangerously_skip_permissions,
            env=env,
            shell_ready_timeout=shell_ready_timeout,
            agent_ready_timeout=claude_ready_timeout,
            stop_hook_marker_id=stop_hook_marker_id,
        )

    async def _run_tmux(self, args: list[str]) -> str:
        """Run a tmux command and return stdout."""
        cmd = ["tmux"]
        if self._socket_path:
            cmd.extend(["-S", self._socket_path])
        cmd.extend(args)

        def _run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )

        result = await asyncio.to_thread(_run)
        return result.stdout.strip()

    def _compute_paste_delay(self, text: str) -> float:
        """Compute a delay to let tmux process pasted text before Enter."""
        # Match the iTerm delay heuristics for consistent cross-backend timing.
        line_count = text.count("\n")
        char_count = len(text)
        if line_count > 0:
            return min(2.0, 0.1 + (line_count * 0.01) + (char_count / 1000 * 0.05))
        return 0.05

    async def _wait_for_shell_ready(
        self,
        session: TerminalSession,
        *,
        timeout_seconds: float = 10.0,
        poll_interval: float = 0.1,
    ) -> bool:
        """Wait for the shell to accept input by echoing a marker."""
        import time

        # Kick off the marker echo and then look for the echoed line.
        await self.send_prompt(session, f'echo "{SHELL_READY_MARKER}"', submit=True)

        start_time = time.monotonic()
        while (time.monotonic() - start_time) < timeout_seconds:
            # Scan visible pane content for the marker on its own line.
            content = await self.read_screen_text(session)
            for line in content.splitlines():
                if line.strip() == SHELL_READY_MARKER:
                    return True
            await asyncio.sleep(poll_interval)

        return False

    async def _wait_for_agent_ready(
        self,
        session: TerminalSession,
        cli: "AgentCLI",
        *,
        timeout_seconds: float = 15.0,
        poll_interval: float = 0.5,
        stable_count: int = 2,
    ) -> bool:
        """Wait for an agent CLI to start in the pane.

        Uses process-based detection: polls ``pane_current_command`` to check
        whether the shell has been replaced by the agent process.  This is more
        reliable than TUI pattern matching which breaks on resumed sessions
        (loading output never stabilises) and prompt-injection warnings (ready
        patterns never appear).

        Falls back to the legacy TUI pattern scan if the process check is
        inconclusive (e.g. the agent binary name matches a common shell name).
        """
        import time

        pane_id = self.unwrap_session(session)
        shells = {"zsh", "bash", "sh", "fish", "dash", "tcsh", "csh"}
        start_time = time.monotonic()

        while (time.monotonic() - start_time) < timeout_seconds:
            try:
                cmd_output = await self._run_tmux(
                    ["display-message", "-p", "-t", pane_id, "#{pane_current_command}"]
                )
                current_cmd = cmd_output.strip()
                # If the pane command is no longer a shell, the agent launched.
                if current_cmd and current_cmd not in shells:
                    return True
            except subprocess.CalledProcessError:
                pass  # pane may not exist yet; keep polling

            await asyncio.sleep(poll_interval)

        # Timeout reached — fall back to a single TUI pattern check on the
        # current screen content so that non-tmux edge-cases still work.
        patterns = cli.ready_patterns()
        try:
            content = await self.read_screen_text(session)
            for line in content.splitlines():
                stripped = line.strip()
                for pattern in patterns:
                    if pattern in stripped:
                        return True
        except subprocess.CalledProcessError:
            pass

        return False

    # Resolve an issue id from explicit input, worker name, or coordinator badge text.
    def _resolve_issue_id(
        self,
        issue_id: str | None,
        coordinator_badge: str | None,
        name: str | None = None,
    ) -> str | None:
        if issue_id:
            return issue_id
        # Check worker name — Nexus names workers after their issue ID (e.g., "DEV-30")
        if name:
            match = ISSUE_ID_PATTERN.search(name)
            if match:
                return match.group(0)
        if not coordinator_badge:
            return None
        match = ISSUE_ID_PATTERN.search(coordinator_badge)
        if not match:
            return None
        return match.group(0)

    # Build the final tmux window name for a worker.
    # This also becomes the iTerm title bar via set-titles-string "#W".
    def _format_window_name(
        self,
        name: str,
        project_name: str | None,
        issue_id: str | None,
    ) -> str:
        if project_name and issue_id:
            return f"{project_name} — {name} [{issue_id}]"
        if project_name:
            return f"{project_name} — {name}"
        return name

    # Generate a default tmux window name.
    def _generate_window_name(self) -> str:
        return f"worker-{uuid.uuid4().hex[:8]}"

    # Parse tmux output that includes pane and window ids.
    @staticmethod
    def _parse_window_output(text: str) -> tuple[str | None, str | None, str | None]:
        line = next((line for line in text.splitlines() if line.strip()), "")
        parts = [part.strip() for part in line.split("\t")]
        if len(parts) < 3:
            return None, None, None
        pane_id, window_id, window_index = parts[0], parts[1], parts[2]
        return pane_id, window_id, window_index

    # Resolve the window id that owns a given pane id.
    async def _window_id_for_pane(self, pane_id: str) -> str | None:
        output = await self._run_tmux(
            ["display-message", "-p", "-t", pane_id, "#{window_id}"]
        )
        return output.strip() or None

    @staticmethod
    def _first_non_empty_line(text: str) -> str | None:
        """Return the first non-empty line from text, if any."""
        for line in text.splitlines():
            line = line.strip()
            if line:
                return line
        return None
