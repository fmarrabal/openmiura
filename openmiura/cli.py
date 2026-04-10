from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import click
import httpx
import uvicorn

from openmiura import __version__
from openmiura.core.worker_runtime import build_worker_manager, resolve_worker_mode
from openmiura.infrastructure.persistence.db import DBConnection
from openmiura.core.migrations import apply_migrations, backup_database, downgrade_migrations, restore_database, schema_status
from openmiura.gateway import Gateway
from openmiura.core.config import load_settings
from openmiura.infrastructure.persistence.audit_store import AuditStore
from openmiura.extensions.sdk import ExtensionHarness, ExtensionRegistry, scaffold_project


@click.group(name="openmiura", help="openMiura CLI", invoke_without_command=False)
def app() -> None:
    pass


@app.group(name="db", help="Database maintenance commands.")
def db_app() -> None:
    pass


@app.group(name="memory", help="Memory maintenance commands.")
def memory_app() -> None:
    pass


@app.group(name="mcp", help="Model Context Protocol commands.")
def mcp_app() -> None:
    pass


@app.group(name="create", help="Scaffold extensions and workflow playbooks.")
def create_app() -> None:
    pass


@app.group(name="sdk", help="SDK helpers for validating and testing extensions.")
def sdk_app() -> None:
    pass


@app.group(name="registry", help="Private extension registry helpers.")
def registry_app() -> None:
    pass


class NamespaceLike(argparse.Namespace):
    pass


def _resolve_config_path(config: str | None) -> str:
    if config is not None:
        path = Path(config)
        if path.is_dir():
            return str(path / "openmiura.yaml")
        return str(path)
    env_value = os.environ.get("OPENMIURA_CONFIG")
    if env_value:
        return env_value
    return "configs/openmiura.yaml"


def _check_storage(*, backend: str, db_path: str, database_url: str) -> tuple[bool, str]:
    try:
        conn = DBConnection(backend=backend, db_path=db_path, database_url=database_url)
        conn.cursor().execute("SELECT 1")
        conn.close()
        if str(backend).strip().lower() == "postgresql":
            return True, f"PostgreSQL OK: {database_url}"
        return True, f"SQLite OK: {db_path}"
    except Exception as exc:
        label = "PostgreSQL" if str(backend).strip().lower() == "postgresql" else "SQLite"
        target = database_url if str(backend).strip().lower() == "postgresql" else db_path
        return False, f"{label} error for {target}: {exc!r}"


