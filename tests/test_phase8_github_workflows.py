from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding='utf-8'))

def test_setup_openmiura_action_exists() -> None:
    path = Path(".github/actions/setup-openmiura/action.yml")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "python -m pip install -e ." in text

def test_package_reproducible_uses_local_setup_action() -> None:
    path = Path(".github/workflows/package-reproducible.yml")
    text = path.read_text(encoding="utf-8")
    assert "uses: ./.github/actions/setup-openmiura" in text
    
def _job_steps(doc: dict, job_name: str) -> list[dict]:
    return list(doc['jobs'][job_name]['steps'])


def test_setup_openmiura_composite_installs_local_package() -> None:
    action = (ROOT / '.github/actions/setup-openmiura/action.yml').read_text(encoding='utf-8')
    assert 'python -m pip install -e ".[${EXTRAS}]"' in action
    assert "importlib.import_module('openmiura')" in action


def test_package_reproducible_workflow_uses_local_setup_action_before_script() -> None:
    workflow = _load_yaml('.github/workflows/package-reproducible.yml')
    steps = _job_steps(workflow, 'reproducible-package')
    setup_step = next(step for step in steps if step.get('name') == 'Set up Python and install local package')
    assert setup_step['uses'] == './.github/actions/setup-openmiura'
    build_step = next(step for step in steps if step.get('name') == 'Build deterministic package')
    assert 'python scripts/reproducible_package.py' in build_step['run']


def test_ci_and_release_reuse_same_local_setup_contract() -> None:
    ci = _load_yaml('.github/workflows/ci.yml')
    validate_steps = _job_steps(ci, 'validate')
    reproducible_steps = _job_steps(ci, 'reproducible-package')
    release = _load_yaml('.github/workflows/release.yml')
    release_steps = _job_steps(release, 'build-release')

    for steps in (validate_steps, reproducible_steps, release_steps):
        setup_step = next(step for step in steps if step.get('name') == 'Set up Python and install local package')
        assert setup_step['uses'] == './.github/actions/setup-openmiura'

    release_upload = next(step for step in release_steps if step.get('name') == 'Upload release artifacts')
    assert str(release_upload['uses']).startswith('actions/upload-artifact@')
