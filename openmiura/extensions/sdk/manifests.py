from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .version import SDK_CONTRACT_VERSION, SUPPORTED_MANIFEST_VERSIONS

_ALLOWED_KINDS = {
    "tool",
    "skill",
    "llm_provider",
    "channel_adapter",
    "storage_backend",
    "auth_provider",
    "observability_exporter",
}


@dataclass(slots=True)
class ExtensionManifest:
    name: str
    kind: str
    version: str = "0.1.0"
    description: str = ""
    author: str = "OpenMiura"
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    entrypoint: str | None = None
    contract_version: str = SDK_CONTRACT_VERSION
    manifest_version: str = "1"
    config_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, Any] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)
    directory: Path | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any], *, directory: Path | None = None) -> "ExtensionManifest":
        if not isinstance(raw, dict):
            raise ValueError("Extension manifest must be a mapping")

        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError("Extension manifest missing required field: name")

        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in _ALLOWED_KINDS:
            raise ValueError(
                f"Unsupported extension kind '{kind}' for {name}. Supported kinds: {', '.join(sorted(_ALLOWED_KINDS))}"
            )

        manifest_version = str(raw.get("manifest_version") or "1").strip()
        if manifest_version not in SUPPORTED_MANIFEST_VERSIONS:
            raise ValueError(
                f"Unsupported manifest_version '{manifest_version}' for {name}. Supported values: {sorted(SUPPORTED_MANIFEST_VERSIONS)}"
            )

        contract_version = str(raw.get("contract_version") or SDK_CONTRACT_VERSION).strip()
        if not contract_version:
            raise ValueError(f"Extension manifest contract_version cannot be empty for {name}")

        def _str_list(value: Any, field_name: str) -> list[str]:
            if value is None:
                return []
            if not isinstance(value, list):
                raise ValueError(f"Extension field '{field_name}' for {name} must be a list of strings")
            out: list[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    out.append(text)
            return out

        config_schema = raw.get("config_schema") or {}
        metadata = raw.get("metadata") or {}
        compatibility = raw.get("compatibility") or {}
        review = raw.get("review") or {}
        if not isinstance(config_schema, dict):
            raise ValueError(f"Extension field 'config_schema' for {name} must be a mapping")
        if not isinstance(metadata, dict):
            raise ValueError(f"Extension field 'metadata' for {name} must be a mapping")
        if not isinstance(compatibility, dict):
            raise ValueError(f"Extension field 'compatibility' for {name} must be a mapping")
        if not isinstance(review, dict):
            raise ValueError(f"Extension field 'review' for {name} must be a mapping")

        required_approvals = review.get("required_approvals", 1)
        try:
            required_approvals = max(1, int(required_approvals))
        except Exception as exc:
            raise ValueError(f"Extension field 'review.required_approvals' for {name} must be an integer") from exc
        review = dict(review)
        review["required_approvals"] = required_approvals
        reviewers = review.get("reviewers") or []
        if reviewers and not isinstance(reviewers, list):
            raise ValueError(f"Extension field 'review.reviewers' for {name} must be a list of strings")
        review["reviewers"] = [str(item).strip() for item in reviewers if str(item).strip()]

        entrypoint = raw.get("entrypoint")
        entrypoint_text = str(entrypoint).strip() if entrypoint else None

        return cls(
            name=name,
            kind=kind,
            version=str(raw.get("version") or "0.1.0").strip() or "0.1.0",
            description=str(raw.get("description") or ""),
            author=str(raw.get("author") or "OpenMiura"),
            enabled=bool(raw.get("enabled", True)),
            tags=_str_list(raw.get("tags"), "tags"),
            permissions=_str_list(raw.get("permissions"), "permissions"),
            capabilities=_str_list(raw.get("capabilities"), "capabilities"),
            entrypoint=entrypoint_text,
            contract_version=contract_version,
            manifest_version=manifest_version,
            config_schema=dict(config_schema),
            metadata=dict(metadata),
            compatibility=dict(compatibility),
            review=dict(review),
            directory=directory,
        )

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> "ExtensionManifest":
        manifest_path = Path(path)
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        return cls.from_mapping(raw, directory=manifest_path.parent)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "contract_version": self.contract_version,
            "name": self.name,
            "kind": self.kind,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "enabled": self.enabled,
            "tags": list(self.tags),
            "permissions": list(self.permissions),
            "capabilities": list(self.capabilities),
            "entrypoint": self.entrypoint,
            "config_schema": dict(self.config_schema),
            "metadata": dict(self.metadata),
            "compatibility": dict(self.compatibility),
            "review": dict(self.review),
        }