def _doctor_payload(config_path: str) -> tuple[dict[str, Any], int]:
    resolved_config = _resolve_config_path(config_path)
    payload: dict[str, Any] = {
        "ok": True,
        "version": __version__,
        "config_path": resolved_config,
        "checks": [],
    }
    exit_code = 0

    def add_check(name: str, ok: bool, detail: str, level: str = "info") -> None:
        nonlocal exit_code
        payload["checks"].append({"name": name, "ok": bool(ok), "level": level, "detail": detail})
        if not ok and level == "error":
            payload["ok"] = False
            exit_code = 1

    cfg_path = Path(resolved_config)
    if not cfg_path.exists():
        add_check("config_exists", False, f"Config file not found: {cfg_path}", "error")
        return payload, exit_code
    add_check("config_exists", True, f"Found config: {cfg_path}")

    try:
        gw = Gateway.from_config(str(cfg_path))
        add_check("gateway_init", True, "Gateway.from_config() succeeded")
    except Exception as exc:
        add_check("gateway_init", False, f"Gateway init failed: {exc!r}", "error")
        return payload, exit_code

    settings = gw.settings
    backend = str(getattr(settings.storage, "backend", "sqlite") or "sqlite").strip().lower()
    db_path = Path(settings.storage.db_path)
    ok_storage, storage_detail = _check_storage(backend=backend, db_path=settings.storage.db_path, database_url=getattr(settings.storage, "database_url", ""))
    add_check("storage", ok_storage, storage_detail, "error" if not ok_storage else "info")

    if backend == "sqlite":
        db_parent = db_path.parent
        storage_ok = db_parent.exists() and os.access(db_parent, os.W_OK)
        add_check(
            "storage_dir",
            storage_ok,
            f"Writable storage dir: {db_parent}" if storage_ok else f"Storage dir missing or not writable: {db_parent}",
            "error" if not storage_ok else "info",
        )
    else:
        add_check("storage_backend", True, f"Using backend {backend} with URL {getattr(settings.storage, 'database_url', '')}")

    sandbox_dir = Path(settings.tools.sandbox_dir if settings.tools else "data/sandbox")
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    sandbox_ok = sandbox_dir.exists() and os.access(sandbox_dir, os.W_OK)
    add_check(
        "sandbox_dir",
        sandbox_ok,
        f"Writable sandbox dir: {sandbox_dir}" if sandbox_ok else f"Sandbox dir missing or not writable: {sandbox_dir}",
        "error" if not sandbox_ok else "info",
    )

    channels: list[str] = []
    if settings.telegram and settings.telegram.bot_token:
        channels.append("telegram")
    if settings.slack and settings.slack.bot_token:
        channels.append("slack")
    if settings.discord and settings.discord.bot_token:
        channels.append("discord")
    add_check("channels", True, "Enabled channels: " + (", ".join(channels) if channels else "none"))
    add_check("admin", True, f"Admin endpoints {'enabled' if settings.admin and settings.admin.enabled else 'disabled'}")
    add_check("worker_mode", True, f"runtime.worker_mode={getattr(settings.runtime, 'worker_mode', 'external')}")

    memory_cfg = getattr(settings, "memory", None)
    if memory_cfg is not None:
        vault_cfg = getattr(memory_cfg, "vault", None)
        vault_enabled = bool(getattr(vault_cfg, "enabled", False))
        add_check("vault", True, f"ContextVault {'enabled' if vault_enabled else 'disabled'}")
        if vault_enabled:
            env_var = getattr(vault_cfg, "passphrase_env_var", "OPENMIURA_VAULT_PASSPHRASE")
            has_passphrase = bool(os.environ.get(env_var, ""))
            add_check(
                "vault_passphrase",
                has_passphrase,
                f"Passphrase env {'found' if has_passphrase else 'missing'}: {env_var}",
                "error" if not has_passphrase else "info",
            )

    mcp_cfg = getattr(settings, "mcp", None)
    if mcp_cfg is not None:
        add_check("mcp", True, f"MCP {'enabled' if mcp_cfg.enabled else 'disabled'} (SSE path {mcp_cfg.sse_path})")
        if mcp_cfg.enabled:
            try:
                import mcp  # type: ignore
                add_check("mcp_dependency", True, "Python package 'mcp' available")
            except Exception:
                add_check("mcp_dependency", False, "Python package 'mcp' not installed", "warning")

    broker_cfg = getattr(settings, "broker", None)
    if broker_cfg is not None:
        add_check(
            "http_broker",
            True,
            f"HTTP broker {'enabled' if broker_cfg.enabled else 'disabled'} at {broker_cfg.base_path}",
        )
        if broker_cfg.enabled and broker_cfg.token:
            add_check("http_broker_auth", True, "HTTP broker token configured")

    runtime_obj = getattr(gw, "runtime", None)
    skill_loader = getattr(runtime_obj, "skill_loader", None)
    if skill_loader is not None:
        catalog = skill_loader.catalog()
        add_check("skills", True, "Loaded skills: " + (", ".join(row["name"] for row in catalog) if catalog else "none"))
        if skill_loader.errors:
            add_check("skills_errors", True, f"Ignored invalid manifests: {len(skill_loader.errors)}", "warning")

    provider = str(settings.llm.provider or 'ollama').strip().lower()
    if provider == 'ollama':
        ollama_tags = settings.llm.base_url.rstrip('/') + '/api/tags'
        try:
            with httpx.Client(timeout=min(settings.llm.timeout_s, 5)) as client:
                response = client.get(ollama_tags)
                response.raise_for_status()
                data = response.json()
            add_check('ollama_http', True, f'Ollama reachable at {settings.llm.base_url}')
            models = [m.get('name') for m in (data.get('models') or []) if isinstance(m, dict)]
            llm_model = settings.llm.model
            embed_model = settings.memory.embed_model if settings.memory else None
            add_check(
                'ollama_model',
                llm_model in models if models else True,
                f"LLM model {'found' if llm_model in models else 'not verified'}: {llm_model}",
                'warning' if models and llm_model not in models else 'info',
            )
            if embed_model:
                add_check(
                    'ollama_embed_model',
                    embed_model in models if models else True,
                    f"Embed model {'found' if embed_model in models else 'not verified'}: {embed_model}",
                    'warning' if models and embed_model not in models else 'info',
                )
        except Exception as exc:
            add_check('ollama_http', True, f'Ollama not reachable now ({exc!r}); config still parsed correctly', 'warning')
    elif provider in {'openai', 'kimi', 'anthropic'}:
        key_var = settings.llm.api_key_env_var or ''
        has_key = bool(key_var and os.environ.get(key_var, '').strip())
        add_check('llm_api_key', has_key, f"API key env {'found' if has_key else 'missing'}: {key_var or '(not configured)'}", 'error' if not has_key else 'info')
        add_check('llm_provider', True, f'Provider {provider} configured at {settings.llm.base_url}')
        if settings.memory:
            add_check('memory_embed_base', True, f"Embedding backend: {settings.memory.embed_base_url} / {settings.memory.embed_model}")

    payload["summary"] = {
        "storage_backend": backend,
        "db_path": str(db_path),
        "database_url": getattr(settings.storage, "database_url", ""),
        "sandbox_dir": str(sandbox_dir),
        "llm_provider": settings.llm.provider,
        "llm_model": settings.llm.model,
        "embed_model": settings.memory.embed_model if settings.memory else None,
        "history_limit": settings.runtime.history_limit,
        "pending_confirmation_ttl_s": getattr(settings.runtime, "pending_confirmation_ttl_s", None),
        "skills_path": getattr(settings, "skills_path", "skills"),
        "skills_loaded": [row["name"] for row in getattr(getattr(getattr(gw, "runtime", None), "skill_loader", None), "catalog", lambda: [])()],
        "vault_enabled": bool(getattr(getattr(settings, "memory", None), "vault", None) and settings.memory.vault.enabled),
        "mcp_enabled": bool(getattr(settings, "mcp", None) and settings.mcp.enabled),
        "broker_enabled": bool(getattr(settings, "broker", None) and settings.broker.enabled),
        "broker_base_path": getattr(getattr(settings, "broker", None), "base_path", None),
    }
    return payload, exit_code


