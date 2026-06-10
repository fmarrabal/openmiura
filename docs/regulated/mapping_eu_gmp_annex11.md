# EU GMP Annex 11 — control-by-control mapping

This document maps the controls in *EudraLex Volume 4, Annex 11
— Computerised Systems* to the openMiura primitives that
contribute to each control.

The full text is at
<https://health.ec.europa.eu/system/files/2016-11/annex11_01-2011_en_0.pdf>.

The 2011 version is the current published edition; a revision is
under public consultation at the time of writing. Update this
document when the revision is finalised.

## Status legend

Same legend as in [`mapping_21cfr_part11.md`](mapping_21cfr_part11.md):
`Stable` / `Beta` / `Partial` / `Experimental` / `n/a`.

---

## 1. Risk management

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 1 | Risk management should be applied throughout the lifecycle of the computerised system, taking into account patient safety, data integrity and product quality | The risk-assessment template in [`whitepaper.md §5.2`](whitepaper.md) is the openMiura-side input; the lifecycle assessment is organisational | `Partial` | Method documented; org-side enactment required |

## 2. Personnel

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 2 | There should be close cooperation between all relevant personnel such as Process Owner, System Owner, Qualified Persons and IT. All personnel should have appropriate qualifications, level of access and defined responsibilities | RBAC + scope isolation map onto the role triangle (process owner / system owner / QP) for the "level of access and defined responsibilities" half; qualifications and training are organisational | `Partial` | Access control vendor-side; qualifications org-side |

## 3. Suppliers and service providers

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 3.1 | Quality of service expected from suppliers should be defined in formal agreements | Open-source project; no formal commercial agreement. Organisations adopting openMiura should treat it as Category 4 software per GAMP 5 (configured product) | `n/a` | Documented in [`mapping_gamp5.md`](mapping_gamp5.md) |
| 3.2 | The competence and reliability of a supplier are key factors when selecting a product or service provider | Vendor docs at this whitepaper + [`docs/architecture/`](../architecture/) + the [`AGENTS.md`](../../AGENTS.md) disclosure | `Partial` | Vendor-side disclosure provided; org-side audit responsibility |
| 3.3 | Information and documentation accompanying commercial off-the-shelf products should be reviewed by regulated users | Vendor-side: this whitepaper, the architecture docs, the policy pack examples and the canonical demo provide the input | `Beta` | — |
| 3.4 | Quality system and audit information relating to suppliers or developers of software and implemented systems should be made available to inspectors on request | The repository's history, [`AGENTS.md`](../../AGENTS.md), [`docs/_workjournal/`](../_workjournal/) and the test suite are public and inspectable | `Beta` | — |

## 4. Validation

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 4.1 | The validation documentation and reports should cover the relevant steps of the life cycle | V-model in [`whitepaper.md §5.1`](whitepaper.md) + the migration path in §5.4 | `Partial` | Org-side enactment required |
| 4.2 | An up to date listing of all relevant systems and their GMP functionality should be available | n/a — a system inventory is an organisational artefact | `n/a` | Org-side |
| 4.3 | User Requirements Specifications should describe the required functions of the computerised system, traceable throughout the life cycle | URS template documented in §5.1 of the whitepaper | `Partial` | Org-side enactment |
| 4.4 | The regulated user should take all reasonable steps to ensure that the system has been developed in accordance with an appropriate quality management system | Vendor-side QMS approximation: PR review, automated tests, signed releases | `Beta` | — |
| 4.5 | Evidence of appropriate test methods and test scenarios should be demonstrated | Test suite (`tests/`) + canonical demo + policy-pack regression tests | `Beta` | `tests/` |
| 4.6 | If data are transferred to another data format or system, validation should include checks that data are not altered in value and/or meaning during this migration process | Data migration via `core/migrations.py`; integrity preserved by SQL constraints; an explicit migration verification report is **`Experimental`** | `Partial` | `core/migrations.py` |
| 4.7 | The application should be validated; IT infrastructure should be qualified | Application validation evidence is on the vendor side (this repo + tests); IT infrastructure qualification is organisational | `Partial` | Org-side IQ |
| 4.8 | Periodic re-evaluation should be performed | n/a — organisational schedule | `n/a` | Org-side |

## 5. Data

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 5 | Computerised systems exchanging data electronically with other systems should include appropriate built-in checks for the correct and secure entry and processing of data | Pydantic schema validation on every HTTP entry point; SQLite/Postgres FK constraints; structured payload hashes in evidence packs | `Beta` | `_models.py`, `evidence_packs/` |

## 6. Accuracy checks

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 6 | For critical data entered manually, there should be an additional check on the accuracy of the data | Approval gates on critical writes; the policy pack determines which writes are "critical" | `Beta` | `policy_packs/` |

## 7. Data storage

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 7.1 | Data should be secured by both physical and electronic means against damage. Stored data should be checked for accessibility, readability and accuracy | Logical: append-only audit trail with SHA-256 manifests; physical: backup directory + organisation's storage policy | `Partial` | Logical layer Beta; physical layer org-side |
| 7.2 | Regular back-ups of all relevant data should be done. Integrity and accuracy of back-up data and the ability to restore the data should be checked during validation and monitored periodically | `data/backups/` directory + restore test in OQ; the *backup schedule* is organisational | `Partial` | `data/backups/` |

