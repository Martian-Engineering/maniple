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

    # agent_type=None means no filtering (for "both" mode)
    candidates = smart_fork._build_candidates(raw_results, limit=5, agent_type=None)

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

    # Filter for claude should exclude codex sessions
    candidates = smart_fork._build_candidates(raw_results, limit=5, agent_type="claude")
    assert candidates == []

    # Filter for codex should include it
    candidates = smart_fork._build_candidates(raw_results, limit=5, agent_type="codex")
    assert len(candidates) == 1
    assert candidates[0]["agent_type"] == "codex"

    # No filter (both) should include all
    candidates = smart_fork._build_candidates(raw_results, limit=5, agent_type=None)
    assert len(candidates) == 1


def test_build_candidates_filters_project_path(tmp_path):
    markdown = tmp_path / "session.md"
    markdown.write_text(
        "Session ID: session-3\n"
        "Working Directory: /tmp/project/subdir\n"
    )
    raw_results = [{"path": str(markdown)}]

    candidates = smart_fork._build_candidates(
        raw_results,
        limit=5,
        agent_type=None,
    )

    assert len(candidates) == 1
    assert candidates[0]["working_directory"] == "/tmp/project/subdir"


def test_build_candidates_filters_repo_root(tmp_path):
    markdown = tmp_path / "session.md"
    markdown.write_text(
        "Session ID: session-4\n"
        "Working Directory: /tmp/project\n"
        "Repo Root: /tmp/project\n"
    )
    raw_results = [{"path": str(markdown)}]

    candidates = smart_fork._build_candidates(
        raw_results,
        limit=5,
        agent_type=None,
    )

    assert len(candidates) == 1
    assert candidates[0]["session_id"] == "session-4"


def test_build_candidates_sorts_by_score(tmp_path):
    """Results from multiple collections should be sorted by score descending."""
    md1 = tmp_path / "session1.md"
    md1.write_text(
        "Session ID: session-low\n"
        "Working Directory: /tmp/project\n"
        "Agent: claude\n"
    )
    md2 = tmp_path / "session2.md"
    md2.write_text(
        "Session ID: session-high\n"
        "Working Directory: /tmp/project\n"
        "Agent: codex\n"
    )
    md3 = tmp_path / "session3.md"
    md3.write_text(
        "Session ID: session-mid\n"
        "Working Directory: /tmp/project\n"
        "Agent: claude\n"
    )
    raw_results = [
        {"path": str(md1), "score": 0.3},
        {"path": str(md2), "score": 0.9},
        {"path": str(md3), "score": 0.6},
    ]

    # No filter (both) should sort by score
    candidates = smart_fork._build_candidates(raw_results, limit=5, agent_type=None)

    assert len(candidates) == 3
    assert candidates[0]["session_id"] == "session-high"
    assert candidates[0]["score"] == 0.9
    assert candidates[1]["session_id"] == "session-mid"
    assert candidates[1]["score"] == 0.6
    assert candidates[2]["session_id"] == "session-low"
    assert candidates[2]["score"] == 0.3


def test_build_candidates_includes_agent_type(tmp_path):
    """Candidates should include agent_type metadata when available."""
    markdown = tmp_path / "session.md"
    markdown.write_text(
        "Session ID: session-5\n"
        "Working Directory: /tmp/project\n"
        "Agent: codex\n"
    )
    raw_results = [{"path": str(markdown)}]

    candidates = smart_fork._build_candidates(raw_results, limit=5, agent_type=None)

    assert len(candidates) == 1
    assert candidates[0]["agent_type"] == "codex"


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


def test_run_qmd_search_fallback_chain(monkeypatch):
    def fake_run(args):
        command = args[1]
        if command in ("query", "vsearch"):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        return SimpleNamespace(
            returncode=0,
            stdout='{"results": [{"path": "/tmp/session.md"}]}',
            stderr="",
        )

    monkeypatch.setattr(smart_fork, "_run_qmd_command", fake_run)

    result = smart_fork._run_qmd_search("intent", "collection")

    assert result.command == "search"
    assert result.fallback_used is True
    assert result.results == [{"path": "/tmp/session.md"}]
