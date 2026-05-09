"""Schema-level tests for the regulated policy packs.

The policy packs under docs/regulated/policy_packs/ describe the
governance posture an operating organisation should expect when
adopting openMiura on the corresponding regulated workflow. These
tests check the structural integrity of every pack so that an
operator can rely on them as machine-readable input.

Semantic binding to the openMiura policy engine is on the roadmap
(the engine reads a different, legacy YAML format). When that
binding lands, this fixture grows into a full policy-engine round
trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKS_DIR = ROOT / "docs" / "regulated" / "policy_packs"

EXPECTED_PACKS = {
    "lab_release",
    "sop_review",
    "ooc_investigation",
    "deviation_report",
    "analytical_interpretation",
}


def _load_pack(name: str) -> dict:
    path = PACKS_DIR / f"{name}.yaml"
    assert path.exists(), f"missing policy pack: {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_policy_packs_directory_contains_expected_files() -> None:
    found = {p.stem for p in PACKS_DIR.glob("*.yaml")}
    assert EXPECTED_PACKS.issubset(found), (
        f"missing packs: {EXPECTED_PACKS - found}"
    )


@pytest.mark.parametrize("pack_name", sorted(EXPECTED_PACKS))
def test_pack_has_required_top_level_fields(pack_name: str) -> None:
    pack = _load_pack(pack_name)
    for field in ("name", "version", "description", "applies_to", "rules"):
        assert field in pack, f"{pack_name}: missing top-level field {field!r}"
    assert pack["name"] == pack_name, (
        f"{pack_name}.yaml: name field {pack['name']!r} does not match filename"
    )
    assert isinstance(pack["version"], str) and pack["version"], (
        f"{pack_name}: version must be a non-empty string"
    )
    assert isinstance(pack["description"], str) and pack["description"].strip(), (
        f"{pack_name}: description must be non-empty"
    )


@pytest.mark.parametrize("pack_name", sorted(EXPECTED_PACKS))
def test_applies_to_section_is_well_formed(pack_name: str) -> None:
    pack = _load_pack(pack_name)
    applies_to = pack["applies_to"]
    assert isinstance(applies_to, dict)
    assert "workflows" in applies_to and isinstance(applies_to["workflows"], list)
    assert applies_to["workflows"], f"{pack_name}: applies_to.workflows must not be empty"
    for action in applies_to["workflows"]:
        assert isinstance(action, str) and action, (
            f"{pack_name}: every workflows entry must be a non-empty string"
        )


@pytest.mark.parametrize("pack_name", sorted(EXPECTED_PACKS))
def test_rules_have_unique_ids_and_required_fields(pack_name: str) -> None:
    pack = _load_pack(pack_name)
    rules = pack["rules"]
    assert isinstance(rules, list) and rules, f"{pack_name}: rules must be a non-empty list"
    seen_ids: set[str] = set()
    for rule in rules:
        assert isinstance(rule, dict)
        assert "id" in rule and "on_action" in rule, (
            f"{pack_name}: every rule must have id and on_action"
        )
        assert rule["id"] not in seen_ids, (
            f"{pack_name}: duplicate rule id {rule['id']}"
        )
        seen_ids.add(rule["id"])
        assert isinstance(rule["on_action"], str) and rule["on_action"], (
            f"{pack_name}.{rule['id']}: on_action must be a non-empty string"
        )


@pytest.mark.parametrize("pack_name", sorted(EXPECTED_PACKS))
def test_require_approval_blocks_have_role_and_meaning(pack_name: str) -> None:
    pack = _load_pack(pack_name)
    for rule in pack["rules"]:
        ra = rule.get("require_approval")
        if ra is None:
            continue
        assert isinstance(ra, dict)
        assert "role" in ra and isinstance(ra["role"], str) and ra["role"], (
            f"{pack_name}.{rule['id']}: require_approval.role must be a non-empty string"
        )
        assert "meaning" in ra and isinstance(ra["meaning"], str) and ra["meaning"], (
            f"{pack_name}.{rule['id']}: require_approval.meaning must be a non-empty string"
        )
        if "multi_party" in ra:
            assert isinstance(ra["multi_party"], bool)


@pytest.mark.parametrize("pack_name", sorted(EXPECTED_PACKS))
def test_require_evidence_lists_known_artefacts(pack_name: str) -> None:
    pack = _load_pack(pack_name)
    known = {
        "audit_trail",
        "approvals",
        "signed_manifest",
        "signer_identity",
        "policy_snapshot",
        "sop_diff",
        "prior_version_hash",
        "new_version_hash",
        "tool_calls",
        "hypothesis_list",
        "investigator_interventions",
        "investigation_tree",
        "hypothesis_history",
        "closure_record",
        "classification_history",
        "impact_assessment",
        "capa_record",
        "spectrum_hash",
        "prompt_and_completion",
        "model_identifier",
        "reviewer_identity",
    }
    for rule in pack["rules"]:
        re_block = rule.get("require_evidence")
        if re_block is None:
            continue
        include = re_block.get("include", [])
        assert isinstance(include, list) and include, (
            f"{pack_name}.{rule['id']}: require_evidence.include must be a non-empty list"
        )
        for art in include:
            assert art in known, (
                f"{pack_name}.{rule['id']}: unknown evidence artefact {art!r}; "
                f"add it to the known set in this test if intentional"
            )


def test_lab_release_has_qp_signature_rule() -> None:
    pack = _load_pack("lab_release")
    qp_rules = [r for r in pack["rules"] if r.get("require_approval", {}).get("role") == "qp_release"]
    assert qp_rules, "lab_release pack must require a Qualified Person signature"


def test_sop_review_requires_two_independent_approvals() -> None:
    pack = _load_pack("sop_review")
    publish_rules = [r for r in pack["rules"] if r["on_action"] == "workflows.sop.publish"]
    approver_roles = {
        r["require_approval"]["role"]
        for r in publish_rules
        if "require_approval" in r
    }
    assert len(approver_roles) >= 2, (
        "sop_review must require at least two distinct approver roles for publish"
    )


def test_ooc_investigation_closure_requires_capa_reference() -> None:
    pack = _load_pack("ooc_investigation")
    closure_rules = [r for r in pack["rules"] if r["on_action"] == "workflows.investigation.close"]
    assert any(
        "capa_reference" in r.get("require_payload_fields", [])
        for r in closure_rules
    ), "ooc_investigation closure must require a CAPA reference"


def test_deviation_critical_requires_director_level_approval() -> None:
    pack = _load_pack("deviation_report")
    critical_rules = [
        r for r in pack["rules"]
        if r.get("when_payload_matches", {}).get("classification") == "critical"
    ]
    assert critical_rules, "deviation_report must have a rule scoped to critical deviations"
    director_rules = [
        r for r in critical_rules
        if r.get("require_approval", {}).get("role") == "qa_deviation_director"
    ]
    assert director_rules, "critical deviations must require qa_deviation_director approval"


def test_analytical_interpretation_pins_model_version() -> None:
    pack = _load_pack("analytical_interpretation")
    draft_rules = [r for r in pack["rules"] if r["on_action"] == "workflows.analysis.draft"]
    pinned = [
        r for r in draft_rules
        if "model_version" in r.get("require_payload_fields", [])
    ]
    assert pinned, "analytical_interpretation must pin model_version on draft"
