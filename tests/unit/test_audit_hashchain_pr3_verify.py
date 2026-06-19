"""Audit hash-chain — PR 3 (`openmiura db verify-chain`).

Read-only verifier over the events + tool_calls chains written in PR 2: it
recomputes every row_hash, checks the prev_hash links and chain_seq
contiguity, and matches the per-scope head. These tests prove it accepts an
untampered chain and detects each tamper class (mutated content, broken
link, deleted row), plus the CLI exit-code contract.
"""
from __future__ import annotations

from pathlib import Path

from openmiura.core.db import DBConnection
from openmiura.core.migrations import apply_migrations
from openmiura.persistence.sessions_repo import SessionsRepo
from openmiura.persistence.tools_repo import ToolsRepo
from openmiura.persistence.hashchain import verify_audit_chain, CHAINED_TABLES


def _conn(tmp_path):
    c = DBConnection(backend="sqlite", db_path=(tmp_path / "audit.db").as_posix(), database_url="")
    apply_migrations(c)
    return c


def _seed(conn, n=4):
    repo = SessionsRepo(conn)
    for i in range(n):
        repo.log_event("in", "http", "u", "s", {"i": i}, tenant_id="acme", workspace_id="w", environment="prod")
    ToolsRepo(conn).log_tool_call("s", "u", "default", "lookup", '{"q": "x"}', True, "ok", "", 1.0,
                                  tenant_id="acme", workspace_id="w", environment="prod")


def _drop_append_only_triggers(conn):
    """The append-only triggers (migration 24) block UPDATE/DELETE on the
    chained tables — exactly so an attacker can't tamper in-place. To
    SIMULATE tamper in these tests we must first drop them (the only way to
    mutate the rows), then prove the verifier still detects the divergence."""
    cur = conn.cursor()
    for table in ("events", "tool_calls"):
        cur.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
        cur.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
    conn.commit()


def test_intact_chains_verify(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    for table in CHAINED_TABLES:
        res = verify_audit_chain(conn, chain_table=table)
        assert res["any_tamper"] is False
        for chain in res["chains"]:
            assert chain["chain_valid"] is True
            assert chain["head_matches"] is True


def test_tampered_payload_is_detected(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    # Mutate a row's content directly (bypassing the write path).
    _drop_append_only_triggers(conn)
    conn.cursor().execute("UPDATE events SET payload_json='{\"i\": 999}' WHERE chain_seq=2")
    conn.commit()
    res = verify_audit_chain(conn, chain_table="events")
    assert res["any_tamper"] is True
    bad = [c for c in res["chains"] if not c["chain_valid"]]
    assert bad and bad[0]["first_bad_seq"] == 2


def test_broken_prev_hash_link_is_detected(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    _drop_append_only_triggers(conn)
    conn.cursor().execute("UPDATE events SET prev_hash='deadbeef' WHERE chain_seq=3")
    conn.commit()
    res = verify_audit_chain(conn, chain_table="events")
    assert res["any_tamper"] is True
    assert any(c["first_bad_seq"] == 3 for c in res["chains"])


def test_deleted_row_creates_sequence_gap(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    # Removing a middle row leaves a gap (1,2,4) the verifier rejects.
    _drop_append_only_triggers(conn)
    conn.cursor().execute("DELETE FROM events WHERE chain_seq=3")
    conn.commit()
    res = verify_audit_chain(conn, chain_table="events")
    assert res["any_tamper"] is True


def test_head_mismatch_is_detected(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    conn.cursor().execute("UPDATE audit_chain_heads SET head_hash='forged' WHERE chain_table='events'")
    conn.commit()
    res = verify_audit_chain(conn, chain_table="events")
    assert res["any_tamper"] is True
    assert any(c["head_matches"] is False for c in res["chains"])


# ============================ CLI ============================

_CONFIG = """\
server:
  host: "127.0.0.1"
  port: 8081
storage:
  db_path: "{db}"
llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5:7b-instruct"
tools:
  sandbox_dir: "{sandbox}"
"""


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        _CONFIG.format(db=(tmp_path / "audit.db").as_posix(), sandbox=(tmp_path / "sandbox").as_posix()),
        encoding="utf-8",
    )
    return cfg


def test_cli_exit_codes(tmp_path):
    from openmiura.cli import db_verify_chain_cli
    from openmiura.core.audit import AuditStore

    cfg = _write_config(tmp_path)
    store = AuditStore(db_path=(tmp_path / "audit.db").as_posix(), backend="sqlite", database_url="")
    apply_migrations(store._conn)
    _seed(store._conn)

    # Intact → exit 0.
    assert db_verify_chain_cli(config=str(cfg)) == 0
    # Unknown / non-chained table → usage error (3), no DB walk needed.
    assert db_verify_chain_cli(config=str(cfg), table="sessions") == 3

    # Tamper → exit 1.
    _drop_append_only_triggers(store._conn)
    store._conn.cursor().execute("UPDATE events SET row_hash='forged' WHERE chain_seq=1")
    store._conn.commit()
    assert db_verify_chain_cli(config=str(cfg)) == 1
