# openMiura for Regulated Scientific Environments

*A technical white paper on governance of LLM agents under 21 CFR
Part 11, EU GMP Annex 11, and GAMP 5.*

**Status:** Working draft, October 2026. The document accompanies
the openMiura source repository at
<https://github.com/fmarrabal/openmiura>. Feedback welcome.

---

## 1. Executive summary

LLM-driven agents are entering regulated scientific workflows: from
analytical interpretation in QC laboratories to SOP authoring, from
deviation triage to clinical-research evidence pipelines. The
operational properties that made *classical* computerised systems
inspectable — deterministic logic, signed code, validated database
schemas — translate badly to systems whose decisions depend on a
non-deterministic generative model.

This paper describes openMiura, an open-source **governance plane**
designed for these workflows. Its scope is intentionally narrow:
openMiura does not run the agent and does not replace the agent's
runtime. It enforces **policy** before each action, gates sensitive
operations behind explicit **human approvals**, records every step
in an append-only **audit trail**, and emits signed
**evidence packs** that link decisions to records.

We map openMiura's architectural primitives to three regulatory
frameworks that practitioners will recognise:

- **21 CFR Part 11** (FDA, electronic records and electronic
  signatures);
- **EU GMP Annex 11** (computerised systems in pharmaceutical
  manufacture);
- **GAMP 5, 2nd ed.** (ISPE, risk-based validation lifecycle).

We close with **ALCOA+** data integrity self-assessment and three
reference implementation sketches.

The result is not a compliance certificate. It is a **starting
point** for an organisation that wants to introduce LLM agents in a
GxP context without abandoning the audit trail that the framework
demands. Validation against any of the frameworks remains the
responsibility of the operating organisation, its quality system
and its qualified personnel.

---

## 2. Problem statement

### 2.1 LLM agents in regulated scientific workflows

Modern LLM agents combine three capabilities that, together, make
them attractive in a laboratory or clinical-research setting:

- **Pattern interpretation** over heterogeneous evidence (free
  text, tables, signal traces, instrument output).
- **Tool orchestration**, including queries against laboratory
  databases, retrieval from internal SOP libraries, and
  invocation of analysis pipelines.
- **Conversational handoff** with the laboratory operator,
  including clarification, summarisation and SOP citation.

Concrete deployments we already see: assistants that draft an
out-of-specification (OOS) investigation, agents that propose a
peak assignment for a NMR spectrum, copilots that summarise a
batch record before QA review.

These deployments are useful. They are also **operationally
risky** if introduced without governance: a hallucinated peak
assignment, a fabricated regulatory citation, or an incorrectly
attributed signature would be bad on its own and ruinous in a GxP
context where the audit trail matters as much as the result.

### 2.2 Why classical e-system validation does not transfer 1:1

Computerised System Validation (CSV) and the more recent Computer
Software Assurance (CSA) approach assume *deterministic* software:
given an input, the output is reproducible, explainable and
defensible against the requirements specification. The validation
lifecycle (URS → FS → DS → IQ → OQ → PQ) inherits that assumption.

LLM agents break the assumption in three ways:

1. **Non-determinism by construction.** Two requests with the same
   prompt can yield different completions. Even with temperature 0,
   model versions and tokenizer subtleties shift behaviour.
2. **Open-ended action space.** A tool-using agent can compose a
   sequence of operations the validator did not anticipate. The
   *Functional Specification* cannot enumerate every traversal.
3. **Knowledge that drifts.** The model's internal knowledge
   changes between releases. A *Performance Qualification* run on
   model M_i is not, by itself, evidence about model M_(i+1).

The conclusion is not that LLM agents cannot be validated; it is
that the validation has to operate **around** the agent rather
than verifying it from the inside. We borrow this framing from
GAMP 5's risk-based approach: focus the validation effort on the
points where harm can occur, not on a futile attempt to enumerate
every possible internal path.

### 2.3 Risk taxonomy

We adopt a small, opinionated risk taxonomy. The categories below
are aligned with the *OWASP Top 10 for LLM Applications* working
list and the early *OWASP Top 10 for Agentic AI Applications*
discussion documents. We use them as **labels for required
controls**, not as a definitive harm catalogue.

