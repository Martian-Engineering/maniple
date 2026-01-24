"""Tests for smart_fork helpers."""

from types import SimpleNamespace

from claude_team_mcp.tools import smart_fork


def test_parse_markdown_headers():
    text = """
    Session ID: abc123
    Working Directory: /Users/test/project
    Date: 2026-01-23
    Agent: claude
    """
    headers = smart_fork._parse_markdown_headers(text)
    assert headers["session_id"] == "abc123"
    assert headers["working_directory"] == "/Users/test/project"
    assert headers["date"] == "2026-01-23"
    assert headers["agent_type"] == "claude"


def test_build_candidates_reads_markdown(tmp_path):
    markdown = tmp_path / "session.md"
    markdown.write_text(
        "Session ID: session-1\n"
        "Working Directory: /tmp/project\n"
        "Date: 2026-01-23\n"
    )
    raw_results = [
        {
            "path": str(markdown),
            "score": 0.9,
            "snippet": "Session ID: session-1",
        }
    ]

    candidates = smart_fork._build_candidates(raw_results, limit=5, agent_type="claude")

    assert len(candidates) == 1
    assert candidates[0]["session_id"] == "session-1"
    assert candidates[0]["working_directory"] == "/tmp/project"
    assert candidates[0]["score"] == 0.9


def test_build_candidates_filters_agent(tmp_path):
    markdown = tmp_path / "session.md"
    markdown.write_text(
        "Session ID: session-2\n"
        "Working Directory: /tmp/project\n"
        "Agent: codex\n"
    )
    raw_results = [{"path": str(markdown)}]

    candidates = smart_fork._build_candidates(raw_results, limit=5, agent_type="claude")

    assert candidates == []


def test_run_qmd_search_fallback(monkeypatch):
    def fake_run(args):
        command = args[1]
        if command == "query":
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        return SimpleNamespace(
            returncode=0,
            stdout='{"results": [{"path": "/tmp/session.md"}]}',
            stderr="",
        )

    monkeypatch.setattr(smart_fork, "_run_qmd_command", fake_run)

    result = smart_fork._run_qmd_search("intent", "collection")

    assert result.command == "vsearch"
    assert result.fallback_used is True
    assert "boom" in (result.qmd_error or "")
