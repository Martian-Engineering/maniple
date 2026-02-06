"""
Dynamic tab color generation for iTerm2 sessions.

Generates visually distinct colors using the golden ratio for hue distribution,
ensuring each session gets a unique, easily distinguishable tab color.
"""

import colorsys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iterm2.color import Color as ItermColor


# Golden ratio conjugate (φ - 1), used for even hue distribution
GOLDEN_RATIO_CONJUGATE = 0.618033988749895

# Default saturation and lightness values for tab colors (HSL)
DEFAULT_SATURATION = 0.65  # 65%
DEFAULT_LIGHTNESS = 0.55   # 55%


def generate_tab_color(
    index: int,
    saturation: float = DEFAULT_SATURATION,
    lightness: float = DEFAULT_LIGHTNESS,
) -> "ItermColor":
    """
    Generate a distinct tab color for a given index.

    Uses the golden ratio to distribute hues evenly across the color wheel,
    ensuring that consecutively spawned sessions have visually distinct colors.
    The golden ratio approach avoids clustering that can occur with linear
    hue increments.

    Args:
        index: The session index (0-based). Each index produces a unique hue.
        saturation: HSL saturation value (0.0-1.0). Default 0.65 (65%).
        lightness: HSL lightness value (0.0-1.0). Default 0.55 (55%).

    Returns:
        iterm2.Color object ready to use with tab color APIs.

    Example:
        # First session gets a warm orange-red
        color0 = generate_tab_color(0)

        # Second session gets a contrasting blue-green
        color1 = generate_tab_color(1)

        # Colors remain visually distinct even for many sessions
        color10 = generate_tab_color(10)
    """
    from iterm2.color import Color

    # Calculate hue using golden ratio distribution
    # Multiply index by golden ratio conjugate and take fractional part
    # This distributes hues evenly across the color wheel
    hue = (index * GOLDEN_RATIO_CONJUGATE) % 1.0

    # Convert HSL to RGB (colorsys uses HLS ordering: hue, lightness, saturation)
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)

    # iterm2.Color expects integer RGB values 0-255
    return Color(
        r=int(r * 255),
        g=int(g * 255),
        b=int(b * 255),
    )


def hsl_to_rgb_tuple(
    hue: float,
    saturation: float = DEFAULT_SATURATION,
    lightness: float = DEFAULT_LIGHTNESS,
) -> tuple[int, int, int]:
    """
    Convert HSL values to RGB tuple (0-255 range).

    Utility function for cases where raw RGB values are needed
    instead of an iterm2.Color object.

    Args:
        hue: HSL hue value (0.0-1.0)
        saturation: HSL saturation value (0.0-1.0)
        lightness: HSL lightness value (0.0-1.0)

    Returns:
        Tuple of (red, green, blue) integers in 0-255 range.
    """
    # colorsys uses HLS (hue, lightness, saturation) ordering
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    return (int(r * 255), int(g * 255), int(b * 255))


def get_hue_for_index(index: int) -> float:
    """
    Get the hue value (0.0-1.0) for a given index.

    Useful when you need just the hue for custom color manipulation.

    Args:
        index: The session index (0-based)

    Returns:
        Hue value in range 0.0 to 1.0
    """
    return (index * GOLDEN_RATIO_CONJUGATE) % 1.0
