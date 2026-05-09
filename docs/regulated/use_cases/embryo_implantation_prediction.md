# Use case — governed prediction support for embryo selection

> **Scope of this document.** This is a *governance architecture*
> for a clinical-research workflow. It describes agent role,
> decision flow, approvals and evidence. It is **not** a clinical
> decision-support claim, **not** a diagnostic algorithm, and
> **not** a description of any specific study or patient. No
> patient data, PII or PHI appears here.

**Maturity (openMiura layer):** `Experimental`.
**Maturity (clinical layer):** out of scope; depends on the
operating organisation, the IRB / Ethics Committee approval, the
clinical validation of the underlying model, and local
data-protection compliance.

## 1. Clinical context

Assisted-reproduction laboratories evaluate embryos derived from
in-vitro fertilisation cycles to support the embryologist in
selecting the most viable embryo for transfer. Inputs include
morphokinetic timelines from time-lapse incubators, morphological
grading, and (in some studies) genetic-screening summaries. The
**embryologist** is the clinical decision-maker. Any model used
to support the decision is, regulatorily, a Class II or Class
III medical device under MDR 2017/745 in the EU and a Software
as a Medical Device (SaMD) under 21 CFR 820 in the US — that
classification work is on the operating organisation, not on
openMiura.

## 2. Role of the agent

- The agent **proposes** an implantation-likelihood ranking for
  the candidate embryos in a cycle, with a structured
  explanation referencing the input features it used.
- The agent **never** issues a clinical recommendation, and
  **never** writes to the clinical record.
- The embryologist **decides** the transfer on the basis of the
  full clinical picture, of which the agent's proposal is one
  input among many.

## 3. Decision flow

```
[input: morphokinetic + morphological data, anonymised]
                │
                ▼
  ┌──────────────────────────────────┐
  │ openMiura: scope check, RBAC     │
  │ (tenant=clinic_X, workspace=     │
  │  cycle_<hash>, env=research)     │
  └──────────────────────────────────┘
                │
                ▼
  ┌──────────────────────────────────┐
  │ Agent draft: ranking +           │
  │ structured explanation           │
  └──────────────────────────────────┘
                │
                ▼
  ┌──────────────────────────────────┐
  │ openMiura: approval gate         │
  │   role=embryologist_reviewer     │
  │   meaning="reviewed; aware of    │
  │     model output as one input"   │
  └──────────────────────────────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
   Approved          Rejected /
                     sent back
        │
        ▼
  ┌──────────────────────────────────┐
  │ Evidence pack written            │
  │ (no clinical decision recorded)  │
  └──────────────────────────────────┘
                │
                ▼
  Clinical decision happens
  outside openMiura, in the
  clinical record system.
```

The flow ends with the evidence pack. The actual transfer
decision is made by the embryologist in the clinical record
system, which is **not** the same data store as openMiura.

## 4. Evidence pack contents

For each cycle reviewed:

- The **input feature list** as it reached the agent (with PII
  removed; the linkage to the underlying patient lives only in
  the clinical record system).
- The **model identifier** and **model version** that produced
  the ranking.
- The **prompt and completion** (the agent's structured
  reasoning) hashed and stored verbatim.
- The **policy pack version** (`analytical_interpretation` or a
  more specific clinical pack, when developed).
- The **embryologist reviewer identity** and signature meaning.
- The **scope triple** (clinic, cycle workspace, environment).

## 5. What openMiura does not handle

- The clinical record itself: the linkage from "cycle
  workspace" to a patient identifier lives in the clinical
  record system, behind hospital authentication. openMiura
  records only the workspace identifier, not the patient.
- The clinical model: training, validation, periodic
  re-validation, drift monitoring, regulatory submission.
- The decision: openMiura captures the agent's output and the
  embryologist's signature on having reviewed it; it does not
  record what embryo was transferred.
- IRB / Ethics Committee approval and informed-consent
  workflow — these are organisational.

## 6. References

This document references public regulatory frameworks; no
specific clinical study is cited.

- European Parliament. *Regulation (EU) 2017/745 (Medical
  Device Regulation)*.
  <https://eur-lex.europa.eu/eli/reg/2017/745/oj>
- FDA. *Software as a Medical Device (SaMD) Action Plan*, 2021.
  <https://www.fda.gov/medical-devices/software-medical-device-samd>
- IMDRF. *Software as a Medical Device: Possible Framework for
  Risk Categorization and Corresponding Considerations*, 2014.
- ESHRE. *Time-lapse imaging in embryo culture* (review
  literature; cite the operating organisation's selected
  reference).

A clinical deployment of this pattern would extend the
references with the specific peer-reviewed clinical-validation
study of the model, plus the IRB / Ethics Committee approval
identifier.
