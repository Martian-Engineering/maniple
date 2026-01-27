"""Tests for claude_team.idle_detection module."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from claude_team.idle_detection import (
    Worker,
    check_file_idle,
    detect_worker_idle,
    get_claude_jsonl_path,
    get_project_slug,
)


class TestProjectSlug:
    """Tests for project slug helpers."""

    def test_get_project_slug_replaces_slashes_and_dots(self):
        """get_project_slug should replace '/' and '.' with '-' characters."""
        assert get_project_slug("/Users/josh/code") == "-Users-josh-code"
        assert get_project_slug("/path/.worktrees/foo") == "-path--worktrees-foo"


class TestClaudeJsonlPath:
    """Tests for Claude JSONL path construction."""

    def test_get_claude_jsonl_path_builds_expected_path(self, tmp_path, monkeypatch):
        """Should build JSONL path using Claude project slug format."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        worker = Worker(project_path="/Users/josh/code", claude_session_id="abc123", agent_type="claude")
        expected = tmp_path / ".claude" / "projects" / "-Users-josh-code" / "abc123.jsonl"
        assert get_claude_jsonl_path(worker) == expected

    def test_get_claude_jsonl_path_missing_fields(self):
        """Should return None when project_path or session_id missing."""
        worker = Worker(project_path="", claude_session_id=None, agent_type="claude")
        assert get_claude_jsonl_path(worker) is None


class TestCheckFileIdle:
    """Tests for file mtime checks."""

    def test_check_file_idle_true_when_old(self, tmp_path):
        """Should report idle when file age exceeds threshold."""
        path = tmp_path / "sample.jsonl"
        path.write_text("data")
        os.utime(path, (time.time() - 10, time.time() - 10))

        is_idle, age = check_file_idle(path, threshold_seconds=5)
        assert is_idle is True
        assert age >= 5

    def test_check_file_idle_false_when_recent(self, tmp_path):
        """Should report not idle when file is recent."""
        path = tmp_path / "sample.jsonl"
        path.write_text("data")
        os.utime(path, (time.time(), time.time()))

        is_idle, age = check_file_idle(path, threshold_seconds=5)
        assert is_idle is False
        assert age >= 0


class TestDetectWorkerIdleClaude:
    """Tests for detect_worker_idle with Claude workers."""

    def test_claude_idle_from_jsonl_mtime(self, tmp_path, monkeypatch):
        """Should detect idle based on JSONL mtime for Claude workers."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        worker = Worker(project_path="/Users/josh/code", claude_session_id="abc123", agent_type="claude")
        jsonl_path = get_claude_jsonl_path(worker)
        assert jsonl_path is not None
        jsonl_path.parent.mkdir(parents=True)
        jsonl_path.write_text("data")

        os.utime(jsonl_path, (time.time() - 10, time.time() - 10))
        is_idle, reason = detect_worker_idle(worker, idle_threshold_seconds=5)
        assert is_idle is True
        assert reason and reason.startswith("jsonl_mtime:")

    def test_claude_not_idle_when_jsonl_recent(self, tmp_path, monkeypatch):
        """Should report active when JSONL mtime is recent."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        worker = Worker(project_path="/Users/josh/code", claude_session_id="abc123", agent_type="claude")
        jsonl_path = get_claude_jsonl_path(worker)
        assert jsonl_path is not None
        jsonl_path.parent.mkdir(parents=True)
        jsonl_path.write_text("data")

        os.utime(jsonl_path, (time.time(), time.time()))
        is_idle, reason = detect_worker_idle(worker, idle_threshold_seconds=5)
        assert is_idle is False
        assert reason is None

    def test_claude_idle_from_message_count(self):
        """Should use message_count when JSONL missing."""
        now = time.time()
        worker = Worker(
            project_path="/Users/josh/code",
            claude_session_id="abc123",
            agent_type="claude",
            message_count=10,
            last_message_count=10,
            last_message_timestamp=now - 400,
        )

        is_idle, reason = detect_worker_idle(worker, idle_threshold_seconds=300)
        assert is_idle is True
        assert reason and reason.startswith("message_count_stalled:")

    def test_claude_preserves_state_when_no_signal(self):
        """Should return existing state when no idle signal is available."""
        worker = Worker(project_path="/Users/josh/code", claude_session_id="abc123", agent_type="claude")
        worker.is_idle = True

        is_idle, reason = detect_worker_idle(worker, idle_threshold_seconds=300)
        assert is_idle is True
        assert reason is None


class TestDetectWorkerIdleCodex:
    """Tests for detect_worker_idle with Codex workers."""

    def test_codex_idle_from_output_mtime(self, tmp_path):
        """Should detect idle based on output file mtime for Codex workers."""
        output_path = tmp_path / "output.txt"
        output_path.write_text("done")
        os.utime(output_path, (time.time() - 10, time.time() - 10))

        worker = Worker(project_path="/Users/josh/code", claude_session_id=None, agent_type="codex")
        worker.output_path = output_path

        is_idle, reason = detect_worker_idle(worker, idle_threshold_seconds=5)
        assert is_idle is True
        assert reason and reason.startswith("output_mtime:")

    def test_codex_idle_when_process_exited(self, monkeypatch):
        """Should detect idle when Codex process no longer exists."""
        worker = Worker(project_path="/Users/josh/code", claude_session_id=None, agent_type="codex", pid=1234)

        def _raise(*_args, **_kwargs):
            raise OSError("no such process")

        monkeypatch.setattr(os, "kill", _raise)

        is_idle, reason = detect_worker_idle(worker, idle_threshold_seconds=300)
        assert is_idle is True
        assert reason == "process_exited"

    def test_codex_idle_when_process_sleeping(self, monkeypatch):
        """Should detect idle when Codex process is sleeping."""
        worker = Worker(project_path="/Users/josh/code", claude_session_id=None, agent_type="codex", pid=4321)

        monkeypatch.setattr(os, "kill", lambda *_args, **_kwargs: None)

        class Result:
            stdout = "S"

        monkeypatch.setattr(
            "claude_team.idle_detection.subprocess.run",
            lambda *_args, **_kwargs: Result(),
        )

        is_idle, reason = detect_worker_idle(worker, idle_threshold_seconds=300)
        assert is_idle is True
        assert reason == "process_sleeping"

    def test_codex_preserves_state_when_no_signal(self):
        """Should return existing state when no Codex signal is available."""
        worker = Worker(project_path="/Users/josh/code", claude_session_id=None, agent_type="codex")
        worker.is_idle = False

        is_idle, reason = detect_worker_idle(worker, idle_threshold_seconds=300)
        assert is_idle is False
        assert reason is None
