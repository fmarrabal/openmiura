from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import openmiura.cli as cli
from openmiura.extensions.sdk import ExtensionRegistry, scaffold_project


runner = CliRunner()


def test_extension_registry_publish_approve_install(tmp_path: Path) -> None:
    extension = scaffold_project(kind="tool", name="publishable-tool", output_dir=tmp_path)
    registry_root = tmp_path / "registry"
    destination = tmp_path / "installed"

    registry = ExtensionRegistry(registry_root)
    registry.init()
    published = registry.publish(extension.root, namespace="tenant-a", submitted_by="qa")
    assert published.status == "pending"

    approved = registry.approve("publishable-tool", "0.1.0", namespace="tenant-a", reviewer="admin", note="ok")
    assert approved.status == "approved"

    install_payload = registry.install("publishable-tool", namespace="tenant-a", destination=destination)
    assert install_payload["ok"] is True
    installed_root = Path(install_payload["destination"])
    assert (installed_root / "manifest.yaml").exists()


def test_registry_cli_flow(tmp_path: Path) -> None:
    extension = scaffold_project(kind="storage", name="registry-cache", output_dir=tmp_path)
    registry_root = tmp_path / "registry"
    destination = tmp_path / "installed"

    init_result = runner.invoke(cli.app, ["registry", "init", "--root", str(registry_root), "--json"])
    assert init_result.exit_code == 0

    publish_result = runner.invoke(
        cli.app,
        ["registry", "publish", str(extension.root), "--root", str(registry_root), "--namespace", "tenant-b", "--submitted-by", "curro", "--json"],
    )
    assert publish_result.exit_code == 0
    publish_payload = json.loads(publish_result.stdout)
    assert publish_payload["entry"]["status"] == "pending"

    list_result = runner.invoke(cli.app, ["registry", "list", "--root", str(registry_root), "--namespace", "tenant-b", "--json"])
    assert list_result.exit_code == 0
    list_payload = json.loads(list_result.stdout)
    assert len(list_payload["entries"]) == 1
    assert list_payload["entries"][0]["name"] == "registry-cache"

    approve_result = runner.invoke(
        cli.app,
        ["registry", "approve", "registry-cache", "0.1.0", "--root", str(registry_root), "--namespace", "tenant-b", "--reviewer", "security", "--json"],
    )
    assert approve_result.exit_code == 0
    approve_payload = json.loads(approve_result.stdout)
    assert approve_payload["entry"]["status"] == "approved"

    install_result = runner.invoke(
        cli.app,
        ["registry", "install", "registry-cache", "--root", str(registry_root), "--namespace", "tenant-b", "--destination", str(destination), "--json"],
    )
    assert install_result.exit_code == 0
    install_payload = json.loads(install_result.stdout)
    assert Path(install_payload["destination"]).exists()


def test_registry_formal_review_flow_and_verification(tmp_path: Path) -> None:
    extension = scaffold_project(kind="tool", name="reviewable-tool", output_dir=tmp_path)
    registry_root = tmp_path / "registry"

    registry = ExtensionRegistry(registry_root)
    published = registry.publish(extension.root, namespace="tenant-c", submitted_by="builder")
    assert published.status == "pending"
    assert published.release_level == "initial"
    assert published.harness_report is not None
    assert published.compatibility["compatible"] is True

    in_review = registry.start_review("reviewable-tool", "0.1.0", namespace="tenant-c", reviewer="secops", note="triage")
    assert in_review.status == "in_review"

    approved = registry.approve("reviewable-tool", "0.1.0", namespace="tenant-c", reviewer="secops", note="approved")
    assert approved.status == "approved"
    assert len(approved.review_history) >= 3

    verification = registry.verify("reviewable-tool", "0.1.0", namespace="tenant-c")
    assert verification["ok"] is True

    described = registry.describe("reviewable-tool", "0.1.0", namespace="tenant-c")
    assert described.name == "reviewable-tool"


def test_registry_cli_extended_review_flow(tmp_path: Path) -> None:
    extension = scaffold_project(kind="tool", name="release-tool", output_dir=tmp_path)
    registry_root = tmp_path / "registry"

    publish_result = runner.invoke(
        cli.app,
        ["registry", "publish", str(extension.root), "--root", str(registry_root), "--namespace", "tenant-d", "--submitted-by", "ci", "--json"],
    )
    assert publish_result.exit_code == 0
    publish_payload = json.loads(publish_result.stdout)
    assert publish_payload["entry"]["harness_report"]["ok"] is True

    review_result = runner.invoke(
        cli.app,
        ["registry", "review-start", "release-tool", "0.1.0", "--root", str(registry_root), "--namespace", "tenant-d", "--reviewer", "reviewer-1", "--json"],
    )
    assert review_result.exit_code == 0
    assert json.loads(review_result.stdout)["entry"]["status"] == "in_review"

    approve_result = runner.invoke(
        cli.app,
        ["registry", "approve", "release-tool", "0.1.0", "--root", str(registry_root), "--namespace", "tenant-d", "--reviewer", "reviewer-1", "--json"],
    )
    assert approve_result.exit_code == 0

    verify_result = runner.invoke(
        cli.app,
        ["registry", "verify", "release-tool", "0.1.0", "--root", str(registry_root), "--namespace", "tenant-d", "--json"],
    )
    assert verify_result.exit_code == 0
    assert json.loads(verify_result.stdout)["ok"] is True

    describe_result = runner.invoke(
        cli.app,
        ["registry", "describe", "release-tool", "0.1.0", "--root", str(registry_root), "--namespace", "tenant-d", "--json"],
    )
    assert describe_result.exit_code == 0
    describe_payload = json.loads(describe_result.stdout)
    assert describe_payload["entry"]["release_level"] == "initial"
    assert len(describe_payload["entry"]["review_history"]) >= 3

    deprecate_result = runner.invoke(
        cli.app,
        ["registry", "deprecate", "release-tool", "0.1.0", "--root", str(registry_root), "--namespace", "tenant-d", "--reviewer", "reviewer-1", "--json"],
    )
    assert deprecate_result.exit_code == 0
    assert json.loads(deprecate_result.stdout)["entry"]["status"] == "deprecated"
