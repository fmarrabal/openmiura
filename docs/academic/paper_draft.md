# openMiura: an open governance layer for LLM agents in regulated scientific environments

*Working draft, May 2026. The paper accompanies the public
implementation at <https://github.com/fmarrabal/openmiura>.*

**Author:** Francisco Manuel Arrabal Campos
(Universidad de Almería, Spain).
**Acknowledgements:** the implementation has been developed
iteratively with Anthropic Claude (see `AGENTS.md` in the
repository for the full disclosure).

**Target venues considered, ordered by fit:** *Computers in
Industry*, *Computers & Chemical Engineering*, *Journal of
Pharmaceutical Innovation*, *Future Generation Computer
Systems*, *npj Digital Medicine* (if a clinical pilot
materialises), and AI-governance workshops at ACL / EMNLP.

---

## Abstract

LLM-driven agents are entering regulated scientific workflows
faster than the validation frameworks designed for classical
computerised systems can adapt. We present openMiura, an open
governance layer that sits in front of an arbitrary agent
runtime and enforces four primitives — policy, approval gates,
tamper-evident evidence packs and scope isolation — without
attempting to validate the agent's internal reasoning. We
position openMiura as a Category 4 product under GAMP 5: a
configured platform where the value comes from the policy
packs, not from the binary. We map the primitives
control-by-control to FDA 21 CFR Part 11, EU GMP Annex 11 and
ALCOA+ data integrity, and we argue that the platform
contributes meaningfully to roughly half of the technical
controls in those frameworks while making the residual
organisational responsibilities explicit. We describe a
non-clinical reference implementation: a governed assistant
for ¹H / ¹³C NMR interpretation of organometallic catalytic
compounds at the Universidad de Almería, with three distinct
identities, signed two-party approval, and a reproducible
smoke-test artefact. We discuss the limits of any governance
layer that cannot, by construction, eliminate hallucination
inside the agent itself, and we frame the path that takes a
non-governed laboratory copilot through four stages — mirror,
advisory, enforced, steady-state — that are individually
testable. The contribution is a working platform plus a
control-mapping that practitioners can use today; the open
question is whether the pattern survives contact with a
sufficient number of QA / regulatory teams to become the
default.
*(247 words)*

## 1. Introduction

The pharmaceutical and laboratory communities have built, over
five decades, a robust set of validation frameworks for
computerised systems: Computerised System Validation (CSV) and
the more recent Computer Software Assurance (CSA) approach,
the V-model lifecycle, the GAMP categorisation [@gamp5], the
21 CFR Part 11 [@cfr_part_11] and EU GMP Annex 11
[@eu_annex_11] regulatory expectations, and the ALCOA+ data
integrity principles [@who_data_integrity; @mhra_data_integrity].
These frameworks assume **deterministic** software: given the
same input, the same output is reproducible, explainable and
defensible. Validation effort is proportional to risk; a
Category 5 custom application requires the full V-model
lifecycle, while a Category 4 configured product is validated
mainly through its configuration.

LLM-driven agents break the determinism assumption in three
ways. They are non-deterministic by construction (two
identical prompts can yield different completions). They have
an open-ended action space (a tool-using agent can compose a
sequence the validator did not anticipate). And their internal
knowledge drifts between releases (a Performance Qualification
on model M_i is not, by itself, evidence about model M_(i+1)).
The conclusion is not that LLM agents cannot be validated; it
is that the validation has to operate **around** the agent
rather than verifying it from inside.

This paper describes openMiura, an open-source governance
layer designed to do exactly that. The contribution is
three-fold:

1. A *minimal* set of architectural primitives — policy,
   approval gates, evidence packs, scope isolation — that
   together constitute a credible technical contribution to
   the relevant regulatory frameworks.
2. A *control-by-control* mapping of those primitives to
   21 CFR Part 11, EU GMP Annex 11, GAMP 5 and ALCOA+, with
   honest *Stable / Beta / Partial / Experimental / n/a*
   labels per control. We explicitly avoid declarations of
   conformity; the labels reflect the implementation today.
3. A *non-clinical reference implementation* in the form of
   a governed assistant for NMR interpretation, with a
   reproducible smoke-test artefact that runs in CI without
   real spectra or patient data.

The paper is organised as follows. §2 reviews adjacent
governance and observability platforms. §3 presents the
architectural primitives. §4 summarises the regulatory
mapping. §5 describes the UAL NMR reference implementation.
§6 discusses limits, open questions and the four-stage
migration path from non-governed to governed deployment. §7
concludes.

## 2. Related work

The closest comparable systems split into three groups.

