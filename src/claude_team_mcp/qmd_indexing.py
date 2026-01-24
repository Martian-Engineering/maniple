"""
QMD indexing pipeline for Claude Team session exports.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .claude_export import export_claude_sessions
from .codex_export import export_codex_sessions

logger = logging.getLogger("claude-team-mcp.qmd_indexing")

ENV_QMD_ENABLED = "CLAUDE_TEAM_QMD_INDEXING"
ENV_QMD_COMMAND = "CLAUDE_TEAM_QMD_COMMAND"

CLAUDE_COLLECTION_NAME = "claude-sessions"
CODEX_COLLECTION_NAME = "codex-sessions"
CLAUDE_COLLECTION_PATH = Path.home() / ".claude-team" / "index" / "claude"
CODEX_COLLECTION_PATH = Path.home() / ".claude-team" / "index" / "codex"


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

    @property
    def collections(self) -> tuple[QmdCollection, QmdCollection]:
        """Return the configured collections in deterministic order."""
        return (self.claude, self.codex)


_CONFIG: QmdIndexingConfig | None = None


def _parse_env_flag(value: str | None) -> bool:
    """Parse an environment flag into a boolean."""
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _run_qmd_command(qmd_command: str, args: list[str]) -> bool:
    """Run a QMD command and log failures without raising."""
    command = [qmd_command, *args]
    # Execute once without retries to keep scheduling deterministic.
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except Exception as exc:
        logger.error("QMD command failed: %s", " ".join(command), exc_info=exc)
        return False

    if result.returncode != 0:
        logger.error(
            "QMD command failed (exit %s): %s", result.returncode, " ".join(command)
        )
        if result.stdout:
            logger.error("QMD stdout: %s", result.stdout.strip())
        if result.stderr:
            logger.error("QMD stderr: %s", result.stderr.strip())
        return False

    return True


def _bootstrap_collections(config: QmdIndexingConfig) -> None:
    """Ensure collections exist and are indexed at startup."""
    # Create collections only when their paths are missing.
    for collection in config.collections:
        if not collection.path.exists():
            _run_qmd_command(
                config.qmd_command,
                [
                    "collection",
                    "create",
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
        logger.info("QMD indexing disabled (set %s=1 to enable)", ENV_QMD_ENABLED)
        return None

    # Resolve the command used to invoke QMD.
    qmd_command = os.environ.get(ENV_QMD_COMMAND, "qmd")
    if not shutil.which(qmd_command):
        logger.error("QMD command not found: %s", qmd_command)
        return None

    # Build the configuration with deterministic collection ordering.
    config = QmdIndexingConfig(
        qmd_command=qmd_command,
        claude=QmdCollection(CLAUDE_COLLECTION_NAME, CLAUDE_COLLECTION_PATH),
        codex=QmdCollection(CODEX_COLLECTION_NAME, CODEX_COLLECTION_PATH),
    )

    # Perform bootstrap indexing without aborting on failures.
    _bootstrap_collections(config)

    # Persist the config for scheduled runs.
    global _CONFIG
    _CONFIG = config
    return config


def _export_and_index(
    config: QmdIndexingConfig,
    collection: QmdCollection,
    exporter: Callable[[Path], list[Path]],
) -> None:
    """Export markdown content and refresh the QMD index."""
    try:
        exporter(collection.path)
    except Exception as exc:
        logger.error("Export failed for %s", collection.name, exc_info=exc)
    finally:
        _run_qmd_command(config.qmd_command, ["update", collection.name])
        _run_qmd_command(config.qmd_command, ["embed", collection.name])


def run_indexing_pipeline(config: QmdIndexingConfig | None = None) -> None:
    """Run the full export and indexing pipeline."""
    # Resolve configuration for the scheduled run.
    resolved = config or _CONFIG or configure_qmd_indexing()
    if not resolved:
        return

    # Export and index Claude sessions.
    _export_and_index(resolved, resolved.claude, export_claude_sessions)

    # Export and index Codex sessions.
    _export_and_index(resolved, resolved.codex, export_codex_sessions)
