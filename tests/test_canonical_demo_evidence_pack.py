"""Acceptance test for the canonical demo evidence pack.

The canonical demo (`scripts/run_canonical_demo.py`) walks a real
end-to-end governed-runtime flow: scope check, policy evaluation,
approval gate creation, canvas operator action that approves the
gate, runtime version activation, signed release records, audit
trail. It writes a structured JSON report at the end and exits 0
when every guardrail held.

This test exercises the demo on a temp directory and asserts the
**structural** properties of the JSON report — the contract that
the regulated whitepaper (`docs/regulated/whitepaper.md` §6) and
the use-case documents in `docs/regulated/use_cases/` claim
openMiura honours.

Why these assertions:

- `success=True` is the bare smoke; without it the rest is noise.
- Every `validation` flag in the report must be true (9 booleans
  that map one-to-one to claims in the whitepaper).
- The `approval` block on the current version must reference a
  real approver and a decided_at timestamp (21 CFR §11.50:
  signer + meaning + timestamp).
- The audit trail (`admin_events`) and the runtime timeline must
  be non-empty (Annex 11 control 9 / ALCOA+ Complete +
  Consistent).
- The scope triple is present and consistent across the report
  (scope isolation contract).

This is the *vendor-side* OQ artefact for the regulated material.
Operating organisations would extend it with their own PQ
scenarios.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_canonical_demo.py"

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

EXPECTED_VALIDATION_FLAGS = (
    "admin_events_available",
    "approval_required",
    "blocked_before_approval",
    "canvas_operator_action_visible",
    "current_version_matches",
    "executed_after_approval",
    "pending_approval_visible",
    "runtime_timeline_available",
    "signed_release_present",
)


@pytest.fixture(scope="module")
def demo_report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Run the canonical demo once per test module and return the parsed report."""
    output = tmp_path_factory.mktemp("canonical_demo") / "report.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"canonical demo failed (exit {result.returncode}); "
        f"stdout: {result.stdout}; stderr: {result.stderr}"
    )
    assert output.exists(), "demo did not write the output JSON"
    return json.loads(output.read_text(encoding="utf-8"))


# ---------- Top-level guarantees ---------------------------------------------


def test_report_says_success(demo_report: dict) -> None:
    assert demo_report.get("success") is True


def test_report_has_the_four_top_sections(demo_report: dict) -> None:
    for key in ("demo", "execution", "steps", "validation"):
        assert key in demo_report, f"missing top-level section: {key!r}"


# ---------- Validation flags --------------------------------------------------


@pytest.mark.parametrize("flag", EXPECTED_VALIDATION_FLAGS)
def test_validation_flag_is_true(demo_report: dict, flag: str) -> None:
    validation = demo_report["validation"]
    assert flag in validation, f"validation does not expose {flag!r}"
    assert validation[flag] is True, (
        f"validation.{flag} must be true; got {validation[flag]!r}"
    )


def test_validation_has_no_unknown_flags(demo_report: dict) -> None:
    """If the demo grows new flags, fail the test so we update the contract."""
    actual = set(demo_report["validation"].keys())
    extra = actual - set(EXPECTED_VALIDATION_FLAGS)
    assert not extra, (
        f"unrecognised validation flags: {sorted(extra)}. "
        f"Either add them to EXPECTED_VALIDATION_FLAGS or remove from the demo."
    )


# ---------- Identifier contracts ---------------------------------------------


def test_runtime_id_and_approval_id_are_valid_uuids(demo_report: dict) -> None:
    demo = demo_report["demo"]
    runtime_id = demo.get("runtime_id")
    approval_id = demo.get("approval_id")
    assert isinstance(runtime_id, str) and UUID_RE.match(runtime_id), (
        f"runtime_id is not a valid UUID: {runtime_id!r}"
    )
    assert isinstance(approval_id, str) and UUID_RE.match(approval_id), (
        f"approval_id is not a valid UUID: {approval_id!r}"
    )


