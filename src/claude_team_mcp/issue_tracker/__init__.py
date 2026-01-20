"""
Issue tracker abstraction module.

Defines a protocol and backend implementations for issue tracker commands.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

logger = logging.getLogger("claude-team-mcp")


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


def detect_issue_tracker(project_path: str) -> IssueTrackerBackend | None:
    """
    Detect the issue tracker backend for the given project path.

    Args:
        project_path: Absolute or relative path to the project root.

    Returns:
        The detected IssueTrackerBackend, or None if no markers are present.
    """
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
    "detect_issue_tracker",
]
