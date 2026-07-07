from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_container_workflow_builds_and_pushes_to_ghcr() -> None:
    workflow = _load(".github/workflows/container.yml")

    # Least-privilege top level; only the build job may write packages.
    assert workflow["permissions"]["contents"] == "read"
    job = workflow["jobs"]["build-push-image"]
    assert job["permissions"]["packages"] == "write"

    steps = job["steps"]
    uses = [str(s.get("uses", "")) for s in steps]
    assert any(u.startswith("docker/login-action@") for u in uses)
    assert any(u.startswith("docker/build-push-action@") for u in uses)

    meta = next(s for s in steps if str(s.get("uses", "")).startswith("docker/metadata-action@"))
    assert meta["with"]["images"] == "ghcr.io/fmarrabal/openmiura"

    build = next(s for s in steps if str(s.get("uses", "")).startswith("docker/build-push-action@"))
    # PR runs are build-only (no push); Release / dispatch push.
    assert build["with"]["push"] == "${{ github.event_name != 'pull_request' }}"

    # PRs that touch the image trigger the regression build.
    assert "Dockerfile" in workflow["on"]["pull_request"]["paths"]
    assert workflow["on"]["release"]["types"] == ["published"]


def test_dockerfile_and_entrypoint_are_present() -> None:
    assert (ROOT / "Dockerfile").exists()
    entrypoint = ROOT / "docker" / "entrypoint.sh"
    assert entrypoint.exists()
    # The image installs the package and runs the CLI; both must be wired.
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install ." in dockerfile
    assert "/app/docker/entrypoint.sh" in dockerfile
    # A `<<heredoc` is NOT valid in a Dockerfile — buildkit reads each following
    # line as its own instruction (this broke the HEALTHCHECK). Keep it out.
    assert "<<" not in dockerfile
