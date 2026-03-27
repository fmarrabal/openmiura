from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_enterprise_alpha_docs_cover_installation_risks_limitations_and_checklist() -> None:
    guide = (ROOT / 'docs/enterprise_alpha.md').read_text(encoding='utf-8')
    checklist = (ROOT / 'docs/alpha_release_checklist.md').read_text(encoding='utf-8')

    assert 'Self-hosted Enterprise Alpha' in guide
    assert 'Requirements' in guide
    assert 'Recommended installation path' in guide
    assert 'Known risks and residual limitations' in guide
    assert 'docker compose up --build -d' in guide
    assert 'openmiura doctor --config configs/' in guide
    assert 'scripts/build_release_artifacts.py' in guide
    assert 'scripts/verify_release_artifacts.py' in guide
    assert 'OpenClaw' in guide

    assert 'Enterprise Alpha release checklist' in checklist
    assert 'SHA256SUMS.txt' in checklist
    assert 'RELEASE_MANIFEST.json' in checklist
    assert 'GO for controlled alpha distribution' in checklist
    assert 'NO-GO until issues are fixed and revalidated' in checklist


def test_docs_index_and_primary_guides_link_to_enterprise_alpha_material() -> None:
    docs_index = (ROOT / 'docs/README.md').read_text(encoding='utf-8')
    installation = (ROOT / 'docs/installation.md').read_text(encoding='utf-8')
    production = (ROOT / 'docs/production.md').read_text(encoding='utf-8')
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')

    assert 'enterprise_alpha.md' in docs_index
    assert 'alpha_release_checklist.md' in docs_index
    assert 'enterprise_alpha.md' in installation
    assert 'alpha_release_checklist.md' in installation
    assert 'enterprise_alpha.md' in production
    assert 'alpha_release_checklist.md' in production
    assert 'docs/enterprise_alpha.md' in readme