def run_cli(*, config: str | None, host: str | None, port: int | None, reload: bool, log_level: str, with_workers: bool = False) -> int:
    config_path = _resolve_config_path(config)
    os.environ["OPENMIURA_CONFIG"] = config_path

    gw = None
    resolved_host = host
    resolved_port = port
    if resolved_host is None or resolved_port is None or with_workers:
        gw = Gateway.from_config(config_path)
        resolved_host = resolved_host or gw.settings.server.host
        resolved_port = resolved_port or gw.settings.server.port

    mode = "external"
    if gw is not None:
        mode = resolve_worker_mode(with_workers=with_workers, settings=gw.settings)

    uvicorn_kwargs = {
        "host": resolved_host,
        "port": resolved_port,
        "reload": bool(reload),
        "log_level": str(log_level),
    }

    if gw is not None and mode == "inline":
        with build_worker_manager(settings=gw.settings, config_path=config_path):
            uvicorn.run("app:app", **uvicorn_kwargs)
        return 0

    uvicorn.run("app:app", **uvicorn_kwargs)
    return 0


def doctor_cli(*, config: str | None, json_output: bool = False) -> int:
    payload, exit_code = _doctor_payload(_resolve_config_path(config))
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return exit_code

    print(f"openMiura doctor v{payload['version']}")
    print(f"config: {payload['config_path']}")
    for check in payload["checks"]:
        icon = "OK" if check["ok"] and check["level"] != "warning" else "WARN"
        if not check["ok"]:
            icon = "ERR"
        elif check["level"] == "warning":
            icon = "WARN"
        print(f"[{icon}] {check['name']}: {check['detail']}")
    if payload.get("summary"):
        print("summary:")
        for key, value in payload["summary"].items():
            print(f"  - {key}: {value}")
    return exit_code


def db_check_cli(*, db: str | None = None, json_output: bool = False) -> int:
    from scripts.check_db import run as run_check_db

    argv: list[str] = []
    if db:
        argv.extend(["--db", db])
    if json_output:
        argv.append("--json")
    return int(run_check_db(argv))


def db_clean_cli(*, db: str | None = None, execute: bool = False, reclassify: bool = False) -> int:
    from scripts.memory_clean import run as run_memory_clean

    argv: list[str] = []
    if db:
        argv.extend(["--db", db])
    if execute:
        argv.append("--execute")
    if reclassify:
        argv.append("--reclassify")
    return int(run_memory_clean(argv))


def db_migrate_cli(*, config: str | None = None, json_output: bool = False) -> int:
    settings = load_settings(_resolve_config_path(config))
    store = AuditStore(db_path=settings.storage.db_path, backend=settings.storage.backend, database_url=settings.storage.database_url)
    applied = apply_migrations(store._conn)
    payload = {"ok": True, "applied": applied, **schema_status(store._conn)}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if json_output else json.dumps(payload, ensure_ascii=False))
    return 0




def db_rollback_cli(*, config: str | None = None, to_version: int | None = None, steps: int | None = None, json_output: bool = False) -> int:
    settings = load_settings(_resolve_config_path(config))
    store = AuditStore(db_path=settings.storage.db_path, backend=settings.storage.backend, database_url=settings.storage.database_url)
    rolled_back = downgrade_migrations(store._conn, target_version=to_version, steps=steps)
    payload = {"ok": True, "rolled_back": rolled_back, **schema_status(store._conn)}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if json_output else json.dumps(payload, ensure_ascii=False))
    return 0

def db_version_cli(*, config: str | None = None, json_output: bool = False) -> int:
    settings = load_settings(_resolve_config_path(config))
    store = AuditStore(db_path=settings.storage.db_path, backend=settings.storage.backend, database_url=settings.storage.database_url)
    payload = schema_status(store._conn)
    print(json.dumps(payload, ensure_ascii=False, indent=2) if json_output else str(payload["current_version"]))
    return 0


def db_backup_cli(*, config: str | None = None, json_output: bool = False) -> int:
    settings = load_settings(_resolve_config_path(config))
    payload = backup_database(backend=settings.storage.backend, db_path=settings.storage.db_path, database_url=settings.storage.database_url, backup_dir=settings.storage.backup_dir)
    payload["ok"] = True
    print(json.dumps(payload, ensure_ascii=False, indent=2) if json_output else json.dumps(payload, ensure_ascii=False))
    return 0


def db_restore_cli(*, config: str | None = None, backup: str, json_output: bool = False) -> int:
    settings = load_settings(_resolve_config_path(config))
    payload = restore_database(backend=settings.storage.backend, db_path=settings.storage.db_path, database_url=settings.storage.database_url, backup_path=backup)
    payload["ok"] = True
    print(json.dumps(payload, ensure_ascii=False, indent=2) if json_output else json.dumps(payload, ensure_ascii=False))
    return 0


def memory_consolidate_cli(*, config: str | None = None, user_key: str | None = None, json_output: bool = False) -> int:
    gw = Gateway.from_config(_resolve_config_path(config))
    if gw.memory is None:
        payload = {"ok": False, "error": "memory_disabled"}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if json_output else "Memory engine disabled")
        return 1
    result = gw.memory.consolidate(user_key=user_key)
    payload = {"ok": True, "user_key": user_key, **result}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def mcp_stdio_cli(*, config: str | None = None) -> int:
    from openmiura.channels.mcp_server import run_stdio

    return int(run_stdio(_resolve_config_path(config)))


def mcp_sse_cli(*, config: str | None = None) -> int:
    from openmiura.channels.mcp_server import run_sse

    return int(run_sse(_resolve_config_path(config)))


def scaffold_cli(*, kind: str, name: str, output_dir: str | None = None, author: str = "OpenMiura", force: bool = False, json_output: bool = False) -> int:
    result = scaffold_project(kind=kind, name=name, output_dir=output_dir or ".", author=author, force=force)
    payload = {"ok": True, **result.to_dict()}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def sdk_validate_manifest_cli(*, path: str, json_output: bool = False) -> int:
    report = ExtensionHarness().validate_manifest(path)
    payload = report.to_dict()
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0 if report.ok else 1


