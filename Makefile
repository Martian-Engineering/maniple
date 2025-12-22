.PHONY: install-commands install-commands-force test sync help

help:
	@echo "Available targets:"
	@echo "  install-commands       Install slash commands to ~/.claude/commands/"
	@echo "  install-commands-force Install slash commands (overwrite existing)"
	@echo "  test                   Run pytest"
	@echo "  sync                   Sync dependencies with uv"

install-commands:
	uv run scripts/install-commands.py

install-commands-force:
	uv run scripts/install-commands.py --force

test:
	uv run --group dev pytest

sync:
	uv sync --group dev
