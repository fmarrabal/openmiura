"""Audit hash-chain — PR 2b (decision_traces immutable versions, option A).

decision_traces legitimately receives the same trace_id more than once as a
turn's status progresses. Instead of an in-place upsert it is now append-only
with a composite PK (trace_id, version); readers return the latest version per
trace_id, so external behaviour (get/list/count) is unchanged — the table is
just truly append-only now, the prerequisite for chaining it.
"""
from __future__ import annotations

from openmiura.core.db import DBConnection
from openmiura.core.migrations import MIGRATIONS, apply_migrations, downgrade_migrations
from openmiura.persistence.tools_repo import ToolsRepo


def _conn(tmp_path):
    c = DBConnection(backend="sqlite", db_path=(tmp_path / "audit.db").as_posix(), database_url="")
    apply_migrations(c)
    return c


def _log(repo, trace_id, **over):
    kw = dict(
        trace_id=trace_id, session_id="s", user_key="u", channel="http", agent_id="default",
        request_text="q", response_text="", status="started",
        tenant_id="acme", workspace_id="w", environment="prod",
    )
    kw.update(over)
    repo.log_decision_trace(**kw)


def test_migration_25_registered_and_contiguous():
    by_version = {m.version: m for m in MIGRATIONS}
    assert by_version[25].name == "decision_traces_immutable_versions"
    assert sorted(by_version) == list(range(1, max(by_version) + 1))


def test_composite_pk_and_version_column(tmp_path):
    conn = _conn(tmp_path)
    cols = {r[1] for r in conn.cursor().execute("PRAGMA table_info(decision_traces)").fetchall()}
    assert "version" in cols
    pk = [r[1] for r in conn.cursor().execute("PRAGMA table_info(decision_traces)").fetchall() if r[5]]
    assert set(pk) == {"trace_id", "version"}


def test_relogging_same_trace_id_appends_a_version(tmp_path):
    conn = _conn(tmp_path)
    repo = ToolsRepo(conn)
    _log(repo, "t1", status="started", response_text="")
    _log(repo, "t1", status="completed", response_text="final answer")

    # Two physical rows (v1, v2) for the same trace_id.
    rows = conn.cursor().execute(
        "SELECT version, status FROM decision_traces WHERE trace_id='t1' ORDER BY version"
    ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [(1, "started"), (2, "completed")]


def test_get_returns_latest_version(tmp_path):
    conn = _conn(tmp_path)
    repo = ToolsRepo(conn)
    _log(repo, "t1", status="started", response_text="")
    _log(repo, "t1", status="completed", response_text="final answer")
    trace = repo.get_decision_trace("t1")
    assert trace["status"] == "completed"
    assert trace["response_text"] == "final answer"


def test_list_dedups_to_latest_version_per_trace(tmp_path):
    conn = _conn(tmp_path)
    repo = ToolsRepo(conn)
    _log(repo, "t1", status="started")
    _log(repo, "t1", status="completed")
    _log(repo, "t2", status="completed")
    listed = repo.list_decision_traces(limit=50)
    # One entry per trace_id (latest), not one per version.
    ids = sorted(t["trace_id"] for t in listed)
    assert ids == ["t1", "t2"]
    t1 = next(t for t in listed if t["trace_id"] == "t1")
    assert t1["status"] == "completed"


def test_single_log_is_one_row_version_one(tmp_path):
    conn = _conn(tmp_path)
    repo = ToolsRepo(conn)
    _log(repo, "solo", status="completed")
    n = conn.cursor().execute("SELECT COUNT(*) FROM decision_traces WHERE trace_id='solo'").fetchone()[0]
    assert n == 1
    assert repo.get_decision_trace("solo")["status"] == "completed"
    assert len(repo.list_decision_traces(limit=50)) == 1


def test_downgrade_collapses_to_single_pk_keeping_latest(tmp_path):
    conn = _conn(tmp_path)
    repo = ToolsRepo(conn)
    _log(repo, "t1", status="started")
    _log(repo, "t1", status="completed")
    downgrade_migrations(conn, target_version=24)  # undo migration 25
    cols = {r[1] for r in conn.cursor().execute("PRAGMA table_info(decision_traces)").fetchall()}
    assert "version" not in cols
    rows = conn.cursor().execute("SELECT trace_id, status FROM decision_traces").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("t1", "completed")]  # only the latest survived
