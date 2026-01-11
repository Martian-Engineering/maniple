"""Tests for Codex JSONL schema parsing."""

import pytest
import msgspec

from claude_team_mcp.schemas import codex
from claude_team_mcp.schemas.codex import (
    AgentMessageItem,
    CommandExecutionItem,
    FileChangeItem,
    FileUpdateChange,
    ItemCompleted,
    ItemStarted,
    ItemUpdated,
    McpToolCallItem,
    McpToolCallItemError,
    McpToolCallItemResult,
    ReasoningItem,
    StreamError,
    ThreadError,
    ThreadStarted,
    TodoItem,
    TodoListItem,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
    Usage,
    WebSearchItem,
    decode_event,
    get_thread_id,
    is_turn_complete,
    is_turn_successful,
)


# --- Sample JSONL fixtures (matching real Codex output format) ---


THREAD_STARTED_JSON = '{"type":"thread.started","thread_id":"thread_abc123xyz"}'

TURN_STARTED_JSON = '{"type":"turn.started"}'

TURN_COMPLETED_JSON = """{
    "type": "turn.completed",
    "usage": {
        "input_tokens": 1500,
        "cached_input_tokens": 500,
        "output_tokens": 200
    }
}"""

TURN_FAILED_JSON = """{
    "type": "turn.failed",
    "error": {
        "message": "Rate limit exceeded"
    }
}"""

STREAM_ERROR_JSON = '{"type":"error","message":"Reconnecting... 1/3"}'

AGENT_MESSAGE_ITEM_JSON = """{
    "type": "item.completed",
    "item": {
        "type": "agent_message",
        "id": "msg_001",
        "text": "I'll help you with that task."
    }
}"""

COMMAND_EXECUTION_ITEM_JSON = """{
    "type": "item.completed",
    "item": {
        "type": "command_execution",
        "id": "cmd_001",
        "command": "ls -la",
        "aggregated_output": "total 16\\ndrwxr-xr-x  4 user  staff  128 Jan 11 10:00 .\\n",
        "exit_code": 0,
        "status": "completed"
    }
}"""

COMMAND_FAILED_JSON = """{
    "type": "item.completed",
    "item": {
        "type": "command_execution",
        "id": "cmd_002",
        "command": "rm -rf /nonexistent",
        "aggregated_output": "rm: /nonexistent: No such file or directory",
        "exit_code": 1,
        "status": "failed"
    }
}"""

FILE_CHANGE_ITEM_JSON = """{
    "type": "item.completed",
    "item": {
        "type": "file_change",
        "id": "file_001",
        "changes": [
            {"path": "src/main.py", "kind": "update"},
            {"path": "src/utils.py", "kind": "add"}
        ],
        "status": "completed"
    }
}"""

MCP_TOOL_CALL_JSON = """{
    "type": "item.completed",
    "item": {
        "type": "mcp_tool_call",
        "id": "mcp_001",
        "server": "filesystem",
        "tool": "read_file",
        "arguments": {"path": "/tmp/test.txt"},
        "result": {
            "content": [{"type": "text", "text": "file contents"}],
            "structured_content": null
        },
        "error": null,
        "status": "completed"
    }
}"""

MCP_TOOL_ERROR_JSON = """{
    "type": "item.completed",
    "item": {
        "type": "mcp_tool_call",
        "id": "mcp_002",
        "server": "database",
        "tool": "query",
        "arguments": {"sql": "SELECT * FROM users"},
        "result": null,
        "error": {"message": "Connection refused"},
        "status": "failed"
    }
}"""

WEB_SEARCH_JSON = """{
    "type": "item.started",
    "item": {
        "type": "web_search",
        "id": "search_001",
        "query": "python msgspec documentation"
    }
}"""

TODO_LIST_JSON = """{
    "type": "item.completed",
    "item": {
        "type": "todo_list",
        "id": "todo_001",
        "items": [
            {"text": "Read the file", "completed": true},
            {"text": "Parse the data", "completed": true},
            {"text": "Write output", "completed": false}
        ]
    }
}"""

REASONING_ITEM_JSON = """{
    "type": "item.started",
    "item": {
        "type": "reasoning",
        "id": "reason_001",
        "text": "Let me think about how to approach this..."
    }
}"""


