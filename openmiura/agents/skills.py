from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class SkillManifestError(ValueError):
    """Raised when a skill manifest is invalid."""


_ALLOWED_MANIFEST_KEYS = {
    "manifest_version",
    "name",
    "version",
    "description",
    "author",
    "enabled",
    "tags",
    "tools",
    "tool_modules",
    "system_prompt_extension",
    "prompt_file",
    "required_permissions",
}


@dataclass
class SkillManifest:
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = "OpenMiura"
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    tool_modules: list[str] | None = None
    system_prompt_extension: str = ""
    prompt_file: str | None = None
    required_permissions: list[str] = field(default_factory=list)
    manifest_version: str = "1"
    directory: Path | None = None
    source: str = "external"

    @property
    def prompt_extension(self) -> str:
        base = (self.system_prompt_extension or "").strip()
        if self.directory is None or not self.prompt_file:
            return base
        prompt_path = self.directory / self.prompt_file
        if not prompt_path.exists():
            raise SkillManifestError(
                f"Skill '{self.name}' references missing prompt_file: {self.prompt_file}"
            )
        extra = prompt_path.read_text(encoding="utf-8").strip()
        if base and extra:
            return base + "\n\n" + extra
        return extra or base

    def to_extension_manifest(self):
        from openmiura.extensions.sdk.manifests import ExtensionManifest

        capabilities = list(self.tools)
        if self.prompt_extension:
            capabilities.append("prompt_extension")
        return ExtensionManifest(
            name=self.name,
            kind="skill",
            version=self.version,
            description=self.description,
            author=self.author,
            enabled=self.enabled,
            tags=list(self.tags),
            permissions=list(self.required_permissions),
            capabilities=capabilities,
            metadata={"source": self.source},
            contract_version="1.0",
            manifest_version=self.manifest_version,
            directory=self.directory,
        )


