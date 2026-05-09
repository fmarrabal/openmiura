"""Smoke test for the UAL NMR pilot of openMiura.

Walks a synthetic NMR-interpretation workflow end to end against the
``nmr_interpretation`` policy pack:

    upload -> agent draft -> reviewer signature -> PI signature
                                                 -> evidence pack

The script does not contact a live openMiura server; it loads the
policy pack, evaluates the rules against a deterministic synthetic
payload, and writes a structured JSON report. It is the
*vendor-side* OQ artefact for the pilot described under
``docs/regulated/pilot_ual/README.md`` and is intended to be safe to
run in CI.

Run as:
    python scripts/run_pilot_ual_nmr_demo.py \\
        --output /tmp/pilot-ual-nmr.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "regulated" / "policy_packs" / "nmr_interpretation.yaml"


def load_pack() -> Dict[str, Any]:
    return yaml.safe_load(PACK_PATH.read_text(encoding="utf-8"))


def synthetic_spectrum_payload() -> Dict[str, Any]:
    """Deterministic synthetic NMR payload for the smoke test.

    Real spectra are out of scope for the smoke test; this is a
    placeholder that exercises every required field of the
    `nmr_interpretation` pack without claiming to be scientifically
    meaningful.
    """
    sample_text = (
        "synthetic ¹H NMR spectrum, organometallic catalyst, "
        "CDCl3, TMS reference, 500 MHz, 298 K"
    )
    spectrum_sha256 = hashlib.sha256(sample_text.encode("utf-8")).hexdigest()
    prompt_text = (
        "Assign the principal peaks of the following ¹H NMR spectrum "
        "of an organometallic catalyst sample. Flag any unknown "
        "impurity above 5% relative intensity. Pin model name and "
        "version."
    )
    prompt_sha256 = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    return {
        "spectrum_sha256": spectrum_sha256,
        "instrument_id": "ual-nmr-500-A",
        "acquisition_timestamp": "2026-05-09T08:00:00Z",
        "solvent": "CDCl3",
        "reference_compound": "TMS",
        "model_name": "openmiura-research-mock",
        "model_version": "0.0.1-pilot",
        "prompt_sha256": prompt_sha256,
        "contains_unknown_impurity_above_threshold": False,
        "contains_new_ligand_identification": False,
        "sample_paramagnetic": False,
        "scope": {
            "tenant_id": "ual",
            "workspace_id": "nmrmbc",
            "environment": "research",
        },
    }


def evaluate_rules(pack: Dict[str, Any], action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Tiny rule evaluator sufficient for the smoke test.

    The current openMiura policy engine reads a different YAML
    format. This evaluator exists only to validate the
    nmr_interpretation pack at the structural and predicate level
    until the proper engine binding lands.
    """
    matched: List[Dict[str, Any]] = []
    denied = False
    deny_reasons: List[str] = []
    required_signers: List[Dict[str, str]] = []

    for rule in pack.get("rules", []):
        rule_action = rule.get("on_action", "")
        if rule_action.endswith("*"):
            if not action.startswith(rule_action[:-1]):
                continue
        else:
            if rule_action != action:
                continue

        when = rule.get("when_payload_matches") or {}
        if when:
            if not all(payload.get(k) == v for k, v in when.items()):
                continue

        for field in rule.get("require_payload_fields", []) or []:
            if payload.get(field) in (None, ""):
                denied = True
                deny_reasons.append(
                    f"{rule['id']}: missing required payload field {field!r}"
                )

        scope_match = rule.get("enforce_scope_match") or {}
        if scope_match:
            for key, requirement in scope_match.items():
                if requirement == "required" and not payload.get("scope", {}).get(f"{key}_id" if key != "environment" else "environment"):
                    denied = True
                    deny_reasons.append(
                        f"{rule['id']}: scope.{key} is required and missing"
                    )

        approval = rule.get("require_approval")
        if approval:
            required_signers.append({
                "rule_id": rule["id"],
                "role": approval["role"],
                "meaning": approval["meaning"],
                "multi_party": bool(approval.get("multi_party", False)),
            })

        if rule.get("deny_without_approval") and not approval:
            denied = True
            deny_reasons.append(f"{rule['id']}: deny_without_approval without an approval block")

        matched.append({"id": rule["id"], "matched": True})

    return {
        "matched_rules": matched,
        "required_signers": required_signers,
        "denied": denied,
        "deny_reasons": deny_reasons,
    }


