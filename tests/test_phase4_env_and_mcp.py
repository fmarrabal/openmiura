from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openmiura.channels import mcp_server
from openmiura.core.config import load_settings


def test_env_flags_override_config_values(monkeypatch, tmp_path: Path) -> None:
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        """
server:
  host: 127.0.0.1
  port: 8081
storage:
  db_path: data/audit.db
llm:
  provider: ollama
  base_url: http://127.0.0.1:11434
  model: qwen
runtime: {}
memory:
  enabled: true
  vault:
    enabled: false
mcp:
  enabled: false
  host: 0.0.0.0
  port: 9000
  sse_path: /mcp
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("OPENMIURA_VAULT_ENABLED", "true")
    monkeypatch.setenv("OPENMIURA_MCP_ENABLED", "1")

    settings = load_settings(str(cfg))

    assert settings.memory is not None
    assert settings.memory.vault.enabled is True
    assert settings.mcp is not None
    assert settings.mcp.enabled is True


def test_run_sse_uses_host_port_and_mount_path(monkeypatch) -> None:
    calls: list[dict] = []

    class _FakeServer:
        def run(self, **kwargs):
            calls.append(kwargs)

    class _FakeGateway:
        def __init__(self):
            self.settings = SimpleNamespace(
                mcp=SimpleNamespace(host="0.0.0.0", port=9123, sse_path="/events")
            )

    monkeypatch.setattr("openmiura.gateway.Gateway.from_config", lambda _: _FakeGateway())
    monkeypatch.setattr(mcp_server, "build_mcp_server", lambda gw: _FakeServer())

    rc = mcp_server.run_sse("configs/openmiura.yaml")

    assert rc == 0
    assert calls == [{"transport": "sse", "host": "0.0.0.0", "port": 9123, "mount_path": "/events"}]
