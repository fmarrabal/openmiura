from __future__ import annotations

from openmiura.core.identity import IdentityManager


def test_identity_link_unlink_resolve_and_list(audit_store):
    identity = IdentityManager(audit_store)

    assert identity.resolve("tg:1") is None

    identity.link("tg:1", "curro", linked_by="test")
    assert identity.resolve("tg:1") == "curro"

    links = identity.list_links("curro")
    assert len(links) == 1
    assert links[0]["channel_user_key"] == "tg:1"
    assert links[0]["global_user_key"] == "curro"

    assert identity.unlink("tg:1") == 1
    assert identity.resolve("tg:1") is None
