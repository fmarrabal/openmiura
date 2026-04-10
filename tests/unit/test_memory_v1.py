from openmiura.core.memory import MemoryEngine


class _FakeEmbedder:
    def embed_one(self, text: str):
        t = (text or '').lower()
        if 'almería' in t:
            return [1.0, 0.0, 0.0]
        if 'python' in t:
            return [0.0, 1.0, 0.0]
        if 'nota' in t:
            return [0.0, 0.0, 1.0]
        return [0.1, 0.1, 0.1]


def _memory(audit_store):
    mem = MemoryEngine(
        audit=audit_store,
        base_url='http://127.0.0.1:11434',
        embed_model='fake',
        top_k=3,
        min_score=0.2,
        scan_limit=20,
        max_items_per_user=3,
        dedupe_threshold=0.95,
    )
    mem.embedder = _FakeEmbedder()
    return mem


def test_memory_safe_mode_dedupe_recall_and_prune(audit_store):
    mem = _memory(audit_store)

    assert mem.remember_text('curro', 'qa', 'esto no debe guardarse') is False
    assert mem.remember_text('curro', 'fact', 'Vivo en Almería') is True
    assert mem.remember_text('curro', 'fact', 'Vivo en Almería') is True
    assert audit_store.count_memory_items(user_key='curro') == 1

    assert mem.remember_text('curro', 'preference', 'Me gusta Python') is True
    assert mem.remember_text('curro', 'user_note', 'Nota temporal') is True
    assert audit_store.count_memory_items(user_key='curro') == 3

    hits = mem.recall('curro', 'Almería')
    assert hits
    assert hits[0]['text'] == 'Vivo en Almería'

    mem.prune_old('curro', max_items=2)
    assert audit_store.count_memory_items(user_key='curro') == 2
