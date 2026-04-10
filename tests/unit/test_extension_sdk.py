from __future__ import annotations

import sys
from pathlib import Path

import pytest

from openmiura.agents.skills import SkillManifest
from openmiura.extensions import ExtensionLoader
from openmiura.extensions.sdk import (
    ExtensionLifecycleContext,
    ExtensionManifest,
    FakeToolRegistry,
    NoopTool,
    ToolExecutionContext,
    ToolExtension,
)


def test_extension_manifest_from_mapping_validates_and_roundtrips():
    manifest = ExtensionManifest.from_mapping(
        {
            "manifest_version": "1",
            "contract_version": "1.0",
            "name": "demo_echo",
            "kind": "tool",
            "version": "0.1.0",
            "permissions": ["tools.read"],
            "capabilities": ["echo"],
            "config_schema": {"type": "object"},
            "metadata": {"category": "demo"},
        }
    )

    payload = manifest.to_dict()
    assert payload["name"] == "demo_echo"
    assert payload["kind"] == "tool"
    assert payload["contract_version"] == "1.0"
    assert payload["capabilities"] == ["echo"]


def test_extension_manifest_rejects_unknown_kind():
    with pytest.raises(ValueError):
        ExtensionManifest.from_mapping({"name": "bad", "kind": "something_else"})


def test_extension_loader_discovers_manifest(tmp_path):
    ext_dir = tmp_path / "extensions" / "demo_tool"
    ext_dir.mkdir(parents=True)
    (ext_dir / "manifest.yaml").write_text(
        """
manifest_version: "1"
contract_version: "1.0"
name: demo_echo
kind: tool
version: "0.1.0"
entrypoint: demo_mod:EXPORTED
""".strip(),
        encoding="utf-8",
    )

    loader = ExtensionLoader(tmp_path / "extensions")
    manifests = loader.discover()

    assert len(manifests) == 1
    assert manifests[0].name == "demo_echo"
    assert manifests[0].kind == "tool"


def test_extension_loader_loads_python_entrypoint(tmp_path, monkeypatch):
    pkg_dir = tmp_path / "pluginpkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "tool_mod.py").write_text(
        "EXPORTED = {'ok': True, 'source': 'plugin'}\n", encoding="utf-8"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        manifest = ExtensionManifest.from_mapping(
            {
                "name": "demo_echo",
                "kind": "tool",
                "entrypoint": "pluginpkg.tool_mod:EXPORTED",
            }
        )
        loaded = ExtensionLoader(tmp_path).load(manifest, base_path=tmp_path)
        assert loaded.exported == {"ok": True, "source": "plugin"}
    finally:
        sys.path = [p for p in sys.path if p != str(tmp_path)]


def test_noop_tool_conforms_to_public_protocol():
    tool = NoopTool()
    assert isinstance(tool, ToolExtension)
    tool.initialize(ExtensionLifecycleContext())
    result = tool.execute({"value": 7}, ToolExecutionContext(agent_name="demo-agent"))
    assert result["ok"] is True
    assert result["arguments"]["value"] == 7


def test_fake_tool_registry_registers_public_tool():
    registry = FakeToolRegistry()
    registry.register(NoopTool())
    assert registry.names() == ["noop"]


def test_skill_manifest_can_bridge_to_public_extension_manifest(tmp_path):
    skill_dir = tmp_path / "researcher"
    skill_dir.mkdir()
    (skill_dir / "prompt.md").write_text("Use citations.", encoding="utf-8")
    manifest = SkillManifest(
        name="researcher",
        version="1.2.0",
        description="Research helper",
        tools=["web_fetch"],
        system_prompt_extension="Be source-aware.",
        prompt_file="prompt.md",
        required_permissions=["tools.read"],
        directory=skill_dir,
        source="external",
    )

    extension_manifest = manifest.to_extension_manifest()
    assert extension_manifest.kind == "skill"
    assert extension_manifest.name == "researcher"
    assert "web_fetch" in extension_manifest.capabilities
    assert "prompt_extension" in extension_manifest.capabilities
    assert extension_manifest.metadata["source"] == "external"