**LLM-observability platforms.** LangSmith and Langfuse trace
LLM calls and provide replayable session logs. They are
indispensable for *debugging* but do not implement signature
manifestation, approval gates with role enforcement, or
tamper-evident evidence packs in the GxP sense. The audit
trail they capture is a developer artefact, not a regulatory
artefact. A pharmaceutical QA team that adopts LangSmith for
visibility still has to build, by themselves, the
signer + meaning + timestamp record that 21 CFR §11.50 and
EU GMP Annex 11 control 14 require — usually as a separate
spreadsheet or workflow tool that is then itself an
unvalidated computerised system, with the cycle starting
again.

**Governance gateways.** Portkey and Credal sit in front of
LLM API calls and apply policies (PII redaction, model
selection, cost guardrails). They are closer in spirit to
openMiura's policy engine, but their approval-gate concept is
operational (e.g. "this prompt requires approval before being
sent to a model") rather than regulatory (signer + meaning +
timestamp tied to a record). Credal in particular has an
enterprise-compliance focus, but its evidence model is closed
and not aligned with 21 CFR Part 11 §11.50 / §11.70. A reviewer
cannot inspect Credal's approval gate format and conclude that
it is — or is not — congruent with the framework they validate
against; the only available answer is the vendor's marketing
claim, which a regulatory inspection does not accept.

**Cloud agent-governance bundles.** Microsoft Agent Governance
Toolkit, AWS Bedrock Agents and Google Vertex AI Agent Builder
include logging, role-based access and content filtering as
part of their cloud bundle. None of them is open source. None
of them ships a control-by-control mapping to GxP frameworks
that a Quality Assurance reviewer can put in a validation
package without further work. Data sovereignty under EU pharma
data protection rules [@gdpr] is also a recurring concern for
EU-regulated organisations adopting US cloud-bundled tooling;
several mid-size pharma companies have stated openly that they
require either an on-premises or an EU-region-only deployment
for any system that touches their batch records, which rules
out most cloud-bundle answers as the *primary* governance
plane.

**Academic prototypes.** A handful of academic prototypes
explore agent governance in research settings, but they are
typically (a) tied to a specific runtime, (b) released under
ad-hoc licences that complicate adoption inside a corporate
quality system, and (c) do not provide regulatory mappings.
We position openMiura as the bridge between the academic
clarity of intent and the production-grade requirements of
GxP environments.

The literature on LLM evaluation [@helm; @lost_in_the_middle]
and the regulatory-side analysis of LLM-assisted clinical
decision support [@samd_action_plan; @imdrf_samd] complement
this paper but address adjacent problems: model evaluation
upstream of the agent, and SaMD classification of the model
itself. The novelty of openMiura is the **governance plane**
between the agent and the regulated record — a gap the
literature acknowledges but does not yet fill with an
open-source artefact.

## 3. System design

### 3.1 Policy engine

The policy engine receives every requested *agent action* (a
tool invocation, a runtime dispatch, a release promotion, a
record write) along with a context object naming operator,
agent identifier and scope (`tenant`, `workspace`,
`environment`). It returns one of three verdicts: *allow*,
*pending approval*, or *deny*. Policies are declarative YAML;
matchers combine action type, scope, role and payload
predicates with verdicts. A policy can require a specific
approver role, a justification text, or a multi-party
signature.

### 3.2 Approval gates

Approval gates are first-class records. Each gate carries the
gated action with the full pre-execution payload, the policy
that triggered it, the approver role required, the operator
who created the request, the decision (approved / denied /
cancelled / expired), the **signer** (a real authenticated
identity), the **meaning** (e.g. "approved for QA release"),
and the **timestamp**. The gate enforces 21 CFR §11.50: a
gate that lacks any of the three signature components is
rejected at write time.

### 3.3 Evidence packs

Every workflow that ends in a record can produce a self-
contained evidence pack: the audit trail (policy decisions,
approval gates, tool calls), the complete prompt-and-completion
pairs of the agent invocations involved, a snapshot of the
relevant policy YAML at the time of decision, the signed
manifest with SHA-256 hashes of every embedded artefact, and
the signer identity and signature meaning. The pack is the
unit of record an inspector or an internal investigation
would request.

### 3.4 Scope isolation

Every persistent record carries a triple
`(tenant_id, workspace_id, environment)`. The persistence
layer enforces scope filtering at SQL level — there is no path
that returns records outside the requested scope unless the
requester holds an explicit cross-scope role. This is the
technical mechanism that prevents accidental cross-tenant
exposure during search, listing or replay.

### 3.5 Implementation

