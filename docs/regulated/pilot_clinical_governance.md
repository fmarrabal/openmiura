# Pilot — clinical governance pattern (architecture only)

> **Scope of this document.** Reusable governance architecture
> for the three clinical-research lines covered in
> [`use_cases/`](use_cases/) (embryo implantation prediction,
> colorectal screening, cardiovascular risk). It is
> **architecture only**: there is **no** implementation in this
> repository, **no** patient data, **no** PII / PHI, and **no**
> clinical claim. Real deployments must live in separate,
> access-controlled repositories with IRB / Ethics Committee
> approval and local data-protection compliance.

**Maturity (openMiura layer):** `Experimental`.
**Maturity (clinical layer):** out of scope.

## 1. Why a single pattern across the three use cases

The three clinical use cases differ in *clinical content* but
share a common *governance shape*: an agent **proposes**, a
clinician **decides**, and the operating organisation must be
able to reconstruct *which model, which prompt, which scope,
which signer* produced any record.

This document captures that shared shape so that any future
clinical pilot inherits it, rather than reinventing the
governance plane each time.

## 2. Required separation of repositories

```
openmiura/                              ← THIS repo (governance plane)
    docs/regulated/use_cases/           ← architecture, no data
    docs/regulated/pilot_clinical_governance.md  ← this file

<separate-clinical-repo>/               ← NOT in this repo
    clinical_data/                      ← under hospital ACL
    clinical_model/                     ← validated model + weights
    clinical_record_integration/        ← LIMS / EHR adapter
    irb_approval/                       ← signed approval letter
```

Mixing the two on the same access boundary is a data-protection
incident waiting to happen. The pattern below assumes the two
sit on different repos with different access controls and with
a documented one-way reference (clinical repo → openMiura
workspace identifier).

## 3. The pattern

### 3.1 Identity and scope

- **Tenant**: hospital or research consortium identifier.
- **Workspace**: per-study identifier. Opaque from openMiura's
  point of view (a hash, not a patient cohort identifier).
- **Environment**: `research` for any clinical-research pilot;
  `production` is reserved for non-clinical workflows under the
  scope of the pilot.

### 3.2 Roles

| Role | Authority | Source of identity |
|---|---|---|
| `clinical_preparer` | uploads anonymised payload into the workspace | hospital IAM |
| `clinical_reviewer` | reviews the agent's draft against the clinical context | hospital IAM, qualified clinician |
| `pi_clinical` | approves for inclusion in the research record | hospital IAM, principal investigator |
| `data_governance` | retroactive audit role; read-only across scopes for governance review only | governance committee |

No role is allowed to sign for another. The `data_governance`
role exists for retrospective audit and cannot create records.

### 3.3 Required policy primitives

Every clinical pilot policy pack must include the following
rules. The pack is per-study; the rules are inherited.

```yaml
rules:
  - id: payload_anonymisation_attested
    on_action: workflows.clinical.draft
    require_payload_fields:
      - payload_anonymisation_attestation
      - upload_principal_id

  - id: model_pinned
    on_action: workflows.clinical.draft
    require_payload_fields:
      - model_name
      - model_version
      - prompt_sha256

  - id: clinical_review_required
    on_action: workflows.clinical.publish
    require_approval:
      role: clinical_reviewer
      meaning: "reviewed against clinical context; agent output is one input among many"
    deny_without_approval: true

  - id: pi_approval_required
    on_action: workflows.clinical.publish
    require_approval:
      role: pi_clinical
      meaning: "approved for inclusion in the research record"
    deny_without_approval: true

  - id: irb_reference_required_for_publication
    on_action: workflows.clinical.publish
    require_payload_fields:
      - irb_or_ethics_approval_id
      - data_protection_compliance_basis

  - id: scope_strict
    on_action: "workflows.clinical.*"
    enforce_scope_match:
      tenant: required
      workspace: required
      environment: required

  - id: evidence_pack_full
    on_action: workflows.clinical.publish
    require_evidence:
      include:
        - audit_trail
        - approvals
        - signed_manifest
        - prompt_and_completion
        - model_identifier
        - reviewer_identity
```

