from __future__ import annotations

from openmiura.core.audit import AuditStore
from openmiura.core.memory import MemoryEngine


class FakeEmbedder:
    def embed_one(self, text: str):
        t = (text or "").lower()
        if "almería" in t:
            return [1.0, 0.0, 0.0]
        if "python" in t:
            return [0.0, 1.0, 0.0]
        if "gusta" in t or "prefiero" in t:
            return [0.0, 0.0, 1.0]
        return [0.2, 0.2, 0.2]


def make_memory(tmp_path) -> MemoryEngine:
    store = AuditStore(str(tmp_path / "memory.db"))
    store.init_db()
    mem = MemoryEngine(
        audit=store,
        base_url="http://127.0.0.1:11434",
        embed_model="fake-embed",
        top_k=5,
        min_score=0.1,
        scan_limit=50,
        max_items_per_user=100,
        dedupe_threshold=0.92,
        store_user_facts=True,
    )
    mem.embedder = FakeEmbedder()
    return mem


def test_remember_text_rejects_disallowed_kind(tmp_path):
    mem = make_memory(tmp_path)

    ok = mem.remember_text(
        user_key="u1",
        kind="qa",
        text="Esto no debe guardarse",
    )

    assert ok is False
    assert mem.audit.count_memory_items("u1") == 0


def test_maybe_remember_user_text_filters_questions_commands_and_short_texts(tmp_path):
    mem = make_memory(tmp_path)

    assert mem.maybe_remember_user_text("u1", "/help") is False
    assert mem.maybe_remember_user_text("u1", "¿Cómo me llamo?") is False
    assert mem.maybe_remember_user_text("u1", "hola") is False
    assert mem.audit.count_memory_items("u1") == 0


def test_maybe_remember_user_text_stores_declarative_statement(tmp_path):
    mem = make_memory(tmp_path)

    ok = mem.maybe_remember_user_text("u1", "Vivo en Almería desde hace años")

    assert ok is True
    items = mem.audit.search_memory_items(user_key="u1", limit=10)
    assert len(items) == 1
    assert items[0]["kind"] == "fact"
    assert "Almería" in items[0]["text"]


def test_preference_statement_is_classified_as_preference(tmp_path):
    mem = make_memory(tmp_path)

    ok = mem.maybe_remember_user_text("u1", "Me gusta programar en Python por las tardes")

    assert ok is True
    items = mem.audit.search_memory_items(user_key="u1", limit=10)
    assert len(items) == 1
    assert items[0]["kind"] == "preference"


def test_semantic_dedupe_updates_duplicate_memory(tmp_path):
    mem = make_memory(tmp_path)

    first = mem.remember_text("u1", "fact", "Vivo en Almería")
    second = mem.remember_text("u1", "fact", "Vivo en Almería")

    assert first is True
    assert second is True
    assert mem.audit.count_memory_items("u1") == 1


def test_recall_returns_only_allowed_kinds(tmp_path):
    mem = make_memory(tmp_path)

    mem.remember_text("u1", "fact", "Vivo en Almería")
    mem.audit.add_memory_item(
        user_key="u1",
        kind="qa",
        text="Pregunta-respuesta heredada",
        embedding_blob=b"1234",
        meta_json="{}",
    )

    hits = mem.recall(user_key="u1", query="Almería", top_k=5)

    assert len(hits) == 1
    assert hits[0]["kind"] == "fact"
    assert "Almería" in hits[0]["text"]


def test_delete_memory_items_removes_user_memory(tmp_path):
    mem = make_memory(tmp_path)

    mem.remember_text("u1", "fact", "Vivo en Almería")
    mem.remember_text("u1", "preference", "Me gusta Python")

    deleted = mem.audit.delete_memory_items("u1")

    assert deleted == 2
    assert mem.audit.count_memory_items("u1") == 0


def test_recall_can_filter_by_kinds(tmp_path):
    mem = make_memory(tmp_path)

    mem.remember_text("u1", "fact", "Vivo en Almería")
    mem.remember_text("u1", "preference", "Me gusta Python")

    hits = mem.recall(user_key="u1", query="Python", top_k=5, kinds=["preference"])

    assert len(hits) == 1
    assert hits[0]["kind"] == "preference"


def test_prune_old_keeps_only_latest_items(tmp_path):
    mem = make_memory(tmp_path)

    mem.remember_text("u1", "fact", "Uno Almería")
    mem.remember_text("u1", "fact", "Dos Python")
    mem.remember_text("u1", "fact", "Tres genérico")

    mem.prune_old("u1", max_items=2)

    assert mem.audit.count_memory_items("u1") == 2
