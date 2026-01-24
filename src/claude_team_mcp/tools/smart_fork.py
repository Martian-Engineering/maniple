"""
Smart fork tool.

Provides smart_fork for searching indexed sessions.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from ..utils import error_response

_AGENT_COLLECTIONS = {
    "claude": ["ct-claude-sessions"],
    "codex": ["ct-codex-sessions"],
    "both": ["ct-claude-sessions", "ct-codex-sessions"],
}

_QMD_COMMANDS = ("query", "vsearch", "search")

_HEADER_MAP = {
    "session id": "session_id",
    "session_id": "session_id",
    "working directory": "working_directory",
    "working dir": "working_directory",
    "cwd": "working_directory",
    "date": "date",
    "agent": "agent_type",
}


class QmdSearchResult:
    """Container for qmd search outcomes."""

    def __init__(
        self,
        results: list[dict],
        command: str | None,
        fallback_used: bool,
        qmd_error: str | None,
    ) -> None:
        self.results = results
        self.command = command
        self.fallback_used = fallback_used
        self.qmd_error = qmd_error


def register_tools(mcp: FastMCP) -> None:
    """Register smart_fork tool on the MCP server."""

    @mcp.tool()
    def smart_fork(
        intent: str,
        agent_type: Literal["claude", "codex", "both"] = "both",
        limit: int = 5,
    ) -> dict:
        """
        Search indexed sessions for relevant context.

        Args:
            intent: Natural-language description of the desired work context.
            agent_type: Which agent sessions to search ("claude", "codex", or "both").
            limit: Maximum number of sessions to return.

        Returns:
            Dict with ranked sessions matching the intent.
        """
        # Validate inputs early for clearer errors.
        if not intent.strip():
            return error_response("intent is required")
        if agent_type not in _AGENT_COLLECTIONS:
            return error_response("agent_type must be 'claude', 'codex', or 'both'")
        if limit < 1:
            return error_response("limit must be at least 1")

        collections = _AGENT_COLLECTIONS[agent_type]

        # QMD must be installed to run search commands.
        if shutil.which("qmd") is None:
            return _qmd_unavailable_response(intent, agent_type, collections)

        # Execute the qmd search pipeline with fallbacks across all collections.
        # When searching multiple collections, merge and sort by score.
        all_results: list[dict] = []
        fallback_used = False
        last_command: str | None = None
        last_error: str | None = None

        for collection in collections:
            search_result = _run_qmd_search(intent, collection)
            all_results.extend(search_result.results)
            if search_result.fallback_used:
                fallback_used = True
            if search_result.command:
                last_command = search_result.command
            if search_result.qmd_error:
                last_error = search_result.qmd_error

        # Build candidates with optional agent_type filter (None for "both").
        filter_agent = None if agent_type == "both" else agent_type
        candidates = _build_candidates(all_results, limit, filter_agent)

        response: dict = {
            "intent": intent,
            "agent_type": agent_type,
            "collections": collections,
            "results": candidates,
            "count": len(candidates),
            "fallback_used": fallback_used,
            "qmd_command": last_command,
        }

        if last_error:
            response["qmd_error"] = last_error

        return response


# Check for qmd and provide guidance when unavailable.
def _qmd_unavailable_response(
    intent: str, agent_type: str, collections: list[str]
) -> dict:
    return error_response(
        "QMD search is unavailable (qmd not found on PATH)",
        hint=(
            "Install qmd and enable indexing in HTTP mode "
            "to use smart_fork."
        ),
        guidance={
            "intent": intent,
            "agent_type": agent_type,
            "collections": collections,
            "next_steps": [
                "Install qmd and ensure it is on PATH.",
                "Run claude-team in HTTP mode with indexing enabled.",
            ],
        },
    )


# Build candidates from qmd results by parsing session metadata headers.
def _build_candidates(
    raw_results: list[dict],
    limit: int,
    agent_type: str | None,
) -> list[dict]:
    """
    Build ranked candidate list from raw qmd results.

    Args:
        raw_results: Raw results from qmd search (may be from multiple collections).
        limit: Maximum number of candidates to return.
        agent_type: Filter to specific agent type, or None to include all.

    Returns:
        List of candidate dicts sorted by score (descending).
    """
    candidates: list[dict] = []

    for result in raw_results:
        # Pull common fields from qmd output (allowing for nested payloads).
        path_value = _extract_result_field(
            result, ("path", "file", "source", "document_path")
        )
        snippet = _extract_result_field(result, ("snippet", "text", "content"))
        score = _extract_score(result)

        headers: dict[str, str] = {}
        # Prefer file-backed metadata, then fill missing values from snippet.
        if path_value:
            headers.update(_load_headers_from_path(path_value))
        if snippet:
            snippet_headers = _parse_markdown_headers(str(snippet))
            for key, value in snippet_headers.items():
                headers.setdefault(key, value)

        # Enforce agent-type consistency when filter is specified.
        header_agent = headers.get("agent_type")
        if agent_type is not None and header_agent and header_agent != agent_type:
            continue

        session_id = headers.get("session_id")
        working_directory = headers.get("working_directory")
        if not session_id or not working_directory:
            continue

        # Emit valid sessions with required metadata.
        candidates.append(
            {
                "session_id": session_id,
                "working_directory": working_directory,
                "agent_type": header_agent,
                "date": headers.get("date"),
                "score": score,
                "snippet": snippet,
                "source_path": path_value,
            }
        )

    # Sort by score descending (None scores sort last).
    candidates.sort(key=lambda c: (c.get("score") is not None, c.get("score") or 0), reverse=True)

    return candidates[:limit]


# Extract a field from a qmd result, including nested document/metadata sections.
def _extract_result_field(result: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = result.get(key)
        if value:
            return str(value)
    for container_key in ("document", "metadata", "meta"):
        container = result.get(container_key)
        if isinstance(container, dict):
            for key in keys:
                value = container.get(key)
                if value:
                    return str(value)
    return None


# Parse a numeric score from the qmd result payload.
def _extract_score(result: dict) -> float | None:
    for key in ("score", "similarity", "distance", "rank"):
        value = result.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


# Parse markdown headers that include session metadata (Session ID, Working Directory, etc.).
def _parse_markdown_headers(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*[-*]?\s*([^:]+?)\s*:\s*(.+?)\s*$", line)
        if not match:
            continue
        # Strip markdown bold/italic markers (**bold**, *italic*) from label
        label = match.group(1).strip().lower().strip("*_")
        value = match.group(2).strip().strip("*_")
        key = _HEADER_MAP.get(label)
        if key and value:
            headers[key] = value
    return headers


# Read header metadata from a path or qmd:// URL.
def _load_headers_from_path(path_or_url: Path | str) -> dict[str, str]:
    path_str = str(path_or_url)
    
    # Handle qmd:// URLs by fetching content with qmd get
    if path_str.startswith("qmd://"):
        try:
            result = subprocess.run(
                ["qmd", "get", path_str],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout:
                return _parse_markdown_headers(result.stdout)
        except FileNotFoundError:
            pass
        return {}
    
    # Handle local file paths
    try:
        path = Path(path_str) if isinstance(path_or_url, str) else path_or_url
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    return _parse_markdown_headers(content)


# Run the qmd search sequence with fallback commands.
def _run_qmd_search(intent: str, collection: str) -> QmdSearchResult:
    last_error: str | None = None

    # Run the preferred qmd query first, then fall back on failure.
    for command in _QMD_COMMANDS:
        args = ["qmd", command, intent, "-c", collection, "--json"]
        try:
            result = _run_qmd_command(args)
        except FileNotFoundError:
            last_error = "qmd executable not found"
            break

        # Non-zero exit triggers fallback to the next command.
        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else "<no stderr>"
            last_error = f"qmd {command} failed: {stderr}"
            continue

        try:
            parsed = _parse_qmd_json(result.stdout)
        except ValueError as exc:
            last_error = f"qmd {command} returned invalid JSON: {exc}"
            continue

        fallback_used = command != _QMD_COMMANDS[0]
        return QmdSearchResult(parsed, command, fallback_used, last_error)

    # All commands failed, return empty results with the last error message.
    return QmdSearchResult([], None, True, last_error)


# Execute qmd with subprocess and return the completed process.
def _run_qmd_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
    )


# Parse qmd JSON output into a list of result dicts.
def _parse_qmd_json(raw: str) -> list[dict]:
    raw = raw.strip()
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        results: list[dict] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(str(exc)) from exc
            if isinstance(entry, dict):
                results.append(entry)
        return results

    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return [entry for entry in results if isinstance(entry, dict)]
        return [data]

    return []
