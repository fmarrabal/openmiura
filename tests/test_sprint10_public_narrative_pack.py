from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_narrative_pack_is_linked_and_uses_single_positioning_language() -> None:
    docs_index = (ROOT / 'docs' / 'README.md').read_text(encoding='utf-8')
    canonical_demo = (ROOT / 'docs' / 'demos' / 'canonical_demo.md').read_text(encoding='utf-8')
    walkthrough = (ROOT / 'docs' / 'walkthroughs' / 'canonical_runtime_governance_walkthrough.md').read_text(encoding='utf-8')

    # Phase 0: README is intentionally short and hype-free. The legacy
    # marketing-speak that used to live here ("governed agent operations
    # platform", "Bring your runtime", "control plane", "not another
    # assistant") is no longer asserted on the public README.
    assert 'pending_approval' in canonical_demo
    assert 'signed' in canonical_demo.lower()
    assert 'canvas runtime inspector' in walkthrough.lower()
    assert 'public_narrative.md' in docs_index
    assert 'canonical_runtime_governance_walkthrough.md' in docs_index
    assert 'media/screenshot_plan.md' in docs_index


def test_public_material_files_exist() -> None:
    # Phase 0: medium_article_* and stable_release_text_pack live under
    # docs/_archive/ now and are no longer asserted as live material.
    expected = [
        ROOT / 'docs' / 'public_narrative.md',
        ROOT / 'docs' / 'walkthroughs' / 'canonical_runtime_governance_walkthrough.md',
        ROOT / 'docs' / 'media' / 'screenshot_plan.md',
    ]
    for path in expected:
        assert path.exists(), str(path)
