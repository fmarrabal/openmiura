"""admin/_voice.py - broker admin sub-routes for the voice domain."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from openmiura.application.admin import AdminService
from openmiura.application.auth.service import AuthService
from openmiura.application.tenancy.service import TenancyService
from openmiura.interfaces.broker.common import (
    audit_sensitive,
    metrics_summary,
    require_csrf,
    require_permission,
)




def register_routes(router, tenancy_service) -> None:
    """Attach the voice broker admin endpoints to *router*."""
    @router.get("/admin/voice/sessions")
    def broker_admin_voice_sessions(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        response = AdminService().list_voice_sessions(
            gw,
            limit=limit,
            status=status,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_voice_sessions", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "status": status})
        return response

    @router.get("/admin/voice/sessions/{voice_session_id}")
    def broker_admin_voice_session_detail(
        voice_session_id: str,
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        response = AdminService().get_voice_session(gw, voice_session_id=voice_session_id, **target_scope)
        audit_sensitive(gw, action="admin_voice_session_detail", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=voice_session_id)
        return response

    @router.post("/admin/voice/sessions")
    async def broker_admin_voice_session_start(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        response = AdminService().start_voice_session(
            gw,
            actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
            user_key=str(payload.get("user_key") or auth_ctx.get("user_key") or auth_ctx.get("username") or "voice-user"),
            locale=str(payload.get("locale") or "es-ES"),
            stt_provider=str(payload.get("stt_provider") or "simulated-stt"),
            tts_provider=str(payload.get("tts_provider") or "simulated-tts"),
            metadata=dict(payload.get("metadata") or {}),
            tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=payload.get("environment") or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_voice_session_start", auth_ctx=auth_ctx, status="ok", target=response.get("session", {}).get("voice_session_id"))
        return response

    @router.post("/admin/voice/sessions/{voice_session_id}/transcribe")
    async def broker_admin_voice_session_transcribe(voice_session_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().transcribe_voice_turn(
                gw,
                voice_session_id=voice_session_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                transcript_text=str(payload.get("transcript_text") or ""),
                confidence=float(payload.get("confidence") or 1.0),
                language=str(payload.get("language") or ""),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_voice_session_transcribe", auth_ctx=auth_ctx, status="ok", target=voice_session_id)
        return response

    @router.post("/admin/voice/sessions/{voice_session_id}/respond")
    async def broker_admin_voice_session_respond(voice_session_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().respond_voice_turn(
                gw,
                voice_session_id=voice_session_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                text=str(payload.get("text") or ""),
                voice_name=str(payload.get("voice_name") or "assistant"),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
        audit_sensitive(gw, action="admin_voice_session_respond", auth_ctx=auth_ctx, status="ok", target=voice_session_id)
        return response

    @router.post("/admin/voice/sessions/{voice_session_id}/confirm")
    async def broker_admin_voice_session_confirm(voice_session_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().confirm_voice_turn(
                gw,
                voice_session_id=voice_session_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                decision=str(payload.get("decision") or "confirm"),
                confirmation_text=str(payload.get("confirmation_text") or ""),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_voice_session_confirm", auth_ctx=auth_ctx, status="ok", target=voice_session_id)
        return response

    @router.post("/admin/voice/sessions/{voice_session_id}/close")
    async def broker_admin_voice_session_close(voice_session_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        try:
            response = AdminService().close_voice_session(
                gw,
                voice_session_id=voice_session_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                reason=str(payload.get("reason") or ""),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
        audit_sensitive(gw, action="admin_voice_session_close", auth_ctx=auth_ctx, status="ok", target=voice_session_id)
        return response

    @router.post("/admin/voice/sessions/{voice_session_id}/audio/transcribe")
    async def broker_admin_voice_session_audio_transcribe(voice_session_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().transcribe_voice_audio(
                gw,
                voice_session_id=voice_session_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                audio_b64=str(payload.get("audio_b64") or ""),
                mime_type=str(payload.get("mime_type") or "audio/wav"),
                sample_rate_hz=int(payload.get("sample_rate_hz") or 16000),
                language=str(payload.get("language") or ""),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
        audit_sensitive(gw, action="admin_voice_session_audio_transcribe", auth_ctx=auth_ctx, status="ok", target=voice_session_id)
        return response

