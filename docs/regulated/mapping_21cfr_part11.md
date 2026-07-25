# 21 CFR Part 11 — control-by-control mapping

This document maps the controls in *Title 21, Code of Federal
Regulations, Part 11 — Electronic Records; Electronic Signatures*
to the openMiura primitives that contribute to each control.

The full text is available at
<https://www.ecfr.gov/current/title-21/chapter-I/subchapter-A/part-11>.

## Status legend

| Label | Meaning |
|---|---|
| `Stable` | Implemented, tested, documented. |
| `Beta` | Implemented and tested; documentation partial. |
| `Partial` | Some sub-controls covered, others not. |
| `Experimental` | Placeholder code or proof-of-concept. |
| `n/a` | Out of scope for the openMiura technical layer (organisational, procedural or hardware control). |

The labels are conservative on purpose. Today the majority sit at
`Partial` or `Beta`. That reflects the state of the project, not a
limitation of the framework.

---

## Subpart B — Electronic Records

### §11.10 — Controls for closed systems

| Section | Title (paraphrased) | openMiura primitive(s) | Status | Evidence path |
|---|---|---|---|---|
| §11.10(a) | Validation of systems to ensure accuracy, reliability, consistent intended performance, and the ability to discern invalid or altered records | Test suite (`tests/`), canonical demo (`scripts/run_canonical_demo.py`), GAMP 5 risk assessment in [`mapping_gamp5.md`](mapping_gamp5.md) | `Partial` | `tests/`, `scripts/run_canonical_demo.py` |
| §11.10(b) | Ability to generate accurate and complete copies of records in human-readable and electronic form | Evidence pack export under `release_repo` and the operations canvas surface; signed manifest with SHA-256 of every embedded artefact | `Beta` | `evidence_packs/<id>.zip` |
| §11.10(c) | Protection of records to enable accurate and ready retrieval throughout the records retention period | Append-only audit trail at the persistence layer; backup directory configurable via `data/backups/`; **chain-of-custody integration with an external WORM store is `Experimental`** | `Partial` | `data/backups/`, `openmiura/persistence/` |
| §11.10(d) | Limiting system access to authorized individuals | RBAC via `auth_repo` (api tokens, auth users, auth sessions), bootstrap admin only via env var, role-aware route gating | `Beta` | `tests/test_phase2_rbac_*.py` |
| §11.10(e) | Use of secure, computer-generated, time-stamped audit trails to record date/time of operator entries and actions that create, modify, or delete records | Per-scope, append-only **hash chain** over `events`, `tool_calls`, `decision_traces` and `release_approvals` (each row hashes its canonical content plus the previous row's hash, so any edit breaks the chain; `events`/`tool_calls`/`decision_traces` additionally carry append-only `UPDATE`/`DELETE` database triggers, while `release_approvals` is chain-protected; the chain head is recomputed and matched by `openmiura db verify-chain` and attested inside the signed evidence pack); every write carries `signer`, `timestamp` and `meaning` | `Beta` | `tests/test_phase5_decision_trace_*.py`, `tests/unit/test_audit_hashchain_pr3_verify.py`, `tests/unit/test_audit_hashchain_pr4_triggers.py` |
| §11.10(f) | Use of operational system checks to enforce permitted sequencing of steps and events | `openmiura doctor` config validation; policy engine refuses out-of-sequence approvals (e.g. cannot promote a release before its approval gate is signed) | `Experimental` | `openmiura/cli.py`, `openmiura/persistence/release_repo.py` |
| §11.10(g) | Use of authority checks to ensure that only authorized individuals can use the system, electronically sign a record, access the operation or computer system input or output device, alter a record, or perform the operation at hand | Policy engine + approval-gate signer-role enforcement; signing attempts that don't match the policy's required role are rejected at write time | `Beta` | `tests/test_phase4_policy_admin.py` |
| §11.10(h) | Use of device (e.g., terminal) checks to determine, as appropriate, the validity of the source of data input or operational instruction | n/a — typically delivered by the host operating environment (corporate endpoint management, MDM, network controls) | `n/a` | — |
| §11.10(i) | Determination that persons who develop, maintain, or use electronic record/electronic signature systems have the education, training, and experience to perform their assigned tasks | n/a — organisational. The operating organisation's training records and qualification matrix sit outside openMiura | `n/a` | — |
| §11.10(j) | The establishment of, and adherence to, written policies that hold individuals accountable and responsible for actions initiated under their electronic signatures, in order to deter record and signature falsification | Policy YAML pack files in [`policy_packs/`](policy_packs/); the *organisational* policies (HR, code of conduct, falsification deterrence) remain organisational | `Experimental` | `policy_packs/` |
| §11.10(k) | Use of appropriate controls over systems documentation including: (1) Adequate controls over the distribution of, access to, and use of documentation for system operation and maintenance; (2) Revision and change control procedures to maintain an audit trail that documents time-sequenced development and modification of systems documentation | Repository under git with PR review; archived legacy material under [`docs/_archive/`](../_archive/); the change history of policy YAML files lives in git | `Partial` | git history, `docs/_archive/` |

### §11.30 — Controls for open systems

If the operating environment qualifies as an open system (e.g.
records traversing a public network outside the operating
organisation's control), additional controls are required:
encryption, digital signatures.

| Section | Title (paraphrased) | openMiura primitive(s) | Status | Evidence path |
|---|---|---|---|---|
| §11.30 | Procedures and controls for open systems including those identified in §11.10, additional measures including document encryption and digital signature standards | TLS termination is delegated to the deployment environment (reverse proxy); evidence pack signature uses a configurable signing key; encryption at rest is delegated to the database/filesystem layer | `Partial` | deployment-specific |

### §11.50 — Signature manifestations

| Section | Title (paraphrased) | openMiura primitive(s) | Status | Evidence path |
|---|---|---|---|---|
| §11.50(a) | Signed electronic records shall contain information associated with the signing that clearly indicates: (1) the printed name of the signer; (2) the date and time when the signature was executed; (3) the meaning (such as review, approval, responsibility, or authorship) associated with the signature | Approval gate enforces all three at write time: a gate that lacks any of `signer`, `timestamp` or `meaning` is rejected | `Beta` | `tests/test_phase3_approval_*.py` |
| §11.50(b) | The items identified in paragraphs (a)(1), (a)(2), and (a)(3) of this section shall be subject to the same controls as for electronic records and shall be included as part of any human readable form of the electronic record (such as electronic display or printout) | Evidence pack renders signer + timestamp + meaning alongside the signed record; the operations canvas displays the same fields in the operator UI | `Beta` | `evidence_packs/<id>.zip` |

### §11.70 — Signature/record linking

| Section | Title (paraphrased) | openMiura primitive(s) | Status | Evidence path |
|---|---|---|---|---|
| §11.70 | Electronic signatures and handwritten signatures executed to electronic records shall be linked to their respective electronic records to ensure that the signatures cannot be excised, copied, or otherwise transferred to falsify an electronic record by ordinary means | The approval-gate row carries `linked_record_id` referencing the gated action; both records are part of the same evidence-pack manifest with their hashes; deleting either breaks the manifest signature | `Beta` | `evidence_packs/<id>.zip` (manifest) |

---

## Subpart C — Electronic Signatures

### §11.100 — General requirements

| Section | Title (paraphrased) | openMiura primitive(s) | Status | Evidence path |
|---|---|---|---|---|
| §11.100(a) | Each electronic signature shall be unique to one individual and shall not be reused by, or reassigned to, anyone else | `auth_users` enforces unique principal IDs; signature records reference principal-id and not just role | `Partial` | `openmiura/persistence/auth_repo.py` |
| §11.100(b) | Before an organization establishes, assigns, certifies, or otherwise sanctions an individual's electronic signature, or any element of such electronic signature, the organization shall verify the identity of the individual | n/a — organisational identity verification (HR, IAM) is a prerequisite for openMiura; the project does not perform identity proofing | `n/a` | — |
| §11.100(c) | Persons using electronic signatures shall, prior to or at the time of such use, certify to the agency that the electronic signatures in their system, used on or after August 20, 1997, are intended to be the legally binding equivalent of traditional handwritten signatures | n/a — the certification letter to the FDA is an organisational obligation | `n/a` | — |

### §11.200 — Electronic signature components and controls

| Section | Title (paraphrased) | openMiura primitive(s) | Status | Evidence path |
|---|---|---|---|---|
| §11.200(a)(1)(i) | Employ at least two distinct identification components such as an identification code and password, in the case of a non-biometric signature | Single-factor (api token / password) is the default; on the signature-grade release-approval path a second factor is available — a single-use TOTP whose secret is encrypted at rest via an env-supplied key-encryption key | `Beta` | `tests/unit/test_sig_approvals_pr3_totp.py`, `tests/unit/test_sig_approvals_pr7_singleuse.py` |
| §11.200(a)(1)(ii) | The first signing in a continuous session shall require all components; subsequent signings shall require, at minimum, one component | Implemented through session lifetime + per-action challenge for sensitive routes | `Partial` | `openmiura/persistence/auth_repo.py` (auth_sessions) |
| §11.200(a)(1)(iii) | A signing not performed during a single, continuous period of controlled system access shall require all components | Session timeout enforced in `auth_repo`; rotating sessions on idle is `Beta` | `Partial` | `openmiura/persistence/auth_repo.py` (session timeout) |
| §11.200(a)(2) | Be used only by their genuine owners | Organisational control — genuine-owner use cannot be technically enforced at the platform layer (tied to the identity proofing of §11.100(b)) | `n/a` | — |
| §11.200(a)(3) | Be administered and executed to ensure that attempted use of an individual's electronic signature by anyone other than its genuine owner requires collaboration of two or more individuals | Signature-grade release approval enforces an *n*-of-*m* quorum of **distinct**, authenticated approvers end-to-end (the release creator and submitter are blocked from approving, and no signer may vote twice), each vote carrying a TOTP second factor and a per-approval Ed25519 signature on the same hash chain | `Beta` | `tests/test_sig_approvals_pr5_http.py`, `tests/unit/test_sig_approvals_pr4_policy.py`, `tests/unit/test_sig_approvals_pr6_signature.py` |
| §11.200(b) | Electronic signatures based upon biometrics shall be designed to ensure that they cannot be used by anyone other than their genuine owners | n/a — biometrics are out of scope for the technical layer | `n/a` | — |

### §11.300 — Controls for identification codes/passwords

| Section | Title (paraphrased) | openMiura primitive(s) | Status | Evidence path |
|---|---|---|---|---|
| §11.300(a) | Maintaining the uniqueness of each combined identification code and password | Unique constraint on principal id; password hashing in `auth_repo._hash_password` (PBKDF2, 200k iterations) | `Partial` | `openmiura/persistence/auth_repo.py:225` (`_hash_password`) |
| §11.300(b) | Ensuring that identification code and password issuances are periodically checked, recalled, or revised | Expiry / rotation hooks exist on api tokens and auth sessions; the *operational* periodic check is organisational | `Partial` | `openmiura/persistence/auth_repo.py` (token/session expiry) |
| §11.300(c) | Following loss management procedures to electronically deauthorize lost, stolen, missing, or otherwise potentially compromised tokens | `revoke_api_token`, `revoke_auth_session`, `revoke_auth_sessions_for_user` exist; the *procedure* (who calls them, when) is organisational | `Partial` | `openmiura/persistence/auth_repo.py:168,458,471` (`revoke_*`) |
| §11.300(d) | Use of transaction safeguards to prevent unauthorized use of passwords and/or identification codes, and to detect and report in an immediate and urgent manner any attempts at their unauthorized use | Login attempt logging, brute-force protection on /broker/auth/* via rate limiting; alerting integration is **`Experimental`** | `Partial` | `interfaces/http/routes/admin/_helpers.py:48` (`_rate_limit`); `tests/test_phase6_security_hardening.py` |
| §11.300(e) | Initial and periodic testing of devices, such as tokens or cards, that bear or generate identification code or password information to ensure that they function properly and have not been altered in an unauthorized manner | n/a — hardware tokens are out of scope | `n/a` | — |

---

## Summary

| Status | Count of controls |
|---|---:|
| Stable | 0 |
| Beta | 7 |
| Partial | 10 |
| Experimental | 2 |
| n/a (organisational/hardware) | 7 |
| **Total** | **26** |

The reading is straightforward: openMiura provides a credible
technical contribution to roughly half of the Part 11 controls,
particularly around the audit trail, the signature manifestation
and the signature/record linking. It does not, and cannot,
substitute the organisational controls that the framework also
demands.
