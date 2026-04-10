from __future__ import annotations

from openmiura.application.voice import VoiceRuntimeService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit


def test_phase8_pr3_voice_runtime_sessions_are_modeled_persisted_and_confirm_sensitive_actions(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = VoiceRuntimeService()

    started = service.start_session(
        gw,
        actor='alice',
        user_key='voice:user-1',
        locale='es-ES',
        tenant_id='tenant-a',
        workspace_id='ws-1',
        environment='staging',
    )
    voice_session_id = started['session']['voice_session_id']
    assert started['session']['status'] == 'active'

    nominal = service.transcribe(
        gw,
        voice_session_id=voice_session_id,
        actor='alice',
        transcript_text='check status for the current workspace',
        confidence=0.98,
        language='en',
        tenant_id='tenant-a',
        workspace_id='ws-1',
        environment='staging',
    )
    assert nominal['command']['requires_confirmation'] is False
    assert nominal['command']['status'] == 'executed'
    assert 'status' in nominal['output']['text'].lower()

    sensitive = service.transcribe(
        gw,
        voice_session_id=voice_session_id,
        actor='alice',
        transcript_text='promote this release to production',
        confidence=0.99,
        language='en',
        tenant_id='tenant-a',
        workspace_id='ws-1',
        environment='staging',
    )
    assert sensitive['command']['requires_confirmation'] is True
    assert sensitive['command']['status'] == 'pending_confirmation'
    assert sensitive['session']['status'] == 'awaiting_confirmation'

    confirmed = service.confirm(
        gw,
        voice_session_id=voice_session_id,
        actor='alice',
        decision='confirm',
        confirmation_text='yes, confirm',
        tenant_id='tenant-a',
        workspace_id='ws-1',
        environment='staging',
    )
    assert confirmed['command']['status'] == 'confirmed'
    assert confirmed['session']['status'] == 'active'

    closed = service.close_session(
        gw,
        voice_session_id=voice_session_id,
        actor='alice',
        reason='done',
        tenant_id='tenant-a',
        workspace_id='ws-1',
        environment='staging',
    )
    assert closed['session']['status'] == 'closed'

    detail = service.get_session(
        gw,
        voice_session_id=voice_session_id,
        tenant_id='tenant-a',
        workspace_id='ws-1',
        environment='staging',
    )
    assert detail['ok'] is True
    assert len(detail['transcripts']) >= 3
    assert len(detail['outputs']) >= 3
    assert any(item['status'] == 'confirmed' for item in detail['commands'])
    assert detail['session']['closed_at'] is not None
