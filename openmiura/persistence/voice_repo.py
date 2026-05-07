"""VoiceRepo: persistence for the voice domain of openMiura.

Owns the persistence logic for the voice-related tables. The class
is instantiated by ``AuditStore`` so existing public callers remain
unaffected; ``AuditStore`` keeps thin one-line delegators on its API.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from openmiura.core.db import DBConnection, CompatRow
from openmiura.core.tenancy.scope import assert_scope_match, normalize_scope
from openmiura.persistence.base import row_scope, scope_payload, scope_where


class VoiceRepo:
    def __init__(self, conn: DBConnection) -> None:
        self._conn = conn

    @staticmethod
    def _scope_payload(*, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return scope_payload(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    @staticmethod
    def _row_scope(row: Any) -> dict[str, Any]:
        return row_scope(row)

    def _scope_where(self, clauses: list[str], params: list[Any], *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, prefix: str = "") -> tuple[list[str], list[Any]]:
        return scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, prefix=prefix)

    def _voice_session_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'voice_session_id': row['voice_session_id'],
            'channel': row['channel'],
            'user_key': row['user_key'],
            'status': row['status'],
            'locale': row['locale'],
            'stt_provider': row['stt_provider'],
            'tts_provider': row['tts_provider'],
            'started_at': float(row['started_at']),
            'updated_at': float(row['updated_at']),
            'closed_at': float(row['closed_at']) if row['closed_at'] is not None else None,
            'last_transcript_text': row['last_transcript_text'] or '',
            'last_output_text': row['last_output_text'] or '',
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _voice_transcript_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'id': int(row['id']),
            'voice_session_id': row['voice_session_id'],
            'direction': row['direction'],
            'stage': row['stage'],
            'text': row['text'],
            'confidence': float(row['confidence']) if row['confidence'] is not None else None,
            'language': row['language'] or '',
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _voice_output_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'output_id': row['output_id'],
            'voice_session_id': row['voice_session_id'],
            'text': row['text'],
            'status': row['status'],
            'voice_name': row['voice_name'],
            'audio_ref': row['audio_ref'] or '',
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _voice_command_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            payload = json.loads(row['command_payload_json'] or '{}')
        except Exception:
            payload = {}
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'command_id': row['command_id'],
            'voice_session_id': row['voice_session_id'],
            'command_name': row['command_name'],
            'command_payload': payload,
            'status': row['status'],
            'requires_confirmation': bool(row['requires_confirmation']),
            'confirmed_by': row['confirmed_by'] or '',
            'confirmed_at': float(row['confirmed_at']) if row['confirmed_at'] is not None else None,
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def count_voice_sessions(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_sessions'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_voice_transcripts(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_transcripts'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_voice_outputs(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_outputs'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_voice_commands(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_commands'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def create_voice_session(
        self,
        *,
        channel: str = 'voice',
        user_key: str,
        locale: str = 'es-ES',
        stt_provider: str = 'simulated-stt',
        tts_provider: str = 'simulated-tts',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        voice_session_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO voice_sessions(voice_session_id, channel, user_key, status, locale, stt_provider, tts_provider, started_at, updated_at, closed_at, last_transcript_text, last_output_text, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (voice_session_id, channel, user_key, 'active', locale, stt_provider, tts_provider, now, now, None, '', '', json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        return self.get_voice_session(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or {
            'voice_session_id': voice_session_id,
            'channel': channel,
            'user_key': user_key,
            'status': 'active',
            'locale': locale,
            'stt_provider': stt_provider,
            'tts_provider': tts_provider,
            'started_at': float(now),
            'updated_at': float(now),
            'closed_at': None,
            'last_transcript_text': '',
            'last_output_text': '',
            'metadata': dict(metadata or {}),
            'tenant_id': tenant_id,
            'workspace_id': workspace_id,
            'environment': environment,
        }

    def list_voice_sessions(self, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        sql = 'SELECT voice_session_id, channel, user_key, status, locale, stt_provider, tts_provider, started_at, updated_at, closed_at, last_transcript_text, last_output_text, metadata_json, tenant_id, workspace_id, environment FROM voice_sessions'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY updated_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._voice_session_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def get_voice_session(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute(
            'SELECT voice_session_id, channel, user_key, status, locale, stt_provider, tts_provider, started_at, updated_at, closed_at, last_transcript_text, last_output_text, metadata_json, tenant_id, workspace_id, environment FROM voice_sessions WHERE ' + ' AND '.join(clauses) + ' LIMIT 1',
            tuple(params),
        ).fetchone()
        return self._voice_session_row_to_dict(row) if row is not None else None

    def update_voice_session(
        self,
        voice_session_id: str,
        *,
        status: str | None = None,
        last_transcript_text: str | None = None,
        last_output_text: str | None = None,
        metadata: dict[str, Any] | None = None,
        closed: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_voice_session(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if current is None:
            return None
        next_metadata = dict(current.get('metadata') or {})
        next_metadata.update(dict(metadata or {}))
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'UPDATE voice_sessions SET status=?, updated_at=?, closed_at=?, last_transcript_text=?, last_output_text=?, metadata_json=? WHERE voice_session_id=?',
            (
                status or current.get('status') or 'active',
                now,
                now if closed else current.get('closed_at'),
                last_transcript_text if last_transcript_text is not None else current.get('last_transcript_text') or '',
                last_output_text if last_output_text is not None else current.get('last_output_text') or '',
                json.dumps(next_metadata, ensure_ascii=False),
                voice_session_id,
            ),
        )
        self._conn.commit()
        return self.get_voice_session(voice_session_id, tenant_id=current.get('tenant_id'), workspace_id=current.get('workspace_id'), environment=current.get('environment'))

    def add_voice_transcript(
        self,
        voice_session_id: str,
        *,
        direction: str,
        stage: str,
        text: str,
        confidence: float | None = None,
        language: str = '',
        created_by: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO voice_transcripts(voice_session_id, direction, stage, text, confidence, language, created_by, created_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (voice_session_id, direction, stage, text, confidence, language or '', created_by or '', now, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        row_id = int(cur.lastrowid)
        cur.execute('UPDATE voice_sessions SET updated_at=?, last_transcript_text=? WHERE voice_session_id=?', (now, text, voice_session_id))
        self._conn.commit()
        row = cur.execute('SELECT id, voice_session_id, direction, stage, text, confidence, language, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_transcripts WHERE id=?', (row_id,)).fetchone()
        return self._voice_transcript_row_to_dict(row)

    def list_voice_transcripts(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT id, voice_session_id, direction, stage, text, confidence, language, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_transcripts WHERE ' + ' AND '.join(clauses) + ' ORDER BY id ASC LIMIT ?'
        params.append(int(limit))
        return [self._voice_transcript_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def add_voice_output(
        self,
        voice_session_id: str,
        *,
        text: str,
        status: str = 'ready',
        voice_name: str = 'assistant',
        audio_ref: str = '',
        created_by: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        output_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO voice_outputs(output_id, voice_session_id, text, status, voice_name, audio_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (output_id, voice_session_id, text, status, voice_name, audio_ref or '', created_by or '', now, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        cur.execute('UPDATE voice_sessions SET updated_at=?, last_output_text=? WHERE voice_session_id=?', (now, text, voice_session_id))
        self._conn.commit()
        row = cur.execute('SELECT output_id, voice_session_id, text, status, voice_name, audio_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_outputs WHERE output_id=?', (output_id,)).fetchone()
        return self._voice_output_row_to_dict(row)

    def list_voice_outputs(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT output_id, voice_session_id, text, status, voice_name, audio_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_outputs WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at ASC LIMIT ?'
        params.append(int(limit))
        return [self._voice_output_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def create_voice_command(
        self,
        voice_session_id: str,
        *,
        command_name: str,
        command_payload: dict[str, Any] | None = None,
        status: str = 'detected',
        requires_confirmation: bool = False,
        confirmed_by: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        command_id = str(uuid.uuid4())
        now = time.time()
        confirmed_at = now if confirmed_by else None
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO voice_commands(command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (command_id, voice_session_id, command_name, json.dumps(command_payload or {}, ensure_ascii=False), status, 1 if requires_confirmation else 0, confirmed_by or None, confirmed_at, now, now, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        row = cur.execute('SELECT command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM voice_commands WHERE command_id=?', (command_id,)).fetchone()
        return self._voice_command_row_to_dict(row)

    def list_voice_commands(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM voice_commands WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at ASC LIMIT ?'
        params.append(int(limit))
        return [self._voice_command_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def get_latest_pending_voice_command(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?', 'status=?']
        params: list[Any] = [voice_session_id, 'pending_confirmation']
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute(
            'SELECT command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM voice_commands WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at DESC LIMIT 1',
            tuple(params),
        ).fetchone()
        return self._voice_command_row_to_dict(row) if row is not None else None

    def resolve_voice_command(self, command_id: str, *, decision: str, actor: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['command_id=?']
        params: list[Any] = [command_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute(
            'SELECT command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM voice_commands WHERE ' + ' AND '.join(clauses) + ' LIMIT 1',
            tuple(params),
        ).fetchone()
        if row is None:
            return None
        current = self._voice_command_row_to_dict(row)
        now = time.time()
        next_status = 'confirmed' if decision == 'confirm' else 'cancelled'
        cur.execute(
            'UPDATE voice_commands SET status=?, confirmed_by=?, confirmed_at=?, updated_at=? WHERE command_id=?',
            (next_status, actor, now, now, command_id),
        )
        self._conn.commit()
        return self.get_latest_voice_command(command_id)

    def get_latest_voice_command(self, command_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            'SELECT command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM voice_commands WHERE command_id=? LIMIT 1',
            (command_id,),
        ).fetchone()
        return self._voice_command_row_to_dict(row) if row is not None else None

    def _voice_audio_asset_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'asset_id': row['asset_id'],
            'voice_session_id': row['voice_session_id'],
            'direction': row['direction'],
            'asset_kind': row['asset_kind'],
            'mime_type': row['mime_type'],
            'sample_rate_hz': int(row['sample_rate_hz'] or 0),
            'byte_count': int(row['byte_count'] or 0),
            'sha256': row['sha256'] or '',
            'storage_ref': row['storage_ref'] or '',
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _voice_provider_call_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            request = json.loads(row['request_json'] or '{}')
        except Exception:
            request = {}
        try:
            response = json.loads(row['response_json'] or '{}')
        except Exception:
            response = {}
        return {
            'provider_call_id': row['provider_call_id'],
            'voice_session_id': row['voice_session_id'],
            'provider_kind': row['provider_kind'],
            'provider_name': row['provider_name'],
            'status': row['status'],
            'request': request,
            'response': response,
            'error_text': row['error_text'] or '',
            'latency_ms': float(row['latency_ms']) if row['latency_ms'] is not None else None,
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def count_voice_audio_assets(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_audio_assets'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_voice_provider_calls(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_provider_calls'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def create_voice_audio_asset(self, voice_session_id: str, *, direction: str, asset_kind: str, mime_type: str, sample_rate_hz: int = 0, byte_count: int = 0, sha256: str = '', storage_ref: str = '', created_by: str = '', metadata: dict[str, Any] | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        asset_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute('INSERT INTO voice_audio_assets(asset_id, voice_session_id, direction, asset_kind, mime_type, sample_rate_hz, byte_count, sha256, storage_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (asset_id, voice_session_id, direction, asset_kind, mime_type, int(sample_rate_hz or 0), int(byte_count or 0), sha256 or '', storage_ref or '', created_by or '', now, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment))
        self._conn.commit()
        row = cur.execute('SELECT asset_id, voice_session_id, direction, asset_kind, mime_type, sample_rate_hz, byte_count, sha256, storage_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_audio_assets WHERE asset_id=?', (asset_id,)).fetchone()
        return self._voice_audio_asset_row_to_dict(row)

    def list_voice_audio_assets(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT asset_id, voice_session_id, direction, asset_kind, mime_type, sample_rate_hz, byte_count, sha256, storage_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_audio_assets WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at ASC LIMIT ?'
        params.append(int(limit))
        return [self._voice_audio_asset_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def create_voice_provider_call(self, voice_session_id: str, *, provider_kind: str, provider_name: str, status: str, request: dict[str, Any] | None = None, response: dict[str, Any] | None = None, error_text: str = '', latency_ms: float | None = None, created_by: str = '', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        provider_call_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute('INSERT INTO voice_provider_calls(provider_call_id, voice_session_id, provider_kind, provider_name, status, request_json, response_json, error_text, latency_ms, created_by, created_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (provider_call_id, voice_session_id, provider_kind, provider_name, status, json.dumps(request or {}, ensure_ascii=False), json.dumps(response or {}, ensure_ascii=False), error_text or '', latency_ms, created_by or '', now, tenant_id, workspace_id, environment))
        self._conn.commit()
        row = cur.execute('SELECT provider_call_id, voice_session_id, provider_kind, provider_name, status, request_json, response_json, error_text, latency_ms, created_by, created_at, tenant_id, workspace_id, environment FROM voice_provider_calls WHERE provider_call_id=?', (provider_call_id,)).fetchone()
        return self._voice_provider_call_row_to_dict(row)

    def list_voice_provider_calls(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT provider_call_id, voice_session_id, provider_kind, provider_name, status, request_json, response_json, error_text, latency_ms, created_by, created_at, tenant_id, workspace_id, environment FROM voice_provider_calls WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at ASC LIMIT ?'
        params.append(int(limit))
        return [self._voice_provider_call_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]
