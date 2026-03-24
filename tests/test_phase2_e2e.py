from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.schema import InboundMessage
from openmiura.gateway import Gateway
from openmiura.pipeline import process_message


def _write_config(tmp_path: Path, policies_text: str) -> Path:
    (tmp_path / 'agents.yaml').write_text(
        '''agents:
  - name: default
    system_prompt: general
    tools: []
    priority: 0
  - name: researcher
    system_prompt: research
    tools: [web_fetch, time_now]
    allowed_tools: [web_fetch, time_now]
    keywords: [paper, review]
    priority: 10
  - name: writer
    system_prompt: write
    tools: [fs_write]
    allowed_tools: [fs_write]
    keywords: [draft, redacta]
    priority: 5
''',
        encoding='utf-8',
    )
    (tmp_path / 'policies.yaml').write_text(policies_text, encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    cfg.write_text(
        f'''server:
  host: "127.0.0.1"
  port: 8081
storage:
  db_path: "{(tmp_path / 'audit.db').as_posix()}"
llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen"
  timeout_s: 30
runtime:
  history_limit: 6
agents: {{}}
memory:
  enabled: false
admin:
  enabled: true
  token: "secret"
agents_path: "{(tmp_path / 'agents.yaml').as_posix()}"
policies_path: "{(tmp_path / 'policies.yaml').as_posix()}"
''',
        encoding='utf-8',
    )
    return cfg


def test_multiagent_policy_e2e(tmp_path: Path):
    cfg = _write_config(
        tmp_path,
        '''user_rules:
  - user: "tg:blocked"
    deny_agents: [researcher]
agent_rules: []
tool_rules: []
''',
    )
    gw = Gateway.from_config(str(cfg))
    gw.runtime.generate_reply = lambda **kw: f"agent={kw['agent_id']}"

    out = process_message(
        gw,
        InboundMessage(channel='http', user_id='u1', text='please review this paper', metadata={}),
    )
    assert out.agent_id == 'researcher'
    assert out.text == 'agent=researcher\n\n💡 Puedes vincular tu cuenta con /link <tu_nombre>.'

    cmd = process_message(
        gw,
        InboundMessage(channel='http', user_id='u1', text='/agent writer', session_id=out.session_id, metadata={}),
    )
    assert 'Agente activo' in cmd.text

    out2 = process_message(
        gw,
        InboundMessage(channel='http', user_id='u1', text='hola', session_id=out.session_id, metadata={}),
    )
    assert out2.agent_id == 'writer'

    denied = process_message(
        gw,
        InboundMessage(channel='telegram', user_id='tg:blocked', text='review this paper', metadata={'chat_id': 1, 'from_id': 2}),
    )
    assert 'No tienes acceso al agente' in denied.text


def test_hot_reload_agents_and_policies(tmp_path: Path):
    cfg = _write_config(
        tmp_path,
        '''user_rules: []
agent_rules: []
tool_rules: []
''',
    )
    gw = Gateway.from_config(str(cfg))
    gw.runtime.generate_reply = lambda **kw: f"agent={kw['agent_id']}"

    out = process_message(gw, InboundMessage(channel='http', user_id='u1', text='draft this', metadata={}))
    assert out.agent_id == 'writer'

    (tmp_path / 'agents.yaml').write_text(
        '''agents:
  - name: default
    system_prompt: general
    tools: []
    priority: 0
  - name: researcher
    system_prompt: research
    tools: [web_fetch]
    allowed_tools: [web_fetch]
    keywords: [draft]
    priority: 10
''',
        encoding='utf-8',
    )
    (tmp_path / 'policies.yaml').write_text(
        '''user_rules:
  - user: "u1"
    deny_agents: [researcher]
agent_rules: []
tool_rules: []
''',
        encoding='utf-8',
    )

    result = gw.reload_dynamic_configs(force=True)
    assert result['agents']['changed'] is True
    assert result['policies']['changed'] is True
    assert 'researcher' in result['agents']['agents']

    denied = process_message(gw, InboundMessage(channel='http', user_id='u1', text='draft this again', metadata={}))
    assert 'No tienes acceso al agente' in denied.text


def test_admin_reload_endpoint(tmp_path: Path):
    cfg = _write_config(
        tmp_path,
        '''user_rules: []
agent_rules: []
tool_rules: []
''',
    )
    gw = Gateway.from_config(str(cfg))
    app = app_module.create_app(gateway_factory=lambda _config: gw)
    with TestClient(app) as client:
        response = client.post('/admin/reload', headers={'Authorization': 'Bearer secret'})
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True
        assert 'agents' in data and 'policies' in data
