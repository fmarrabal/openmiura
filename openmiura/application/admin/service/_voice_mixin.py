"""openmiura.application.admin.service._voice_mixin

Part of the AdminService split. Methods originally lived on
``openmiura.application.admin.service.AdminService``; they have been
moved verbatim into this mixin so that no individual file in the
package exceeds the project's ``max 1,500 lines`` ceiling. The
public class still inherits from this mixin and exposes every
method unchanged.

The module-level ``AdminService = None`` sentinel is rebound by
``service/__init__.py`` once the final class is defined; this lets
the mixin's ``@staticmethod`` call sites that reference
``AdminService.foo(...)`` resolve correctly at call time without
introducing a circular import.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from openmiura.application.admin.status_snapshot import (
    build_status_snapshot,
    collect_registered_tool_names,
)
from openmiura.application.canvas import LiveCanvasService
from openmiura.application.costs import CostGovernanceService
from openmiura.application.evaluations import EvaluationService
from openmiura.application.memory import MemoryService
from openmiura.application.operator import OperatorConsoleService
from openmiura.application.packaging import PackagingHardeningService
from openmiura.application.pwa import PWAFoundationService
from openmiura.application.releases import ReleaseService
from openmiura.application.replay import ReplayService
from openmiura.application.runtime_adapters.external import (
    OpenClawAdapterService,
    OpenClawRecoverySchedulerService,
)
from openmiura.application.secrets import SecretGovernanceService
from openmiura.application.sessions import SessionService
from openmiura.application.tenancy import TenancyService
from openmiura.application.voice import VoiceRuntimeService
from openmiura import __version__
from openmiura.core.config import resolve_config_related_path
from openmiura.core.contracts import AdminGatewayLike
from openmiura.core.policies.engine import PolicyEngine


AdminService: type | None = None  # late-bound by service/__init__.py


class _AdminServiceVoiceMixin:
    """Mixin: voice methods on AdminService."""

    def list_voice_sessions(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.list_sessions(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_voice_session(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.get_session(
            gw,
            voice_session_id=voice_session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def start_voice_session(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        user_key: str,
        locale: str = 'es-ES',
        stt_provider: str = 'simulated-stt',
        tts_provider: str = 'simulated-tts',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.start_session(
            gw,
            actor=actor,
            user_key=user_key,
            locale=locale,
            stt_provider=stt_provider,
            tts_provider=tts_provider,
            metadata=metadata,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def transcribe_voice_turn(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        actor: str,
        transcript_text: str,
        confidence: float = 1.0,
        language: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.transcribe(
            gw,
            voice_session_id=voice_session_id,
            actor=actor,
            transcript_text=transcript_text,
            confidence=confidence,
            language=language,
            metadata=metadata,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def transcribe_voice_audio(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        actor: str,
        audio_b64: str,
        mime_type: str = 'audio/wav',
        sample_rate_hz: int = 16000,
        language: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.transcribe_audio(
            gw,
            voice_session_id=voice_session_id,
            actor=actor,
            audio_b64=audio_b64,
            mime_type=mime_type,
            sample_rate_hz=sample_rate_hz,
            language=language,
            metadata=metadata,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def respond_voice_turn(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        actor: str,
        text: str,
        voice_name: str = 'assistant',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.respond(
            gw,
            voice_session_id=voice_session_id,
            actor=actor,
            text=text,
            voice_name=voice_name,
            metadata=metadata,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def confirm_voice_turn(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        actor: str,
        decision: str = 'confirm',
        confirmation_text: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.confirm(
            gw,
            voice_session_id=voice_session_id,
            actor=actor,
            decision=decision,
            confirmation_text=confirmation_text,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def close_voice_session(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.close_session(
            gw,
            voice_session_id=voice_session_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

