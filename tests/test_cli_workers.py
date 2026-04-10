from __future__ import annotations

import argparse
from types import SimpleNamespace

import openmiura.cli as cli
from openmiura.core.worker_runtime import build_worker_specs, resolve_worker_mode


class _FakeWorkerManager:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited = True
        return False


class _FakeGateway:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            server=SimpleNamespace(host="127.0.0.1", port=8081),
            runtime=SimpleNamespace(worker_mode="external"),
            telegram=SimpleNamespace(bot_token="tg-token", mode="polling"),
            discord=SimpleNamespace(bot_token="dc-token"),
            slack=SimpleNamespace(bot_token="slack-token"),
        )


def test_build_worker_specs_detects_supported_inline_workers() -> None:
    settings = _FakeGateway().settings
    specs = build_worker_specs(settings)
    assert [spec.name for spec in specs] == ["telegram_polling", "discord_gateway"]


def test_resolve_worker_mode_prefers_inline_when_requested() -> None:
    settings = _FakeGateway().settings
    assert resolve_worker_mode(with_workers=True, settings=settings) == "inline"
    assert resolve_worker_mode(with_workers=False, settings=settings) == "external"


def test_cmd_run_with_workers_uses_unified_worker_manager(monkeypatch) -> None:
    gw = _FakeGateway()
    worker_manager = _FakeWorkerManager()
    calls: list[dict] = []

    monkeypatch.setattr(cli.Gateway, "from_config", lambda _path: gw)
    monkeypatch.setattr(cli, "build_worker_manager", lambda *, settings, config_path: worker_manager)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app_ref, **kwargs: calls.append({"app_ref": app_ref, **kwargs}))

    args = argparse.Namespace(
        config="configs/openmiura.yaml",
        host=None,
        port=None,
        reload=False,
        log_level="info",
        with_workers=True,
    )

    rc = cli.cmd_run(args)

    assert rc == 0
    assert worker_manager.entered is True and worker_manager.exited is True
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8081
