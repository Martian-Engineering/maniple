"""
Claude Session Markdown Exporter.

Exports Claude Code session JSONL logs to Markdown for indexing.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .session_state import (
    Message,
    SessionState,
    get_project_dir,
    get_project_slug,
    parse_session,
    unslugify_path,
)


CLAUDE_EXPORT_ROOT = Path.home() / ".claude-team" / "index" / "claude"
CLAUDE_AGENT_NAME = "claude"


# Resolve the Claude projects directory for a given project path.
def _resolve_project_dir(project_path: str, source_root: Optional[Path]) -> Path:
    if source_root is None:
        return get_project_dir(project_path)
    return source_root / get_project_slug(project_path)


# Determine whether an export is already newer than the source JSONL.
def _is_export_current(output_path: Path, jsonl_path: Path) -> bool:
    if not output_path.exists():
        return False
    try:
        return output_path.stat().st_mtime >= jsonl_path.stat().st_mtime
    except OSError:
        return False


# Choose the working directory from JSONL contents or project slug.
def _resolve_working_directory(state: SessionState, project_dir: Optional[Path]) -> str:
    if state.project_path:
        return state.project_path
    if project_dir is None:
        return ""
    slug_path = unslugify_path(project_dir.name)
    return slug_path or ""


# Pick a stable session date from message timestamps or file mtime.
def _resolve_session_date(state: SessionState, jsonl_path: Path) -> datetime:
    if state.messages:
        return min(message.timestamp for message in state.messages)
    return datetime.fromtimestamp(jsonl_path.stat().st_mtime)


# Walk upward from the working directory to find a git repo root.
def _find_repo_root(working_directory: str) -> Optional[str]:
    if not working_directory:
        return None
    try:
        path = Path(working_directory).expanduser().resolve()
    except OSError:
        return None

    # Walk upward so nested working directories still resolve to the repo root.
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return str(parent)
    return None


def render_session_markdown(
    session_id: str,
    working_directory: str,
    date: datetime | str,
    messages: Iterable[Message],
    repo_root: Optional[str] = None,
    agent: str = CLAUDE_AGENT_NAME,
) -> str:
    """Render a Claude session as Markdown with normalized headers."""
    date_value = date.isoformat() if isinstance(date, datetime) else str(date)

    # Build a stable YAML-style header for downstream parsers.
    lines: list[str] = [
        "---",
        f"Session ID: {session_id}",
        f"Working Directory: {working_directory}",
        f"Date: {date_value}",
        f"Agent: {agent}",
    ]
    if repo_root:
        lines.append(f"Repo Root: {repo_root}")
    lines.append("---")
    lines.append("")

    # Emit each message as its own section to preserve role boundaries.
    for message in messages:
        if message.role not in ("user", "assistant"):
            continue
        if not message.content:
            continue

        heading = "User" if message.role == "user" else "Assistant"
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(message.content)
        lines.append("")

    markdown = "\n".join(lines)
    if not markdown.endswith("\n"):
        markdown += "\n"
    return markdown


def export_jsonl_session(
    jsonl_path: Path,
    output_root: Optional[Path] = None,
    project_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Export a single Claude session JSONL file to Markdown."""
    output_root = output_root or CLAUDE_EXPORT_ROOT
    output_path = output_root / f"{jsonl_path.stem}.md"

    if _is_export_current(output_path, jsonl_path):
        return None

    # Parse the session once for header metadata and message content.
    state = parse_session(jsonl_path)
    working_directory = _resolve_working_directory(state, project_dir)
    session_date = _resolve_session_date(state, jsonl_path)
    repo_root = _find_repo_root(working_directory)

    markdown = render_session_markdown(
        session_id=state.session_id,
        working_directory=working_directory,
        date=session_date,
        messages=state.messages,
        repo_root=repo_root,
    )

    output_root.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown)
    return output_path


def export_project_sessions(
    project_path: str,
    output_root: Optional[Path] = None,
    source_root: Optional[Path] = None,
) -> list[Path]:
    """Export all Claude session JSONL files for a project to Markdown."""
    project_dir = _resolve_project_dir(project_path, source_root)
    if not project_dir.exists():
        return []

    exported: list[Path] = []

    # Scan sessions in a deterministic order and skip agent sub-session files.
    for jsonl_path in sorted(project_dir.glob("*.jsonl")):
        if jsonl_path.name.startswith("agent-"):
            continue

        exported_path = export_jsonl_session(
            jsonl_path,
            output_root=output_root,
            project_dir=project_dir,
        )
        if exported_path:
            exported.append(exported_path)

    return exported

def export_claude_sessions(output_dir: Path) -> list[Path]:
    """
    Export all Claude sessions from all projects to Markdown.

    Scans ~/.claude/projects/ for all project directories and exports
    their session JSONL files to the specified output directory.

    Args:
        output_dir: Directory to write Markdown exports to.

    Returns:
        List of paths to exported Markdown files.
    """
    from .session_state import CLAUDE_PROJECTS_DIR

    if not CLAUDE_PROJECTS_DIR.exists():
        return []

    exported: list[Path] = []

    # Scan all project directories in the Claude projects root.
    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        # Export each JSONL session file in deterministic order.
        for jsonl_path in sorted(project_dir.glob("*.jsonl")):
            # Skip agent sub-session files.
            if jsonl_path.name.startswith("agent-"):
                continue

            exported_path = export_jsonl_session(
                jsonl_path,
                output_root=output_dir,
                project_dir=project_dir,
            )
            if exported_path:
                exported.append(exported_path)

    return exported
