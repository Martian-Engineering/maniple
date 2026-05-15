"""Tests for HTTP CLI options and transport security configuration."""

import sys

import maniple_mcp.server as server_module


def test_build_transport_security_settings_defaults_to_fastmcp_behavior():
    """No explicit overrides should preserve FastMCP's built-in defaults."""
    settings = server_module.build_transport_security_settings(host="127.0.0.1")
    assert settings is None


def test_build_transport_security_settings_merges_localhost_defaults():
    """Explicit allow-lists on localhost should keep local defaults available."""
    settings = server_module.build_transport_security_settings(
        host="127.0.0.1",
        allowed_hosts=["100.64.0.45:8766"],
        allowed_origins=["https://manager.example.com"],
    )

    assert settings is not None
    assert settings.enable_dns_rebinding_protection is True
    assert "127.0.0.1:*" in settings.allowed_hosts
    assert "localhost:*" in settings.allowed_hosts
    assert "100.64.0.45:8766" in settings.allowed_hosts
    assert "http://127.0.0.1:*" in settings.allowed_origins
    assert "https://manager.example.com" in settings.allowed_origins


def test_build_transport_security_settings_can_disable_rebinding_protection():
    """The explicit disable flag should override localhost auto-protection."""
    settings = server_module.build_transport_security_settings(
        host="127.0.0.1",
        disable_dns_rebinding_protection=True,
    )

    assert settings is not None
    assert settings.enable_dns_rebinding_protection is False
    assert settings.allowed_hosts == []
    assert settings.allowed_origins == []


def test_run_server_http_uses_custom_host_and_security(monkeypatch):
    """HTTP mode should forward host and transport security to FastMCP."""
    captured: dict[str, object] = {}

    class DummyServer:
        def run(self, *, transport: str) -> None:
            captured["transport"] = transport

    def fake_create_mcp_server(**kwargs):
        captured.update(kwargs)
        return DummyServer()

    monkeypatch.setattr(server_module, "create_mcp_server", fake_create_mcp_server)
    monkeypatch.setattr(server_module, "configure_logging", lambda: "/tmp/maniple.log")

    server_module.run_server(
        transport="streamable-http",
        host="100.64.0.45",
        port=8766,
        allowed_hosts=["100.64.0.45:8766"],
    )

    assert captured["host"] == "100.64.0.45"
    assert captured["port"] == 8766
    assert captured["enable_poller"] is True
    assert captured["transport"] == "streamable-http"
    settings = captured["transport_security"]
    assert settings is not None
    assert settings.allowed_hosts == ["100.64.0.45:8766"]


def test_main_parses_http_host_security_flags(monkeypatch):
    """CLI parsing should pass host and allow-lists through to run_server."""
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "maniple",
            "--http",
            "--host",
            "100.64.0.45",
            "--port",
            "8766",
            "--allow-host",
            "100.64.0.45:8766",
            "--allow-origin",
            "https://manager.example.com",
            "--disable-dns-rebinding-protection",
        ],
    )
    monkeypatch.setattr(server_module, "run_server", lambda **kwargs: captured.update(kwargs))

    server_module.main()

    assert captured == {
        "transport": "streamable-http",
        "host": "100.64.0.45",
        "port": 8766,
        "allowed_hosts": ["100.64.0.45:8766"],
        "allowed_origins": ["https://manager.example.com"],
        "disable_dns_rebinding_protection": True,
    }