| Risk family | Concrete failure mode in a lab context |
|---|---|
| **Hallucination** | The agent reports a peak assignment, a CFR citation, or a calibration value that is not in the source data. |
| **Unauthorised action** | The agent triggers a database write, a release, or a tool call that exceeds the operator's role. |
| **Scope leakage** | An agent that should operate inside one tenant / workspace / environment touches data or actions belonging to another. |
| **Replayability gap** | A reviewer cannot reproduce, six months later, *which* model version, *which* prompt, *which* tools, and *which* approvals produced a given record. |
| **Identity drift** | The agent acts on behalf of an unspecified or implicit operator; the signature on the record cannot be tied to a real person. |

openMiura targets the last four directly through architectural
controls. Hallucination is partly addressed by approval gates and
evidence packs (a hallucinated answer at least appears in the
record alongside the human reviewer's decision), but full
hallucination control remains the responsibility of the agent
runtime, model selection and prompt engineering — areas openMiura
is intentionally agnostic about.

---

## 3. openMiura architectural primitives

openMiura is a thin control plane composed of four primitives.
Each is implemented today; their maturity differs and is labelled
honestly throughout this document.

### 3.1 Policy engine

The policy engine receives every requested *agent action* (a tool
invocation, a runtime dispatch, a release promotion, a memory
write, etc.) along with a context object that names the operator,
the agent identifier, and the scope (`tenant`, `workspace`,
`environment`). It returns one of three verdicts:

- **Allow**: the action proceeds with audit logging.
- **Pending approval**: the action is held until a human
  decision lands in the approval gate.
- **Deny**: the action is rejected and recorded as such.

Policies are declarative. They live in YAML files (see
[`policy_packs/`](policy_packs/) for examples) and combine
matchers (action type, scope, role, payload predicate) with
verdicts. A policy can require a specific approver role
("`security`", "`qa_release`"), a justification text, or a
multi-party signature.

The policy engine is **Beta**: feature-complete for the matchers
listed above, used in the canonical demo, but the YAML schema is
still subject to change before a 1.0 stamp.

### 3.2 Approval gates (human-in-the-loop)

Approval gates are first-class records. Each gate carries:

- The **action** it gates (with the full pre-execution payload).
- The **policy** that triggered it.
- The **approver role** required.
- The **operator** who created the request.
- The **decision**: approved, denied, cancelled, expired.
- The **signer** (a real authenticated identity), the
  **meaning** (e.g. "approved for QA release"), and the
  **timestamp**.

The gate enforces 21 CFR §11.50 *Signature manifestations*:
signer + meaning + timestamp are mandatory, not optional. A gate
that lacks any of the three is rejected at write time.

Gates are exposed through the operations canvas surface and the
admin HTTP API. They can be inspected, replayed and exported.

The approval gate is **Beta**: end-to-end implementation tested in
the canonical demo, but the multi-party signature flow (two
signers required for a single decision) is not yet in production
shape.

### 3.3 Evidence packs (tamper-evident)

Every workflow that ends in a record can produce an **evidence
pack**: a self-contained zip-style export that bundles, for the
record in question:

- The audit trail (policy decisions, approval gates, tool calls).
- The complete prompt-and-completion pairs of the agent
  invocations involved.
- A snapshot of the relevant policy YAML at the time of decision.
- The signed manifest with SHA-256 hashes of every embedded
  artefact.
- The signer identity and the signature meaning.

The pack is what an inspector would ask for during a review. It
is also what the operating organisation files when an external
investigation requires reconstruction of a decision.

Evidence packs are **Beta**: the basic pack format is implemented
and tested; chain-of-custody integration with an external tamper-
evident log (e.g. a corporate immutable store) is **Experimental**.

### 3.4 Scope isolation (tenant / workspace / environment)

Every persistent record carries a triple
`(tenant_id, workspace_id, environment)`. The persistence layer
enforces scope filtering at SQL level — there is no path that
returns records outside the requested scope unless the requester
holds an explicit cross-scope role. This prevents accidental
cross-tenant exposure during search, listing or replay.

Scope isolation is **Beta**: implemented across the persistence
layer (`openmiura/persistence/`) and exercised in the existing
test suite. A formal *negative-scope* security audit (red-team
scenarios attempting to bypass the filter) is **Experimental** —
informal review only.

---

## 4. Mapping to regulatory frameworks

This section sketches *what each framework demands* and *what
openMiura supplies* at the technical layer. The full
control-by-control tables live in the dedicated files:

- [`mapping_21cfr_part11.md`](mapping_21cfr_part11.md)
- [`mapping_eu_gmp_annex11.md`](mapping_eu_gmp_annex11.md)
- [`mapping_gamp5.md`](mapping_gamp5.md)

### 4.1 21 CFR Part 11 — Electronic Records and Electronic Signatures

21 CFR Part 11 governs how the FDA accepts electronic records and
electronic signatures as equivalent to paper-and-ink. The relevant
families for an LLM-agent deployment are:

- §11.10 — Controls for closed systems (validation, accurate
  copies, record protection, RBAC, audit trail, operational
  checks, authority checks, written policies).
- §11.50 — Signature manifestations (signer + meaning +
  timestamp).
- §11.70 — Signature/record linking.
- §11.100 / §11.200 / §11.300 — General requirements for
  e-signatures, components/controls, and identification
  controls.

openMiura's strongest contributions are §11.10(e) (audit trail),
§11.50 (signatures) and §11.70 (linking). It contributes
materially but not exhaustively to §11.10(a)/(b)/(d)/(g) and
§11.100. It is silent on §11.10(h) (device checks),
§11.10(i) (personnel qualification) and §11.300 (password
controls), all of which sit in the operating organisation's quality
system.

### 4.2 EU GMP Annex 11 — Computerised Systems

Annex 11 is the EU manufacturing-side counterpart to 21 CFR Part 11.
The notable additions over Part 11 are around lifecycle, supplier
qualification, inventory of computerised systems, and incident
management. openMiura supports the system-level controls (audit
trail, change control of policies, accuracy of records, business
continuity through database backups). Procedural controls
(validation master plan, supplier audit, training records) remain
organisational.

### 4.3 GAMP 5 — Risk-based approach

GAMP 5 (2nd ed., 2022) provides the lifecycle and software
categorisation framework. We classify openMiura as a **Category 4
"Configured Product"**: the binary is a generic governance plane,
the value comes from the configuration (policy packs, approval
roles, evidence schema). Validation effort scales accordingly: the
configurable parts (YAML policy packs, role definitions) need
documented intent and verification; the binary itself follows the
vendor's own change-management approach (this repository's PRs,
tests and release notes).