def sdk_test_extension_cli(*, path: str, json_output: bool = False) -> int:
    report = ExtensionHarness().run(path)
    payload = report.to_dict()
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0 if report.ok else 1

def sdk_quickstart_cli(*, kind: str | None = None, json_output: bool = False) -> int:
    resolved_kind = str(kind or "tool").strip().lower() or "tool"
    lines = [
        "openMiura SDK quickstart",
        "",
        f"1. Create scaffold: openmiura create {resolved_kind if resolved_kind != 'llm_provider' else 'provider'} my-extension",
        "2. Validate manifest: openmiura sdk validate-manifest ./my-extension/manifest.yaml",
        "3. Run contract harness: openmiura sdk test-extension ./my-extension",
        "4. Publish to registry: openmiura registry publish ./my-extension --root ./registry --namespace demo",
        "5. Start and approve review: openmiura registry review-start my-extension 0.1.0 --root ./registry --namespace demo",
        "6. Verify signed package: openmiura registry verify my-extension 0.1.0 --root ./registry --namespace demo",
        "7. Apply tenant policy: openmiura registry policy-set demo --root ./registry --allowed-namespace demo",
        "8. Install with policy enforcement: openmiura registry install my-extension --root ./registry --namespace demo --tenant demo",
    ]
    if json_output:
        print(json.dumps({"ok": True, "kind": resolved_kind, "steps": lines}, ensure_ascii=False, indent=2))
    else:
        print("\n".join(lines))
    return 0


def registry_init_cli(*, root: str = "extensions_registry", json_output: bool = False) -> int:
    payload = ExtensionRegistry(root=root).init()
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0

def registry_keygen_cli(*, root: str = "extensions_registry", key_id: str = "default", rotate: bool = False, json_output: bool = False) -> int:
    payload = ExtensionRegistry(root=root).generate_signing_key(key_id=key_id, overwrite=rotate)
    payload = {"ok": True, **payload}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def registry_policy_set_cli(*, tenant_id: str, root: str = "extensions_registry", allowed_namespaces: list[str] | tuple[str, ...] = (), allowed_kinds: list[str] | tuple[str, ...] = (), allowed_extensions: list[str] | tuple[str, ...] = (), blocked_extensions: list[str] | tuple[str, ...] = (), allowed_submitters: list[str] | tuple[str, ...] = (), allowed_statuses: list[str] | tuple[str, ...] = ("approved",), min_approvals: int = 1, require_signature: bool = True, require_approved: bool = True, require_compatibility: bool = True, json_output: bool = False) -> int:
    payload = ExtensionRegistry(root=root).set_install_policy(
        tenant_id,
        {
            "allowed_namespaces": list(allowed_namespaces),
            "allowed_kinds": list(allowed_kinds),
            "allowed_extensions": list(allowed_extensions),
            "blocked_extensions": list(blocked_extensions),
            "allowed_submitters": list(allowed_submitters),
            "allowed_statuses": list(allowed_statuses),
            "min_required_approvals": min_approvals,
            "require_signature": require_signature,
            "require_approved": require_approved,
            "require_compatibility": require_compatibility,
        },
    )
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def registry_policy_show_cli(*, tenant_id: str, root: str = "extensions_registry", json_output: bool = False) -> int:
    payload = ExtensionRegistry(root=root).get_install_policy(tenant_id)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def registry_policy_explain_cli(*, name: str, version: str | None = None, root: str = "extensions_registry", namespace: str = "global", tenant_id: str | None = None, workspace_id: str | None = None, allow_pending: bool = False, json_output: bool = False) -> int:
    payload = ExtensionRegistry(root=root).explain_install_policy(name, version=version, namespace=namespace, tenant_id=tenant_id, workspace_id=workspace_id, require_approved=not allow_pending)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


def registry_publish_cli(*, path: str, root: str = "extensions_registry", namespace: str = "global", submitted_by: str = "OpenMiura", force: bool = False, signer_key_id: str = "default", json_output: bool = False) -> int:
    entry = ExtensionRegistry(root=root).publish(path, namespace=namespace, submitted_by=submitted_by, overwrite=force, signer_key_id=signer_key_id)
    payload = {"ok": True, "entry": entry.to_dict()}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def registry_list_cli(*, root: str = "extensions_registry", namespace: str | None = None, status: str | None = None, kind: str | None = None, json_output: bool = False) -> int:
    entries = [entry.to_dict() for entry in ExtensionRegistry(root=root).list(namespace=namespace, status=status, kind=kind)]
    payload = {"ok": True, "entries": entries}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def registry_approve_cli(*, name: str, version: str, root: str = "extensions_registry", namespace: str = "global", reviewer: str = "OpenMiura", note: str | None = None, json_output: bool = False) -> int:
    entry = ExtensionRegistry(root=root).approve(name, version, namespace=namespace, reviewer=reviewer, note=note)
    payload = {"ok": True, "entry": entry.to_dict()}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def registry_review_start_cli(*, name: str, version: str, root: str = "extensions_registry", namespace: str = "global", reviewer: str = "OpenMiura", note: str | None = None, json_output: bool = False) -> int:
    entry = ExtensionRegistry(root=root).start_review(name, version, namespace=namespace, reviewer=reviewer, note=note)
    payload = {"ok": True, "entry": entry.to_dict()}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def registry_reject_cli(*, name: str, version: str, root: str = "extensions_registry", namespace: str = "global", reviewer: str = "OpenMiura", note: str | None = None, json_output: bool = False) -> int:
    entry = ExtensionRegistry(root=root).reject(name, version, namespace=namespace, reviewer=reviewer, note=note)
    payload = {"ok": True, "entry": entry.to_dict()}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def registry_describe_cli(*, name: str, version: str, root: str = "extensions_registry", namespace: str = "global", json_output: bool = False) -> int:
    entry = ExtensionRegistry(root=root).describe(name, version, namespace=namespace)
    payload = {"ok": True, "entry": entry.to_dict()}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def registry_verify_cli(*, name: str, version: str, root: str = "extensions_registry", namespace: str = "global", json_output: bool = False) -> int:
    payload = ExtensionRegistry(root=root).verify(name, version, namespace=namespace)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


