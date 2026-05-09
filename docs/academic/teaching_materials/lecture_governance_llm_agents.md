# Lecture — Governance of LLM agents in regulated scientific environments

*90 minutes. Standalone module, slot anywhere in a course on
AI for laboratory science / biomedical engineering /
pharmaceutical technology / data science applied to the lab.*

## Learning objectives

By the end of the session a student should be able to:

1. Explain why classical computerised-system validation does
   not transfer 1:1 to LLM-based agents.
2. Name the four primitives a governance plane needs to
   provide and describe each in one sentence.
3. Map a single technical control (e.g. 21 CFR §11.50, EU GMP
   Annex 11 control 14) onto a concrete software primitive.
4. Identify, given a workflow description, where in the flow
   an approval gate would be required and what the signature
   meaning would be.
5. Distinguish architectural responsibility (the platform)
   from organisational responsibility (the quality system).

## Format

| Time | Block | Activity |
|---|---|---|
| 00:00 – 00:10 | Block 1 — Why this matters | Lecture + Q&A |
| 00:10 – 00:25 | Block 2 — Three failure modes | Lecture |
| 00:25 – 00:50 | Block 3 — Architectural primitives | Lecture + 1 micro-exercise |
| 00:50 – 01:05 | Block 4 — Mapping to GxP frameworks | Lecture |
| 01:05 – 01:25 | Block 5 — Walkthrough of the UAL NMR pilot | Demo + Q&A |
| 01:25 – 01:30 | Block 6 — Closing + readings | Discussion |

## Slide-deck outline

> Build a slide deck of ~25 slides from the bullets below. Two
> slides per main bullet, one slide per sub-bullet, plus title
> and references slides.

### Block 1 — Why this matters (10 minutes)

- Concrete opener: a hallucinated NMR peak assignment that an
  inexperienced student copies into a manuscript.
- The cost of that single error in three different settings
  (academic preprint, GxP batch release, clinical research).
- The misconception ("AI will solve this") vs the realistic
  framing ("the audit trail is the deliverable, not just the
  result").
- Quick poll: who in the room has reviewed an audit trail
  recently? who has produced one for an AI-assisted decision?

### Block 2 — Three failure modes (15 minutes)

- *Non-determinism by construction.* Same prompt, different
  completion. Demo: run the same query twice on a public LLM
  and show the diff.
- *Open-ended action space.* A tool-using agent composes a
  sequence the validator did not anticipate.
- *Knowledge that drifts.* PQ on model M_i is not, by itself,
  evidence about M_(i+1).
- The conclusion is **not** "LLM agents cannot be validated".
  The conclusion is "validation has to operate around the
  agent, not from inside it".

### Block 3 — Architectural primitives (25 minutes)

- *Policy engine.* Declarative rules. Verdicts: allow, pending
  approval, deny.
- *Approval gates.* Signer + meaning + timestamp. First-class
  records.
- *Evidence packs.* Self-contained, signed, replayable.
- *Scope isolation.* Tenant / workspace / environment, enforced
  at SQL level.
- **Micro-exercise (10 min).** Given a one-sentence workflow
  ("an agent drafts an OOS investigation closure"), the student
  identifies which primitives apply and what the approval gate
  would look like (role, meaning, payload-required fields).
  Discuss in pairs, present 2–3 examples.

### Block 4 — Mapping to GxP frameworks (15 minutes)

- Snapshot of 21 CFR Part 11 (Subpart B controls + §11.50 +
  §11.70). Map §11.50 to the approval gate primitive, live.
- Snapshot of EU GMP Annex 11 (control 14 electronic
  signatures, control 15 batch release).
- One sentence on GAMP 5 categorisation: openMiura is Category
  4; the LLM agent is closer to Category 5.
- ALCOA+: the platform is *Strong* on Attributable /
  Contemporaneous / Complete; the operating organisation is
  responsible for *Accurate* (training reviewers) and
  *Enduring* (long-term storage substrate).

### Block 5 — Walkthrough of the UAL NMR pilot (20 minutes)

- The non-clinical case: ¹H / ¹³C NMR of organometallic
  catalysts.
- Three identities: preparer / nmr_reviewer / pi_approver.
  Why three.
- The flow, with slides showing the policy pack (YAML),
  the evidence pack (JSON), the smoke-test artefact.
- Live demo: run `scripts/run_pilot_ual_nmr_demo.py` in two
  modes (routine, escalation) and inspect the produced JSON
  on the projector. ~5 minutes including Q&A.
- The boundary: what the pilot proves (the platform works
  end-to-end), and what the pilot does **not** prove
  (the agent's NMR assignments are correct without review).

### Block 6 — Closing (5 minutes)

- Take-home message:
  - Governance ≠ algorithm.
  - The audit trail is part of the deliverable.
  - Architectural responsibility ≠ organisational responsibility;
    both are needed.
- Readings (post on the course platform):
  - openMiura technical whitepaper (`docs/regulated/whitepaper.md`).
  - 21 CFR Part 11 (skim only the section headers; depth on
    §11.10(e), §11.50, §11.70).
  - GAMP 5 chapter 6 (categorisation) — book chapter only.
  - One short blog post or news article about a recent
    AI-related GxP incident, chosen by the lecturer that year.
- Optional follow-up: TFG / TFM proposals (next document).

## Assessment options

For courses that include this lecture as part of a graded
module:

- *Short essay (1,500 words).* "Walk a chosen GxP workflow
  through the four primitives. Identify one approval gate, one
  evidence pack, one scope decision. Explain what stays
  organisational."
- *Take-home exercise.* Modify one of the existing policy
  packs in the openMiura repo to require an additional
  signature meaning, run the smoke-test demo, and submit the
  evidence-pack JSON plus a one-page diff explanation.
- *Group presentation.* Pick a use case (clinical or
  industrial) not covered in the openMiura repository and
  produce a one-slide governance architecture for it.

## Lecturer notes

- Adjust block 4 timing if the audience already knows
  21 CFR / Annex 11. Spending 15 minutes there with QA
  professionals is too little; spending 15 minutes with
  computer-science students with no regulatory background is
  too much. Tune.
- The micro-exercise in block 3 is the part students remember.
  Do not skip it for time.
- The live demo in block 5 should be rehearsed once before the
  session. The smoke-test script writes a deterministic JSON;
  the file lives under `/tmp/` by default — point a viewer at
  it before walking up to the lectern.
