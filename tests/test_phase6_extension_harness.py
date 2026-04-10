from __future__ import annotations

from openmiura.extensions.sdk import ExtensionHarness, scaffold_project


def test_extension_harness_reports_missing_required_method(tmp_path) -> None:
    root = tmp_path / "broken-tool"
    root.mkdir()
    (root / "manifest.yaml").write_text(
        'manifest_version: "1"\ncontract_version: "1.0"\nname: broken-tool\nkind: tool\nentrypoint: broken_tool:tool\n',
        encoding="utf-8",
    )
    (root / "broken_tool.py").write_text("tool = object()\n", encoding="utf-8")

    report = ExtensionHarness().run(root)
    assert report.ok is False
    assert any("missing required methods" in error for error in report.errors)


def test_extension_harness_smoke_for_scaffolded_skill(tmp_path) -> None:
    result = scaffold_project(kind="skill", name="ops-triage", output_dir=tmp_path)
    report = ExtensionHarness().run(result.root)
    assert report.ok is True
    assert report.manifest is not None
    assert report.manifest.kind == "skill"
    assert report.smoke_result["metadata"]["extended_by"] == "ops-triage"


def test_extension_harness_security_scan_rejects_dangerous_patterns(tmp_path) -> None:
    root = tmp_path / "unsafe-tool"
    root.mkdir()
    (root / "manifest.yaml").write_text(
        '\n'.join(
            [
                'manifest_version: "1"',
                'contract_version: "1.0"',
                'name: unsafe-tool',
                'kind: tool',
                'entrypoint: unsafe_tool:tool',
            ]
        ),
        encoding="utf-8",
    )
    (root / "unsafe_tool.py").write_text(
        'from openmiura.extensions.sdk import ExtensionLifecycleContext, ExtensionManifest, ToolExecutionContext\n'
        'import os\n'
        'class UnsafeTool:\n'
        '    manifest = ExtensionManifest(name="unsafe-tool", kind="tool")\n'
        '    def initialize(self, ctx: ExtensionLifecycleContext) -> None:\n        ...\n'
        '    def execute(self, arguments, ctx: ToolExecutionContext):\n        os.system("echo bad")\n        return {"ok": True}\n'
        '    def shutdown(self) -> None:\n        ...\n'
        'tool = UnsafeTool()\n',
        encoding="utf-8",
    )
    report = ExtensionHarness().run(root)
    assert report.ok is False
    assert any("security_check_failed" in error for error in report.errors)


def test_extension_harness_detects_entrypoint_manifest_mismatch(tmp_path) -> None:
    root = tmp_path / "mismatch-tool"
    root.mkdir()
    (root / "manifest.yaml").write_text(
        'manifest_version: "1"\ncontract_version: "1.0"\nname: manifest-name\nkind: tool\nentrypoint: mismatch_tool:tool\n',
        encoding="utf-8",
    )
    (root / "mismatch_tool.py").write_text(
        'from openmiura.extensions.sdk import ExtensionLifecycleContext, ExtensionManifest, ToolExecutionContext\n'
        'class DemoTool:\n'
        '    manifest = ExtensionManifest(name="different-name", kind="tool")\n'
        '    def initialize(self, ctx: ExtensionLifecycleContext) -> None:\n        self._ctx = ctx\n'
        '    def execute(self, arguments, ctx: ToolExecutionContext):\n        return {"ok": True}\n'
        '    def shutdown(self) -> None:\n        self._ctx = None\n'
        'tool = DemoTool()\n',
        encoding="utf-8",
    )
    report = ExtensionHarness().run(root)
    assert report.ok is False
    assert any("manifest name mismatch" in error for error in report.errors)
