from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding='utf-8'))


def test_quality_gate_lists_exist_and_cover_key_suites() -> None:
    required = (ROOT / 'ops' / 'quality_gate' / 'release_required.txt').read_text(encoding='utf-8')
    extended = (ROOT / 'ops' / 'quality_gate' / 'release_extended.txt').read_text(encoding='utf-8')

    assert 'tests/test_cli_doctor.py' in required
    assert 'tests/test_phase9_config_center_ui.py' in required
    assert 'tests/test_openclaw_portfolio_native_providers_reconciliation_v2.py' in required
    assert 'tests/test_openclaw_portfolio_baseline_attestations_canvas_v2.py' in extended


def test_build_and_verify_release_scripts_support_documented_arguments() -> None:
    build_mod = _load_module('scripts/build_release_artifacts.py', 'build_release_artifacts_mod')
    verify_mod = _load_module('scripts/verify_release_artifacts.py', 'verify_release_artifacts_mod')

    build_args = build_mod.parse_args(['--dist-dir', 'custom-dist', '--tag', 'v1.2.3', '--target', 'desktop', '--strict'])
    verify_args = verify_mod.parse_args(['--dist-dir', 'custom-dist'])

    assert build_args.dist_dir == 'custom-dist'
    assert build_args.tag == 'v1.2.3'
    assert build_args.target == 'desktop'
    assert build_args.strict is True
    assert verify_args.dist_dir == 'custom-dist'


def test_quality_gate_script_and_doc_exist() -> None:
    script = _load_module('scripts/run_release_quality_gate.py', 'run_release_quality_gate_mod')
    args = script.parse_args(['--include-extended', '--skip-build', '--output-dir', 'reports/quality_gate'])
    doc = (ROOT / 'docs' / 'release_quality_gate.md').read_text(encoding='utf-8')

    assert args.include_extended is True
    assert args.skip_build is True
    assert 'python scripts/run_release_quality_gate.py --include-extended --output-dir reports/quality_gate' in doc
    assert 'release_required.txt' in doc


def test_ci_and_release_workflows_use_dev_extras_for_quality_gate_and_builds() -> None:
    ci = _load_yaml('.github/workflows/ci.yml')
    release = _load_yaml('.github/workflows/release.yml')
    package = _load_yaml('.github/workflows/package-reproducible.yml')

    ci_qg_steps = ci['jobs']['quality-gate']['steps']
    ci_setup = next(step for step in ci_qg_steps if step.get('name') == 'Set up Python and install local package')
    ci_gate = next(step for step in ci_qg_steps if step.get('name') == 'Run release quality gate')

    release_steps = release['jobs']['build-release']['steps']
    release_setup = next(step for step in release_steps if step.get('name') == 'Set up Python and install local package')
    release_gate = next(step for step in release_steps if step.get('name') == 'Run release quality gate')

    package_steps = package['jobs']['reproducible-package']['steps']
    package_setup = next(step for step in package_steps if step.get('name') == 'Set up Python and install local package')

    assert ci_setup['with']['extras'] == 'dev'
    assert release_setup['with']['extras'] == 'dev'
    assert package_setup['with']['extras'] == 'dev'
    assert 'python scripts/run_release_quality_gate.py --include-extended --output-dir reports/quality_gate' in ci_gate['run']
    assert 'python scripts/run_release_quality_gate.py --include-extended --output-dir reports/quality_gate' in release_gate['run']
