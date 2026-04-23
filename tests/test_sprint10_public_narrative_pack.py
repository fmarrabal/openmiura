from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_narrative_pack_is_linked_and_uses_single_positioning_language() -> None:
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    docs_index = (ROOT / 'docs' / 'README.md').read_text(encoding='utf-8')
    public_narrative = (ROOT / 'docs' / 'public_narrative.md').read_text(encoding='utf-8')
    canonical_demo = (ROOT / 'docs' / 'demos' / 'canonical_demo.md').read_text(encoding='utf-8')
    walkthrough = (ROOT / 'docs' / 'walkthroughs' / 'canonical_runtime_governance_walkthrough.md').read_text(encoding='utf-8')

    assert 'governed agent operations platform' in readme.lower()
    assert 'governed agent operations platform' in public_narrative.lower()
    assert 'Bring your runtime. openMiura governs it.' in readme
    assert 'Bring your runtime. openMiura governs it.' in public_narrative
    assert 'control plane' in readme.lower()
    assert 'control plane' in public_narrative.lower()
    assert 'not another assistant' in readme.lower()
    assert 'pending_approval' in canonical_demo
    assert 'signed' in canonical_demo.lower()
    assert 'canvas runtime inspector' in walkthrough.lower()
    assert 'public_narrative.md' in docs_index
    assert 'canonical_runtime_governance_walkthrough.md' in docs_index
    assert 'media/screenshot_plan.md' in docs_index


def test_media_pack_and_release_text_pack_reference_real_assets_and_limits() -> None:
    screenshot_plan = (ROOT / 'docs' / 'media' / 'screenshot_plan.md').read_text(encoding='utf-8')
    medium_outline = (ROOT / 'docs' / 'media' / 'medium_article_outline.md').read_text(encoding='utf-8')
    medium_draft = (ROOT / 'docs' / 'media' / 'medium_article_draft.md').read_text(encoding='utf-8')
    release_pack = (ROOT / 'docs' / 'media' / 'stable_release_text_pack.md').read_text(encoding='utf-8')
    publication = (ROOT / 'docs' / 'release_publication.md').read_text(encoding='utf-8')
    installation = (ROOT / 'docs' / 'installation.md').read_text(encoding='utf-8')

    assert '01-installation-health-check.png' in screenshot_plan
    assert '05-canvas-inspector-action.png' in screenshot_plan
    assert '08-current-version-signed-evidence.png' in screenshot_plan
    assert 'Stop Demoing Agents. Start Governing Runtime Operations.' in medium_outline
    assert 'not another chatbot' in medium_draft.lower()
    assert 'OpenClaw is one runtime that openMiura can govern' in medium_draft
    assert 'v1.0.0-rc1' in release_pack and 'v1.0.0' in release_pack
    assert 'reproducible bundle zip' in release_pack
    assert 'reproducible bundle zip' in publication
    assert 'canonical demo' in installation.lower()


def test_public_material_files_exist() -> None:
    expected = [
        ROOT / 'docs' / 'public_narrative.md',
        ROOT / 'docs' / 'walkthroughs' / 'canonical_runtime_governance_walkthrough.md',
        ROOT / 'docs' / 'media' / 'screenshot_plan.md',
        ROOT / 'docs' / 'media' / 'medium_article_outline.md',
        ROOT / 'docs' / 'media' / 'medium_article_draft.md',
        ROOT / 'docs' / 'media' / 'stable_release_text_pack.md',
    ]
    for path in expected:
        assert path.exists(), str(path)