class SkillLoader:
    def __init__(
        self,
        skills_root: str | Path = "skills",
        *,
        include_builtin: bool = True,
    ) -> None:
        self.skills_root = Path(skills_root)
        self.include_builtin = include_builtin
        self._cache: dict[str, SkillManifest] = {}
        self._errors: dict[str, str] = {}

    def _builtin_root(self) -> Path:
        return Path(__file__).resolve().parents[1] / "builtin_skills"

    def _roots(self) -> list[tuple[str, Path]]:
        roots: list[tuple[str, Path]] = []
        if self.include_builtin:
            roots.append(("builtin", self._builtin_root()))
        roots.append(("external", self.skills_root))
        return roots

    def _coerce_str_list(self, value: Any, field_name: str, skill_name: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise SkillManifestError(
                f"Skill '{skill_name}' field '{field_name}' must be a list of strings"
            )
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out

    def _parse_manifest(self, path: Path, source: str) -> SkillManifest:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise SkillManifestError(f"Manifest must be a mapping: {path}")

        unknown = sorted(set(raw.keys()) - _ALLOWED_MANIFEST_KEYS)
        if unknown:
            raise SkillManifestError(
                f"Unknown manifest keys in {path}: {', '.join(unknown)}"
            )

        name = str(raw.get("name") or path.parent.name).strip()
        if not name:
            raise SkillManifestError(f"Skill manifest missing name: {path}")

        prompt_file = raw.get("prompt_file")
        tool_modules_raw = raw.get("tool_modules")
        tool_modules = None
        if tool_modules_raw is not None:
            tool_modules = self._coerce_str_list(tool_modules_raw, "tool_modules", name)

        return SkillManifest(
            name=name,
            version=str(raw.get("version") or "0.1.0"),
            description=str(raw.get("description") or ""),
            author=str(raw.get("author") or "OpenMiura"),
            enabled=bool(raw.get("enabled", True)),
            tags=self._coerce_str_list(raw.get("tags"), "tags", name),
            tools=self._coerce_str_list(raw.get("tools"), "tools", name),
            tool_modules=tool_modules,
            system_prompt_extension=str(raw.get("system_prompt_extension") or ""),
            prompt_file=str(prompt_file).strip() if prompt_file else None,
            required_permissions=self._coerce_str_list(
                raw.get("required_permissions"), "required_permissions", name
            ),
            manifest_version=str(raw.get("manifest_version") or "1"),
            directory=path.parent,
            source=source,
        )

    def load_all(self) -> dict[str, SkillManifest]:
        manifests: dict[str, SkillManifest] = {}
        errors: dict[str, str] = {}
        for source, base in self._roots():
            if not base.exists():
                continue
            for path in sorted(base.glob("*/manifest.yaml")):
                try:
                    manifest = self._parse_manifest(path, source)
                    if manifest.enabled:
                        manifests[manifest.name] = manifest
                except Exception as exc:
                    errors[str(path)] = repr(exc)
        self._cache = manifests
        self._errors = errors
        return manifests

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)

    def _ensure_cache(self) -> None:
        if not self._cache and not self._errors:
            self.load_all()

    def get_many(self, names: list[str] | None) -> list[SkillManifest]:
        self._ensure_cache()
        return [self._cache[name] for name in (names or []) if name in self._cache]

    def catalog(self) -> list[dict[str, Any]]:
        self._ensure_cache()
        rows: list[dict[str, Any]] = []
        for name in sorted(self._cache):
            skill = self._cache[name]
            rows.append(
                {
                    "name": skill.name,
                    "version": skill.version,
                    "description": skill.description,
                    "author": skill.author,
                    "source": skill.source,
                    "tools": list(skill.tools),
                    "required_permissions": list(skill.required_permissions),
                    "tags": list(skill.tags),
                }
            )
        return rows

    def extend_agent_config(self, agent_cfg: dict[str, Any]) -> dict[str, Any]:
        cfg = dict(agent_cfg or {})
        skills = self.get_many(list(cfg.get("skills") or []))
        if not skills:
            return cfg
        tools = list(cfg.get("allowed_tools") or cfg.get("tools") or [])
        extensions: list[str] = []
        permissions = list(cfg.get("required_permissions") or [])
        for skill in skills:
            for tool in skill.tools:
                if tool not in tools:
                    tools.append(tool)
            for permission in skill.required_permissions:
                if permission not in permissions:
                    permissions.append(permission)
            prompt_extension = skill.prompt_extension
            if prompt_extension:
                extensions.append(prompt_extension)
        cfg["allowed_tools"] = tools
        cfg["required_permissions"] = permissions
        if extensions:
            base = str(cfg.get("system_prompt") or "You are openMiura.").rstrip()
            cfg["system_prompt"] = base + "\n\n" + "\n\n".join(extensions)
        return cfg

    def _tool_module_paths(self, skill: SkillManifest) -> list[Path]:
        if skill.directory is None:
            return []
        if skill.tool_modules is not None:
            out: list[Path] = []
            for rel in skill.tool_modules:
                rel_path = Path(rel)
                candidate = skill.directory / rel_path
                if not candidate.exists() and rel_path.parent == Path('.'):
                    candidate = skill.directory / 'tools' / rel_path
                if not candidate.suffix:
                    candidate = candidate.with_suffix('.py')
                if not candidate.exists():
                    raise SkillManifestError(
                        f"Skill '{skill.name}' references missing tool module: {rel}"
                    )
                out.append(candidate)
            return out

        out: list[Path] = []
        single = skill.directory / "tools.py"
        if single.exists():
            out.append(single)
        tools_dir = skill.directory / "tools"
        if tools_dir.exists():
            out.extend(sorted(p for p in tools_dir.glob("*.py") if p.name != "__init__.py"))
        return out

    def _load_module_from_path(self, skill_name: str, path: Path):
        module_name = f"openmiura_skill_{skill_name}_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load skill tools module from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def register_skill_tools(self, registry, names: list[str] | None = None) -> list[str]:
        self._ensure_cache()
        loaded: list[str] = []
        selected = self.get_many(names or list(self._cache.keys()))
        for skill in selected:
            for path in self._tool_module_paths(skill):
                module = self._load_module_from_path(skill.name, path)
                if hasattr(module, "register_tools"):
                    module.register_tools(registry)
                    loaded.append(f"{skill.name}:{path.name}")
                    continue
                for tool in list(getattr(module, "TOOLS", []) or []):
                    registry.register(tool)
                    loaded.append(f"{skill.name}:{getattr(tool, 'name', path.stem)}")
        return loaded
