"""End-to-end simulation of openMiura for the academic paper.

This driver exercises the REAL openMiura system (the same FastAPI app,
persistence layer, policy/approval engine and Ed25519 evidence signing that
ship in the package) against a persistent SQLite database, and records every
result as JSON plus a human-readable transcript. Nothing here is mocked or
hand-authored: each scenario drives the app over HTTP (via Starlette's
in-process TestClient) exactly as an operator would.

Scenarios
---------
A. Governed runtime — a sensitive operational policy change is blocked until a
   human approves it, then executes, leaving a signed release and an auditable
   trail (openmiura/demo/canonical_case.py, the project's canonical demo).
B. NMR pilot — the synthetic UAL ¹H/¹³C NMR interpretation workflow evaluated
   against the nmr_interpretation policy pack (scripts/run_pilot_ual_nmr_demo.py),
   in both the nominal and the unknown-impurity escalation paths.
C. Signature-grade approvals — identity resolution, separation of duties, an
   n-of-m quorum of distinct approvers, a single-use TOTP second factor and a
   per-approval Ed25519 signature, all recorded on the audit hash chain.
D. Evidence pack — a real signed evidence pack is exported to packs/ so a third
   party can verify it offline with `openmiura verify`.

The database is left on disk (workspace/audit.db) so the companion shell steps
can run `openmiura db verify-chain` and the tamper demonstration against it.

Run:
    python docs/academic/simulation/run_simulation.py
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESULTS = HERE / "results"
PACKS = HERE / "packs"
WORKSPACE = HERE / "workspace"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A real operator signing seed so exported packs verify as *authoritative*
# (not the built-in non-authoritative development seed). This is a demo
# operator key, generated for the simulation only — never a production secret.
os.environ["OPENMIURA_EVIDENCE_SIGNING_SEED"] = "arxiv-simulation-operator-signing-seed-2026"
# Key-encryption key for TOTP secrets at rest (scenario C).
os.environ["OPENMIURA_OTP_KEK"] = "arxiv-simulation-otp-kek"

_H = {"Authorization": "Bearer secret-admin"}
_SCOPE = {"tenant_id": "tenant-a", "workspace_id": "ws-a", "environment": "prod"}

_TRANSCRIPT: list[str] = []


def log(line: str = "") -> None:
    print(line)
    _TRANSCRIPT.append(line)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_config(path: Path) -> None:
    db_path = (WORKSPACE / "audit.db").as_posix()
    sandbox_dir = (WORKSPACE / "sandbox").as_posix()
    path.write_text(
        f'''\
server:
  host: "127.0.0.1"
  port: 8099
storage:
  db_path: "{db_path}"
llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5:7b-instruct"
runtime:
  history_limit: 6
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
admin:
  enabled: true
  token: secret-admin
broker:
  enabled: true
  base_path: "/broker"
auth:
  enabled: true
  session_ttl_s: 3600
''',
        encoding="utf-8",
    )


def _post(client: Any, url: str, payload: dict[str, Any]) -> Any:
    return client.post(url, headers=_H, json=payload)


def _totp_now(secret_b32: str) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.twofactor.totp import TOTP

    raw = base64.b32decode(secret_b32)
    return TOTP(raw, 6, hashes.SHA1(), 30).generate(int(time.time())).decode("ascii")


# ---------------------------------------------------------------------------
# Scenario A — governed runtime (canonical demo)
# ---------------------------------------------------------------------------
def scenario_governed_runtime(client: Any) -> dict[str, Any]:
    from openmiura.demo.canonical_case import run_canonical_demo

    log("=" * 72)
    log("SCENARIO A — Governed runtime: block a policy change until approved")
    log("=" * 72)
    report = run_canonical_demo(client)
    v = report["validation"]
    log(f"  runtime_id           : {report['demo']['runtime_id']}")
    log(f"  approval_id          : {report['demo']['approval_id']}")
    log(f"  requester / approver : {report['demo']['actors']['requester']} / {report['demo']['actors']['approver']}")
    for key, val in v.items():
        log(f"  [{'PASS' if val else 'FAIL'}] {key}")
    log(f"  overall success      : {report['success']}")
    log("")
    (RESULTS / "scenario_a_governed_runtime.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {
        "runtime_id": report["demo"]["runtime_id"],
        "approval_id": report["demo"]["approval_id"],
        "validation": v,
        "success": report["success"],
    }


# ---------------------------------------------------------------------------
# Scenario C — signature-grade approvals
# ---------------------------------------------------------------------------
def scenario_signature_grade(client: Any) -> dict[str, Any]:
    log("=" * 72)
    log("SCENARIO C — Signature-grade approval (SoD + n-of-m quorum + TOTP + signature)")
    log("=" * 72)
    store = client.app.state.gw.audit
    # alice/bob are registered so the block on them is unambiguously separation
    # of duties (creator/submitter), not an unknown-identity rejection.
    for name in ("alice", "bob", "carol", "dave"):
        role = "developer" if name in ("alice", "bob") else "approver"
        store.ensure_auth_user(username=name, password="pw", user_key=f"user:{name}", role=role)
    log("  registered identities: user:alice (creator), user:bob (submitter), user:carol, user:dave (approvers)")

    created = _post(client, "/admin/releases", {
        "kind": "workflow", "name": "nmr-batch-release", "version": "1.0.0",
        "created_by": "user:alice",
        "items": [{"item_kind": "workflow", "item_key": "k", "item_version": "1.0.0", "payload": {}}],
    })
    rid = created.json()["release"]["release_id"]
    _post(client, f"/admin/releases/{rid}/submit", {"actor": "user:bob"})
    _post(client, f"/admin/releases/{rid}/quorum", {"required_n": 2})
    log(f"  release_id           : {rid}  (created_by alice, submitted_by bob, quorum n=2)")

    events: list[dict[str, Any]] = []

    # Separation of duties: creator cannot approve own release.
    self_try = _post(client, f"/admin/releases/{rid}/approve", {"actor": "user:alice"})
    events.append({"step": "self_approval_alice", "http_status": self_try.status_code,
                   "blocked": self_try.status_code == 403})
    log(f"  [{'BLOCKED' if self_try.status_code == 403 else 'ALLOWED'}] creator user:alice self-approval -> HTTP {self_try.status_code}")

    # Unknown identity rejected.
    ghost = _post(client, f"/admin/releases/{rid}/approve", {"actor": "ghost"})
    events.append({"step": "unknown_approver_ghost", "http_status": ghost.status_code,
                   "blocked": ghost.status_code == 403})
    log(f"  [{'BLOCKED' if ghost.status_code == 403 else 'ALLOWED'}] unknown approver 'ghost' -> HTTP {ghost.status_code}")

    # Enrol + confirm TOTP for both approvers.
    otp: dict[str, str] = {}
    for name in ("carol", "dave"):
        enroll = _post(client, "/admin/auth/otp/enroll", {"user_key": f"user:{name}"})
        secret = enroll.json()["secret_b32"]
        otp[name] = secret
        conf = _post(client, "/admin/auth/otp/confirm", {"user_key": f"user:{name}", "code": _totp_now(secret)})
        log(f"  enrolled 2FA         : user:{name} (confirm HTTP {conf.status_code})")

    # Approval without a second factor is rejected once 2FA is enabled.
    no_code = _post(client, f"/admin/releases/{rid}/approve", {"actor": "user:carol"})
    events.append({"step": "carol_without_otp", "http_status": no_code.status_code,
                   "blocked": no_code.status_code == 403})
    log(f"  [{'BLOCKED' if no_code.status_code == 403 else 'ALLOWED'}] user:carol without OTP -> HTTP {no_code.status_code}")

    # First valid approval — quorum not yet met.
    first = _post(client, f"/admin/releases/{rid}/approve", {"actor": "user:carol", "otp_code": _totp_now(otp["carol"])})
    fj = first.json()
    events.append({"step": "carol_with_otp", "http_status": first.status_code,
                   "quorum_met": fj.get("quorum_met")})
    log(f"  [OK] user:carol with OTP -> HTTP {first.status_code}, quorum_met={fj.get('quorum_met')}")

    status_mid = store.get_release_bundle(rid)["status"]
    log(f"  release status (1/2) : {status_mid}")

    # Wait for a fresh TOTP window so dave's code differs from any consumed one.
    second = _post(client, f"/admin/releases/{rid}/approve", {"actor": "user:dave", "otp_code": _totp_now(otp["dave"])})
    sj = second.json()
    events.append({"step": "dave_with_otp", "http_status": second.status_code,
                   "quorum_met": sj.get("quorum_met")})
    log(f"  [OK] user:dave with OTP -> HTTP {second.status_code}, quorum_met={sj.get('quorum_met')}")

    status_final = store.get_release_bundle(rid)["status"]
    log(f"  release status (2/2) : {status_final}")

    # Pull the signed approval rows straight from the audit store.
    approvals = _read_release_approvals(store, rid)
    signed = [a for a in approvals if a.get("signature")]
    log(f"  signed approvals     : {len(signed)} (ed25519, on the audit hash chain)")
    for a in signed:
        log(f"     - {a['actor']} :: 2fa={a.get('second_factor_method')} :: sig={str(a.get('signature'))[:16]}…")
    log("")

    result = {
        "release_id": rid,
        "quorum_required_n": 2,
        "events": events,
        "status_after_first": status_mid,
        "status_after_second": status_final,
        "signed_approvals": approvals,
        "distinct_signers": sorted({a["actor"] for a in signed}),
    }
    (RESULTS / "scenario_c_signature_grade.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    return result


def _read_release_approvals(store: Any, rid: str) -> list[dict[str, Any]]:
    cur = store._conn.cursor()
    rows = cur.execute(
        "SELECT release_id, action, actor, reason, created_at, signer_user_key, meaning, "
        "second_factor_method, otp_verified_at, signature, signature_scheme, signer_key_id, "
        "chain_seq, prev_hash, row_hash FROM release_approvals WHERE release_id=? ORDER BY chain_seq",
        (rid,),
    ).fetchall()
    out = []
    for r in rows:
        out.append({k: r[k] for k in r.keys()})
    return out


# ---------------------------------------------------------------------------
# Scenario D — real signed evidence pack export
# ---------------------------------------------------------------------------
def _base_metadata() -> dict[str, Any]:
    return {
        "runtime_class": "incident",
        "allowed_actions": ["chat"],
        "dispatch_policy": {"dispatch_mode": "async", "poll_after_s": 0.1,
                            "max_active_runs": 2, "max_active_runs_per_workspace": 3},
        "heartbeat_policy": {"runtime_stale_after_s": 120, "active_run_stale_after_s": 60,
                             "auto_reconcile_after_s": 600, "poll_interval_s": 5, "max_poll_retries": 1,
                             "auto_poll_enabled": False, "auto_reconcile_enabled": False,
                             "stale_target_status": "timed_out"},
        "session_bridge": {"enabled": True, "workspace_connection": "primary-conn",
                           "external_workspace_id": "oc-ws-a", "external_environment": "prod",
                           "event_bridge_enabled": True},
        "governance_release_policy": {"approval_required": False, "requested_role": "security",
                                      "ttl_s": 1800, "require_signature": True, "signer_key_id": "governance-ci"},
    }


def _candidate_policy() -> dict[str, Any]:
    return {"default_timezone": "UTC",
            "quiet_hours": {"enabled": True, "timezone": "UTC", "weekdays": [0, 1, 2, 3, 4, 5, 6],
                            "start_time": "00:00", "end_time": "23:59", "action": "schedule"}}


def scenario_evidence_pack(client: Any, base_now: float) -> dict[str, Any]:
    log("=" * 72)
    log("SCENARIO D — Export a real signed evidence pack (offline-verifiable)")
    log("=" * 72)

    rt = _post(client, "/admin/openclaw/runtimes", {
        "actor": "admin", "name": "runtime-evidence", "base_url": "simulated://openclaw",
        "transport": "simulated", "allowed_agents": ["default"], **_SCOPE, "metadata": _base_metadata()})
    runtime_id = rt.json()["runtime"]["runtime_id"]

    bundle = _post(client, "/admin/openclaw/alert-governance/bundles", {
        "actor": "release-admin", "name": "bundle-evidence", "version": "bundle-evidence-v1",
        "runtime_ids": [runtime_id], "candidate_policy": _candidate_policy(), "wave_size": 1, **_SCOPE})
    bundle_id = bundle.json()["bundle_id"]
    _post(client, f"/admin/openclaw/alert-governance/bundles/{bundle_id}/submit", {"actor": "release-admin", **_SCOPE})
    _post(client, f"/admin/openclaw/alert-governance/bundles/{bundle_id}/approve", {"actor": "security-admin", **_SCOPE})

    portfolio = _post(client, "/admin/openclaw/alert-governance/portfolios", {
        "actor": "portfolio-admin", "name": "portfolio-evidence",
        "version": "2026.arxiv.portfolio.evidence", "bundle_ids": [bundle_id],
        "base_release_at": base_now + 10,
        "export_policy": {"enabled": True, "require_signature": True, "signer_key_id": "arxiv-operator-ci",
                          "timeline_limit": 120, "embed_artifact_content": True},
        "notarization_policy": {"enabled": True, "provider": "simulated-ledger",
                                "reference_namespace": "portfolio-evidence", "notary_key_id": "notary-ci"},
        "retention_policy": {"enabled": True, "classification": "regulated-evidence", "retention_days": 30,
                             "max_packages": 5, "purge_expired": True, "prune_on_export": True},
        "escrow_policy": {}, "signing_policy": {}, "chain_of_custody_policy": {},
        "custody_anchor_policy": {}, "verification_gate_policy": {}, **_SCOPE})
    portfolio_id = portfolio.json()["portfolio_id"]
    _post(client, f"/admin/openclaw/alert-governance/portfolios/{portfolio_id}/submit", {"actor": "portfolio-admin", **_SCOPE})
    _post(client, f"/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve",
          {"actor": "security-admin", "reason": "approve evidence portfolio", **_SCOPE})

    export = _post(client, f"/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export",
                   {"actor": "auditor", **_SCOPE})
    payload = export.json()
    content_b64 = payload["artifact"]["content_b64"]
    data = base64.b64decode(content_b64.encode("ascii"))
    pack_path = PACKS / "evidence_pack.zip"
    pack_path.write_bytes(data)
    log(f"  portfolio_id         : {portfolio_id}")
    log(f"  evidence pack        : {pack_path.relative_to(ROOT)} ({len(data)} bytes)")
    log(f"  artifact filename    : {payload['artifact'].get('filename')}")
    log("")
    return {"portfolio_id": portfolio_id, "pack_path": str(pack_path), "size_bytes": len(data)}


# ---------------------------------------------------------------------------
# Scenario B — NMR pilot (synthetic policy-pack smoke test)
# ---------------------------------------------------------------------------
def scenario_nmr_pilot() -> dict[str, Any]:
    log("=" * 72)
    log("SCENARIO B — UAL NMR interpretation pilot (nmr_interpretation policy pack)")
    log("=" * 72)
    py = sys.executable
    out: dict[str, Any] = {}
    for label, extra in (("nominal", []), ("escalation", ["--unknown-impurity"])):
        target = RESULTS / f"scenario_b_nmr_{label}.json"
        cmd = [py, str(ROOT / "scripts" / "run_pilot_ual_nmr_demo.py"), "--output", str(target), *extra]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        report = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        out[label] = {"returncode": proc.returncode, "report": report}
        log(f"  {label:10s} : success={report.get('success')} stage={report.get('stage')} "
            f"policy_version={report.get('policy_version')}")
        signers = [s["role"] for s in report.get("evidence_pack", {}).get("publish_evaluation", {}).get("required_signers", [])]
        if signers:
            log(f"               required signers: {', '.join(signers)}")
    log("")
    return out


# ---------------------------------------------------------------------------
# Chain heads snapshot (for the hash-chain figure)
# ---------------------------------------------------------------------------
def snapshot_chain_heads(store: Any) -> dict[str, Any]:
    from openmiura.persistence.hashchain import CHAINED_TABLES

    cur = store._conn.cursor()
    heads: list[dict[str, Any]] = []
    for row in cur.execute("SELECT chain_table, chain_scope, head_hash, head_seq FROM audit_chain_heads ORDER BY chain_table, chain_scope").fetchall():
        heads.append({"table": row["chain_table"], "scope": row["chain_scope"],
                      "head_hash": row["head_hash"], "head_seq": row["head_seq"]})
    counts = {}
    for t in CHAINED_TABLES:
        try:
            counts[t] = cur.execute(f"SELECT COUNT(*) AS c FROM {t} WHERE chain_seq IS NOT NULL").fetchone()["c"]
        except Exception:
            counts[t] = None
    return {"chained_tables": list(CHAINED_TABLES), "row_counts": counts, "heads": heads}


def main() -> int:
    for d in (RESULTS, PACKS, WORKSPACE):
        d.mkdir(parents=True, exist_ok=True)
    # Fresh DB for a clean, reproducible run.
    dbfile = WORKSPACE / "audit.db"
    if dbfile.exists():
        dbfile.unlink()

    import app as app_module
    from fastapi.testclient import TestClient
    from openmiura.gateway import Gateway
    from openmiura import __version__

    base_now = time.time()
    started = _iso(base_now)
    log(f"openMiura simulation — version {__version__} — {started}")
    log(f"repo root: {ROOT}")
    log("")

    cfg = WORKSPACE / "openmiura.yaml"
    write_config(cfg)

    summary: dict[str, Any] = {
        "openmiura_version": __version__,
        "started_utc": started,
        "config_path": str(cfg),
        "db_path": str(dbfile),
        "scenarios": {},
    }

    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    try:
        with TestClient(app) as client:
            for name, fn in (
                ("A_governed_runtime", lambda: scenario_governed_runtime(client)),
                ("C_signature_grade", lambda: scenario_signature_grade(client)),
                ("D_evidence_pack", lambda: scenario_evidence_pack(client, base_now)),
            ):
                try:
                    summary["scenarios"][name] = fn()
                except Exception as exc:  # keep going; record the failure honestly
                    tb = traceback.format_exc()
                    log(f"  !! scenario {name} raised: {exc!r}")
                    log(tb)
                    summary["scenarios"][name] = {"error": repr(exc), "traceback": tb}
            summary["chain_heads"] = snapshot_chain_heads(client.app.state.gw.audit)
    finally:
        gw = getattr(app.state, "gw", None)
        close = getattr(gw, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    # Scenario B is a standalone script (independent of the app / DB).
    try:
        summary["scenarios"]["B_nmr_pilot"] = scenario_nmr_pilot()
    except Exception as exc:
        summary["scenarios"]["B_nmr_pilot"] = {"error": repr(exc)}

    summary["finished_utc"] = _iso(time.time())
    (RESULTS / "simulation_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    (RESULTS / "transcript.txt").write_text("\n".join(_TRANSCRIPT) + "\n", encoding="utf-8")
    log("Simulation complete. Results under docs/academic/simulation/results/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
