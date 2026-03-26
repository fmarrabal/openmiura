from __future__ import annotations

import json
from pathlib import Path

from openmiura.application.packaging import PackagingHardeningService


def test_phase8_release_manifest_and_verification(tmp_path: Path) -> None:
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'openmiura-1.0.0.tar.gz').write_bytes(b'sdist')
    (dist / 'openmiura-1.0.0-py3-none-any.whl').write_bytes(b'wheel')
    (dist / 'openmiura-desktop-1.0.0-abc123.zip').write_bytes(b'bundle')
    (dist / 'openmiura-desktop-1.0.0-abc123.manifest.json').write_text(json.dumps({'ok': True}), encoding='utf-8')
    (dist / 'RELEASE_NOTES.md').write_text('notes\n', encoding='utf-8')

    service = PackagingHardeningService()
    created = service.generate_release_manifest(dist_dir=str(dist), tag='v1.0.0', target='desktop')

    assert created['ok'] is True
    assert Path(created['manifest_path']).exists()
    assert Path(created['checksums_path']).exists()

    verified = service.verify_release_artifacts(dist_dir=str(dist))
    assert verified['ok'] is True
    assert verified['artifact_count'] == 5

    (dist / 'openmiura-1.0.0-py3-none-any.whl').write_bytes(b'wheel-mutated')
    verified_after_change = service.verify_release_artifacts(dist_dir=str(dist))
    assert verified_after_change['ok'] is False
    assert 'openmiura-1.0.0-py3-none-any.whl' in verified_after_change['changed']


def test_phase8_release_summary_and_manifest_tree_are_present() -> None:
    service = PackagingHardeningService()
    summary = service.packaging_summary()
    release = service.release_summary()

    root = service._project_root()
    manifest_text = (root / 'MANIFEST.in').read_text(encoding='utf-8')
    workflow_text = (root / '.github/workflows/release.yml').read_text(encoding='utf-8')

    assert summary['targets']['release_alpha']['manifest'] is True
    assert summary['release_checks']['manifest_in'] is True
    assert release['checks']['release_build_script'] is True
    assert 'recursive-include packaging *' in manifest_text
    assert 'recursive-include .github/actions *.yml' in manifest_text
    assert 'python scripts/build_release_artifacts.py' in workflow_text
    assert 'python scripts/verify_release_artifacts.py --dist-dir dist' in workflow_text
    assert 'SOURCE_DATE_EPOCH' in workflow_text
