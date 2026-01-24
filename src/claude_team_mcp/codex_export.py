"""
Codex JSONL session export helpers.

Exports Codex session JSONL to a normalized Markdown format for indexing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .session_state import Message, parse_codex_session
from .utils.constants import CODEX_INDEX_DIR

logger = logging.getLogger("claude-team-mcp")


@dataclass(frozen=True)
class CodexSessionMeta:
    """Metadata extracted from a Codex session_meta entry."""

    session_id: str
    cwd: str
    timestamp: str


def parse_codex_session_meta(jsonl_path: Path) -> CodexSessionMeta | None:
    """Parse session_meta payload fields from a Codex JSONL file."""
    if not jsonl_path.exists():
        return None

    try:
        with open(jsonl_path, "r", encoding="utf-8") as handle:
            # Scan for the first session_meta entry to capture session metadata.
            for line in handle:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Ignore non-meta entries; only session_meta contains id/cwd/timestamp.
                if entry.get("type") != "session_meta":
                    continue

                # Extract the core identifiers used for resume/fork behavior.
                payload = entry.get("payload", {})
                session_id = payload.get("id") or ""
                if not session_id:
                    return None

                return CodexSessionMeta(
                    session_id=session_id,
                    cwd=payload.get("cwd") or "",
                    timestamp=payload.get("timestamp") or "",
                )
    except OSError as exc:
        logger.warning("Failed to read Codex session meta from %s: %s", jsonl_path, exc)

    return None


def format_codex_markdown(meta: CodexSessionMeta, messages: Iterable[Message]) -> str:
    """Format Codex session metadata and messages into Markdown."""
    # Use the same YAML-frontmatter format as Claude export for consistent parsing.
    lines: list[str] = [
        "---",
        f"Session ID: {meta.session_id}",
        f"Working Directory: {meta.cwd}",
        f"Date: {meta.timestamp}",
        "Agent: codex",
        "---",
        "",
    ]

    # Append each message with role headings and optional thinking blocks.
    for message in messages:
        role = "User" if message.role == "user" else "Assistant"
        lines.extend([f"## {role}", "", message.content, ""])
        if message.thinking:
            lines.extend(["### Thinking", "", message.thinking, ""])

    # Ensure trailing newline for consistent diffing and tooling.
    return "\n".join(lines).rstrip() + "\n"


def export_codex_session_markdown(
    jsonl_path: Path,
    *,
    output_dir: Path | None = None,
    messages: Iterable[Message] | None = None,
) -> Path | None:
    """Export a Codex JSONL session to Markdown for indexing."""
    meta = parse_codex_session_meta(jsonl_path)
    if meta is None:
        return None

    resolved_output_dir = output_dir or CODEX_INDEX_DIR
    output_path = resolved_output_dir / f"{meta.session_id}.md"

    # Skip export when the Markdown is already newer than the JSONL input.
    try:
        if output_path.exists():
            output_mtime = output_path.stat().st_mtime
            jsonl_mtime = jsonl_path.stat().st_mtime
            if output_mtime >= jsonl_mtime:
                return output_path
    except OSError as exc:
        logger.warning("Failed to compare export timestamps for %s: %s", jsonl_path, exc)

    # Use provided messages when available to avoid re-parsing.
    if messages is None:
        state = parse_codex_session(jsonl_path)
        messages = state.conversation

    # Build markdown content and ensure output directory exists.
    markdown = format_codex_markdown(meta, messages)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        output_path.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to write Codex markdown export %s: %s", output_path, exc)
        return None

    return output_path

# Codex sessions directory (matches idle_detection.py)
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def export_codex_sessions(output_dir: Path) -> list[Path]:
    """
    Export all Codex sessions to Markdown.

    Scans ~/.codex/sessions/ for all session JSONL files and exports
    them to the specified output directory.

    Args:
        output_dir: Directory to write Markdown exports to.

    Returns:
        List of paths to exported Markdown files.
    """
    exported: list[Path] = []

    # Codex sessions are organized as ~/.codex/sessions/{YYYY}/{MM}/{DD}/*.jsonl
    if not CODEX_SESSIONS_DIR.exists():
        return exported

    # Use recursive glob to handle the 3-level date directory structure.
    for jsonl_path in sorted(CODEX_SESSIONS_DIR.glob("**/*.jsonl")):
        exported_path = export_codex_session_markdown(
            jsonl_path,
            output_dir=output_dir,
        )
        if exported_path:
            exported.append(exported_path)

    return exported
