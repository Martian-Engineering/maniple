"""Tests for QMD indexing gating."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from claude_team_mcp import qmd_indexing


class _Server:
    """Test double for server object."""

    def __init__(self) -> None:
        self.qmd_indexing_enabled = False
        self.qmd_indexing_errors: list[str] = []


def test_configure_qmd_indexing_skips_non_http(monkeypatch):
    """Indexing should be skipped for stdio transport."""
    monkeypatch.setenv(qmd_indexing.ENV_QMD_INDEXING, "1")
    server = _Server()

    status = qmd_indexing.configure_qmd_indexing(server, transport="stdio")

    assert status.enabled is False
    assert server.qmd_indexing_enabled is False


def test_configure_qmd_indexing_disabled_by_env(monkeypatch):
    """Disabled env flag should prevent indexing in HTTP mode."""
    monkeypatch.setenv(qmd_indexing.ENV_QMD_INDEXING, "0")
    server = _Server()

    status = qmd_indexing.configure_qmd_indexing(server, transport="streamable-http")

    assert status.enabled is False
    assert server.qmd_indexing_enabled is False


def test_configure_qmd_indexing_missing_qmd(monkeypatch, tmp_path):
    """Missing qmd should disable indexing and record errors."""
    monkeypatch.setenv(qmd_indexing.ENV_QMD_INDEXING, "true")
    monkeypatch.setattr(qmd_indexing, "_claude_projects_dir", lambda: tmp_path / "claude")
    monkeypatch.setattr(qmd_indexing, "_codex_sessions_dir", lambda: tmp_path / "codex")
    monkeypatch.setattr(qmd_indexing, "_index_root", lambda: tmp_path / "index")
    monkeypatch.setattr(qmd_indexing.shutil, "which", lambda _: None)

    (tmp_path / "claude").mkdir()
    (tmp_path / "codex").mkdir()

    server = _Server()
    status = qmd_indexing.configure_qmd_indexing(server, transport="streamable-http")

    assert status.enabled is False
    assert server.qmd_indexing_enabled is False
    assert "qmd not found" in " ".join(status.errors)


def test_configure_qmd_indexing_success(monkeypatch, tmp_path):
    """Successful prerequisites should enable indexing."""
    monkeypatch.setenv(qmd_indexing.ENV_QMD_INDEXING, "true")
    monkeypatch.setattr(qmd_indexing, "_claude_projects_dir", lambda: tmp_path / "claude")
    monkeypatch.setattr(qmd_indexing, "_codex_sessions_dir", lambda: tmp_path / "codex")
    monkeypatch.setattr(qmd_indexing, "_index_root", lambda: tmp_path / "index")
    monkeypatch.setattr(qmd_indexing.shutil, "which", lambda _: "/usr/bin/qmd")
    monkeypatch.setattr(
        qmd_indexing,
        "_run_qmd_command",
        lambda _: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    (tmp_path / "claude").mkdir()
    (tmp_path / "codex").mkdir()

    server = _Server()
    status = qmd_indexing.configure_qmd_indexing(server, transport="streamable-http")

    assert status.enabled is True
    assert server.qmd_indexing_enabled is True
    assert status.errors == ()


def test_parse_env_flag_unknown_value_defaults():
    """Unknown values should return the default."""
    assert qmd_indexing._parse_env_flag("maybe", default=True) is True
    assert qmd_indexing._parse_env_flag("maybe", default=False) is False
