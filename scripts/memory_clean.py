from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openmiura.core.audit import AuditStore
from openmiura.core.memory import MemoryEngine


ALLOWED_RECLASSIFY = tuple(sorted(MemoryEngine.ALLOWED_KINDS))


def _preview(text: str, width: int = 100) -> str:
    clean = (text or "").replace("\n", " ").strip()
    if len(clean) <= width:
        return clean
    return clean[: width - 3] + "..."


def _load_qa_items(store: AuditStore) -> list[dict]:
    return store.search_memory_items(kind="qa", limit=1_000_000)


def _print_items(items: list[dict]) -> None:
    if not items:
        print("No se han encontrado items con kind='qa'.")
        return
    print(f"Encontrados {len(items)} items kind='qa':")
    for item in items:
        print(
            f"- #{item['id']} user={item['user_key']} kind={item['kind']} text={_preview(item['text'])}"
        )


def _confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer in {"y", "yes", "s", "si", "sí"}


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Limpia o reclasifica memoria contaminada (kind='qa')."
    )
    parser.add_argument("--db", default="data/audit.db", help="Ruta al SQLite de openMiura")
    parser.add_argument("--execute", action="store_true", help="Borra realmente los items QA")
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Reclasifica interactivamente items QA a fact/user_note/preference/tool_result",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: no existe la base de datos: {db_path}", file=sys.stderr)
        return 2

    store = AuditStore(str(db_path))
    store.init_db()

    qa_items = _load_qa_items(store)
    _print_items(qa_items)

    if not qa_items:
        return 0

    if args.reclassify:
        print("\nModo reclasificación interactiva.")
        print("Opciones: fact | preference | user_note | tool_result | skip | delete")
        changed = 0
        deleted = 0
        for item in qa_items:
            prompt = (
                f"\n#{item['id']} user={item['user_key']} text={_preview(item['text'], 120)}\n"
                f"Nuevo kind ({'/'.join(ALLOWED_RECLASSIFY)}/skip/delete): "
            )
            choice = input(prompt).strip().lower()
            if not choice or choice == "skip":
                continue
            if choice == "delete":
                if _confirm(f"¿Borrar #{item['id']}?"):
                    deleted += store.delete_memory_item_by_id(item_id=int(item["id"]), user_key=item["user_key"])
                continue
            if choice not in MemoryEngine.ALLOWED_KINDS:
                print("Valor no permitido. Se omite.")
                continue
            if _confirm(f"¿Reclasificar #{item['id']} a '{choice}'?"):
                current = store.get_memory_item(int(item["id"]))
                if current is None:
                    print("Item no encontrado; se omite.")
                    continue
                store.update_memory_item(
                    item_id=int(item["id"]),
                    kind=choice,
                    text=current["text"],
                    embedding_blob=current["embedding"],
                    meta_json=json.dumps(current["meta"], ensure_ascii=False),
                )
                changed += 1
        print(f"\nReclasificados: {changed}. Borrados: {deleted}.")
        return 0

    if not args.execute:
        print("\nDry-run: no se ha borrado nada. Usa --execute para aplicar el borrado.")
        return 0

    if not _confirm(f"Se van a borrar {len(qa_items)} items kind='qa'. ¿Continuar?"):
        print("Operación cancelada.")
        return 1

    deleted = 0
    for item in qa_items:
        deleted += store.delete_memory_item_by_id(item_id=int(item["id"]), user_key=item["user_key"])

    print(f"Borrados {deleted} items kind='qa'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
