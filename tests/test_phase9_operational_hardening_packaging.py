from __future__ import annotations

from pathlib import Path

from openmiura.application.packaging import PackagingHardeningService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit


def test_phase9_packaging_reproducible_build_and_manifest_verify(tmp_path: Path):
    project = tmp_path / 'project'
    (project / 'openmiura').mkdir(parents=True)
    (project / 'docs').mkdir(parents=True)
    (project / 'scripts').mkdir(parents=True)
    (project / 'README.md').write_text('demo\n', encoding='utf-8')
    (project / 'app.py').write_text('print("ok")\n', encoding='utf-8')
    (project / 'openmiura' / '__init__.py').write_text('__all__ = []\n', encoding='utf-8')
    (project / 'docs' / 'note.md').write_text('# note\n', encoding='utf-8')
    (project / 'scripts' / 'tool.py').write_text('print("tool")\n', encoding='utf-8')

    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = PackagingHardeningService()

    first = service.create_reproducible_build(
        gw,
        actor='alice',
        target='desktop',
        label='Deterministic desktop',
        version='v1',
        source_root=str(project),
        output_dir=str(project / 'dist'),
        tenant_id='tenant-p',
        workspace_id='ws-p',
        environment='prod',
    )
    second = service.create_reproducible_build(
        gw,
        actor='alice',
        target='desktop',
        label='Deterministic desktop',
        version='v1',
        source_root=str(project),
        output_dir=str(project / 'dist'),
        tenant_id='tenant-p',
        workspace_id='ws-p',
        environment='prod',
    )
    assert first['manifest_hash'] == second['manifest_hash']
    assert first['artifact_path'] == second['artifact_path']

    verified = service.verify_reproducible_manifest(manifest_path=first['manifest_path'])
    assert verified['ok'] is True
    assert Path(first['artifact_path']).exists()
    assert Path(first['manifest_path']).exists()
    assert audit.count_package_builds(tenant_id='tenant-p', workspace_id='ws-p', environment='prod') == 2
