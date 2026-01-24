"""Tests for claude_export module."""

import json
import os
from pathlib import Path

from claude_team_mcp.claude_export import export_project_sessions
from claude_team_mcp.session_state import get_project_slug


class TestClaudeExport:
    """Coverage for Claude session Markdown export."""

    def test_exports_markdown_with_headers_and_messages(self, tmp_path: Path) -> None:
        """Exports a JSONL file into a stable Markdown format."""
        project_path = tmp_path / "demo-project"
        project_path.mkdir()
        (project_path / ".git").mkdir()

        source_root = tmp_path / "claude-projects"
        project_dir = source_root / get_project_slug(str(project_path))
        project_dir.mkdir(parents=True)

        jsonl_path = project_dir / "session-123.jsonl"
        entries = [
            {
                "type": "user",
                "sessionId": "session-123",
                "uuid": "user-1",
                "parentUuid": None,
                "message": {"role": "user", "content": "Hello from user"},
                "timestamp": "2025-01-01T12:00:00Z",
                "cwd": str(project_path),
            },
            {
                "type": "assistant",
                "sessionId": "session-123",
                "uuid": "assistant-1",
                "parentUuid": "user-1",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello from assistant"}],
                },
                "timestamp": "2025-01-01T12:00:01Z",
                "cwd": str(project_path),
            },
        ]
        jsonl_path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")

        output_root = tmp_path / "output"
        exported = export_project_sessions(
            str(project_path),
            output_root=output_root,
            source_root=source_root,
        )

        output_path = output_root / "session-123.md"
        assert output_path in exported
        content = output_path.read_text()

        assert "Session ID: session-123" in content
        assert f"Working Directory: {project_path}" in content
        assert "Date: 2025-01-01T12:00:00+00:00" in content
        assert "Agent: claude" in content
        assert f"Repo Root: {project_path}" in content
        assert "## User" in content
        assert "Hello from user" in content
        assert "## Assistant" in content
        assert "Hello from assistant" in content

    def test_skips_export_when_output_newer(self, tmp_path: Path) -> None:
        """Skips export when the Markdown file is newer than JSONL."""
        project_path = tmp_path / "demo-project"
        project_path.mkdir()

        source_root = tmp_path / "claude-projects"
        project_dir = source_root / get_project_slug(str(project_path))
        project_dir.mkdir(parents=True)

        jsonl_path = project_dir / "session-456.jsonl"
        entries = [
            {
                "type": "user",
                "sessionId": "session-456",
                "uuid": "user-1",
                "parentUuid": None,
                "message": {"role": "user", "content": "Hello"},
                "timestamp": "2025-01-02T12:00:00Z",
                "cwd": str(project_path),
            }
        ]
        jsonl_path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")

        output_root = tmp_path / "output"
        output_root.mkdir()
        output_path = output_root / "session-456.md"
        output_path.write_text("stale")

        jsonl_mtime = jsonl_path.stat().st_mtime
        newer_time = jsonl_mtime + 10
        os.utime(output_path, (newer_time, newer_time))

        exported = export_project_sessions(
            str(project_path),
            output_root=output_root,
            source_root=source_root,
        )

        assert output_path not in exported
        assert output_path.read_text() == "stale"
