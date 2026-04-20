from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _parse_env_keys(path: Path) -> list[str]:
    keys: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key = line.split('=', 1)[0].strip()
        keys.append(key)
    return keys


def test_env_example_has_unique_keys_and_core_variables() -> None:
    path = ROOT / '.env.example'
    keys = _parse_env_keys(path)
    assert keys
    assert len(keys) == len(set(keys))
    assert 'OPENMIURA_CONFIG' in keys
    assert 'OPENMIURA_UI_ADMIN_USERNAME' in keys
    assert 'OPENMIURA_UI_ADMIN_PASSWORD' in keys
    assert 'OPENMIURA_DISCORD_APPLICATION_ID' in keys
    assert 'OPENMIURA_CONTROL_SELF_RESTART_COMMAND' in keys


def test_profile_templates_exist_and_stay_consistent() -> None:
    profiles_dir = ROOT / 'ops' / 'env'
    expected = {
        'insecure-dev.env',
        'secure-default.env',
        'local-dev.env',
        'local-secure.env',
        'demo.env',
        'production-like.env',
    }
    actual = {path.name for path in profiles_dir.glob('*.env')}
    assert actual == expected

    for name in expected:
        path = profiles_dir / name
        keys = _parse_env_keys(path)
        assert len(keys) == len(set(keys)), name
        data = path.read_text(encoding='utf-8')
        assert 'OPENMIURA_CONFIG=configs/openmiura.yaml' in data
        assert 'OPENMIURA_LLM_PROVIDER=ollama' in data
        assert 'OPENMIURA_UI_ADMIN_USERNAME=admin' in data

    production_like = (profiles_dir / 'production-like.env').read_text(encoding='utf-8')
    assert 'OPENMIURA_AUTH_COOKIE_SECURE=true' in production_like
    assert 'OPENMIURA_AUTH_CSRF_ENABLED=true' in production_like


def test_configuration_profile_docs_reference_precedence_and_profiles() -> None:
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    installation = (ROOT / 'docs' / 'installation.md').read_text(encoding='utf-8')
    production = (ROOT / 'docs' / 'production.md').read_text(encoding='utf-8')
    profile_doc = (ROOT / 'docs' / 'configuration_profiles.md').read_text(encoding='utf-8')

    assert 'ops/env/secure-default.env' in readme
    assert 'docs/configuration_profiles.md' in readme
    assert 'cp ops/env/secure-default.env .env' in installation
    assert 'cp ops/env/production-like.env .env' in production
    assert 'env:NOMBRE_VARIABLE|valor_por_defecto' in profile_doc
    assert 'OPENMIURA_CONFIG' in profile_doc
    assert 'secure-by-default' in profile_doc
    assert 'ops/env/insecure-dev.env' in profile_doc
    assert 'ops/env/secure-default.env' in profile_doc
