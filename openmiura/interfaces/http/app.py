from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount

from openmiura import __version__
from openmiura.interfaces.broker.router import build_broker_router
from openmiura.core.config import load_settings
from openmiura.core.schema import InboundMessage, OutboundMessage
from openmiura.interfaces.channels.slack.routes import router as slack_router
from openmiura.interfaces.channels.telegram.routes import router as telegram_router
from openmiura.gateway import Gateway
from openmiura.infrastructure.bootstrap.container import build_gateway, resolve_gateway_factory
from openmiura.interfaces.http.routes.admin import router as admin_router
from openmiura.observability import metrics_payload, update_memory_metrics
from openmiura.pipeline import process_message

try:  # pragma: no cover - optional dependency/runtime feature
    from openmiura.channels.mcp_server import build_sse_app
except Exception:  # pragma: no cover
    build_sse_app = None  # type: ignore


class _UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


_HTTP_LOG = logging.getLogger("openmiura.http")


def _build_lazy_mcp_app(app: FastAPI, mount_path: str):
    inner_app = None

    async def _asgi(scope, receive, send):
        nonlocal inner_app
        if inner_app is None:
            gw: Gateway | None = getattr(app.state, "gw", None)
            if gw is None:
                raise RuntimeError("Service not initialized")
            inner_app = build_sse_app(gw, mount_path)
        await inner_app(scope, receive, send)

    return _asgi


def _apply_security_headers(response: Response, *, path: str, request_id: str) -> None:
    response.headers.setdefault("X-Request-ID", request_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
    if path.startswith("/broker/auth"):
        response.headers.setdefault("Cache-Control", "no-store")
    if path.startswith("/ui") or path == "/":
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; base-uri 'self'; frame-ancestors 'none'",
        )


def create_app(
    config_path: str | None = None,
    gateway_factory=None,
    message_handler=None,
) -> FastAPI:
    factory = resolve_gateway_factory(gateway_factory)
    handler = message_handler or process_message

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        gw = build_gateway(config_path, factory)
        app.state.gw = gw
        cleanup_task = None
        settings = getattr(gw, "settings", None)
        runtime = getattr(settings, "runtime", None)
        interval = max(
            5,
            int(getattr(runtime, "confirmation_cleanup_interval_s", 60) or 60),
        )

        async def _cleanup_loop() -> None:
            while True:
                await asyncio.sleep(interval)
                try:
                    gw.cleanup_expired_tool_confirmations()
                    if getattr(gw, "audit", None) is not None:
                        update_memory_metrics(gw.audit)
                except Exception:
                    pass

        if hasattr(gw, "cleanup_expired_tool_confirmations"):
            cleanup_task = asyncio.create_task(_cleanup_loop())
        try:
            if getattr(gw, "audit", None) is not None:
                update_memory_metrics(gw.audit)
            yield
        finally:
            if cleanup_task is not None:
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(
        title="openMiura Gateway",
        version=__version__,
        default_response_class=_UTF8JSONResponse,
        lifespan=_lifespan,
    )

    @app.middleware("http")
    async def _security_and_request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "").strip() or uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        _apply_security_headers(response, path=request.url.path, request_id=request_id)
        duration_ms = round((time.perf_counter() - start) * 1000.0, 3)
        try:
            _HTTP_LOG.info(json.dumps({
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": request.client.host if request.client else None,
            }, ensure_ascii=False))
        except Exception:
            pass
        return response

    app.include_router(telegram_router)
    app.include_router(slack_router)
    app.include_router(admin_router)

    @app.get("/health")
    def health():
        return {"ok": True, "name": "openMiura", "version": __version__}

    @app.get("/metrics")
    def metrics():
        gw: Gateway | None = getattr(app.state, "gw", None)
        payload, content_type = metrics_payload(getattr(gw, "audit", None))
        return Response(content=payload, media_type=content_type)

    @app.post("/http/message", response_model=OutboundMessage)
    def http_message(msg: InboundMessage):
        gw: Gateway | None = getattr(app.state, "gw", None)
        if gw is None:
            raise HTTPException(status_code=503, detail="Service not initialized")
        return handler(gw, msg)

    @app.exception_handler(HTTPException)
    def _http_exception_handler(_, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    probe_settings = None
    settings_path = config_path or os.environ.get("OPENMIURA_CONFIG", "configs/openmiura.yaml")
    try:
        probe_settings = load_settings(settings_path)
    except Exception:
        probe_settings = None

    broker_cfg = getattr(probe_settings, "broker", None)
    if broker_cfg and getattr(broker_cfg, "enabled", False):
        app.include_router(build_broker_router(), prefix=getattr(broker_cfg, "base_path", "/broker"))

    if build_sse_app is not None:
        try:
            mcp_cfg = getattr(probe_settings, "mcp", None)
            if mcp_cfg and getattr(mcp_cfg, "enabled", False):
                app.router.routes.append(
                    Mount(
                        getattr(mcp_cfg, "sse_path", "/mcp"),
                        app=_build_lazy_mcp_app(app, getattr(mcp_cfg, "sse_path", "/mcp")),
                    )
                )
        except Exception:
            pass

    ui_static = Path(__file__).resolve().parents[2] / "ui" / "static"
    if ui_static.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_static), html=True), name="ui")

    return app
