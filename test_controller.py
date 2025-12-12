#!/usr/bin/env python3
"""
Test script for Claude Code iTerm2 Controller.

This will:
1. Open a new iTerm2 window
2. Start Claude Code in it
3. Send a simple prompt
4. Wait for and display the response

You'll be able to watch it happen in the new iTerm2 window.
"""

import asyncio
import iterm2
from claude_controller import ClaudeSessionManager, ClaudeSession
from session_parser import SessionParser


async def test_create_and_prompt(connection):
    """Test creating a session and sending a prompt."""
    project_path = "/Users/phaedrus/Projects/claude-iterm-controller"

    print("=" * 60)
    print("Claude Code iTerm2 Controller Test")
    print("=" * 60)

    print("\n1. Creating ClaudeSessionManager...")

    # We need to manually manage the connection since we're in an iterm2.run context
    app = await iterm2.async_get_app(connection)

    print("2. Creating new iTerm2 window and starting Claude...")

    # Create a new window
    window = await iterm2.Window.async_create(connection)
    tab = window.current_tab
    iterm_session = tab.current_session

    # Change to project directory
    await iterm_session.async_send_text(f"cd {project_path}\n")
    await asyncio.sleep(0.5)

    # Start Claude
    await iterm_session.async_send_text("claude\n")
    print("   Waiting for Claude to initialize...")
    await asyncio.sleep(4)  # Give Claude time to start

    # Create our session wrapper
    session = ClaudeSession(
        iterm_session=iterm_session,
        project_path=project_path
    )

    # Try to discover the session ID
    print("3. Discovering session ID from JSONL files...")
    session.refresh_state()

    if session.session_id:
        print(f"   Found session: {session.session_id[:16]}...")
    else:
        print("   Could not discover session ID yet (will retry)")

    # Send a test prompt using the fixed send_prompt method
    test_prompt = "What files are in this directory? Just list them briefly."
    print(f"\n4. Sending prompt: {test_prompt[:50]}...")
    await session.send_prompt(test_prompt)  # Now uses \x0d for Enter

    # Wait for response
    print("5. Waiting for response (watching JSONL file)...")
    response = await session.wait_for_response(timeout=60, idle_threshold=3.0)

    if response:
        print("\n" + "=" * 60)
        print("RESPONSE FROM CLAUDE:")
        print("=" * 60)
        print(response.content[:500])
        if len(response.content) > 500:
            print("... [truncated]")
        print("=" * 60)
    else:
        print("\n   Timeout waiting for response.")
        print("   Check the iTerm2 window to see what happened.")

    # Get full state
    print("\n6. Final session state:")
    state = session.get_state()
    if state:
        print(f"   Total messages: {len(state.messages)}")
        print(f"   Conversation turns: {len(state.conversation)}")

    print("\n" + "=" * 60)
    print("Test complete! The Claude session is still open in iTerm2.")
    print("You can interact with it manually or close the window.")
    print("=" * 60)


async def test_monitor_current_session(connection):
    """Test monitoring the currently running session (this one!)."""
    project_path = "/Users/phaedrus"  # Where this session is running

    print("=" * 60)
    print("Monitoring Current Claude Session")
    print("=" * 60)

    session_id = SessionParser.find_active_session(project_path, max_age_seconds=60)

    if not session_id:
        print("No active session found!")
        return

    print(f"\nActive session: {session_id}")

    project_dir = SessionParser.get_project_dir(project_path)
    state = SessionParser.parse_session(project_dir / f"{session_id}.jsonl")

    print(f"Messages: {len(state.messages)}")
    print(f"Conversation turns: {len(state.conversation)}")

    print("\nLast 3 conversation turns:")
    print("-" * 40)
    for msg in state.conversation[-3:]:
        role = "USER" if msg.role == "user" else "CLAUDE"
        content = msg.content[:100].replace('\n', ' ')
        print(f"[{role}] {content}...")

    print("\nThis is the session you're currently in!")


async def main(connection):
    """Main test runner."""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "monitor":
        await test_monitor_current_session(connection)
    else:
        await test_create_and_prompt(connection)


if __name__ == "__main__":
    iterm2.run_until_complete(main)
