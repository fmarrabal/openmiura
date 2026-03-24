from __future__ import annotations

import json
import time

from openmiura.core.memory import MemoryEngine


class FakeEmbedder:
    def embed_one(self, text: str):
        return [1.0, 0.0, 0.0]


def make_memory(audit_store) -> MemoryEngine:
    mem = MemoryEngine(
        audit=audit_store,
        base_url="http://127.0.0.1:11434",
        embed_model="fake-embed",
        top_k=5,
        min_score=0.1,
        scan_limit=50,
        max_items_per_user=20,
        dedupe_threshold=0.95,
        store_user_facts=True,
        short_ttl_s=86400,
        medium_ttl_s=30 * 86400,
        short_promote_repeat=3,
        medium_promote_access=5,
    )
    mem.embedder = FakeEmbedder()
    return mem


def test_memory_consolidation_promotes_and_degrades(audit_store):
    mem = make_memory(audit_store)
    now = time.time()
    audit_store.add_memory_item("u1", "fact", "short repeat", b"1234", json.dumps({}), tier="short", repeat_count=4, access_count=0, last_accessed_at=now)
    audit_store.add_memory_item("u1", "fact", "medium access", b"1234", json.dumps({}), tier="medium", repeat_count=1, access_count=6, last_accessed_at=now)
    audit_store.add_memory_item("u1", "fact", "old short", b"1234", json.dumps({}), tier="short", repeat_count=1, access_count=0, last_accessed_at=now - 2 * 86400)
    audit_store.add_memory_item("u1", "fact", "old medium", b"1234", json.dumps({}), tier="medium", repeat_count=1, access_count=0, last_accessed_at=now - 40 * 86400)

    result = audit_store.consolidate_memory(user_key="u1", now=now, short_ttl_s=86400, medium_ttl_s=30 * 86400)

    assert result["promoted_to_medium"] == 1
    assert result["promoted_to_long"] == 1
    assert result["deleted_short"] == 1
    assert result["degraded_to_short"] == 1

    items = {item["text"]: item for item in audit_store.search_memory_items(user_key="u1", limit=10)}
    assert items["short repeat"]["tier"] == "medium"
    assert items["medium access"]["tier"] == "long"
    assert items["old medium"]["tier"] == "short"
    assert "old short" not in items


def test_recall_applies_tier_weighting(audit_store):
    mem = make_memory(audit_store)
    audit_store.add_memory_item("u1", "fact", "short note", b"1234", json.dumps({}), tier="short")
    audit_store.add_memory_item("u1", "fact", "long note", b"1234", json.dumps({}), tier="long")

    hits = mem.recall("u1", "anything", top_k=5)
    assert hits[0]["tier"] == "long"