## 8. Printouts

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 8.1 | It should be possible to obtain clear printed copies of electronically stored data | Evidence packs render every signed record into a human-readable PDF/HTML companion (basic version `Beta`; richer typography `Experimental`) | `Beta` | `evidence_packs/<id>.zip` |
| 8.2 | For records supporting batch release it should be possible to generate printouts indicating if any of the data has been changed since the original entry | Audit trail captures every modification with timestamp and signer; the printout flag for "changed since original" is **`Experimental`** | `Experimental` | — |

## 9. Audit trail

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 9 | Consideration should be given, based on a risk assessment, to building into the system the creation of a record of all GMP-relevant changes and deletions (a system generated "audit trail"). For change or deletion of GMP-relevant data the reason should be documented. Audit trails need to be available and convertible to a generally intelligible form and regularly reviewed | Append-only audit trail across all persistence repos; reasons captured at the approval-gate `meaning` field; review surfaces in the operations canvas; periodic review is organisational | `Beta` | `tests/test_phase5_decision_trace_*.py` |

## 10. Change and configuration management

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 10 | Any changes to a computerised system including system configurations should only be made in a controlled manner in accordance with a defined procedure | Policy YAML changes go through git PR review; binary upgrades follow the project's release process; the *organisation's* change-control procedure layers on top | `Partial` | git history |

## 11. Periodic evaluation

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 11 | Computerised systems should be periodically evaluated to confirm that they remain in a valid state and are compliant with GMP | n/a — organisational schedule | `n/a` | Org-side |

## 12. Security

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 12.1 | Physical and/or logical controls should be in place to restrict access to computerised system to authorised persons | RBAC, scope isolation, rate limiting, optional CSRF, optional cookie-based session | `Beta` | `auth_repo`, `_helpers.py` |
| 12.2 | Suitable methods of preventing unauthorised entry to the system should be available | Login + token + optional MFA (MFA is `Experimental`) | `Partial` | `auth_repo` |
| 12.3 | The extent of security controls depends on the criticality of the computerised system | Per-policy-pack approval requirements; organisations tighten or relax based on risk | `Beta` | `policy_packs/` |
| 12.4 | Creation, change, and cancellation of access authorisations should be recorded | Auth-session lifecycle + api-token lifecycle in audit trail | `Beta` | `auth_repo` |

## 13. Incident management

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 13 | All incidents, not only system failures and data errors, should be reported and assessed | Audit trail records system errors; the policy pack `deviation_report` provides a workflow for non-system incidents; the *organisational* incident-management process is required | `Partial` | `policy_packs/deviation_report.yaml` |

## 14. Electronic signatures

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 14 | Electronic records may be signed electronically. Electronic signatures are expected to: (a) have the same impact as hand-written signatures within the boundaries of the company, (b) be permanently linked to their respective record, (c) include the time and date that they were applied | Approval gates with `signer + meaning + timestamp + linked_record_id` enforced at write time; same primitives that satisfy 21 CFR §11.50 / §11.70 | `Beta` | `evidence_packs/<id>.zip` |

## 15. Batch release

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 15 | When a computerised system is used for recording certification and batch release, the system should allow only Qualified Persons to certify the release of the batches and it should clearly identify and record the person releasing or certifying the batches. This should be performed using an electronic signature | Policy pack `lab_release` enforces the QP role on the release approval gate; the QP identity and signature are part of the evidence pack | `Beta` | `policy_packs/lab_release.yaml` |

## 16. Business continuity

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 16 | For the availability of computerised systems supporting critical processes, provisions should be made to ensure continuity of support for those processes in the event of a system breakdown (e.g. a manual or alternative system). The time required to bring the alternative arrangements into use should be based on risk and appropriate for a particular system and the business process it supports. These arrangements should be adequately documented and tested | Local-first architecture survives short loss of network; database backups + restore; alternative manual workflow is documented organisation-side | `Partial` | `data/backups/` |

## 17. Archiving

| Control | Title (paraphrased) | openMiura primitive(s) | Status | Notes |
|---|---|---|---|---|
| 17 | Data may be archived. This data should be checked for accessibility, readability and integrity. If relevant changes are to be made to the system (e.g. computer equipment or programs), then the ability to retrieve the data should be ensured and tested | Evidence pack export is the long-term archive format; format stability requires a documented schema (the manifest format is versioned); restore test is `Experimental` | `Partial` | `evidence_packs/<id>.zip` |

---

## Summary

| Status | Count of controls |
|---|---:|
| Stable | 0 |
| Beta | 9 |
| Partial | 11 |
| Experimental | 1 |
| n/a (organisational) | 4 |
| **Total** | **25** |

The Annex 11 mapping is denser than Part 11 because the EU
framework asks more explicitly about lifecycle and change
control. openMiura's strongest contribution remains the same:
audit trail, signed records, batch-release enforcement (control
15), and electronic signatures (control 14).
