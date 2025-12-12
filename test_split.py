#!/usr/bin/env python3
"""
Test window splitting functionality.

Creates a window and splits it into multiple panes,
demonstrating vertical and horizontal splits.
"""

import asyncio
import iterm2
from primitives import send_prompt, read_screen_text, KEYS


async def main(connection):
    print("Testing iTerm2 window splitting...")
    print("=" * 60)

    app = await iterm2.async_get_app(connection)

    # Create a new window
    print("\n1. Creating new window...")
    window = await iterm2.Window.async_create(connection)
    main_session = window.current_tab.current_session

    # Label the main session
    await send_prompt(main_session, "echo 'PANE 1 - Main'", submit=True)
    await asyncio.sleep(0.3)

    # Split vertically (side by side)
    print("2. Splitting vertically (creating PANE 2 to the right)...")
    pane2 = await main_session.async_split_pane(vertical=True, before=False)
    await send_prompt(pane2, "echo 'PANE 2 - Right'", submit=True)
    await asyncio.sleep(0.3)

    # Split pane2 horizontally (stacked)
    print("3. Splitting PANE 2 horizontally (creating PANE 3 below it)...")
    pane3 = await pane2.async_split_pane(vertical=False, before=False)
    await send_prompt(pane3, "echo 'PANE 3 - Bottom Right'", submit=True)
    await asyncio.sleep(0.3)

    # Split main_session horizontally
    print("4. Splitting PANE 1 horizontally (creating PANE 4 below it)...")
    pane4 = await main_session.async_split_pane(vertical=False, before=False)
    await send_prompt(pane4, "echo 'PANE 4 - Bottom Left'", submit=True)
    await asyncio.sleep(0.3)

    print("\n" + "=" * 60)
    print("Created 4-pane layout:")
    print("""
    ┌─────────────────┬─────────────────┐
    │     PANE 1      │     PANE 2      │
    │   (Main/Left)   │    (Right)      │
    ├─────────────────┼─────────────────┤
    │     PANE 4      │     PANE 3      │
    │  (Bottom Left)  │ (Bottom Right)  │
    └─────────────────┴─────────────────┘
    """)

    # Demonstrate sending commands to specific panes
    print("5. Demonstrating control of individual panes...")
    await asyncio.sleep(0.5)

    await send_prompt(main_session, "pwd", submit=True)
    await send_prompt(pane2, "ls", submit=True)
    await send_prompt(pane3, "date", submit=True)
    await send_prompt(pane4, "whoami", submit=True)

    await asyncio.sleep(1)

    # Read content from each pane
    print("\n6. Reading content from each pane:")
    print("-" * 40)

    for i, (name, session) in enumerate([
        ("PANE 1", main_session),
        ("PANE 2", pane2),
        ("PANE 3", pane3),
        ("PANE 4", pane4)
    ], 1):
        screen = await read_screen_text(session)
        lines = [l for l in screen.split('\n') if l.strip()][-3:]
        print(f"{name}:")
        for line in lines:
            print(f"  {line[:60]}")
        print()

    print("=" * 60)
    print("Window splitting test complete!")
    print("Check the new iTerm2 window to see the 4-pane layout.")

    # Return the sessions for further use
    return {
        'window': window,
        'panes': [main_session, pane2, pane3, pane4]
    }


if __name__ == "__main__":
    iterm2.run_until_complete(main)
