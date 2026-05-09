# GAMP 5 — risk-based mapping

This document positions openMiura inside the *GAMP 5 (2nd
edition, 2022)* framework: software categorisation, lifecycle
phase coverage and the risk-based scaling of validation effort.

## Software categorisation

GAMP 5 categorises software as follows:

| Category | Description | Validation effort |
|---|---|---|
| 1 | Infrastructure software (operating systems, databases, programming languages) | Verification of installation only |
| 3 | Non-configured products (commercial off-the-shelf used as-is) | Vendor audit + test of intended use |
| 4 | Configured products (commercial off-the-shelf with site-specific configuration) | Configuration documented, verified, change-controlled |
| 5 | Custom applications (bespoke software) | Full lifecycle: URS → DS → IQ → OQ → PQ |

**openMiura is Category 4 — Configured Product.**

The binary is generic: it does not encode the operating
organisation's policies, roles or workflows. The value comes
from the configuration: the YAML policy packs, the role
definitions, the operations canvas layout, the deployment-time
secrets and the integration with site-specific identity
providers. Validation effort scales accordingly:

- The **binary itself** follows the project's own change
  management (PR review, automated tests, semantic versioning,
  release notes). The operating organisation does *not* need to
  re-audit the binary for every release; it does need to track
  which version is in use and whether to upgrade based on its
  internal change-control procedure.
- The **configuration** (policy packs, role assignments,
  deployment profile) is the validated artefact. Each policy
  pack is a configurable element; changes to it must follow the
  organisation's change control.

A subtlety: while openMiura the *binary* is Category 4, the
*LLM agent it governs* is on a separate categorisation track.
The model itself is closer to Category 5 in GAMP 5 terms because
it is a custom-trained system whose internal state cannot be
fully characterised. The risk-based approach below addresses
this asymmetry.

---

## Lifecycle coverage

The 5-stage validation lifecycle in GAMP 5 (URS → FS → DS → IQ
→ OQ → PQ) maps onto openMiura artefacts as follows:

| Stage | What the framework asks for | openMiura input | Owner |
|---|---|---|---|
| URS — User Requirements Specification | Functional / regulatory requirements derived from the business need | This document + the use-case files in [`use_cases/`](use_cases/) provide *examples*; the operating organisation writes the URS for its own deployment | Organisation |
| FS — Functional Specification | What the software does, traceable to URS | [`whitepaper.md §3`](whitepaper.md) (architectural primitives) + the chosen policy pack(s) | Organisation, with vendor-side reference |
| DS — Design Specification | How the software is constructed | [`docs/architecture/persistence.md`](../architecture/persistence.md) + [`whitepaper.md §3`](whitepaper.md) + the open repository | Vendor |
| IQ — Installation Qualification | Verifies the deployment matches the design | `openmiura doctor --config <profile>.yaml` + the canonical demo's setup phase | Organisation |
| OQ — Operational Qualification | Verifies functional behaviour against the spec | The test suite (`tests/`), the canonical demo, the policy-pack tests | Joint (vendor-side reference + organisation-side scenarios) |
| PQ — Performance Qualification | Verifies behaviour under realistic operating conditions | Organisation runs a controlled rehearsal of the use-case workflows in a staging environment with representative agents and data | Organisation |

**openMiura ships the FS-side reference and a substantial OQ
fixture.** The URS, the IQ scripts targeted at the operating
infrastructure, and PQ in the operating environment remain
organisation-side responsibilities.

---

## Risk-based approach

GAMP 5 emphasises that the *amount* of validation effort should
be proportional to the risk to patient safety, product quality
and data integrity. We adopt this framing concretely.

### Risk classes for openMiura-governed workflows

| Risk class | Examples | Required openMiura controls |
|---|---|---|
| **Low** | Search assistant inside an SOP library; FAQ on internal tooling; non-critical documentation drafting | Policy pack with logging; no approval gate strictly required; standard scope isolation |
| **Medium** | Drafting an SOP revision; analytical interpretation when the spectrum is from a non-critical batch; OOS-investigation hypothesis ranking | Policy pack with single-party approval gate; signed evidence pack; reviewer trained on AI output review |
| **High** | Batch release certification; OOS investigation closure; clinical-research evidence handling; any GxP write that would otherwise require a Qualified Person signature | Policy pack with two-party approval gate (where multi-party is implemented); signed evidence pack with full audit trail; QP role on the gate; mandatory CAPA reference for any closure record |

The exact classification for a given workflow is set by the
operating organisation's quality system; openMiura provides the
controls to enforce the chosen class once it is set.

### Risk to data integrity

The single most common risk for an LLM-driven workflow is
*silent drift*: the agent produces an answer that looks correct
but is subtly different from the reference, and the reviewer
approves it without catching the drift. openMiura mitigates this
by:

- Recording the **exact prompt** and the **exact completion**
  in the evidence pack. A retrospective audit can replay the
  agent against the same prompt to detect drift over model
  versions.
- Recording the **policy version** at the time of decision. A
  policy that becomes stricter later does not invalidate prior
  decisions, but the operator can identify which old decisions
  would not pass current policy and review them explicitly.
- Recording the **scope** at the time of decision. A change in
  scope membership (e.g. a workspace's role changes) does not
  retroactively re-classify old records.

These three together approximate the *replayability* property
that classical CSV obtains for free with deterministic software.

### Risk to patient safety

For any workflow where a wrong agent answer could affect a
patient (clinical research, investigational diagnostics), we
recommend:

- The **human reviewer is the decision-maker**, not the agent.
  openMiura's approval gates enforce this with the policy
  schema.
- The use-case documents in [`use_cases/`](use_cases/)
  describe the architecture for three such workflows
  (embryo implantation prediction, colorectal screening,
  cardiovascular risk). They explicitly avoid making clinical
  claims; they describe **agent role, decision flow and
  evidence**.

### Risk to product quality

For pharmaceutical workflows, *batch release* is the
canonical high-risk action. The `lab_release` policy pack
enforces:

- Required role: `qp_release` (Qualified Person).
- Required signature meaning: `"approved for QP release"`.
- Required signature components per §11.200(a)(1)(i): tied to
  the auth_users record.
- Required evidence pack export before the release event is
  visible downstream.

---

## Categorisation summary

| Component | GAMP 5 category | Validation owner |
|---|---|---|
| openMiura binary | 4 (Configured Product) | Vendor-side change management; organisation tracks version |
| Policy YAML pack | Configuration (within Cat. 4) | Organisation, with change control |
| Role assignments | Configuration (within Cat. 4) | Organisation, with change control |
| Deployment profile (`configs/openmiura.yaml`) | Configuration (within Cat. 4) | Organisation, with change control |
| LLM agent / model | 5-equivalent (effectively bespoke; the model state is not fully characterisable) | Organisation, model-version-aware PQ |

The honest takeaway: openMiura simplifies validation of the
**governance plane** to a Category 4 effort. It does not
simplify validation of the **agent itself**, which remains the
hardest part of the lifecycle and is not a problem any
governance plane can solve from the outside.
