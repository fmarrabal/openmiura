# Adversarial security audit — 2026-09-19

Five independent reviewers attacked the codebase from distinct angles
(evidence cryptography, audit hash chain, authorization and approval
controls, concurrency and resource safety, operator/CLI surfaces). Each
finding below was **reproduced against a running system**, not inferred
from reading. Findings the author could not independently reproduce are
not listed.

This register exists so that nothing found is quietly lost. It is the
project's own audit trail applied to itself.

**Legend** — `FIXED`: corrected and pinned by a regression test in this
repository. `OPEN`: reproduced, not yet fixed; the reason is stated.

---

## A. Audit hash chain — integrity of the core guarantee

The three `FIXED` items below broke the chain **on an honest system, with
no attacker involved**. That is worse than a missed tamper: `verify-chain`
would report `TAMPER DETECTED` forever on a database nobody touched, which
destroys the credibility of the one control the product is built around.

| # | Severity | Status | Defect |
|---|---|---|---|
| A1 | HIGH | **FIXED** | Concurrent writers were handed the **same `chain_seq`**. `compute_chain_link` was an unsynchronised read-modify-write of the per-scope head, on a SQLite connection shared across threads (`check_same_thread=False`, no lock anywhere). 8 parallel `log_event` calls produced duplicate sequence numbers; the append-only triggers then make the duplicate unrepairable. |
| A2 | HIGH | **FIXED** | A **failed row INSERT left the head advanced**. The head was written before the caller's INSERT; when the INSERT raised (a bind or constraint error) the advance stayed in the shared connection's open transaction and was committed by the *next* writer, opening a permanent `chain_seq` gap from an ordinary application bug. |
| A3 | HIGH | **FIXED** | **Deleting every row of a scope verified clean.** The verifier derived its scope set from surviving rows only, so a scope with nothing left was never visited — while its head sat in `audit_chain_heads`, unread, contradicting it. Truncating a whole table reported `intact`, exit 0. |
| A4 | MEDIUM | **FIXED** | `events` hashed the **pre-serialization** payload while the verifier could only rebuild it by re-parsing `payload_json`. A payload with non-string keys (`{2: 'b', 10: 'a'}`) sorts numerically before the round trip and lexicographically after, so an untampered chain failed verification. |
| A5 | MEDIUM | **FIXED** | `decision_traces` filtered `chain_seq IS NOT NULL` **inside the verifier's own query**, so a row inserted with NULL chain columns was not merely unverified — it did not appear in the report at all, while the application returned it as a genuine record. |
| A6 | MEDIUM | **FIXED** | `log_decision_trace` computed `MAX(version)+1` outside any transaction. Two overlapping writes for one turn (a cancelled stream whose disconnect and completion handlers both fire) collided on the composite PK — after the loser had already advanced the chain head, triggering A2. |
| A7 | HIGH | **OPEN** | A row **INSERTed with NULL chain columns passes verification.** The append-only triggers are `BEFORE UPDATE`/`BEFORE DELETE` only — nothing guards INSERT — and unchained rows are counted as legacy "preexisting" rather than treated as tamper. After A5 such a row is at least *visible* in the report, but it does not fail the run. A real fix needs a genesis watermark per chained table (the max rowid present when the chain migration ran), so any unchained row above it is tamper. **That is a schema change — CLAUDE.md §3.3 says ask first.** |
| A8 | MEDIUM | **OPEN** | `release_approvals` has **no append-only trigger** (`_TRIGGER_TABLES` covers `events`, `tool_calls`, `decision_traces`). It is protected by the hash chain alone — which is accurate as documented in the paper §3.3 and the Part 11 mapping, and is caught by `verify-chain`, but the DB-enforced guarantee the other three have is absent on the one table holding §11.50 signature manifestations. Adding the trigger is a migration — **schema change, ask first.** |
| A9 | MEDIUM | **OPEN** | Dropping `audit_chain_heads` downgrades **TAMPER (exit 1) to "apply migrations first" (exit 3)**: the CLI's blanket `except` matches on the substring `no such table`. An attacker who defeats every head check at once is reported as a misconfiguration. |
| A10 | MEDIUM | **OPEN** | Rolling back below migration 23 and re-applying leaves an **intact chain reporting TAMPER** (heads are dropped and recreated empty). Distinguishing "head missing" from "head wrong" would fix it — but naively treating a missing head as benign would re-open A3, so this needs a deliberate design decision. |
| A11 | LOW | **OPEN** | The chain hashes a *digest* of the scope triple, and `canonical_chain_scope` collapses `None` and `''`. Flipping a scope column between the two leaves the row hash unchanged. |

