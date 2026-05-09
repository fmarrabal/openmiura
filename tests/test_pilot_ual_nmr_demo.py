"""Smoke test for the UAL NMR pilot demo script.

The script ``scripts/run_pilot_ual_nmr_demo.py`` is the vendor-side
OQ artefact for the pilot described under
``docs/regulated/pilot_ual/README.md``. This test exercises both the
routine path (`nmr_reviewer` only) and the escalation path
(unknown-impurity flag triggers `pi_approver`) and asserts the
expected structural properties of the produced report.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_pilot_ual_nmr_demo.py"


def _run(tmp_path: Path, *extra_args: str) -> dict:
    output = tmp_path / "pilot-ual-nmr.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output), *extra_args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"pilot demo failed (exit {result.returncode}); "
        f"stdout: {result.stdout}; stderr: {result.stderr}"
    )
    return json.loads(output.read_text(encoding="utf-8"))


def test_routine_path_writes_signed_evidence_pack(tmp_path: Path) -> None:
    report = _run(tmp_path)
    assert report["success"] is True
    assert report["stage"] == "evidence_pack_written"
    assert report["policy_version"]
    assert report["scope"] == {
        "tenant_id": "ual",
        "workspace_id": "nmrmbc",
        "environment": "research",
    }
    pack = report["evidence_pack"]
    assert pack["spectrum_sha256"]
    assert pack["prompt_sha256"]
    assert pack["model_identifier"]
    assert pack["manifest_sha256"]
    signatures = pack["signatures"]
    roles = {sig["role"] for sig in signatures}
    assert "nmr_reviewer" in roles
    assert "pi_approver" in roles
    for sig in signatures:
        assert sig["signer"]
        assert sig["meaning"]
        assert sig["timestamp"] > 0


def test_escalation_path_records_pi_meaning_for_unknown_impurity(tmp_path: Path) -> None:
    report = _run(tmp_path, "--unknown-impurity")
    assert report["success"] is True
    pack = report["evidence_pack"]
    pi_sigs = [s for s in pack["signatures"] if s["role"] == "pi_approver"]
    assert pi_sigs, "PI signature must be present in the escalation path"
    assert "unknown impurity" in pi_sigs[0]["meaning"].lower()


def test_demo_report_is_idempotent_for_same_synthetic_input(tmp_path: Path) -> None:
    """The synthetic payload is deterministic, so running twice
    must produce the same manifest hash. Signatures change because
    they include uuids and timestamps; the *artefact* hash does not."""
    report_a = _run(tmp_path / "a")
    report_b = _run(tmp_path / "b")
    assert (
        report_a["evidence_pack"]["manifest_sha256"]
        == report_b["evidence_pack"]["manifest_sha256"]
    )
