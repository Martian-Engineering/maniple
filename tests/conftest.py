"""Shared pytest fixtures for test isolation."""

from pathlib import Path

import pytest

from maniple_mcp import config as config_module


@pytest.fixture(autouse=True)
def isolate_config_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Point config path to a temp file so user config doesn't affect tests."""
    if "test_config_cli.py" in request.node.nodeid:
        return
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