**Clean under attack** (verified, not assumed): cross-table replay, moving a
row between scopes, in-place content mutation, mid-chain deletion, broken
`prev_hash`, forged `head_hash`, partial tail truncation, and the
writer/verifier field parity of `tool_calls`, `decision_traces` (22 fields)
and `release_approvals` (13 fields).

---

## B. Evidence-pack verification

| # | Severity | Status | Defect |
|---|---|---|---|
| B1 | HIGH | **FIXED** | **One space defeated the dev-seed guard.** The guard re-derives the public development key from `signer_key_id`, but used the RAW field while the signature binds the STRIPPED one. Padding it, plus deleting the two unsigned `dev_signing_key`/`signing_warning` fields, turned a pack signed with the *publicly known* dev seed into `VERIFIED`, `authoritative`, exit 0. The exception path also defaulted to "not a dev key" — fail-open on the one check that catches a worthless key; it now fails closed. |
| B2 | MEDIUM-HIGH | **FIXED** | `--allow-dev-seed` returned exit 0 **without consulting `trusted_signer`**, silently overriding an explicit, non-matching `--trust-anchor`. A CI job pinning its operator key accepted a dev-seed-signed pack. |
| B3 | HIGH | **OPEN** | **A fabricated chain of custody is accepted, including under `--strict`.** When the signed `package.json` carries no `chain_of_custody` key (reachable via `chain_of_custody_policy.include_in_artifact = False`), the verifier falls back to the *unsigned* ZIP entry, and both guards that would catch an injected sidecar no-op in that case. Each entry is validated against its own embedded integrity block with no binding to the pack signer; the legacy branch computes the "signature" as a plain digest with no key at all. Fixing this changes what "verified" means for a pack class — **needs a decision, not a patch.** |
| B4 | MEDIUM | **OPEN** | RFC 3161 `--tsa-anchor` accepts a signer certificate on a bare one-hop signature check: **no `id-kp-timeStamping` EKU check** (RFC 3161 §2.3 requires it), no CA check on the anchor, and no validity-period check against `genTime`. An operator who anchors a commercial CA accepts any leaf that CA ever issued — including a TLS server certificate, expired, over a back-dated `genTime`. |
| B5 | MEDIUM | **OPEN** | The **timestamp verdict is computed and never gated on.** A pack printing `[FAIL] rfc3161 timestamp present but INVALID` still exits 0, even under `--strict`; likewise `trusted: false` with an explicitly supplied `--tsa-anchor`. An explicitly requested check that cannot fail the run is not a check. |
| B6 | MEDIUM | **OPEN** | **Extra files can be added to a "verified" pack.** The ZIP entry set is never compared against `manifest.artifacts`, so an injected `batch_release_certificate.json` rides along with `failures=[]`, exit 0 under `--strict`. |
| B7 | MEDIUM | **OPEN** | The runtime verification API reports a **different Ed25519 fingerprint** than the pack and the offline verifier (SHA-256 of the DER SubjectPublicKeyInfo vs of the raw 32-byte key). An operator who copies the fingerprint from the API into `--trust-anchor` gets a permanent, silent false negative on every valid pack. |
| B8 | MEDIUM-LOW | **OPEN** | `provider` and `origin` are printed as fact (`provider: aws-kms-ecdsa-p256  origin: kms_file`) but live **outside the signing input**. For a reviewer this is the difference between "signed in an HSM" and "signed on a laptop". |
| B9 | LOW | **OPEN** | Duplicate ZIP entry names are tolerated silently; `manifest.json`'s own `manifest_hash` is never compared to the signed copy; a lone surrogate anywhere in the pack escapes as an uncaught `UnicodeEncodeError`, violating the documented "never raises" contract. |

**Clean under attack**: canonicalization. A 20,000-case differential fuzz
between the offline verifier and the in-process signer (nested structures,
CJK/emoji/ZWSP, `±0.0`, `1e±300`, `2**53+1`, `NaN`/`Infinity`) found zero
mismatches. Trust-anchor *resolution* is fail-closed throughout: uppercase
hex, empty values, unparseable PEM, a directory path and a typo all raise
`EXIT_USAGE` rather than silently matching or silently skipping.

---

## C. Authorization and approval controls