class TestDecodeEvent:
    """Tests for decode_event function."""

    def test_decode_thread_started(self):
        """Should decode ThreadStarted event."""
        event = decode_event(THREAD_STARTED_JSON)
        assert isinstance(event, ThreadStarted)
        assert event.thread_id == "thread_abc123xyz"

    def test_decode_turn_started(self):
        """Should decode TurnStarted event."""
        event = decode_event(TURN_STARTED_JSON)
        assert isinstance(event, TurnStarted)

    def test_decode_turn_completed(self):
        """Should decode TurnCompleted with usage stats."""
        event = decode_event(TURN_COMPLETED_JSON)
        assert isinstance(event, TurnCompleted)
        assert event.usage.input_tokens == 1500
        assert event.usage.cached_input_tokens == 500
        assert event.usage.output_tokens == 200

    def test_decode_turn_failed(self):
        """Should decode TurnFailed with error message."""
        event = decode_event(TURN_FAILED_JSON)
        assert isinstance(event, TurnFailed)
        assert event.error.message == "Rate limit exceeded"

    def test_decode_stream_error(self):
        """Should decode StreamError (reconnection messages, etc.)."""
        event = decode_event(STREAM_ERROR_JSON)
        assert isinstance(event, StreamError)
        assert "Reconnecting" in event.message

    def test_decode_bytes_input(self):
        """Should accept bytes input as well as string."""
        event = decode_event(THREAD_STARTED_JSON.encode("utf-8"))
        assert isinstance(event, ThreadStarted)
        assert event.thread_id == "thread_abc123xyz"

    def test_invalid_json_raises_error(self):
        """Should raise DecodeError for malformed JSON."""
        with pytest.raises(msgspec.DecodeError):
            decode_event("{invalid json")

    def test_unknown_type_raises_error(self):
        """Should raise DecodeError for unknown event type."""
        with pytest.raises(msgspec.DecodeError):
            decode_event('{"type":"unknown.event"}')


class TestItemEvents:
    """Tests for item lifecycle events (started, updated, completed)."""

    def test_decode_item_started(self):
        """Should decode ItemStarted event."""
        event = decode_event(WEB_SEARCH_JSON)
        assert isinstance(event, ItemStarted)
        assert isinstance(event.item, WebSearchItem)
        assert event.item.query == "python msgspec documentation"

    def test_decode_item_updated(self):
        """Should decode ItemUpdated event."""
        json_data = REASONING_ITEM_JSON.replace("item.started", "item.updated")
        event = decode_event(json_data)
        assert isinstance(event, ItemUpdated)
        assert isinstance(event.item, ReasoningItem)

    def test_decode_item_completed(self):
        """Should decode ItemCompleted event."""
        event = decode_event(AGENT_MESSAGE_ITEM_JSON)
        assert isinstance(event, ItemCompleted)
        assert isinstance(event.item, AgentMessageItem)


class TestItemTypes:
    """Tests for different ThreadItem types."""

    def test_agent_message_item(self):
        """Should parse AgentMessageItem correctly."""
        event = decode_event(AGENT_MESSAGE_ITEM_JSON)
        assert isinstance(event, ItemCompleted)
        item = event.item
        assert isinstance(item, AgentMessageItem)
        assert item.id == "msg_001"
        assert "help you" in item.text

    def test_command_execution_item_success(self):
        """Should parse successful CommandExecutionItem."""
        event = decode_event(COMMAND_EXECUTION_ITEM_JSON)
        item = event.item
        assert isinstance(item, CommandExecutionItem)
        assert item.id == "cmd_001"
        assert item.command == "ls -la"
        assert item.exit_code == 0
        assert item.status == "completed"

    def test_command_execution_item_failure(self):
        """Should parse failed CommandExecutionItem."""
        event = decode_event(COMMAND_FAILED_JSON)
        item = event.item
        assert isinstance(item, CommandExecutionItem)
        assert item.exit_code == 1
        assert item.status == "failed"

    def test_file_change_item(self):
        """Should parse FileChangeItem with changes list."""
        event = decode_event(FILE_CHANGE_ITEM_JSON)
        item = event.item
        assert isinstance(item, FileChangeItem)
        assert len(item.changes) == 2
        assert item.changes[0].path == "src/main.py"
        assert item.changes[0].kind == "update"
        assert item.changes[1].kind == "add"

    def test_mcp_tool_call_success(self):
        """Should parse successful McpToolCallItem."""
        event = decode_event(MCP_TOOL_CALL_JSON)
        item = event.item
        assert isinstance(item, McpToolCallItem)
        assert item.server == "filesystem"
        assert item.tool == "read_file"
        assert item.arguments == {"path": "/tmp/test.txt"}
        assert item.result is not None
        assert item.error is None
        assert item.status == "completed"

    def test_mcp_tool_call_error(self):
        """Should parse failed McpToolCallItem."""
        event = decode_event(MCP_TOOL_ERROR_JSON)
        item = event.item
        assert isinstance(item, McpToolCallItem)
        assert item.result is None
        assert item.error is not None
        assert item.error.message == "Connection refused"
        assert item.status == "failed"

    def test_web_search_item(self):
        """Should parse WebSearchItem."""
        event = decode_event(WEB_SEARCH_JSON)
        item = event.item
        assert isinstance(item, WebSearchItem)
        assert item.query == "python msgspec documentation"

    def test_todo_list_item(self):
        """Should parse TodoListItem with items."""
        event = decode_event(TODO_LIST_JSON)
        item = event.item
        assert isinstance(item, TodoListItem)
        assert len(item.items) == 3
        assert item.items[0].text == "Read the file"
        assert item.items[0].completed is True
        assert item.items[2].completed is False

    def test_reasoning_item(self):
        """Should parse ReasoningItem."""
        event = decode_event(REASONING_ITEM_JSON)
        item = event.item
        assert isinstance(item, ReasoningItem)
        assert "think about" in item.text


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_is_turn_complete_for_completed(self):
        """is_turn_complete should return True for TurnCompleted."""
        event = decode_event(TURN_COMPLETED_JSON)
        assert is_turn_complete(event) is True

    def test_is_turn_complete_for_failed(self):
        """is_turn_complete should return True for TurnFailed."""
        event = decode_event(TURN_FAILED_JSON)
        assert is_turn_complete(event) is True

    def test_is_turn_complete_for_other_events(self):
        """is_turn_complete should return False for non-turn events."""
        event = decode_event(THREAD_STARTED_JSON)
        assert is_turn_complete(event) is False

        event = decode_event(AGENT_MESSAGE_ITEM_JSON)
        assert is_turn_complete(event) is False

    def test_is_turn_successful_for_completed(self):
        """is_turn_successful should return True only for TurnCompleted."""
        event = decode_event(TURN_COMPLETED_JSON)
        assert is_turn_successful(event) is True

    def test_is_turn_successful_for_failed(self):
        """is_turn_successful should return False for TurnFailed."""
        event = decode_event(TURN_FAILED_JSON)
        assert is_turn_successful(event) is False

    def test_get_thread_id_from_thread_started(self):
        """get_thread_id should extract ID from ThreadStarted."""
        event = decode_event(THREAD_STARTED_JSON)
        assert get_thread_id(event) == "thread_abc123xyz"

    def test_get_thread_id_from_other_events(self):
        """get_thread_id should return None for non-ThreadStarted events."""
        event = decode_event(TURN_COMPLETED_JSON)
        assert get_thread_id(event) is None


