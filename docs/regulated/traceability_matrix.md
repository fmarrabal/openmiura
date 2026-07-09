# Traceability matrix — controls ↔ tests

> Status: `beta`. This consolidates the control-by-control mappings
> ([21 CFR Part 11](mapping_21cfr_part11.md), [EU GMP Annex 11](mapping_eu_gmp_annex11.md),
> [GAMP 5](mapping_gamp5.md), [ALCOA+](alcoa_plus_self_assessment.md)) into a
> single view that links each control to the **executable tests** that evidence
> it. This is a *mapping and validation-strategy* artifact, **not** a
> declaration of conformance — conformance is asserted by an organisation
> operating a validated quality system, not by a repository.

## How to read this

Each row cites the test file(s) or glob(s) that exercise the corresponding
openMiura capability. The `Test evidence` cells are **machine-checked**: the
test [`tests/test_regulated_traceability.py`](../../tests/test_regulated_traceability.py)
parses every `` `tests/...` `` token in this table and fails if any of them no
longer matches at least one collected test file — so the matrix cannot silently
rot as tests are renamed or removed.

Status legend: `Stable` (implemented + tested + documented) · `Beta`
(implemented + tested, docs partial) · `Partial` (some sub-controls) ·
`Experimental` (placeholder).

## Matrix

| Framework | Control | openMiura capability | Test evidence | Status |
|---|---|---|---|---|
| 21 CFR Part 11 | §11.10(d) — limit system access to authorized individuals | RBAC (`auth_repo`): api tokens, auth users/sessions, role-gated routes; bootstrap admin only via env | `tests/test_phase2_rbac_*.py` | Beta |
| 21 CFR Part 11 | §11.10(e) — secure, computer-generated, time-stamped audit trail | Append-only `events` / `tool_calls` / `decision_traces`, each row **hash-chained** (row_hash/prev_hash/chain_seq) and engine-level tamper-proof; offline `openmiura db verify-chain` | `tests/test_phase5_decision_trace_*.py`, `tests/unit/test_audit_hashchain_*.py` | Beta |
| 21 CFR Part 11 | §11.10(g) — authority checks before signing / acting | Signature-grade approval enforcement: identity resolution, anti-self-approval (creator/submitter, canonicalized), n-of-m distinct-approver quorum | `tests/test_phase4_policy_admin.py`, `tests/unit/test_sig_approvals_pr4_policy.py` | Beta |
| 21 CFR Part 11 | §11.10(b) — accurate, complete, human-readable copies | Signed evidence-pack export (ed25519, SHA-256 manifest of every artifact); offline `openmiura verify` re-checks it on a clean machine | `tests/test_cli_verify_pack.py`, `tests/test_openclaw_portfolio_evidence_packaging_v2.py` | Beta |
| 21 CFR Part 11 | §11.50 — signature manifestation (signer + timestamp + meaning) | Approval gate requires all three at write time; each approval also carries a standalone ed25519 signature over its canonical tuple | `tests/test_phase3_approval_*.py`, `tests/unit/test_sig_approvals_pr6_signature.py` | Beta |
| 21 CFR Part 11 | §11.70 — signature/record linking | Approvals are hash-chained per (table, scope); the chain head is attested inside the signed evidence pack | `tests/unit/test_sig_approvals_pr2_chain.py`, `tests/test_audit_hashchain_pr5_pack.py` | Beta |
| 21 CFR Part 11 | §11.200 — e-signature components & controls (second factor, non-repudiation) | TOTP second factor (encrypted at rest, fail-closed without a KEK), **single-use** codes, wired into the approval HTTP path | `tests/unit/test_sig_approvals_pr3_totp.py`, `tests/unit/test_sig_approvals_pr7_singleuse.py`, `tests/test_sig_approvals_pr5_http.py` | Beta |
| EU GMP Annex 11 | §9 / §12 — audit trail & access, integrity of records | Tamper-evident audit hash-chain + RBAC; tamper is detectable offline against the live DB | `tests/unit/test_audit_hashchain_*.py`, `tests/test_phase2_rbac_*.py` | Beta |
| ALCOA+ | *Attributable* — who did it | Approvals bind a resolved `signer_user_key`; signer authenticity is bindable to a known key via trust anchors in `openmiura verify` | `tests/unit/test_sig_approvals_pr6_signature.py`, `tests/test_cli_verify_trust_anchors.py` | Beta |
| ALCOA+ | *Contemporaneous / Original* — when it happened | RFC 3161 trusted timestamp over the pack signature, verified **offline** (imprint + TSA signature; `trusted` when a TSA anchor is supplied) | `tests/unit/test_rfc3161_verify.py`, `tests/test_rfc3161_issue.py`, `tests/test_cli_verify_timestamp.py` | Beta |
| ALCOA+ | *Enduring / Available* — retrievable copies | Evidence pack + configurable backups; `openmiura db backup` / `restore` | `tests/test_cli_verify_pack.py`, `tests/test_sprint8_installation_smoke.py` | Partial |
| GAMP 5 | Risk-based verification — a runnable end-to-end proof | Canonical governed-runtime demo produces a real signed audit trail with approvals | `tests/test_openclaw_portfolio_evidence_packaging_v2.py` | Beta |

## What this does not claim

- Controls marked `n/a` in the per-framework tables (device checks, personnel
  qualification, written organisational policies) are **out of the technical
  layer** and are not represented here.
- A green matrix proves the cited tests exist and pass in CI; it does **not**
  prove operational qualification (IQ/OQ/PQ) of a specific deployment, which is
  the operating organisation's responsibility.

See also: [whitepaper](whitepaper.md), and the per-framework mappings linked at
the top.
