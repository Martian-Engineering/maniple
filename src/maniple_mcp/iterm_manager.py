"""
iTerm2 window manager for tmux -CC control mode.

Manages iTerm2 windows and tabs via the Python API, bootstrapping tmux -CC
sessions for native scrollback integration. Zero AppleScript.

Key behaviors:
- Lazy connection: connects to iTerm2 on first use, refreshes if stale
- Best-effort: if API unavailable, logs warning — tmux sessions still work
- Gateway tracking: tracks -CC gateway tabs for cleanup on close
- Window persistence: caches project → window ID mapping to disk
"""

from __future__ import annotations

import asyncio
import colorsys
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import iterm2

logger = logging.getLogger("maniple")

# How long to wait for -CC connection discovery after bootstrap
_CC_DISCOVERY_TIMEOUT_S = 10.0
_CC_DISCOVERY_POLL_S = 0.5

# Golden ratio conjugate for even hue distribution across workers
_GOLDEN_RATIO_CONJUGATE = 0.618033988749895
_DEFAULT_SATURATION = 0.65
_DEFAULT_LIGHTNESS = 0.55


def generate_tab_color_rgb(index: int) -> tuple[int, int, int]:
    """Generate a distinct RGB color for a worker tab using golden ratio hue distribution."""
    hue = (index * _GOLDEN_RATIO_CONJUGATE) % 1.0
    r, g, b = colorsys.hls_to_rgb(hue, _DEFAULT_LIGHTNESS, _DEFAULT_SATURATION)
    return (int(r * 255), int(g * 255), int(b * 255))


