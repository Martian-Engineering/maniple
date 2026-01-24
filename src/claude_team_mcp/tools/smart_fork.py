"""
Smart fork tool.

Provides smart_fork for searching indexed sessions and optionally forking one.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from . import spawn_workers as spawn_workers_tool
from ..utils import error_response

_AGENT_COLLECTIONS = {
    "claude": "claude-sessions",
    "codex": "codex-sessions",
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
    async def smart_fork(
        ctx: Context[ServerSession, "AppContext"],
        intent: str,
        agent_type: Literal["claude", "codex"] = "claude",
        limit: int = 5,
        auto_fork: bool = False,
        fork_index: int | None = None,
    ) -> dict:
        """
        Search indexed sessions and optionally fork a matching session.

        Args:
            intent: Natural-language description of the desired work context.
            agent_type: Which agent to search ("claude" or "codex").
            limit: Maximum number of sessions to return.
            auto_fork: When true, immediately fork the top-ranked session.
            fork_index: Fork the session at this index (0-based).

        Returns:
            Dict with ranked sessions and optional fork result.
        """
        # Validate inputs early for clearer errors.
        if not intent.strip():
            return error_response("intent is required")
        if agent_type not in _AGENT_COLLECTIONS:
            return error_response("agent_type must be 'claude' or 'codex'")
        if limit < 1:
            return error_response("limit must be at least 1")
        if fork_index is not None and fork_index < 0:
            return error_response("fork_index must be non-negative")

        collection = _AGENT_COLLECTIONS[agent_type]

        # QMD must be installed to run search commands.
        if shutil.which("qmd") is None:
            return _qmd_unavailable_response(intent, agent_type, collection)

        # Execute the qmd search pipeline with fallbacks.
        search_result = _run_qmd_search(intent, collection)
        candidates = _build_candidates(search_result.results, limit, agent_type)

        response: dict = {
            "intent": intent,
            "agent_type": agent_type,
            "collection": collection,
            "results": candidates,
            "count": len(candidates),
            "fallback_used": search_result.fallback_used,
            "qmd_command": search_result.command,
        }

        if search_result.qmd_error:
            response["qmd_error"] = search_result.qmd_error

        # Optionally fork a chosen session.
        selected_index = _resolve_fork_index(auto_fork, fork_index)
        if selected_index is not None:
            fork_response = await _fork_session(
                ctx,
                candidates,
                selected_index,
                agent_type,
            )
            if "error" in fork_response:
                return fork_response
            response.update(fork_response)

        return response


# Check for qmd and provide guidance when unavailable.
def _qmd_unavailable_response(intent: str, agent_type: str, collection: str) -> dict:
    return error_response(
        "QMD search is unavailable (qmd not found on PATH)",
        hint=(
            "Install qmd and enable indexing in HTTP mode "
            "to use smart_fork."
        ),
        guidance={
            "intent": intent,
            "agent_type": agent_type,
            "collection": collection,
            "next_steps": [
                "Install qmd and ensure it is on PATH.",
                "Run claude-team in HTTP mode with indexing enabled.",
            ],
        },
    )


# Determine which session index should be auto-forked.
def _resolve_fork_index(auto_fork: bool, fork_index: int | None) -> int | None:
    if fork_index is not None:
        return fork_index
    if auto_fork:
        return 0
    return None


# Build candidates from qmd results by parsing session metadata headers.
def _build_candidates(
    raw_results: list[dict],
    limit: int,
    agent_type: str,
) -> list[dict]:
    candidates: list[dict] = []

    for result in raw_results:
        # Pull common fields from qmd output (allowing for nested payloads).
        path_value = _extract_result_field(result, ("path", "file", "source", "document_path"))
        snippet = _extract_result_field(result, ("snippet", "text", "content"))
        score = _extract_score(result)

        headers: dict[str, str] = {}
        # Prefer file-backed metadata, then fill missing values from snippet.
        if path_value:
            headers.update(_load_headers_from_path(Path(path_value)))
        if snippet:
            snippet_headers = _parse_markdown_headers(str(snippet))
            for key, value in snippet_headers.items():
                headers.setdefault(key, value)

        # Enforce agent-type consistency when metadata is available.
        header_agent = headers.get("agent_type")
        if header_agent and header_agent != agent_type:
            continue

        session_id = headers.get("session_id")
        working_directory = headers.get("working_directory")
        if not session_id or not working_directory:
            continue

        # Emit only forkable sessions (session_id + working_directory).
        candidates.append(
            {
                "session_id": session_id,
                "working_directory": working_directory,
                "date": headers.get("date"),
                "score": score,
                "snippet": snippet,
                "source_path": path_value,
            }
        )

        if len(candidates) >= limit:
            break

    return candidates


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
        label = match.group(1).strip().lower()
        value = match.group(2).strip()
        key = _HEADER_MAP.get(label)
        if key and value:
            headers[key] = value
    return headers


# Read header metadata from a markdown file path.
def _load_headers_from_path(path: Path) -> dict[str, str]:
    try:
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


# Spawn a forked worker session using spawn_workers tool.
async def _fork_session(
    ctx: Context[ServerSession, "AppContext"],
    candidates: list[dict],
    index: int,
    agent_type: str,
) -> dict:
    # Validate selection before attempting to fork.
    if not candidates:
        return error_response("No forkable sessions found")
    if index >= len(candidates):
        return error_response("fork_index is out of range")

    candidate = candidates[index]
    session_id = candidate.get("session_id")
    working_directory = candidate.get("working_directory")
    if not session_id or not working_directory:
        return error_response("Selected session is missing required metadata")

    spawn_tool = spawn_workers_tool.SPAWN_WORKERS_TOOL
    if spawn_tool is None:
        return error_response("spawn_workers tool is not available")

    # Use spawn_workers resume+fork semantics for the chosen agent type.
    worker_config = {
        "project_path": working_directory,
        "agent_type": agent_type,
        "resume_session_id": session_id,
        "fork_session": True,
    }

    fork_result = await spawn_tool(ctx, workers=[worker_config])

    return {
        "forked_index": index,
        "forked_session": fork_result,
    }