| # | Severity | Status | Defect |
|---|---|---|---|
| C1 | HIGH | **FIXED** | **The broker admin approve route bypassed signature-grade approval entirely.** `POST /broker/admin/releases/{id}/approve` called the legacy single-approver path unconditionally — no identity resolution, no anti-self-approval, no TOTP, no quorum counting. Reproduced: the same release that returns 403 "the creator cannot approve their own release" on the HTTP admin route returned 200 on the broker route, reaching `approved` with **zero** signature-grade votes recorded. *Fix*: signature-grade is now a property of `ReleaseService.approve_release` — it refuses outright when a quorum is configured — so the two non-HTTP callers and any future one fail closed too; the broker route additionally dispatches to the strict path so it works rather than merely failing. |
| C2 | HIGH | **PARTLY FIXED** | **Broker routes take tenant/workspace scope from the request body**, short-circuiting the validated header scope (`payload.get("tenant_id") or auth_ctx.get("tenant_id")`). Reproduced: a `workspace_admin` bound to `acme/ops` is refused `acme/research` via headers (403) and succeeds via body (200). *Fix so far*: a public `AuthService.enforce_requested_scope` plus a `resolve_request_scope` broker helper that validates a body-supplied scope against the principal's binding, applied to the release **approve** route (where the escalation was demonstrated). The idiom appears ~280 more times across the broker routes; applying the helper to the rest is mechanical but wide, and belongs in its own reviewed pass. |
| C3 | HIGH | **OPEN** | **Re-running TOTP enrolment silently disables a confirmed second factor** (`set_user_otp_secret` resets `otp_enabled=0` with no guard). Reproduced: approval without a code goes 403 → re-enroll → 200. Needs a policy decision (refuse re-enrolment vs. require an audited reset). |
| C4 | MEDIUM | **OPEN** | **Anti-self-approval is defeated by a creator handle that does not resolve.** `_canonical_identity` falls back to the raw string on a lookup miss, and `created_by` is never validated at write time, so `Alice` or `alice@ual.es` as creator compares unequal to approver `user:alice`. The earlier canonicalization fix only covered the case where *both* sides resolve. A real fix stores a canonical `creator_user_key` at create time and treats an unresolvable handle as "cannot prove distinct". |
| C5 | MEDIUM | **OPEN** | `cast_release_approval_vote` accepts an `auth_ctx` parameter and **never reads it**; the signer is derived entirely from the caller-asserted `actor` string. This is the enabler under C1, C2 and C4. |
| C6 | LOW | **OPEN** | `distinct_required` is stored, returned by the API and read by nothing. `set_release_quorum` is an unguarded DELETE+INSERT, so the quorum can be relaxed *after* votes are cast (reproduced: 1-of-3 pending → rewrite to 1-of-1 self-allowed → creator approves). |

**Clean under attack**: TOTP single-use replay (atomic `INSERT OR IGNORE`
on a UNIQUE key), the ±1-step skew window, fail-closed behaviour when
`OPENMIURA_OTP_KEK` is absent, quorum distinctness for one account (case,
whitespace and Cyrillic-homoglyph variants are all rejected as unknown
approvers), admin-token gating (`secrets.compare_digest`, no dev bypass),
and the persistence-layer scope helpers — an AST scan found no repository
read path missing its scope predicate. **The scope leak is at the route
layer, not the repository layer.**

---

## D. Concurrency and resource safety

| # | Severity | Status | Defect |
|---|---|---|---|
| D1 | HIGH | **FIXED** | See A1/A2/A6 — the audit-integrity half of this class. |
| D2 | MEDIUM-HIGH | **OPEN** | **One `sqlite3` connection is shared by every thread** with `check_same_thread=False` and nothing replacing the safety it removes. Beyond the chain (now serialised), any multi-statement operation can be split by another thread's `commit()`. The sharpest case: `set_release_quorum`'s DELETE+INSERT — if the INSERT fails after another thread commits, a release's multi-approver quorum silently vanishes and the release drops to single-approver approval. Proper fix: per-thread connections or a pool. |
| D3 | MEDIUM | **OPEN** | The `run_in_threadpool` refactor **skipped the entire broker router** (99 `async def` handlers, 0 uses), including handlers that call `urllib.request.urlopen(timeout=15)` and `time.sleep` on the event loop. One unreachable external runtime freezes every request in the process. `stream_message_native` likewise runs the whole audit path on the loop. |
| D4 | MEDIUM | **OPEN** | Quorum approval is a TOCTOU: the **double-vote guard** is read, decided and written without a transaction, so one signer firing two concurrent approvals records two signed §11.50 manifestations for a single act of approval. |
| D5 | LOW | **OPEN** | Unbounded per-request daemon threads in `broker/routes/chat.py`; connection leaks on the backup/restore error paths; unlocked appends to the uploads index; ~200 admin endpoints whose audit-write failures are swallowed with no counter, so a dropped audit record is invisible. |

---

## E. Operator and CLI surfaces

