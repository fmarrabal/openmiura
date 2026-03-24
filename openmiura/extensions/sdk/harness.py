from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import inspect
import json

from openmiura import __version__
from openmiura.extensions.sdk.context import (
    AuthRequestContext,
    ChannelAdapterContext,
    ExtensionLifecycleContext,
    ProviderExecutionContext,
    SkillExecutionContext,
    StorageContext,
    ToolExecutionContext,
)
from openmiura.extensions.sdk.manifests import ExtensionManifest
from openmiura.extensions.sdk.version import SDK_CONTRACT_VERSION, evaluate_extension_compatibility

_DANGEROUS_PATTERNS: dict[str, str] = {
    "os.system(": "os.system invocation",
    "shell=True": "shell=True subprocess invocation",
    "eval(": "eval usage",
    "exec(": "exec usage",
}
_WARNING_PATTERNS: dict[str, str] = {
    "pickle.loads(": "pickle.loads usage",
    "yaml.load(": "yaml.load usage",
}


@dataclass(slots=True)
class ExtensionTestReport:
    ok: bool
    path: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: ExtensionManifest | None = None
    smoke_result: Any | None = None
    compatibility: dict[str, Any] = field(default_factory=dict)
    contract_checks: list[dict[str, Any]] = field(default_factory=list)
    packaging_checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "path": self.path,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "manifest": self.manifest.to_dict() if self.manifest else None,
            "smoke_result": self.smoke_result,
            "compatibility": dict(self.compatibility),
            "contract_checks": list(self.contract_checks),
            "packaging_checks": list(self.packaging_checks),
        }


