# ALCOA+ data integrity self-assessment

ALCOA+ extends the original ALCOA principles (Attributable,
Legible, Contemporaneous, Original, Accurate) with Complete,
Consistent, Enduring and Available. Together the nine
dimensions form the most-cited yardstick for data integrity in
pharmaceutical inspections.

This document evaluates openMiura against each dimension. The
evaluation is intentionally honest: we mark a dimension `Strong`
only when the evidence is contemporaneous and machine-checkable;
we mark it `Partial` whenever the property holds at the
technical layer but depends on an organisational behaviour that
openMiura cannot enforce.

References:

- WHO. *Guidance on good data and record management practices.*
  Annex 5, TRS 996. <https://www.who.int/publications/m/item/trs996-annex5>
- MHRA. *'GxP' Data Integrity Guidance and Definitions*, 2018.
  <https://www.gov.uk/government/publications/guidance-on-gxp-data-integrity>

---

## A — Attributable

> Each piece of data should be linked to the individual who
> generated, modified or signed it.

**openMiura status: `Strong`.**

Every persistent record carries the principal id of the writer.
Approval gates require an authenticated `signer`, and the signer
identity is part of the evidence-pack manifest. The audit trail
records every `tool_call` and `decision_trace` against the
session principal. There is no path that produces an
unattributed record without explicit configuration to bypass
RBAC, which is rejected by the policy engine.

Caveat: attribution to a *person* (rather than to a *principal
id*) is only as strong as the operating organisation's identity
proofing. Whether the principal id corresponds to a real,
qualified individual is an organisational concern.

## L — Legible

> Records should be readable in a way that allows interpretation
> over the data's retention period.

**openMiura status: `Strong`.**

Every record is stored in plain SQL columns or JSON; there is
no opaque binary format. Evidence packs render every signed
record into a human-readable companion (Markdown / HTML); the
operations canvas displays records inline.

Caveat: long-term legibility (decades) requires the operating
organisation to keep the evidence-pack format documentation
alongside the archived packs. The repository documents the
manifest format in code comments and in
[`whitepaper.md §3.3`](whitepaper.md).

## C — Contemporaneous

> Data should be recorded at the time of the activity.

**openMiura status: `Strong`.**

Every audit-trail event carries the database-side timestamp of
the write; there is no path that allows backdating a record
through the public API. Evidence packs are generated at the
moment of approval, not at retrieval time.

Caveat: clock accuracy depends on the deployment environment.
The recommended deployment profile uses NTP-synchronised hosts;
clock skew is reported by `openmiura doctor`.

## O — Original

> The first capture of the data should be preserved (or a true
> copy thereof should be retained).

**openMiura status: `Strong`.**

Records are append-only in the audit trail. Updates are
modelled as new rows that reference the prior version; the
original is never overwritten. Evidence packs include the
original prompt-and-completion pairs of the agent invocations
involved, not a summarised version.

Caveat: pruning long-term records (e.g. for storage cost
reasons) is an organisational decision and must be made in
accordance with the data retention policy. openMiura provides
`prune_memory` and similar primitives but does not call them
unsolicited.

## A — Accurate

> Data should be free from errors and reflect the true outcome
> of the activity.

**openMiura status: `Partial`.**

openMiura cannot verify the accuracy of agent output (that is a
property of the model, the prompt and the source data). It can
ensure that what is captured is what the agent produced (no
silent transformation between completion and persistence) and
that approvals are tied to the captured content.

Caveat: accuracy of the agent's output remains the joint
responsibility of the model selection, the prompt design and
the human reviewer who approves the gate.

## C — Complete

> Data should include all relevant information, including any
> repeated or repeated test data, original results before any
> calculations, and any audit trail entries.

**openMiura status: `Strong`.**

Every tool call, every prompt, every completion, every gate,
every approval and every retraction is recorded. Evidence packs
bundle them together for the record in question. There is no
"summary mode" that drops intermediate steps.

Caveat: completeness of the *agent's* internal reasoning (the
chain-of-thought, intermediate latent states) is not captured —
that level of detail is not exposed by current LLM APIs in a
durable, comparable form.

## C — Consistent

> Data should be presented in chronological order, with no gaps
> in the sequence.

**openMiura status: `Strong`.**

The audit-trail tables use monotonically increasing IDs and
timestamps. The evidence-pack manifest verifies the chain by
hash. A gap in the sequence is detectable both at write time
(constraint violation) and at retrieval time (manifest
verification failure).

## E — Enduring

> Data should be retained for the required retention period in
> a form that resists corruption.

**openMiura status: `Partial`.**

The local backup directory and the evidence-pack export
support medium-term retention. Long-term tamper-evident
storage (S3 Object Lock, WORM tape, blockchain anchor) is
**`Experimental`**: the integration hooks exist but production
deployments are not documented yet.

The operating organisation must define its retention policy
and the storage substrate. openMiura's contribution is the
file format and the integrity manifest; the storage commitment
is the organisation's.

## A — Available

> Data should be retrievable on demand throughout the retention
> period.

**openMiura status: `Strong` (within deployment lifetime).**

Records are accessible through the admin HTTP API, the
operations canvas and the evidence-pack export at any time.
Scope filtering and RBAC apply on retrieval, but they do not
affect availability for authorised users.

Caveat: availability across deployment migrations or vendor
transitions depends on the operating organisation maintaining
either the openMiura binary or a documented import path into a
successor system.

---

## Summary

| Dimension | Status |
|---|---|
| Attributable | `Strong` |
| Legible | `Strong` |
| Contemporaneous | `Strong` |
| Original | `Strong` |
| Accurate | `Partial` (agent accuracy is out of scope) |
| Complete | `Strong` |
| Consistent | `Strong` |
| Enduring | `Partial` (long-term WORM substrate is org-side) |
| Available | `Strong` (within deployment lifetime) |

Reading the table: openMiura's audit-trail design carries 7 of
the 9 ALCOA+ dimensions at the technical layer. The two that
are `Partial` (Accurate, Enduring) reflect honest scope limits:

- **Accurate** — openMiura can record what the agent produced
  and tie it to a reviewer's signature, but the truth value of
  the agent's claim is a domain-knowledge problem the
  governance plane cannot solve.
- **Enduring** — openMiura provides the file format; the
  storage substrate is organisational.

This pattern of "strong on Attributable / Contemporaneous /
Complete; partial on Accurate / Enduring" is exactly what the
MHRA 2018 guidance expects from a well-built electronic record
system: the technical platform makes integrity *checkable*, and
the organisation builds the procedures and training that make
the data *trustworthy*.
