from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
import pytest

import openmiura.cli as cli
from openmiura.extensions.sdk import ExtensionRegistry, scaffold_project


runner = CliRunner()


def test_registry_verify_detects_tampered_package_with_signature_still_present(tmp_path: Path) -> None:
    extension = scaffold_project(kind="tool", name="signed-tool", output_dir=tmp_path)
    registry = ExtensionRegistry(tmp_path / "registry")

    published = registry.publish(extension.root, namespace="tenant-z", submitted_by="builder")
    assert published.signature is not None
    assert published.signer_key_id == "default"

    verification = registry.verify("signed-tool", "0.1.0", namespace="tenant-z")
    assert verification["ok"] is True
    assert verification["checksum_ok"] is True
    assert verification["signature_ok"] is True

    package_dir = Path(published.package_dir)
    tool_module = next(package_dir.glob("*.py"))
    tool_module.write_text(tool_module.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    verification_after = registry.verify("signed-tool", "0.1.0", namespace="tenant-z")
    assert verification_after["ok"] is False
    assert verification_after["checksum_ok"] is False
    assert verification_after["signature_ok"] is True


def test_registry_tenant_install_policy_requires_second_approval_and_allowed_namespace(tmp_path: Path) -> None:
    extension = scaffold_project(kind="storage", name="tenant-cache", output_dir=tmp_path)
    registry = ExtensionRegistry(tmp_path / "registry")
    registry.publish(extension.root, namespace="shared", submitted_by="platform")
    registry.approve("tenant-cache", "0.1.0", namespace="shared", reviewer="alice")

    registry.set_install_policy(
        "tenant-consumer",
        {
            "allowed_namespaces": ["shared"],
            "allowed_kinds": ["storage_backend"],
            "allowed_submitters": ["platform"],
            "min_required_approvals": 2,
            "require_signature": True,
            "require_approved": True,
        },
    )

    explanation = registry.explain_install_policy(
        "tenant-cache",
        namespace="shared",
        tenant_id="tenant-consumer",
    )
    assert explanation["ok"] is False
    assert any("insufficient_approvals" in reason for reason in explanation["reasons"])

    with pytest.raises(PermissionError):
        registry.install(
            "tenant-cache",
            namespace="shared",
            tenant_id="tenant-consumer",
            destination=tmp_path / "installed",
        )

    registry.approve("tenant-cache", "0.1.0", namespace="shared", reviewer="bob")
    installed = registry.install(
        "tenant-cache",
        namespace="shared",
        tenant_id="tenant-consumer",
        workspace_id="prod",
        destination=tmp_path / "installed",
    )
    assert installed["ok"] is True
    assert installed["tenant_id"] == "tenant-consumer"
    assert installed["policy"]["ok"] is True
    assert Path(installed["destination"]).exists()


def test_registry_cli_policy_flow_and_sdk_quickstart(tmp_path: Path) -> None:
    extension = scaffold_project(kind="auth", name="tenant-auth", output_dir=tmp_path)
    registry_root = tmp_path / "registry"
    destination = tmp_path / "installed"

    publish_result = runner.invoke(
        cli.app,
        [
            "registry",
            "publish",
            str(extension.root),
            "--root",
            str(registry_root),
            "--namespace",
            "catalog",
            "--submitted-by",
            "platform",
            "--json",
        ],
    )
    assert publish_result.exit_code == 0
    publish_payload = json.loads(publish_result.stdout)
    assert publish_payload["entry"]["signature"]

    runner.invoke(
        cli.app,
        ["registry", "approve", "tenant-auth", "0.1.0", "--root", str(registry_root), "--namespace", "catalog", "--reviewer", "alice", "--json"],
    )

    policy_result = runner.invoke(
        cli.app,
        [
            "registry",
            "policy-set",
            "consumer-a",
            "--root",
            str(registry_root),
            "--allowed-namespace",
            "catalog",
            "--allowed-kind",
            "auth_provider",
            "--allowed-submitter",
            "platform",
            "--json",
        ],
    )
    assert policy_result.exit_code == 0
    assert json.loads(policy_result.stdout)["policy"]["allowed_kinds"] == ["auth_provider"]

    explain_result = runner.invoke(
        cli.app,
        [
            "registry",
            "policy-explain",
            "tenant-auth",
            "--root",
            str(registry_root),
            "--namespace",
            "catalog",
            "--tenant",
            "consumer-a",
            "--json",
        ],
    )
    assert explain_result.exit_code == 0
    explain_payload = json.loads(explain_result.stdout)
    assert explain_payload["ok"] is True
    assert explain_payload["verification"]["signature_ok"] is True

    install_result = runner.invoke(
        cli.app,
        [
            "registry",
            "install",
            "tenant-auth",
            "--root",
            str(registry_root),
            "--namespace",
            "catalog",
            "--tenant",
            "consumer-a",
            "--workspace",
            "prod",
            "--destination",
            str(destination),
            "--json",
        ],
    )
    assert install_result.exit_code == 0
    install_payload = json.loads(install_result.stdout)
    assert Path(install_payload["destination"]).exists()
    assert install_payload["policy"]["ok"] is True

    quickstart_result = runner.invoke(cli.app, ["sdk", "quickstart", "--kind", "auth", "--json"])
    assert quickstart_result.exit_code == 0
    quickstart_payload = json.loads(quickstart_result.stdout)
    assert quickstart_payload["ok"] is True
    assert any("policy-set" in step for step in quickstart_payload["steps"])
