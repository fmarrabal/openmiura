from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_candidate_docs_exist_and_are_linked() -> None:
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    docs_index = (ROOT / 'docs' / 'README.md').read_text(encoding='utf-8')
    installation = (ROOT / 'docs' / 'installation.md').read_text(encoding='utf-8')
    production = (ROOT / 'docs' / 'production.md').read_text(encoding='utf-8')

    assert (ROOT / 'RELEASE_NOTES_RC1.md').exists()
    assert (ROOT / 'docs' / 'release_candidate.md').exists()
    assert (ROOT / 'docs' / 'release_support_matrix.md').exists()
    assert (ROOT / 'docs' / 'quickstarts' / 'release_candidate.md').exists()
    assert 'docs/release_candidate.md' in readme
    assert 'docs/release_support_matrix.md' in readme
    assert 'RELEASE_NOTES_RC1.md' in readme
    assert 'release_candidate.md' in docs_index
    assert 'release_support_matrix.md' in docs_index
    assert 'quickstarts/release_candidate.md' in installation
    assert 'quickstarts/release_candidate.md' in production


def test_release_candidate_docs_cover_freeze_scope_and_validation() -> None:
    rc = (ROOT / 'docs' / 'release_candidate.md').read_text(encoding='utf-8')
    quickstart = (ROOT / 'docs' / 'quickstarts' / 'release_candidate.md').read_text(encoding='utf-8')
    notes = (ROOT / 'RELEASE_NOTES_RC1.md').read_text(encoding='utf-8')
    matrix = (ROOT / 'docs' / 'release_support_matrix.md').read_text(encoding='utf-8')

    assert 'python scripts/freeze_release_candidate.py --output-dir dist/rc --label rc1 --version 1.0.0-rc1' in rc
    assert 'openmiura doctor --config configs/openmiura.yaml' in rc
    assert 'python scripts/run_release_quality_gate.py --include-extended --output-dir reports/quality_gate' in quickstart
    assert 'controlled pilots' in notes
    assert 'Voice runtime | Preview' in matrix


def test_enterprise_alpha_docs_use_explicit_config_path_and_rc_companions() -> None:
    guide = (ROOT / 'docs' / 'enterprise_alpha.md').read_text(encoding='utf-8')
    checklist = (ROOT / 'docs' / 'alpha_release_checklist.md').read_text(encoding='utf-8')

    assert 'openmiura doctor --config configs/openmiura.yaml' in guide
    assert 'RELEASE_NOTES_RC1.md' in guide
    assert 'openmiura doctor --config configs/openmiura.yaml' in checklist
    assert 'docs/release_candidate.md' in checklist


def test_freeze_script_supports_documented_arguments() -> None:
    path = ROOT / 'scripts' / 'freeze_release_candidate.py'
    namespace = {'__name__': 'freeze_release_candidate_test', '__file__': str(path)}
    code = compile(path.read_text(encoding='utf-8'), str(path), 'exec')
    exec(code, namespace)
    args = namespace['parse_args'](['--output-dir', 'custom', '--label', 'candidate', '--version', '9.9.9-rc1'])
    assert args.output_dir == 'custom'
    assert args.label == 'candidate'
    assert args.version == '9.9.9-rc1'

def test_release_tree_is_clean_of_known_stale_artifacts() -> None:
    assert not (ROOT / 'configs' / 'configs' / 'evaluations.yaml').exists()

    egg_info = ROOT / 'openmiura.egg-info'
    if egg_info.exists():
        assert egg_info.is_dir()
        assert {p.name for p in egg_info.iterdir()}.issubset({
            'PKG-INFO',
            'SOURCES.txt',
            'dependency_links.txt',
            'entry_points.txt',
            'not-zip-safe',
            'requires.txt',
            'top_level.txt',
        })
        freeze_script = (ROOT / 'scripts' / 'freeze_release_candidate.py').read_text(encoding='utf-8')
        gitignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
        assert 'openmiura.egg-info' in freeze_script
        assert '*.egg-info/' in gitignore

    voice_dir = ROOT / 'data' / 'voice_assets'
    assert voice_dir.exists()
    assert sorted(p.name for p in voice_dir.iterdir()) == ['.gitkeep']
    assert not (ROOT / 'reports' / 'manual_qg').exists()
    assert not (ROOT / 'reports' / 'quality_gate_sprint4').exists()
    assert not (ROOT / 'reports' / 'sprint4_gate_run').exists()