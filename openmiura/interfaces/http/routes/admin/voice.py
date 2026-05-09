"""admin/voice.py — sub-router for the voice bounded admin domain."""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from openmiura.interfaces.http.routes.admin._helpers import (
    _ADMIN_SERVICE,
    _audit_admin,
    _extract_admin_token,
    _get_gw,
    _rate_limit,
    _require_admin,
)
from openmiura.interfaces.http.routes.admin._models import *  # noqa: F401,F403

router = APIRouter(tags=["admin"])


@router.get("/admin/voice/sessions")
def admin_voice_sessions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_voice_sessions(
        gw,
        limit=limit,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "voice_sessions_list", {"count": len(payload.get("items", [])), "status": status})
    return payload


@router.get("/admin/voice/sessions/{voice_session_id}")
def admin_voice_session_detail(
    voice_session_id: str,
    request: Request,
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.get_voice_session(
        gw,
        voice_session_id=voice_session_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "voice_session_detail", {"voice_session_id": voice_session_id, "ok": payload.get("ok")})
    return payload


@router.post("/admin/voice/sessions")
def admin_voice_session_start(payload: VoiceSessionStartRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.start_voice_session(
        gw,
        actor=payload.actor,
        user_key=payload.user_key,
        locale=payload.locale,
        stt_provider=payload.stt_provider,
        tts_provider=payload.tts_provider,
        metadata=payload.metadata,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "voice_session_start", {"voice_session_id": response.get("session", {}).get("voice_session_id"), "actor": payload.actor})
    return response


@router.post("/admin/voice/sessions/{voice_session_id}/transcribe")
def admin_voice_session_transcribe(voice_session_id: str, payload: VoiceTranscriptRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.transcribe_voice_turn(
            gw,
            voice_session_id=voice_session_id,
            actor=payload.actor,
            transcript_text=payload.transcript_text,
            confidence=payload.confidence,
            language=payload.language,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "voice_session_transcribe", {"voice_session_id": voice_session_id, "actor": payload.actor})
    return response


@router.post("/admin/voice/sessions/{voice_session_id}/respond")
def admin_voice_session_respond(voice_session_id: str, payload: VoiceRespondRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.respond_voice_turn(
            gw,
            voice_session_id=voice_session_id,
            actor=payload.actor,
            text=payload.text,
            voice_name=payload.voice_name,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
    _audit_admin(gw, "voice_session_respond", {"voice_session_id": voice_session_id, "actor": payload.actor})
    return response


@router.post("/admin/voice/sessions/{voice_session_id}/confirm")
def admin_voice_session_confirm(voice_session_id: str, payload: VoiceConfirmRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.confirm_voice_turn(
            gw,
            voice_session_id=voice_session_id,
            actor=payload.actor,
            decision=payload.decision,
            confirmation_text=payload.confirmation_text,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "voice_session_confirm", {"voice_session_id": voice_session_id, "actor": payload.actor, "decision": payload.decision})
    return response


@router.post("/admin/voice/sessions/{voice_session_id}/close")
def admin_voice_session_close(voice_session_id: str, payload: VoiceCloseRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.close_voice_session(
            gw,
            voice_session_id=voice_session_id,
            actor=payload.actor,
            reason=payload.reason,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
    _audit_admin(gw, "voice_session_close", {"voice_session_id": voice_session_id, "actor": payload.actor})
    return response


@router.post("/admin/voice/sessions/{voice_session_id}/audio/transcribe")
def admin_voice_session_audio_transcribe(voice_session_id: str, payload: VoiceAudioTranscribeRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.transcribe_voice_audio(
            gw,
            voice_session_id=voice_session_id,
            actor=payload.actor,
            audio_b64=payload.audio_b64,
            mime_type=payload.mime_type,
            sample_rate_hz=payload.sample_rate_hz,
            language=payload.language,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
    audit_event_id = _audit_admin(gw, "voice_session_audio_transcribe", {"voice_session_id": voice_session_id, "actor": payload.actor, "mime_type": payload.mime_type})
    if isinstance(response, dict):
        response["audit_event_id"] = audit_event_id
    return response


