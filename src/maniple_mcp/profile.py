"""
iTerm2 Profile Management for Claude Team MCP

Handles creation and customization of iTerm2 profiles for managed Claude sessions.
Includes automatic dark/light mode detection and consistent visual styling.
"""

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iterm2.color import Color as ItermColor
    from iterm2.connection import Connection as ItermConnection
    from iterm2.profile import LocalWriteOnlyProfile

from .subprocess_cache import cached_system_profiler

logger = logging.getLogger("claude-team-mcp.profile")


# =============================================================================
# Constants
# =============================================================================

# Profile identifier - used to find or create our managed profile
PROFILE_NAME = "claude-team"

# Font configuration - Source Code Pro preferred, Menlo as fallback
FONT_PRIMARY = "Source Code Pro"
FONT_FALLBACK = "Menlo"
FONT_SIZE = 12


# =============================================================================
# Color Schemes
# =============================================================================

# Light mode color scheme - optimized for readability
COLORS_LIGHT = {
    "foreground": (30, 30, 30),         # Near-black text
    "background": (255, 255, 255),       # White background
    "cursor": (0, 122, 255),             # Blue cursor
    "selection": (179, 215, 255),        # Light blue selection
    "bold": (0, 0, 0),                   # Black for bold text
    # ANSI colors (normal)
    "ansi_black": (0, 0, 0),
    "ansi_red": (194, 54, 33),
    "ansi_green": (37, 137, 58),
    "ansi_yellow": (173, 124, 36),
    "ansi_blue": (66, 133, 244),
    "ansi_magenta": (162, 73, 162),
    "ansi_cyan": (23, 162, 184),
    "ansi_white": (255, 255, 255),
}

# Dark mode color scheme - optimized for low-light environments
COLORS_DARK = {
    "foreground": (229, 229, 229),       # Light gray text
    "background": (30, 30, 30),          # Near-black background
    "cursor": (66, 133, 244),            # Blue cursor
    "selection": (62, 68, 81),           # Dark gray selection
    "bold": (255, 255, 255),             # White for bold text
    # ANSI colors (normal)
    "ansi_black": (0, 0, 0),
    "ansi_red": (255, 85, 85),
    "ansi_green": (80, 200, 120),
    "ansi_yellow": (255, 204, 0),
    "ansi_blue": (100, 149, 237),
    "ansi_magenta": (218, 112, 214),
    "ansi_cyan": (0, 206, 209),
    "ansi_white": (255, 255, 255),
}


# =============================================================================
# Screen Dimension Calculation
# =============================================================================


def calculate_screen_dimensions() -> tuple[int, int]:
    """
    Calculate terminal columns/rows to fill the screen.

    Uses system_profiler to get screen resolution and calculates appropriate
    terminal dimensions based on Menlo 12pt font cell size.

    Returns:
        Tuple of (columns, rows) for a screen-filling terminal window
    """
    try:
        # Use cached system_profiler to avoid repeated slow calls
        stdout = cached_system_profiler("SPDisplaysDataType")
        if stdout is None:
            logger.warning("system_profiler failed, using default dimensions")
            return (200, 60)

        # Parse resolution from output like "Resolution: 3024 x 1964"
        match = re.search(r"Resolution: (\d+) x (\d+)", stdout)
        if not match:
            logger.warning("Could not parse screen resolution, using defaults")
            return (200, 60)

        screen_w, screen_h = int(match.group(1)), int(match.group(2))

        # Detect Retina display (2x scale factor)
        scale = 2 if "Retina" in stdout else 1
        logical_w = screen_w // scale
        logical_h = screen_h // scale

        # Subtract margins for window chrome:
        # - ~20px for window borders
        # - ~100px for menu bar + dock + title bar
        usable_w = logical_w - 20
        usable_h = logical_h - 100

        # Menlo 12pt cell size (approximately)
        cell_w, cell_h = 7.2, 14.0

        cols = int(usable_w / cell_w)
        rows = int(usable_h / cell_h)

        logger.debug(
            f"Screen {screen_w}x{screen_h} (scale {scale}) -> "
            f"terminal {cols}x{rows}"
        )
        return (cols, rows)

    except Exception as e:
        logger.warning(f"Failed to calculate screen dimensions: {e}")
        return (200, 60)


# =============================================================================
# Appearance Mode Detection
# =============================================================================


async def detect_appearance_mode(connection: "ItermConnection") -> str:
    """
    Detect the current macOS appearance mode (light or dark).

    Uses iTerm2's effective theme to determine the system appearance.
    Falls back to 'dark' if detection fails.

    Args:
        connection: Active iTerm2 connection

    Returns:
        'light' or 'dark' based on system appearance
    """
    try:
        from iterm2.app import async_get_app

        # Get the app object to query effective theme
        app = await async_get_app(connection)
        if app is None:
            logger.warning("Could not get iTerm2 app, defaulting to dark")
            return "dark"

        # iTerm2's effective_theme returns a list of theme components
        # Common values include 'dark', 'light', 'automatic'
        theme = await app.async_get_variable("effectiveTheme")

        if theme and isinstance(theme, str):
            # effectiveTheme is a string like "dark" or "light"
            theme_lower = theme.lower()
            if "light" in theme_lower:
                return "light"
            elif "dark" in theme_lower:
                return "dark"

        # If theme is a list (some iTerm2 versions), check for dark indicators
        if theme and isinstance(theme, list):
            for component in theme:
                if isinstance(component, str) and "dark" in component.lower():
                    return "dark"
            return "light"

        logger.warning(f"Could not parse theme '{theme}', defaulting to dark")
        return "dark"

    except Exception as e:
        logger.warning(f"Failed to detect appearance mode: {e}, defaulting to dark")
        return "dark"


