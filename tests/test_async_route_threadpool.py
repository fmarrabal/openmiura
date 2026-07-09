"""Async admin route handlers must offload blocking DB work to a threadpool.

The runtime-adapter POST handlers are `async def` (they `await request.json()`),
so any synchronous, blocking service/DB call in their body would run ON the
asyncio event loop and serialize every concurrent request. They now wrap those
calls in `run_in_threadpool`. This test proves it at the behaviour level: the
service method observes that it is running OFF the event loop (a threadpool
worker has no running loop, so `asyncio.get_running_loop()` raises).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from openmiura.interfaces.http.routes.admin._helpers import _ADMIN_SERVICE
from tests.test_openclaw_runtime_operations_v2 import (
    _create_async_runtime,
    _dispatch_async_run,
    _write_config,
)

_H = {"Authorization": "Bearer secret-admin"}


def _runs_off_loop(monkeypatch, method_name: str) -> dict:
    seen: dict[str, bool] = {}
    real = getattr(_ADMIN_SERVICE, method_name)

    def spy(gw, **kwargs):
        try:
            asyncio.get_running_loop()
            seen["off_loop"] = False  # running ON the event loop → blocks it
        except RuntimeError:
            seen["off_loop"] = True   # no running loop → offloaded to a thread
        return real(gw, **kwargs)

    monkeypatch.setattr(_ADMIN_SERVICE, method_name, spy)
    return seen


def test_dispatch_cancel_service_runs_off_the_event_loop(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "openmiura.yaml"
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        runtime_id = _create_async_runtime(client)
        dispatch_id = _dispatch_async_run(client, runtime_id, "threadpool-check-001")["dispatch"]["dispatch_id"]

        seen = _runs_off_loop(monkeypatch, "cancel_openclaw_dispatch")
        resp = client.post(
            f"/admin/openclaw/dispatches/{dispatch_id}/cancel",
            headers=_H,
            json={"actor": "admin", "reason": "threadpool test", "tenant_id": "tenant-a", "workspace_id": "ws-a", "environment": "prod"},
        )
        assert resp.status_code == 200, resp.text
        assert seen.get("off_loop") is True, "blocking dispatch-cancel service ran on the event loop"


def test_dispatch_poll_service_runs_off_the_event_loop(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "openmiura.yaml"
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        runtime_id = _create_async_runtime(client)
        dispatch_id = _dispatch_async_run(client, runtime_id, "threadpool-check-002")["dispatch"]["dispatch_id"]

        seen = _runs_off_loop(monkeypatch, "poll_openclaw_dispatch")
        resp = client.post(
            f"/admin/openclaw/dispatches/{dispatch_id}/poll",
            headers=_H,
            json={"actor": "admin", "tenant_id": "tenant-a", "workspace_id": "ws-a", "environment": "prod"},
        )
        assert resp.status_code == 200, resp.text
        assert seen.get("off_loop") is True, "blocking dispatch-poll service ran on the event loop"