The reference implementation is a Python application built on
FastAPI [@fastapi] and SQLite/PostgreSQL. After Phase 1 of
the project, the persistence layer comprises 12 specialised
repository classes under `openmiura/persistence/`, none of
them over 1,500 lines of code. The HTTP admin layer is split
into 15 sub-routers under `openmiura/interfaces/http/routes/admin/`.
The codebase is GAMP 5 Category 4: the binary is generic, the
configuration (policy packs in YAML, role assignments,
deployment profile) is the validated artefact.

## 4. Mapping to regulatory frameworks

We summarise the mapping; the full control-by-control tables
live in the project repository under `docs/regulated/`.

**21 CFR Part 11.** openMiura contributes meaningfully to 15
of 26 controls (Beta or Partial); 7 of 26 are out of technical
scope (organisational training, hardware tokens, certification
to FDA). The strongest contributions are §11.10(e) audit
trail, §11.50 signature manifestations and §11.70
signature/record linking. These are also the controls under
which most CSV remediations get cited, so the contribution is
practically valuable, not merely formal.

**EU GMP Annex 11.** openMiura contributes to 19 of 25
controls; 5 of 25 are organisational. The strongest
contribution is control 14 (electronic signatures: signer +
meaning + timestamp + linked_record_id, all enforced at write
time) and control 15 (batch release: QP role enforcement on
the release approval gate, with the QP identity in the
evidence pack).

**GAMP 5.** The platform is Category 4. Validation effort
scales with the configuration. We provide a four-stage
migration path — *mirror*, *advisory*, *enforced*,
*steady-state* — that maps onto the V-model: stages 1–2 sit
inside Operational Qualification, stage 3 is the Performance
Qualification entry point, and stage 4 is the post-PQ steady
state.

**ALCOA+.** Of the nine dimensions, seven are *Strong* at the
technical layer (Attributable, Legible, Contemporaneous,
Original, Complete, Consistent, Available). Two are *Partial*:
*Accurate* depends on the agent's output (no governance plane
can solve hallucination from outside), and *Enduring* depends
on the operating organisation's long-term storage substrate.
The honest pattern of "Strong on Attributable / Contemporaneous /
Complete; Partial on Accurate / Enduring" is exactly what the
MHRA 2018 guidance [@mhra_data_integrity] expects from a
well-built electronic record system: the technical platform
makes integrity *checkable*, and the organisation builds the
procedures and training that make the data *trustworthy*.

## 5. Reference implementation: governed NMR interpretation at UAL

We describe the first openMiura pilot. It is **non-clinical by
design**. The use case is the interpretation of ¹H / ¹³C NMR
spectra of organometallic catalytic compounds inside a single
research group at the Universidad de Almería. Three distinct
identities operate the workflow: a *preparer* uploads the
spectrum and metadata; an *nmr_reviewer* (senior chemist)
reviews the agent's draft assignments against the spectrum
and known chemistry; a *pi_approver* signs the final
assignment for the laboratory notebook. Reviewer-before-
approver ordering is enforced by the policy engine.

The pilot's policy pack splits the publication action into two
paths. Routine assignments require *nmr_reviewer* attestation
only; an unknown-impurity flag above a configurable threshold
or a new-ligand identification escalates to *pi_approver*.
Spectrum SHA-256, model name and version, and prompt SHA-256
are pinned at draft time. Paramagnetic samples are explicitly
out of scope.

A reproducible smoke-test artefact (`scripts/run_pilot_ual_nmr_demo.py`)
walks the synthetic workflow end to end and writes a signed
JSON report. The script is idempotent: the manifest hash is
stable across runs for the same synthetic input. The smoke
test is the *vendor-side* Operational Qualification artefact;
the *organisation-side* PQ requires three real spectra
acquired over three different days by three different
preparers, plus one controlled "known wrong" spectrum that the
reviewer must catch before it reaches the approver.

The pilot intentionally does not include any patient-related
or clinically sensitive data. A separate document
(`docs/regulated/pilot_clinical_governance.md` in the
repository) describes the reusable architecture pattern for a
future clinical pilot, with explicit separation of repositories
(governance plane vs clinical data), four mandatory roles, and
seven minimum policy primitives including
*payload_anonymisation_attested* and
*irb_reference_required_for_publication*.

## 6. Discussion

### 6.1 What openMiura cannot do

A governance layer cannot eliminate hallucination inside the
agent. Approval gates catch hallucinations *before they leave
the system* if the approver reads carefully — but only if the
approver reads carefully. The operating organisation must
train its approvers and structure the approval interface so
that the relevant evidence is visible alongside the agent's
claim. We frame this trade-off explicitly in the limitations
section of the technical whitepaper [@openmiura_whitepaper].

### 6.2 Validation lifecycle and the four-stage migration