### 4.4 ALCOA+ data integrity principles

ALCOA+ extends the original ALCOA principles (Attributable, Legible,
Contemporaneous, Original, Accurate) with Complete, Consistent,
Enduring and Available. The dedicated document
[`alcoa_plus_compliance.md`](alcoa_plus_compliance.md) gives the
self-assessment dimension by dimension. openMiura does well on
**Attributable**, **Contemporaneous**, **Original** and
**Available**. **Enduring** depends on the operating
organisation's backup strategy and is `Partial` for that reason.

---

## 5. Validation strategy

### 5.1 Validation lifecycle

We position openMiura inside a standard V-model:

```
URS  ────────────────────────────────────────────────►  PQ
       \                                              /
        FS  ───────────────────────────────────►  OQ
              \                                /
               DS  ────────────────────►  IQ
                     \              /
                      Code (this repo + policy packs)
```

A reasonable mapping for an organisation introducing openMiura:

- **URS** — Drafted by the organisation; lists the scientific
  workflows it intends to govern with openMiura, with explicit
  acceptable risk levels.
- **FS** — Pulls from the architectural primitives in §3 plus
  the chosen policy packs.
- **DS** — Reuses this whitepaper, the
  [`docs/architecture/persistence.md`](../architecture/persistence.md)
  document, and the policy pack files as the design specification
  inputs.
- **IQ** — Verifies the installation: package version, database
  schema, signed binaries, environment variables. Scripted via
  `openmiura doctor --config <profile>.yaml`.
- **OQ** — Verifies operational behaviour against representative
  scenarios. Reuses the canonical demo
  (`scripts/run_canonical_demo.py`) and the policy-pack regression
  tests.
- **PQ** — Verifies behaviour under the organisation's real
  workload. Scripted as a controlled rehearsal pass through one
  or more of the use cases in [`use_cases/`](use_cases/) before
  go-live.

### 5.2 Risk assessment template

For each workflow under consideration, the template asks:

1. *Severity if the agent's recommendation is wrong* — measured
   on a `low / medium / high` scale anchored to the
   organisation's existing risk matrix.
