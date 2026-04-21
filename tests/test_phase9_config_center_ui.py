from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway

TEST_ADMIN_USERNAME = 'ui-test-user'
TEST_ADMIN_PASSWORD = 'test-pass-not-secret'

def _write_config(path: Path, policies_path: Path, agents_path: Path, evaluations_path: Path) -> None:
    db_path = (path.parent / 'audit.db').as_posix()
    backup_dir = (path.parent / 'backups').as_posix()
    sandbox_dir = (path.parent / 'sandbox').as_posix()
    content = f"""\
server:
  host: \"127.0.0.1\"
  port: 8081
storage:
  db_path: \"{db_path}\"
  backup_dir: \"{backup_dir}\"
llm:
  provider: \"ollama\"
  base_url: \"http://127.0.0.1:11434\"
  model: \"qwen2.5:7b-instruct\"
runtime:
  history_limit: 6
memory:
  enabled: false
tools:
  sandbox_dir: \"{sandbox_dir}\"
broker:
  enabled: true
  base_path: \"/broker\"
auth:
  enabled: true
  session_ttl_s: 3600
agents_path: \"{agents_path.as_posix()}\"
policies_path: \"{policies_path.as_posix()}\"
evaluations:
  suites_path: \"{evaluations_path.as_posix()}\"
"""
    path.write_text(content, encoding='utf-8')


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        '/broker/auth/login',
        json={'username': TEST_ADMIN_USERNAME, 'password': TEST_ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {'Authorization': f"Bearer {response.json()['token']}"}


def test_config_center_ui_and_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', TEST_ADMIN_USERNAME)
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', TEST_ADMIN_PASSWORD)
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text('defaults:\n  tools: true\n', encoding='utf-8')
    agents_path = tmp_path / 'agents.yaml'
    agents_path.write_text('default:\n  system_prompt: "base"\n  tools: ["time_now"]\n', encoding='utf-8')
    evaluations_path = tmp_path / 'evaluations.yaml'
    evaluations_path.write_text('defaults: {}\nsuites: {}\n', encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path, agents_path, evaluations_path)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = _login(client)
        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Configuration Center' in ui.text
        assert 'configSectionSelect' in ui.text
        assert 'Main settings form' in ui.text
        assert 'applyConfigFormBtn' in ui.text
        assert 'Channel setup wizard' in ui.text
        assert 'channelWizardChannelSelect' in ui.text
        assert 'saveChannelWizardBtn' in ui.text
        assert 'Secrets &amp; env references' in ui.text
        assert 'secretEnvProfileSelect' in ui.text
        assert 'applySuggestedSecretEnvRefsBtn' in ui.text

        snapshot = client.get('/broker/admin/config-center', headers=headers)
        assert snapshot.status_code == 200, snapshot.text
        payload = snapshot.json()
        names = {item['name'] for item in payload['sections']}
        assert {'openmiura', 'agents', 'policies', 'evaluations'} <= names
        assert payload['files']['openmiura']['summary']['llm']['provider'] == 'ollama'
        assert payload['files']['policies']['path'] == policies_path.as_posix()
        assert payload['channel_wizard']['channels'][0]['name'] == 'telegram'


def test_config_center_validate_and_save_with_reload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', TEST_ADMIN_USERNAME)
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', TEST_ADMIN_PASSWORD)
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text('defaults:\n  tools: true\n', encoding='utf-8')
    agents_path = tmp_path / 'agents.yaml'
    agents_path.write_text('default:\n  system_prompt: "base"\n  tools: ["time_now"]\n', encoding='utf-8')
    evaluations_path = tmp_path / 'evaluations.yaml'
    evaluations_path.write_text('defaults: {}\nsuites: {}\n', encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path, agents_path, evaluations_path)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = _login(client)
        validated = client.post(
            '/broker/admin/config-center/validate',
            headers=headers,
            json={
                'section': 'policies',
                'content': 'defaults:\n  tools: true\ntool_rules:\n  - name: allow_time_now\n    tool: time_now\n    effect: allow\n',
            },
        )
        assert validated.status_code == 200, validated.text
        assert validated.json()['summary']['tool_rules'] == 1

        saved = client.post(
            '/broker/admin/config-center/save',
            headers=headers,
            json={
                'section': 'policies',
                'content': 'defaults:\n  tools: true\ntool_rules:\n  - name: allow_time_now\n    tool: time_now\n    effect: allow\n',
                'reload_after_save': True,
            },
        )
        assert saved.status_code == 200, saved.text
        saved_payload = saved.json()
        assert saved_payload['reload_applied'] is True
        assert saved_payload['restart_required'] is False
        assert saved_payload['backup_path']
        assert 'allow_time_now' in policies_path.read_text(encoding='utf-8')

        main_cfg = client.post(
            '/broker/admin/config-center/save',
            headers=headers,
            json={
                'section': 'openmiura',
                'content': cfg.read_text(encoding='utf-8').replace('qwen2.5:7b-instruct', 'llama3.2'),
                'reload_after_save': True,
            },
        )
        assert main_cfg.status_code == 200, main_cfg.text
        assert main_cfg.json()['restart_required'] is True
        assert main_cfg.json()['reload_applied'] is False


def test_config_center_openmiura_form_validate_and_save(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', TEST_ADMIN_USERNAME)
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', TEST_ADMIN_PASSWORD)
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text('defaults:\n  tools: true\n', encoding='utf-8')
    agents_path = tmp_path / 'agents.yaml'
    agents_path.write_text('default:\n  system_prompt: "base"\n  tools: ["time_now"]\n', encoding='utf-8')
    evaluations_path = tmp_path / 'evaluations.yaml'
    evaluations_path.write_text('defaults: {}\nsuites: {}\n', encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path, agents_path, evaluations_path)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = _login(client)
        snapshot = client.get('/broker/admin/config-center', headers=headers)
        assert snapshot.status_code == 200, snapshot.text
        openmiura_file = snapshot.json()['files']['openmiura']
        assert openmiura_file['form_values']['llm.provider'] == 'ollama'
        assert openmiura_file['form_values']['broker.enabled'] is True
        assert openmiura_file['form_schema']

        form_payload = {
            'server.host': '0.0.0.0',
            'server.port': 8099,
            'llm.provider': 'local_openai_compat',
            'llm.base_url': 'http://127.0.0.1:1234/v1',
            'llm.model': 'llama3.2:latest',
            'runtime.history_limit': 15,
            'memory.enabled': True,
            'memory.embed_model': 'bge-m3',
            'broker.enabled': False,
            'auth.enabled': True,
            'auth.session_ttl_s': 7200,
            'tenancy.enabled': True,
            'tenancy.default_environment': 'staging',
        }
        validated = client.post(
            '/broker/admin/config-center/validate',
            headers=headers,
            json={
                'section': 'openmiura',
                'form_payload': form_payload,
            },
        )
        assert validated.status_code == 200, validated.text
        validated_payload = validated.json()
        assert validated_payload['summary']['llm']['provider'] == 'local_openai_compat'
        assert validated_payload['form_values']['server.port'] == 8099
        assert 'llama3.2:latest' in validated_payload['normalized_yaml']
        assert agents_path.as_posix() in validated_payload['normalized_yaml']

        saved = client.post(
            '/broker/admin/config-center/save',
            headers=headers,
            json={
                'section': 'openmiura',
                'form_payload': form_payload,
                'reload_after_save': False,
            },
        )
        assert saved.status_code == 200, saved.text
        saved_payload = saved.json()
        assert saved_payload['restart_required'] is True
        new_raw = cfg.read_text(encoding='utf-8')
        assert 'local_openai_compat' in new_raw
        assert '0.0.0.0' in new_raw
        assert 'staging' in new_raw


def test_config_center_channel_wizard_snapshot_and_validate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', TEST_ADMIN_USERNAME)
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', TEST_ADMIN_PASSWORD)
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text('defaults:\n  tools: true\n', encoding='utf-8')
    agents_path = tmp_path / 'agents.yaml'
    agents_path.write_text('default:\n  system_prompt: "base"\n  tools: ["time_now"]\n', encoding='utf-8')
    evaluations_path = tmp_path / 'evaluations.yaml'
    evaluations_path.write_text('defaults: {}\nsuites: {}\n', encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path, agents_path, evaluations_path)
    cfg.write_text(
        cfg.read_text(encoding='utf-8')
        + 'telegram:\n'
        + '  bot_token: "env:OPENMIURA_TELEGRAM_BOT_TOKEN"\n'
        + '  mode: "polling"\n',
        encoding='utf-8',
    )
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = _login(client)
        snapshot = client.get('/broker/admin/config-center/channels-wizard', headers=headers)
        assert snapshot.status_code == 200, snapshot.text
        payload = snapshot.json()
        assert {item['name'] for item in payload['channels']} == {'telegram', 'slack', 'discord'}
        assert payload['values']['telegram']['telegram.bot_token.mode'] == 'env'
        assert payload['values']['telegram']['telegram.bot_token.value'] == 'OPENMIURA_TELEGRAM_BOT_TOKEN'
        assert payload['channels'][0]['status']['configured'] is True

        validated = client.post(
            '/broker/admin/config-center/channels-wizard/validate',
            headers=headers,
            json={
                'channel': 'telegram',
                'content': cfg.read_text(encoding='utf-8'),
                'wizard_payload': {
                    'telegram.bot_token.mode': 'env',
                    'telegram.bot_token.value': 'OPENMIURA_TELEGRAM_BOT_TOKEN',
                    'telegram.mode': 'webhook',
                    'telegram.webhook_secret.mode': 'literal',
                    'telegram.webhook_secret.value': 'hook-secret',
                    'telegram.allowlist.enabled': True,
                    'telegram.allowlist.allow_user_ids': '11, 22',
                    'telegram.allowlist.allow_chat_ids': '-1001,-1002',
                    'telegram.allowlist.allow_groups': True,
                    'telegram.allowlist.deny_message': 'denied',
                },
            },
        )
        assert validated.status_code == 200, validated.text
        validated_payload = validated.json()
        assert validated_payload['channel'] == 'telegram'
        assert validated_payload['wizard_values']['telegram.mode'] == 'webhook'
        assert validated_payload['channel_status']['configured'] is True
        assert 'env:OPENMIURA_TELEGRAM_BOT_TOKEN' in validated_payload['normalized_yaml']
        assert 'webhook_secret: hook-secret' in validated_payload['normalized_yaml']
        assert 'allow_user_ids:' in validated_payload['normalized_yaml']


def test_config_center_channel_wizard_save_slack_and_discord(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', TEST_ADMIN_USERNAME)
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', TEST_ADMIN_PASSWORD)
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text('defaults:\n  tools: true\n', encoding='utf-8')
    agents_path = tmp_path / 'agents.yaml'
    agents_path.write_text('default:\n  system_prompt: "base"\n  tools: ["time_now"]\n', encoding='utf-8')
    evaluations_path = tmp_path / 'evaluations.yaml'
    evaluations_path.write_text('defaults: {}\nsuites: {}\n', encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path, agents_path, evaluations_path)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = _login(client)
        saved_slack = client.post(
            '/broker/admin/config-center/channels-wizard/save',
            headers=headers,
            json={
                'channel': 'slack',
                'content': cfg.read_text(encoding='utf-8'),
                'wizard_payload': {
                    'slack.bot_token.mode': 'env',
                    'slack.bot_token.value': 'OPENMIURA_SLACK_BOT_TOKEN',
                    'slack.signing_secret.mode': 'env',
                    'slack.signing_secret.value': 'OPENMIURA_SLACK_SIGNING_SECRET',
                    'slack.bot_user_id': 'U123',
                    'slack.reply_in_thread': False,
                    'slack.allowlist.enabled': True,
                    'slack.allowlist.allow_team_ids': 'T1,T2',
                    'slack.allowlist.allow_channel_ids': 'C1,C2',
                    'slack.allowlist.allow_im': False,
                    'slack.allowlist.deny_message': 'nope',
                },
            },
        )
        assert saved_slack.status_code == 200, saved_slack.text
        slack_payload = saved_slack.json()
        assert slack_payload['channel'] == 'slack'
        assert slack_payload['restart_required'] is True
        new_raw = cfg.read_text(encoding='utf-8')
        assert 'env:OPENMIURA_SLACK_BOT_TOKEN' in new_raw
        assert 'reply_in_thread: false' in new_raw.lower()
        assert 'allow_team_ids:' in new_raw

        saved_discord = client.post(
            '/broker/admin/config-center/channels-wizard/save',
            headers=headers,
            json={
                'channel': 'discord',
                'content': cfg.read_text(encoding='utf-8'),
                'wizard_payload': {
                    'discord.bot_token.mode': 'literal',
                    'discord.bot_token.value': 'discord-secret',
                    'discord.application_id': '999',
                    'discord.mention_only': False,
                    'discord.reply_as_reply': True,
                    'discord.slash_enabled': True,
                    'discord.slash_command_name': 'openmiura',
                    'discord.sync_on_startup': True,
                    'discord.sync_guild_ids': '101,202',
                    'discord.expose_native_commands': False,
                    'discord.include_attachments_in_text': False,
                    'discord.max_attachment_items': 7,
                    'discord.allowlist.enabled': True,
                    'discord.allowlist.allow_user_ids': '1,2',
                    'discord.allowlist.allow_channel_ids': '3,4',
                    'discord.allowlist.allow_guild_ids': '5,6',
                    'discord.allowlist.allow_dm': False,
                    'discord.allowlist.deny_message': 'blocked',
                },
            },
        )
        assert saved_discord.status_code == 200, saved_discord.text
        discord_payload = saved_discord.json()
        assert discord_payload['channel'] == 'discord'
        assert discord_payload['channel_status']['configured'] is True
        latest_raw = cfg.read_text(encoding='utf-8')
        assert 'bot_token: discord-secret' in latest_raw
        assert 'slash_command_name: openmiura' in latest_raw
        assert 'max_attachment_items: 7' in latest_raw
        assert 'allow_guild_ids:' in latest_raw


def test_config_center_secret_env_wizard_snapshot_and_validate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', TEST_ADMIN_USERNAME)
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', TEST_ADMIN_PASSWORD)
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text('defaults:\n  tools: true\n', encoding='utf-8')
    agents_path = tmp_path / 'agents.yaml'
    agents_path.write_text('default:\n  system_prompt: "base"\n  tools: ["time_now"]\n', encoding='utf-8')
    evaluations_path = tmp_path / 'evaluations.yaml'
    evaluations_path.write_text('defaults: {}\nsuites: {}\n', encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path, agents_path, evaluations_path)
    cfg.write_text(
        cfg.read_text(encoding='utf-8').replace(
            '  model: "qwen2.5:7b-instruct"\n',
            '  model: "qwen2.5:7b-instruct"\n  api_key_env_var: "OPENMIURA_LLM_API_KEY"\n',
        )
        + 'telegram:\n'
        + '  bot_token: "env:OPENMIURA_TELEGRAM_BOT_TOKEN"\n',
        encoding='utf-8',
    )
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = _login(client)
        snapshot = client.get('/broker/admin/config-center/secrets-wizard?env_prefix=ACME', headers=headers)
        assert snapshot.status_code == 200, snapshot.text
        payload = snapshot.json()
        assert {item['name'] for item in payload['profiles']} == {'llm', 'telegram', 'slack', 'discord'}
        assert payload['values']['telegram']['telegram.bot_token.mode'] == 'env'
        assert payload['values']['llm']['llm.api_key_env_var.value'] == 'OPENMIURA_LLM_API_KEY'
        assert payload['suggestions']['slack']['slack.bot_token'] == 'ACME_SLACK_BOT_TOKEN'

        validated = client.post(
            '/broker/admin/config-center/secrets-wizard/validate',
            headers=headers,
            json={
                'profile': 'slack',
                'content': cfg.read_text(encoding='utf-8'),
                'env_prefix': 'ACME',
                'wizard_payload': {
                    'slack.bot_token.mode': 'env',
                    'slack.bot_token.value': '',
                    'slack.signing_secret.mode': 'env',
                    'slack.signing_secret.value': '',
                },
            },
        )
        assert validated.status_code == 200, validated.text
        validated_payload = validated.json()
        assert validated_payload['profile'] == 'slack'
        assert validated_payload['wizard_values']['slack.bot_token.value'] == 'ACME_SLACK_BOT_TOKEN'
        assert validated_payload['wizard_values']['slack.signing_secret.value'] == 'ACME_SLACK_SIGNING_SECRET'
        assert 'env:ACME_SLACK_BOT_TOKEN' in validated_payload['normalized_yaml']
        assert 'ACME_SLACK_SIGNING_SECRET=' in validated_payload['env_example']
        assert validated_payload['profile_status']['configured'] is True


def test_config_center_secret_env_wizard_save_llm_and_discord(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', TEST_ADMIN_USERNAME)
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', TEST_ADMIN_PASSWORD)
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text('defaults:\n  tools: true\n', encoding='utf-8')
    agents_path = tmp_path / 'agents.yaml'
    agents_path.write_text('default:\n  system_prompt: "base"\n  tools: ["time_now"]\n', encoding='utf-8')
    evaluations_path = tmp_path / 'evaluations.yaml'
    evaluations_path.write_text('defaults: {}\nsuites: {}\n', encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path, agents_path, evaluations_path)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = _login(client)
        saved_llm = client.post(
            '/broker/admin/config-center/secrets-wizard/save',
            headers=headers,
            json={
                'profile': 'llm',
                'content': cfg.read_text(encoding='utf-8'),
                'env_prefix': 'OPENMIURA',
                'wizard_payload': {
                    'llm.api_key_env_var.mode': 'env',
                    'llm.api_key_env_var.value': '',
                },
            },
        )
        assert saved_llm.status_code == 200, saved_llm.text
        llm_payload = saved_llm.json()
        assert llm_payload['profile'] == 'llm'
        assert llm_payload['restart_required'] is True
        raw_after_llm = cfg.read_text(encoding='utf-8')
        assert 'api_key_env_var: OPENMIURA_LLM_API_KEY' in raw_after_llm

        saved_discord = client.post(
            '/broker/admin/config-center/secrets-wizard/save',
            headers=headers,
            json={
                'profile': 'discord',
                'content': cfg.read_text(encoding='utf-8'),
                'env_prefix': 'TEAMX',
                'wizard_payload': {
                    'discord.bot_token.mode': 'env',
                    'discord.bot_token.value': '',
                },
            },
        )
        assert saved_discord.status_code == 200, saved_discord.text
        discord_payload = saved_discord.json()
        assert discord_payload['profile'] == 'discord'
        assert 'TEAMX_DISCORD_BOT_TOKEN=' in discord_payload['env_example']
        latest_raw = cfg.read_text(encoding='utf-8')
        assert 'bot_token: env:TEAMX_DISCORD_BOT_TOKEN' in latest_raw




def test_config_center_reload_assistant_snapshot_and_apply(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', TEST_ADMIN_USERNAME)
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', TEST_ADMIN_PASSWORD)
    monkeypatch.setenv('OPENMIURA_CONTROL_ALLOW_SELF_RESTART', 'true')
    restart_log = tmp_path / 'restart-hook.log'
    command = f'"{sys.executable}" -c "from pathlib import Path; Path(r\'{restart_log.as_posix()}\').write_text(\'ok\', encoding=\'utf-8\')"'
    monkeypatch.setenv('OPENMIURA_CONTROL_SELF_RESTART_COMMAND', command)
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text("""defaults:
  tools: true
""", encoding='utf-8')
    agents_path = tmp_path / 'agents.yaml'
    agents_path.write_text("""default:
  system_prompt: "base"
  tools: ["time_now"]
""", encoding='utf-8')
    evaluations_path = tmp_path / 'evaluations.yaml'
    evaluations_path.write_text("""defaults: {}
suites: {}
""", encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path, agents_path, evaluations_path)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = _login(client)
        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Reload &amp; restart assistant' in ui.text
        assert 'applyReloadAssistantBtn' in ui.text
        assert 'refreshReloadAssistantBtn' in ui.text
        assert 'reloadAssistantRuntimeBadge' in ui.text
        assert 'Startup config signature' in ui.text
        assert 'Restart hook result' in ui.text
        assert 'Latest boot evidence' in ui.text

        snapshot = client.get('/broker/admin/config-center/reload-assistant', headers=headers)
        assert snapshot.status_code == 200, snapshot.text
        payload = snapshot.json()
        assert {item['name'] for item in payload['sections']} == {'openmiura', 'agents', 'policies', 'evaluations'}
        assert payload['capabilities']['live_reload_sections'] == ['agents', 'policies']
        assert payload['restart_hook']['configured'] is True
        assert payload['operational_state']['health']['status'] == 'healthy'
        assert payload['operational_state']['process']['pid'] > 0
        assert payload['operational_state']['startup_config']['main_config']['sha256']
        assert payload['operational_state']['current_boot']['boot_instance_id']
        assert payload['operational_state']['latest_boot_evidence']['current_process_matches'] is True

        applied = client.post(
            '/broker/admin/config-center/reload-assistant/apply',
            headers=headers,
            json={
                'sections': ['agents', 'policies', 'openmiura'],
                'apply_live_reload': True,
                'request_restart': False,
                'execute_restart_hook': True,
            },
        )
        assert applied.status_code == 200, applied.text
        applied_payload = applied.json()
        assert applied_payload['live_reload_applied'] is True
        assert applied_payload['restart_required'] is True
        assert applied_payload['restart_request']['status'] == 'executed'
        assert restart_log.read_text(encoding='utf-8') == 'ok'

        snapshot_after = client.get('/broker/admin/config-center/reload-assistant', headers=headers)
        assert snapshot_after.status_code == 200, snapshot_after.text
        snapshot_after_payload = snapshot_after.json()
        recent = snapshot_after_payload['recent_restart_requests']
        assert recent
        assert recent[0]['status'] == 'executed'
        assert snapshot_after_payload['operational_state']['restart_observation']['latest_request_status'] == 'executed'
        assert snapshot_after_payload['operational_state']['startup_config']['router']['agents_path']
        assert snapshot_after_payload['operational_state']['restart_hook_result']['executed'] is True
        assert snapshot_after_payload['operational_state']['restart_hook_result']['ok'] is True
        assert snapshot_after_payload['operational_state']['latest_boot_evidence']['boot_instance_id'] == snapshot_after_payload['operational_state']['current_boot']['boot_instance_id']


def test_config_center_reload_assistant_request_queue_without_hook(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', TEST_ADMIN_USERNAME)
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', TEST_ADMIN_PASSWORD)
    monkeypatch.delenv('OPENMIURA_CONTROL_ALLOW_SELF_RESTART', raising=False)
    monkeypatch.delenv('OPENMIURA_CONTROL_SELF_RESTART_COMMAND', raising=False)
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text("""defaults:
  tools: true
""", encoding='utf-8')
    agents_path = tmp_path / 'agents.yaml'
    agents_path.write_text("""default:
  system_prompt: "base"
  tools: ["time_now"]
""", encoding='utf-8')
    evaluations_path = tmp_path / 'evaluations.yaml'
    evaluations_path.write_text("""defaults: {}
suites: {}
""", encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path, agents_path, evaluations_path)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = _login(client)
        applied = client.post(
            '/broker/admin/config-center/reload-assistant/apply',
            headers=headers,
            json={
                'sections': ['openmiura'],
                'apply_live_reload': False,
                'request_restart': False,
                'execute_restart_hook': False,
            },
        )
        assert applied.status_code == 200, applied.text
        payload = applied.json()
        assert payload['restart_request']['status'] == 'queued'
        snapshot = client.get('/broker/admin/config-center/reload-assistant', headers=headers)
        assert snapshot.status_code == 200, snapshot.text
        snapshot_payload = snapshot.json()
        assert snapshot_payload['pending_restart_requests']
        assert snapshot_payload['operational_state']['restart_observation']['state'] in {'pending', 'awaiting_observation'}
        assert snapshot_payload['operational_state']['restart_hook_result']['available'] is False
        assert snapshot_payload['operational_state']['latest_boot_evidence']['current_process_matches'] is True



def test_config_center_snapshot_supports_list_based_agents_catalog(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', TEST_ADMIN_USERNAME)
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', TEST_ADMIN_PASSWORD)
    monkeypatch.setenv('OPENMIURA_BROKER_ENABLED', 'true')
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text('defaults:\n  tools: true\n', encoding='utf-8')
    agents_path = tmp_path / 'agents.yaml'
    agents_path.write_text(
        """agents:
  - name: default
    model: qwen2.5:7b-instruct
    tools: [time_now]
  - name: researcher
    model: qwen2.5:7b-instruct
    tools: [fs_read]
""",
        encoding='utf-8',
    )
    evaluations_path = tmp_path / 'evaluations.yaml'
    evaluations_path.write_text('defaults: {}\nsuites: {}\n', encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path, agents_path, evaluations_path)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = _login(client)
        snapshot = client.get('/broker/admin/config-center', headers=headers)
        assert snapshot.status_code == 200, snapshot.text
        agents_summary = snapshot.json()['files']['agents']['summary']
        assert agents_summary['agent_count'] == 2
        assert agents_summary['catalog_shape'] == 'list'
        assert agents_summary['agent_ids'] == ['default', 'researcher']



def test_config_center_evaluations_path_defaults_relative_to_config_dir(tmp_path: Path) -> None:
    from openmiura.application.admin.service import AdminService

    cfg_dir = tmp_path / 'configs'
    cfg_dir.mkdir()
    cfg = cfg_dir / 'openmiura.yaml'
    cfg.write_text('server:\n  host: "127.0.0.1"\n', encoding='utf-8')

    service = AdminService()
    resolved = service._resolve_config_related_path(cfg, 'evaluations.yaml')
    assert resolved == (cfg_dir / 'evaluations.yaml').resolve()


def test_evaluation_service_supports_legacy_configs_prefixed_path(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from openmiura.application.evaluations import EvaluationService

    cfg_dir = tmp_path / 'configs'
    cfg_dir.mkdir()
    cfg = cfg_dir / 'openmiura.yaml'
    cfg.write_text('server:\n  host: "127.0.0.1"\n', encoding='utf-8')
    evaluations_path = cfg_dir / 'evaluations.yaml'
    evaluations_path.write_text('defaults: {}\nsuites: {}\n', encoding='utf-8')

    gw = SimpleNamespace(
        config_path=str(cfg),
        settings=SimpleNamespace(
            evaluations=SimpleNamespace(suites_path='configs/evaluations.yaml')
        ),
    )
    service = EvaluationService()

    assert service._suites_path(gw) == evaluations_path.resolve()
    payload = service.list_suites(gw)
    assert payload['ok'] is True
    assert payload['path'] == evaluations_path.resolve().as_posix()


def test_runtime_defaults_resolve_agents_and_policies_relative_to_config_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv('OPENMIURA_CONFIG', raising=False)

    cfg_dir = tmp_path / 'configs'
    cfg_dir.mkdir()
    (cfg_dir / 'agents.yaml').write_text(
        '''agents:
  - name: default
    system_prompt: "base"
    tools: ["time_now"]
''',
        encoding='utf-8',
    )
    (cfg_dir / 'policies.yaml').write_text(
        '''defaults:
  tools: true
''',
        encoding='utf-8',
    )
    cfg = cfg_dir / 'openmiura.yaml'
    cfg.write_text(
        f'''server:
  host: "127.0.0.1"
storage:
  db_path: "{(tmp_path / 'audit.db').as_posix()}"
  backup_dir: "{(tmp_path / 'backups').as_posix()}"
memory:
  enabled: false
broker:
  enabled: true
''',
        encoding='utf-8',
    )

    gw = Gateway.from_config(str(cfg))

    assert gw.router.agents_path == (cfg_dir / 'agents.yaml').resolve().as_posix()
    assert gw.policy is not None
    assert gw.policy.policies_path == (cfg_dir / 'policies.yaml').resolve().as_posix()
    assert 'default' in gw.router.available_agents()
    assert gw.policy.snapshot()['defaults']['tools'] is True


def test_runtime_supports_legacy_configs_prefixed_agents_and_policies_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv('OPENMIURA_CONFIG', raising=False)

    cfg_dir = tmp_path / 'configs'
    cfg_dir.mkdir()
    (cfg_dir / 'agents.yaml').write_text(
        '''agents:
  - name: default
    system_prompt: "base"
    tools: ["time_now"]
''',
        encoding='utf-8',
    )
    (cfg_dir / 'policies.yaml').write_text(
        '''defaults:
  tools: true
''',
        encoding='utf-8',
    )
    cfg = cfg_dir / 'openmiura.yaml'
    cfg.write_text(
        f'''server:
  host: "127.0.0.1"
storage:
  db_path: "{(tmp_path / 'audit.db').as_posix()}"
  backup_dir: "{(tmp_path / 'backups').as_posix()}"
memory:
  enabled: false
broker:
  enabled: true
agents_path: "configs/agents.yaml"
policies_path: "configs/policies.yaml"
''',
        encoding='utf-8',
    )

    gw = Gateway.from_config(str(cfg))

    assert gw.router.agents_path == (cfg_dir / 'agents.yaml').resolve().as_posix()
    assert gw.policy is not None
    assert gw.policy.policies_path == (cfg_dir / 'policies.yaml').resolve().as_posix()
    assert 'default' in gw.router.available_agents()
    assert gw.policy.snapshot()['defaults']['tools'] is True



def test_runtime_defaults_resolve_skills_relative_to_config_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv('OPENMIURA_CONFIG', raising=False)

    cfg_dir = tmp_path / 'configs'
    cfg_dir.mkdir()
    skills_dir = tmp_path / 'skills'
    skills_dir.mkdir()
    cfg = cfg_dir / 'openmiura.yaml'
    cfg.write_text(
        f'''server:
  host: "127.0.0.1"
storage:
  db_path: "{(tmp_path / 'audit.db').as_posix()}"
  backup_dir: "{(tmp_path / 'backups').as_posix()}"
memory:
  enabled: false
broker:
  enabled: true
''',
        encoding='utf-8',
    )

    gw = Gateway.from_config(str(cfg))

    assert gw.runtime.skills_path == skills_dir.resolve().as_posix()


def test_runtime_supports_legacy_skills_path_relative_to_project_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv('OPENMIURA_CONFIG', raising=False)

    cfg_dir = tmp_path / 'configs'
    cfg_dir.mkdir()
    skills_dir = tmp_path / 'skills'
    skills_dir.mkdir()
    cfg = cfg_dir / 'openmiura.yaml'
    cfg.write_text(
        f'''server:
  host: "127.0.0.1"
storage:
  db_path: "{(tmp_path / 'audit.db').as_posix()}"
  backup_dir: "{(tmp_path / 'backups').as_posix()}"
memory:
  enabled: false
broker:
  enabled: true
skills_path: "skills"
''',
        encoding='utf-8',
    )

    gw = Gateway.from_config(str(cfg))

    assert gw.runtime.skills_path == skills_dir.resolve().as_posix()
