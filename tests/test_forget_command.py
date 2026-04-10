from __future__ import annotations

from types import SimpleNamespace

from openmiura.commands import handle_commands
from openmiura.core.audit import AuditStore
from openmiura.core.memory import MemoryEngine


class FakeGateway:
    def __init__(self, db_path: str) -> None:
        self.audit = AuditStore(db_path)
        self.audit.init_db()
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(model="fake-llm"),
            memory=SimpleNamespace(embed_model="fake-embed"),
        )


def _seed_memory(gw: FakeGateway, user_key: str) -> list[int]:
    ids = []
    for text in ["Uno", "Dos", "Tres"]:
        gw.audit.add_memory_item(
            user_key=user_key,
            kind="fact",
            text=text,
            embedding_blob=b"1234",
            meta_json="{}",
        )
        item = gw.audit.search_memory_items(user_key=user_key, limit=1)[0]
        ids.append(item["id"])
    return ids


def test_forget_without_args_lists_latest_memories(tmp_path):
    gw = FakeGateway(str(tmp_path / "audit.db"))
    _seed_memory(gw, "u1")
    session_id = gw.audit.get_or_create_session("telegram", "u1", "s1")

    out = handle_commands(
        gw,
        channel="telegram",
        channel_user_id="tg:1",
        user_key="u1",
        session_id=session_id,
        text="/forget",
        metadata=None,
    )

    assert out is not None
    assert "Últimas 5 memorias" in out.text
    assert "#" in out.text


def test_forget_by_id_deletes_single_memory(tmp_path):
    gw = FakeGateway(str(tmp_path / "audit.db"))
    ids = _seed_memory(gw, "u1")
    session_id = gw.audit.get_or_create_session("telegram", "u1", "s1")

    out = handle_commands(
        gw,
        channel="telegram",
        channel_user_id="tg:1",
        user_key="u1",
        session_id=session_id,
        text=f"/forget {ids[1]}",
        metadata=None,
    )

    assert out is not None
    assert f"#{ids[1]}" in out.text
    assert gw.audit.count_memory_items("u1") == 2


def test_forget_all_requires_confirmation(tmp_path):
    gw = FakeGateway(str(tmp_path / "audit.db"))
    _seed_memory(gw, "u1")
    session_id = gw.audit.get_or_create_session("telegram", "u1", "s1")

    out = handle_commands(
        gw,
        channel="telegram",
        channel_user_id="tg:1",
        user_key="u1",
        session_id=session_id,
        text="/forget all",
        metadata=None,
    )

    assert out is not None
    assert "confirm" in out.text
    assert gw.audit.count_memory_items("u1") == 3

    out2 = handle_commands(
        gw,
        channel="telegram",
        channel_user_id="tg:1",
        user_key="u1",
        session_id=session_id,
        text="/forget all confirm",
        metadata=None,
    )

    assert out2 is not None
    assert "borrado" in out2.text.lower()
    assert gw.audit.count_memory_items("u1") == 0
