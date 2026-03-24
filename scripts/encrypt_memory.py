from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from openmiura.core.audit import AuditStore
from openmiura.core.memory import MemoryEngine
from openmiura.core.vault import ContextVault


class _NoNetworkEmbedder:
    def embed_one(self, text: str):
        raise RuntimeError("Embedder should not be called during encryption migration")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encrypt existing openMiura memories in place.")
    parser.add_argument("--db", required=True, help="Path to audit.db")
    parser.add_argument("--passphrase-env", default="OPENMIURA_VAULT_PASSPHRASE")
    parser.add_argument("--iterations", type=int, default=390000)
    parser.add_argument("--execute", action="store_true", help="Apply changes instead of dry-run")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)

    passphrase = os.environ.get(args.passphrase_env, "")
    if not passphrase:
        payload = {"ok": False, "error": f"Missing env var {args.passphrase_env}"}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else payload["error"])
        return 1

    store = AuditStore(args.db)
    store.init_db()
    vault = ContextVault(enabled=True, passphrase=passphrase, iterations=args.iterations)
    memory = MemoryEngine(
        audit=store,
        base_url="http://127.0.0.1:11434",
        embed_model="nomic-embed-text",
        vault=vault,
    )
    memory.embedder = _NoNetworkEmbedder()

    encrypted = 0
    skipped = 0
    updates = []
    for row in store.iter_memory_records():
        meta = dict(row.get("meta") or {})
        if ContextVault.is_encrypted_meta(meta):
            skipped += 1
            continue
        stored_text, meta_with_vault = memory._prepare_storage_text(
            user_key=str(row["user_key"]),
            kind=str(row["kind"]),
            text=str(row["text"]),
            meta=meta,
        )
        updates.append((row, stored_text, json.dumps(meta_with_vault, ensure_ascii=False)))
        encrypted += 1

    if args.execute:
        for row, stored_text, meta_json in updates:
            store.update_memory_item(
                item_id=int(row["id"]),
                kind=str(row["kind"]),
                text=stored_text,
                embedding_blob=row["embedding"],
                meta_json=meta_json,
                tier=str(row.get("tier") or "medium"),
                repeat_count=int(row.get("repeat_count", 1)),
                access_count=int(row.get("access_count", 0)),
                last_accessed_at=float(row.get("last_accessed_at") or row["created_at"]),
            )

    payload = {
        "ok": True,
        "db": str(Path(args.db)),
        "execute": bool(args.execute),
        "encrypted": encrypted,
        "skipped": skipped,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
