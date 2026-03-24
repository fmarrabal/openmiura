from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway


POLICIES_YAML = """defaults:
  tools: true
tool_rules:
  - name: deny_terminal_for_user
    tool: terminal_exec
    user_role: user
    effect: deny
    reason: terminal blocked for regular users
approval_rules:
  - name: require_fs_write_approval
    action_name: fs_write
    effect: require_approval
    reason: fs_write requires approval
"""


CANDIDATE_YAML = """defaults:
  tools: true
tool_rules:
  - name: allow_terminal_for_user
    tool: terminal_exec
    user_role: user
    effect: allow
    reason: terminal enabled for regular users
approval_rules:
  - name: require_fs_write_approval
    action_name: fs_write
    effect: require_approval
    reason: fs_write requires approval
"""


def _write_config(path: Path, policies_path: Path) -> None:
    db_path = (path.parent / 'audit.db').as_posix()
    sandbox_dir = (path.parent / 'sandbox').as_posix()
    path.write_text(
        f'''\
server:
  host: "127.0.0.1"
  port: 8081
storage:
  db_path: "{db_path}"
llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5:7b-instruct"
runtime:
  history_limit: 6
agents:
  default:
    system_prompt: "base"
    tools: ["time_now", "terminal_exec"]
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
broker:
  enabled: true
  base_path: "/broker"
auth:
  enabled: true
  session_ttl_s: 3600
policies_path: "{policies_path.as_posix()}"
''',
        encoding='utf-8',
    )


def test_phase7_policy_explorer_snapshot_simulate_diff_and_ui_surface(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text(POLICIES_YAML, encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path)

    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        login = client.post('/broker/auth/login', json={'username': 'admin', 'password': 'secret123'})
        assert login.status_code == 200, login.text
        headers = {'Authorization': f"Bearer {login.json()['token']}"}

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Policy Explorer' in ui.text
        assert 'policyExplorerCandidate' in ui.text

        snapshot = client.get('/broker/admin/policy-explorer/snapshot', headers=headers)
        assert snapshot.status_code == 200, snapshot.text
        snapshot_payload = snapshot.json()
        assert snapshot_payload['ok'] is True
        assert snapshot_payload['sections']['tool_rules']['count'] == 1
        assert 'tool' in snapshot_payload['supported_scopes']

        simulate = client.post(
            '/broker/admin/policy-explorer/simulate',
            headers=headers,
            json={
                'request': {
                    'scope': 'tool',
                    'resource_name': 'terminal_exec',
                    'action': 'use',
                    'agent_name': 'default',
                    'user_role': 'user',
                },
                'candidate_policy_yaml': CANDIDATE_YAML,
            },
        )
        assert simulate.status_code == 200, simulate.text
        simulate_payload = simulate.json()
        assert simulate_payload['baseline']['decision']['allowed'] is False
        assert simulate_payload['candidate']['decision']['allowed'] is True
        assert simulate_payload['changed'] is True
        assert 'allowed' in simulate_payload['change_summary']['fields']

        diff = client.post(
            '/broker/admin/policy-explorer/diff',
            headers=headers,
            json={
                'candidate_policy_yaml': CANDIDATE_YAML,
                'samples': [
                    {
                        'scope': 'tool',
                        'resource_name': 'terminal_exec',
                        'action': 'use',
                        'agent_name': 'default',
                        'user_role': 'user',
                    }
                ],
            },
        )
        assert diff.status_code == 200, diff.text
        diff_payload = diff.json()
        assert diff_payload['ok'] is True
        assert diff_payload['diff']['summary']['changed'] >= 1 or diff_payload['diff']['summary']['added'] >= 1
        assert diff_payload['sample_results'][0]['changed'] is True
        assert diff_payload['sample_results'][0]['candidate']['decision']['allowed'] is True
