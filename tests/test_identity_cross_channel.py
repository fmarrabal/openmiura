from openmiura.core.audit import AuditStore
from openmiura.core.identity import IdentityManager


def test_identity_cross_channel_shares_user_key_and_memory(tmp_path):
    db = tmp_path / "audit.db"
    audit = AuditStore(str(db))
    audit.init_db()
    identity = IdentityManager(audit)

    identity.link("tg:1", "curro", linked_by="test")
    identity.link("http:u1", "curro", linked_by="test")

    assert identity.resolve("tg:1") == "curro"
    assert identity.resolve("http:u1") == "curro"

    emb = b"\x00" * 8
    audit.add_memory_item("curro", "fact", "dato compartido", emb, "{}")

    tg_items = audit.search_memory_items(user_key="curro", limit=10)
    http_items = audit.search_memory_items(user_key="curro", limit=10)

    assert tg_items
    assert http_items
    assert tg_items[0]["text"] == "dato compartido"
    assert http_items[0]["text"] == "dato compartido"