class ExtensionHarness:
    def _manifest_path(self, path: str | Path) -> Path:
        raw = Path(path)
        if raw.is_dir():
            candidate = raw / "manifest.yaml"
            if candidate.exists():
                return candidate
        return raw

    def validate_manifest(self, path: str | Path) -> ExtensionTestReport:
        manifest_path = self._manifest_path(path)
        errors: list[str] = []
        warnings: list[str] = []
        manifest: ExtensionManifest | None = None
        try:
            manifest = ExtensionManifest.from_yaml_file(manifest_path)
        except Exception as exc:
            errors.append(f"manifest_validation_failed: {exc}")
            return ExtensionTestReport(ok=False, path=str(manifest_path), errors=errors, warnings=warnings, manifest=None)

        if manifest.entrypoint:
            module_name, sep, attr = manifest.entrypoint.partition(":")
            if not sep or not module_name or not attr:
                errors.append("invalid_entrypoint")
            if attr.startswith("__"):
                errors.append("invalid_entrypoint_attribute")
        elif manifest.kind != "workflow":
            warnings.append("manifest_has_no_entrypoint")

        if manifest.contract_version.split(".", 1)[0] != SDK_CONTRACT_VERSION.split(".", 1)[0]:
            errors.append(f"unsupported_contract_major: {manifest.contract_version}")
        if manifest.config_schema and manifest.config_schema.get("type") not in {None, "object"}:
            errors.append("config_schema_must_be_object")
        if manifest.kind in {"auth_provider", "storage_backend"} and not manifest.capabilities:
            warnings.append("manifest_has_no_capabilities")
        if manifest.kind == "tool" and not manifest.permissions:
            warnings.append("manifest_has_no_permissions")
        if int(manifest.review.get("required_approvals", 1) or 1) < 1:
            errors.append("review_required_approvals_must_be_positive")

        compatibility_report = evaluate_extension_compatibility(
            extension_contract=manifest.contract_version,
            runtime_contract=SDK_CONTRACT_VERSION,
            runtime_version=__version__,
            compatibility=manifest.compatibility,
        )
        warnings.extend(compatibility_report.warnings)
        errors.extend(compatibility_report.errors)

        report = ExtensionTestReport(
            ok=not errors,
            path=str(manifest_path),
            errors=errors,
            warnings=warnings,
            manifest=manifest,
            compatibility=compatibility_report.to_dict(),
        )
        self._packaging_checks(manifest.directory or manifest_path.parent, report)
        return report

    def run(self, path: str | Path) -> ExtensionTestReport:
        report = self.validate_manifest(path)
        if not report.ok or report.manifest is None:
            return report

        manifest = report.manifest
        if manifest.kind == "workflow":
            report.smoke_result = {"validated": True, "kind": "workflow", "steps": "declarative_only"}
            return report

        self._security_scan(manifest.directory or Path(path).parent, report)
        if report.errors:
            report.ok = False
            return report

        try:
            from openmiura.extensions.loader import ExtensionLoader

            loader = ExtensionLoader(root=manifest.directory or Path(path).parent)
            loaded = loader.load(manifest, base_path=manifest.directory)
            exported = loaded.exported
            extension = exported() if isinstance(exported, type) else exported
            if extension is None:
                raise ValueError("Extension entrypoint resolved to None")
            self._assert_contract(manifest.kind, extension)
            self._assert_manifest_consistency(manifest, extension)
            self._initialize(extension)
            smoke_result = self._smoke(manifest.kind, extension)
            self._assert_smoke_result(manifest.kind, smoke_result)
            report.smoke_result = smoke_result
            self._shutdown(extension)
        except Exception as exc:
            report.errors.append(f"extension_test_failed: {exc}")
            report.ok = False
            return report

        report.ok = not report.errors
        return report

    def _assert_contract(self, kind: str, extension: Any) -> None:
        methods_by_kind = {
            "tool": ("initialize", "execute", "shutdown"),
            "skill": ("initialize", "extend_agent_config", "shutdown"),
            "llm_provider": ("initialize", "complete", "shutdown"),
            "channel_adapter": ("initialize", "normalize_inbound", "format_outbound", "shutdown"),
            "storage_backend": ("initialize", "get", "put", "delete", "shutdown"),
            "auth_provider": ("initialize", "authenticate", "shutdown"),
            "observability_exporter": ("initialize", "emit", "shutdown"),
        }
        required = methods_by_kind.get(kind, ())
        missing = [name for name in required if not callable(getattr(extension, name, None))]
        if missing:
            raise TypeError(f"Extension kind '{kind}' is missing required methods: {', '.join(missing)}")
        self._assert_signatures(kind, extension)

    def _assert_signatures(self, kind: str, extension: Any) -> None:
        minimum_arity = {
            "tool": {"execute": 2},
            "skill": {"extend_agent_config": 2},
            "llm_provider": {"complete": 2},
            "channel_adapter": {"normalize_inbound": 2, "format_outbound": 2},
            "storage_backend": {"get": 2, "put": 3, "delete": 2},
            "auth_provider": {"authenticate": 2},
            "observability_exporter": {"emit": 1},
        }.get(kind, {})
        for method_name, expected in minimum_arity.items():
            method = getattr(extension, method_name)
            sig = inspect.signature(method)
            positional = [
                param
                for param in sig.parameters.values()
                if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            if len(positional) < expected:
                raise TypeError(f"Method '{method_name}' requires at least {expected} positional parameters for kind '{kind}'")

    def _assert_manifest_consistency(self, manifest: ExtensionManifest, extension: Any) -> None:
        extension_manifest = getattr(extension, "manifest", None)
        if isinstance(extension_manifest, ExtensionManifest):
            if extension_manifest.name != manifest.name:
                raise ValueError(f"Entrypoint manifest name mismatch: expected '{manifest.name}', got '{extension_manifest.name}'")
            if extension_manifest.kind != manifest.kind:
                raise ValueError(f"Entrypoint manifest kind mismatch: expected '{manifest.kind}', got '{extension_manifest.kind}'")
            if extension_manifest.contract_version != manifest.contract_version:
                raise ValueError(
                    f"Entrypoint manifest contract mismatch: expected '{manifest.contract_version}', got '{extension_manifest.contract_version}'"
                )
        elif extension_manifest is None:
            raise ValueError("Entrypoint object must expose a manifest")

    def _initialize(self, extension: Any) -> None:
        extension.initialize(ExtensionLifecycleContext(settings=None, logger=None, metadata={"source": "harness"}))

    def _shutdown(self, extension: Any) -> None:
        shutdown = getattr(extension, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def _security_scan(self, root: Path, report: ExtensionTestReport) -> None:
        if not root.exists():
            return
        for file_path in sorted(root.rglob("*.py")):
            if any(part in {"__pycache__", ".pytest_cache"} for part in file_path.parts):
                continue
            content = file_path.read_text(encoding="utf-8")
            for pattern, label in _DANGEROUS_PATTERNS.items():
                if pattern in content:
                    report.errors.append(f"security_check_failed: {label} in {file_path.name}")
            for pattern, label in _WARNING_PATTERNS.items():
                if pattern in content:
                    report.warnings.append(f"security_warning: {label} in {file_path.name}")

    def _packaging_checks(self, root: Path, report: ExtensionTestReport) -> None:
        required = [
            (root / "README.md", False, "README.md present"),
            (root / "CHANGELOG.md", False, "CHANGELOG.md present"),
            (root / "tests" / "test_smoke.py", False, "tests/test_smoke.py present"),
        ]
        for path, required_flag, label in required:
            ok = path.exists()
            entry = {"name": label, "ok": ok, "path": str(path)}
            report.packaging_checks.append(entry)
            if not ok and required_flag:
                report.errors.append(f"packaging_check_failed: missing {path.name}")
            elif not ok:
                report.warnings.append(f"packaging_warning: missing {path.relative_to(root)}")

    def _assert_smoke_result(self, kind: str, smoke_result: Any) -> None:
        try:
            json.dumps(smoke_result, ensure_ascii=False, default=str)
        except Exception as exc:
            raise TypeError(f"Smoke result must be JSON serializable: {exc}") from exc
        if kind == "tool":
            if not isinstance(smoke_result, dict) or "tool" not in smoke_result:
                raise TypeError("Tool smoke result must be a dict with key 'tool'")
        elif kind == "skill":
            if not isinstance(smoke_result, dict) or "skills" not in smoke_result:
                raise TypeError("Skill smoke result must include 'skills'")
        elif kind == "llm_provider":
            if not isinstance(smoke_result, dict) or "text" not in smoke_result:
                raise TypeError("Provider smoke result must include 'text'")
        elif kind == "channel_adapter":
            if not isinstance(smoke_result, dict) or "normalized" not in smoke_result or "formatted" not in smoke_result:
                raise TypeError("Channel smoke result must include 'normalized' and 'formatted'")
        elif kind == "storage_backend":
            if not isinstance(smoke_result, dict) or "value" not in smoke_result:
                raise TypeError("Storage smoke result must include 'value'")
        elif kind == "auth_provider":
            if not isinstance(smoke_result, dict) or "provider" not in smoke_result:
                raise TypeError("Auth smoke result must include 'provider'")

    def _smoke(self, kind: str, extension: Any) -> Any:
        if kind == "tool":
            return extension.execute({"example": True}, ToolExecutionContext(agent_name="sdk-smoke", user_key="test-user"))
        if kind == "skill":
            return extension.extend_agent_config({"agent_id": "sdk-smoke"}, SkillExecutionContext(agent_name="sdk-smoke"))
        if kind == "llm_provider":
            return extension.complete("hello", ProviderExecutionContext(model="demo-model"))
        if kind == "channel_adapter":
            normalized = extension.normalize_inbound({"text": "hello", "user_id": "u-1"}, ChannelAdapterContext())
            formatted = extension.format_outbound({"text": "world"}, ChannelAdapterContext())
            return {
                "normalized": asdict(normalized),
                "formatted": formatted,
            }
        if kind == "storage_backend":
            ctx = StorageContext(tenant_id="tenant-a", workspace_id="workspace-a")
            extension.put("k", {"ok": True}, ctx)
            value = extension.get("k", ctx)
            extension.delete("k", ctx)
            return {"value": value}
        if kind == "auth_provider":
            return extension.authenticate({"token": "demo"}, AuthRequestContext(channel="http"))
        if kind == "observability_exporter":
            extension.emit({"type": "smoke", "ok": True})
            return {"emitted": True}
        return {"ok": True}


__all__ = ["ExtensionHarness", "ExtensionTestReport"]