| # | Severity | Status | Defect |
|---|---|---|---|
| E1 | HIGH | **OPEN** | **`db rollback` permanently deletes chained audit rows.** Migration 25's down-migration rebuilds `decision_traces` keeping only `MAX(version)` per trace — and migration 26's down drops the append-only trigger first, so openMiura's own command bypasses the guarantee. Re-applying forward then reports `TAMPER DETECTED`. |
| E2 | HIGH | **OPEN** | **`db restore` from a zero-length backup wipes the database and reports `ok: true`.** An empty file is a valid empty SQLite DB, so `.backup()` succeeds and blanks the target. (A non-SQLite source correctly fails before touching the destination.) |
| E3 | HIGH | **OPEN** | **`db backup` from the wrong working directory silently backs up an empty database** and reports success: `db_path` is resolved against the cwd, and `DBConnection` creates a fresh empty DB rather than failing. A nightly cron produces a directory of 4 KB "backups" — which then feeds E2. |
| E4 | MEDIUM | **OPEN** | **Every CLI usage error is a Python traceback, exit 1** — including bare `openmiura`, an unknown command, a missing required option, and a missing config file. This is the first thing a user runs after `pip install openmiura`. The documented `EXIT_USAGE=3` contract is honoured only for some paths. |
| E5 | MEDIUM | **OPEN** | `openmiura db check` / `db clean` **fail in every wheel install** (`from scripts.check_db import ...`; `scripts/` is not packaged). They work from a git checkout only, which is why the test suite never caught it. `db check` also returns `ok: true`, exit 0, with every table missing. |
| E6 | MEDIUM | **OPEN** | **`openmiura doctor` silently re-applies migrations** to the database it inspects (Gateway `auto_migrate` defaults on), so the documented rollback → doctor flow undoes the rollback. In a GxP deployment an unlogged schema change from a diagnostic is a change-control problem. |
| E7 | MEDIUM | **OPEN** | `db rollback --to-version -5` is clamped to 0 and **tears the schema down to nothing** — migration 1's down drops `events`, `sessions`, `tool_calls`, `memory_items` — from a single sign typo, with no confirmation. Rolling back below 23 also leaves the running binary unable to log any audit event, with no warning. |
| E8 | LOW | **OPEN** | `db restore` clobbers a live DB with no confirmation and no safety copy; `rolled_back` lists migrations that were not actually reversed; registry error paths traceback; `db version` creates the database it reports on; `sdk quickstart` prints an 8-step flow whose step 8 fails (a missing `registry approve`). |
| E9 | MEDIUM | **OPEN** | **Evaluation run comparison is non-deterministic.** `list_evaluation_runs` orders by `started_at DESC` with no tiebreaker, and `time.time()` has ~15 ms resolution on Windows, so two runs recorded in the same tick order arbitrarily — which run counts as "latest" then flips between executions. Surfaced as a flaky test: `test_admin_evaluation_leaderboard_and_comparison` and `test_admin_evaluation_compare_regressions_and_scorecards` fail intermittently. **Verified pre-existing** — reproduced on pristine `origin/main` (2 failures in 3 runs) with none of this pass's changes applied. Fix: add a monotonic tiebreaker (`ORDER BY started_at DESC, id DESC`). |

**Clean under attack**: the SQLite backup/restore happy path (rows,
triggers, heads and `verify-chain` all survive a round trip), the
`verify`/`timestamp` exit-code contract, `doctor` failing closed on a
malformed config or a missing driver, and — checked command by command —
every `openmiura verify` invocation printed in the README and in
`docs/media/medium_verifiable_governance.md`.

---

## What was fixed here, and why only that

This pass fixes **A1–A6, B1, B2, C1** and the demonstrated half of **C2**:
the defects that corrupt the audit chain during ordinary honest operation,
the two that let a pack signed with a publicly-known key read as
authoritative, and the live authorization bypass. Each is pinned by a
regression test that fails on the previous code.

Everything else is left open on purpose. The remainder falls into three
groups, none of which should be rushed into the same change:

1. **Schema/migration changes** (A7, A8) — CLAUDE.md §3.3 requires asking
   before a DB-schema change.
2. **Semantics decisions** (B3, B4, B5, B6, A10) — these change what
   `verify` accepts, so they need a deliberate call about existing packs
   and a matching update to the paper §3.3 and the Part 11 mapping.
3. **Wide but mechanical route work** (the rest of C2, C3–C6, D2–D5) —
   ~280 more body-scope sites now have a helper to adopt; `cast_release_approval_vote`
   still ignores its `auth_ctx`; TOTP re-enrolment still silently clears a
   confirmed factor.

Recommended order from here: **E1–E3** (an operator can destroy the audit
trail with a documented command, and `db backup` can silently produce empty
backups that then feed a destructive restore), then **C3/C4** (the TOTP
re-enrolment downgrade and the anti-self-approval fallback), then the rest
of C2, then the B-group semantics.
