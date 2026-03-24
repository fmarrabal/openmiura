from __future__ import annotations

import builtins

from openmiura.core.audit import AuditStore
from scripts import memory_clean


def _make_store(tmp_path):
    store = AuditStore(str(tmp_path / "audit.db"))
    store.init_db()
    store.add_memory_item(
        user_key="u1",
        kind="qa",
        text="Pregunta vieja",
        embedding_blob=b"1234",
        meta_json="{}",
    )
    store.add_memory_item(
        user_key="u1",
        kind="fact",
        text="Dato bueno",
        embedding_blob=b"1234",
        meta_json="{}",
    )
    return store


def test_memory_clean_dry_run_lists_qa(tmp_path, monkeypatch, capsys):
    _make_store(tmp_path)
    monkeypatch.setattr(memory_clean.sys, "argv", ["memory_clean.py", "--db", str(tmp_path / "audit.db")])

    rc = memory_clean.run()

    captured = capsys.readouterr()
    assert rc == 0
    assert "kind='qa'" in captured.out
    assert "Dry-run" in captured.out


def test_memory_clean_execute_deletes_qa(tmp_path, monkeypatch):
    store = _make_store(tmp_path)
    monkeypatch.setattr(memory_clean.sys, "argv", ["memory_clean.py", "--db", str(tmp_path / "audit.db"), "--execute"])
    monkeypatch.setattr(builtins, "input", lambda _prompt='': "y")

    rc = memory_clean.run()

    assert rc == 0
    assert store.count_memory_items(kind="qa") == 0
    assert store.count_memory_items(kind="fact") == 1
