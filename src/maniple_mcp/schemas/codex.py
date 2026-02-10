"""Codex CLI JSONL schema for parsing headless mode output.

Schema derived from Codex rust-v0.77.0 (git 112f40e91c12af0f7146d7e03f20283516a8af0b).
Ported from takopi/src/takopi/schemas/codex.py.
"""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

import msgspec

# Status type aliases for various item types
CommandExecutionStatus: TypeAlias = Literal[
    "in_progress",
    "completed",
    "failed",
    "declined",
]

PatchApplyStatus: TypeAlias = Literal[
    "in_progress",
    "completed",
    "failed",
]

PatchChangeKind: TypeAlias = Literal[
    "add",
    "delete",
    "update",
]

McpToolCallStatus: TypeAlias = Literal[
    "in_progress",
    "completed",
    "failed",
]


# --- Core structs ---


class Usage(msgspec.Struct, kw_only=True):
    """Token usage statistics for a turn."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int


class ThreadError(msgspec.Struct, kw_only=True):
    """Error information for failed turns."""

    message: str


# --- Thread lifecycle events ---


class ThreadStarted(msgspec.Struct, tag="thread.started", kw_only=True):
    """Emitted when a new Codex thread begins. Contains thread_id for session tracking."""

    thread_id: str


class TurnStarted(msgspec.Struct, tag="turn.started", kw_only=True):
    """Emitted when a new turn begins within a thread."""

    pass


class TurnCompleted(msgspec.Struct, tag="turn.completed", kw_only=True):
    """Emitted when a turn completes successfully. Contains usage statistics."""

    usage: Usage


class TurnFailed(msgspec.Struct, tag="turn.failed", kw_only=True):
    """Emitted when a turn fails. Contains error details."""

    error: ThreadError


class StreamError(msgspec.Struct, tag="error", kw_only=True):
    """Emitted for stream-level errors (e.g., reconnection attempts)."""

    message: str


# --- Item types (tools, messages, etc.) ---


class AgentMessageItem(msgspec.Struct, tag="agent_message", kw_only=True):
    """Text message from the agent."""

    id: str
    text: str


class ReasoningItem(msgspec.Struct, tag="reasoning", kw_only=True):
    """Reasoning/thinking output from the agent."""

    id: str
    text: str


class CommandExecutionItem(msgspec.Struct, tag="command_execution", kw_only=True):
    """Shell command execution."""

    id: str
    command: str
    aggregated_output: str
    exit_code: int | None
    status: CommandExecutionStatus


class FileUpdateChange(msgspec.Struct, kw_only=True):
    """A single file change within a patch."""

    path: str
    kind: PatchChangeKind


class FileChangeItem(msgspec.Struct, tag="file_change", kw_only=True):
    """File modification/patch operation."""

    id: str
    changes: list[FileUpdateChange]
    status: PatchApplyStatus


class McpToolCallItemResult(msgspec.Struct, kw_only=True):
    """Result of an MCP tool call."""

    content: list[dict[str, Any]]
    structured_content: Any


class McpToolCallItemError(msgspec.Struct, kw_only=True):
    """Error from an MCP tool call."""

    message: str


class McpToolCallItem(msgspec.Struct, tag="mcp_tool_call", kw_only=True):
    """MCP tool invocation."""

    id: str
    server: str
    tool: str
    arguments: Any
    result: McpToolCallItemResult | None
    error: McpToolCallItemError | None
    status: McpToolCallStatus


class WebSearchItem(msgspec.Struct, tag="web_search", kw_only=True):
    """Web search operation."""

    id: str
    query: str


class ErrorItem(msgspec.Struct, tag="error", kw_only=True):
    """Error item (distinct from StreamError - this is an item in the thread)."""

    id: str
    message: str


class TodoItem(msgspec.Struct, kw_only=True):
    """A single todo item."""

    text: str
    completed: bool


class TodoListItem(msgspec.Struct, tag="todo_list", kw_only=True):
    """Todo list from the agent."""

    id: str
    items: list[TodoItem]


# Union of all possible thread items
ThreadItem: TypeAlias = (
    AgentMessageItem
    | ReasoningItem
    | CommandExecutionItem
    | FileChangeItem
    | McpToolCallItem
    | WebSearchItem
    | TodoListItem
    | ErrorItem
)


# --- Item lifecycle events ---


class ItemStarted(msgspec.Struct, tag="item.started", kw_only=True):
    """Emitted when an item (tool use, message, etc.) starts."""

    item: ThreadItem


class ItemUpdated(msgspec.Struct, tag="item.updated", kw_only=True):
    """Emitted when an item is updated (streaming content)."""

    item: ThreadItem


class ItemCompleted(msgspec.Struct, tag="item.completed", kw_only=True):
    """Emitted when an item finishes."""

    item: ThreadItem


# Union of all possible thread events
ThreadEvent: TypeAlias = (
    ThreadStarted
    | TurnStarted
    | TurnCompleted
    | TurnFailed
    | ItemStarted
    | ItemUpdated
    | ItemCompleted
    | StreamError
)

# Pre-constructed decoder for efficient parsing
_DECODER = msgspec.json.Decoder(ThreadEvent)


def decode_event(data: bytes | str) -> ThreadEvent:
    """Decode a single JSONL line into a ThreadEvent.

    Args:
        data: Raw JSON bytes or string from Codex JSONL output

    Returns:
        Parsed ThreadEvent (one of the union member types)

    Raises:
        msgspec.DecodeError: If the JSON is malformed or doesn't match schema
    """
    return _DECODER.decode(data)


# --- Helper functions for common operations ---


def is_turn_complete(event: ThreadEvent) -> bool:
    """Check if the event indicates a turn has finished (success or failure)."""
    return isinstance(event, (TurnCompleted, TurnFailed))


def is_turn_successful(event: ThreadEvent) -> bool:
    """Check if the event is a successful turn completion."""
    return isinstance(event, TurnCompleted)


def get_thread_id(event: ThreadEvent) -> str | None:
    """Extract thread_id from a ThreadStarted event, or None for other events."""
    if isinstance(event, ThreadStarted):
        return event.thread_id
    return None
