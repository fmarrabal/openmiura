from __future__ import annotations

import json
import math
from array import array
from typing import Any, Dict, List, Optional, Set

import httpx

from .audit import AuditStore
from .vault import ContextVault, memory_aad


def _pack_f32(vec: List[float]) -> bytes:
    return array("f", vec).tobytes()


def _unpack_f32(blob: bytes) -> array:
    a = array("f")
    a.frombytes(blob)
    return a


def _cosine(a: array, b: array) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += float(x) * float(y)
        na += float(x) * float(x)
        nb += float(y) * float(y)
    denom = math.sqrt(na) * math.sqrt(nb) + 1e-12
    return float(dot) / denom


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, timeout_s: int = 60):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    def embed_one(self, text: str) -> List[float]:
        url = f"{self.base_url}/api/embed"
        payload = {"model": self.model, "input": text}
        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()

        embs = data.get("embeddings")
        if not embs or not isinstance(embs, list) or not isinstance(embs[0], list):
            raise RuntimeError(f"Unexpected embedding response: {data}")
        return [float(x) for x in embs[0]]


class MemoryEngine:
    """
    Safe Mode:
      - NO guardamos QA (ni respuestas del asistente como 'verdad').
      - Solo guardamos: fact | preference | user_note | tool_result
      - recall() ignora todo lo demás (incluye qa heredado).
    """

    ALLOWED_KINDS: Set[str] = {"fact", "preference", "user_note", "tool_result"}
    TIER_WEIGHTS: dict[str, float] = {"long": 1.5, "medium": 1.2, "short": 1.0}

    def __init__(
        self,
        audit: AuditStore,
        base_url: str,
        embed_model: str,
        timeout_s: int = 60,
        top_k: int = 6,
        min_score: float = 0.25,
        scan_limit: int = 400,
        max_items_per_user: int = 2000,
        dedupe_threshold: float = 0.92,
        store_user_facts: bool = True,
        vault: ContextVault | None = None,
        short_ttl_s: int = 86400,
        medium_ttl_s: int = 2592000,
        short_promote_repeat: int = 3,
        medium_promote_access: int = 5,
    ):
        self.audit = audit
        self.embedder = OllamaEmbedder(base_url=base_url, model=embed_model, timeout_s=timeout_s)
        self.top_k = int(top_k)
        self.min_score = float(min_score)
        self.scan_limit = int(scan_limit)
        self.max_items_per_user = int(max_items_per_user)
        self.dedupe_threshold = float(dedupe_threshold)
        self.store_user_facts = bool(store_user_facts)
        self.vault = vault
        self.short_ttl_s = int(short_ttl_s)
        self.medium_ttl_s = int(medium_ttl_s)
        self.short_promote_repeat = int(short_promote_repeat)
        self.medium_promote_access = int(medium_promote_access)

    # ---------- Public API ----------

    def remember_text(
        self,
        user_key: str,
        kind: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
        *,
        dedupe: bool = True,
        dedupe_window: int = 80,
        tier: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> bool:
        kind = (kind or "").strip()
        if kind not in self.ALLOWED_KINDS:
            return False

        clean = self._normalize_text(text)
        if not clean:
            return False

        storage_tier = self._normalize_tier(tier or self._default_tier_for_kind(kind))
        raw_meta = dict(meta or {})

        vec = self.embedder.embed_one(clean)
        blob = _pack_f32(vec)
        new_arr = array("f", vec)

        if dedupe:
            recent = self.audit.get_recent_memory_records(user_key=user_key, limit=min(dedupe_window, self.scan_limit), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
            for row in recent:
                if row["kind"] not in self.ALLOWED_KINDS:
                    continue
                try:
                    old_arr = _unpack_f32(row["embedding"])
                    score = _cosine(new_arr, old_arr)
                    if score >= self.dedupe_threshold:
                        current_meta = self._clean_meta(row.get("meta") or {})
                        merged_meta = {**current_meta, **raw_meta}
                        stored_text, meta_with_vault = self._prepare_storage_text(
                            user_key=user_key,
                            kind=kind,
                            text=clean,
                            meta=merged_meta,
                        )
                        self.audit.increment_memory_repeat(
                            item_id=int(row["id"]),
                            kind=kind,
                            text=stored_text,
                            embedding_blob=blob,
                            meta_json=json.dumps(meta_with_vault, ensure_ascii=False),
                            tier=storage_tier,
                        )
                        return True
                except Exception:
                    pass

        stored_text, meta_with_vault = self._prepare_storage_text(
            user_key=user_key,
            kind=kind,
            text=clean,
            meta=raw_meta,
        )
        self.audit.add_memory_item(
            user_key=user_key,
            kind=kind,
            text=stored_text,
            embedding_blob=blob,
            meta_json=json.dumps(meta_with_vault, ensure_ascii=False),
            tier=storage_tier,
            repeat_count=1,
            access_count=0,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        self.audit.prune_memory(user_key=user_key, keep_last=self.max_items_per_user)
        return True

    def maybe_remember_user_text(self, user_key: str, user_text: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> bool:
        if not self.store_user_facts:
            return False

        text = self._normalize_text(user_text)
        if not text:
            return False
        if text.startswith("/"):
            return False
        if "?" in text or text.startswith("¿") or text.endswith("?"):
            return False
        if len(text) < 12:
            return False

        kind = self._classify_user_statement(text)
        return self.remember_text(user_key=user_key, kind=kind, text=text, meta={"source": "user"}, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def recall(
        self,
        user_key: str,
        query: str,
        top_k: Optional[int] = None,
        kinds: Optional[List[str]] = None,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> List[Dict[str, Any]]:
        top_k = int(top_k or self.top_k)
        q = self._normalize_text(query)
        if not q:
            return []

        q_vec = self.embedder.embed_one(q)
        q_arr = array("f", q_vec)

        allowed_kinds = set(self.ALLOWED_KINDS)
        if kinds is not None:
            allowed_kinds &= {str(k).strip() for k in kinds if str(k).strip()}
            if not allowed_kinds:
                return []

        rows = self.audit.get_recent_memory_records(user_key=user_key, limit=self.scan_limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        scored: List[Dict[str, Any]] = []

        for row in rows:
            kind = str(row["kind"])
            if kind not in allowed_kinds:
                continue

            try:
                emb_arr = _unpack_f32(row["embedding"])
                score = _cosine(q_arr, emb_arr)
            except Exception:
                continue

            weighted = score * self._tier_weight(row.get("tier"))
            if weighted >= self.min_score:
                scored.append(
                    {
                        "id": row["id"],
                        "kind": kind,
                        "text": self._resolve_row_text(row),
                        "score": float(weighted),
                        "raw_score": float(score),
                        "tier": row.get("tier", "medium"),
                        "created_at": float(row["created_at"]),
                        "access_count": int(row.get("access_count", 0)),
                        "repeat_count": int(row.get("repeat_count", 1)),
                    }
                )

        scored.sort(key=lambda x: x["score"], reverse=True)
        hits = scored[:top_k]
        try:
            self.audit.note_memory_access(h["id"] for h in hits)
        except Exception:
            pass
        return hits

    def search_items(
        self,
        *,
        user_key: str | None = None,
        kind: str | None = None,
        text_contains: str | None = None,
        limit: int = 20,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.audit.search_memory_items(
            user_key=user_key,
            kind=kind,
            text_contains=text_contains,
            limit=limit,
            text_resolver=self._resolve_row_text,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        for item in rows:
            item.pop("embedding", None)
        return rows

    def consolidate(self, *, user_key: str | None = None) -> dict[str, int]:
        return self.audit.consolidate_memory(
            user_key=user_key,
            short_ttl_s=float(self.short_ttl_s),
            medium_ttl_s=float(self.medium_ttl_s),
            short_promote_repeat=int(self.short_promote_repeat),
            medium_promote_access=int(self.medium_promote_access),
        )

    def prune_old(self, user_key: str, max_items: int = 500) -> None:
        self.audit.prune_memory(user_key=user_key, keep_last=int(max_items))

    def format_context(self, hits: List[Dict[str, Any]]) -> str:
        if not hits:
            return ""

        lines = ["Long-term memory (use only if helpful, do not fabricate):"]
        for h in hits:
            prefix = {
                "fact": "FACT",
                "preference": "PREFERENCE",
                "user_note": "NOTE",
                "tool_result": "TOOL",
            }.get(h["kind"], "MEM")
            tier = str(h.get("tier") or "medium").upper()
            lines.append(f"- [{prefix}/{tier}] {h['text']}")
        return "\n".join(lines)

    # ---------- Internal helpers ----------

    def _prepare_storage_text(
        self,
        *,
        user_key: str,
        kind: str,
        text: str,
        meta: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        meta = self._clean_meta(meta)
        if self.vault is None or not self.vault.is_enabled():
            return text, meta
        return self.vault.encrypt_meta(text, meta, aad=memory_aad(user_key=user_key, kind=kind))

    def _resolve_row_text(self, row: dict[str, Any]) -> str:
        meta = dict(row.get("meta") or {})
        text = str(row.get("text") or "")
        if self.vault is None or not ContextVault.is_encrypted_meta(meta):
            return text
        return self.vault.decrypt_meta(
            text,
            meta,
            aad=memory_aad(user_key=str(row.get("user_key") or ""), kind=str(row.get("kind") or "")),
        )

    @staticmethod
    def _clean_meta(meta: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(meta or {})
        if ContextVault.is_encrypted_meta(cleaned):
            cleaned = ContextVault.strip_vault_meta(cleaned)
        return cleaned

    @staticmethod
    def _normalize_text(text: str) -> str:
        return (text or "").strip()

    @staticmethod
    def _classify_user_statement(text: str) -> str:
        t = text.lower()
        pref_markers = ["prefiero", "me gusta", "no me gusta", "odio", "encanta", "favorito", "preferencia"]
        if any(m in t for m in pref_markers):
            return "preference"
        return "fact"

    @staticmethod
    def _default_tier_for_kind(kind: str) -> str:
        return "short" if kind in {"user_note", "tool_result"} else "medium"

    @staticmethod
    def _normalize_tier(tier: str | None) -> str:
        raw = str(tier or "medium").strip().lower()
        if raw not in {"short", "medium", "long"}:
            return "medium"
        return raw

    def _tier_weight(self, tier: str | None) -> float:
        return float(self.TIER_WEIGHTS.get(self._normalize_tier(tier), 1.0))
