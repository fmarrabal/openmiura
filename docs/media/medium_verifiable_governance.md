<!--
DRAFT for Medium — written to be edited and published by Francisco (Curro).
Angle: verifiable governance (what + who + when, checkable offline).
Tone per CLAUDE.md §3.2: honest, technical, no hype, no conformance claims.
Every command below is evidenced by a captured run committed to the repo
(docs/academic/simulation/results/) against release 1.1.0; the reader-facing
steps were re-walked in order before writing.
Suggested Medium tags: LLM, AI Governance, Open Source, Compliance, Python.
-->

# Your AI agent's audit trail is only as good as a skeptic can prove

*An open-source governance plane where "what happened, who approved it, and when" survives an audit — and you can check the evidence yourself, offline.*

We are wiring LLM agents into workflows that used to be done by people under a paper trail: releasing a configuration, approving a batch, signing off on an analytical result. The agent is fast. The problem shows up later, when someone asks a boring question: **prove what the agent did, who authorized it, and when it happened.**

Most agent stacks answer with logs. But a log you can edit is not evidence. If the record lives in a table your own service can `UPDATE`, then "the agent did X, approved by Y, at time T" is a claim, not a fact — and in a regulated or high-stakes setting, a claim that only you can vouch for is worth very little.

[openMiura](https://github.com/fmarrabal/openmiura) is an open-source (Apache-2.0) governance plane for LLM agents built around one idea: **the audit trail should be verifiable by a third party who does not trust you.** Not "trust our dashboard" — hand a skeptic a file and let them check the math on their own laptop.

This post is not a pitch. The repository ships the evidence: a reproducible end-to-end run, its captured results, and a signed evidence pack you can verify right now.

## The gap: three questions an audit asks

A record that stands up to scrutiny has to answer three things, and answer them in a way the reader can independently verify:

- **What** happened — and has the record been altered since?
- **Who** authorized it — bound to a real identity, not a free-form string?
- **When** — attested by someone other than the party being audited?

openMiura maps these to three cryptographic primitives. Let's install it and walk through each.

```bash
pip install openmiura
```

## WHAT: a tamper-evident audit trail

Every governance-relevant write — events, tool calls, decision traces, release approvals — is appended to a per-scope hash chain: each row stores a `row_hash` over its canonical content plus the previous row's hash. The operational tables additionally enforce append-only with database triggers that reject `UPDATE`/`DELETE`; the approvals table is guarded by the chain itself. One command re-walks every chain:

```bash
openmiura db verify-chain --config openmiura.yaml
# exit 0 = intact, 1 = tamper detected, 3 = usage error (e.g. migrations not applied)
```

If someone edits a row in the SQLite file without recomputing everything downstream, `verify-chain` returns non-zero and points at the first bad row.

Honesty requires one more sentence, because a skeptic will ask: what if the attacker recomputes the *whole* chain and its stored head? Self-verification alone cannot catch a fully consistent rewrite by someone with unrestricted database access. That is exactly why the chain **head** is also attested inside every signed, exported evidence pack: the auditor holds the pack, runs `verify-chain` against your live database, and compares heads. A rewrite that fools the database cannot fool the pack the auditor already has — the operator would need to forge an Ed25519 signature to keep the story consistent.

## WHO: signatures, not usernames

Two layers here.

**Evidence packs are signed.** When a governed action produces evidence, openMiura exports a self-contained `.zip` with an Ed25519 signature over a canonical signing input (report type, scope, a hash of the payload, and the signer key id). The point of the pack is that it travels: you can verify it on a clean machine with no server, no database and no network, using only the `cryptography` and `asn1crypto` libraries.

You don't have to take my word for it — the repository commits a pack produced by its reproducible simulation, so this works right now on your machine:

```bash
git clone https://github.com/fmarrabal/openmiura.git
cd openmiura && pip install openmiura
openmiura verify docs/academic/simulation/packs/evidence_pack.zip
```

A green result proves the pack is internally consistent, untampered, and signed by whoever held the embedded key. That last clause matters, so openMiura is honest about it: a green pack does **not** by itself prove *who* the signer is — the public key travels inside the pack. To close that gap, bind the pack to a signer you already trust. A trust anchor can be a PEM public key or simply the signer's 64-hex key fingerprint; the fingerprint for the committed pack is published in the captured results (`docs/academic/simulation/results/verify_summary.json` — it is the simulation's demo operator key):

```bash
openmiura verify docs/academic/simulation/packs/evidence_pack.zip \
  --trust-anchor 7573864941f89fecde124793b9164e1854582dd17a32fb05f1f715aef824455e
```

Now a pack forged with an attacker's own key reads as *non-authoritative* (a distinct exit code, 2), because the key the signature actually verified against isn't one you trust. In the captured run, the same pack checked against a deliberately foreign anchor exits 2; a pack with one byte of signed content edited fails outright with exit 1. openMiura also ships a built-in **development** signing seed for local use — and it refuses to let that fool you: it re-derives the dev key by fingerprint and marks any pack signed with it as non-authoritative, even if someone strips the flag.

