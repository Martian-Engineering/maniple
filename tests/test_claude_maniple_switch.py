"""Tests for the claude-maniple-switch wrapper script."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_wrapper_loads_maniple_env_and_dispatches_provider(tmp_path: Path) -> None:
    """The wrapper should dispatch to the requested provider with ~/.maniple env overrides."""
    fake_switch = tmp_path / "fake-claude-switch.sh"
    _write_executable(
        fake_switch,
        """#!/usr/bin/env bash
claude-minimax() {
  echo "provider=minimax"
  echo "base_url=${ANTHROPIC_BASE_URL:-}"
  echo "auth=${ANTHROPIC_AUTH_TOKEN:-}"
  echo "arg1=${1:-}"
}
claude-kimi() { echo "provider=kimi"; }
claude-local() { echo "provider=local"; }
claude-official() { echo "provider=official"; }
""",
    )

    provider_env = tmp_path / ".env"
    provider_env.write_text(
        "export ANTHROPIC_BASE_URL=https://minimax.example.test/anthropic\n"
        "export ANTHROPIC_AUTH_TOKEN=test-token\n"
    )

    wrapper = Path(__file__).resolve().parent.parent / "scripts" / "claude-maniple-switch"
    env = os.environ.copy()
    env.update({
        "CLAUDE_SWITCH_SCRIPT": str(fake_switch),
        "CLAUDE_SWITCH_PROVIDER": "minimax",
        "MANIPLE_PROVIDER_ENV_FILE": str(provider_env),
    })

    result = subprocess.run(
        ["bash", str(wrapper), "--help"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    assert "provider=minimax" in result.stdout
    assert "base_url=https://minimax.example.test/anthropic" in result.stdout
    assert "auth=test-token" in result.stdout
    assert "arg1=--help" in result.stdout


def test_wrapper_applies_namespaced_provider_env_convention(tmp_path: Path) -> None:
    """Namespaced MANIPLE_PROVIDER_* vars should map to provider-specific aliases."""
    fake_switch = tmp_path / "fake-claude-switch.sh"
    _write_executable(
        fake_switch,
        """#!/usr/bin/env bash
claude-local() {
  echo "provider=local"
  echo "local_base_url=${LOCAL_BASE_URL:-}"
  echo "local_api_key=${LOCAL_API_KEY:-}"
  echo "local_model=${LOCAL_MODEL:-}"
}
claude-official() { echo "provider=official"; }
""",
    )

    provider_env = tmp_path / ".env"
    provider_env.write_text(
        "export MANIPLE_PROVIDER_LOCAL_BASE_URL=http://127.0.0.1:4000\n"
        "export MANIPLE_PROVIDER_LOCAL_API_KEY=local-token\n"
        "export MANIPLE_PROVIDER_LOCAL_MODEL=claude-local-model\n"
    )

    wrapper = Path(__file__).resolve().parent.parent / "scripts" / "claude-maniple-switch"
    env = os.environ.copy()
    env.pop("LOCAL_BASE_URL", None)
    env.pop("LOCAL_API_KEY", None)
    env.pop("LOCAL_MODEL", None)
    env.update({
        "CLAUDE_SWITCH_SCRIPT": str(fake_switch),
        "CLAUDE_SWITCH_PROVIDER": "local",
        "MANIPLE_PROVIDER_ENV_FILE": str(provider_env),
    })

    result = subprocess.run(
        ["bash", str(wrapper)],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    assert "provider=local" in result.stdout
    assert "local_base_url=http://127.0.0.1:4000" in result.stdout
    assert "local_api_key=local-token" in result.stdout
    assert "local_model=claude-local-model" in result.stdout
