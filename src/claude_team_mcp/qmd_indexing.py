"""
QMD indexing configuration and background scheduling.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Awaitable, Callable, Mapping

INDEX_CRON_ENV = "CLAUDE_TEAM_INDEX_CRON"
DEFAULT_INDEX_INTERVAL = "1h"

_INTERVAL_PATTERN = re.compile(r"^(?P<count>\d+)(?P<unit>[mh])$")

_logger = logging.getLogger("claude-team-mcp.qmd-indexing")


@dataclass(frozen=True)
class IndexingConfig:
    """Configuration for background QMD indexing."""

    interval: timedelta
    interval_label: str


def parse_index_interval(value: str) -> timedelta:
    """
    Parse an interval string like "15m" or "1h" into a timedelta.

    Args:
        value: Interval string using minutes (m) or hours (h).

    Returns:
        A timedelta representing the interval.

    Raises:
        ValueError: If the interval format is invalid.
    """
    # Normalize input to keep parsing strict but user-friendly.
    normalized = value.strip().lower()
    match = _INTERVAL_PATTERN.match(normalized)
    if not match:
        raise ValueError(f"Unsupported interval format: {value!r}")

    # Convert matched groups into a concrete duration.
    count = int(match.group("count"))
    unit = match.group("unit")
    if count <= 0:
        raise ValueError("Interval must be a positive value")

    if unit == "m":
        return timedelta(minutes=count)
    return timedelta(hours=count)


def configure_qmd_indexing(
    env: Mapping[str, str] | None = None,
    logger: logging.Logger | None = None,
) -> IndexingConfig | None:
    """
    Determine whether QMD indexing should be enabled.

    Returns a configuration when indexing can run. If configuration cannot be
    parsed, returns None and logs the reason.
    """
    # Resolve runtime inputs with defaults for production use.
    effective_env = os.environ if env is None else env
    effective_logger = _logger if logger is None else logger

    # Pull interval from environment, falling back to the default cadence.
    interval_label = effective_env.get(INDEX_CRON_ENV, DEFAULT_INDEX_INTERVAL)
    try:
        interval = parse_index_interval(interval_label)
    except ValueError as exc:
        effective_logger.error(
            "Invalid %s=%s; disabling indexing (%s)",
            INDEX_CRON_ENV,
            interval_label,
            exc,
        )
        return None

    return IndexingConfig(interval=interval, interval_label=interval_label)


async def run_indexing_pipeline() -> None:
    """
    Run the QMD indexing pipeline.

    This function is expected to export sessions and run qmd update/embed.
    """
    return None


async def _run_indexing_once(
    run_pipeline: Callable[[], Awaitable[None]],
    logger: logging.Logger,
) -> None:
    """Run a single indexing cycle and log the outcome."""
    logger.info("QMD indexing run started")
    try:
        await run_pipeline()
    except asyncio.CancelledError:
        logger.info("QMD indexing run cancelled")
        raise
    except Exception:
        logger.exception("QMD indexing run failed")
    else:
        logger.info("QMD indexing run completed")


async def _indexing_scheduler_loop(
    interval_seconds: float,
    run_pipeline: Callable[[], Awaitable[None]],
    logger: logging.Logger,
) -> None:
    """Run the indexing pipeline on a fixed interval until cancelled."""
    while True:
        await _run_indexing_once(run_pipeline, logger)
        await asyncio.sleep(interval_seconds)


def start_indexing_scheduler(
    run_pipeline: Callable[[], Awaitable[None]],
    interval: timedelta,
    logger: logging.Logger | None = None,
) -> asyncio.Task[None]:
    """
    Start the background indexing scheduler.

    Args:
        run_pipeline: Async callable to execute each indexing run.
        interval: Interval between indexing runs.
        logger: Optional logger for status output.

    Returns:
        The asyncio.Task managing the scheduler loop.
    """
    # Guard against non-positive intervals before scheduling.
    interval_seconds = interval.total_seconds()
    if interval_seconds <= 0:
        raise ValueError("Interval must be greater than zero")

    scheduler_logger = _logger if logger is None else logger
    return asyncio.create_task(
        _indexing_scheduler_loop(interval_seconds, run_pipeline, scheduler_logger),
        name="qmd-indexing-scheduler",
    )


async def stop_indexing_scheduler(
    task: asyncio.Task[None],
    logger: logging.Logger | None = None,
) -> None:
    """
    Cancel and await the background indexing scheduler task.
    """
    if task.done():
        return

    scheduler_logger = _logger if logger is None else logger
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        scheduler_logger.info("QMD indexing scheduler stopped")


__all__ = [
    "DEFAULT_INDEX_INTERVAL",
    "INDEX_CRON_ENV",
    "IndexingConfig",
    "configure_qmd_indexing",
    "parse_index_interval",
    "run_indexing_pipeline",
    "start_indexing_scheduler",
    "stop_indexing_scheduler",
]