def sign(role: str, meaning: str) -> Dict[str, Any]:
    return {
        "signer": f"pilot-{role}-{uuid.uuid4()}",
        "role": role,
        "meaning": meaning,
        "timestamp": time.time(),
    }


def build_evidence_pack(
    payload: Dict[str, Any],
    draft_eval: Dict[str, Any],
    publish_eval: Dict[str, Any],
    reviewer_signature: Dict[str, Any],
    pi_signature: Dict[str, Any],
    pack: Dict[str, Any],
) -> Dict[str, Any]:
    artefacts = {
        "spectrum_sha256": payload["spectrum_sha256"],
        "prompt_sha256": payload["prompt_sha256"],
        "model_identifier": f"{payload['model_name']}@{payload['model_version']}",
        "scope": payload["scope"],
        "policy_version": pack["version"],
    }
    manifest_text = json.dumps(artefacts, sort_keys=True)
    artefacts["manifest_sha256"] = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
    artefacts["signatures"] = [reviewer_signature, pi_signature]
    artefacts["draft_evaluation"] = draft_eval
    artefacts["publish_evaluation"] = publish_eval
    return artefacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="demo_artifacts/pilot-ual-nmr-report.json",
        help="Path to write the JSON report.",
    )
    parser.add_argument(
        "--unknown-impurity",
        action="store_true",
        help="Simulate the unknown-impurity escalation path.",
    )
    args = parser.parse_args()

    pack = load_pack()
    payload = synthetic_spectrum_payload()
    if args.unknown_impurity:
        payload["contains_unknown_impurity_above_threshold"] = True

    draft_eval = evaluate_rules(pack, "workflows.analysis.nmr.draft", payload)
    if draft_eval["denied"]:
        report = {
            "success": False,
            "stage": "draft",
            "deny_reasons": draft_eval["deny_reasons"],
            "policy_version": pack["version"],
        }
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"pilot demo failed at draft stage; report at {args.output}")
        return 1

    publish_eval = evaluate_rules(pack, "workflows.analysis.nmr.publish", payload)
    required_roles = {s["role"] for s in publish_eval["required_signers"]}
    if "nmr_reviewer" not in required_roles and "pi_approver" not in required_roles:
        report = {
            "success": False,
            "stage": "publish",
            "deny_reasons": ["no signer role required by the policy pack"],
            "policy_version": pack["version"],
        }
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"pilot demo failed at publish policy evaluation; report at {args.output}")
        return 1

    reviewer_signature = sign(
        role="nmr_reviewer",
        meaning="reviewed; assignments match spectrum and known chemistry",
    )
    pi_signature = sign(
        role="pi_approver",
        meaning=(
            "approved for laboratory notebook despite unknown impurity flag"
            if payload["contains_unknown_impurity_above_threshold"]
            else "approved for laboratory notebook"
        ),
    )

    pack_record = build_evidence_pack(
        payload, draft_eval, publish_eval, reviewer_signature, pi_signature, pack,
    )

    report = {
        "success": True,
        "stage": "evidence_pack_written",
        "policy_version": pack["version"],
        "scope": payload["scope"],
        "model_identifier": pack_record["model_identifier"],
        "evidence_pack": pack_record,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"pilot UAL NMR demo report written to {args.output}")
    print(f"success={bool(report['success'])}")
    print(f"policy_version={report['policy_version']}")
    print(f"manifest_sha256={pack_record['manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
