#!/usr/bin/env python3
"""
Multi-session Claude Code Orchestrator

Example of running multiple Claude sessions and coordinating between them.

Usage:
    python orchestrator.py --project /path/to/project --prompt "Your task here"
"""

import argparse
import asyncio
import sys
from pathlib import Path

try:
    import iterm2
except ImportError:
    print("Install iterm2: pip install iterm2")
    sys.exit(1)

from claude_controller import ClaudeSessionManager, SessionParser


async def run_single_prompt(project_path: str, prompt: str, timeout: float = 120):
    """
    Open a new Claude session, send a prompt, wait for response, and print it.
    """
    print(f"Creating Claude session in: {project_path}")
    print(f"Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    print("-" * 50)

    async with ClaudeSessionManager() as manager:
        session = await manager.create_session(project_path)

        print("Waiting for Claude to initialize...")
        await asyncio.sleep(3)

        print("Sending prompt...")
        await session.send_prompt(prompt)

        print("Waiting for response...")
        response = await session.wait_for_response(timeout=timeout)

        if response:
            print("\n" + "=" * 50)
            print("RESPONSE:")
            print("=" * 50)
            print(response.content)
        else:
            print("Timeout waiting for response. Check the iTerm2 window.")

        # Keep the session open for manual interaction
        print("\n[Session remains open in iTerm2 for manual interaction]")


async def monitor_session(project_path: str, session_id: str = None):
    """
    Monitor an existing Claude session and print updates.
    """
    if not session_id:
        session_id = SessionParser.find_active_session(project_path)
        if not session_id:
            print(f"No active session found for: {project_path}")
            return

    project_dir = SessionParser.get_project_dir(project_path)
    jsonl_path = project_dir / f"{session_id}.jsonl"

    if not jsonl_path.exists():
        print(f"Session file not found: {jsonl_path}")
        return

    print(f"Monitoring session: {session_id[:16]}...")
    print(f"File: {jsonl_path}")
    print("-" * 50)

    last_msg_count = 0
    state = SessionParser.parse_session(jsonl_path)

    # Print existing messages
    for msg in state.messages:
        if msg.role in ("user", "assistant") and msg.content:
            prefix = "USER" if msg.role == "user" else "CLAUDE"
            content = msg.content[:200]
            print(f"[{prefix}] {content}{'...' if len(msg.content) > 200 else ''}")

    last_msg_count = len(state.messages)
    print("-" * 50)
    print("Watching for new messages (Ctrl+C to stop)...")

    try:
        while True:
            await asyncio.sleep(0.5)

            if not jsonl_path.exists():
                continue

            state = SessionParser.parse_session(jsonl_path)

            # Print new messages
            if len(state.messages) > last_msg_count:
                for msg in state.messages[last_msg_count:]:
                    if msg.role in ("user", "assistant") and msg.content:
                        prefix = "USER" if msg.role == "user" else "CLAUDE"
                        ts = msg.timestamp.strftime("%H:%M:%S")
                        content = msg.content[:200]
                        print(f"[{ts}] [{prefix}] {content}{'...' if len(msg.content) > 200 else ''}")

                last_msg_count = len(state.messages)

    except KeyboardInterrupt:
        print("\nStopped monitoring.")


async def list_sessions(project_path: str):
    """List all sessions for a project."""
    import time

    sessions = SessionParser.list_sessions(project_path)

    if not sessions:
        print(f"No sessions found for: {project_path}")
        return

    print(f"Sessions for: {project_path}")
    print("-" * 70)
    print(f"{'Session ID':<40} {'Age':<15} {'Messages'}")
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
        msg_count = len([m for m in state.messages if m.role in ("user", "assistant")])

        print(f"{session_id:<40} {age:<15} {msg_count}")


async def inject_prompt(project_path: str, prompt: str):
    """
    Inject a prompt into the most recently active Claude session.

    This finds the active iTerm2 session running Claude for the given project
    and sends the prompt to it.
    """
    print(f"Looking for active Claude session in: {project_path}")

    # Find active session from JSONL
    session_id = SessionParser.find_active_session(project_path, max_age_seconds=60)
    if not session_id:
        print("No recently active session found (< 60s old).")
        print("Make sure Claude Code is running in an iTerm2 window.")
        return

    print(f"Found active session: {session_id[:16]}...")

    async with ClaudeSessionManager() as manager:
        app = manager.app

        # Find all iTerm2 sessions and try to match
        for window in app.terminal_windows:
            for tab in window.tabs:
                for iterm_session in tab.sessions:
                    # Check if this session is running Claude in our project
                    try:
                        screen = await iterm_session.async_get_screen_contents()
                        content = "\n".join(
                            screen.line(i).string
                            for i in range(min(5, screen.number_of_lines))
                        )

                        # Simple heuristic: look for Claude's prompt character or project path
                        if ">" in content or project_path in content or "claude" in content.lower():
                            print(f"Found likely Claude session in window.")
                            print(f"Injecting prompt: {prompt[:50]}...")

                            await iterm_session.async_send_text(prompt + "\n")

                            print("Prompt sent!")
                            return

                    except Exception as e:
                        continue

        print("Could not find matching iTerm2 session.")
        print("Make sure Claude Code is running and visible.")


def main():
    parser = argparse.ArgumentParser(
        description="Claude Code iTerm2 Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run a prompt in a new session
    python orchestrator.py run --project . --prompt "List all Python files"

    # Monitor an existing session
    python orchestrator.py monitor --project .

    # List all sessions for a project
    python orchestrator.py list --project /path/to/project

    # Inject a prompt into an active session
    python orchestrator.py inject --project . --prompt "Now fix the bug"
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a prompt in a new session")
    run_parser.add_argument("--project", "-p", default=".", help="Project directory")
    run_parser.add_argument("--prompt", required=True, help="Prompt to send")
    run_parser.add_argument("--timeout", type=float, default=120, help="Response timeout")

    # Monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Monitor a session")
    monitor_parser.add_argument("--project", "-p", default=".", help="Project directory")
    monitor_parser.add_argument("--session", "-s", help="Session ID (optional)")

    # List command
    list_parser = subparsers.add_parser("list", help="List sessions")
    list_parser.add_argument("--project", "-p", default=".", help="Project directory")

    # Inject command
    inject_parser = subparsers.add_parser("inject", help="Inject prompt into active session")
    inject_parser.add_argument("--project", "-p", default=".", help="Project directory")
    inject_parser.add_argument("--prompt", required=True, help="Prompt to inject")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Resolve project path
    project_path = str(Path(args.project).resolve())

    if args.command == "run":
        iterm2.run_until_complete(
            run_single_prompt(project_path, args.prompt, args.timeout)
        )
    elif args.command == "monitor":
        iterm2.run_until_complete(
            monitor_session(project_path, getattr(args, 'session', None))
        )
    elif args.command == "list":
        iterm2.run_until_complete(list_sessions(project_path))
    elif args.command == "inject":
        iterm2.run_until_complete(inject_prompt(project_path, args.prompt))


if __name__ == "__main__":
    main()
