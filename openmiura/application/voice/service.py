from __future__ import annotations

import base64
import hashlib
import time
from pathlib import Path
from typing import Any

from openmiura.application.packaging import PackagingHardeningService
from openmiura.application.voice.providers import resolve_stt_provider, resolve_tts_provider


class VoiceRuntimeService:
    _VOICE_LIMITS = PackagingHardeningService.DEFAULT_HARDENING['voice']
    MAX_TRANSCRIPTS_PER_MINUTE = int(_VOICE_LIMITS['max_transcripts_per_minute'])
    MAX_TRANSCRIPT_CHARS = int(_VOICE_LIMITS['max_transcript_chars'])
    MAX_OUTPUT_CHARS = int(_VOICE_LIMITS['max_output_chars'])

    SENSITIVE_TOKENS = {
        'delete': 'delete_data',
        'borrar': 'delete_data',
        'purge': 'delete_data',
        'rollback': 'rollback_release',
        'revert': 'rollback_release',
        'promote': 'promote_release',
        'deploy': 'promote_release',
        'approve': 'approve_action',
        'apru': 'approve_action',
        'send': 'send_action',
        'transfer': 'transfer_action',
    }

    SIMPLE_TOKENS = {
        'status': 'status_check',
        'estado': 'status_check',
        'approval': 'approval_lookup',
        'approv': 'approval_lookup',
        'aprob': 'approval_lookup',
        'help': 'help',
        'ayuda': 'help',
    }

    def _assets_dir(self) -> Path:
        path = Path(__file__).resolve().parents[3] / 'data' / 'voice_assets'
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _recent_transcript_count(self, gw, *, voice_session_id: str, tenant_id: str | None, workspace_id: str | None, environment: str | None, window_s: float = 60.0) -> int:
        cutoff = time.time() - float(window_s)
        count = 0
        for item in gw.audit.list_voice_transcripts(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, limit=max(self.MAX_TRANSCRIPTS_PER_MINUTE * 4, 50)):
            if float(item.get('created_at') or 0.0) >= cutoff:
                count += 1
        return count

    def _validate_transcript(self, gw, *, voice_session_id: str, text: str, tenant_id: str | None, workspace_id: str | None, environment: str | None) -> str:
        cleaned = str(text or '').strip()
        if len(cleaned) > self.MAX_TRANSCRIPT_CHARS:
            raise ValueError(f'voice transcript exceeds max length ({self.MAX_TRANSCRIPT_CHARS})')
        recent = self._recent_transcript_count(gw, voice_session_id=voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if recent >= self.MAX_TRANSCRIPTS_PER_MINUTE:
            raise ValueError('voice transcript rate limit exceeded')
        return cleaned

    def _validate_output(self, text: str) -> str:
        cleaned = str(text or '').strip()
        if len(cleaned) > self.MAX_OUTPUT_CHARS:
            raise ValueError(f'voice output exceeds max length ({self.MAX_OUTPUT_CHARS})')
        return cleaned

    def list_sessions(
        self,
        gw,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        items = gw.audit.list_voice_sessions(limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {'ok': True, 'items': items, 'summary': {'count': len(items), 'status': status}}

    def get_session(
        self,
        gw,
        *,
        voice_session_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        session = gw.audit.get_voice_session(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if session is None:
            return {'ok': False, 'error': 'voice_session_not_found', 'voice_session_id': voice_session_id}
        effective_tenant = tenant_id or session.get('tenant_id')
        effective_workspace = workspace_id or session.get('workspace_id')
        effective_env = environment or session.get('environment')
        payload = {
            'ok': True,
            'session': session,
            'transcripts': gw.audit.list_voice_transcripts(voice_session_id, tenant_id=effective_tenant, workspace_id=effective_workspace, environment=effective_env, limit=100),
            'outputs': gw.audit.list_voice_outputs(voice_session_id, tenant_id=effective_tenant, workspace_id=effective_workspace, environment=effective_env, limit=100),
            'commands': gw.audit.list_voice_commands(voice_session_id, tenant_id=effective_tenant, workspace_id=effective_workspace, environment=effective_env, limit=100),
        }
        if hasattr(gw.audit, 'list_voice_audio_assets'):
            payload['audio_assets'] = gw.audit.list_voice_audio_assets(voice_session_id, tenant_id=effective_tenant, workspace_id=effective_workspace, environment=effective_env, limit=100)
        if hasattr(gw.audit, 'list_voice_provider_calls'):
            payload['provider_calls'] = gw.audit.list_voice_provider_calls(voice_session_id, tenant_id=effective_tenant, workspace_id=effective_workspace, environment=effective_env, limit=100)
        return payload

    def start_session(
        self,
        gw,
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
        session = gw.audit.create_voice_session(
            channel='voice',
            user_key=str(user_key or actor or 'voice-user'),
            locale=locale,
            stt_provider=stt_provider,
            tts_provider=tts_provider,
            metadata=dict(metadata or {}),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        gw.audit.log_event('system', 'voice', str(user_key or actor or 'voice-user'), session['voice_session_id'], {'action': 'voice_session_started', 'actor': actor, 'locale': locale}, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {'ok': True, 'session': session}

    def transcribe(
        self,
        gw,
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
        session = gw.audit.get_voice_session(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if session is None:
            raise KeyError(voice_session_id)
        text = str(transcript_text or '').strip()
        if not text:
            raise ValueError('transcript text is required')
        return self._process_transcript_text(
            gw,
            session=session,
            voice_session_id=voice_session_id,
            actor=actor,
            text=text,
            confidence=confidence,
            language=language or session.get('locale') or '',
            stage='stt',
            transcript_metadata=dict(metadata or {}),
        )

    def transcribe_audio(
        self,
        gw,
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
        session = gw.audit.get_voice_session(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if session is None:
            raise KeyError(voice_session_id)
        raw_b64 = str(audio_b64 or '').strip()
        if not raw_b64:
            raise ValueError('audio_b64 is required')
        try:
            audio_bytes = base64.b64decode(raw_b64)
        except Exception as exc:
            raise ValueError('invalid audio_b64 payload') from exc
        if not audio_bytes:
            raise ValueError('empty audio payload')
        meta = dict(metadata or {})
        input_asset = self._persist_audio_asset(
            gw,
            session=session,
            voice_session_id=voice_session_id,
            actor=actor,
            direction='input',
            asset_kind='stt_request',
            mime_type=mime_type,
            sample_rate_hz=sample_rate_hz,
            audio_bytes=audio_bytes,
            metadata={**meta, 'source': 'audio-transcribe'},
        )
        provider_name = str(session.get('stt_provider') or 'local-inline-stt')
        provider = resolve_stt_provider(provider_name)
        started_at = time.time()
        status = 'ok'
        error_text = ''
        result_payload: dict[str, Any] = {}
        try:
            result = provider.transcribe(audio_bytes, locale=language or session.get('locale') or '', metadata=meta)
            result_payload = {'text': result.text, 'confidence': result.confidence, 'language': result.language, 'metadata': result.metadata}
        except Exception as exc:
            status = 'error'
            error_text = repr(exc)
            result = None
        latency_ms = max(0.0, (time.time() - started_at) * 1000.0)
        provider_call = None
        if hasattr(gw.audit, 'create_voice_provider_call'):
            provider_call = gw.audit.create_voice_provider_call(
                voice_session_id,
                provider_kind='stt',
                provider_name=getattr(provider, 'name', provider_name),
                status=status,
                request={'mime_type': mime_type, 'sample_rate_hz': sample_rate_hz, 'byte_count': len(audio_bytes), 'sha256': hashlib.sha256(audio_bytes).hexdigest()},
                response=result_payload if status == 'ok' else {},
                error_text=error_text,
                latency_ms=latency_ms,
                created_by=actor,
                tenant_id=session.get('tenant_id'),
                workspace_id=session.get('workspace_id'),
                environment=session.get('environment'),
            )
        if status != 'ok' or result is None:
            raise RuntimeError(f'voice STT provider failed: {error_text or provider_name}')
        payload = self._process_transcript_text(
            gw,
            session=session,
            voice_session_id=voice_session_id,
            actor=actor,
            text=result.text,
            confidence=float(result.confidence or 0.0),
            language=result.language or language or session.get('locale') or '',
            stage='stt_audio',
            transcript_metadata={**meta, 'provider': getattr(provider, 'name', provider_name), 'audio_asset_id': input_asset.get('asset_id') if input_asset else None},
        )
        payload['input_audio_asset'] = input_asset
        if provider_call is not None:
            payload['provider_call'] = provider_call
        return payload

    def respond(
        self,
        gw,
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
        session = gw.audit.get_voice_session(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if session is None:
            raise KeyError(voice_session_id)
        response_text = str(text or '').strip() or self._response_for_transcript(session.get('last_transcript_text') or '')
        response_text = self._validate_output(response_text)
        meta = dict(metadata or {})
        output_meta = dict(meta)
        audio_asset = None
        provider_call = None
        provider_name = str(session.get('tts_provider') or '')
        if provider_name.lower() not in {'', 'simulated-tts'} or bool(meta.get('emit_audio')):
            provider = resolve_tts_provider(provider_name or 'local-wave-tts')
            started_at = time.time()
            status = 'ok'
            error_text = ''
            synth_payload: dict[str, Any] = {}
            try:
                tts = provider.synthesize(response_text, voice_name=voice_name, locale=session.get('locale') or '', metadata=meta)
                audio_asset = self._persist_audio_asset(
                    gw,
                    session=session,
                    voice_session_id=voice_session_id,
                    actor=actor,
                    direction='output',
                    asset_kind='tts_response',
                    mime_type=tts.mime_type,
                    sample_rate_hz=int(tts.sample_rate_hz or 0),
                    audio_bytes=tts.audio_bytes,
                    metadata={**tts.metadata, 'duration_ms': int(tts.duration_ms or 0)},
                )
                synth_payload = {'mime_type': tts.mime_type, 'sample_rate_hz': tts.sample_rate_hz, 'duration_ms': tts.duration_ms, 'asset_id': audio_asset.get('asset_id') if audio_asset else None}
                output_meta.update({'audio_asset_id': audio_asset.get('asset_id') if audio_asset else None, 'provider': getattr(provider, 'name', provider_name), 'duration_ms': tts.duration_ms})
            except Exception as exc:
                status = 'error'
                error_text = repr(exc)
            latency_ms = max(0.0, (time.time() - started_at) * 1000.0)
            if hasattr(gw.audit, 'create_voice_provider_call'):
                provider_call = gw.audit.create_voice_provider_call(
                    voice_session_id,
                    provider_kind='tts',
                    provider_name=getattr(provider, 'name', provider_name),
                    status=status,
                    request={'text': response_text, 'voice_name': voice_name},
                    response=synth_payload if status == 'ok' else {},
                    error_text=error_text,
                    latency_ms=latency_ms,
                    created_by=actor,
                    tenant_id=session.get('tenant_id'),
                    workspace_id=session.get('workspace_id'),
                    environment=session.get('environment'),
                )
            if status != 'ok':
                raise RuntimeError(f'voice TTS provider failed: {error_text or provider_name}')
        output = gw.audit.add_voice_output(
            voice_session_id,
            text=response_text,
            status='ready',
            voice_name=voice_name,
            audio_ref=str(audio_asset.get('asset_id') or '') if audio_asset else '',
            created_by=actor,
            metadata=output_meta,
            tenant_id=session.get('tenant_id'),
            workspace_id=session.get('workspace_id'),
            environment=session.get('environment'),
        )
        session = gw.audit.update_voice_session(voice_session_id, last_output_text=response_text, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
        gw.audit.log_event('outbound', 'voice', str(session.get('user_key') or actor or 'voice-user'), voice_session_id, {'action': 'voice_responded', 'voice_name': voice_name, 'text': response_text, 'audio_asset_id': audio_asset.get('asset_id') if audio_asset else None}, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
        payload = {'ok': True, 'session': session, 'output': output}
        if audio_asset is not None:
            payload['audio_asset'] = audio_asset
        if provider_call is not None:
            payload['provider_call'] = provider_call
        return payload

    def confirm(
        self,
        gw,
        *,
        voice_session_id: str,
        actor: str,
        decision: str = 'confirm',
        confirmation_text: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        session = gw.audit.get_voice_session(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if session is None:
            raise KeyError(voice_session_id)
        pending = gw.audit.get_latest_pending_voice_command(voice_session_id, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
        if pending is None:
            raise ValueError('no pending voice command')
        normalized = str(decision or 'confirm').strip().lower()
        if normalized not in {'confirm', 'cancel'}:
            raise ValueError('unsupported decision')
        if confirmation_text:
            gw.audit.add_voice_transcript(
                voice_session_id,
                direction='user',
                stage='confirmation',
                text=str(confirmation_text),
                confidence=1.0,
                language=session.get('locale') or '',
                created_by=actor,
                metadata={'decision': normalized},
                tenant_id=session.get('tenant_id'),
                workspace_id=session.get('workspace_id'),
                environment=session.get('environment'),
            )
        command = gw.audit.resolve_voice_command(pending['command_id'], decision=normalized, actor=actor, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
        response_text = f"Confirmed voice command '{pending['command_name']}'." if normalized == 'confirm' else f"Cancelled voice command '{pending['command_name']}'."
        output = gw.audit.add_voice_output(
            voice_session_id,
            text=response_text,
            status='ready' if normalized == 'confirm' else 'cancelled',
            voice_name='system',
            created_by=actor,
            metadata={'command_id': pending['command_id'], 'decision': normalized},
            tenant_id=session.get('tenant_id'),
            workspace_id=session.get('workspace_id'),
            environment=session.get('environment'),
        )
        session = gw.audit.update_voice_session(voice_session_id, status='active', last_output_text=response_text, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
        gw.audit.log_event('system', 'voice', str(session.get('user_key') or actor or 'voice-user'), voice_session_id, {'action': 'voice_command_resolved', 'decision': normalized, 'command_id': pending['command_id']}, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
        return {'ok': True, 'session': session, 'command': command, 'output': output}

    def close_session(
        self,
        gw,
        *,
        voice_session_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        session = gw.audit.get_voice_session(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if session is None:
            raise KeyError(voice_session_id)
        session = gw.audit.update_voice_session(voice_session_id, status='closed', closed=True, metadata={'close_reason': reason or '', 'closed_by': actor}, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
        gw.audit.log_event('system', 'voice', str(session.get('user_key') or actor or 'voice-user'), voice_session_id, {'action': 'voice_session_closed', 'reason': reason or '', 'actor': actor}, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
        return {'ok': True, 'session': session}

    def _persist_audio_asset(
        self,
        gw,
        *,
        session: dict[str, Any],
        voice_session_id: str,
        actor: str,
        direction: str,
        asset_kind: str,
        mime_type: str,
        sample_rate_hz: int,
        audio_bytes: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not hasattr(gw.audit, 'create_voice_audio_asset'):
            return None
        digest = hashlib.sha256(audio_bytes).hexdigest()
        extension = 'wav' if 'wav' in str(mime_type or '').lower() else 'bin'
        storage_ref = self._assets_dir() / f'{digest[:16]}-{asset_kind}.{extension}'
        storage_ref.write_bytes(audio_bytes)
        return gw.audit.create_voice_audio_asset(
            voice_session_id,
            direction=direction,
            asset_kind=asset_kind,
            mime_type=mime_type,
            sample_rate_hz=int(sample_rate_hz or 0),
            byte_count=len(audio_bytes),
            sha256=digest,
            storage_ref=str(storage_ref),
            created_by=actor,
            metadata=dict(metadata or {}),
            tenant_id=session.get('tenant_id'),
            workspace_id=session.get('workspace_id'),
            environment=session.get('environment'),
        )

    def _process_transcript_text(
        self,
        gw,
        *,
        session: dict[str, Any],
        voice_session_id: str,
        actor: str,
        text: str,
        confidence: float,
        language: str,
        stage: str,
        transcript_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = self._validate_transcript(gw, voice_session_id=voice_session_id, text=text, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
        transcript = gw.audit.add_voice_transcript(
            voice_session_id,
            direction='user',
            stage=stage,
            text=text,
            confidence=confidence,
            language=language or session.get('locale') or '',
            created_by=actor,
            metadata=dict(transcript_metadata or {}),
            tenant_id=session.get('tenant_id'),
            workspace_id=session.get('workspace_id'),
            environment=session.get('environment'),
        )
        command_name = self._command_name_from_text(text)
        sensitive = self._is_sensitive(text)
        if sensitive:
            command = gw.audit.create_voice_command(
                voice_session_id,
                command_name=command_name,
                command_payload={'transcript_text': text},
                status='pending_confirmation',
                requires_confirmation=True,
                metadata={'channel': 'voice', 'policy': 'confirm_sensitive_action'},
                tenant_id=session.get('tenant_id'),
                workspace_id=session.get('workspace_id'),
                environment=session.get('environment'),
            )
            session = gw.audit.update_voice_session(voice_session_id, status='awaiting_confirmation', last_transcript_text=text, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
            response_text = f"Confirmation required before executing voice command '{command_name}'."
            output = gw.audit.add_voice_output(
                voice_session_id,
                text=response_text,
                status='pending_confirmation',
                voice_name='system',
                created_by=actor,
                metadata={'command_name': command_name, 'requires_confirmation': True},
                tenant_id=session.get('tenant_id'),
                workspace_id=session.get('workspace_id'),
                environment=session.get('environment'),
            )
        else:
            command = gw.audit.create_voice_command(
                voice_session_id,
                command_name=command_name,
                command_payload={'transcript_text': text},
                status='executed',
                requires_confirmation=False,
                confirmed_by=actor,
                metadata={'channel': 'voice', 'policy': 'allow_nominal_voice_action'},
                tenant_id=session.get('tenant_id'),
                workspace_id=session.get('workspace_id'),
                environment=session.get('environment'),
            )
            response_text = self._response_for_transcript(text)
            output = gw.audit.add_voice_output(
                voice_session_id,
                text=response_text,
                status='ready',
                voice_name='assistant',
                created_by=actor,
                metadata={'command_name': command_name, 'spoken': True},
                tenant_id=session.get('tenant_id'),
                workspace_id=session.get('workspace_id'),
                environment=session.get('environment'),
            )
            session = gw.audit.update_voice_session(voice_session_id, status='active', last_transcript_text=text, last_output_text=response_text, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
        gw.audit.log_event('inbound', 'voice', str(session.get('user_key') or actor or 'voice-user'), voice_session_id, {'action': 'voice_transcribed', 'command_name': command_name, 'requires_confirmation': sensitive, 'transcript_text': text, 'stage': stage}, tenant_id=session.get('tenant_id'), workspace_id=session.get('workspace_id'), environment=session.get('environment'))
        return {'ok': True, 'session': session, 'transcript': transcript, 'command': command, 'output': output}

    def _is_sensitive(self, text: str) -> bool:
        low = str(text or '').strip().lower()
        return any(token in low for token in self.SENSITIVE_TOKENS)

    def _command_name_from_text(self, text: str) -> str:
        low = str(text or '').strip().lower()
        for token, command_name in self.SENSITIVE_TOKENS.items():
            if token in low:
                return command_name
        for token, command_name in self.SIMPLE_TOKENS.items():
            if token in low:
                return command_name
        return 'freeform_voice_turn'

    def _response_for_transcript(self, text: str) -> str:
        low = str(text or '').strip().lower()
        if not low:
            return 'Voice session ready.'
        if 'status' in low or 'estado' in low:
            return 'Voice status OK. Session is active and audited.'
        if 'approval' in low or 'aprob' in low:
            return 'Approval lookup prepared for operator review.'
        if 'help' in low or 'ayuda' in low:
            return 'Available voice actions: status, approvals, and governed confirmations for sensitive commands.'
        return f'Voice response recorded for: {text}'
