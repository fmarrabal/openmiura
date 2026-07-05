from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding='utf-8'))


def test_release_workflow_supports_stable_publication_to_github_release() -> None:
    workflow = _load_yaml('.github/workflows/release.yml')

    assert 'workflow_dispatch' in workflow['on']
    assert workflow['on']['release']['types'] == ['published']
    assert workflow['permissions']['contents'] == 'write'

    steps = workflow['jobs']['build-release']['steps']
    meta_step = next(step for step in steps if step.get('name') == 'Resolve release metadata')
    upload_step = next(step for step in steps if step.get('name') == 'Upload workflow artifacts')
    publish_step = next(step for step in steps if step.get('name') == 'Upload official assets to GitHub Release')

    assert 'publish_release' in meta_step['run']
    assert str(upload_step['uses']).startswith('actions/upload-artifact@')
    assert publish_step['if'] == "steps.meta.outputs.publish_release == 'true'"
    assert 'gh release upload' in publish_step['run']
    assert 'dist/RELEASE_MANIFEST.json' in publish_step['run']
    assert 'dist/SHA256SUMS.txt' in publish_step['run']


def test_release_workflow_publishes_to_pypi_via_trusted_publishing() -> None:
    workflow = _load_yaml('.github/workflows/release.yml')
    job = workflow['jobs']['publish-pypi']

    # Gated on the same stable-publish decision as the GitHub Release upload.
    assert job['needs'] == 'build-release'
    assert job['if'] == "needs.build-release.outputs.publish_release == 'true'"
    # Approval gate + OIDC (no long-lived token stored in the repo).
    assert job['environment'] == 'pypi'
    assert job['permissions']['id-token'] == 'write'
    # Top-level workflow permissions stay least-privilege (contents only).
    assert 'id-token' not in workflow['permissions']

    publish = next(s for s in job['steps'] if str(s.get('uses', '')).startswith('pypa/gh-action-pypi-publish'))
    assert publish['with']['packages-dir'] == 'dist-pypi'


def test_stable_release_publication_docs_are_linked_and_define_rc_vs_stable_policy() -> None:
    docs_index = (ROOT / 'docs' / 'README.md').read_text(encoding='utf-8')
    publication = (ROOT / 'docs' / 'release_publication.md').read_text(encoding='utf-8')
    checklist = (ROOT / 'docs' / 'github_pr_merge_publish_checklist.md').read_text(encoding='utf-8')
    rc = (ROOT / 'docs' / 'release_candidate.md').read_text(encoding='utf-8')

    # Phase 0: release-publication policy link lives in docs/README.md,
    # not in the top-level README.md.
    assert 'release_publication.md' in docs_index
    assert 'RC / pre-release' in publication
    assert 'Stable releases are the first GitHub Releases that carry the official downloadable artifact set.' in publication
    assert 'v1.0.0-rc1' in publication
    assert 'v1.0.0' in publication
    assert 'official wheel/sdist/bundle/manifest/checksum assets' in checklist
    assert 'stable `v1.0.0` release' in rc
