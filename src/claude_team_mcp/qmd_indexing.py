"""
QMD indexing configuration, pipeline, and background scheduling.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Awaitable, Callable, Mapping

from .claude_export import export_claude_sessions
from .codex_export import export_codex_sessions

ENV_QMD_ENABLED = "CLAUDE_TEAM_QMD_INDEXING"
ENV_QMD_COMMAND = "CLAUDE_TEAM_QMD_COMMAND"

INDEX_CRON_ENV = "CLAUDE_TEAM_INDEX_CRON"
DEFAULT_INDEX_INTERVAL = "1h"

CLAUDE_COLLECTION_NAME = "claude-sessions"
CODEX_COLLECTION_NAME = "codex-sessions"
CLAUDE_COLLECTION_PATH = Path.home() / ".claude-team" / "index" / "claude"
CODEX_COLLECTION_PATH = Path.home() / ".claude-team" / "index" / "codex"

_INTERVAL_PATTERN = re.compile(r"^(?P<count>\d+)(?P<unit>[mh])$")

_logger = logging.getLogger("claude-team-mcp.qmd-indexing")


@dataclass(frozen=True)
class QmdCollection:
    """Metadata for a QMD collection."""

    name: str
    path: Path


@dataclass(frozen=True)
class QmdIndexingConfig:
    """Configuration for QMD indexing."""

    qmd_command: str
    claude: QmdCollection
    codex: QmdCollection
    interval: timedelta
    interval_label: str

    @property
    def collections(self) -> tuple[QmdCollection, QmdCollection]:
        """Return the configured collections in deterministic order."""
        return (self.claude, self.codex)


@dataclass(frozen=True)
class IndexingConfig:
    """Configuration for background QMD indexing."""

    interval: timedelta
    interval_label: str


_CONFIG: QmdIndexingConfig | None = None


# Parse truthy/falsy env flag values.
def _parse_env_flag(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Parse interval format strictly so callers can decide how to handle failures.
def _parse_index_interval_strict(value: str) -> timedelta:
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


def parse_index_interval(value: str) -> timedelta:
    """
    Parse an interval string like "15m" or "1h" into a timedelta.

    Invalid intervals fall back to DEFAULT_INDEX_INTERVAL.
    """
    try:
        return _parse_index_interval_strict(value)
    except ValueError:
        return _parse_index_interval_strict(DEFAULT_INDEX_INTERVAL)


def configure_index_schedule(
    env: Mapping[str, str] | None = None,
    logger: logging.Logger | None = None,
) -> IndexingConfig:
    """
    Resolve the indexing schedule interval from environment settings.
    """
    # Resolve runtime inputs with defaults for production use.
    effective_env = os.environ if env is None else env
    effective_logger = _logger if logger is None else logger

    # Pull interval from environment, falling back to the default cadence.
    interval_label = effective_env.get(INDEX_CRON_ENV, DEFAULT_INDEX_INTERVAL)
    try:
        interval = _parse_index_interval_strict(interval_label)
    except ValueError as exc:
        effective_logger.warning(
            "Invalid %s=%s; using default %s (%s)",
            INDEX_CRON_ENV,
            interval_label,
            DEFAULT_INDEX_INTERVAL,
            exc,
            extra={"event": "qmd_index_interval_fallback"},
        )
        interval_label = DEFAULT_INDEX_INTERVAL
        interval = _parse_index_interval_strict(DEFAULT_INDEX_INTERVAL)

    return IndexingConfig(interval=interval, interval_label=interval_label)


# Run a QMD command and log failures without raising.
def _run_qmd_command(qmd_command: str, args: list[str]) -> bool:
    command = [qmd_command, *args]
    # Execute once without retries to keep scheduling deterministic.
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except Exception as exc:
        _logger.error(
            "QMD command failed: %s",
            " ".join(command),
            exc_info=exc,
            extra={"event": "qmd_command_error", "command": command},
        )
        return False

    if result.returncode != 0:
        _logger.error(
            "QMD command failed (exit %s): %s",
            result.returncode,
            " ".join(command),
            extra={
                "event": "qmd_command_failed",
                "command": command,
                "returncode": result.returncode,
            },
        )
        if result.stdout:
            _logger.error(
                "QMD stdout: %s",
                result.stdout.strip(),
                extra={"event": "qmd_command_stdout", "command": command},
            )
        if result.stderr:
            _logger.error(
                "QMD stderr: %s",
                result.stderr.strip(),
                extra={"event": "qmd_command_stderr", "command": command},
            )
        return False

    return True


# Ensure collections exist and are indexed before scheduling.
def _bootstrap_collections(config: QmdIndexingConfig) -> None:
    # Create collections only when their paths are missing.
    for collection in config.collections:
        if not collection.path.exists():
            _run_qmd_command(
                config.qmd_command,
                [
                    "collection",
                    "add",
                    collection.name,
                    "--path",
                    str(collection.path),
                ],
            )

    # Always refresh indexes after bootstrap.
    for collection in config.collections:
        _run_qmd_command(config.qmd_command, ["update", collection.name])
        _run_qmd_command(config.qmd_command, ["embed", collection.name])


def configure_qmd_indexing() -> QmdIndexingConfig | None:
    """Configure the QMD indexing pipeline from environment flags."""
    # Gate the pipeline on an explicit environment flag.
    if not _parse_env_flag(os.environ.get(ENV_QMD_ENABLED)):
        _logger.info(
            "QMD indexing disabled (set %s=1 to enable)",
            ENV_QMD_ENABLED,
            extra={"event": "qmd_indexing_disabled"},
        )
        return None

    # Resolve the command used to invoke QMD.
    qmd_command = os.environ.get(ENV_QMD_COMMAND, "qmd")
    if not shutil.which(qmd_command):
        _logger.error(
            "QMD command not found: %s",
            qmd_command,
            extra={"event": "qmd_command_missing"},
        )
        return None

    # Get the indexing interval configuration.
    schedule = configure_index_schedule()

    # Build the configuration with deterministic collection ordering.
    config = QmdIndexingConfig(
        qmd_command=qmd_command,
        claude=QmdCollection(CLAUDE_COLLECTION_NAME, CLAUDE_COLLECTION_PATH),
        codex=QmdCollection(CODEX_COLLECTION_NAME, CODEX_COLLECTION_PATH),
        interval=schedule.interval,
        interval_label=schedule.interval_label,
    )

    # Perform bootstrap indexing without aborting on failures.
    _bootstrap_collections(config)

    # Persist the config for scheduled runs.
    global _CONFIG
    _CONFIG = config
    return config


# Export markdown content and refresh the QMD index for a collection.
def _export_and_index(
    config: QmdIndexingConfig,
    collection: QmdCollection,
    exporter: Callable[[Path], list[Path]],
) -> None:
    try:
        exporter(collection.path)
    except Exception as exc:
        _logger.error(
            "Export failed for %s",
            collection.name,
            exc_info=exc,
            extra={"event": "qmd_export_failed", "collection": collection.name},
        )
    finally:
        _run_qmd_command(config.qmd_command, ["update", collection.name])
        _run_qmd_command(config.qmd_command, ["embed", collection.name])


def run_indexing_pipeline(config: QmdIndexingConfig | None = None) -> None:
    """Run the full export and indexing pipeline."""
    # Resolve configuration for the scheduled run.
    resolved = config or _CONFIG or configure_qmd_indexing()
    if not resolved:
        return

    _logger.info(
        "QMD indexing pipeline started",
        extra={"event": "qmd_indexing_pipeline_start"},
    )

    # Export and index Claude sessions.
    _export_and_index(resolved, resolved.claude, export_claude_sessions)

    # Export and index Codex sessions.
    _export_and_index(resolved, resolved.codex, export_codex_sessions)

    _logger.info(
        "QMD indexing pipeline completed",
        extra={"event": "qmd_indexing_pipeline_complete"},
    )


async def run_indexing_pipeline_async(
    config: QmdIndexingConfig | None = None,
) -> None:
    """
    Async wrapper for run_indexing_pipeline.

    Runs the synchronous pipeline in a thread pool to avoid blocking
    the event loop during file I/O and subprocess calls.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_indexing_pipeline, config)


