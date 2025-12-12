#!/usr/bin/env python3
"""
Claude Code Session Parser

Parse Claude Code session JSONL files to read conversation state.
No external dependencies required.

Usage:
    from session_parser import SessionParser, SessionState

    # List sessions for a project
    sessions = SessionParser.list_sessions("/path/to/project")

    # Parse a specific session
    state = SessionParser.parse_session(Path("~/.claude/projects/.../session.jsonl"))

    # Get conversation details
    print(state.last_assistant_message.content)
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Iterator
from datetime import datetime


@dataclass
class Message:
    """A single message from the Claude session."""
    uuid: str
    parent_uuid: Optional[str]
    role: str  # "user" or "assistant"
    content: str  # Extracted text content
    raw_content: list  # Full content array (may include tool_use, thinking, etc.)
    timestamp: datetime
    message_type: str  # "user", "assistant", "file-history-snapshot", etc.
    tool_uses: list = field(default_factory=list)
    is_thinking: bool = False

    def __repr__(self):
        content_preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"Message(role={self.role!r}, content={content_preview!r})"


@dataclass
class SessionState:
    """Current state of a Claude session parsed from JSONL."""
    session_id: str
    project_path: str
    jsonl_path: Path
    messages: list[Message] = field(default_factory=list)
    last_modified: float = 0

    @property
    def last_user_message(self) -> Optional[Message]:
        """Get the most recent user message."""
        for msg in reversed(self.messages):
            if msg.role == "user":
                return msg
        return None

    @property
    def last_assistant_message(self) -> Optional[Message]:
        """Get the most recent assistant message with text content."""
        for msg in reversed(self.messages):
            if msg.role == "assistant" and msg.content:
                return msg
        return None

    @property
    def conversation(self) -> list[Message]:
        """Get only user/assistant messages with content (no tool results, etc.)."""
        return [m for m in self.messages if m.role in ("user", "assistant") and m.content]

    @property
    def is_processing(self) -> bool:
        """Check if Claude appears to be processing (last msg has tool_use)."""
        if not self.messages:
            return False
        last = self.messages[-1]
        return bool(last.tool_uses)

    def __repr__(self):
        return f"SessionState(id={self.session_id[:8]}..., messages={len(self.messages)})"


class SessionParser:
    """Parse Claude Code session JSONL files."""

    CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

    @classmethod
    def get_project_slug(cls, project_path: str) -> str:
        """
        Convert a project path to Claude's directory slug format.

        Claude replaces / with - for the directory name.
        Example: /Users/phaedrus -> -Users-phaedrus
        """
        return project_path.replace("/", "-")

    @classmethod
    def get_project_dir(cls, project_path: str) -> Path:
        """Get the Claude projects directory for a given project path."""
        slug = cls.get_project_slug(project_path)
        return cls.CLAUDE_PROJECTS_DIR / slug

    @classmethod
    def list_sessions(cls, project_path: str) -> list[tuple[str, Path, float]]:
        """
        List all sessions for a project, sorted by modification time (newest first).

        Args:
            project_path: Absolute path to the project directory

        Returns:
            List of (session_id, jsonl_path, mtime) tuples
        """
        project_dir = cls.get_project_dir(project_path)
        if not project_dir.exists():
            return []

        sessions = []
        for jsonl_file in project_dir.glob("*.jsonl"):
            # Skip agent-* files (subagents)
            if jsonl_file.name.startswith("agent-"):
                continue
            session_id = jsonl_file.stem
            mtime = jsonl_file.stat().st_mtime
            sessions.append((session_id, jsonl_file, mtime))

        return sorted(sessions, key=lambda x: x[2], reverse=True)

    @classmethod
    def find_active_session(cls, project_path: str, max_age_seconds: int = 300) -> Optional[str]:
        """
        Find the most recently active session (modified within max_age_seconds).

        This helps identify which session corresponds to a running Claude instance.

        Args:
            project_path: Absolute path to the project directory
            max_age_seconds: Maximum age in seconds to consider "active"

        Returns:
            Session ID string, or None if no active session found
        """
        sessions = cls.list_sessions(project_path)
        if not sessions:
            return None

        session_id, _, mtime = sessions[0]
        if time.time() - mtime < max_age_seconds:
            return session_id
        return None

    @classmethod
    def parse_session(cls, jsonl_path: Path) -> SessionState:
        """
        Parse a session JSONL file into a SessionState object.

        Args:
            jsonl_path: Path to the .jsonl session file

        Returns:
            SessionState with parsed messages
        """
        messages = []
        session_id = jsonl_path.stem
        project_path = ""

        with open(jsonl_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = entry.get("type", "")

                # Skip non-message entries
                if msg_type == "file-history-snapshot":
                    continue

                # Extract project path from cwd if available
                if "cwd" in entry and not project_path:
                    project_path = entry["cwd"]

                # Parse message content
                message_data = entry.get("message", {})
                role = message_data.get("role", "")
                raw_content = message_data.get("content", [])

                # Handle string content (user messages)
                if isinstance(raw_content, str):
                    text_content = raw_content
                    tool_uses = []
                    is_thinking = False
                else:
                    # Extract text and tool_use from content array
                    text_parts = []
                    tool_uses = []
                    is_thinking = False

                    for item in raw_content:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                text_parts.append(item.get("text", ""))
                            elif item.get("type") == "tool_use":
                                tool_uses.append({
                                    "id": item.get("id"),
                                    "name": item.get("name"),
                                    "input": item.get("input", {})
                                })
                            elif item.get("type") == "thinking":
                                is_thinking = True

                    text_content = "\n".join(text_parts)

                # Parse timestamp
                ts_str = entry.get("timestamp", "")
                try:
                    timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except:
                    timestamp = datetime.now()

                msg = Message(
                    uuid=entry.get("uuid", ""),
                    parent_uuid=entry.get("parentUuid"),
                    role=role,
                    content=text_content,
                    raw_content=raw_content if isinstance(raw_content, list) else [raw_content],
                    timestamp=timestamp,
                    message_type=msg_type,
                    tool_uses=tool_uses,
                    is_thinking=is_thinking
                )
                messages.append(msg)

        return SessionState(
            session_id=session_id,
            project_path=project_path,
            jsonl_path=jsonl_path,
            messages=messages,
            last_modified=jsonl_path.stat().st_mtime if jsonl_path.exists() else 0
        )

    @classmethod
    def watch_session(cls, jsonl_path: Path, poll_interval: float = 0.5) -> Iterator[SessionState]:
        """
        Generator that yields updated SessionState whenever the file changes.

        Args:
            jsonl_path: Path to the session JSONL file
            poll_interval: Seconds between checks

        Yields:
            SessionState objects when changes detected
        """
        import time

        last_mtime = 0
        last_size = 0

        while True:
            try:
                stat = jsonl_path.stat()
                if stat.st_mtime > last_mtime or stat.st_size > last_size:
                    last_mtime = stat.st_mtime
                    last_size = stat.st_size
                    yield cls.parse_session(jsonl_path)
            except FileNotFoundError:
                pass

            time.sleep(poll_interval)


# --- CLI ---

def main():
    """Command-line interface for session parsing."""
    import argparse

    parser = argparse.ArgumentParser(description="Parse Claude Code session files")
    parser.add_argument("--project", "-p", default=".", help="Project directory path")
    parser.add_argument("--session", "-s", help="Specific session ID to parse")
    parser.add_argument("--watch", "-w", action="store_true", help="Watch for changes")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    project_path = str(Path(args.project).resolve())

    if args.session:
        # Parse specific session
        project_dir = SessionParser.get_project_dir(project_path)
        jsonl_path = project_dir / f"{args.session}.jsonl"

        if not jsonl_path.exists():
            print(f"Session not found: {jsonl_path}")
            return 1

        if args.watch:
            print(f"Watching session: {args.session}")
            for state in SessionParser.watch_session(jsonl_path):
                if args.json:
                    print(json.dumps({
                        "messages": len(state.messages),
                        "last_user": state.last_user_message.content[:100] if state.last_user_message else None,
                        "last_assistant": state.last_assistant_message.content[:100] if state.last_assistant_message else None,
                    }))
                else:
                    print(f"[{len(state.messages)} messages] Last: {state.last_assistant_message.content[:60] if state.last_assistant_message else 'N/A'}...")
        else:
            state = SessionParser.parse_session(jsonl_path)
            if args.json:
                print(json.dumps({
                    "session_id": state.session_id,
                    "project_path": state.project_path,
                    "message_count": len(state.messages),
                    "conversation": [
                        {"role": m.role, "content": m.content, "timestamp": m.timestamp.isoformat()}
                        for m in state.conversation
                    ]
                }, indent=2))
            else:
                print(f"Session: {state.session_id}")
                print(f"Project: {state.project_path}")
                print(f"Messages: {len(state.messages)}")
                print("\nConversation:")
                for msg in state.conversation[-10:]:
                    prefix = "USER" if msg.role == "user" else "CLAUDE"
                    content = msg.content[:100]
                    print(f"  [{prefix}] {content}{'...' if len(msg.content) > 100 else ''}")

    else:
        # List sessions
        sessions = SessionParser.list_sessions(project_path)

        if not sessions:
            print(f"No sessions found for: {project_path}")
            print(f"(Looking in: {SessionParser.get_project_dir(project_path)})")
            return 1

        if args.json:
            print(json.dumps([
                {"id": sid, "path": str(path), "mtime": mtime}
                for sid, path, mtime in sessions
            ], indent=2))
        else:
            print(f"Sessions for: {project_path}")
            print("-" * 70)

            for session_id, jsonl_path, mtime in sessions[:20]:
                age_seconds = time.time() - mtime
                if age_seconds < 60:
                    age = f"{age_seconds:.0f}s ago"
                elif age_seconds < 3600:
                    age = f"{age_seconds/60:.0f}m ago"
                elif age_seconds < 86400:
                    age = f"{age_seconds/3600:.1f}h ago"
                else:
                    age = f"{age_seconds/86400:.1f}d ago"

                state = SessionParser.parse_session(jsonl_path)
                msg_count = len(state.conversation)

                print(f"{session_id[:36]:<38} {age:<12} {msg_count:>3} msgs")

    return 0


if __name__ == "__main__":
    exit(main())
