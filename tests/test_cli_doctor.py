from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import openmiura.cli as cli


class _FakeGateway:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            server=SimpleNamespace(host="127.0.0.1", port=8081),
            storage=SimpleNamespace(db_path="data/test.db"),
            tools=SimpleNamespace(sandbox_dir="data/sandbox"),
            llm=SimpleNamespace(
                provider="ollama",
                model="qwen2.5:7b-instruct",
                base_url="http://127.0.0.1:11434",
                timeout_s=5,
            ),
            memory=SimpleNamespace(embed_model="nomic-embed-text"),
            runtime=SimpleNamespace(history_limit=12),
            telegram=SimpleNamespace(bot_token="tg-token"),
            slack=SimpleNamespace(bot_token="slack-token"),
            discord=SimpleNamespace(bot_token="discord-token"),
            admin=SimpleNamespace(enabled=True),
        )


class _FakeHTTPClientOK:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str):
        return _FakeResponse(url)


class _FakeResponse:
    def __init__(self, url: str) -> None:
        self.url = url

    def raise_for_status(self) -> None:
        return None


class _FakeHTTPClientFail(_FakeHTTPClientOK):
    def get(self, url: str):
        raise RuntimeError(f"cannot reach {url}")


def test_resolve_config_path_prefers_explicit(monkeypatch) -> None:
    monkeypatch.setenv("OPENMIURA_CONFIG", "from-env.yaml")
    assert cli._resolve_config_path("from-arg.yaml") == "from-arg.yaml"


def test_resolve_config_path_uses_env_then_default(monkeypatch) -> None:
    monkeypatch.setenv("OPENMIURA_CONFIG", "from-env.yaml")
    assert cli._resolve_config_path(None) == "from-env.yaml"

    monkeypatch.delenv("OPENMIURA_CONFIG", raising=False)
    assert cli._resolve_config_path(None) == "configs/openmiura.yaml"


def test_doctor_payload_returns_error_for_missing_config(tmp_path) -> None:
    payload, exit_code = cli._doctor_payload(str(tmp_path / "missing.yaml"))

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["checks"][0]["name"] == "config_exists"
    assert payload["checks"][0]["ok"] is False


def test_doctor_payload_success_with_ollama_warning(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "openmiura.yaml"
    config_path.write_text("server: {}\n", encoding="utf-8")
    (tmp_path / "data" / "sandbox").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(cli.Gateway, "from_config", lambda _path: _FakeGateway())
    monkeypatch.setattr(cli.httpx, "Client", _FakeHTTPClientFail)

    payload, exit_code = cli._doctor_payload(str(config_path))

    assert exit_code == 0
    assert payload["ok"] is True
    assert any(c["name"] == "gateway_init" and c["ok"] for c in payload["checks"])
    assert any(c["name"] == "ollama_http" and c["level"] == "warning" for c in payload["checks"])
    assert payload["summary"]["llm_model"] == "qwen2.5:7b-instruct"
    assert payload["summary"]["history_limit"] == 12


def test_cmd_doctor_prints_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "_doctor_payload",
        lambda _path: ({"version": "0.1.0", "config_path": "cfg.yaml", "checks": [], "summary": {}, "ok": True}, 0),
    )
    args = argparse.Namespace(config="cfg.yaml", json=True)

    rc = cli.cmd_doctor(args)
    out = capsys.readouterr().out

    assert rc == 0
    data = json.loads(out)
    assert data["version"] == "0.1.0"
    assert data["config_path"] == "cfg.yaml"


def test_cmd_doctor_prints_human_readable(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "_doctor_payload",
        lambda _path: (
            {
                "version": "0.1.0",
                "config_path": "cfg.yaml",
                "checks": [
                    {"name": "config_exists", "ok": True, "level": "info", "detail": "Found cfg.yaml"},
                    {"name": "ollama_http", "ok": True, "level": "warning", "detail": "not reachable"},
                ],
                "summary": {"db_path": "data/test.db"},
                "ok": True,
            },
            0,
        ),
    )
    args = argparse.Namespace(config="cfg.yaml", json=False)

    rc = cli.cmd_doctor(args)
    out = capsys.readouterr().out

    assert rc == 0
    assert "openMiura doctor v0.1.0" in out
    assert "[OK] config_exists: Found cfg.yaml" in out
    assert "[WARN] ollama_http: not reachable" in out
    assert "db_path: data/test.db" in out


def test_cmd_run_uses_config_values_when_host_and_port_not_overridden(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(cli.Gateway, "from_config", lambda _path: _FakeGateway())

    def fake_run(app_ref: str, **kwargs):
        calls.append({"app_ref": app_ref, **kwargs})

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    monkeypatch.delenv("OPENMIURA_CONFIG", raising=False)

    args = argparse.Namespace(
        config="configs/openmiura.yaml",
        host=None,
        port=None,
        reload=False,
        log_level="debug",
    )

    rc = cli.cmd_run(args)

    assert rc == 0
    assert calls == [
        {
            "app_ref": "app:app",
            "host": "127.0.0.1",
            "port": 8081,
            "reload": False,
            "log_level": "debug",
        }
    ]


def test_cmd_run_respects_explicit_host_port(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_run(app_ref: str, **kwargs):
        calls.append({"app_ref": app_ref, **kwargs})

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    monkeypatch.setattr(cli.Gateway, "from_config", lambda _path: (_ for _ in ()).throw(AssertionError("Gateway.from_config should not be called")))

    args = argparse.Namespace(
        config="configs/openmiura.yaml",
        host="0.0.0.0",
        port=9000,
        reload=True,
        log_level="info",
    )

    rc = cli.cmd_run(args)

    assert rc == 0
    assert calls == [
        {
            "app_ref": "app:app",
            "host": "0.0.0.0",
            "port": 9000,
            "reload": True,
            "log_level": "info",
        }
    ]