2. *Probability of error* given the model and the prompt — driven
   by prior evaluation runs and external benchmarks.
3. *Detectability before harm* — does the workflow include a
   human gate before the harmful side-effect occurs?
4. *Resulting risk class* — combination of the three; drives the
   choice of approval policy, signature requirements and evidence
   pack scope.

The approach is deliberately compatible with ICH Q9 and with most
existing internal QRM frameworks; no new vocabulary is introduced.

### 5.3 Test evidence and traceability matrix

For OQ, the organisation maintains a *traceability matrix* with
columns: requirement ID → openMiura primitive → policy pack rule
→ test ID → test result. The repository ships:

- A **canonical demo** (`scripts/run_canonical_demo.py`) that
  exercises a complete *requested change → policy → approval →
  signed release → evidence pack* flow and emits a structured
  JSON report. Used as a smoke test.
- A **policy-pack test fixture** (see
  [`policy_packs/`](policy_packs/) and the corresponding tests
  under `tests/`) that loads each pack, exercises a small set of
  matcher cases, and asserts the policy verdict.

Together these constitute *vendor-side* OQ artefacts. The
*organisation-side* OQ runs additional scripted scenarios for the
specific workflows it governs.

### 5.4 Migration path from a non-governed deployment

Most laboratories interested in openMiura already run an LLM
copilot of some kind, typically a thin wrapper over a third-party
model API. Migrating from that state to a governed deployment is
not a one-step exercise. We sketch a four-stage path that an
organisation can follow:

1. **Mirror mode** — Insert openMiura between the operator and
   the existing copilot without changing the operator's UI. The
   policy engine runs in a permissive mode that records every
   decision but never blocks. This stage gathers data about how
   the copilot is actually used and which actions would have
   triggered which gates. Typically a 2–4 week observation
   window.
2. **Advisory mode** — The policy engine is upgraded from
   permissive to advisory: a gate is shown to the operator on
   sensitive actions, but the operator can choose to override it
   with a justification. The override is recorded and reviewed
   weekly. The number of overrides typically falls fast as the
   policy is tuned.
3. **Enforced mode** — The override is removed; gates that match
   become hard requirements. At this point the workflow is
   technically GxP-ready in terms of the openMiura primitives.
   The operating organisation's quality system still has to
   close the procedural gaps (training, SOPs about the use of AI
   suggestions, incident management) before the workflow is
   actually GxP-released.
4. **Steady state** — Periodic review of the policy pack against
   incidents, model upgrades, and new use cases. The evidence
   packs accumulated under enforced mode become the input to PQ
   re-runs whenever the underlying model is upgraded.

The four stages map naturally onto the V-model: stages 1–2 sit
inside OQ, stage 3 is the PQ entry point, and stage 4 is the
post-PQ steady state.

---

## 6. Reference implementations

The following sketches name **architecture and governance**, not
science. Each one assumes the reader has access to a deployment
of openMiura and has a domain-qualified human reviewer in the
loop.

### 6.1 Analytical interpretation under QA approval

Scenario: an analyst submits an NMR spectrum from a synthesis
batch; an agent proposes peak assignments and impurity
identification; QA must sign before the report enters the
laboratory notebook.

- **Agent role**: drafter, never approver.
- **Tool surface**: spectrum reader, NMR shift database lookup,
  literature retrieval inside the institutional library.
- **Policy**: `analytical_interpretation` pack — every
  assignment that suggests an unknown impurity above a
  configurable threshold triggers an approval gate.
- **Approver role**: `qa_analytical`.
- **Evidence**: signed evidence pack including spectrum hash,
  prompt, completion, policy version, approver identity,
  timestamp.

The flow:

1. Analyst uploads the spectrum; openMiura records the upload
   event with a SHA-256 of the file, scoped to
   `(tenant=lab_X, workspace=batch_42, environment=production)`.
2. The agent runs against a controlled prompt that pins the
   model name, the model version and the temperature.
3. The agent's draft assignments are written to a draft record,
   not to the laboratory notebook.
4. The policy engine inspects the draft. If it suggests an
   unknown impurity above the threshold, an approval gate is
   created; otherwise the draft moves to a `pending_review`
   state.
5. A `qa_analytical` reviewer inspects the draft. The reviewer
   either approves (gate becomes a signed decision and the draft
   is published to the laboratory notebook) or sends back with a
   structured comment.
