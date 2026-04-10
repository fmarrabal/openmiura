from __future__ import annotations

from openmiura.application.packaging import PackagingHardeningService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit


def test_phase8_pr8_packaging_hardening_records_builds_and_exposes_summary(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = PackagingHardeningService()

    summary = service.packaging_summary(gw)
    hardening = service.hardening_summary(gw)
    created = service.create_package_build(
        gw,
        actor='alice',
        target='desktop',
        label='Phase 8 desktop shell',
        version='phase8-pr8',
        artifact_path='dist/openmiura-phase8-desktop.zip',
        tenant_id='tenant-pkg',
        workspace_id='ws-shell',
        environment='prod',
        metadata={'channel': 'ci'},
    )
    listed = service.list_package_builds(
        gw,
        tenant_id='tenant-pkg',
        workspace_id='ws-shell',
        environment='prod',
    )

    assert summary['ok'] is True
    assert summary['targets']['desktop']['wrapper'] == 'electron'
    assert summary['targets']['mobile']['wrapper'] == 'capacitor'
    assert 'docs/quickstarts/admin.md' in summary['files']['quickstarts']
    assert hardening['profile']['voice']['max_transcripts_per_minute'] == 6
    assert created['build']['target'] == 'desktop'
    assert listed['summary']['count'] == 1
    assert listed['items'][0]['artifact_path'].endswith('.zip')
    assert audit.count_package_builds(tenant_id='tenant-pkg', workspace_id='ws-shell', environment='prod') == 1
