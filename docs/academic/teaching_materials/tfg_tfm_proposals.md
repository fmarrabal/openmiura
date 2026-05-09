# Five TFG / TFM proposals derived from openMiura

Each proposal is **self-contained** (a student can read it and
self-assess fit) and **scoped to one academic course** (a TFG
of 12 ECTS or a TFM of 12–30 ECTS depending on the master). The
five proposals span low to high technical difficulty and span
software, regulatory and analytical-chemistry profiles.

For all five, the supervisor is Curro (or a co-supervisor inside
his research group). The artefacts produced live either inside
the public openMiura repository (under `extensions/` or `docs/`)
or in a separate student-owned repository, depending on the
proposal.

The Apache-2.0 licence of the openMiura repository extends to
contributions from these projects when they land in the public
repo.

---

## TFG-01 — A red-team negative-scope security audit of openMiura

**Level.** Final-year undergraduate (TFG) in Computer Science
or Cybersecurity. ~12 ECTS.

**Background needed.** Python, SQL (SQLite + PostgreSQL),
basic web-application security (OWASP Top 10), basic
familiarity with FastAPI helpful but not required.

**Problem.** openMiura's persistence layer claims that scope
isolation (tenant_id / workspace_id / environment) is enforced
at SQL level: no path returns records outside the requested
scope. The claim has been verified by reading the code and by
the existing test suite, but no formal red-team audit has
been performed.

**Objectives.**

1. Build a structured threat model focused on cross-scope
   leakage.
2. Implement a battery of negative-scope tests: scenarios
   where the requester is *not* authorised to see data
   belonging to another scope.
3. Identify any path that returns records outside the
   requested scope. For each such path, file a structured
   report (impact, reproducer, suggested fix).
4. Contribute the test battery as a permanent addition to
   the repository.

**Deliverables.**

- Threat model (10–15 pages, in English, suitable for the
  repository under `docs/architecture/security_threat_model.md`).
- Pull request adding the negative-scope test battery to
  `tests/`.
- Final report (TFG defence document, in Spanish or English).

**Scope explicitly excluded.** Network-layer attacks (TLS,
DDoS), social-engineering attacks, attacks that require
physical access to the host. Stay at the application-layer
boundary.

---

## TFG-02 — A LIMS adapter for openMiura

**Level.** Final-year undergraduate (TFG) in Computer Science
or Pharmaceutical Engineering. ~12 ECTS.

**Background needed.** Python, REST API integration, basic
understanding of laboratory information management (one
elective course in the curriculum is enough).

**Problem.** Real laboratories run a Laboratory Information
Management System (LIMS) as the system of record for batches,
samples and instrument logs. openMiura's evidence pack
references workspace identifiers; for a real deployment, the
operator wants the workspace identifier to resolve to the
correct LIMS record without manual cross-walking.

**Objectives.**

1. Design and implement an adapter that, given a workspace
   identifier in openMiura, retrieves the corresponding LIMS
   record (read-only) for inclusion in the evidence pack.
