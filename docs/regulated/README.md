# openMiura for regulated scientific environments

This directory groups the technical material that explains how
openMiura can serve as a governance plane for LLM agents in
**regulated scientific contexts** — analytical laboratories,
pharmaceutical Quality Assurance, biomedical research that has to
keep an inspectable audit trail.

The material is intentionally **technical and honest**: it maps the
architecture to the regulatory frameworks it can support today, with
explicit *Stable / Beta / Partial / Experimental / n/a* labels per
control, and flags every gap. Nothing here is a declaration of
conformity — that signature only an organization with a validated
quality system can issue.

## Contents

- [`whitepaper.md`](whitepaper.md) — the technical white paper.
  Covers the problem statement, the architectural primitives
  (policy / approvals / evidence / scope), validation strategy and
  reference implementations.
- [`mapping_21cfr_part11.md`](mapping_21cfr_part11.md) —
  control-by-control mapping to FDA *21 CFR Part 11 — Electronic
  Records; Electronic Signatures*.
- [`mapping_eu_gmp_annex11.md`](mapping_eu_gmp_annex11.md) —
  control-by-control mapping to *EudraLex Volume 4, Annex 11 —
  Computerised Systems*.
- [`mapping_gamp5.md`](mapping_gamp5.md) — risk-based mapping to
  ISPE *GAMP 5* (2nd ed., 2022): software categorization 3 / 4 / 5
  and the V-model lifecycle.
- [`alcoa_plus_compliance.md`](alcoa_plus_compliance.md) — ALCOA+
  data integrity self-assessment, dimension by dimension.
- [`policy_packs/`](policy_packs/) — concrete, executable YAML
  policy packs covering lab release, SOP review, OOS/OOT
  investigation, deviation reporting and analytical interpretation.
- [`use_cases/`](use_cases/) — three governance architectures for
  Curro's clinical research lines (embryo implantation prediction,
  colorectal screening, cardiovascular risk). The use-case
  documents describe **agent role, decision flow, approvals and
  evidence**; they do **not** include patient data, PII, PHI, or
  any clinical claim.

## Status legend

Every mapping table uses the same legend:

| Label | Meaning |
|---|---|
| `Stable` | Implemented, covered by tests, documented in the public docs. |
| `Beta` | Implemented, covered by tests, documentation partial. |
| `Partial` | Partial implementation; some sub-controls covered, others not. |
| `Experimental` | Placeholder code or proof-of-concept; not ready for adoption. |
| `n/a` | Out of scope for the openMiura technical layer (organizational, procedural, or hardware control). |

The labels are **deliberately conservative**. Today the majority of
controls are `Partial` or `Experimental`. That is honest, it is the
state of the project, and it is what a Quality Assurance reviewer
wants to see.

## What this material is *not*

- **Not a declaration of conformity.** Validation against any of
  these frameworks is an organizational responsibility that
  involves the operating company, its quality system, its SOPs,
  its training programme and its qualified personnel.
- **Not a clinical decision-support claim.** The use-case
  documents describe governance architecture, not diagnostic
  algorithms.
- **Not legal advice.** When in doubt, ask a qualified validation
  consultant, regulatory affairs officer, or notified body.
