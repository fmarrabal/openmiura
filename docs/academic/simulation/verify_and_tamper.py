"""Verification-chain and tamper-evidence demonstration for the paper.

Runs the auditor-facing side of openMiura against the artifacts produced by
``run_simulation.py``:

  1. ``openmiura db verify-chain`` on the live DB — every chain intact.
  2. ``openmiura verify`` on the exported pack — VERIFIED + authoritative.
  3. ``--trust-anchor`` with the real signer fingerprint — authoritative;
     with a foreign fingerprint — NON-AUTHORITATIVE (distinct exit code).
  4. A tampered pack (one byte of signed content changed) — FAILS.
  5. Append-only enforcement: a plain ``UPDATE`` on an audit row is rejected
     by a database trigger.
  6. Attacker bypass: even after dropping the trigger and editing a row
     directly, ``verify-chain`` detects the break (hash mismatch).
  7. RFC 3161: attempt a trusted timestamp over the pack signature against a
     public TSA (network-gated; the outcome is recorded either way).

Every exit code and JSON verdict is captured under results/.

Run (after run_simulation.py):
    python docs/academic/simulation/verify_and_tamper.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESULTS = HERE / "results"
PACKS = HERE / "packs"
WORKSPACE = HERE / "workspace"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CFG = WORKSPACE / "openmiura.yaml"
CFG_TAMPERED = WORKSPACE / "openmiura_tampered.yaml"
PACK = PACKS / "evidence_pack.zip"
PACK_TAMPERED = PACKS / "evidence_pack_tampered.zip"

_TRANSCRIPT: list[str] = []
_RESULTS: dict[str, Any] = {}


def log(line: str = "") -> None:
    print(line)
    _TRANSCRIPT.append(line)


def run_cli(argv: list[str]) -> tuple[int, str]:
    """Invoke the real console entry point, capturing stdout and exit code."""
    from openmiura.cli import main

    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            code = int(main(argv))
        except SystemExit as exc:  # click may raise SystemExit
            code = int(exc.code or 0)
    text = buf.getvalue()
    return code, text


def show(title: str, argv: list[str]) -> tuple[int, str]:
    log("-" * 72)
    log(f"$ openmiura {' '.join(argv)}")
    code, text = run_cli(argv)
    for ln in text.rstrip("\n").splitlines():
        log("  " + ln)
    log(f"  -> exit {code}")
    log("")
    return code, text


# ---------------------------------------------------------------------------
def _entry(pack_bytes: bytes, name: str) -> dict:
    with zipfile.ZipFile(io.BytesIO(pack_bytes), "r") as zf:
        return json.loads(zf.read(name).decode("utf-8"))


def _rezip(original: bytes, overrides: dict[str, object]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original), "r") as zin:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in zin.namelist():
                if name in overrides:
                    zout.writestr(name, json.dumps(overrides[name], ensure_ascii=False, sort_keys=True, indent=2))
                else:
                    zout.writestr(name, zin.read(name))
    return out.getvalue()


def build_tampered_pack() -> None:
    data = PACK.read_bytes()
    pkg = _entry(data, "package.json")
    pkg["generated_by"] = "attacker"  # mutate signed content without re-signing
    PACK_TAMPERED.write_bytes(_rezip(data, {"package.json": pkg}))


def write_tampered_config() -> None:
    text = CFG.read_text(encoding="utf-8")
    text = text.replace("audit.db", "audit_tampered.db")
    CFG_TAMPERED.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
def demo_verify_chain_intact() -> None:
    log("=" * 72)
    log("1) Audit hash-chain — live DB is intact")
    log("=" * 72)
    code, text = show("db verify-chain (intact)", ["db", "verify-chain", "--config", str(CFG)])
    jcode, jtext = run_cli(["db", "verify-chain", "--config", str(CFG), "--json"])
    payload = json.loads(jtext)
    (RESULTS / "verify_chain_intact.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _RESULTS["verify_chain_intact"] = {"exit": code, "any_tamper": payload["any_tamper"]}


def demo_pack_verify() -> None:
    log("=" * 72)
    log("2) Evidence pack — offline verification (WHAT + WHO)")
    log("=" * 72)
    code, text = show("verify <pack>", ["verify", str(PACK)])
    jcode, jtext = run_cli(["verify", str(PACK), "--json"])
    payload = json.loads(jtext)
    (RESULTS / "verify_pack_authoritative.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    fpr = payload.get("signer_fingerprint") or payload.get("public_key_fingerprint")
    if not fpr:
        # fall back to parsing the human line
        for ln in text.splitlines():
            if "fingerprint" in ln.lower():
                fpr = ln.split(":")[-1].strip()
                break
    _RESULTS["verify_pack_no_anchor"] = {"exit": code, "verdict": payload.get("verdict"),
                                         "authoritative": payload.get("authoritative"),
                                         "signature_scheme": payload.get("signature_scheme"),
                                         "fingerprint": fpr}
    return fpr


def demo_trust_anchor(fpr: str) -> None:
    log("=" * 72)
    log("3) Trust anchor — bind the pack to a known signer (WHO)")
    log("=" * 72)
    # Correct anchor: authoritative.
    code_ok, _ = show("verify --trust-anchor <real fingerprint>",
                      ["verify", str(PACK), "--trust-anchor", fpr])
    # Foreign anchor: a different, syntactically valid ed25519 fingerprint.
    wrong = ("00" * 32)
    if wrong == fpr:
        wrong = ("11" * 32)
    code_wrong, _ = show("verify --trust-anchor <foreign fingerprint>",
                         ["verify", str(PACK), "--trust-anchor", wrong])
    _RESULTS["trust_anchor"] = {
        "real_anchor_exit": code_ok, "real_anchor_authoritative": code_ok == 0,
        "foreign_anchor_exit": code_wrong, "foreign_anchor_authoritative": code_wrong == 0,
        "foreign_fingerprint": wrong,
    }


def demo_tampered_pack() -> None:
    log("=" * 72)
    log("4) Tampered pack — one byte of signed content changed")
    log("=" * 72)
    build_tampered_pack()
    code, text = show("verify <tampered pack>", ["verify", str(PACK_TAMPERED)])
    jcode, jtext = run_cli(["verify", str(PACK_TAMPERED), "--json"])
    payload = json.loads(jtext)
    (RESULTS / "verify_pack_tampered.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _RESULTS["verify_pack_tampered"] = {"exit": code, "verdict": payload.get("verdict"),
                                        "failures": payload.get("failures")}


def _triggers_on(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)
    ).fetchall()
    return [r[0] for r in rows]


def demo_db_tamper() -> None:
    log("=" * 72)
    log("5-6) Two-layer tamper-evidence")
    log("=" * 72)
    log("  Layer 1 — append-only DB triggers on the operational audit tables")
    log("            (events, tool_calls, decision_traces): a plain UPDATE is")
    log("            rejected at the database.")
    log("  Layer 2 — the per-scope hash chain covers ALL chained tables,")
    log("            including release_approvals (which is chain-protected, not")
    log("            trigger-protected): a direct edit is caught by verify-chain.")
    log("")
    # Work on a copy so the intact DB stays reproducible.
    src = WORKSPACE / "audit.db"
    dst = WORKSPACE / "audit_tampered.db"
    shutil.copy2(src, dst)
    write_tampered_config()

    conn = sqlite3.connect(str(dst))

    # (5) Layer 1: a plain UPDATE on a trigger-protected table is rejected.
    trg_table = "events"
    triggers_here = _triggers_on(conn, trg_table)
    ev = conn.execute(f"SELECT rowid FROM {trg_table} ORDER BY chain_seq LIMIT 1").fetchone()
    trigger_rejected = None
    trigger_error = ""
    try:
        conn.execute(f"UPDATE {trg_table} SET payload_json='{{\"forged\":true}}' WHERE rowid=?", (ev[0],))
        conn.commit()
        trigger_rejected = False
    except Exception as exc:  # RAISE(ABORT,…) from the append-only trigger
        conn.rollback()
        trigger_rejected = True
        trigger_error = str(exc)
    log(f"  Layer 1: {trg_table} has triggers {triggers_here}")
    log(f"  [{'REJECTED' if trigger_rejected else 'ALLOWED'}] plain UPDATE on {trg_table}: {trigger_error or 'no error'}")
    log("")

    # (6) Layer 2: release_approvals has NO trigger — a direct edit succeeds at
    # the SQL level, but the hash chain makes it detectable.
    sig_table = "release_approvals"
    triggers_sig = _triggers_on(conn, sig_table)
    row = conn.execute(
        f"SELECT rowid, actor, reason, chain_seq FROM {sig_table} "
        f"WHERE signature IS NOT NULL ORDER BY chain_seq LIMIT 1"
    ).fetchone()
    log(f"  Layer 2: {sig_table} has triggers {triggers_sig or '[]'} (chain-protected)")
    log(f"  target signed approval: rowid={row[0]} actor={row[1]!r} chain_seq={row[3]}")
    conn.execute(f"UPDATE {sig_table} SET reason='forged-by-operator' WHERE rowid=?", (row[0],))
    conn.commit()
    conn.close()
    log(f"  attacker force-updated the signed approval (row_hash left stale)")
    log("")

    code, text = show("db verify-chain (tampered DB)", ["db", "verify-chain", "--config", str(CFG_TAMPERED)])
    jcode, jtext = run_cli(["db", "verify-chain", "--config", str(CFG_TAMPERED), "--json"])
    payload = json.loads(jtext)
    (RESULTS / "verify_chain_tampered.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _RESULTS["db_tamper"] = {
        "layer1_trigger_table": trg_table,
        "layer1_triggers": triggers_here,
        "layer1_plain_update_rejected": trigger_rejected,
        "layer1_trigger_error": trigger_error,
        "layer2_table": sig_table,
        "layer2_triggers": triggers_sig,
        "layer2_edited_actor": row[1],
        "verify_chain_exit": code,
        "any_tamper_detected": payload["any_tamper"],
    }


def demo_rfc3161() -> None:
    log("=" * 72)
    log("7) RFC 3161 trusted timestamp (WHEN) — network-gated")
    log("=" * 72)
    stamped = PACKS / "evidence_pack_stamped.zip"
    tsa_url = os.environ.get("OPENMIURA_SIM_TSA_URL", "https://freetsa.org/tsr")
    code, text = show(f"timestamp --tsa-url {tsa_url}",
                      ["timestamp", str(PACK), "--tsa-url", tsa_url, "-o", str(stamped)])
    outcome: dict[str, Any] = {"tsa_url": tsa_url, "timestamp_exit": code, "stamped": stamped.exists()}
    if code == 0 and stamped.exists():
        vcode, vtext = show("verify <stamped pack>", ["verify", str(stamped)])
        outcome["verify_stamped_exit"] = vcode
        for ln in vtext.splitlines():
            if "rfc3161 timestamp" in ln.lower():
                outcome["rfc3161_line"] = ln.strip()
                if "genTime=" in ln:
                    outcome["gen_time"] = ln.split("genTime=", 1)[1].split(" ", 1)[0]
                if "Common Name:" in ln:
                    outcome["tsa_common_name"] = ln.split("Common Name:", 1)[1].split(",", 1)[0].strip()
                break
        # Structured re-read for the figure.
        _, jt = run_cli(["verify", str(stamped), "--json"])
        try:
            js = json.loads(jt)
            (RESULTS / "verify_pack_stamped.json").write_text(json.dumps(js, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            pass
    else:
        log("  RFC 3161 timestamping did not complete (no network access to a public TSA).")
        log("  The offline verification path is exercised by tests/test_rfc3161_*.py and")
        log("  tests/test_cli_verify_timestamp.py; `openmiura verify --tsa-anchor` checks a")
        log("  token's CMS signature and message imprint with no network at verify time.")
    _RESULTS["rfc3161"] = outcome
    log("")


def main() -> int:
    demo_verify_chain_intact()
    fpr = demo_pack_verify()
    if fpr:
        demo_trust_anchor(fpr)
    demo_tampered_pack()
    demo_db_tamper()
    demo_rfc3161()

    (RESULTS / "verify_summary.json").write_text(
        json.dumps(_RESULTS, indent=2, sort_keys=True), encoding="utf-8"
    )
    (RESULTS / "verify_transcript.txt").write_text("\n".join(_TRANSCRIPT) + "\n", encoding="utf-8")
    log("Verification + tamper demonstration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
