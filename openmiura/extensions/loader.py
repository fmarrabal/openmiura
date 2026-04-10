from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator
import sys

from openmiura.extensions.sdk.manifests import ExtensionManifest


@dataclass(slots=True)
class LoadedExtension:
    manifest: ExtensionManifest
    source_path: Path
    exported: Any
    module: ModuleType | None = None


@contextmanager
def _sys_path(path: Path | None) -> Iterator[None]:
    if path is None:
        yield
        return
    value = str(path)
    added = value not in sys.path
    if added:
        sys.path.insert(0, value)
    try:
        yield
    finally:
        if added:
            try:
                sys.path.remove(value)
            except ValueError:
                pass


class ExtensionLoader:
    """Filesystem-backed discovery/loader for public extensions.

    This is intentionally small in phase 1: it discovers declarative manifests,
    validates them through the public SDK model and optionally resolves a Python
    entrypoint. The runtime integration can expand later without changing the
    external contract.
    """

    def __init__(self, root: str | Path = "extensions") -> None:
        self.root = Path(root)

    def discover(self) -> list[ExtensionManifest]:
        manifests: list[ExtensionManifest] = []
        if not self.root.exists():
            return manifests
        for path in sorted(self.root.rglob("manifest.yaml")):
            manifests.append(ExtensionManifest.from_yaml_file(path))
        return manifests

    def load(self, manifest: ExtensionManifest, *, base_path: str | Path | None = None) -> LoadedExtension:
        source_path = Path(base_path or self.root)
        exported: Any = None
        module: ModuleType | None = None
        if manifest.entrypoint:
            module_name, sep, attr = manifest.entrypoint.partition(":")
            if not sep or not module_name or not attr:
                raise ValueError(
                    f"Invalid extension entrypoint '{manifest.entrypoint}' for {manifest.name}. "
                    "Expected 'package.module:attribute'."
                )
            search_path = Path(base_path) if base_path is not None else (manifest.directory if manifest.directory else self.root)
            with _sys_path(search_path):
                module = import_module(module_name)
                exported = getattr(module, attr)
        return LoadedExtension(
            manifest=manifest,
            source_path=source_path,
            exported=exported,
            module=module,
        )
