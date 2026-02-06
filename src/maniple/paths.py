"""Shared filesystem paths for Maniple, including legacy migrations."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger("maniple")

LEGACY_DATA_DIRNAME = ".claude-team"
DATA_DIRNAME = ".maniple"


def migrate_legacy_data_dir(*, home: Path | None = None) -> None:
    """Best-effort migration of `~/.claude-team/` to `~/.maniple/`.

    Per `docs/rename-decisions.md`, we migrate the entire directory as a unit.

    If `~/.maniple/` already exists (or `~/.claude-team/` does not), this is a no-op.
    """

    home_dir = home or Path.home()
    legacy_dir = home_dir / LEGACY_DATA_DIRNAME
    new_dir = home_dir / DATA_DIRNAME

    if new_dir.exists() or not legacy_dir.exists():
        return

    try:
        legacy_dir.rename(new_dir)
    except OSError:
        # Fallback for odd filesystem situations where rename fails.
        try:
            shutil.move(str(legacy_dir), str(new_dir))
        except OSError as exc:
            logger.warning(
                "Unable to migrate legacy data dir (%s -> %s): %s",
                legacy_dir,
                new_dir,
                exc,
            )


def resolve_data_dir(*, home: Path | None = None) -> Path:
    """Return the data dir path to use, migrating legacy dir when needed.

    This function prefers `~/.maniple/`. If legacy migration fails, it will fall
    back to `~/.claude-team/` when that directory still exists.
    """

    migrate_legacy_data_dir(home=home)

    home_dir = home or Path.home()
    new_dir = home_dir / DATA_DIRNAME
    if new_dir.exists():
        return new_dir

    legacy_dir = home_dir / LEGACY_DATA_DIRNAME
    if legacy_dir.exists():
        return legacy_dir

    return new_dir


__all__ = [
    "DATA_DIRNAME",
    "LEGACY_DATA_DIRNAME",
    "migrate_legacy_data_dir",
    "resolve_data_dir",
]

