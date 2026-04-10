from __future__ import annotations

from openmiura.application.pwa import PWAFoundationService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit


def test_phase8_pr4_pwa_foundation_models_installations_notifications_and_deep_links(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = PWAFoundationService()

    installed = service.register_installation(
        gw,
        actor='alice',
        user_key='operator:alice',
        platform='pwa',
        device_label='Pixel test device',
        push_capable=True,
        notification_permission='granted',
        tenant_id='tenant-pwa',
        workspace_id='ws-mobile',
        environment='staging',
    )
    installation_id = installed['installation']['installation_id']
    assert installed['installation']['push_capable'] is True

    notified = service.create_notification(
        gw,
        actor='alice',
        title='Approval pending',
        body='A release is waiting in staging.',
        category='operator',
        installation_id=installation_id,
        target_path='/ui/?tab=operator&approval_id=appr_1',
        tenant_id='tenant-pwa',
        workspace_id='ws-mobile',
        environment='staging',
    )
    assert notified['notification']['installation_id'] == installation_id
    assert notified['notification']['target_path'].startswith('/ui/?tab=operator')

    linked = service.create_deep_link(
        gw,
        actor='alice',
        view='operator',
        target_type='approval',
        target_id='appr_1',
        params={'approval_id': 'appr_1', 'tab': 'operator'},
        expires_in_s=3600,
        tenant_id='tenant-pwa',
        workspace_id='ws-mobile',
        environment='staging',
    )
    assert linked['deep_link']['url'].startswith('/app/deep-links/')

    resolved = service.resolve_deep_link(gw, link_token=linked['deep_link']['link_token'])
    assert resolved['ok'] is True
    assert 'approval_id=appr_1' in resolved['ui_path']

    installations = service.list_installations(
        gw,
        tenant_id='tenant-pwa',
        workspace_id='ws-mobile',
        environment='staging',
    )
    notifications = service.list_notifications(
        gw,
        tenant_id='tenant-pwa',
        workspace_id='ws-mobile',
        environment='staging',
    )
    deep_links = service.list_deep_links(
        gw,
        tenant_id='tenant-pwa',
        workspace_id='ws-mobile',
        environment='staging',
    )
    assert len(installations['items']) == 1
    assert len(notifications['items']) == 1
    assert len(deep_links['items']) == 1