class TestUsageStruct:
    """Tests for Usage struct."""

    def test_usage_fields(self):
        """Usage should have all required token count fields."""
        event = decode_event(TURN_COMPLETED_JSON)
        usage = event.usage
        assert isinstance(usage, Usage)
        assert hasattr(usage, "input_tokens")
        assert hasattr(usage, "cached_input_tokens")
        assert hasattr(usage, "output_tokens")


class TestThreadErrorStruct:
    """Tests for ThreadError struct."""

    def test_thread_error_message(self):
        """ThreadError should contain error message."""
        event = decode_event(TURN_FAILED_JSON)
        assert isinstance(event.error, ThreadError)
        assert event.error.message == "Rate limit exceeded"


class TestModuleExports:
    """Test that all expected types are exported from the module."""

    def test_decode_event_exported(self):
        """decode_event should be accessible from module."""
        assert hasattr(codex, "decode_event")
        assert callable(codex.decode_event)

    def test_helper_functions_exported(self):
        """Helper functions should be accessible."""
        assert hasattr(codex, "is_turn_complete")
        assert hasattr(codex, "is_turn_successful")
        assert hasattr(codex, "get_thread_id")

    def test_event_types_exported(self):
        """All event types should be accessible."""
        for event_type in [
            "ThreadStarted",
            "TurnStarted",
            "TurnCompleted",
            "TurnFailed",
            "ItemStarted",
            "ItemUpdated",
            "ItemCompleted",
            "StreamError",
        ]:
            assert hasattr(codex, event_type)

    def test_item_types_exported(self):
        """All item types should be accessible."""
        for item_type in [
            "AgentMessageItem",
            "ReasoningItem",
            "CommandExecutionItem",
            "FileChangeItem",
            "McpToolCallItem",
            "WebSearchItem",
            "TodoListItem",
        ]:
            assert hasattr(codex, item_type)


class TestRealWorldScenarios:
    """Test parsing sequences that mimic real Codex output."""

    def test_full_session_sequence(self):
        """Should parse a sequence of events like a real session."""
        events_json = [
            THREAD_STARTED_JSON,
            TURN_STARTED_JSON,
            REASONING_ITEM_JSON,
            AGENT_MESSAGE_ITEM_JSON,
            COMMAND_EXECUTION_ITEM_JSON,
            TURN_COMPLETED_JSON,
        ]

        thread_id = None
        turn_complete = False

        for json_line in events_json:
            event = decode_event(json_line)
            if isinstance(event, ThreadStarted):
                thread_id = event.thread_id
            if isinstance(event, TurnCompleted):
                turn_complete = True

        assert thread_id == "thread_abc123xyz"
        assert turn_complete is True

    def test_failed_session_sequence(self):
        """Should parse a sequence ending in failure."""
        events_json = [
            THREAD_STARTED_JSON,
            TURN_STARTED_JSON,
            TURN_FAILED_JSON,
        ]

        turn_failed = False
        error_message = None

        for json_line in events_json:
            event = decode_event(json_line)
            if isinstance(event, TurnFailed):
                turn_failed = True
                error_message = event.error.message

        assert turn_failed is True
        assert error_message == "Rate limit exceeded"
