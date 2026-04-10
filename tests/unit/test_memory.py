from __future__ import annotations

from openmiura.core.memory import MemoryEngine


class FakeEmbedder:
    def embed_one(self, text: str):
        low = (text or "").lower()
        if "almería" in low:
            return [1.0, 0.0, 0.0]
        if "python" in low:
            return [0.0, 1.0, 0.0]
        if "nota" in low:
            return [0.0, 0.0, 1.0]
        return [0.2, 0.2, 0.2]


def make_memory(audit_store) -> MemoryEngine:
    mem = MemoryEngine(
        audit=audit_store,
        base_url="http://127.0.0.1:11434",
        embed_model="fake-embed",
        top_k=5,
        min_score=0.1,
        scan_limit=50,
        max_items_per_user=3,
        dedupe_threshold=0.95,
        store_user_facts=True,
    )
    mem.embedder = FakeEmbedder()
    return mem


def test_memory_safe_mode_recall_and_pruning(audit_store):
    mem = make_memory(audit_store)

    assert mem.remember_text("curro", "qa", "esto no debe guardarse") is False
    assert mem.remember_text("curro", "fact", "Vivo en Almería") is True
    assert mem.remember_text("curro", "fact", "Vivo en Almería") is True
    assert audit_store.count_memory_items("curro") == 1

    assert mem.remember_text("curro", "preference", "Me gusta Python") is True
    assert mem.remember_text("curro", "user_note", "Nota temporal") is True
    assert audit_store.count_memory_items("curro") == 3

    hits = mem.recall("curro", "Almería")
    assert hits
    assert hits[0]["kind"] == "fact"
    assert hits[0]["text"] == "Vivo en Almería"

    mem.prune_old("curro", max_items=2)
    assert audit_store.count_memory_items("curro") == 2


def test_memory_filters_questions_commands_and_short_messages(audit_store):
    mem = make_memory(audit_store)

    assert mem.maybe_remember_user_text("curro", "/help") is False
    assert mem.maybe_remember_user_text("curro", "¿Cómo me llamo?") is False
    assert mem.maybe_remember_user_text("curro", "hola") is False
    assert audit_store.count_memory_items("curro") == 0

    assert mem.maybe_remember_user_text("curro", "Prefiero Python para prototipar") is True
    items = audit_store.search_memory_items(user_key="curro", limit=10)
    assert len(items) == 1
    assert items[0]["kind"] == "preference"
