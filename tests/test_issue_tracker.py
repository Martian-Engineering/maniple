"""
Tests for issue tracker abstraction module.
"""

from claude_team_mcp.issue_tracker import (
    BEADS_BACKEND,
    PEBBLES_BACKEND,
    IssueTrackerBackend,
    detect_issue_tracker,
)


class TestIssueTrackerBackendProtocol:
    """Tests for IssueTrackerBackend protocol compliance."""

    def test_beads_backend_is_protocol(self):
        """Beads backend should satisfy IssueTrackerBackend protocol."""
        assert isinstance(BEADS_BACKEND, IssueTrackerBackend)

    def test_pebbles_backend_is_protocol(self):
        """Pebbles backend should satisfy IssueTrackerBackend protocol."""
        assert isinstance(PEBBLES_BACKEND, IssueTrackerBackend)


class TestBackendCommands:
    """Tests for backend command templates."""

    def test_beads_commands_include_expected_keys(self):
        """Beads commands should include all required templates."""
        expected_keys = {
            "list",
            "ready",
            "show",
            "update",
            "close",
            "create",
            "comment",
            "dep_add",
            "dep_tree",
        }
        assert set(BEADS_BACKEND.commands.keys()) == expected_keys

    def test_pebbles_commands_include_expected_keys(self):
        """Pebbles commands should include all required templates."""
        expected_keys = {
            "list",
            "ready",
            "show",
            "update",
            "close",
            "create",
            "comment",
            "dep_add",
            "dep_tree",
        }
        assert set(PEBBLES_BACKEND.commands.keys()) == expected_keys

    def test_beads_commands_start_with_cli(self):
        """Beads commands should start with the beads CLI prefix."""
        for command in BEADS_BACKEND.commands.values():
            assert command.startswith("bd --no-db")

    def test_pebbles_commands_start_with_cli(self):
        """Pebbles commands should start with the pebbles CLI prefix."""
        for command in PEBBLES_BACKEND.commands.values():
            assert command.startswith("pb ")


class TestDetectIssueTracker:
    """Tests for issue tracker detection."""

    def test_detects_beads(self, tmp_path):
        """Detection should return beads backend when .beads exists."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        (project_path / ".beads").mkdir()
        detected = detect_issue_tracker(str(project_path))
        assert detected == BEADS_BACKEND

    def test_detects_pebbles(self, tmp_path):
        """Detection should return pebbles backend when .pebbles exists."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()
        detected = detect_issue_tracker(str(project_path))
        assert detected == PEBBLES_BACKEND

    def test_detects_pebbles_when_both_markers_present(self, tmp_path, caplog):
        """Detection should prefer pebbles when both markers are present."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        (project_path / ".beads").mkdir()
        (project_path / ".pebbles").mkdir()
        detected = detect_issue_tracker(str(project_path))
        assert detected == PEBBLES_BACKEND
        assert "defaulting to pebbles" in caplog.text

    def test_returns_none_when_no_marker(self, tmp_path):
        """Detection should return None when no tracker marker exists."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        detected = detect_issue_tracker(str(project_path))
        assert detected is None
