"""Tests for the QMD indexing pipeline."""

from __future__ import annotations

from pathlib import Path

from claude_team_mcp import qmd_indexing


class DummyResult:
    """Minimal subprocess result stub."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_configure_qmd_indexing_disabled(monkeypatch):
    """configure_qmd_indexing should no-op when disabled."""
    # Ensure the enable flag is unset.
    monkeypatch.delenv(qmd_indexing.ENV_QMD_ENABLED, raising=False)

    calls: list[list[str]] = []

    # Fail the test if subprocess is invoked.
    def fake_run(*args, **kwargs):
        calls.append(list(args[0]))
        return DummyResult()

    monkeypatch.setattr(qmd_indexing.subprocess, "run", fake_run)

    config = qmd_indexing.configure_qmd_indexing()

    assert config is None
    assert calls == []


def test_configure_qmd_indexing_bootstrap(monkeypatch, tmp_path):
    """configure_qmd_indexing should bootstrap collections and index."""
    # Enable indexing and provide a deterministic command path.
    monkeypatch.setenv(qmd_indexing.ENV_QMD_ENABLED, "1")
    monkeypatch.setenv(qmd_indexing.ENV_QMD_COMMAND, "qmd")
    monkeypatch.setattr(qmd_indexing.shutil, "which", lambda _: "/usr/bin/qmd")

    # Override collection paths to keep the test isolated.
    claude_path = tmp_path / "claude"
    codex_path = tmp_path / "codex"
    monkeypatch.setattr(qmd_indexing, "CLAUDE_COLLECTION_PATH", claude_path)
    monkeypatch.setattr(qmd_indexing, "CODEX_COLLECTION_PATH", codex_path)

    calls: list[list[str]] = []

    # Capture qmd subprocess calls.
    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return DummyResult()

    monkeypatch.setattr(qmd_indexing.subprocess, "run", fake_run)

    config = qmd_indexing.configure_qmd_indexing()

    assert config is not None
    assert calls == [
        ["qmd", "collection", "add", "ct-claude-sessions", "--path", str(claude_path)],
        ["qmd", "collection", "add", "ct-codex-sessions", "--path", str(codex_path)],
        ["qmd", "update", "ct-claude-sessions"],
        ["qmd", "embed", "ct-claude-sessions"],
        ["qmd", "update", "ct-codex-sessions"],
        ["qmd", "embed", "ct-codex-sessions"],
    ]


def test_run_indexing_pipeline_order(monkeypatch, tmp_path):
    """run_indexing_pipeline should export then update/embed per collection."""
    from datetime import timedelta
    # Provide a fully-specified config to avoid env lookups.
    config = qmd_indexing.QmdIndexingConfig(
        qmd_command="qmd",
        claude=qmd_indexing.QmdCollection("ct-claude-sessions", tmp_path / "claude"),
        codex=qmd_indexing.QmdCollection("ct-codex-sessions", tmp_path / "codex"),
        interval=timedelta(hours=1),
        interval_label="1h",
    )

    events: list[tuple[str, object]] = []

    # Record export calls so ordering is observable.
    def fake_claude_export(path: Path):
        events.append(("export-claude", str(path)))
        return []

    def fake_codex_export(path: Path):
        events.append(("export-codex", str(path)))
        return []

    # Record qmd commands for ordering verification.
    def fake_run(cmd, **kwargs):
        events.append(("qmd", list(cmd)))
        return DummyResult()

    monkeypatch.setattr(qmd_indexing, "export_claude_sessions", fake_claude_export)
    monkeypatch.setattr(qmd_indexing, "export_codex_sessions", fake_codex_export)
    monkeypatch.setattr(qmd_indexing.subprocess, "run", fake_run)

    qmd_indexing.run_indexing_pipeline(config)

    assert events == [
        ("export-claude", str(config.claude.path)),
        ("qmd", ["qmd", "update", "ct-claude-sessions"]),
        ("qmd", ["qmd", "embed", "ct-claude-sessions"]),
        ("export-codex", str(config.codex.path)),
        ("qmd", ["qmd", "update", "ct-codex-sessions"]),
        ("qmd", ["qmd", "embed", "ct-codex-sessions"]),
    ]


def test_run_indexing_pipeline_logs_qmd_errors(monkeypatch, tmp_path):
    """run_indexing_pipeline should swallow qmd failures."""
    from datetime import timedelta
    # Use a config that avoids environment-based configuration.
    config = qmd_indexing.QmdIndexingConfig(
        qmd_command="qmd",
        claude=qmd_indexing.QmdCollection("ct-claude-sessions", tmp_path / "claude"),
        codex=qmd_indexing.QmdCollection("ct-codex-sessions", tmp_path / "codex"),
        interval=timedelta(hours=1),
        interval_label="1h",
    )

    # Skip export work and force qmd failures.
    monkeypatch.setattr(qmd_indexing, "export_claude_sessions", lambda _: [])
    monkeypatch.setattr(qmd_indexing, "export_codex_sessions", lambda _: [])
    monkeypatch.setattr(
        qmd_indexing.subprocess,
        "run",
        lambda *_args, **_kwargs: DummyResult(returncode=1, stderr="boom"),
    )

    qmd_indexing.run_indexing_pipeline(config)
