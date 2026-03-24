from openmiura.core.audit import AuditStore
from openmiura.core.config import LLMSettings, RuntimeSettings, ServerSettings, Settings, StorageSettings
from openmiura.core.router import AgentRouter


def _settings(tmp_path):
    return Settings(
        server=ServerSettings(),
        storage=StorageSettings(db_path=str(tmp_path / 'audit.db')),
        llm=LLMSettings(),
        runtime=RuntimeSettings(),
        agents={
            'default': {'name': 'default', 'system_prompt': 'base'},
            'researcher': {'name': 'researcher', 'keywords': ['paper', 'study'], 'priority': 10},
        },
    )


def test_router_by_command_keyword_and_default(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    router = AgentRouter(_settings(tmp_path), audit)
    assert router.route('http', 'u1', 'hola')['agent_id'] == 'default'
    assert router.route('http', 'u1', 'quiero un paper')['agent_id'] == 'researcher'
    assert router.route('http', 'u1', '/agent researcher')['agent_id'] == 'researcher'