class ItermManager:
    """Manages iTerm2 windows for tmux sessions via Python API + tmux -CC.

    All operations are best-effort: if the iTerm2 Python API is unavailable
    (not running, API disabled), methods log warnings and return without error.
    The tmux sessions still exist and work — users can attach manually.
    """

    _WINDOWS_PATH = Path.home() / ".maniple" / "iterm-windows.json"

    def __init__(self) -> None:
        self._connection: iterm2.Connection | None = None
        self._app: iterm2.App | None = None
        self._windows: dict[str, str] = {}  # project_key -> iTerm window_id
        self._gateways: dict[str, str] = {}  # tmux_session -> iTerm gateway session_id
        self._color_counter: int = 0
        self._load_window_ids()

    async def ensure_connected(self) -> iterm2.App | None:
        """Lazy-init and refresh stale iTerm2 Python API connection.

        Returns App on success, None on failure (best-effort).
        Connection.async_create() works from an existing asyncio loop
        (spike-validated — no run_forever() needed).
        """
        import iterm2

        if self._connection is not None and self._app is not None:
            try:
                refreshed = await iterm2.async_get_app(self._connection)
                if refreshed is not None:
                    self._app = refreshed
                    return self._app
            except Exception:
                logger.debug("iTerm2 connection stale, refreshing...")
                self._connection = None
                self._app = None

        try:
            self._connection = await iterm2.Connection.async_create()
            self._app = await iterm2.async_get_app(self._connection)
            if self._app is None:
                raise RuntimeError("async_get_app returned None")
            logger.debug("iTerm2 Python API connected")
            return self._app
        except Exception as e:
            logger.warning("iTerm2 Python API unavailable (%s) — windows won't open", e)
            self._connection = None
            self._app = None
            return None

    async def open_session(
        self,
        tmux_session: str,
        project: str | None = None,
        *,
        tab_title: str | None = None,
        tab_badge: str | None = None,
        tab_color_index: int | None = None,
    ) -> None:
        """Open an iTerm2 window/tab for a tmux session via -CC control mode.

        Best-effort: returns silently if API unavailable.

        Args:
            tmux_session: tmux session name to attach via -CC
            project: project name for window grouping
            tab_title: title for the native iTerm tab
            tab_badge: badge text for the tab
            tab_color_index: color index for golden-ratio hue distribution
        """
        app = await self.ensure_connected()
        if app is None:
            return

        project_key = project or "_default"
        window_id = self._windows.get(project_key)

        # Re-validate cached window ID (handles stale IDs from prior runs)
        if window_id and not await self._window_exists(window_id):
            logger.debug("Cached window %s no longer exists, clearing", window_id)
            del self._windows[project_key]
            self._save_window_ids()
            window_id = None

        if not window_id:
            window_id = await self._find_window_for_project(project)
            if window_id:
                logger.info("Found existing window %s for project %s", window_id, project)
            else:
                logger.info("No existing window found for project %s — creating new", project)

        await self._bootstrap_cc(window_id, tmux_session)

        # Discover and cache the window ID if we created a new one
        if not window_id:
            window_id = await self._discover_window_for_session(tmux_session)
            if window_id:
                self._windows[project_key] = window_id
                self._save_window_ids()
                logger.debug("Cached new window %s for project %s", window_id, project_key)

        # Tab appearance (color/title/badge) is disabled until DEV-50 fixes
        # _find_tmux_tab_session to scope by gateway. Without scoping, it
        # applies appearance to the wrong tab in concurrent spawns.

    def next_color_index(self) -> int:
        """Return and increment the color counter for tab color generation."""
        idx = self._color_counter
        self._color_counter += 1
        return idx

    async def close_session(self, tmux_session: str) -> None:
        """Close a -CC session: kill tmux session + close gateway tab.

        kill-session removes the tmux session and native -CC tabs, but the
        gateway tab survives as an orphaned shell. We close it explicitly.
        """
        # Close the gateway tab first (before the session dies)
        gateway_id = self._gateways.pop(tmux_session, None)
        if gateway_id:
            await self._close_session_by_id(gateway_id)

    async def set_tab_appearance(
        self,
        iterm_session_id: str,
        *,
        color: tuple[int, int, int] | None = None,
        title: str | None = None,
        badge: str | None = None,
    ) -> None:
        """Set tab color, title, and badge via Python API."""
        import iterm2

        app = await self.ensure_connected()
        if app is None:
            return

        session = self._find_session_by_id(app, iterm_session_id)
        if session is None:
            return

        if title is not None:
            tab = self._find_tab_for_session(app, iterm_session_id)
            if tab is not None:
                await tab.async_set_title(title)

        profile = iterm2.LocalWriteOnlyProfile()
        if color is not None:
            r, g, b = color
            tab_color = iterm2.Color(r, g, b)
            profile.set_tab_color(tab_color)
            profile.set_use_tab_color(True)
        if badge is not None:
            profile.set_badge_text(badge)
        await session.async_set_profile_properties(profile)

    async def activate_window(self, window_id: str) -> None:
        """Bring a window to front without stealing focus from other apps."""
        app = await self.ensure_connected()
        if app is None:
            return

        for w in app.terminal_windows:
            if w.window_id == window_id:
                # async_activate brings to front
                await w.async_activate()
                return

    async def find_tmux_session_for_tab(
        self, tab_id: str,
    ) -> str | None:
        """Find the tmux window ID for a -CC controlled tab.

        Returns the tmux window ID string, or None if not a -CC tab.
        Uses tab.tmux_window_id (-1 = non-tmux).
        """
        app = await self.ensure_connected()
        if app is None:
            return None

        for w in app.terminal_windows:
            for t in w.tabs:
                if t.tab_id == tab_id:
                    tmux_wid = t.tmux_window_id
                    if tmux_wid is not None and str(tmux_wid) != "-1":
                        return str(tmux_wid)
                    return None
        return None

    # ---- Internal: bootstrap ----

    async def _bootstrap_cc(
        self,
        window_id: str | None,
        tmux_session: str,
    ) -> None:
        """Bootstrap -CC via Python API (zero AppleScript).

        1. Create tab in target window (or new window)
        2. Send tmux -CC attach command
        3. Poll for TmuxConnection discovery (~0.5s typical)
        4. Track gateway session ID for cleanup
        """
        import iterm2

        if self._connection is None or self._app is None:
            return

        try:
            if window_id:
                window = self._find_window_by_id(window_id)
                if window is not None:
                    tab = await window.async_create_tab()
                else:
                    # Window gone, create new
                    window = await iterm2.Window.async_create(self._connection)
                    tab = window.tabs[0]
            else:
                window = await iterm2.Window.async_create(self._connection)
                tab = window.tabs[0]

            gateway = tab.current_session
            await gateway.async_send_text(f"tmux -CC attach -t {tmux_session}\n")

            # Track gateway for cleanup
            self._gateways[tmux_session] = gateway.session_id
            logger.debug(
                "Bootstrapped -CC for %s, gateway=%s",
                tmux_session, gateway.session_id,
            )

            # Wait for -CC connection to establish
            attempts = int(_CC_DISCOVERY_TIMEOUT_S / _CC_DISCOVERY_POLL_S)
            for i in range(attempts):
                await asyncio.sleep(_CC_DISCOVERY_POLL_S)
                try:
                    conns = await iterm2.async_get_tmux_connections(self._connection)
                    if conns:
                        logger.debug(
                            "-CC connection discovered after %.1fs (%d connection(s))",
                            (i + 1) * _CC_DISCOVERY_POLL_S, len(conns),
                        )
                        return
                except Exception:
                    pass

            logger.warning(
                "Timed out waiting for -CC connection for %s after %.0fs",
                tmux_session, _CC_DISCOVERY_TIMEOUT_S,
            )
        except Exception as e:
            logger.warning("Failed to bootstrap -CC for %s: %s", tmux_session, e)

    # ---- Internal: window discovery ----

    async def _find_window_for_project(
        self, project: str | None,
    ) -> str | None:
        """Find existing iTerm window for project via Python API traversal.

        Searches for windows containing tabs with -CC controlled sessions
        whose names match the project pattern. Forces an app refresh to
        ensure newly created windows (from other -CC connections) are visible.
        """
        if not project:
            return None

        # Force fresh app state — other spawn calls may have created windows
        # that our cached _app doesn't know about yet
        app = await self.ensure_connected()
        if app is None:
            return None

        slug = project.lower().replace(" ", "-")
        short = slug.split("-")[0][:3]
        patterns = [
            f"{short}-reviewer",
            f"maniple-{slug}",
            slug,
        ]

        for w in app.terminal_windows:
            for t in w.tabs:
                for s in t.sessions:
                    try:
                        name = await s.async_get_variable("name")
                        if name and any(p in str(name).lower() for p in patterns):
                            logger.debug(
                                "Found project window %s for %s (matched '%s')",
                                w.window_id, project, name,
                            )
                            return w.window_id
                    except Exception:
                        continue
        return None

    async def _discover_window_for_session(
        self, tmux_session: str,
    ) -> str | None:
        """Find the iTerm window containing the newly created -CC tabs.

        After bootstrap, iTerm creates native tabs for tmux windows.
        Find the window containing a tab with tmux_window_id != -1.
        """
        if self._app is None:
            return None

        # Refresh app state to see new tabs
        app = await self.ensure_connected()
        if app is None:
            return None

        for w in app.terminal_windows:
            for t in w.tabs:
                if t.tmux_window_id is not None and str(t.tmux_window_id) != "-1":
                    return w.window_id
        return None

    async def _find_tmux_tab_session(self) -> str | None:
        """Find the iTerm session ID of the most recently created -CC tab.

        After bootstrap, the newest tab with tmux_window_id != -1 is our tab.
        """
        app = await self.ensure_connected()
        if app is None:
            return None

        # Find any tab with a real tmux_window_id
        for w in app.terminal_windows:
            for t in w.tabs:
                if t.tmux_window_id is not None and str(t.tmux_window_id) != "-1":
                    return t.current_session.session_id
        return None

    async def _window_exists(self, window_id: str) -> bool:
        """Check if an iTerm window still exists."""
        if self._app is None:
            return False
        return any(w.window_id == window_id for w in self._app.terminal_windows)

    def _find_window_by_id(self, window_id: str) -> iterm2.Window | None:
        """Find an iTerm window by ID."""
        if self._app is None:
            return None
        for w in self._app.terminal_windows:
            if w.window_id == window_id:
                return w
        return None

    # ---- Internal: session helpers ----

    def _find_session_by_id(
        self, app: iterm2.App, session_id: str,
    ) -> iterm2.Session | None:
        """Find an iTerm session by ID across all windows."""
        for w in app.terminal_windows:
            for t in w.tabs:
                for s in t.sessions:
                    if s.session_id == session_id:
                        return s
        return None

    def _find_tab_for_session(
        self, app: iterm2.App, session_id: str,
    ) -> iterm2.Tab | None:
        """Find the tab containing a session."""
        for w in app.terminal_windows:
            for t in w.tabs:
                for s in t.sessions:
                    if s.session_id == session_id:
                        return t
        return None

    async def _close_session_by_id(self, session_id: str) -> None:
        """Close an iTerm session by ID. Best-effort."""
        app = await self.ensure_connected()
        if app is None:
            return
        session = self._find_session_by_id(app, session_id)
        if session is not None:
            try:
                await session.async_close(force=True)
                logger.debug("Closed iTerm session %s", session_id)
            except Exception as e:
                logger.debug("Failed to close iTerm session %s: %s", session_id, e)

    # ---- Internal: persistence ----

    def _load_window_ids(self) -> None:
        """Load persisted window IDs from disk."""
        if self._WINDOWS_PATH.exists():
            try:
                data = json.loads(self._WINDOWS_PATH.read_text())
                if isinstance(data, dict):
                    self._windows = data
            except (json.JSONDecodeError, OSError):
                pass

    def _save_window_ids(self) -> None:
        """Persist window IDs to disk."""
        try:
            self._WINDOWS_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._WINDOWS_PATH.write_text(json.dumps(self._windows, indent=2))
        except OSError:
            pass