6. On approval, the evidence pack is generated and stored under
   the same scope. The pack includes everything an inspector
   would need to reconstruct the decision later.

Failure modes openMiura *catches*: hallucinated impurity that the
reviewer can spot in the gate; missing reviewer signature
(blocked at write time); cross-batch contamination through scope
filter (the agent cannot see batch 41's prior data unless
explicitly granted).

Failure modes that remain the operator's responsibility: the
reviewer rubber-stamping without reading; an upstream
signal-processing error that the agent inherits; a corrupt input
file that passes hash verification but is semantically wrong.

### 6.2 SOP authoring with controlled drafting and review

Scenario: an SOP draft is generated from an existing template plus
a change request; a senior author and a QA reviewer must approve
before publication.

- **Agent role**: drafter against a controlled template.
- **Tool surface**: template retrieval, change-request retrieval,
  diff against the previous SOP version.
- **Policy**: `sop_review` pack — publication is gated behind
  two-party approval (author + QA).
- **Evidence**: signed evidence pack with diff, both approval
  gates, and the rendered SOP.

The flow:

1. The author opens a change request that references the
   existing SOP and the regulatory or operational reason for
   the update.
2. The agent retrieves the current SOP, the change request,
   and any cited regulatory text. It produces a draft of the
   new SOP and a *structured diff* against the previous version.
3. The author reviews the diff inside the operations canvas.
   They can edit the draft directly; every edit is recorded as
   a change attribution (author identity + timestamp).
4. When the author submits the draft for publication, the
   `sop_review` policy creates two approval gates: one for the
   document author (self-attestation that the draft is
   complete), one for the QA reviewer (independent verification
   that the change is justified and the diff is acceptable).
5. Only after both gates are signed is the SOP published.
   Publication is itself a recorded event with its own evidence
   pack containing the diff, the two signed gates, the author
   identity, the QA reviewer identity, and a snapshot of the
   policy YAML at the moment of publication.

This pattern is the openMiura analogue of a paper-and-ink
workflow with two independent signatures. The signed evidence
pack replaces the binder folder where SOP histories used to live.

### 6.3 OOS investigation assistant

Scenario: an out-of-specification result triggers an investigation;
the agent assists in walking the standard investigative tree
(equipment, method, calibration, sample preparation) and proposes
a hypothesis ranking.

- **Agent role**: investigator's assistant; the agent **proposes**,
  the investigator **decides**.
- **Tool surface**: equipment maintenance log, calibration
  history, prior OOS records (with scope filtering).
- **Policy**: `ooc_investigation` pack — any closure of the
  investigation requires explicit approval by a designated
  investigator role.
- **Evidence**: signed evidence pack including the investigation
  tree, all hypotheses considered, the closure decision, the
  approver identity.

The flow:

1. The OOS event is registered with a unique investigation ID.
   The scope is set to the originating laboratory and the
   originating batch.
2. The agent walks the standard investigative tree, querying the
   tool surface as it goes. Every tool call is recorded as a
   `tool_call` event in the audit trail, with full request and
   response payload.
3. As the agent collects evidence, it builds a hypothesis list
   ranked by *likelihood given the evidence so far* and *required
   follow-up to confirm or reject*. The list is visible to the
   investigator at all times.
4. The investigator can request additional evidence, override
   any ranking, or add hypotheses the agent did not surface. All
   such interventions are recorded as `decision_trace` events.
5. To close the investigation, the investigator must write a
   structured closure record naming: the root cause (or
   "indeterminate"), the corrective and preventive action
   (CAPA), the affected batches, and the basis for closure. The
   `ooc_investigation` policy gates this write behind an
   approval that requires a designated investigator role.
6. On approval, the evidence pack consolidates the entire tree:
   every tool call, every hypothesis, every intervention, the
   closure record, and the signed approval. The pack is the
   primary artefact a regulatory inspector would request during
   a follow-up audit.

Failure modes openMiura catches: agent hallucinating a
maintenance record (the hash of the underlying log is checked at
retrieval time); investigator closing without listing CAPA
(blocked at write); audit gap between investigation and closure
(the trail is contiguous by construction).

