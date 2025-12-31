"""
Read worker logs tool.

Provides read_worker_logs for getting conversation history from a Claude Code session.
"""

from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..utils import error_response, HINTS, get_session_or_error, CONVERSATION_PAGE_SIZE


def register_tools(mcp: FastMCP) -> None:
    """Register read_worker_logs tool on the MCP server."""

    @mcp.tool()
    async def read_worker_logs(
        ctx: Context[ServerSession, "AppContext"],
        session_id: str,
        pages: int = 1,
        offset: int = 0,
    ) -> dict:
        """
        Get conversation history from a Claude Code session with reverse pagination.

        Returns messages from the session's JSONL file, paginated from the end
        (most recent first by default). Each message includes text content,
        tool use names/inputs, and thinking blocks.

        Pagination works from the end of the conversation:
        - pages=1, offset=0: Returns the most recent page (default)
        - pages=3, offset=0: Returns the last 3 pages in chronological order
        - pages=2, offset=1: Returns 2 pages, skipping the most recent page

        Page size is 5 messages (each user or assistant message counts as 1).

        Args:
            session_id: ID of the target session.
                Accepts internal IDs, terminal IDs, or worker names.
            pages: Number of pages to return (default 1)
            offset: Number of pages to skip from the end (default 0 = most recent)

        Returns:
            Dict with:
                - messages: List of message dicts in chronological order
                - page_info: Pagination metadata (total_messages, total_pages, etc.)
                - session_id: The session ID
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Validate inputs
        if pages < 1:
            return error_response(
                "pages must be at least 1",
                hint="Use pages=1 to get the most recent page",
            )
        if offset < 0:
            return error_response(
                "offset must be non-negative",
                hint="Use offset=0 for most recent, offset=1 to skip most recent page, etc.",
            )

        # Look up session (accepts internal ID, terminal ID, or name)
        session = get_session_or_error(registry, session_id)
        if isinstance(session, dict):
            return session  # Error response

        jsonl_path = session.get_jsonl_path()
        if not jsonl_path or not jsonl_path.exists():
            return error_response(
                "No JSONL session file found - Claude may not have started yet",
                hint=HINTS["no_jsonl_file"],
                session_id=session_id,
                status=session.status.value,
            )

        # Parse the session state
        state = session.get_conversation_state()
        if not state:
            return error_response(
                "Could not parse session state",
                hint="The JSONL file may be corrupted. Try closing and spawning a new session",
                session_id=session_id,
                status=session.status.value,
            )

        # Get all messages (user and assistant with content)
        all_messages = state.conversation
        total_messages = len(all_messages)
        total_pages = (total_messages + CONVERSATION_PAGE_SIZE - 1) // CONVERSATION_PAGE_SIZE

        if total_messages == 0:
            return {
                "session_id": session_id,
                "messages": [],
                "page_info": {
                    "total_messages": 0,
                    "total_pages": 0,
                    "page_size": CONVERSATION_PAGE_SIZE,
                    "pages_returned": 0,
                    "offset": offset,
                },
            }

        # Calculate which messages to return using reverse pagination
        # offset=0 means start from the end, offset=1 means skip 1 page from end, etc.
        messages_to_skip_from_end = offset * CONVERSATION_PAGE_SIZE
        messages_to_take = pages * CONVERSATION_PAGE_SIZE

        # Calculate start and end indices
        # We're working backwards from the end
        end_index = total_messages - messages_to_skip_from_end
        start_index = max(0, end_index - messages_to_take)

        # Handle edge cases
        if end_index <= 0:
            return {
                "session_id": session_id,
                "messages": [],
                "page_info": {
                    "total_messages": total_messages,
                    "total_pages": total_pages,
                    "page_size": CONVERSATION_PAGE_SIZE,
                    "pages_returned": 0,
                    "offset": offset,
                    "note": f"Offset {offset} is beyond available messages",
                },
            }

        # Slice messages (already in chronological order)
        selected_messages = all_messages[start_index:end_index]

        # Convert to dicts
        message_dicts = [msg.to_dict() for msg in selected_messages]

        # Calculate actual pages returned
        pages_returned = (len(selected_messages) + CONVERSATION_PAGE_SIZE - 1) // CONVERSATION_PAGE_SIZE

        return {
            "session_id": session_id,
            "messages": message_dicts,
            "page_info": {
                "total_messages": total_messages,
                "total_pages": total_pages,
                "page_size": CONVERSATION_PAGE_SIZE,
                "pages_returned": pages_returned,
                "messages_returned": len(selected_messages),
                "offset": offset,
                "start_index": start_index,
                "end_index": end_index,
            },
        }
