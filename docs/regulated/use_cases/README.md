# Use cases — governance architectures for clinical research

The three documents in this directory describe **governance
architectures** for clinical-research workflows that the openMiura
project will need to support over time. They are written from the
perspective of "if this workflow were governed by openMiura, what
would the agent role, decision flow, approvals and evidence look
like".

## Important boundaries

These documents are deliberately **not**:

- A clinical decision-support claim.
- A diagnostic algorithm.
- A description of any specific clinical study.
- A repository of patient data, PII or PHI in any form, real or
  synthetic. The flows reference data *types* (e.g. "embryo
  morphokinetic timeline"), never specific patient records.

Any actual clinical deployment of these patterns would require:

- A separate, access-controlled repository for clinical data and
  the model implementation.
- Ethical Review Board / Institutional Review Board approval for
  the specific study.
- Local data-protection compliance (GDPR / Spanish LOPDGDD /
  HIPAA / equivalent).
- Independent clinical validation of the underlying model.

openMiura is the **governance plane**. The clinical model and the
clinical data live elsewhere.

## Files

- [`embryo_implantation_prediction.md`](embryo_implantation_prediction.md) —
  governed prediction support for assisted-reproduction embryo
  selection.
- [`colorectal_screening.md`](colorectal_screening.md) — governed
  triage support for colorectal cancer screening evidence.
- [`cardiovascular_risk.md`](cardiovascular_risk.md) — governed
  cardiovascular risk estimation in primary-care-style
  workflows.

## Pattern

All three follow the same template:

1. **Clinical context** — generic description of the workflow.
2. **Role of the agent** — what the agent proposes; what the
   human reviewer decides.
3. **Decision flow** — step-by-step, with explicit approvals.
4. **Evidence pack contents** — what is captured for each
   reviewed case.
5. **What openMiura does not handle** — the boundary with the
   clinical model, the clinical data, and the organisational
   responsibilities.
6. **Maturity** — Experimental at the openMiura layer for all
   three; the operating organisation is responsible for the
   clinical maturity.
