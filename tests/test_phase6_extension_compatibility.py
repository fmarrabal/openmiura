from __future__ import annotations

from pathlib import Path

from openmiura.extensions.sdk import (
    ExtensionHarness,
    compare_versions,
    detect_version_bump,
    evaluate_extension_compatibility,
    scaffold_project,
)


def test_version_helpers_detect_semantic_bumps() -> None:
    assert compare_versions("1.2.0", "1.1.9") == 1
    assert compare_versions("1.2.0", "1.2.0") == 0
    assert detect_version_bump("1.2.0", "1.3.0") == "minor"
    assert detect_version_bump("1.2.0", "2.0.0") == "major"
    assert detect_version_bump("1.2.0", "1.2.1") == "patch"


def test_evaluate_extension_compatibility_flags_runtime_bounds() -> None:
    report = evaluate_extension_compatibility(
        extension_contract="1.0",
        runtime_contract="1.0",
        runtime_version="1.0.0",
        compatibility={"min_openmiura_version": "2.0.0", "tested_contract_versions": ["1.0"]},
    )
    assert report.compatible is False
    assert any("openmiura_too_old" in error for error in report.errors)


def test_harness_rejects_manifest_with_incompatible_runtime_window(tmp_path: Path) -> None:
    result = scaffold_project(kind="tool", name="future-only-tool", output_dir=tmp_path)
    manifest = result.root / "manifest.yaml"
    content = manifest.read_text(encoding="utf-8")
    content = content.replace('  max_openmiura_version: null', '  max_openmiura_version: "0.9.0"')
    manifest.write_text(content, encoding="utf-8")

    report = ExtensionHarness().validate_manifest(result.root)
    assert report.ok is False
    assert any("openmiura_too_new" in error for error in report.errors)
