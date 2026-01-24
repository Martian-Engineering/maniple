"""Tests for Codex JSONL markdown export helpers."""

import os
import time
from pathlib import Path

from claude_team_mcp.codex_export import (
    CodexSessionMeta,
    export_codex_session_markdown,
    format_codex_markdown,
    parse_codex_session_meta,
)


def _write_codex_jsonl(path: Path) -> None:
    # Write a minimal Codex JSONL session for tests.
    lines = [
        '{"type":"session_meta","payload":{"id":"session_123","cwd":"/tmp/project","timestamp":"2026-01-23T12:00:00Z"}}',
        '{"type":"event_msg","payload":{"type":"user_message","id":"u1","text":"Hello"}}',
        '{"type":"event_msg","payload":{"type":"agent_message","id":"a1","text":"Hi there"}}',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_parse_codex_session_meta_reads_payload(tmp_path: Path) -> None:
    """Should read session_meta payload fields from JSONL."""
    # Arrange JSONL fixture with session_meta payload.
    jsonl_path = tmp_path / "session.jsonl"
    _write_codex_jsonl(jsonl_path)

    # Act on the JSONL file.
    meta = parse_codex_session_meta(jsonl_path)

    # Assert metadata fields match the payload.
    assert meta == CodexSessionMeta(
        session_id="session_123",
        cwd="/tmp/project",
        timestamp="2026-01-23T12:00:00Z",
    )


def test_format_codex_markdown_contains_headers() -> None:
    """Should include normalized headers in the markdown output."""
    # Arrange metadata for formatting.
    meta = CodexSessionMeta(
        session_id="session_123",
        cwd="/tmp/project",
        timestamp="2026-01-23T12:00:00Z",
    )
    markdown = format_codex_markdown(meta, [])

    # Assert YAML-frontmatter format with key: value pairs.
    assert "Session ID: session_123" in markdown
    assert "Working Directory: /tmp/project" in markdown
    assert "Date: 2026-01-23T12:00:00Z" in markdown
    assert "Agent: codex" in markdown


def test_export_codex_session_markdown_writes_file(tmp_path: Path) -> None:
    """Should export JSONL to a markdown file named after session id."""
    # Arrange JSONL input and output directory.
    jsonl_path = tmp_path / "session.jsonl"
    _write_codex_jsonl(jsonl_path)
    output_dir = tmp_path / "index" / "codex"

    # Act to export the markdown.
    output_path = export_codex_session_markdown(jsonl_path, output_dir=output_dir)

    # Assert the output file name and content.
    assert output_path == output_dir / "session_123.md"
    assert output_path is not None
    content = output_path.read_text(encoding="utf-8")
    assert "## User" in content
    assert "Hello" in content
    assert "## Assistant" in content
    assert "Hi there" in content


def test_export_codex_session_markdown_skips_newer_output(tmp_path: Path) -> None:
    """Should skip export when output markdown is newer than JSONL."""
    # Arrange JSONL input and a pre-existing, newer markdown export.
    jsonl_path = tmp_path / "session.jsonl"
    _write_codex_jsonl(jsonl_path)
    output_dir = tmp_path / "index" / "codex"
    output_dir.mkdir(parents=True)
    output_path = output_dir / "session_123.md"
    output_path.write_text("existing", encoding="utf-8")

    now = time.time()
    os.utime(jsonl_path, (now, now))
    os.utime(output_path, (now + 10, now + 10))

    # Act to export (should skip due to newer output).
    result = export_codex_session_markdown(jsonl_path, output_dir=output_dir)

    # Assert the existing markdown was preserved.
    assert result == output_path
    assert output_path.read_text(encoding="utf-8") == "existing"
