"""
Tests for QMD indexing interval parsing and scheduler behavior.
"""

import asyncio
import logging
from datetime import timedelta

from claude_team_mcp.qmd_indexing import (
    DEFAULT_INDEX_INTERVAL,
    parse_index_interval,
    start_indexing_scheduler,
    stop_indexing_scheduler,
)


class TestParseIndexInterval:
    """Tests for parse_index_interval."""

    def test_parse_minutes(self):
        """Parses minute intervals correctly."""
        assert parse_index_interval("15m") == timedelta(minutes=15)

    def test_parse_hours(self):
        """Parses hour intervals correctly."""
        assert parse_index_interval("1h") == timedelta(hours=1)

    def test_parse_normalizes_case_and_whitespace(self):
        """Normalizes interval input before parsing."""
        assert parse_index_interval(" 6H ") == timedelta(hours=6)

    def test_parse_invalid_defaults(self):
        """Falls back to the default interval for invalid input."""
        assert parse_index_interval("1d") == parse_index_interval(DEFAULT_INDEX_INTERVAL)


class TestIndexingScheduler:
    """Tests for the background indexing scheduler."""

    def test_scheduler_runs_and_logs(self, caplog):
        """Runs indexing at least twice and logs start/completion."""
        calls = 0
        scheduler_logger = logging.getLogger("claude-team-mcp.qmd-indexing")

        async def pipeline():
            nonlocal calls
            calls += 1

        async def run_test():
            task = start_indexing_scheduler(
                pipeline,
                timedelta(milliseconds=20),
                logger=scheduler_logger,
            )
            await asyncio.sleep(0.07)
            await stop_indexing_scheduler(task, logger=scheduler_logger)

        caplog.set_level(logging.INFO, logger="claude-team-mcp.qmd-indexing")
        asyncio.run(run_test())

        assert calls >= 2
        assert "QMD indexing run started" in caplog.text
        assert "QMD indexing run completed" in caplog.text

    def test_scheduler_logs_errors_and_continues(self, caplog):
        """Logs failures without retrying immediately."""
        calls = 0
        scheduler_logger = logging.getLogger("claude-team-mcp.qmd-indexing")

        async def pipeline():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("boom")

        async def run_test():
            task = start_indexing_scheduler(
                pipeline,
                timedelta(milliseconds=20),
                logger=scheduler_logger,
            )
            await asyncio.sleep(0.07)
            await stop_indexing_scheduler(task, logger=scheduler_logger)

        caplog.set_level(logging.INFO, logger="claude-team-mcp.qmd-indexing")
        asyncio.run(run_test())

        assert calls >= 2
        assert "QMD indexing run failed" in caplog.text
