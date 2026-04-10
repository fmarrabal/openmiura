from __future__ import annotations

import sqlite3

from openmiura.core.audit import AuditStore


def make_store(tmp_path):
    db_path = tmp_path / "audit_test.db"
    store = AuditStore(str(db_path))
    store.init_db()
    return store


def test_init_db_creates_expected_tables(tmp_path):
    store = make_store(tmp_path)

    conn = sqlite3.connect(store.db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {r[0] for r in rows}

    expected = {
        "sessions",
        "messages",
        "events",
        "memory_items",
        "telegram_state",
        "identity_map",
        "tool_calls",
        "slack_event_dedupe",
    }
    assert expected.issubset(table_names)


def test_get_or_create_session_is_stable_for_same_session_id(tmp_path):
    store = make_store(tmp_path)

    session_id = store.get_or_create_session(
        channel="http",
        user_id="u1",
        session_id="sess-123",
    )
    session_id_again = store.get_or_create_session(
        channel="http",
        user_id="u1",
        session_id="sess-123",
    )

    assert session_id == "sess-123"
    assert session_id_again == "sess-123"
    assert store.table_counts()["sessions"] == 1


def test_append_message_and_recent_messages(tmp_path):
    store = make_store(tmp_path)
    session_id = store.get_or_create_session("http", "u1", "sess-1")

    store.append_message(session_id, "user", "hola")
    store.append_message(session_id, "assistant", "qué tal")

    assert store.get_recent_messages(session_id, limit=10) == [
        ("user", "hola"),
        ("assistant", "qué tal"),
    ]
    assert store.table_counts()["messages"] == 2


def test_table_counts_reflect_data(tmp_path):
    store = make_store(tmp_path)
    session_id = store.get_or_create_session("http", "u1", "sess-2")

    store.append_message(session_id, "user", "mensaje")
    store.log_event(
        direction="in",
        channel="http",
        user_id="u1",
        session_id=session_id,
        payload={"text": "mensaje"},
    )
    store.set_identity("tg:1", "global-curro")
    store.set_telegram_offset("bot-1", 42)
    store.log_tool_call(
        session_id=session_id,
        user_key="global-curro",
        agent_id="default",
        tool_name="time_now",
        args_json="{}",
        ok=True,
        result_excerpt="2026-03-14",
        error="",
        duration_ms=3.5,
    )

    counts = store.table_counts()
    assert counts["sessions"] == 1
    assert counts["messages"] == 1
    assert counts["events"] == 1
    assert counts["identity_map"] == 1
    assert counts["telegram_state"] == 1
    assert counts["tool_calls"] == 1


def test_mark_slack_event_once_is_idempotent(tmp_path):
    store = make_store(tmp_path)

    first = store.mark_slack_event_once(
        event_id="evt-1",
        team_id="T1",
        channel_id="C1",
        user_id="U1",
    )
    second = store.mark_slack_event_once(
        event_id="evt-1",
        team_id="T1",
        channel_id="C1",
        user_id="U1",
    )

    assert first is True
    assert second is False
    assert store.table_counts()["slack_event_dedupe"] == 1
