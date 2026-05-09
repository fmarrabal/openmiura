# Use case — governed triage support for colorectal cancer screening

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

Population-level colorectal cancer screening combines several
inputs to triage individuals into "follow-up needed" versus
"routine continued screening" categories. Common inputs include
faecal immunochemical test (FIT) results, family-history flags,
prior screening history, and (in research settings) imaging or
laboratory biomarker panels. The **clinician** is the decision-
maker; any model used to support triage is regulated as SaMD
under MDR / FDA frameworks. Classification is the operating
organisation's responsibility.

## 2. Role of the agent

- The agent **proposes** a structured triage suggestion (e.g.
  "review recommended" vs "routine continued") with the input
  features and the model's confidence-equivalent score.
- The agent **never** schedules procedures, **never** writes to
  the clinical record, and **never** communicates directly with
  the patient.
- The reviewing clinician **decides** the triage on the full
  clinical picture; the agent's suggestion is one input.

## 3. Decision flow

```
[input: anonymised triage feature panel]
                │
                ▼
  ┌──────────────────────────────────┐
  │ openMiura: scope check, RBAC     │
  │ (tenant=screening_program,       │
  │  workspace=cohort_batch_<hash>,  │
  │  env=research)                   │
  └──────────────────────────────────┘
                │
                ▼
  ┌──────────────────────────────────┐
  │ Agent draft: triage suggestion + │
  │ feature attribution explanation  │
  └──────────────────────────────────┘
                │
                ▼
  ┌──────────────────────────────────┐
  │ openMiura: approval gate         │
  │   role=screening_clinician       │
  │   meaning="reviewed; aware of    │
  │     model output; clinical       │
  │     decision lives elsewhere"    │
  └──────────────────────────────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
   Approved          Sent back
        │
        ▼
  ┌──────────────────────────────────┐
  │ Evidence pack                    │
  │ (no clinical decision recorded)  │
  └──────────────────────────────────┘
                │
                ▼
  Clinical decision and any
  follow-up scheduling happens
  outside openMiura, in the
  clinical record system.
```

## 4. Evidence pack contents

For each cohort batch reviewed:

- The **anonymised feature panel** as it reached the agent.
- The **model identifier** and **model version**.
- The **prompt and completion** hashes and verbatim text.
- The **policy pack version**.
- The **reviewing clinician identity** and signature meaning.
- The **scope triple**.

The pack is keyed by the cohort batch, not by the individual.
The link from cohort batch to specific patients lives in the
screening-programme clinical record system, not in openMiura.

## 5. What openMiura does not handle

- Patient identification or follow-up communication. The
  workspace identifier in the openMiura record is opaque to the
  governance plane; only the screening-programme clinical
  record system can resolve it back to people.
- The clinical model: training set composition, fairness
  evaluation across demographic strata, periodic re-validation
  against current screening guidelines, drift monitoring.
- The screening-programme governance (frequency of screening,
  inclusion criteria, communication of results) — these are
  defined by the public-health authority and the operating
  organisation.

## 6. References

This document references public regulatory frameworks; no
specific clinical study is cited.

- European Parliament. *Regulation (EU) 2017/745 (Medical
  Device Regulation)*.
- European Council. *Council Recommendation on cancer
  screening*, 2022 update.
  <https://eur-lex.europa.eu/eli/reco/2022/c_473/oj>
- WHO. *Guide to cancer early diagnosis*, 2017.
- FDA. *Software as a Medical Device (SaMD) Action Plan*, 2021.

A clinical deployment of this pattern would extend the
references with the specific peer-reviewed validation study of
the screening model, the screening programme's standard
operating procedure, and any IRB / Ethics Committee approval.
