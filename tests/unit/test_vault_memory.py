from __future__ import annotations

import os

from openmiura.core.memory import MemoryEngine
from openmiura.core.vault import ContextVault


class FakeEmbedder:
    def embed_one(self, text: str):
        t = (text or "").lower()
        if "almería" in t:
            return [1.0, 0.0, 0.0]
        if "python" in t:
            return [0.0, 1.0, 0.0]
        return [0.1, 0.1, 0.1]


def make_memory(audit_store) -> MemoryEngine:
    vault = ContextVault(enabled=True, passphrase="secret-passphrase")
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
        vault=vault,
    )
    mem.embedder = FakeEmbedder()
    return mem


def test_vault_encrypts_stored_text_but_recall_decrypts(audit_store):
    mem = make_memory(audit_store)

    assert mem.remember_text("curro", "fact", "Vivo en Almería") is True

    raw_items = audit_store.search_memory_items(user_key="curro", limit=5)
    assert raw_items[0]["text"] == "[encrypted]"
    assert "_vault" in raw_items[0]["meta"]

    searched = mem.search_items(user_key="curro", limit=5)
    assert searched[0]["text"] == "Vivo en Almería"

    hits = mem.recall("curro", "Almería")
    assert hits[0]["text"] == "Vivo en Almería"


def test_vaulted_memory_search_text_contains_works(audit_store):
    mem = make_memory(audit_store)
    mem.remember_text("curro", "preference", "Me gusta Python")

    hits = mem.search_items(user_key="curro", text_contains="python", limit=5)
    assert len(hits) == 1
    assert hits[0]["text"] == "Me gusta Python"
