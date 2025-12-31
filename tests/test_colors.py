"""Tests for the colors module."""

import pytest
from unittest.mock import MagicMock, patch
import colorsys

# Import the pure functions that don't need iterm2
from claude_team_mcp.colors import (
    GOLDEN_RATIO_CONJUGATE,
    DEFAULT_SATURATION,
    DEFAULT_LIGHTNESS,
    get_hue_for_index,
    hsl_to_rgb_tuple,
)


class TestGetHueForIndex:
    """Tests for the get_hue_for_index function."""

    def test_index_zero_returns_zero(self):
        """Index 0 should return hue of 0."""
        assert get_hue_for_index(0) == 0.0

    def test_index_one_returns_golden_ratio(self):
        """Index 1 should return the golden ratio conjugate."""
        expected = GOLDEN_RATIO_CONJUGATE
        assert abs(get_hue_for_index(1) - expected) < 1e-10

    def test_consecutive_indices_produce_distinct_hues(self):
        """Consecutive indices should produce visually distinct hues."""
        hues = [get_hue_for_index(i) for i in range(10)]
        # All hues should be unique
        assert len(set(hues)) == 10

        # Adjacent hues should differ by at least 0.1 (36 degrees) for visibility
        for i in range(len(hues) - 1):
            diff = abs(hues[i] - hues[i + 1])
            # Account for wraparound
            diff = min(diff, 1.0 - diff)
            assert diff > 0.1, f"Hues {hues[i]} and {hues[i+1]} are too similar"

    def test_hue_wraps_correctly(self):
        """Hue values should always be in [0, 1) range."""
        for i in range(100):
            hue = get_hue_for_index(i)
            assert 0.0 <= hue < 1.0, f"Hue {hue} for index {i} is out of range"

    def test_large_indices_still_produce_valid_hues(self):
        """Large indices should still produce valid hue values."""
        hue = get_hue_for_index(1000)
        assert 0.0 <= hue < 1.0


class TestHslToRgbTuple:
    """Tests for the hsl_to_rgb_tuple function."""

    def test_red_hue(self):
        """Hue 0 (red) should produce a reddish color."""
        r, g, b = hsl_to_rgb_tuple(0.0)
        assert r > g and r > b, "Red should be dominant for hue 0"

    def test_green_hue(self):
        """Hue 0.333 (green) should produce a greenish color."""
        r, g, b = hsl_to_rgb_tuple(0.333)
        assert g > r and g > b, "Green should be dominant for hue ~0.33"

    def test_blue_hue(self):
        """Hue 0.666 (blue) should produce a bluish color."""
        r, g, b = hsl_to_rgb_tuple(0.666)
        assert b > r and b > g, "Blue should be dominant for hue ~0.66"

    def test_rgb_values_in_valid_range(self):
        """RGB values should be integers in 0-255 range."""
        for hue in [0.0, 0.25, 0.5, 0.75]:
            r, g, b = hsl_to_rgb_tuple(hue)
            for value in (r, g, b):
                assert isinstance(value, int), "RGB values should be integers"
                assert 0 <= value <= 255, f"RGB value {value} out of range"

    def test_custom_saturation_and_lightness(self):
        """Custom saturation and lightness should affect output."""
        # Low saturation should produce more gray-ish colors
        low_sat = hsl_to_rgb_tuple(0.0, saturation=0.1, lightness=0.5)
        high_sat = hsl_to_rgb_tuple(0.0, saturation=0.9, lightness=0.5)

        # High saturation red should be more different from gray
        assert high_sat[0] - high_sat[1] > low_sat[0] - low_sat[1]


class TestGenerateTabColor:
    """Tests for the generate_tab_color function."""

    def test_returns_iterm2_color(self):
        """generate_tab_color should return an iterm2.Color object."""
        # Mock the iterm2 module and its color submodule
        mock_color_instance = MagicMock()
        mock_color_class = MagicMock(return_value=mock_color_instance)
        mock_color_module = MagicMock()
        mock_color_module.Color = mock_color_class
        mock_iterm2 = MagicMock()
        mock_iterm2.color = mock_color_module

        # Must patch both 'iterm2' and 'iterm2.color' for submodule imports
        with patch.dict('sys.modules', {
            'iterm2': mock_iterm2,
            'iterm2.color': mock_color_module,
        }):
            from claude_team_mcp.colors import generate_tab_color
            result = generate_tab_color(0)

            # Verify Color was called with RGB values
            mock_color_class.assert_called_once()
            call_kwargs = mock_color_class.call_args[1]
            assert 'r' in call_kwargs
            assert 'g' in call_kwargs
            assert 'b' in call_kwargs

    def test_different_indices_produce_different_colors(self):
        """Different indices should produce different colors."""
        mock_colors = []

        def capture_color(**kwargs):
            color = MagicMock()
            color.rgb = (kwargs['r'], kwargs['g'], kwargs['b'])
            mock_colors.append(color)
            return color

        mock_color_class = MagicMock(side_effect=capture_color)
        mock_color_module = MagicMock()
        mock_color_module.Color = mock_color_class
        mock_iterm2 = MagicMock()
        mock_iterm2.color = mock_color_module

        # Must patch both 'iterm2' and 'iterm2.color' for submodule imports
        with patch.dict('sys.modules', {
            'iterm2': mock_iterm2,
            'iterm2.color': mock_color_module,
        }):
            from claude_team_mcp.colors import generate_tab_color
            for i in range(5):
                generate_tab_color(i)

        # All colors should be unique
        rgb_values = [c.rgb for c in mock_colors]
        assert len(set(rgb_values)) == 5, "All generated colors should be unique"


class TestConstants:
    """Tests for module constants."""

    def test_golden_ratio_value(self):
        """Golden ratio conjugate should be approximately 0.618."""
        assert abs(GOLDEN_RATIO_CONJUGATE - 0.618033988749895) < 1e-15

    def test_default_saturation(self):
        """Default saturation should be 65%."""
        assert DEFAULT_SATURATION == 0.65

    def test_default_lightness(self):
        """Default lightness should be 55%."""
        assert DEFAULT_LIGHTNESS == 0.55
