from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import hashlib
import hmac
import json
import secrets
import shutil

from .harness import ExtensionHarness
from .manifests import ExtensionManifest
from .version import detect_version_bump, evaluate_extension_compatibility, semver_key

_IGNORE_NAMES = {"__pycache__", ".pytest_cache", ".git", ".mypy_cache"}
_IGNORE_SUFFIXES = {".pyc", ".pyo"}
_DEFAULT_SIGNING_KEY_ID = "default"


@dataclass(slots=True)
class RegistryEntry:
    namespace: str
    name: str
    version: str
    kind: str
    status: str
    manifest: dict[str, Any]
    package_dir: str
    checksum: str
    created_at: str
    submitted_by: str = "OpenMiura"
    reviewer: str | None = None
    review_note: str | None = None
    review_history: list[dict[str, Any]] = field(default_factory=list)
    harness_report: dict[str, Any] | None = None
    compatibility: dict[str, Any] = field(default_factory=dict)
    release_level: str = "initial"
    signature: str | None = None
    signature_algorithm: str = "hmac-sha256"
    signer_key_id: str | None = None
    manifest_checksum: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TenantInstallPolicy:
    tenant_id: str
    allowed_namespaces: list[str] = field(default_factory=list)
    allowed_kinds: list[str] = field(default_factory=list)
    allowed_extensions: list[str] = field(default_factory=list)
    blocked_extensions: list[str] = field(default_factory=list)
    allowed_submitters: list[str] = field(default_factory=list)
    allowed_statuses: list[str] = field(default_factory=lambda: ["approved"])
    require_approved: bool = True
    require_signature: bool = True
    min_required_approvals: int = 1
    require_compatibility: bool = True

    @classmethod
    def from_mapping(cls, tenant_id: str, raw: dict[str, Any] | None) -> "TenantInstallPolicy":
        data = dict(raw or {})

        def _items(value: Any) -> list[str]:
            if not value:
                return []
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list):
                raise ValueError(f"Tenant install policy field must be a list of strings for tenant '{tenant_id}'")
            return [str(item).strip() for item in value if str(item).strip()]

        min_required_approvals = data.get("min_required_approvals", 1)
        try:
            min_required_approvals = max(0, int(min_required_approvals))
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError(f"Tenant install policy min_required_approvals must be an integer for tenant '{tenant_id}'") from exc

        return cls(
            tenant_id=tenant_id,
            allowed_namespaces=_items(data.get("allowed_namespaces")),
            allowed_kinds=_items(data.get("allowed_kinds")),
            allowed_extensions=_items(data.get("allowed_extensions")),
            blocked_extensions=_items(data.get("blocked_extensions")),
            allowed_submitters=_items(data.get("allowed_submitters")),
            allowed_statuses=_items(data.get("allowed_statuses")) or ["approved"],
            require_approved=bool(data.get("require_approved", True)),
            require_signature=bool(data.get("require_signature", True)),
            min_required_approvals=min_required_approvals,
            require_compatibility=bool(data.get("require_compatibility", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExtensionRegistry:
    def __init__(self, root: str | Path = "extensions_registry") -> None:
        self.root = Path(root)
        self.packages_dir = self.root / "packages"
        self.index_path = self.root / "index.json"
        self.keys_dir = self.root / "keys"
        self.install_policies_path = self.root / "install_policies.json"

    def init(self) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._save_index({"entries": []})
        if not self.install_policies_path.exists():
            self._save_install_policies({"tenants": {}})
        key_info = self.generate_signing_key(_DEFAULT_SIGNING_KEY_ID, overwrite=False)
        return {
            "ok": True,
            "root": str(self.root),
            "entries": len(self._load_index().get("entries", [])),
            "default_signing_key": key_info,
        }

    def generate_signing_key(self, key_id: str = _DEFAULT_SIGNING_KEY_ID, *, overwrite: bool = False) -> dict[str, Any]:
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        key_path = self.keys_dir / f"{key_id}.key"
        created = False
        if overwrite or not key_path.exists():
            key_path.write_text(secrets.token_hex(32), encoding="utf-8")
            created = True
        return {"key_id": key_id, "path": str(key_path), "created": created}

    def list_signing_keys(self) -> list[dict[str, Any]]:
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        payload: list[dict[str, Any]] = []
        for path in sorted(self.keys_dir.glob("*.key")):
            payload.append({"key_id": path.stem, "path": str(path)})
        return payload

    def publish(
        self,
        path: str | Path,
        *,
        namespace: str = "global",
        submitted_by: str = "OpenMiura",
        overwrite: bool = False,
        run_checks: bool = True,
        signer_key_id: str = _DEFAULT_SIGNING_KEY_ID,
    ) -> RegistryEntry:
        self.init()
        source = Path(path)
        manifest_path = source / "manifest.yaml" if source.is_dir() else source
        manifest = ExtensionManifest.from_yaml_file(manifest_path)
        package_source = manifest.directory or manifest_path.parent
        previous = self._resolve_entry(name=manifest.name, version=None, namespace=namespace)
        release_level = detect_version_bump(previous.version if previous else None, manifest.version)
        if release_level in {"same", "downgrade"} and not overwrite:
            raise ValueError(
                f"Registry version must advance semantically for {namespace}/{manifest.name}: previous={previous.version if previous else 'n/a'}, new={manifest.version}"
            )

        harness_report = None
        if run_checks:
            report = ExtensionHarness().run(package_source)
            harness_report = report.to_dict()
            if not report.ok:
                raise ValueError(f"Registry publication blocked by harness errors: {report.errors}")

        compatibility = evaluate_extension_compatibility(
            extension_contract=manifest.contract_version,
            compatibility=manifest.compatibility,
        ).to_dict()
        if not compatibility.get("compatible", False):
            raise ValueError(f"Registry publication blocked by compatibility errors: {compatibility.get('errors', [])}")

        dest = self.packages_dir / namespace / manifest.name / manifest.version
        if dest.exists() and not overwrite:
            raise FileExistsError(f"Registry entry already exists: {namespace}/{manifest.name}/{manifest.version}")
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(package_source, dest / "package", ignore=shutil.ignore_patterns(*_IGNORE_NAMES, *[f"*{s}" for s in _IGNORE_SUFFIXES]))
        checksum = self._compute_checksum(dest / "package")
        manifest_checksum = self._compute_file_checksum(dest / "package" / "manifest.yaml")
        entry = RegistryEntry(
            namespace=namespace,
            name=manifest.name,
            version=manifest.version,
            kind=manifest.kind,
            status="pending",
            manifest=manifest.to_dict(),
            package_dir=str(dest / "package"),
            checksum=checksum,
            created_at=datetime.now(UTC).isoformat(),
            submitted_by=submitted_by,
            review_history=[self._history_event(actor=submitted_by, action="submitted", note=None, status="pending")],
            harness_report=harness_report,
            compatibility=compatibility,
            release_level=release_level,
            signer_key_id=signer_key_id,
            manifest_checksum=manifest_checksum,
        )
        entry.signature = self._sign_entry(entry, signer_key_id=signer_key_id)
        index = self._load_index()
        entries = [
            e
            for e in index.get("entries", [])
            if not (e.get("namespace") == namespace and e.get("name") == manifest.name and e.get("version") == manifest.version)
        ]
        entries.append(entry.to_dict())
        index["entries"] = sorted(entries, key=lambda item: (item.get("namespace", ""), item.get("name", ""), item.get("version", "")))
        self._save_index(index)
        return entry

    def list(self, *, namespace: str | None = None, status: str | None = None, kind: str | None = None) -> list[RegistryEntry]:
        entries = [RegistryEntry(**item) for item in self._load_index().get("entries", [])]
        if namespace:
            entries = [entry for entry in entries if entry.namespace == namespace]
        if status:
            entries = [entry for entry in entries if entry.status == status]
        if kind:
            entries = [entry for entry in entries if entry.kind == kind]
        return sorted(entries, key=lambda entry: (entry.namespace, entry.name, self._semver_key(entry.version)))

    def describe(self, name: str, version: str, *, namespace: str = "global") -> RegistryEntry:
        entry = self._resolve_entry(name=name, version=version, namespace=namespace)
        if entry is None:
            raise FileNotFoundError(f"Registry entry not found: {namespace}/{name}/{version}")
        return entry

    def start_review(
        self,
        name: str,
        version: str,
        *,
        namespace: str = "global",
        reviewer: str = "OpenMiura",
        note: str | None = None,
    ) -> RegistryEntry:
        return self._set_status(name=name, version=version, namespace=namespace, status="in_review", reviewer=reviewer, note=note, action="review_started")

    def approve(
        self,
        name: str,
        version: str,
        *,
        namespace: str = "global",
        reviewer: str = "OpenMiura",
        note: str | None = None,
    ) -> RegistryEntry:
        return self._set_status(name=name, version=version, namespace=namespace, status="approved", reviewer=reviewer, note=note, action="approved")

    def reject(
        self,
        name: str,
        version: str,
        *,
        namespace: str = "global",
        reviewer: str = "OpenMiura",
        note: str | None = None,
    ) -> RegistryEntry:
        return self._set_status(name=name, version=version, namespace=namespace, status="rejected", reviewer=reviewer, note=note, action="rejected")

    def deprecate(
        self,
        name: str,
        version: str,
        *,
        namespace: str = "global",
        reviewer: str = "OpenMiura",
        note: str | None = None,
    ) -> RegistryEntry:
        return self._set_status(name=name, version=version, namespace=namespace, status="deprecated", reviewer=reviewer, note=note, action="deprecated")

    def verify(self, name: str, version: str, *, namespace: str = "global") -> dict[str, Any]:
        entry = self.describe(name, version, namespace=namespace)
        source = Path(entry.package_dir)
        current_checksum = self._compute_checksum(source)
        current_manifest_checksum = self._compute_file_checksum(source / "manifest.yaml")
        checksum_ok = current_checksum == entry.checksum
        manifest_checksum_ok = (entry.manifest_checksum is None) or (current_manifest_checksum == entry.manifest_checksum)
        signature_ok = self._verify_entry_signature(entry)
        ok = checksum_ok and manifest_checksum_ok and signature_ok
        return {
            "ok": ok,
            "namespace": namespace,
            "name": entry.name,
            "version": entry.version,
            "expected_checksum": entry.checksum,
            "current_checksum": current_checksum,
            "expected_manifest_checksum": entry.manifest_checksum,
            "current_manifest_checksum": current_manifest_checksum,
            "checksum_ok": checksum_ok,
            "manifest_checksum_ok": manifest_checksum_ok,
            "signature_present": bool(entry.signature),
            "signature_ok": signature_ok,
            "signature_algorithm": entry.signature_algorithm,
            "signer_key_id": entry.signer_key_id,
            "approval_count": self._approval_count(entry),
            "status": entry.status,
        }

    def set_install_policy(self, tenant_id: str, policy: dict[str, Any]) -> dict[str, Any]:
        self.init()
        normalized = TenantInstallPolicy.from_mapping(tenant_id, policy)
        payload = self._load_install_policies()
        tenants = dict(payload.get("tenants") or {})
        tenants[tenant_id] = normalized.to_dict()
        payload["tenants"] = tenants
        self._save_install_policies(payload)
        return {"ok": True, "tenant_id": tenant_id, "policy": normalized.to_dict()}

    def get_install_policy(self, tenant_id: str) -> dict[str, Any]:
        payload = self._load_install_policies()
        raw = dict((payload.get("tenants") or {}).get(tenant_id) or {})
        if not raw:
            policy = TenantInstallPolicy(tenant_id=tenant_id)
        else:
            policy = TenantInstallPolicy.from_mapping(tenant_id, raw)
        return {"ok": True, "tenant_id": tenant_id, "policy": policy.to_dict(), "explicit": bool(raw)}

    def explain_install_policy(
        self,
        name: str,
        *,
        version: str | None = None,
        namespace: str = "global",
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        require_approved: bool = True,
    ) -> dict[str, Any]:
        entry = self._resolve_entry(name=name, version=version, namespace=namespace)
        if entry is None:
            raise FileNotFoundError(f"Registry entry not found: {namespace}/{name}/{version or 'latest'}")
        verification = self.verify(name, entry.version, namespace=namespace)
        tenant = str(tenant_id or namespace)
        policy_info = self.get_install_policy(tenant)
        policy = TenantInstallPolicy.from_mapping(tenant, policy_info.get("policy") or {})
        reasons: list[str] = []
        approval_count = self._approval_count(entry)

        effective_require_approved = require_approved or policy.require_approved
        if effective_require_approved and entry.status != "approved":
            reasons.append(f"status_not_allowed: requires approved, current={entry.status}")
        allowed_statuses = set(policy.allowed_statuses or ([] if not effective_require_approved else ["approved"]))
        if allowed_statuses and entry.status not in allowed_statuses:
            reasons.append(f"status_not_in_allowed_statuses: {entry.status}")
        if policy.allowed_namespaces and entry.namespace not in set(policy.allowed_namespaces):
            reasons.append(f"namespace_not_allowed: {entry.namespace}")
        if policy.allowed_kinds and entry.kind not in set(policy.allowed_kinds):
            reasons.append(f"kind_not_allowed: {entry.kind}")
        if policy.allowed_extensions and entry.name not in set(policy.allowed_extensions):
            reasons.append(f"extension_not_in_allowlist: {entry.name}")
        if policy.blocked_extensions and entry.name in set(policy.blocked_extensions):
            reasons.append(f"extension_blocked: {entry.name}")
        if policy.allowed_submitters and entry.submitted_by not in set(policy.allowed_submitters):
            reasons.append(f"submitter_not_allowed: {entry.submitted_by}")
        if approval_count < int(policy.min_required_approvals):
            reasons.append(f"insufficient_approvals: required={policy.min_required_approvals}, current={approval_count}")
        if policy.require_signature and not verification.get("signature_ok", False):
            reasons.append("signature_required_but_invalid")
        if not verification.get("checksum_ok", False):
            reasons.append("checksum_invalid")
        if not verification.get("manifest_checksum_ok", False):
            reasons.append("manifest_checksum_invalid")
        if policy.require_compatibility and not bool((entry.compatibility or {}).get("compatible", False)):
            reasons.append("compatibility_required_but_failed")

        return {
            "ok": not reasons,
            "tenant_id": tenant,
            "workspace_id": workspace_id,
            "namespace": namespace,
            "name": entry.name,
            "version": entry.version,
            "status": entry.status,
            "policy": policy.to_dict(),
            "verification": verification,
            "reasons": reasons,
        }

    def install(
        self,
        name: str,
        *,
        version: str | None = None,
        namespace: str = "global",
        destination: str | Path = "extensions_installed",
        require_approved: bool = True,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        entry = self._resolve_entry(name=name, version=version, namespace=namespace)
        if entry is None:
            raise FileNotFoundError(f"Registry entry not found: {namespace}/{name}/{version or 'latest'}")
        policy_eval = self.explain_install_policy(
            name,
            version=entry.version,
            namespace=namespace,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            require_approved=require_approved,
        )
        if not policy_eval.get("ok", False):
            raise PermissionError(f"Registry install blocked by tenant policy: {policy_eval.get('reasons', [])}")
        source = Path(entry.package_dir)
        resolved_tenant = str(tenant_id or namespace)
        dest = Path(destination) / resolved_tenant / namespace / entry.name / entry.version
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest, ignore=shutil.ignore_patterns(*_IGNORE_NAMES, *[f"*{s}" for s in _IGNORE_SUFFIXES]))
        return {
            "ok": True,
            "tenant_id": resolved_tenant,
            "workspace_id": workspace_id,
            "namespace": namespace,
            "name": entry.name,
            "version": entry.version,
            "status": entry.status,
            "destination": str(dest),
            "checksum_verified": True,
            "signature_verified": True,
            "policy": policy_eval,
        }

    def _set_status(self, *, name: str, version: str, namespace: str, status: str, reviewer: str, note: str | None, action: str) -> RegistryEntry:
        index = self._load_index()
        entries = index.get("entries", [])
        updated: dict[str, Any] | None = None
        for item in entries:
            if item.get("namespace") == namespace and item.get("name") == name and item.get("version") == version:
                item["status"] = status
                item["reviewer"] = reviewer
                item["review_note"] = note
                history = list(item.get("review_history") or [])
                history.append(self._history_event(actor=reviewer, action=action, note=note, status=status))
                item["review_history"] = history
                updated = item
                break
        if updated is None:
            raise FileNotFoundError(f"Registry entry not found: {namespace}/{name}/{version}")
        self._save_index(index)
        return RegistryEntry(**updated)

    def _resolve_entry(self, *, name: str, version: str | None, namespace: str) -> RegistryEntry | None:
        candidates = [entry for entry in self.list(namespace=namespace) if entry.name == name]
        if version:
            for entry in candidates:
                if entry.version == version:
                    return entry
            return None
        if not candidates:
            return None
        return sorted(candidates, key=lambda entry: self._semver_key(entry.version), reverse=True)[0]

    def _compute_checksum(self, path: Path) -> str:
        digest = hashlib.sha256()
        for file_path in sorted(path.rglob("*")):
            if file_path.is_dir():
                if file_path.name in _IGNORE_NAMES:
                    continue
                continue
            if file_path.suffix in _IGNORE_SUFFIXES:
                continue
            digest.update(file_path.relative_to(path).as_posix().encode("utf-8"))
            digest.update(file_path.read_bytes())
        return digest.hexdigest()

    def _compute_file_checksum(self, path: Path) -> str | None:
        if not path.exists() or path.is_dir():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _load_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"entries": []}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _save_index(self, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_install_policies(self) -> dict[str, Any]:
        if not self.install_policies_path.exists():
            return {"tenants": {}}
        return json.loads(self.install_policies_path.read_text(encoding="utf-8"))

    def _save_install_policies(self, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.install_policies_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _semver_key(self, version: str) -> tuple[int, int, int]:
        return semver_key(version)

    def _history_event(self, *, actor: str, action: str, note: str | None, status: str) -> dict[str, Any]:
        return {
            "at": datetime.now(UTC).isoformat(),
            "actor": actor,
            "action": action,
            "status": status,
            "note": note,
        }

    def _approval_count(self, entry: RegistryEntry) -> int:
        actors = {
            str(item.get("actor") or "")
            for item in (entry.review_history or [])
            if str(item.get("action") or "") == "approved" and str(item.get("actor") or "").strip()
        }
        return len(actors)

    def _sign_entry(self, entry: RegistryEntry, *, signer_key_id: str | None = None) -> str:
        key_id = signer_key_id or entry.signer_key_id or _DEFAULT_SIGNING_KEY_ID
        key_material = self._load_signing_key(key_id)
        if key_material is None:
            raise FileNotFoundError(f"Registry signing key not found: {key_id}")
        payload = self._signature_payload(entry)
        return hmac.new(key_material.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def _verify_entry_signature(self, entry: RegistryEntry) -> bool:
        if not entry.signature:
            return False
        key_id = entry.signer_key_id or _DEFAULT_SIGNING_KEY_ID
        key_material = self._load_signing_key(key_id)
        if key_material is None:
            return False
        payload = self._signature_payload(entry)
        expected = hmac.new(key_material.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, entry.signature)

    def _signature_payload(self, entry: RegistryEntry) -> str:
        payload = {
            "namespace": entry.namespace,
            "name": entry.name,
            "version": entry.version,
            "kind": entry.kind,
            "submitted_by": entry.submitted_by,
            "created_at": entry.created_at,
            "checksum": entry.checksum,
            "manifest_checksum": entry.manifest_checksum,
            "contract_version": (entry.manifest or {}).get("contract_version"),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _load_signing_key(self, key_id: str) -> str | None:
        key_path = self.keys_dir / f"{key_id}.key"
        if not key_path.exists():
            return None
        return key_path.read_text(encoding="utf-8").strip() or None


__all__ = ["ExtensionRegistry", "RegistryEntry", "TenantInstallPolicy"]
