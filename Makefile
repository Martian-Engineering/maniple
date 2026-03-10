.PHONY: install-commands install-commands-force install-systemd-user setup-provider-presets test sync help

help:
	@echo "Available targets:"
	@echo "  install-commands       Install slash commands to ~/.claude/commands/"
	@echo "  install-commands-force Install slash commands (overwrite existing)"
	@echo "  install-systemd-user   Install/update the user-level systemd service"
	@echo "  setup-provider-presets Install wrapper and create provider config templates"
	@echo "  test                   Run pytest"
	@echo "  sync                   Sync dependencies with uv"

install-commands:
	uv run scripts/install-commands.py

install-commands-force:
	uv run scripts/install-commands.py --force

install-systemd-user:
	bash scripts/install-systemd-user.sh

setup-provider-presets:
	bash scripts/setup-provider-presets.sh

test:
	uv run --group dev pytest

sync:
	uv sync --group dev
