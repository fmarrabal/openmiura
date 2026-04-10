from __future__ import annotations

from pathlib import Path

from openmiura.core.schema import InboundMessage
from openmiura.gateway import Gateway
from openmiura.pipeline import process_message


def _write_config(tmp_path: Path) -> Path:
    (tmp_path / "agents.yaml").write_text(
        '''agents:
  - name: default
    system_prompt: general
    tools: []
    priority: 0
''',
        encoding="utf-8",
    )
    (tmp_path / "policies.yaml").write_text("user_rules: []\nagent_rules: []\ntool_rules: []\n", encoding="utf-8")
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        f'''server:\n  host: "127.0.0.1"\n  port: 8081\nstorage:\n  db_path: "{(tmp_path / "audit.db").as_posix()}"\nllm:\n  provider: "ollama"\n  base_url: "http://127.0.0.1:11434"\n  model: "qwen"\n  timeout_s: 30\nruntime:\n  history_limit: 6\n  pending_confirmation_ttl_s: 30\n  pending_confirmation_cleanup_interval_s: 1\nagents: {{}}\nmemory:\n  enabled: false\nadmin:\n  enabled: false\nagents_path: "{(tmp_path / "agents.yaml").as_posix()}"\npolicies_path: "{(tmp_path / "policies.yaml").as_posix()}"\n''',
        encoding="utf-8",
    )
    return cfg


def test_identity_validation_across_http_telegram_slack_and_discord(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    gw = Gateway.from_config(str(cfg))
    gw.runtime.generate_reply = lambda **kw: f"effective_user_key={kw['user_key']}"

    gw.identity.link("http:u1", "curro", linked_by="test")
    gw.identity.link("tg:1", "curro", linked_by="test")
    gw.identity.link("slack:T1:U1", "curro", linked_by="test")
    gw.identity.link("discord:42", "curro", linked_by="test")
    gw.audit.add_memory_item("curro", "fact", "shared memory", b"\\x00" * 8, "{}")

    http_out = process_message(gw, InboundMessage(channel="http", user_id="http:u1", text="hola", metadata={}))
    tg_out = process_message(gw, InboundMessage(channel="telegram", user_id="tg:1", text="hola", metadata={"chat_id": 10, "from_id": 1}))
    slack_out = process_message(gw, InboundMessage(channel="slack", user_id="slack:T1:U1", text="hola", metadata={"team_id": "T1", "channel_id": "C1"}))
    discord_out = process_message(gw, InboundMessage(channel="discord", user_id="discord:42", text="hola", metadata={"channel_id": 99, "author_id": 42}))

    assert http_out.text == "effective_user_key=curro"
    assert tg_out.text == "effective_user_key=curro"
    assert slack_out.text == "effective_user_key=curro"
    assert discord_out.text == "effective_user_key=curro"

    assert http_out.session_id == "http-curro"
    assert tg_out.session_id == "tg-10-curro"
    assert slack_out.session_id == "slack-curro"
    assert discord_out.session_id == "dc-curro"

    items = gw.audit.search_memory_items(user_key="curro", limit=10)
    assert items and items[0]["text"] == "shared memory"
