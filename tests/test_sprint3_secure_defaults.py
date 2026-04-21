from __future__ import annotations

from pathlib import Path

import openmiura.cli as cli
from openmiura.core.config import load_settings


ROOT = Path(__file__).resolve().parents[1]


def test_default_config_is_secure_by_default(monkeypatch) -> None:
    monkeypatch.delenv('OPENMIURA_TERMINAL_ENABLED', raising=False)
    monkeypatch.delenv('OPENMIURA_TERMINAL_ALLOW_SHELL', raising=False)
    monkeypatch.delenv('OPENMIURA_TERMINAL_ALLOW_METACHARACTERS', raising=False)
    monkeypatch.delenv('OPENMIURA_TERMINAL_REQUIRE_EXPLICIT_ALLOWLIST', raising=False)
    monkeypatch.delenv('OPENMIURA_WEB_FETCH_ALLOW_ALL_DOMAINS', raising=False)
    settings = load_settings(str(ROOT / 'configs' / 'openmiura.yaml'))
    assert settings.tools.web_fetch.allow_all_domains is False
    assert settings.tools.terminal.enabled is False
    assert settings.tools.terminal.allow_shell is False
    assert settings.tools.terminal.allow_shell_metacharacters is False
    assert settings.tools.terminal.require_explicit_allowlist is True


def test_env_overrides_can_opt_into_relaxed_dev_posture(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    cfg.write_text(
        """server: {}
storage: {}
llm: {}
runtime: {}
agents:
  default:
    system_prompt: hola
tools:
  web_fetch: {}
  terminal: {}
""",
        encoding='utf-8',
    )
    monkeypatch.setenv('OPENMIURA_WEB_FETCH_ALLOW_ALL_DOMAINS', 'true')
    monkeypatch.setenv('OPENMIURA_WEB_FETCH_ALLOWED_DOMAINS', 'example.org,api.openai.com')
    monkeypatch.setenv('OPENMIURA_TERMINAL_ENABLED', 'true')
    monkeypatch.setenv('OPENMIURA_TERMINAL_ALLOW_SHELL', 'true')
    monkeypatch.setenv('OPENMIURA_TERMINAL_ALLOW_METACHARACTERS', 'true')
    monkeypatch.setenv('OPENMIURA_TERMINAL_REQUIRE_EXPLICIT_ALLOWLIST', 'false')
    monkeypatch.setenv('OPENMIURA_TERMINAL_ALLOWED_COMMANDS', 'python,echo')
    settings = load_settings(str(cfg))
    assert settings.tools.web_fetch.allow_all_domains is True
    assert settings.tools.web_fetch.allowed_domains == ['example.org', 'api.openai.com']
    assert settings.tools.terminal.enabled is True
    assert settings.tools.terminal.allow_shell is True
    assert settings.tools.terminal.allow_shell_metacharacters is True
    assert settings.tools.terminal.require_explicit_allowlist is False
    assert settings.tools.terminal.allowed_commands == ['python', 'echo']


def test_doctor_warns_on_permissive_tool_posture_and_placeholders(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    cfg.write_text(
        """server:
  host: 127.0.0.1
  port: 8081
storage:
  db_path: ':memory:'
llm:
  provider: openai
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  api_key_env_var: OPENAI_API_KEY
runtime: {}
agents:
  default:
    system_prompt: hola
tools:
  sandbox_dir: data/sandbox
  web_fetch:
    allow_all_domains: true
  terminal:
    enabled: true
    allow_shell: true
    allow_shell_metacharacters: true
    require_explicit_allowlist: false
admin:
  enabled: true
  token: change-me
auth:
  enabled: true
  ui_admin_password: change-me
broker:
  enabled: true
  token: change-me
memory:
  enabled: false
mcp:
  enabled: false
""",
        encoding='utf-8',
    )
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data' / 'sandbox').mkdir(parents=True, exist_ok=True)
    payload, exit_code = cli._doctor_payload(str(cfg))
    assert exit_code == 0
    names = {row['name']: row for row in payload['checks']}
    assert names['web_fetch_posture']['level'] == 'warning'
    assert names['terminal_posture']['level'] == 'warning'
    assert names['placeholder_credentials']['level'] == 'warning'


def test_profile_templates_capture_secure_and_insecure_modes() -> None:
    insecure = (ROOT / 'ops' / 'env' / 'insecure-dev.env').read_text(encoding='utf-8')
    secure = (ROOT / 'ops' / 'env' / 'secure-default.env').read_text(encoding='utf-8')
    assert 'OPENMIURA_WEB_FETCH_ALLOW_ALL_DOMAINS=true' in insecure
    assert 'OPENMIURA_TERMINAL_ENABLED=true' in insecure
    assert 'OPENMIURA_TERMINAL_ALLOW_SHELL=true' in insecure
    assert 'OPENMIURA_WEB_FETCH_ALLOW_ALL_DOMAINS=false' in secure
    assert 'OPENMIURA_TERMINAL_ENABLED=false' in secure
    assert 'OPENMIURA_TERMINAL_REQUIRE_EXPLICIT_ALLOWLIST=true' in secure
