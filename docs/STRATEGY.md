# openMiura — strategic decision document

*Working draft, May 2026. Consolidates the technical state of the
project after Phases 0-3 of the master plan, names the three
non-exclusive routes ahead, and recommends the one to commit to
based on what is known today.*

This document is the input to a real conversation, not a unilateral
declaration. It will be revised as the discovery interviews of
Phase 3 produce data and as the routes diverge in practice.

---

## 1. Where the project stands today

Four phases of the master plan defined in `CLAUDE.md` are closed:

- **Phase 0 — Cleanup and truth.** The repository stops
  misrepresenting itself. Honest README, no fake claims, marketing
  copy archived, `AGENTS.md` discloses LLM-assisted development.
- **Phase 1 — Refactor.** The 5,693-line `AuditStore` god-class
  is split into a thin facade plus 12 specialised repositories
  under `openmiura/persistence/`. The 4,841-line `admin.py` HTTP
  layer is split into a package of 15 sub-routers under
  `openmiura/interfaces/http/routes/admin/`.
- **Phase 2 — GxP technical material.** A 4,000-word whitepaper,
  three control-by-control mappings (21 CFR Part 11, EU GMP
  Annex 11, GAMP 5), an honest ALCOA+ self-assessment, five
  policy packs and three clinical use-case governance
  architectures (no PHI / PII).
- **Phase 3 — Discovery + first pilot.** A Mom-Test-style
  interview kit for QA/RA conversations, plus the UAL NMR
  pilot: real research workflow, executable policy pack,
  smoke-test script, signed evidence pack.

Working artefacts that came out of those phases:

- ~7,600 lines of persistence layer (one file per bounded
  domain, none over 1,500 lines).
- ~3,200 lines of admin sub-routers.
- ~2,500 lines of regulatory documentation (whitepaper +
  mappings + ALCOA+).
- 6 policy packs, 42 structural / smoke tests passing in CI.
- Interview kit ready to send (English + Spanish templates).
- One vendor-side OQ artefact (`scripts/run_pilot_ual_nmr_demo.py`).

The repository has not been benchmarked against a competitor's
governance plane (LangSmith, Langfuse, Portkey, Credal, Microsoft
Agent Governance Toolkit). That comparison is part of Route (b)
work below.

## 2. The three routes

The routes are **not exclusive**. (a) is a sustaining default
even if (b) or (c) succeed. The strategic decision is *which one
gets the lion's share of Curro's hours* over the next 12 months.

### Route (a) — Academic demonstrator

**What it is.** Treat openMiura as the technical backbone of a
publishable contribution. Use it in teaching (governance of LLM
agents, GxP-aware AI). Direct TFGs / TFMs around it. Publish
the paper draft (Phase 4) and follow-up work as the platform
matures. No commercial commitment.

**Cost.** Low. The work is mostly Curro's existing academic
output reorganised around openMiura. A paper, two or three
graduate projects, one or two course modules per year.

**Upside.** Reliable. Builds Curro's research portfolio and
gives UAL students a real artefact to work on. Compatible with
Spanish national research funding tracks (PID, Ramón y Cajal,
EU Horizon).

**Downside.** Contained. Open-source impact stays small unless
the paper triggers a community. Industrial impact is indirect.

**Signals it is the right route.**
- Discovery interviews produce few or weak signals of acute
  pain in industry; the pattern is "interesting but not
  urgent".
- TFGs / TFMs around openMiura produce strong student
  outcomes; reviewers find the platform pedagogically useful.
- The paper is accepted in a venue that gives it durable
  visibility (Computers in Industry, Journal of Pharmaceutical
  Innovation, npj Digital Medicine).

### Route (b) — Open-source niche around regulated AI governance

**What it is.** Position openMiura as the open-source default
for "I need to govern an LLM agent inside a regulated lab and
I don't want to build the audit trail myself". Build a small,
serious community of practitioners (5–20 active users in the
first 12 months). Engage with QA / RA conferences. Maintain
release discipline; produce policy packs as users request
them.

**Cost.** Medium. Curro's hours per week probably 8–12 to keep
the community alive: PR review, release cadence, conference
attendance, mailing-list answers. Better with a co-maintainer.

**Upside.** Compounds. A serious open-source niche around
regulated AI governance is rare; the field is dominated by
closed vendors and academic prototypes. A small but loyal
community is a defensible position and an honest moat.