2. Pick a public LIMS API (e.g. LabKey, OpenLab, or the
   institution's existing LIMS) and document the integration
   contract.
3. Add tests using a fake LIMS server (mock or contract test).
4. Update `docs/regulated/pilot_ual/README.md` to describe the
   integration if the institutional NMR LIMS is the one
   chosen.

**Deliverables.**

- LIMS adapter under `openmiura/adapters/lims/` (or a separate
  extension repo if the chosen LIMS is closed-source).
- Tests under `tests/test_lims_adapter.py`.
- Documentation update.
- Final report (TFG defence document).

**Scope explicitly excluded.** Two-way write integration
(updating LIMS records from openMiura) is out of scope; the
adapter is read-only for safety.

---

## TFM-01 — Binding the regulated policy packs to the openMiura policy engine

**Level.** Master (TFM) in Computer Science, Software
Engineering or Data Engineering. 18–24 ECTS.

**Background needed.** Python (advanced), AST manipulation,
schema-validation libraries (jsonschema, pydantic), familiarity
with declarative policy languages helpful (OPA / Cedar etc.
are useful prior art, not required).

**Problem.** The current policy engine reads a legacy YAML
format (`configs/policies.yaml`). The regulated policy packs
under `docs/regulated/policy_packs/` use a richer schema
(matchers, scope-match, when_payload_matches, evidence
inclusion lists). The two formats need to be reconciled so
that the regulated packs are loaded by the engine and enforce
the rules at runtime.

**Objectives.**

1. Specify the union of the two schemas formally
   (jsonschema or equivalent).
2. Implement a schema-aware loader that accepts both formats,
   normalises them to a single internal representation, and
   surfaces clear validation errors.
3. Implement evaluation of the regulated rules
   (`require_approval`, `require_evidence`, `enforce_scope_match`,
   `when_payload_matches`) against agent-action payloads.
4. Ship a migration tool (`openmiura policy migrate`) that
   converts a legacy YAML to the regulated format.
5. End-to-end test: the UAL NMR pilot's smoke-test script,
   currently using a stub evaluator, calls the real engine
   instead.

**Deliverables.**

- Schema specification under `openmiura/policies/schema.py`.
- Loader + evaluator under `openmiura/policies/`.
- Migration tool under `openmiura/cli.py`.
- Tests under `tests/test_policies_engine.py` (target: 30+
  cases).
- Updated demo script.
- Final report (TFM defence document).

---

## TFM-02 — Risk-based AI evaluation harness for openMiura

**Level.** Master (TFM) in Data Science, Computer Science or
Computational Chemistry. 18–30 ECTS.

**Background needed.** Python, statistics, prior coursework
on ML evaluation (HELM-style holistic evaluation, MMLU /
domain benchmarks).

**Problem.** A governed agent in a regulated workflow needs a
periodic evaluation harness: every model upgrade, the operator
must demonstrate that the new model performs no worse than
the previous one against a held-out task suite, and that
performance has not silently regressed in the openMiura-
relevant dimensions (truthfulness, citation, refusal of
out-of-scope tasks).

**Objectives.**

1. Build a harness that, given a model identifier, runs a
   curated task suite and produces a structured evaluation
   record stored as an openMiura evidence pack.
2. Define the task suite for one specific domain
   (e.g. analytical chemistry interpretation; or alternatively
   pharmaceutical-SOP question answering).
3. Compare two open models on the suite; produce a report
   that an operating organisation could attach to a PQ
   re-validation.
4. Document the limits explicitly: which failure modes the
   harness catches, which it does not.

**Deliverables.**

- Harness code under `openmiura/evaluations/regulated/`.
- Task suite (>= 50 cases) with reference answers, in a
  reproducible format.
- Comparison report (TFM defence document).

**Scope explicitly excluded.** Closed-model fine-tuning. Any
clinical / patient-derived dataset (use synthetic or public
benchmarks only).

---

## TFM-03 — A field study of QA practitioner attitudes towards open-source AI governance

**Level.** Master (TFM) in Pharmaceutical Technology, Quality
Management, Regulatory Affairs or Health Informatics. 18 ECTS.

**Background needed.** Foundations of qualitative research
(semi-structured interviews, thematic analysis), awareness of
21 CFR Part 11 and EU GMP Annex 11 at the level of one
elective course.

**Problem.** The openMiura discovery kit
(`docs/regulated/discovery/`) provides interview questions,
target personas and outreach templates. The next step is to
**actually conduct** 10–15 interviews with QA / RA / CSV
practitioners, code the responses, and produce a
qualitative-research-grade analysis of whether the openMiura
governance pattern matches their pain points.

**Objectives.**

1. Recruit 10–15 interviewees across at least three of the
   six personas (QA Director, CSV/CSA, QC Analytical, RA,
   IT-OT, Hospital Research).
2. Conduct semi-structured 30–45 minute interviews using the
   provided Mom-Test script.
3. Code the interview transcripts thematically.
4. Produce a qualitative research report including:
   - Pain points mapped to the four openMiura primitives.
   - Disagreement between practitioners' framing and the
     project's framing (the most informative output).
   - Recommended changes to the project's framing or
     architecture.
5. Update `docs/STRATEGY.md` with the qualitative findings as
   the input to the strategic decision.

**Deliverables.**

- Interview transcripts (anonymised), stored in a
  student-owned repository per IRB / Ethics Committee
  approval.
- Coded thematic analysis (15–25 pages, suitable for a
  TFM defence).
- Updated `docs/STRATEGY.md` with a "discovery findings"
  section.

**Scope explicitly excluded.** Quantitative survey methodology
(this is a qualitative study; the sample size is too small for
statistical claims). Any clinical interview that touches
patient data.

---

## How to choose between the five

| Profile | Best fit |
|---|---|
| Software-only, looking for a clean security project | TFG-01 |
| Software + lab interest, hands-on integration | TFG-02 |
| Software-heavy, language / parser / type-system inclined | TFM-01 |
| Data-science / ML-evaluation profile | TFM-02 |
| Qualitative research, regulatory or quality-management profile | TFM-03 |

For each, the prerequisite reading is the same: the openMiura
technical whitepaper and the relevant section of the master
plan in `CLAUDE.md`. Initial scoping conversations with the
supervisor should happen before the project is formally
proposed; one good signal is that the student can, after the
first conversation, restate the problem in their own words.
