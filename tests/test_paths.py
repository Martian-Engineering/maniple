"""Tests for Maniple path resolution and legacy migrations."""

from __future__ import annotations

from pathlib import Path

from maniple.paths import DATA_DIRNAME, LEGACY_DATA_DIRNAME, resolve_data_dir


class TestResolveDataDir:
    """Tests for resolve_data_dir legacy migration behavior."""

    def test_migrates_legacy_dir_when_new_missing(self, tmp_path: Path) -> None:
        """Legacy ~/.claude-team should be moved to ~/.maniple."""
        home = tmp_path / "home"
        legacy_dir = home / LEGACY_DATA_DIRNAME
        new_dir = home / DATA_DIRNAME
        legacy_dir.mkdir(parents=True)

        marker = legacy_dir / "config.json"
        marker.write_text("{}", encoding="utf-8")

        resolved = resolve_data_dir(home=home)
        assert resolved == new_dir
        assert not legacy_dir.exists()
        assert (new_dir / "config.json").exists()
        assert (new_dir / "config.json").read_text(encoding="utf-8") == "{}"

    def test_prefers_new_dir_when_present(self, tmp_path: Path) -> None:
        """If ~/.maniple exists, it should be returned even if legacy exists."""
        home = tmp_path / "home"
        legacy_dir = home / LEGACY_DATA_DIRNAME
        new_dir = home / DATA_DIRNAME
        legacy_dir.mkdir(parents=True)
        new_dir.mkdir(parents=True)

        resolved = resolve_data_dir(home=home)
        assert resolved == new_dir
        assert legacy_dir.exists()

    def test_returns_new_dir_path_when_none_exist(self, tmp_path: Path) -> None:
        """When neither directory exists, return ~/.maniple without creating it."""
        home = tmp_path / "home"
        resolved = resolve_data_dir(home=home)
        assert resolved == home / DATA_DIRNAME
        assert not resolved.exists()