def get_colors_for_mode(mode: str) -> dict:
    """
    Get the color scheme dictionary for the specified appearance mode.

    Args:
        mode: Either 'light' or 'dark'

    Returns:
        Dictionary of color names to RGB tuples
    """
    if mode == "light":
        return COLORS_LIGHT.copy()
    return COLORS_DARK.copy()


# =============================================================================
# Profile Management
# =============================================================================


async def get_or_create_profile(connection: "ItermConnection") -> str:
    """
    Get or create the claude-team iTerm2 profile.

    Checks if a profile named 'claude-team' exists. If not, creates it
    with sensible defaults including font configuration and color scheme
    based on the current system appearance mode.

    Args:
        connection: Active iTerm2 connection

    Returns:
        The profile name (PROFILE_NAME constant)

    Note:
        This function creates a partial profile. The caller should
        use create_session_customizations() to apply per-session
        customizations like tab color and title.
    """
    from iterm2.profile import LocalWriteOnlyProfile as LWOProfile
    from iterm2.profile import PartialProfile

    # Get all existing profiles
    all_profiles = await PartialProfile.async_query(connection)
    profile_names = [p.name for p in all_profiles if p.name]

    # Check if our profile already exists
    if PROFILE_NAME in profile_names:
        logger.debug(f"Profile '{PROFILE_NAME}' already exists")
        return PROFILE_NAME

    logger.info(f"Creating new profile '{PROFILE_NAME}'")

    # Find a suitable source profile (prefer Default, then first available)
    source_profile = None
    for profile in all_profiles:
        if profile.name == "Default":
            source_profile = profile
            break

    if not source_profile and all_profiles:
        source_profile = all_profiles[0]

    if not source_profile:
        raise RuntimeError("No profiles found to use as template")

    # Create a new profile with our name
    # iTerm2 doesn't have a direct "create profile" API, so we use
    # LocalWriteOnlyProfile to define settings and create a session with it

    # Detect appearance mode for initial colors
    mode = await detect_appearance_mode(connection)
    colors = get_colors_for_mode(mode)

    # Create the profile settings
    profile = LWOProfile()
    profile.set_name(PROFILE_NAME)

    # Font configuration - use async_set methods for font
    # Try Source Code Pro first, fall back to Menlo
    try:
        profile.set_normal_font(f"{FONT_PRIMARY} {FONT_SIZE}")
    except Exception:
        logger.warning(f"Font '{FONT_PRIMARY}' not available, using '{FONT_FALLBACK}'")
        profile.set_normal_font(f"{FONT_FALLBACK} {FONT_SIZE}")

    # Apply color scheme
    _apply_colors_to_profile(profile, colors)

    # Window settings - use tabs, not fullscreen
    profile.set_use_tab_color(True)
    profile.set_smart_cursor_color(True)

    # The profile will be created implicitly when a session uses it.
    # For now, we need to ensure it exists by using create_profile_with_api
    # or by having a session use it.

    # Note: iTerm2's Python API doesn't have a direct "create profile from scratch" method.
    # The profile will be created when first used. For persistence, users should
    # save the profile via iTerm2's UI or use the JSON profile import feature.

    logger.info(
        f"Profile '{PROFILE_NAME}' configured with {FONT_PRIMARY} {FONT_SIZE}pt, "
        f"{mode} mode colors"
    )

    return PROFILE_NAME


async def apply_appearance_colors(
    profile: "LocalWriteOnlyProfile",
    connection: "ItermConnection",
) -> None:
    """
    Apply current appearance mode colors to a session profile.

    Detects the current macOS light/dark mode and applies the appropriate
    color scheme to the given profile. Call this when creating per-session
    customizations to ensure workers match the current system appearance.

    Args:
        profile: The LocalWriteOnlyProfile to modify
        connection: Active iTerm2 connection (needed for appearance detection)
    """
    mode = await detect_appearance_mode(connection)
    colors = get_colors_for_mode(mode)
    _apply_colors_to_profile(profile, colors)


def _apply_colors_to_profile(
    profile: "LocalWriteOnlyProfile",
    colors: dict,
) -> None:
    """
    Apply a color scheme to a profile.

    Helper function that sets all color-related profile properties
    from a color scheme dictionary.

    Args:
        profile: The profile to modify
        colors: Dictionary of color names to RGB tuples
    """
    from iterm2.color import Color

    def rgb_to_color(rgb: tuple[int, int, int]) -> "ItermColor":
        return Color(rgb[0], rgb[1], rgb[2])

    # Basic colors
    if "foreground" in colors:
        profile.set_foreground_color(rgb_to_color(colors["foreground"]))
    if "background" in colors:
        profile.set_background_color(rgb_to_color(colors["background"]))
    if "cursor" in colors:
        profile.set_cursor_color(rgb_to_color(colors["cursor"]))
    if "selection" in colors:
        profile.set_selection_color(rgb_to_color(colors["selection"]))
    if "bold" in colors:
        profile.set_bold_color(rgb_to_color(colors["bold"]))

    # ANSI colors
    ansi_color_setters = [
        ("ansi_black", profile.set_ansi_0_color),
        ("ansi_red", profile.set_ansi_1_color),
        ("ansi_green", profile.set_ansi_2_color),
        ("ansi_yellow", profile.set_ansi_3_color),
        ("ansi_blue", profile.set_ansi_4_color),
        ("ansi_magenta", profile.set_ansi_5_color),
        ("ansi_cyan", profile.set_ansi_6_color),
        ("ansi_white", profile.set_ansi_7_color),
    ]

    for color_name, setter in ansi_color_setters:
        if color_name in colors:
            setter(rgb_to_color(colors[color_name]))


