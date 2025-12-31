#!/usr/bin/env python3
"""
Install slash commands from this repository to the user's global Claude commands.

Copies commands/*.md to ~/.claude/commands/ for global availability.

Usage:
    uv run scripts/install-commands.py [--force] [--dry-run]

Options:
    --force    Overwrite existing commands without prompting
    --dry-run  Show what would be done without making changes
"""

import argparse
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Install slash commands to ~/.claude/commands/"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing commands without prompting"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be done without making changes"
    )
    args = parser.parse_args()

    # Find repo root (where this script lives is scripts/, go up one level)
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    source_dir = repo_root / "commands"
    target_dir = Path.home() / ".claude" / "commands"

    # Verify source directory exists
    if not source_dir.exists():
        print(f"Error: Source directory not found: {source_dir}")
        sys.exit(1)

    # Find all command files
    commands = list(source_dir.glob("*.md"))
    if not commands:
        print(f"No command files found in {source_dir}")
        sys.exit(0)

    print(f"Found {len(commands)} command(s) to install:")
    for cmd in commands:
        print(f"  - {cmd.name}")
    print()

    # Create target directory if needed
    if not target_dir.exists():
        if args.dry_run:
            print(f"Would create directory: {target_dir}")
        else:
            target_dir.mkdir(parents=True)
            print(f"Created directory: {target_dir}")

    # Copy each command
    installed = 0
    skipped = 0
    for cmd in commands:
        target = target_dir / cmd.name

        if target.exists() and not args.force:
            if args.dry_run:
                print(f"Would skip (exists): {cmd.name}")
                skipped += 1
                continue

            # Prompt user
            response = input(f"Overwrite existing {cmd.name}? [y/N] ").strip().lower()
            if response != "y":
                print(f"  Skipped: {cmd.name}")
                skipped += 1
                continue

        if args.dry_run:
            print(f"Would install: {cmd.name} -> {target}")
        else:
            shutil.copy2(cmd, target)
            print(f"Installed: {cmd.name}")
        installed += 1

    # Summary
    print()
    if args.dry_run:
        print(f"Dry run complete. Would install {installed}, skip {skipped}.")
    else:
        print(f"Done. Installed {installed}, skipped {skipped}.")
        if installed > 0:
            print(f"\nCommands are now available globally in Claude Code.")


if __name__ == "__main__":
    main()
