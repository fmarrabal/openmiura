# Pilot — NMR interpretation of catalytic compounds at UAL

> **A 15-minute read.** This document describes the first
> internal pilot of openMiura at the Universidad de Almería: a
> governed assistant for the interpretation of ¹H / ¹³C NMR
> spectra of organometallic catalytic compounds, with signed
> audit trail and reviewer approval before any interpretation
> reaches the laboratory notebook or a manuscript.

## 1. What this pilot is and is not

| | |
|---|---|
| **Is** | A controlled rehearsal of the Phase 2 governance pattern (whitepaper §6.1) on a real research workflow inside Curro's research group. |
| **Is** | A test of the openMiura primitives end-to-end on data that nobody outside the group sees. |
| **Is** | The vendor-side OQ artefact for any future external user that asks "does this run on a real lab?". |
| **Is not** | A clinical workflow. The pilot intentionally avoids any clinical or patient context. |
| **Is not** | A claim that the agent's NMR assignments are "correct" without review. The reviewer is the source of truth. |
| **Is not** | A change to the publication policy of the host research group. Manuscripts and notebooks remain subject to the existing internal review. |

## 2. Scope

- **Tenant**: `ual`
- **Workspace**: `nmrmbc` (Curro's research line on metal-based catalysis NMR; the workspace name is opaque to openMiura).
- **Environment**: `research`
- **Production environment**: not used. The pilot stays in `research` for the duration.

## 3. Actors

| Actor | Role in openMiura | Who, in practice |
|---|---|---|
| **Preparer** | `analyst` | The PhD student or researcher who acquires the spectrum and uploads it into the workspace. Drafts notes; does **not** sign assignments. |
| **Agent** | n/a (system) | The configured LLM agent. Runs against a controlled prompt that pins the model name and version. Proposes assignments. Never approves. |
| **Reviewer** | `nmr_reviewer` | A senior chemist in the group. Reviews the agent's draft against the spectrum and the chemistry. Signs or sends back. |
| **Approver** | `pi_approver` | Curro (or a delegated PI). Signs the final assignment for inclusion in the laboratory notebook / manuscript. Has authority to override the reviewer's decision but the override must carry a recorded justification. |

Three distinct identities with three distinct roles; no role is allowed to sign for another.

## 4. Flow

```
[upload spectrum + metadata]              (Preparer)
        │
        ▼
  ┌─────────────────────────────────────┐
  │ openMiura: scope check              │
  │   (tenant=ual,                      │
  │    workspace=nmrmbc,                │
  │    environment=research)            │
  │ Spectrum SHA-256 recorded           │
  └─────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────┐
  │ Agent draft                         │
  │   pinned model name + version       │
  │   prompt SHA-256 recorded           │
  │   structured assignments + impurity │
  │   flags                             │
  └─────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────┐
  │ openMiura: nmr_interpretation       │
  │   policy pack                       │
  │   - any unknown impurity flag       │
  │     above threshold => approval     │
  │     gate                            │
  │   - any new ligand identification   │
  │     => approval gate                │
  │   - routine known compound =>       │
  │     reviewer attestation only       │
  └─────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────┐
  │ Reviewer: nmr_reviewer signs        │
  │   meaning="reviewed; assignments    │
  │     match spectrum and known        │
  │     chemistry"                      │
  │   timestamp, identity recorded      │
  └─────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────┐
  │ Approver: pi_approver signs         │
  │   meaning="approved for laboratory  │
  │     notebook"                       │
  │   timestamp, identity recorded      │
  │   evidence pack written             │
  └─────────────────────────────────────┘
        │
        ▼
  Assignment is now eligible for the
  laboratory notebook / manuscript.
```

The order matters: reviewer **before** approver. A signed gate
out of order is rejected at the policy layer.

## 5. Evidence pack

Each approved assignment produces an evidence pack containing:

- The **spectrum SHA-256** + the original file.
- The **metadata** at upload time (instrument id, acquisition
  parameters, solvent, reference, sample id within the workspace).
- The **prompt** (verbatim, SHA-256 too) and the **completion**
  (verbatim, SHA-256 too) of every agent invocation involved.
- The **model identifier** and **model version** that produced
  the draft.
- The **policy pack version** at the moment of decision.
- The **two signatures** (reviewer and approver) with signer
  identity, timestamp and meaning.
- The **scope triple** at the moment of decision.
- The **manifest** with SHA-256 of every embedded artefact and
  a single signed pointer to that manifest.

The pack is the unit of record. It is what an external auditor
(or a future Curro looking back six months later) would request.

## 6. Policy pack

The pilot's policy pack lives at
[`../policy_packs/nmr_interpretation.yaml`](../policy_packs/nmr_interpretation.yaml).
It extends the generic `analytical_interpretation` pack with
NMR-specific predicates: unknown-impurity threshold, new-ligand
flag, paramagnetic compound flag (currently *out of scope* —
paramagnetic samples are handled outside the pilot).

The pack is loaded by the adapted demo (see §8); the
\`tests/test_regulated_policy_packs.py\` fixture verifies its
structural integrity alongside the other packs.

## 7. Out of scope for the pilot

- Paramagnetic compounds. Different acquisition pattern; the
  agent is not configured for them.
- ¹⁹F, ³¹P and 2D experiments. Future extension.
- Any spectrum acquired outside the `nmrmbc` workspace.
- Any spectrum involving chiral / enantiomeric analysis as the
  primary endpoint.
- Any external publication of evidence packs without explicit
  PI approval.

## 8. Verification plan

A new script,
[`../../../scripts/run_pilot_ual_nmr_demo.py`](../../../scripts/run_pilot_ual_nmr_demo.py),
adapts the canonical demo (`scripts/run_canonical_demo.py`) to
this pilot. It exercises one synthetic spectrum (no real
acquisition), drives a fake agent through a controlled prompt,
loads the `nmr_interpretation` policy pack and produces an
evidence pack on disk. It is a smoke test, not a clinical
demonstration.

The smoke test is the **vendor-side OQ artefact** for the pilot.
Running it should produce \`success=True\` and a structured JSON
report that names the policy version, the model identifier, the
two signatures and the manifest SHA-256.

## 9. What "done" means for the pilot

The pilot is in steady-state when:

- Three different real spectra (acquired over three different
  days, by three different preparers) have been processed end to
  end.
- The `nmr_reviewer` and `pi_approver` roles have signed for
  each of those three.
- The evidence packs have been retrieved and re-verified after
  the fact (manifest SHA-256 still matches).
- One controlled "known wrong" spectrum has been processed and
  the reviewer caught the error before it reached the
  approver. (This is the negative test that the pattern works.)

At that point the pilot output is suitable as input to Phase 4
(the strategic decision document `docs/STRATEGY.md` and the
academic paper draft).

## 10. References to existing material

- Whitepaper: [`../whitepaper.md`](../whitepaper.md) — §6.1
  describes the analytical-interpretation pattern this pilot
  implements.
- Mappings: [`../mapping_eu_gmp_annex11.md`](../mapping_eu_gmp_annex11.md)
  controls 5, 6, 9, 14 are the relevant ones for an analytical
  workflow inside a research lab.
- Use cases: [`../use_cases/`](../use_cases/) — clinical
  governance patterns the pilot does **not** implement; see
  [`pilot_clinical_governance.md`](../pilot_clinical_governance.md)
  for the reusable architecture sketch.
