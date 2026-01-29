"""
Issue tracker abstraction module.

Defines a protocol and backend implementations for issue tracker commands.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from claude_team_mcp.config import ClaudeTeamConfig

logger = logging.getLogger("claude-team-mcp")

# Environment variable for explicit tracker override (highest priority).
ISSUE_TRACKER_ENV_VAR = "CLAUDE_TEAM_ISSUE_TRACKER"


@runtime_checkable
class IssueTrackerBackend(Protocol):
    """
    Protocol defining the issue tracker backend interface.

    Backends provide a name, CLI command, marker directory, and command templates.
    """

    name: str
    cli: str
    marker_dir: str
    commands: dict[str, str]


@dataclass(frozen=True)
class BeadsBackend:
    """Beads issue tracker backend."""

    name: str = "beads"
    cli: str = "bd"
    marker_dir: str = ".beads"
    commands: dict[str, str] = field(
        default_factory=lambda: {
            "list": "bd --no-db list",
            "ready": "bd --no-db ready",
            "show": "bd --no-db show {issue_id}",
            "update": "bd --no-db update {issue_id} --status {status}",
            "close": "bd --no-db close {issue_id}",
            "create": (
                "bd --no-db create --title \"{title}\" --type {type} "
                "--priority {priority} --description \"{description}\""
            ),
            "comment": "bd --no-db comment {issue_id} \"{comment}\"",
            "dep_add": "bd --no-db dep add {issue_id} {dependency_id}",
            "dep_tree": "bd --no-db dep tree {issue_id}",
        }
    )


@dataclass(frozen=True)
class PebblesBackend:
    """Pebbles issue tracker backend."""

    name: str = "pebbles"
    cli: str = "pb"
    marker_dir: str = ".pebbles"
    commands: dict[str, str] = field(
        default_factory=lambda: {
            "list": "pb list",
            "ready": "pb ready",
            "show": "pb show {issue_id}",
            "update": "pb update {issue_id} -status {status}",
            "close": "pb close {issue_id}",
            "create": (
                "pb create -title \"{title}\" -type {type} -priority {priority} "
                "-description \"{description}\""
            ),
            "comment": "pb comment {issue_id} -body \"{comment}\"",
            "dep_add": "pb dep add {issue_id} {dependency_id}",
            "dep_tree": "pb dep tree {issue_id}",
        }
    )


BEADS_BACKEND = BeadsBackend()
PEBBLES_BACKEND = PebblesBackend()
BACKEND_REGISTRY: dict[str, IssueTrackerBackend] = {
    BEADS_BACKEND.name: BEADS_BACKEND,
    PEBBLES_BACKEND.name: PEBBLES_BACKEND,
}


def detect_issue_tracker(
    project_path: str,
    config: ClaudeTeamConfig | None = None,
) -> IssueTrackerBackend | None:
    """
    Detect the issue tracker backend for the given project path.

    Resolution order (highest to lowest priority):
      1. CLAUDE_TEAM_ISSUE_TRACKER environment variable
      2. config.issue_tracker.override setting
      3. Marker directory detection (.pebbles, .beads)

    Args:
        project_path: Absolute or relative path to the project root.
        config: Optional config object. If None, config is loaded from disk.

    Returns:
        The detected IssueTrackerBackend, or None if no tracker is configured
        or detected.
    """
    # Priority 1: Environment variable override.
    env_override = os.environ.get(ISSUE_TRACKER_ENV_VAR)
    if env_override:
        backend = BACKEND_REGISTRY.get(env_override.lower())
        if backend:
            logger.debug(
                "Using issue tracker '%s' from %s env var",
                backend.name,
                ISSUE_TRACKER_ENV_VAR,
            )
            return backend
        logger.warning(
            "Unknown issue tracker '%s' in %s; ignoring",
            env_override,
            ISSUE_TRACKER_ENV_VAR,
        )

    # Priority 2: Config file override.
    if config is None:
        # Lazy import to avoid circular dependency at module load time.
        try:
            from claude_team_mcp.config import ConfigError, load_config

            config = load_config()
        except ConfigError as exc:
            logger.warning("Invalid config file; ignoring overrides: %s", exc)
            config = None

    if config and config.issue_tracker.override:
        backend = BACKEND_REGISTRY.get(config.issue_tracker.override)
        if backend:
            logger.debug(
                "Using issue tracker '%s' from config override",
                backend.name,
            )
            return backend
        # Config validation should prevent this, but handle gracefully.
        logger.warning(
            "Unknown issue tracker '%s' in config; ignoring",
            config.issue_tracker.override,
        )

    # Priority 3: Marker directory detection.
    return _detect_from_markers(project_path)


def _detect_from_markers(project_path: str) -> IssueTrackerBackend | None:
    """Detect issue tracker by checking for marker directories."""
    beads_marker = os.path.join(project_path, BEADS_BACKEND.marker_dir)
    pebbles_marker = os.path.join(project_path, PEBBLES_BACKEND.marker_dir)

    # Check marker directories in the project root.
    beads_present = os.path.isdir(beads_marker)
    pebbles_present = os.path.isdir(pebbles_marker)

    # Resolve the deterministic backend when both markers exist.
    if beads_present and pebbles_present:
        logger.warning(
            "Both .beads and .pebbles found in %s; defaulting to pebbles",
            project_path,
        )
        return PEBBLES_BACKEND

    # Return the matching backend if only one marker exists.
    if pebbles_present:
        return PEBBLES_BACKEND

    if beads_present:
        return BEADS_BACKEND

    return None


__all__ = [
    "IssueTrackerBackend",
    "BeadsBackend",
    "PebblesBackend",
    "BEADS_BACKEND",
    "PEBBLES_BACKEND",
    "BACKEND_REGISTRY",
    "ISSUE_TRACKER_ENV_VAR",
    "detect_issue_tracker",
]
