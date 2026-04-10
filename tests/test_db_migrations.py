from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import openmiura.cli as cli
from openmiura.core.audit import AuditStore
from openmiura.core.config import load_settings
from openmiura.core.migrations import downgrade_migrations, schema_status


def _write_cfg(path: Path, db_path: Path, backup_dir: Path, backend: str = "sqlite") -> None:
    path.write_text(
        f"""server:
  host: 127.0.0.1
  port: 8081
storage:
  backend: {backend}
  db_path: {db_path.as_posix()}
  backup_dir: {backup_dir.as_posix()}
llm:
  provider: ollama
  base_url: http://127.0.0.1:11434
  model: qwen2.5:7b-instruct
runtime:
  history_limit: 2
memory:
  enabled: false
tools:
  sandbox_dir: {(path.parent / 'sandbox').as_posix()}
admin:
  enabled: false
mcp:
  enabled: false
""",
        encoding="utf-8",
    )


def test_storage_settings_parse_backend_and_backup_dir(tmp_path: Path) -> None:
    cfg = tmp_path / "openmiura.yaml"
    db_path = tmp_path / "audit.db"
    backup_dir = tmp_path / "backups"
    _write_cfg(cfg, db_path, backup_dir)

    settings = load_settings(str(cfg))
    assert settings.storage.backend == "sqlite"
    assert settings.storage.db_path == db_path.as_posix()
    assert settings.storage.backup_dir == backup_dir.as_posix()
    assert settings.storage.auto_migrate is True



def test_init_db_applies_schema_migrations(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.db"
    store = AuditStore(str(db_path))
    store.init_db()

    status = schema_status(store._conn)
    assert status["current_version"] >= 17
    assert len(status["applied"]) >= 17



def test_cli_db_backup_and_restore_roundtrip(tmp_path: Path) -> None:
    cfg = tmp_path / "openmiura.yaml"
    db_path = tmp_path / "audit.db"
    backup_dir = tmp_path / "backups"
    _write_cfg(cfg, db_path, backup_dir)

    store = AuditStore(str(db_path))
    store.init_db()
    session_id = store.get_or_create_session("http", "user-1", "sess-1")
    store.append_message(session_id, "user", "hola")

    runner = CliRunner()
    backup_result = runner.invoke(cli.app, ["db", "backup", "--config", str(cfg), "--json"])
    assert backup_result.exit_code == 0, backup_result.output
    payload = json.loads(backup_result.output)
    backup_path = Path(payload["backup_path"])
    assert backup_path.exists()

    store.clear_session_messages("sess-1")
    assert store.get_recent_messages("sess-1", 10) == []

    restore_result = runner.invoke(cli.app, ["db", "restore", "--config", str(cfg), "--backup", str(backup_path), "--json"])
    assert restore_result.exit_code == 0, restore_result.output

    restored = AuditStore(str(db_path))
    restored.init_db()
    messages = restored.get_recent_messages("sess-1", 10)
    assert messages == [("user", "hola")]


def test_downgrade_migrations_rolls_back_auth_and_memory_tiers(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.db"
    store = AuditStore(str(db_path))
    store.init_db()
    store.add_memory_item("user:a", "fact", "hello", b"[]", json.dumps({}))

    current_before = schema_status(store._conn)['current_version']
    rolled_back = downgrade_migrations(store._conn, target_version=1)
    assert rolled_back == list(range(current_before, 1, -1))

    status = schema_status(store._conn)
    assert status["current_version"] == 1

    cur = store._conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(memory_items)").fetchall()]
    assert "tier" not in cols
    tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "auth_users" not in tables
    assert "auth_sessions" not in tables
    assert "api_tokens" not in tables
    assert "evaluation_runs" not in tables
    assert "evaluation_case_results" not in tables


def test_cli_db_rollback_command(tmp_path: Path) -> None:
    cfg = tmp_path / "openmiura.yaml"
    db_path = tmp_path / "audit.db"
    backup_dir = tmp_path / "backups"
    _write_cfg(cfg, db_path, backup_dir)

    store = AuditStore(str(db_path))
    store.init_db()

    runner = CliRunner()
    current_before = schema_status(store._conn)['current_version']
    result = runner.invoke(cli.app, ["db", "rollback", "--config", str(cfg), "--steps", "1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rolled_back"] == [current_before]
    assert payload["current_version"] == current_before - 1
