from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway

TEST_ADMIN_USERNAME = 'ui-test-user'
TEST_ADMIN_PASSWORD = 'test-pass-not-secret'
TEST_ADMIN_TOKEN = 'test-admin-token-not-secret'

def _write_config(path: Path) -> None:
    db_path = (path.parent / "audit.db").as_posix()
    sandbox_dir = (path.parent / "sandbox").as_posix()
    path.write_text(
        f"""\
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
    tools: ["time_now"]
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
admin:
  enabled: true
  token: "{TEST_ADMIN_TOKEN}"
broker:
  enabled: true
  base_path: "/broker"
auth:
  enabled: true
  session_ttl_s: 3600
""",
        encoding="utf-8",
    )


def _login(client: TestClient) -> str:
    response = client.post(
        '/broker/auth/login',
        json={'username': TEST_ADMIN_USERNAME, 'password': TEST_ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_tiny_runtime_ui_assets_and_runtime_console_presence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', TEST_ADMIN_USERNAME)
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', TEST_ADMIN_PASSWORD)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        token = _login(client)
        headers = {
            'Authorization': f'Bearer {token}',
            'X-Tenant-Id': 'acme',
            'X-Workspace-Id': 'research',
            'X-Environment': 'dev',
        }
        created = client.post(
            '/broker/admin/openclaw/runtimes',
            headers=headers,
            json={
                'name': 'Tiny Local Runtime',
                'base_url': 'http://127.0.0.1:5051',
                'transport': 'simulated',
                'capabilities': ['chat', 'memory', 'skills'],
                'metadata': {
                    'kind': 'tiny_openclaw',
                    'runtime_class': 'simulated_lab',
                    'policy_pack': 'simulated_lab',
                    'skills': ['filesystem.read', 'browser.open', 'memory.write'],
                    'local_llm': {
                        'mode': 'local',
                        'provider': 'ollama',
                        'model': 'qwen2.5:7b-instruct',
                        'base_url': 'http://127.0.0.1:11434',
                        'api_style': 'openai-compatible',
                    },
                    'state_bridge': {
                        'enabled': True,
                        'storage': 'sqlite',
                    },
                },
            },
        )
        assert created.status_code == 200, created.text
        runtime_id = created.json()['runtime']['runtime_id']

        detail = client.get(f'/broker/admin/openclaw/runtimes/{runtime_id}', headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()['runtime_summary']['metadata']['kind'] == 'tiny_openclaw'

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Tiny Runtime' in ui.text
        assert 'Tiny Runtime Console' in ui.text

        app_js = client.get('/ui/app.js')
        assert app_js.status_code == 200
        assert 'refreshTinyRuntimeConsole' in app_js.text