**Approvals are signature-grade.** For release approvals, "any actor string is accepted" isn't good enough. openMiura's strict path (opt-in per release) resolves the actor to a registered identity, blocks the creator and submitter from approving their own release, requires an *n-of-m* quorum of **distinct** approvers, takes a **TOTP** second factor (the secret is encrypted at rest; codes are single-use), and writes an Ed25519 signature over each approval — all on the same tamper-evident chain. In the captured run, a creator's self-approval, an unregistered identity and a missing TOTP code are each rejected with HTTP 403; two distinct TOTP-authenticated approvers then meet the 2-of-m quorum, and both signatures land on the chain. It's the digital shape of a separation-of-duties control.

## WHEN: a trusted timestamp

A timestamp you write yourself proves nothing about time — you could backdate it. openMiura supports **RFC 3161**: it requests a token from a trusted Timestamping Authority (TSA) over the pack's signature and embeds it.

```bash
openmiura timestamp evidence_pack.zip --tsa-url https://freetsa.org/tsr -o stamped.zip
```

Verifying the timestamp is fully offline: openMiura checks the TSA's CMS signature and the message imprint, and reports the `genTime`. To also check the token came from an authority you trust, hand it the TSA's public certificate (FreeTSA publishes its own at `https://freetsa.org/files/tsa.crt`):

```bash
openmiura verify stamped.zip --tsa-anchor tsa.crt
```

In the captured run, the committed pack was stamped by FreeTSA and the anchored verification reports the timestamp as coming from a **trusted TSA**, `genTime` attested, exit 0. That's the last leg — **what + who + when**, all checkable without contacting openMiura or its authors.

## See it end to end

The repository ships a reproducible simulation that drives the real system — the same FastAPI app, persistence layer, policy engine and signing code that are on PyPI — through a governed policy change (blocked until a human approves), the signature-grade quorum above, and a signed evidence-pack export. It writes every verdict, exit code and transcript to `docs/academic/simulation/results/`, and the paper figures are generated from those files:

```bash
git clone https://github.com/fmarrabal/openmiura.git
cd openmiura && pip install -e .[dev]
python docs/academic/simulation/run_simulation.py
python docs/academic/simulation/verify_and_tamper.py
```

## Where this fits — and the honest limits

openMiura is aimed at environments where an auditable trail actually matters, with a focus on regulated scientific work (labs, biomedical, pharma). The repository includes control-by-control mappings to **21 CFR Part 11**, **EU GMP Annex 11**, **GAMP 5**, and **ALCOA+**, plus a consolidated traceability matrix that links each control to the executable test that evidences it — and a test that fails if any cited test disappears, so the matrix can't quietly rot.

Two things I want to be precise about, because over-claiming here is how these tools lose credibility:

1. **This is a mapping and a validation strategy, not a declaration of conformance.** Conformance is asserted by an organisation operating a validated quality system, not by a GitHub repository. openMiura gives you primitives and evidence; the qualification (IQ/OQ/PQ) of a specific deployment is the operator's responsibility.
2. **Status is `experimental`.** It works — the release is on PyPI, the simulation runs, the test suite is green across Python 3.10–3.12 — but it's early, single-node by default, and the clinical use cases in the repo describe *architecture and governance*, never patient data.

## Built in the open, with disclosure

openMiura is developed in iterative collaboration with generative AI models under continuous human review. That's stated plainly in the repo's [`AGENTS.md`](https://github.com/fmarrabal/openmiura/blob/main/AGENTS.md) — the human author retains full responsibility for correctness, security, and every claim above. It felt only right that a project about honest, auditable AI operations be honest about how it was itself built.

## Try to break it

The best thing you can do with a "tamper-evident" claim is try to tamper with it. The simulation leaves its database on disk precisely so you can:

```bash
python docs/academic/simulation/run_simulation.py
openmiura db verify-chain --config docs/academic/simulation/workspace/openmiura.yaml
# → all chains intact, exit 0
```

Now open `docs/academic/simulation/workspace/audit.db` with any SQLite tool. Try to `UPDATE` a row in `events` — the append-only trigger refuses it at the database. Then change one byte of a row in `release_approvals` (no trigger there; the chain guards it) and run `verify-chain` again — it exits 1 and names the first broken row. Do the same to a byte inside `evidence_pack.zip` and `openmiura verify` fails it. (The repo's captured run does both, plus the trigger-rejection and foreign-anchor cases, in `verify_and_tamper.py`.) If you find an edit these checks *don't* catch, that's a bug worth an issue.

- **Install:** `pip install openmiura` · **Container:** `ghcr.io/fmarrabal/openmiura`
- **Source & docs:** https://github.com/fmarrabal/openmiura

*openMiura is built and maintained by Francisco M. Arrabal Campos (Universidad de Almería). Feedback from QA/RA and lab-operations folks is especially welcome.*
