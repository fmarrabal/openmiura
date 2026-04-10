from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import openmiura.cli as cli


runner = CliRunner()


def test_create_tool_scaffold_and_sdk_test(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["create", "tool", "demo-tool", "--output-dir", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    root = Path(payload["root"])
    assert (root / "manifest.yaml").exists()
    assert (root / "demo_tool.py").exists()
    assert (root / "tests" / "test_smoke.py").exists()
    assert (root / "CHANGELOG.md").exists()

    validate = runner.invoke(cli.app, ["sdk", "validate-manifest", str(root), "--json"])
    assert validate.exit_code == 0
    validate_payload = json.loads(validate.stdout)
    assert validate_payload["ok"] is True
    assert validate_payload["manifest"]["kind"] == "tool"

    test_result = runner.invoke(cli.app, ["sdk", "test-extension", str(root), "--json"])
    assert test_result.exit_code == 0
    test_payload = json.loads(test_result.stdout)
    assert test_payload["ok"] is True
    assert test_payload["smoke_result"]["tool"] == "demo-tool"


def test_create_workflow_scaffold(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["create", "workflow", "daily-summary", "--output-dir", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    root = Path(payload["root"])
    assert (root / "playbook.yaml").exists()
    content = (root / "playbook.yaml").read_text(encoding="utf-8")
    assert "playbook_id: daily-summary" in content


def test_create_auth_and_storage_scaffolds(tmp_path: Path) -> None:
    auth_result = runner.invoke(cli.app, ["create", "auth", "corp-login", "--output-dir", str(tmp_path), "--json"])
    assert auth_result.exit_code == 0
    auth_payload = json.loads(auth_result.stdout)
    auth_root = Path(auth_payload["root"])
    assert (auth_root / "corp_login.py").exists()

    auth_test = runner.invoke(cli.app, ["sdk", "test-extension", str(auth_root), "--json"])
    assert auth_test.exit_code == 0
    auth_report = json.loads(auth_test.stdout)
    assert auth_report["ok"] is True
    assert auth_report["manifest"]["kind"] == "auth_provider"
    assert auth_report["smoke_result"]["provider"] == "corp-login"

    storage_result = runner.invoke(cli.app, ["create", "storage", "tenant-cache", "--output-dir", str(tmp_path), "--json"])
    assert storage_result.exit_code == 0
    storage_payload = json.loads(storage_result.stdout)
    storage_root = Path(storage_payload["root"])
    assert (storage_root / "tenant_cache.py").exists()

    storage_test = runner.invoke(cli.app, ["sdk", "test-extension", str(storage_root), "--json"])
    assert storage_test.exit_code == 0
    storage_report = json.loads(storage_test.stdout)
    assert storage_report["ok"] is True
    assert storage_report["manifest"]["kind"] == "storage_backend"
    assert storage_report["smoke_result"]["value"]["ok"] is True