def test_scope_triple_is_complete(demo_report: dict) -> None:
    scope = demo_report["demo"].get("scope") or {}
    for key in ("tenant_id", "workspace_id", "environment"):
        assert scope.get(key), f"demo.scope.{key} missing or empty"


# ---------- Signature & approval contract (21 CFR §11.50) --------------------


def test_current_version_carries_an_approval(demo_report: dict) -> None:
    cv = demo_report["steps"]["versions_after_approval"]["current_version"]
    approval = cv.get("approval")
    assert isinstance(approval, dict), (
        "current_version.approval must be a dict (the approval gate that "
        "released this version)"
    )
    assert approval.get("approval_id"), "approval.approval_id missing"
    assert approval.get("decided_at"), "approval.decided_at missing (timestamp)"
    assert approval.get("decided_by"), "approval.decided_by missing (signer)"


def test_current_version_status_is_active_post_approval(demo_report: dict) -> None:
    cv = demo_report["steps"]["versions_after_approval"]["current_version"]
    assert cv.get("status") == "active", (
        f"after approval, the current version status must be 'active'; "
        f"got {cv.get('status')!r}"
    )


def test_current_version_approval_id_matches_top_level(demo_report: dict) -> None:
    cv = demo_report["steps"]["versions_after_approval"]["current_version"]
    assert cv["approval"]["approval_id"] == demo_report["demo"]["approval_id"], (
        "the approval_id reported at the top level must be the one bound to "
        "the activated version (signature/record linking, 21 CFR §11.70)"
    )


# ---------- Audit trail completeness -----------------------------------------


def test_admin_events_recorded(demo_report: dict) -> None:
    admin_events = demo_report["steps"]["admin_events"]
    assert admin_events.get("ok") is True
    items = admin_events.get("items")
    assert isinstance(items, list) and len(items) >= 1, (
        "admin_events.items must be a non-empty list (audit trail contract)"
    )


def test_runtime_timeline_recorded(demo_report: dict) -> None:
    rt = demo_report["steps"]["runtime_timeline"]
    assert rt.get("ok") is True
    timeline = rt.get("timeline")
    assert isinstance(timeline, list) and len(timeline) >= 1, (
        "runtime_timeline.timeline must be a non-empty list"
    )


def test_pending_approvals_were_visible_before_decision(demo_report: dict) -> None:
    pa = demo_report["steps"]["pending_approvals_before_decision"]
    assert pa.get("ok") is True
    items = pa.get("items")
    assert isinstance(items, list) and len(items) >= 1, (
        "before approval, the pending_approvals_before_decision list must be "
        "non-empty (proves the gate existed and was visible to operators)"
    )


# ---------- Canvas operator action -------------------------------------------


def test_canvas_approval_action_was_executed_by_operator(demo_report: dict) -> None:
    car = demo_report["steps"]["canvas_approval_result"]
    assert car.get("ok") is True
    assert car.get("action") == "approve_governance_promotion", (
        "the canvas action that approved the gate must be "
        "'approve_governance_promotion'"
    )
    assert car.get("reconciled") is True, (
        "after the canvas action the system must report reconciled=True "
        "(operator action consistent with backend state)"
    )


def test_scope_is_consistent_across_sections(demo_report: dict) -> None:
    expected = demo_report["demo"]["scope"]
    locations = [
        ("steps.versions_after_approval.scope", demo_report["steps"]["versions_after_approval"].get("scope")),
        ("steps.pending_approvals_before_decision.scope", demo_report["steps"]["pending_approvals_before_decision"].get("scope")),
        ("steps.canvas_approval_result.scope", demo_report["steps"]["canvas_approval_result"].get("scope")),
    ]
    for name, scope in locations:
        assert scope == expected, (
            f"{name} disagrees with demo.scope: {scope!r} vs {expected!r}"
        )