Failure modes the operator must address: an investigator who
approves their own work without independent review (the policy
pack can be tightened to require a second approver, but the
default keeps a single role for speed); an upstream calibration
issue that escapes the tool surface entirely (out of scope for
openMiura).

---

## 7. Limitations and open questions

This section is deliberate. A whitepaper that cannot list its own
gaps is not a serious whitepaper.

- **Vendor lock-in on the model side.** openMiura is agnostic
  about the agent runtime (LLM provider) but the operating
  organisation is not. Model versioning, API stability and the
  exact PQ scope must be re-evaluated whenever the underlying
  model is upgraded. openMiura records the model identifier in
  the evidence pack but does not select the model.
- **Negative-scope security audit.** Scope isolation has been
  verified at the SQL level. A formal red-team audit attempting
  to bypass the filter is `Experimental` — pending.
- **Hallucination is not eliminated.** Approvals catch
  hallucinations *before they leave the system*, but only if the
  approver reads carefully. The organisation must train its
  approvers and structure the approval UI so the relevant
  evidence is visible alongside the agent's claim.
- **Multi-party signature flow.** The current implementation
  supports single-signer approval gates; a polished multi-party
  flow (two signers required, both authenticated, both visible
  on the evidence pack) is on the roadmap.
- **Backup and disaster recovery.** Tamper-evident export is
  `Beta` for the local file output. Integration with a corporate
  immutable store (S3 Object Lock, WORM tape, blockchain anchor)
  is `Experimental`.
- **Personnel-side controls.** Training records, qualification
  evidence, and SOPs about *how the human approver should
  evaluate AI suggestions* are organisational and out of scope
  for openMiura. We recommend explicit training material before
  go-live.

---

## 8. References

The references below are the live source for every claim in this
whitepaper. Each entry has either a public URL or a verifiable
citation. We do **not** fabricate citations; if a reference cannot
be located after a reasonable search, it is removed rather than
invented.

### Regulatory texts

- FDA. *Code of Federal Regulations, Title 21, Part 11 —
  Electronic Records; Electronic Signatures.*
  <https://www.ecfr.gov/current/title-21/chapter-I/subchapter-A/part-11>
- European Commission. *EudraLex — Volume 4, Annex 11:
  Computerised Systems.*
  <https://health.ec.europa.eu/system/files/2016-11/annex11_01-2011_en_0.pdf>
- ISPE. *GAMP 5: A Risk-Based Approach to Compliant GxP
  Computerized Systems*, 2nd ed., 2022.
- WHO. *Guidance on good data and record management practices.*
  WHO Technical Report Series, No. 996, Annex 5.
- MHRA. *'GxP' Data Integrity Guidance and Definitions*, 2018.
- ICH. *Q9 (R1) — Quality Risk Management*, 2023.

### AI governance and safety

- OWASP. *Top 10 for Large Language Model Applications, 2025
  edition.* <https://owasp.org/www-project-top-10-for-large-language-model-applications/>
- OWASP. *Top 10 for Agentic AI Applications* (working draft,
  monitor the project page for the published version).
- European Union. *Regulation (EU) 2024/1689 of the European
  Parliament and of the Council laying down harmonised rules on
  artificial intelligence (AI Act).*
  <https://eur-lex.europa.eu/eli/reg/2024/1689/oj>
- NIST. *AI Risk Management Framework (AI RMF) 1.0*, 2023.
  <https://www.nist.gov/itl/ai-risk-management-framework>

### Software validation

- ISPE. *GAMP Good Practice Guide: Records and Data Integrity*,
  2nd ed.
- FDA. *Computer Software Assurance for Production and Quality
  System Software*, draft guidance, 2022.

### LLM-specific evaluation

- Liang, P. *et al.* Holistic Evaluation of Language Models
  (HELM). *Transactions on Machine Learning Research*, 2023.
  arXiv: 2211.09110.
- Liu, N. F. *et al.* Lost in the Middle: How Language Models
  Use Long Contexts. *Transactions of the Association for
  Computational Linguistics*, 2024. arXiv: 2307.03172.

The bibliography in this whitepaper is intentionally minimal. The
companion file [`docs/academic/references.bib`](../academic/references.bib)
(planned, Phase 4 of the master plan) will hold the consolidated
list with full citation metadata.

---

*Document version: working draft, October 2026. Living document;
expect revision as the implementation matures and as the OWASP
Agentic AI Top 10 stabilises.*