The pack is intentionally short: the burden of correctness is
on the operating organisation's choice of model, training
validation and ethics approval.

### 3.4 Evidence pack contents

Per published record:

- The **anonymised payload hash** (no payload contents stored
  in openMiura beyond the hash).
- The **model identifier** + **model version** + **prompt
  SHA-256** + **completion** verbatim.
- The **policy pack version** at publication time.
- The **two signatures** (clinical reviewer + PI) with
  identity, role, meaning and timestamp.
- The **IRB / Ethics Committee approval id** + the
  **data-protection compliance basis** (GDPR Art. 6 lawful
  basis + Art. 9 special category condition where
  applicable).
- The **scope triple** at publication time.
- The **manifest** with SHA-256 of every embedded artefact.

The pack's manifest is what an external auditor would request;
the underlying clinical data is **not** in the pack — only its
hash is.

### 3.5 What openMiura does not store

Explicitly **not** in any openMiura record:

- Direct patient identifiers (name, DOB, ID number).
- Indirect patient identifiers (rare-disease combinations,
  small-cohort timestamps).
- Free-text PHI (clinical notes, narratives).
- Imaging or signal data beyond a hash.
- Genetic data.

The workspace identifier is a one-way reference: openMiura sees
"workspace X has 12 published records"; only the clinical record
system can resolve "workspace X" back to people.

### 3.6 Roles and responsibilities recap

| Question | Answered by |
|---|---|
| "Was this model validated for the population?" | clinical model owner (not openMiura) |
| "Was IRB approval in place when the record was published?" | clinical data governance (the field is required by the policy pack but openMiura does not validate the IRB id) |
| "Who signed the publication?" | openMiura evidence pack |
| "What prompt and what completion produced the draft?" | openMiura evidence pack |
| "Did the workflow stay inside scope?" | openMiura policy engine + evidence pack |
| "Was the underlying data anonymised?" | clinical data governance + the `payload_anonymisation_attestation` field; openMiura records the attestation but does not perform anonymisation |

## 4. When to use this pattern vs the UAL NMR pilot pattern

| Question | Use NMR pilot pattern | Use clinical pattern |
|---|---|---|
| Is the data clinical (about people)? | ❌ | ✅ |
| Is there PHI / PII anywhere in the workflow? | ❌ | ✅ |
| Is IRB / Ethics Committee approval relevant? | ❌ | ✅ |
| Is data-protection law (GDPR / equivalent) the governing constraint? | ❌ | ✅ |
| Is the deployment inside a single research group? | ✅ | ✅ |

The UAL NMR pilot is the right *first* pilot. It gives
operational experience with the openMiura primitives without
the data-protection and ethics-approval overhead. Once the
group is comfortable running the NMR pilot end to end, the
clinical pattern becomes the next step — under a separate
repository, separate ACL and separate validation.

## 5. References

- European Parliament. *Regulation (EU) 2016/679 (GDPR)*.
  Articles 6 and 9 are the lawful-basis frame for clinical
  research.
  <https://eur-lex.europa.eu/eli/reg/2016/679/oj>
- European Parliament. *Regulation (EU) 2017/745 (Medical
  Device Regulation)* — applies if a model is classified as
  SaMD.
- ICH. *E6(R3) — Guideline for Good Clinical Practice (GCP)*.
- WMA. *Declaration of Helsinki — Ethical Principles for
  Medical Research Involving Human Subjects*.
- OECD. *AI principles* (transparency, accountability,
  human-centred values).

A real clinical deployment of this pattern would extend the
references with the specific national data-protection law
(LOPDGDD in Spain, NHS-DSP-NS in the UK, HIPAA in the US),
the specific IRB / Ethics Committee approval letter, and the
peer-reviewed validation study of the underlying clinical
model.