We propose a four-stage migration path for organisations that
already run a non-governed LLM copilot. *Mirror* mode runs
openMiura permissively for 2–4 weeks to gather data on which
actions would have triggered which gates. *Advisory* mode
upgrades to soft gates with operator override and recorded
justification. *Enforced* mode removes the override; gates
become hard requirements. *Steady-state* is the post-PQ
periodic-review loop, anchored in evidence packs accumulated
under enforced mode. The four stages are individually
testable, and they map onto the V-model at OQ → PQ → post-PQ.

### 6.3 Open questions

Three open questions remain and would benefit from
collaboration with practitioners.

First, the *negative-scope* security audit. Scope isolation
has been verified at the SQL level. A formal red-team audit
attempting to bypass the filter is on the roadmap and remains
open.

Second, *long-term tamper-evident storage*. Evidence packs
have a stable file format and a signed manifest. Integration
with corporate WORM substrates (S3 Object Lock, immutable
filesystem, blockchain anchor) is documented but not yet
deployed in production.

Third, *multi-party signature flows* under §11.200(a)(3) of
21 CFR Part 11. Single-signer approval gates are stable;
two-signer flows where both signers must independently
authenticate are implemented in policy form
(`deviation_report.yaml` requires this for critical
deviations) but the end-to-end UI flow is not yet shipped.

### 6.4 Threats to validity

Three threats to validity are worth naming explicitly.

The *empirical evidence base* is currently one synthetic
smoke-test artefact and a discovery interview kit that has not
yet been exercised at scale. We do not claim that the
governance pattern is proven by the work in this paper; the
contribution is the artefact and the mapping. The discovery
phase will produce, over the next 4–8 weeks, the qualitative
data needed to assess whether the pattern matches a real pain
across organisations. We commit to publishing follow-up work
that incorporates that data, including negative findings if
the discovery shows the pattern is incomplete.

The *generalisation across regulatory contexts* deserves
caution. The mappings cover FDA 21 CFR Part 11, EU GMP
Annex 11, GAMP 5 and ALCOA+. These are dominant in
pharmaceutical and biomedical workflows but are not the only
frameworks that matter: ISO 13485 (medical devices), the EU
AI Act [@eu_ai_act] obligations for high-risk AI systems,
and national data-protection regulations layered on top of
GDPR each add controls that openMiura's primitives may or
may not contribute to. We have flagged the most directly
relevant in §4 and we acknowledge the rest as out of the
scope of this paper.

The *vendor-side / organisation-side boundary* is, finally,
the most operationally consequential threat. Many of the
controls the project labels as `Partial` depend on
organisational behaviour the platform cannot enforce: backup
schedules, training records, periodic re-evaluation of
validated systems, identity proofing of signers. A reader
who interprets the maturity table as a substitute for the
operating organisation's quality system will be unpleasantly
surprised by an inspector. We have stated the boundary
clearly throughout the project documentation, but the gap
between *what the vendor delivers* and *what the operator
must build* is not a problem any platform of this kind can
fully close.

## 7. Conclusion

openMiura is a working open governance layer for LLM agents
in regulated scientific environments. It is intentionally
narrow: it does not run the agent, does not validate the
model, does not prove the absence of hallucination. It does
enforce a small, defensible set of primitives (policy,
approval gates, evidence packs, scope isolation) that map
honestly to the dominant regulatory frameworks (21 CFR
Part 11, EU GMP Annex 11, GAMP 5, ALCOA+).

The contribution of this paper is the artefact plus the
control mapping, both available under an Apache-2.0 licence.
The open question is empirical: whether the pattern matches
the pain of QA / RA practitioners across enough organisations
to become a community default. The discovery phase of the
project (`docs/regulated/discovery/` in the repository) is
the cheapest way to find out, and we welcome practitioner
feedback at the project URL above.

We close on a claim and a wish. The claim is that the pattern
of "thin governance plane in front of the agent runtime, plus
an honest control-by-control mapping, plus a real reference
implementation that runs without patient data or proprietary
chemistry" is reproducible by other groups in their own
domains: the four primitives translate well from analytical
chemistry to clinical research, from manufacturing release
to laboratory information management. The wish is that the
community of regulated-AI practitioners — quality assurance,
regulatory affairs, computer-system validation, computer
software assurance — engages with the artefact as something
they can fork, adapt and contribute back to, rather than as a
closed product. The frameworks the project maps onto are
public; the platform that implements the mapping should be
public too.

## References

The bibliography lives in `docs/academic/references.bib`. It
contains over 25 entries with verifiable DOI / arXiv /
official-URL references; no citation in this paper has been
fabricated. Inline citation keys follow standard BibTeX
conventions.
