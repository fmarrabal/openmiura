# Use case — governed cardiovascular risk estimation support

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

Primary-care-style cardiovascular risk estimation combines
laboratory results (lipid panel, HbA1c), vital signs (blood
pressure, BMI), demographic factors and lifestyle inputs to
produce a 10-year risk estimate that informs preventive
discussions. Standard scoring tools (SCORE2, ASCVD, QRISK) are
already validated and endorsed; an LLM-based "explanation
companion" alongside them is the workflow we describe here.
The **physician** is the decision-maker; any model used as a
companion is regulated as SaMD if it issues a clinical
recommendation, or as a low-risk advisory tool if it explains
existing scores. The classification depends on the framing the
operating organisation chooses.

## 2. Role of the agent

- The agent **explains** the structured risk panel: which
  factors contribute most, how the patient compares against
  the reference cohort, what lifestyle factors would shift the
  estimate.
- The agent **does not** issue a clinical recommendation;
  recommendations come from the physician on the basis of the
  full picture (including factors openMiura never sees).
- The agent **never** writes to the clinical record and
  **never** communicates directly with the patient.

## 3. Decision flow

```
[input: anonymised risk panel, computed score]
                │
                ▼
  ┌──────────────────────────────────┐
  │ openMiura: scope check, RBAC     │
  │ (tenant=primary_care_clinic,     │
  │  workspace=session_<hash>,       │
  │  env=research)                   │
  └──────────────────────────────────┘
                │
                ▼
  ┌──────────────────────────────────┐
  │ Agent draft: structured          │
  │ explanation of the score         │
  │ (no recommendation)              │
  └──────────────────────────────────┘
                │
                ▼
  ┌──────────────────────────────────┐
  │ openMiura: approval gate         │
  │   role=primary_care_physician    │
  │   meaning="explanation reviewed  │
  │     for use during consultation" │
  └──────────────────────────────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
   Approved          Sent back
        │
        ▼
  ┌──────────────────────────────────┐
  │ Evidence pack                    │
  │ (used as companion material;     │
  │  not the clinical record)        │
  └──────────────────────────────────┘
                │
                ▼
  Consultation with the patient
  and any prescribing decision
  happens outside openMiura.
```

## 4. Evidence pack contents

For each consultation session reviewed:

- The **anonymised risk panel** reaching the agent.
- The **computed risk score** from the validated scoring tool
  (SCORE2 / ASCVD / QRISK / equivalent). openMiura is downstream
  of the score; it does **not** compute the score.
- The **model identifier** and **model version** of the
  explanation agent.
- The **prompt and completion** hashes and verbatim text.
- The **physician reviewer identity** and signature meaning.
- The **scope triple**.

## 5. What openMiura does not handle

- The risk-score computation itself. Validated scoring tools
  remain authoritative; the agent only explains.
- Patient identity, contact, and follow-up scheduling.
- The clinical model: training data composition, demographic
  fairness, interaction with regulatory frameworks for
  preventive screening.
- The consultation itself, the prescribing decision, the
  patient's lifestyle counselling, and any downstream
  laboratory tests — all live outside openMiura.

## 6. References

This document references public regulatory frameworks and
validated scoring tools; no specific clinical study is cited.

- European Society of Cardiology. *2021 ESC Guidelines on
  cardiovascular disease prevention in clinical practice*.
  *European Heart Journal*, 2021. SCORE2 algorithm.
  <https://academic.oup.com/eurheartj/article/42/34/3227/6358713>
- American Heart Association / American College of Cardiology.
  *2018 Guideline on the Management of Blood Cholesterol*.
  ASCVD risk estimator.
- European Parliament. *Regulation (EU) 2017/745 (Medical
  Device Regulation)*.
- FDA. *Software as a Medical Device (SaMD) Action Plan*, 2021.

A clinical deployment of this pattern would extend the
references with the operating organisation's chosen scoring
tool, its calibration evidence in the local population, and any
IRB / Ethics Committee approval for the explanation companion.
