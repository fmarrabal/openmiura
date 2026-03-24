from __future__ import annotations

import base64

from openmiura.application.voice import VoiceRuntimeService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit


def test_phase9_voice_audio_assets_and_provider_calls_are_audited(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = VoiceRuntimeService()

    started = service.start_session(
        gw,
        actor='alice',
        user_key='voice:user-audio',
        locale='en-US',
        stt_provider='local-inline-stt',
        tts_provider='local-wave-tts',
        tenant_id='tenant-a',
        workspace_id='ws-audio',
        environment='prod',
    )
    voice_session_id = started['session']['voice_session_id']

    payload = service.transcribe_audio(
        gw,
        voice_session_id=voice_session_id,
        actor='alice',
        audio_b64=base64.b64encode(b'check status from audio').decode('ascii'),
        mime_type='audio/wav',
        sample_rate_hz=16000,
        tenant_id='tenant-a',
        workspace_id='ws-audio',
        environment='prod',
    )
    assert payload['input_audio_asset']['byte_count'] > 0
    assert payload['provider_call']['provider_kind'] == 'stt'
    assert payload['transcript']['stage'] == 'stt_audio'
    assert payload['command']['status'] == 'executed'

    responded = service.respond(
        gw,
        voice_session_id=voice_session_id,
        actor='alice',
        text='System nominal, continuing with audited response.',
        voice_name='operator',
        metadata={'emit_audio': True},
        tenant_id='tenant-a',
        workspace_id='ws-audio',
        environment='prod',
    )
    assert responded['audio_asset']['mime_type'] == 'audio/wav'
    assert responded['provider_call']['provider_kind'] == 'tts'
    assert responded['output']['audio_ref'] == responded['audio_asset']['asset_id']

    detail = service.get_session(
        gw,
        voice_session_id=voice_session_id,
        tenant_id='tenant-a',
        workspace_id='ws-audio',
        environment='prod',
    )
    assert len(detail['audio_assets']) == 2
    assert len(detail['provider_calls']) == 2
    assert audit.count_voice_audio_assets(tenant_id='tenant-a', workspace_id='ws-audio', environment='prod') == 2
    assert audit.count_voice_provider_calls(tenant_id='tenant-a', workspace_id='ws-audio', environment='prod') == 2