async def _run_indexing_once(
    run_pipeline: Callable[[], Awaitable[None]] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """
    Run a single indexing cycle and log the outcome.

    Args:
        run_pipeline: Async callable to execute. Defaults to run_indexing_pipeline_async.
        logger: Logger for status output. Defaults to module logger.
    """
    # Use defaults when not provided (enables standalone testing).
    effective_pipeline = run_pipeline or run_indexing_pipeline_async
    effective_logger = logger or _logger

    effective_logger.info(
        "QMD indexing run started",
        extra={"event": "qmd_indexing_run_start"},
    )
    try:
        await effective_pipeline()
    except asyncio.CancelledError:
        effective_logger.info(
            "QMD indexing run cancelled",
            extra={"event": "qmd_indexing_run_cancel"},
        )
        raise
    except Exception:
        effective_logger.exception(
            "QMD indexing run failed",
            extra={"event": "qmd_indexing_run_failed"},
        )
    else:
        effective_logger.info(
            "QMD indexing run completed",
            extra={"event": "qmd_indexing_run_complete"},
        )


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
        scheduler_logger.info(
            "QMD indexing scheduler stopped",
            extra={"event": "qmd_indexing_scheduler_stop"},
        )


__all__ = [
    "CLAUDE_COLLECTION_NAME",
    "CLAUDE_COLLECTION_PATH",
    "CODEX_COLLECTION_NAME",
    "CODEX_COLLECTION_PATH",
    "DEFAULT_INDEX_INTERVAL",
    "ENV_QMD_COMMAND",
    "ENV_QMD_ENABLED",
    "INDEX_CRON_ENV",
    "IndexingConfig",
    "QmdCollection",
    "QmdIndexingConfig",
    "configure_index_schedule",
    "configure_qmd_indexing",
    "parse_index_interval",
    "run_indexing_pipeline",
    "run_indexing_pipeline_async",
    "start_indexing_scheduler",
    "stop_indexing_scheduler",
]
