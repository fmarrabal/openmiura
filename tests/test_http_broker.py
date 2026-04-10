from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.config import load_settings
from openmiura.core.schema import OutboundMessage
from openmiura.gateway import Gateway


def _write_config(path: Path, *, broker_enabled: bool = True) -> None:
    db_path = (path.parent / "audit.db").as_posix()
    sandbox_dir = (path.parent / "sandbox").as_posix()
    path.write_text(
        f'''\
server:
  host: "127.0.0.1"
  port: 8081
storage:
  db_path: "{db_path}"
llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5:7b-instruct"
runtime:
  history_limit: 4
agents:
  default:
    system_prompt: "base"
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
broker:
  enabled: {str(broker_enabled).lower()}
  base_path: "/broker"
  token: ""
''',
        encoding="utf-8",
    )


def test_broker_env_override(monkeypatch, tmp_path: Path) -> None:
    cfg = tmp_path / "openmiura.yaml"
    _write_config(cfg, broker_enabled=False)
    monkeypatch.setenv("OPENMIURA_BROKER_ENABLED", "true")
    settings = load_settings(str(cfg))
    assert settings.broker is not None
    assert settings.broker.enabled is True


def test_broker_tools_and_tool_call(tmp_path: Path) -> None:
    cfg = tmp_path / "openmiura.yaml"
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        tools_response = client.get("/broker/tools")
        assert tools_response.status_code == 200
        payload = tools_response.json()
        assert payload["transport"] == "http-broker"
        names = {tool["name"] for tool in payload["tools"]}
        assert "time_now" in names
        time_tool = next(tool for tool in payload["tools"] if tool["name"] == "time_now")
        assert time_tool["mcp_compatible"] is True
        assert "inputSchema" in time_tool
        assert "openai_schema" in time_tool

        call_response = client.post(
            "/broker/tools/call",
            json={"agent_id": "default", "user_key": "broker:alice", "tool_name": "time_now", "arguments": {}},
        )
        assert call_response.status_code == 200
        body = call_response.json()
        assert body["ok"] is True
        assert body["tool_name"] == "time_now"
        assert isinstance(body["result"], str)
        assert body["session_id"].startswith("broker:broker:alice")


def test_broker_respects_token(monkeypatch, tmp_path: Path) -> None:
    cfg = tmp_path / "openmiura.yaml"
    _write_config(cfg)
    monkeypatch.setenv("OPENMIURA_BROKER_TOKEN", "secret-broker")
    # keep config enabled, token comes from env
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        denied = client.get("/broker/health")
        assert denied.status_code == 401
        allowed = client.get("/broker/health", headers={"Authorization": "Bearer secret-broker"})
        assert allowed.status_code == 200
        assert allowed.json()["ok"] is True


def test_broker_chat_uses_pipeline(monkeypatch, tmp_path: Path) -> None:
    cfg = tmp_path / "openmiura.yaml"
    _write_config(cfg)

    seen = {}

    def _fake_process_message(gw, inbound):
        seen["channel"] = inbound.channel
        seen["user_id"] = inbound.user_id
        seen["session_id"] = inbound.session_id
        return OutboundMessage(
            channel="broker",
            user_id=inbound.user_id,
            session_id=inbound.session_id or "broker:user",
            agent_id="default",
            text="broker reply",
        )

    monkeypatch.setattr("openmiura.channels.http_broker.process_message", _fake_process_message)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        response = client.post("/broker/chat", json={"message": "hola", "user_id": "broker:user", "agent_id": "default"})
    assert response.status_code == 200
    assert response.json()["text"] == "broker reply"
    assert seen["channel"] == "broker"
    assert seen["user_id"] == "broker:user"
    assert seen["session_id"] == "broker:broker:user"