def registry_deprecate_cli(*, name: str, version: str, root: str = "extensions_registry", namespace: str = "global", reviewer: str = "OpenMiura", note: str | None = None, json_output: bool = False) -> int:
    entry = ExtensionRegistry(root=root).deprecate(name, version, namespace=namespace, reviewer=reviewer, note=note)
    payload = {"ok": True, "entry": entry.to_dict()}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def registry_install_cli(*, name: str, version: str | None = None, root: str = "extensions_registry", namespace: str = "global", destination: str = "extensions_installed", tenant_id: str | None = None, workspace_id: str | None = None, allow_pending: bool = False, json_output: bool = False) -> int:
    payload = ExtensionRegistry(root=root).install(name, version=version, namespace=namespace, destination=destination, require_approved=not allow_pending, tenant_id=tenant_id, workspace_id=workspace_id)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


# Compatibility wrappers used by the existing test suite

def cmd_run(args: argparse.Namespace) -> int:
    return run_cli(
        config=getattr(args, "config", None),
        host=getattr(args, "host", None),
        port=getattr(args, "port", None),
        reload=bool(getattr(args, "reload", False)),
        log_level=str(getattr(args, "log_level", "info")),
        with_workers=bool(getattr(args, "with_workers", False)),
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    return doctor_cli(config=getattr(args, "config", None), json_output=bool(getattr(args, "json", False)))


def cmd_db_check(args: argparse.Namespace) -> int:
    return db_check_cli(db=getattr(args, "db", None), json_output=bool(getattr(args, "json", False)))


def cmd_db_clean(args: argparse.Namespace) -> int:
    return db_clean_cli(db=getattr(args, "db", None), execute=bool(getattr(args, "execute", False)), reclassify=bool(getattr(args, "reclassify", False)))


def cmd_db_migrate(args: argparse.Namespace) -> int:
    return db_migrate_cli(config=getattr(args, "config", None), json_output=bool(getattr(args, "json", False)))


def cmd_db_version(args: argparse.Namespace) -> int:
    return db_version_cli(config=getattr(args, "config", None), json_output=bool(getattr(args, "json", False)))


def cmd_db_rollback(args: argparse.Namespace) -> int:
    return db_rollback_cli(config=getattr(args, "config", None), to_version=getattr(args, "to_version", None), steps=getattr(args, "steps", None), json_output=bool(getattr(args, "json", False)))


def cmd_db_backup(args: argparse.Namespace) -> int:
    return db_backup_cli(config=getattr(args, "config", None), json_output=bool(getattr(args, "json", False)))


def cmd_db_restore(args: argparse.Namespace) -> int:
    return db_restore_cli(config=getattr(args, "config", None), backup=str(getattr(args, "backup")), json_output=bool(getattr(args, "json", False)))


def cmd_scaffold(args: argparse.Namespace) -> int:
    return scaffold_cli(
        kind=str(getattr(args, "kind")),
        name=str(getattr(args, "name")),
        output_dir=getattr(args, "output_dir", None),
        author=str(getattr(args, "author", "OpenMiura")),
        force=bool(getattr(args, "force", False)),
        json_output=bool(getattr(args, "json", False)),
    )


def cmd_sdk_validate_manifest(args: argparse.Namespace) -> int:
    return sdk_validate_manifest_cli(path=str(getattr(args, "path")), json_output=bool(getattr(args, "json", False)))


def cmd_sdk_test_extension(args: argparse.Namespace) -> int:
    return sdk_test_extension_cli(path=str(getattr(args, "path")), json_output=bool(getattr(args, "json", False)))


def cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
    return 0


build_parser = None


@app.command("run")
@click.option("--config", type=str, default=None, help="Path to YAML config or config directory.")
@click.option("--host", type=str, default=None, help="Override bind host.")
@click.option("--port", type=int, default=None, help="Override bind port.")
@click.option("--reload", is_flag=True, default=False, help="Enable Uvicorn reload.")
@click.option("--log-level", type=str, default="info", show_default=True, help="Uvicorn log level.")
@click.option("--with-workers", is_flag=True, default=False, help="Spawn supported inline workers.")
def run_command(config: str | None, host: str | None, port: int | None, reload: bool, log_level: str, with_workers: bool) -> None:
    raise click.exceptions.Exit(run_cli(config=config, host=host, port=port, reload=reload, log_level=log_level, with_workers=with_workers))


@app.command("doctor")
@click.option("--config", type=str, default=None, help="Path to YAML config or config directory.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def doctor_command(config: str | None, json_output: bool) -> None:
    raise click.exceptions.Exit(doctor_cli(config=config, json_output=json_output))


@db_app.command("check")
@click.option("--db", type=str, default=None, help="Path to the SQLite database.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def db_check_command(db: str | None, json_output: bool) -> None:
    raise click.exceptions.Exit(db_check_cli(db=db, json_output=json_output))


@db_app.command("clean")
@click.option("--db", type=str, default=None, help="Path to the SQLite database.")
@click.option("--execute", is_flag=True, default=False, help="Delete qa items instead of dry-run.")
@click.option("--reclassify", is_flag=True, default=False, help="Interactive reclassification mode.")
def db_clean_command(db: str | None, execute: bool, reclassify: bool) -> None:
    raise click.exceptions.Exit(db_clean_cli(db=db, execute=execute, reclassify=reclassify))


@db_app.command("migrate")
@click.option("--config", type=str, default=None, help="Path to YAML config or config directory.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def db_migrate_command(config: str | None, json_output: bool) -> None:
    raise click.exceptions.Exit(db_migrate_cli(config=config, json_output=json_output))


@db_app.command("version")
@click.option("--config", type=str, default=None, help="Path to YAML config or config directory.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def db_version_command(config: str | None, json_output: bool) -> None:
    raise click.exceptions.Exit(db_version_cli(config=config, json_output=json_output))


@db_app.command("rollback")
@click.option("--config", type=str, default=None, help="Path to YAML config or config directory.")
@click.option("--to-version", type=int, default=None, help="Target schema version to downgrade to.")
@click.option("--steps", type=int, default=None, help="Number of migration steps to roll back.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def db_rollback_command(config: str | None, to_version: int | None, steps: int | None, json_output: bool) -> None:
    raise click.exceptions.Exit(db_rollback_cli(config=config, to_version=to_version, steps=steps, json_output=json_output))


@db_app.command("backup")
@click.option("--config", type=str, default=None, help="Path to YAML config or config directory.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def db_backup_command(config: str | None, json_output: bool) -> None:
    raise click.exceptions.Exit(db_backup_cli(config=config, json_output=json_output))


@db_app.command("restore")
@click.option("--config", type=str, default=None, help="Path to YAML config or config directory.")
@click.option("--backup", required=True, type=str, help="Path to backup file.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def db_restore_command(config: str | None, backup: str, json_output: bool) -> None:
    raise click.exceptions.Exit(db_restore_cli(config=config, backup=backup, json_output=json_output))


@memory_app.command("consolidate")
@click.option("--config", type=str, default=None, help="Path to YAML config or config directory.")
@click.option("--user-key", type=str, default=None, help="Restrict consolidation to one user key.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def memory_consolidate_command(config: str | None, user_key: str | None, json_output: bool) -> None:
    raise click.exceptions.Exit(memory_consolidate_cli(config=config, user_key=user_key, json_output=json_output))


@mcp_app.command("stdio")
@click.option("--config", type=str, default=None, help="Path to YAML config or config directory.")
def mcp_stdio_command(config: str | None) -> None:
    raise click.exceptions.Exit(mcp_stdio_cli(config=config))


@mcp_app.command("sse")
@click.option("--config", type=str, default=None, help="Path to YAML config or config directory.")
def mcp_sse_command(config: str | None) -> None:
    raise click.exceptions.Exit(mcp_sse_cli(config=config))


@create_app.command("tool")
@click.argument("name", type=str)
@click.option("--output-dir", type=str, default=".", show_default=True, help="Destination directory.")
@click.option("--author", type=str, default="OpenMiura", show_default=True, help="Author value for the manifest.")
@click.option("--force", is_flag=True, default=False, help="Allow overwriting an existing destination.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def create_tool_command(name: str, output_dir: str, author: str, force: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(scaffold_cli(kind="tool", name=name, output_dir=output_dir, author=author, force=force, json_output=json_output))


@create_app.command("skill")
@click.argument("name", type=str)
@click.option("--output-dir", type=str, default=".", show_default=True, help="Destination directory.")
@click.option("--author", type=str, default="OpenMiura", show_default=True, help="Author value for the manifest.")
@click.option("--force", is_flag=True, default=False, help="Allow overwriting an existing destination.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def create_skill_command(name: str, output_dir: str, author: str, force: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(scaffold_cli(kind="skill", name=name, output_dir=output_dir, author=author, force=force, json_output=json_output))


@create_app.command("provider")
@click.argument("name", type=str)
@click.option("--output-dir", type=str, default=".", show_default=True, help="Destination directory.")
@click.option("--author", type=str, default="OpenMiura", show_default=True, help="Author value for the manifest.")
@click.option("--force", is_flag=True, default=False, help="Allow overwriting an existing destination.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def create_provider_command(name: str, output_dir: str, author: str, force: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(scaffold_cli(kind="provider", name=name, output_dir=output_dir, author=author, force=force, json_output=json_output))


@create_app.command("channel")
@click.argument("name", type=str)
@click.option("--output-dir", type=str, default=".", show_default=True, help="Destination directory.")
@click.option("--author", type=str, default="OpenMiura", show_default=True, help="Author value for the manifest.")
@click.option("--force", is_flag=True, default=False, help="Allow overwriting an existing destination.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def create_channel_command(name: str, output_dir: str, author: str, force: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(scaffold_cli(kind="channel", name=name, output_dir=output_dir, author=author, force=force, json_output=json_output))


@create_app.command("workflow")
@click.argument("name", type=str)
@click.option("--output-dir", type=str, default=".", show_default=True, help="Destination directory.")
@click.option("--author", type=str, default="OpenMiura", show_default=True, help="Reserved for future metadata parity.")
@click.option("--force", is_flag=True, default=False, help="Allow overwriting an existing destination.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def create_workflow_command(name: str, output_dir: str, author: str, force: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(scaffold_cli(kind="workflow", name=name, output_dir=output_dir, author=author, force=force, json_output=json_output))


@create_app.command("auth")
@click.argument("name", type=str)
@click.option("--output-dir", type=str, default=".", show_default=True, help="Destination directory.")
@click.option("--author", type=str, default="OpenMiura", show_default=True, help="Author value for the manifest.")
@click.option("--force", is_flag=True, default=False, help="Allow overwriting an existing destination.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def create_auth_command(name: str, output_dir: str, author: str, force: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(scaffold_cli(kind="auth", name=name, output_dir=output_dir, author=author, force=force, json_output=json_output))


@create_app.command("storage")
@click.argument("name", type=str)
@click.option("--output-dir", type=str, default=".", show_default=True, help="Destination directory.")
@click.option("--author", type=str, default="OpenMiura", show_default=True, help="Author value for the manifest.")
@click.option("--force", is_flag=True, default=False, help="Allow overwriting an existing destination.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def create_storage_command(name: str, output_dir: str, author: str, force: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(scaffold_cli(kind="storage", name=name, output_dir=output_dir, author=author, force=force, json_output=json_output))


@sdk_app.command("validate-manifest")
@click.argument("path", type=str)
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def sdk_validate_manifest_command(path: str, json_output: bool) -> None:
    raise click.exceptions.Exit(sdk_validate_manifest_cli(path=path, json_output=json_output))


@sdk_app.command("test-extension")
@click.argument("path", type=str)
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def sdk_test_extension_command(path: str, json_output: bool) -> None:
    raise click.exceptions.Exit(sdk_test_extension_cli(path=path, json_output=json_output))

@sdk_app.command("quickstart")
@click.option("--kind", type=str, default="tool", show_default=True, help="Extension kind to illustrate.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def sdk_quickstart_command(kind: str, json_output: bool) -> None:
    raise click.exceptions.Exit(sdk_quickstart_cli(kind=kind, json_output=json_output))


@registry_app.command("init")
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_init_command(root: str, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_init_cli(root=root, json_output=json_output))

@registry_app.command("keygen")
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--key-id", type=str, default="default", show_default=True, help="Signing key identifier.")
@click.option("--rotate", is_flag=True, default=False, help="Rotate an existing key identifier.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_keygen_command(root: str, key_id: str, rotate: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_keygen_cli(root=root, key_id=key_id, rotate=rotate, json_output=json_output))


@registry_app.command("publish")
@click.argument("path", type=str)
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--namespace", type=str, default="global", show_default=True, help="Registry namespace / tenant.")
@click.option("--submitted-by", type=str, default="OpenMiura", show_default=True, help="Submitter identity for the publication.")
@click.option("--signer-key-id", type=str, default="default", show_default=True, help="Signing key used for publication integrity.")
@click.option("--force", is_flag=True, default=False, help="Allow overwriting an existing registry version.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_publish_command(path: str, root: str, namespace: str, submitted_by: str, signer_key_id: str, force: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_publish_cli(path=path, root=root, namespace=namespace, submitted_by=submitted_by, force=force, signer_key_id=signer_key_id, json_output=json_output))


@registry_app.command("list")
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--namespace", type=str, default=None, help="Restrict to one registry namespace / tenant.")
@click.option("--status", type=str, default=None, help="Filter by publication status.")
@click.option("--kind", type=str, default=None, help="Filter by extension kind.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_list_command(root: str, namespace: str | None, status: str | None, kind: str | None, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_list_cli(root=root, namespace=namespace, status=status, kind=kind, json_output=json_output))


@registry_app.command("policy-set")
@click.argument("tenant_id", type=str)
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--allowed-namespace", "allowed_namespaces", type=str, multiple=True, help="Allowed source namespaces for this tenant.")
@click.option("--allowed-kind", "allowed_kinds", type=str, multiple=True, help="Allowed extension kinds for this tenant.")
@click.option("--allowed-extension", "allowed_extensions", type=str, multiple=True, help="Optional extension allowlist.")
@click.option("--blocked-extension", "blocked_extensions", type=str, multiple=True, help="Optional extension denylist.")
@click.option("--allowed-submitter", "allowed_submitters", type=str, multiple=True, help="Optional submitter allowlist.")
@click.option("--allowed-status", "allowed_statuses", type=str, multiple=True, default=("approved",), show_default=True, help="Allowed registry statuses.")
@click.option("--min-approvals", type=int, default=1, show_default=True, help="Minimum number of distinct approvals required.")
@click.option("--require-signature/--no-require-signature", default=True, show_default=True, help="Require a valid package signature.")
@click.option("--require-approved/--no-require-approved", default=True, show_default=True, help="Require approved status in addition to allowed statuses.")
@click.option("--require-compatibility/--no-require-compatibility", default=True, show_default=True, help="Require compatibility checks to pass.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_policy_set_command(tenant_id: str, root: str, allowed_namespaces: tuple[str, ...], allowed_kinds: tuple[str, ...], allowed_extensions: tuple[str, ...], blocked_extensions: tuple[str, ...], allowed_submitters: tuple[str, ...], allowed_statuses: tuple[str, ...], min_approvals: int, require_signature: bool, require_approved: bool, require_compatibility: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_policy_set_cli(tenant_id=tenant_id, root=root, allowed_namespaces=list(allowed_namespaces), allowed_kinds=list(allowed_kinds), allowed_extensions=list(allowed_extensions), blocked_extensions=list(blocked_extensions), allowed_submitters=list(allowed_submitters), allowed_statuses=list(allowed_statuses), min_approvals=min_approvals, require_signature=require_signature, require_approved=require_approved, require_compatibility=require_compatibility, json_output=json_output))


@registry_app.command("policy-show")
@click.argument("tenant_id", type=str)
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_policy_show_command(tenant_id: str, root: str, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_policy_show_cli(tenant_id=tenant_id, root=root, json_output=json_output))


@registry_app.command("policy-explain")
@click.argument("name", type=str)
@click.option("--version", type=str, default=None, help="Specific version to evaluate. Defaults to latest.")
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--namespace", type=str, default="global", show_default=True, help="Registry namespace / tenant.")
@click.option("--tenant", "tenant_id", type=str, default=None, help="Consuming tenant receiving the extension.")
@click.option("--workspace", "workspace_id", type=str, default=None, help="Optional consuming workspace identifier.")
@click.option("--allow-pending", is_flag=True, default=False, help="Allow non-approved entries when not blocked by tenant policy.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_policy_explain_command(name: str, version: str | None, root: str, namespace: str, tenant_id: str | None, workspace_id: str | None, allow_pending: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_policy_explain_cli(name=name, version=version, root=root, namespace=namespace, tenant_id=tenant_id, workspace_id=workspace_id, allow_pending=allow_pending, json_output=json_output))


@registry_app.command("approve")
@click.argument("name", type=str)
@click.argument("version", type=str)
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--namespace", type=str, default="global", show_default=True, help="Registry namespace / tenant.")
@click.option("--reviewer", type=str, default="OpenMiura", show_default=True, help="Reviewer identity.")
@click.option("--note", type=str, default=None, help="Approval note.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_approve_command(name: str, version: str, root: str, namespace: str, reviewer: str, note: str | None, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_approve_cli(name=name, version=version, root=root, namespace=namespace, reviewer=reviewer, note=note, json_output=json_output))


@registry_app.command("review-start")
@click.argument("name", type=str)
@click.argument("version", type=str)
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--namespace", type=str, default="global", show_default=True, help="Registry namespace / tenant.")
@click.option("--reviewer", type=str, default="OpenMiura", show_default=True, help="Reviewer identity.")
@click.option("--note", type=str, default=None, help="Review-start note.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_review_start_command(name: str, version: str, root: str, namespace: str, reviewer: str, note: str | None, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_review_start_cli(name=name, version=version, root=root, namespace=namespace, reviewer=reviewer, note=note, json_output=json_output))


@registry_app.command("reject")
@click.argument("name", type=str)
@click.argument("version", type=str)
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--namespace", type=str, default="global", show_default=True, help="Registry namespace / tenant.")
@click.option("--reviewer", type=str, default="OpenMiura", show_default=True, help="Reviewer identity.")
@click.option("--note", type=str, default=None, help="Rejection note.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_reject_command(name: str, version: str, root: str, namespace: str, reviewer: str, note: str | None, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_reject_cli(name=name, version=version, root=root, namespace=namespace, reviewer=reviewer, note=note, json_output=json_output))


@registry_app.command("describe")
@click.argument("name", type=str)
@click.argument("version", type=str)
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--namespace", type=str, default="global", show_default=True, help="Registry namespace / tenant.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_describe_command(name: str, version: str, root: str, namespace: str, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_describe_cli(name=name, version=version, root=root, namespace=namespace, json_output=json_output))


@registry_app.command("verify")
@click.argument("name", type=str)
@click.argument("version", type=str)
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--namespace", type=str, default="global", show_default=True, help="Registry namespace / tenant.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_verify_command(name: str, version: str, root: str, namespace: str, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_verify_cli(name=name, version=version, root=root, namespace=namespace, json_output=json_output))


@registry_app.command("deprecate")
@click.argument("name", type=str)
@click.argument("version", type=str)
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--namespace", type=str, default="global", show_default=True, help="Registry namespace / tenant.")
@click.option("--reviewer", type=str, default="OpenMiura", show_default=True, help="Reviewer identity.")
@click.option("--note", type=str, default=None, help="Deprecation note.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_deprecate_command(name: str, version: str, root: str, namespace: str, reviewer: str, note: str | None, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_deprecate_cli(name=name, version=version, root=root, namespace=namespace, reviewer=reviewer, note=note, json_output=json_output))


@registry_app.command("install")
@click.argument("name", type=str)
@click.option("--version", type=str, default=None, help="Specific version to install. Defaults to latest.")
@click.option("--root", type=str, default="extensions_registry", show_default=True, help="Registry root directory.")
@click.option("--namespace", type=str, default="global", show_default=True, help="Registry namespace / tenant.")
@click.option("--tenant", "tenant_id", type=str, default=None, help="Consuming tenant receiving the extension.")
@click.option("--workspace", "workspace_id", type=str, default=None, help="Optional consuming workspace identifier.")
@click.option("--destination", type=str, default="extensions_installed", show_default=True, help="Installation destination.")
@click.option("--allow-pending", is_flag=True, default=False, help="Allow installation of non-approved entries.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON output.")
def registry_install_command(name: str, version: str | None, root: str, namespace: str, tenant_id: str | None, workspace_id: str | None, destination: str, allow_pending: bool, json_output: bool) -> None:
    raise click.exceptions.Exit(registry_install_cli(name=name, version=version, root=root, namespace=namespace, destination=destination, tenant_id=tenant_id, workspace_id=workspace_id, allow_pending=allow_pending, json_output=json_output))


@app.command("version")
def version_command() -> None:
    click.echo(__version__)


def main(argv: list[str] | None = None) -> int:
    try:
        app.main(args=argv, prog_name="openmiura", standalone_mode=False)
        return 0
    except click.exceptions.Exit as exc:
        return int(exc.exit_code or 0)
