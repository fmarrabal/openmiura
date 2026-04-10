from __future__ import annotations

import pytest

from openmiura.application.canvas import LiveCanvasService
from openmiura.application.packaging import PackagingHardeningService
from openmiura.application.voice import VoiceRuntimeService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit
        self.policy = None


def test_phase8_pr8_hardening_smoke_limits_voice_and_canvas_payloads(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)

    voice = VoiceRuntimeService()
    canvas = LiveCanvasService()
    limits = PackagingHardeningService.DEFAULT_HARDENING

    started = voice.start_session(
        gw,
        actor='alice',
        user_key='voice:user-1',
        tenant_id='tenant-smoke',
        workspace_id='ws-smoke',
        environment='staging',
    )
    voice_session_id = started['session']['voice_session_id']

    with pytest.raises(ValueError, match='voice transcript exceeds max length'):
        voice.transcribe(
            gw,
            voice_session_id=voice_session_id,
            actor='alice',
            transcript_text='x' * (limits['voice']['max_transcript_chars'] + 1),
            tenant_id='tenant-smoke',
            workspace_id='ws-smoke',
            environment='staging',
        )

    created = canvas.create_document(
        gw,
        actor='alice',
        title='Smoke canvas',
        tenant_id='tenant-smoke',
        workspace_id='ws-smoke',
        environment='staging',
    )
    canvas_id = created['document']['canvas_id']

    with pytest.raises(ValueError, match='canvas payload exceeds max size'):
        canvas.upsert_node(
            gw,
            canvas_id=canvas_id,
            actor='alice',
            node_type='note',
            label='oversized',
            data={'blob': 'x' * (limits['canvas']['max_payload_chars'] + 100)},
            tenant_id='tenant-smoke',
            workspace_id='ws-smoke',
            environment='staging',
        )

    node = canvas.upsert_node(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        node_type='note',
        label='normal',
        tenant_id='tenant-smoke',
        workspace_id='ws-smoke',
        environment='staging',
    )

    with pytest.raises(ValueError, match='canvas snapshot exceeds max size'):
        canvas.create_snapshot(
            gw,
            canvas_id=canvas_id,
            actor='alice',
            label='oversized snapshot',
            metadata={'blob': 'x' * (limits['canvas']['max_snapshot_bytes'] + 100)},
            selected_node_id=node['node']['node_id'],
            tenant_id='tenant-smoke',
            workspace_id='ws-smoke',
            environment='staging',
        )
