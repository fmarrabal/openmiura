from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_publication_final_pack_files_exist_and_are_indexed() -> None:
    docs_index = (ROOT / 'docs' / 'README.md').read_text(encoding='utf-8')
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    expected = [
        ROOT / 'docs' / 'media' / 'medium_article_final.md',
        ROOT / 'docs' / 'media' / 'medium_article_publication_pack.md',
        ROOT / 'docs' / 'release' / 'stable_release_final_pack.md',
        ROOT / 'docs' / 'media' / 'publication_reuse_note.md',
    ]
    for path in expected:
        assert path.exists(), str(path)

    assert 'medium_article_final.md' in docs_index
    assert 'medium_article_publication_pack.md' in docs_index
    assert 'stable_release_final_pack.md' in docs_index
    assert 'publication_reuse_note.md' in docs_index

    assert 'Medium article final' in readme
    assert 'Medium article publication pack' in readme
    assert 'Stable release final pack' in readme


def test_medium_article_final_uses_the_control_plane_narrative() -> None:
    article = (ROOT / 'docs' / 'media' / 'medium_article_final.md').read_text(encoding='utf-8')
    publication_pack = (ROOT / 'docs' / 'media' / 'medium_article_publication_pack.md').read_text(encoding='utf-8')
    public_narrative = (ROOT / 'docs' / 'public_narrative.md').read_text(encoding='utf-8')

    assert 'governed agent operations platform' in article.lower()
    assert 'control plane' in article.lower()
    assert 'the runtime executes' in article.lower()
    assert 'openmiura governs' in article.lower()
    assert 'pending_approval' in article
    assert 'canvas' in article.lower()
    assert 'OpenClaw is one runtime that openMiura can govern' in article
    assert 'Stop Demoing Agents. Start Governing Runtime Operations.' in publication_pack
    assert 'What not to promise yet' in publication_pack
    assert 'Bring your runtime. openMiura governs it.' in public_narrative


def test_stable_release_final_pack_points_to_real_install_and_demo_paths() -> None:
    release_pack = (ROOT / 'docs' / 'release' / 'stable_release_final_pack.md').read_text(encoding='utf-8')
    installation = (ROOT / 'docs' / 'installation.md').read_text(encoding='utf-8')
    canonical_demo = (ROOT / 'docs' / 'demos' / 'canonical_demo.md').read_text(encoding='utf-8')
    screenshot_plan = (ROOT / 'docs' / 'media' / 'screenshot_plan.md').read_text(encoding='utf-8')
    reuse_note = (ROOT / 'docs' / 'media' / 'publication_reuse_note.md').read_text(encoding='utf-8')

    assert 'openmiura doctor --config configs/openmiura.yaml' in release_pack
    assert 'python scripts/run_canonical_demo.py --output demo_artifacts/canonical-demo-report.json' in release_pack
    assert 'reproducible bundle zip' in release_pack.lower()
    assert 'v1.0.0-rc1' in release_pack and 'v1.0.0' in release_pack
    assert 'canonical demo' in installation.lower()
    assert 'governed runtime alert policy activation' in canonical_demo.lower()
    assert '08-current-version-signed-evidence.png' in screenshot_plan
    assert 'cut `v1.0.0`' in reuse_note