**Downside.** Burnout risk. Open-source maintenance scales
poorly with the number of users; without funding (foundation
grant, sponsored development, paid support), 2 years in is
where the energy runs out for most solo maintainers.

**Signals it is the right route.**
- Discovery interviews surface 3+ organisations with concrete
  current pain that openMiura's pattern matches *and* that
  would value an open-source rather than a closed solution.
- The paper is accepted in a venue with a practitioner
  audience (ISPE Annual Meeting workshop, Computers in
  Industry, GAMP USA / Europe contributions).
- One or two clear contributor candidates emerge from the
  discovery conversations.

### Route (c) — Spin-off / commercial offering via UAL OTRI

**What it is.** Use openMiura as the open-source core of a
commercial product targeted at regulated labs that *will pay
for* hardening, support, certification-ready validation
documentation, and hosted deployment. Engage UAL's OTRI
(technology transfer office) to evaluate spin-off feasibility.
Apply for CDTI / Neotec / EIC funding tracks if feasibility
is confirmed.

**Cost.** High. Spin-off feasibility study, legal / IP review,
business plan, hiring (at minimum a CSV/CSA-experienced
co-founder). Most of Curro's research bandwidth on hold during
the bootstrap phase.

**Upside.** Largest. A serious regulated-AI-governance
business has a real market; the competitor map is sparse
(LangSmith and Langfuse are not GxP-positioned; Credal is
adjacent but US-centric; Microsoft Agent Governance Toolkit
is bundled with Azure and not friendly to EU pharma data
sovereignty concerns).

**Downside.** Highest risk. A spin-off changes Curro's
day-to-day from researcher to founder. Failure modes include:
not finding a co-founder, not finding a paying customer in
12 months, draining the academic portfolio without commercial
return.

**Signals it is the right route.**
- Discovery interviews surface 3+ organisations that would
  pilot a paid version with a defined budget.
- A credible co-founder (CSV/CSA background, GxP industry
  contacts) appears organically through the discovery
  conversations or referrals.
- OTRI evaluation comes back positive on IP cleanliness, and
  CDTI / Neotec / EIC fit looks plausible after a 30-minute
  call with the corresponding programme officer.

## 3. Decision criteria

The three routes are ordered by cost / risk / upside (low →
high). The decision is data-driven once the discovery
interviews land.

| Signal | (a) Academic | (b) Open-source | (c) Spin-off |
|---|:---:|:---:|:---:|
| Discovery surfaces concrete pain in 1+ orgs | ✅ enough | required | required |
| Discovery surfaces concrete pain in 3+ orgs | (nice) | strong fit | required |
| Discovery surfaces willing-to-pay budget in 3+ orgs | (n/a) | (nice) | required |
| Co-founder candidate appears | (n/a) | ✅ accelerates | required |
| Paper accepted in a practitioner venue | ✅ enough | ✅ accelerates | (nice) |
| OTRI evaluation positive | (n/a) | (n/a) | required |

## 4. Recommendation

The recommendation is conditional on the discovery output, which
will land over the next 4–8 weeks. Today's reading, before that
data:

- **Default to (a) + start (b).** (a) is a low-cost sustaining
  effort regardless of the other two. (b) is a *low-commitment*
  way to test the open-source community appetite — by holding
  the discovery conversations of Phase 3 and shipping a small
  number of additional policy packs as practitioners request
  them.
- **Hold (c) for a re-read in 8 weeks.** A spin-off decision
  with thin discovery data is a coin flip. The cheapest way to
  know whether (c) is real is to do (a) + (b) for 8 weeks and
  then look at the discovery log.

This recommendation is **provisional**. Curro fills in this
section after the first 5–10 discovery interviews are logged
under `docs/_workjournal/discovery/`; at that point the
recommendation moves from "provisional" to "decided". This
document is the place where the decision is recorded, not a
side note in a Slack thread.

## 5. What this document is not

- Not a business plan. (c) needs one if it is selected; the
  draft would live in a separate, access-controlled
  repository.
- Not a contract. None of the routes are committed to;
  this is the document where the choice is reasoned through.
- Not a substitute for the discovery interviews. The whole
  point is that **data wins**, and the data lives in the
  interview log.

## 6. Update log

- 2026-05-09 — first draft, Phase 4 of the master plan.
  Provisional recommendation is "default to (a) + start (b),
  re-read in 8 weeks". Awaiting discovery data.
