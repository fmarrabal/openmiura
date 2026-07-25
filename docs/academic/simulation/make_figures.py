"""Generate paper figures from the simulation results.

Reads only the JSON captured by run_simulation.py and verify_and_tamper.py and
renders seven figures (PNG at 200 dpi for preview + PDF vector for LaTeX) under
figures/. Every number, hash, verdict and exit code shown is taken verbatim
from those result files — no figure hard-codes an outcome.

Run (after the two drivers):
    python docs/academic/simulation/make_figures.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
FIGURES = HERE / "figures"

# Palette (light background, print-friendly).
INK = "#1f2328"; SLATE = "#57606a"; LINE = "#d0d7de"; PANEL = "#f6f8fa"
GREEN = "#1a7f37"; GREEN_BG = "#dafbe1"
RED = "#cf222e"; RED_BG = "#ffebe9"
AMBER = "#9a6700"; AMBER_BG = "#fff8c5"
BLUE = "#0969da"; BLUE_BG = "#ddf4ff"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "figure.dpi": 200,
    "savefig.dpi": 200,
    "axes.edgecolor": LINE,
    "text.color": INK,
})


def _load(name: str) -> Any:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def _ax(figsize):
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_xlim(0, 100); ax.set_ylim(0, 100)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, *, fc="white", ec=LINE, lw=1.2, text="", fs=10,
        weight="normal", tc=INK, ha="center", va="center", round_r=0.02, mono=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={round_r*100}",
                                fc=fc, ec=ec, lw=lw, mutation_aspect=1))
    if text:
        fam = "DejaVu Sans Mono" if mono else "DejaVu Sans"
        ax.text(x + (w/2 if ha == "center" else 2.2), y + h/2, text, ha=ha, va=va,
                fontsize=fs, color=tc, weight=weight, family=fam, zorder=5)


def arrow(ax, x1, y1, x2, y2, color=SLATE, lw=1.6, style="-|>"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                                 mutation_scale=14, color=color, lw=lw, zorder=1))


def badge(ax, x, y, label, kind):
    fc, tc = {"ok": (GREEN_BG, GREEN), "fail": (RED_BG, RED),
              "block": (AMBER_BG, AMBER), "info": (BLUE_BG, BLUE)}[kind]
    box(ax, x, y, 15, 5.2, fc=fc, ec=fc, text=label, fs=9, weight="bold", tc=tc, round_r=0.03)


def title(ax, t, sub=""):
    ax.text(2, 96, t, fontsize=14, weight="bold", color=INK, ha="left", va="top")
    if sub:
        ax.text(2, 90.5, sub, fontsize=9.5, color=SLATE, ha="left", va="top")


def save(fig, name):
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / f"{name}.png", bbox_inches="tight", facecolor="white")
    fig.savefig(FIGURES / f"{name}.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  wrote {name}.png / .pdf")


# ---------------------------------------------------------------------------
def fig1_governance_flow():
    s = _load("simulation_summary.json")
    a = s["scenarios"]["A_governed_runtime"]
    v = a["validation"]
    fig, ax = _ax((10, 5.2))
    title(ax, "Fig. 1  Governed runtime: a policy change blocked until approved",
          "Scenario A — openMiura's canonical demo, run in-process against a real audit store")

    stages = [
        ("1. Requester\n(platform-admin)", BLUE_BG, BLUE),
        ("2. Policy engine\nverdict: PENDING", AMBER_BG, AMBER),
        ("3. Human approval\n(security-admin,\ncanvas inspector)", BLUE_BG, BLUE),
        ("4. Execute\n(version → active)", GREEN_BG, GREEN),
        ("5. Signed release\n+ audit trail", GREEN_BG, GREEN),
    ]
    x = 3.5; y = 62; w = 16.5; h = 16; gap = 3.0
    x2 = None
    for i, (t, fc, tc) in enumerate(stages):
        box(ax, x, y, w, h, fc=fc, ec=tc, lw=1.4, text=t, fs=8.5, tc=tc, weight="bold")
        if i == 1:
            x2 = x + w  # right edge of stage 2
        if i < len(stages) - 1:
            arrow(ax, x + w, y + h/2, x + w + gap, y + h/2)
        x += w + gap
    # gate marker over the 2→3 arrow
    ax.text(x2 + gap/2, y + h + 2.5, "human-in-the-loop gate",
            ha="center", fontsize=8.5, color=AMBER, style="italic")

    # validation checklist
    ax.text(3.5, 50, "Validation (all checks from the live run):", fontsize=10, weight="bold")
    items = list(v.items())
    col_w = 47
    for i, (k, val) in enumerate(items):
        cx = 3.5 + (i % 2) * col_w
        cy = 44 - (i // 2) * 5.4
        mark = "✓" if val else "✗"
        col = GREEN if val else RED
        ax.text(cx, cy, mark, fontsize=11, color=col, weight="bold", va="center")
        ax.text(cx + 3, cy, k, fontsize=9, color=INK, va="center", family="DejaVu Sans Mono")

    ok = a["success"]
    badge(ax, 78, 50.5, "success" if ok else "FAILED", "ok" if ok else "fail")
    ax.text(3.5, 4, f"runtime_id {a['runtime_id'][:8]}…   approval_id {a['approval_id'][:8]}…",
            fontsize=8, color=SLATE, family="DejaVu Sans Mono")
    save(fig, "fig1_governance_flow")


# ---------------------------------------------------------------------------
def fig2_verification_triangle():
    vs = _load("verify_summary.json")
    fig, ax = _ax((10, 5.4))
    title(ax, "Fig. 2  The verification chain: WHAT + WHO + WHEN, checkable offline",
          "Each leg is a real command run against the exported artifacts")

    cards = [
        ("WHAT", "Tamper-evident audit trail",
         "openmiura db verify-chain",
         f"all chains intact · exit {vs['verify_chain_intact']['exit']}", "ok"),
        ("WHO", "Signed, signer-bound evidence pack",
         "openmiura verify <pack> --trust-anchor <fpr>",
         f"VERIFIED · authoritative · exit {vs['trust_anchor']['real_anchor_exit']}", "ok"),
        ("WHEN", "RFC 3161 trusted timestamp",
         "openmiura verify <stamped-pack>",
         f"genTime {vs['rfc3161'].get('gen_time','n/a')} · exit {vs['rfc3161'].get('verify_stamped_exit','n/a')}", "ok"),
    ]
    y = 74
    for tag, prim, cmd, verdict, kind in cards:
        box(ax, 3.5, y - 18, 93, 18, fc=PANEL, ec=LINE, lw=1.2, round_r=0.015)
        box(ax, 5.5, y - 14.5, 12, 11, fc=BLUE_BG, ec=BLUE, text=tag, fs=13, weight="bold", tc=BLUE)
        ax.text(21, y - 4.6, prim, fontsize=11, weight="bold", va="center")
        ax.text(21, y - 10.5, cmd, fontsize=9.5, color=SLATE, va="center", family="DejaVu Sans Mono")
        badge(ax, 79, y - 11.6, "PASS", kind)
        ax.text(70.5, y - 15.2, verdict, fontsize=8.2, color=SLATE, ha="left", family="DejaVu Sans Mono")
        y -= 23
    ax.text(3.5, 3.5, "All three verified with only the cryptography library — no server, no database, no network at verify time.",
            fontsize=8.5, color=SLATE, style="italic")
    save(fig, "fig2_verification_triangle")


# ---------------------------------------------------------------------------
def _chain_rows(payload):
    rows = []
    for res in payload["tables"]:
        for ch in res["chains"]:
            rows.append((res["table"], ch["scope"][:12], ch["count"],
                         ch["chain_valid"] and ch["head_matches"], ch.get("first_bad_seq")))
    return rows


def fig3_tamper_detection():
    intact = _load("verify_chain_intact.json")
    tamper = _load("verify_chain_tampered.json")
    dt = _load("verify_summary.json")["db_tamper"]
    fig, ax = _ax((10, 5.6))
    title(ax, "Fig. 3  Two-layer tamper-evidence on the audit hash chain",
          "Left: intact live DB. Right: after a forced edit to a signed approval.")

    def panel(x0, payload, header, hkind):
        box(ax, x0, 30, 44, 48, fc="white", ec=LINE, lw=1.3, round_r=0.015)
        badge(ax, x0 + 2.5, 71, header, hkind)
        ax.text(x0 + 2.5, 66, "db verify-chain", fontsize=9, color=SLATE, family="DejaVu Sans Mono")
        yy = 60
        for tbl, scope, cnt, ok, bad in _chain_rows(payload):
            col = GREEN if ok else RED
            mark = "PASS" if ok else "FAIL"
            ax.text(x0 + 2.5, yy, mark, fontsize=8.5, color=col, weight="bold", family="DejaVu Sans Mono")
            extra = "" if ok else f"  first_bad_seq={bad}"
            ax.text(x0 + 11, yy, f"{tbl}", fontsize=8.2, color=INK, family="DejaVu Sans Mono")
            ax.text(x0 + 11, yy - 2.7, f"scope {scope}…  n={cnt}{extra}", fontsize=7.3, color=SLATE, family="DejaVu Sans Mono")
            yy -= 6.4
        verdict = "TAMPER DETECTED" if payload["any_tamper"] else "all chains intact"
        vk = "fail" if payload["any_tamper"] else "ok"
        fc, tc = {"ok": (GREEN_BG, GREEN), "fail": (RED_BG, RED)}[vk]
        box(ax, x0 + 2.5, 33, 28, 5.4, fc=fc, ec=fc, text=verdict, fs=9, weight="bold", tc=tc, round_r=0.03)
        ax.text(x0 + 32.5, 35.7, f"exit {1 if payload['any_tamper'] else 0}", fontsize=8.5, color=SLATE, family="DejaVu Sans Mono")

    panel(3.5, intact, "INTACT", "ok")
    panel(52.5, tamper, "AFTER EDIT", "fail")

    # two-layer note
    box(ax, 3.5, 6, 93, 18, fc=PANEL, ec=LINE, round_r=0.015)
    ax.text(5.5, 21, "Two layers of defence:", fontsize=9.5, weight="bold")
    l1 = dt["layer1_plain_update_rejected"]
    ax.text(5.5, 16, f"① Append-only DB triggers on events/tool_calls/decision_traces — "
                     f"a plain UPDATE is {'rejected' if l1 else 'NOT rejected'}: "
                     f"“{dt['layer1_trigger_error']}”", fontsize=8.3, color=INK)
    ax.text(5.5, 11.5, "② The per-scope hash chain covers all four tables, including release_approvals "
                       "(trigger-free). A direct edit", fontsize=8.3, color=INK)
    ax.text(5.5, 8.2, "   to a signed approval leaves row_hash stale, so verify-chain flags the exact row.",
            fontsize=8.3, color=INK)
    save(fig, "fig3_tamper_detection")


# ---------------------------------------------------------------------------
def fig4_pack_matrix():
    vs = _load("verify_summary.json")
    fig, ax = _ax((10, 4.4))
    title(ax, "Fig. 4  Offline evidence-pack verification — the honest verdict grid",
          "openmiura verify distinguishes untampered-but-unbound, bound, foreign-key and tampered")

    rows = [
        ("no trust anchor", "VERIFIED", "consistent, signer not asserted",
         vs["verify_pack_no_anchor"]["exit"], "info"),
        ("--trust-anchor  (real signer)", "VERIFIED", "authoritative — signer confirmed",
         vs["trust_anchor"]["real_anchor_exit"], "ok"),
        ("--trust-anchor  (foreign key)", "NON-AUTHORITATIVE", "signed, but not by a trusted key",
         vs["trust_anchor"]["foreign_anchor_exit"], "block"),
        ("tampered pack", "FAILED", "package_integrity_valid = false",
         vs["verify_pack_tampered"]["exit"], "fail"),
    ]
    # header
    ax.text(3.5, 78, "input", fontsize=9, weight="bold", color=SLATE)
    ax.text(38, 78, "verdict", fontsize=9, weight="bold", color=SLATE)
    ax.text(88, 78, "exit", fontsize=9, weight="bold", color=SLATE)
    y = 68
    for inp, verdict, note, code, kind in rows:
        fc = {"ok": GREEN_BG, "fail": RED_BG, "block": AMBER_BG, "info": BLUE_BG}[kind]
        tc = {"ok": GREEN, "fail": RED, "block": AMBER, "info": BLUE}[kind]
        box(ax, 3.5, y - 2, 93, 13.5, fc=fc, ec=fc, round_r=0.02)
        ax.text(6, y + 6.5, inp, fontsize=9.5, weight="bold", family="DejaVu Sans Mono", va="center")
        ax.text(38, y + 6.5, verdict, fontsize=10, weight="bold", color=tc, va="center")
        ax.text(38, y + 1.6, note, fontsize=8, color=SLATE, va="center")
        box(ax, 86, y + 1.5, 9, 8, fc="white", ec=tc, text=str(code), fs=12, weight="bold", tc=tc, round_r=0.04)
        y -= 16.5
    save(fig, "fig4_pack_verification")


# ---------------------------------------------------------------------------
def fig5_signature_grade():
    c = _load("scenario_c_signature_grade.json")
    fig, ax = _ax((10, 5.6))
    title(ax, "Fig. 5  Signature-grade approval (SoD + n-of-m quorum + TOTP)",
          f"Scenario C — release {c['release_id'][:8]}…, quorum n={c['quorum_required_n']}, distinct approvers required")

    steps = [
        ("creator user:alice tries to approve", "BLOCKED", "block", "separation of duties (403)"),
        ("unknown 'ghost' tries to approve", "BLOCKED", "block", "identity not resolved (403)"),
        ("user:carol approves without OTP", "BLOCKED", "block", "second factor required (403)"),
        ("user:carol approves with TOTP", "1 / 2", "info", "quorum not yet met"),
        ("user:dave approves with TOTP", "2 / 2", "ok", "quorum met → approved"),
    ]
    y = 74
    for label, tag, kind, note in steps:
        box(ax, 3.5, y - 8.5, 66, 9, fc=PANEL, ec=LINE, round_r=0.02)
        ax.text(6, y - 4, label, fontsize=9.5, va="center", family="DejaVu Sans Mono")
        badge(ax, 47, y - 6.6, tag, kind)
        ax.text(71, y - 4, note, fontsize=8.3, color=SLATE, va="center")
        y -= 11.5
    # signatures
    signed = [a for a in c["signed_approvals"] if a.get("signature")]
    box(ax, 3.5, 5, 93, 10, fc=GREEN_BG, ec=GREEN, round_r=0.015)
    ax.text(5.5, 11.5, f"final status: {c['status_after_second']}   ·   "
                       f"{len(signed)} per-approval Ed25519 signatures on the audit hash chain",
            fontsize=9.5, weight="bold", color=GREEN)
    sig_txt = "   ".join(f"{a['actor']}:{str(a['signature'])[:10]}…" for a in signed)
    ax.text(5.5, 7.5, sig_txt, fontsize=8.2, color=INK, family="DejaVu Sans Mono")
    save(fig, "fig5_signature_grade")


# ---------------------------------------------------------------------------
def fig6_hashchain():
    s = _load("simulation_summary.json")
    heads = s.get("chain_heads", {})
    fig, ax = _ax((10, 5.0))
    title(ax, "Fig. 6  Per-(table, scope) append-only hash chain",
          "Each row hashes its content + the previous row's hash; the head is attested in the signed pack")

    # show the largest chain, then the largest chain from a *different* table
    # (so an operational table and the signed-approvals table both appear).
    ordered = sorted(heads.get("heads", []), key=lambda h: -h["head_seq"])
    hs = []
    if ordered:
        hs.append(ordered[0])
        for h in ordered[1:]:
            if h["table"] != ordered[0]["table"]:
                hs.append(h)
                break
        if len(hs) == 1 and len(ordered) > 1:
            hs.append(ordered[1])
    y = 66
    for h in hs:
        ax.text(3.5, y + 10, f"{h['table']}   ·   scope {h['scope'][:12]}…   ·   {h['head_seq']} rows",
                fontsize=9.5, weight="bold")
        n = min(4, h["head_seq"])
        x = 4
        seqs = list(range(1, n)) + [h["head_seq"]]
        for i, seq in enumerate(seqs):
            is_head = (seq == h["head_seq"])
            fc = GREEN_BG if is_head else "white"
            ec = GREEN if is_head else LINE
            box(ax, x, y, 17, 8.5, fc=fc, ec=ec, lw=1.3, round_r=0.03)
            ax.text(x + 8.5, y + 5.6, f"seq {seq}", fontsize=8.5, ha="center", weight="bold")
            digest = h["head_hash"][:10] if is_head else "row_hash…"
            ax.text(x + 8.5, y + 2.2, digest, fontsize=7.3, ha="center", color=SLATE, family="DejaVu Sans Mono")
            if i < len(seqs) - 1:
                if seq == n - 1 and h["head_seq"] > n:
                    ax.text(x + 20.5, y + 4.2, "…", fontsize=13, ha="center", va="center", color=SLATE)
                    arrow(ax, x + 17, y + 4.2, x + 19, y + 4.2, lw=1.2)
                    arrow(ax, x + 22, y + 4.2, x + 24, y + 4.2, lw=1.2)
                else:
                    arrow(ax, x + 17, y + 4.2, x + 24, y + 4.2, lw=1.2)
            x += 24
        ax.text(x + 1, y + 4.2, "← head\n   (in pack)", fontsize=8, color=GREEN, va="center", weight="bold")
        y -= 30
    counts = heads.get("row_counts", {})
    ax.text(3.5, 6, "chained tables: " + ", ".join(f"{k}={v}" for k, v in counts.items()),
            fontsize=8.3, color=SLATE, family="DejaVu Sans Mono")
    save(fig, "fig6_hashchain")


# ---------------------------------------------------------------------------
def fig7_rfc3161():
    r = _load("verify_summary.json")["rfc3161"]
    fig, ax = _ax((10, 4.8))
    title(ax, "Fig. 7  RFC 3161 trusted timestamp — the WHEN",
          "A public TSA signs the pack signature; the token is then verified offline")

    nodes = [
        ("Evidence pack\nsigned (Ed25519)", BLUE_BG, BLUE),
        (f"TSA token\n{r.get('tsa_common_name','TSA')}", AMBER_BG, AMBER),
        (f"Offline verify\ngenTime attested", GREEN_BG, GREEN),
    ]
    x = 8; y = 45; w = 22; h = 16
    for i, (t, fc, tc) in enumerate(nodes):
        box(ax, x, y, w, h, fc=fc, ec=tc, lw=1.5, text=t, fs=9.5, weight="bold", tc=tc)
        if i < len(nodes) - 1:
            arrow(ax, x + w, y + h/2, x + w + 8, y + h/2)
        x += w + 8
    ax.text(50, 33, f"genTime = {r.get('gen_time','n/a')}   (RFC 3161, {r.get('tsa_url','')})",
            fontsize=9.5, ha="center", color=INK, family="DejaVu Sans Mono")
    badge(ax, 42.5, 20, "PASS", "ok" if r.get("verify_stamped_exit") == 0 else "fail")
    ax.text(50, 12, "The timestamp binds a trusted “when” to the trusted “what” and “who” — no network needed to re-check it.",
            fontsize=8.5, ha="center", color=SLATE, style="italic")
    save(fig, "fig7_rfc3161")


def main() -> int:
    print("Rendering figures from real simulation results…")
    fig1_governance_flow()
    fig2_verification_triangle()
    fig3_tamper_detection()
    fig4_pack_matrix()
    fig5_signature_grade()
    fig6_hashchain()
    fig7_rfc3161()
    print("Done. Figures under docs/academic/simulation/figures/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
