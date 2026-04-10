from __future__ import annotations

from typing import Any

from openmiura.core.contracts import AdminGatewayLike


class MemoryService:
    def semantic_or_table_search(
        self,
        gw: AdminGatewayLike,
        *,
        q: str | None,
        user_key: str | None,
        top_k: int,
    ) -> dict[str, Any]:
        if q and getattr(gw, "memory", None) is not None and user_key:
            try:
                hits = gw.memory.recall(user_key=user_key, query=q, top_k=top_k)  # type: ignore[attr-defined]
                return {
                    "ok": True,
                    "mode": "semantic",
                    "q": q,
                    "user_key": user_key,
                    "top_k": top_k,
                    "items": hits,
                }
            except Exception:
                pass

        if getattr(gw, "memory", None) is not None:
            try:
                items = gw.memory.search_items(user_key=user_key, text_contains=q, limit=top_k)  # type: ignore[attr-defined]
            except Exception:
                items = gw.audit.search_memory_items(user_key=user_key, text_contains=q, limit=top_k)
        else:
            items = gw.audit.search_memory_items(user_key=user_key, text_contains=q, limit=top_k)
        return {
            "ok": True,
            "mode": "table",
            "q": q,
            "user_key": user_key,
            "items": items,
        }

    def search(
        self,
        gw: AdminGatewayLike,
        *,
        user_key: str | None,
        kind: str | None,
        text_contains: str | None,
        limit: int,
        max_rows: int,
    ) -> dict[str, Any]:
        limited = min(int(limit), int(max_rows))
        if getattr(gw, "memory", None) is not None:
            try:
                items = gw.memory.search_items(  # type: ignore[attr-defined]
                    user_key=user_key,
                    kind=kind,
                    text_contains=text_contains,
                    limit=limited,
                )
            except Exception:
                items = gw.audit.search_memory_items(
                    user_key=user_key,
                    kind=kind,
                    text_contains=text_contains,
                    limit=limited,
                )
        else:
            items = gw.audit.search_memory_items(
                user_key=user_key,
                kind=kind,
                text_contains=text_contains,
                limit=limited,
            )
        return {
            "ok": True,
            "filters": {
                "user_key": user_key,
                "kind": kind,
                "text_contains": text_contains,
                "limit": limit,
            },
            "returned": len(items),
            "items": items,
        }

    def delete(
        self,
        gw: AdminGatewayLike,
        *,
        user_key: str,
        kind: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        would_delete = gw.audit.count_memory_items(user_key=user_key, kind=kind)
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "user_key": user_key,
                "kind": kind,
                "would_delete": would_delete,
            }

        deleted = gw.audit.delete_memory_items(user_key=user_key, kind=kind)
        return {
            "ok": True,
            "dry_run": False,
            "user_key": user_key,
            "kind": kind,
            "deleted": deleted,
        }

    def delete_by_id(self, gw: AdminGatewayLike, *, item_id: int) -> dict[str, Any]:
        deleted = gw.audit.delete_memory_item_by_id(item_id)
        return {"ok": True, "item_id": item_id, "deleted": deleted}
