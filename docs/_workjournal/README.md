# Workjournal — session-by-session log

Each file in this directory is a single Claude Code session's
closure note. The CLAUDE.md master prompt (§3.4) makes the
workjournal mandatory at the end of every batch of work: what was
done (commits + branches), what is left of the current phase,
decisions taken and why, risks for Curro to review, recommended
next step.

The files double as the project's audit trail of itself. The
master plan's Phase 4 paper draft and Phase 4 strategy decisions
are expected to draw on this log.

## Chronological index

| Date | Title | Branch(es) merged | Closed |
|---|---|---|---|
| 2026-05-06 22:59 | [Fase 0 cerrada](2026-05-06-2259.md) | `phase/0-cleanup-and-truth` (#16) | Phase 0: cleanup and truth |
| 2026-05-08 19:46 | [Fase 1 cerrada](2026-05-08-1946.md) | `phase/1-refactor-audit-store` (#17) | Phase 1: persistence layer (Sprints 1-4) |
| 2026-05-09 01:15 | [Fase 1.1 cerrada](2026-05-09-0115.md) | `phase/1.1-sessions-repo` (#18) | SessionsRepo + delegator compaction (`audit.py` 2,145 → 755 lines) |
| 2026-05-09 12:52 | [Fase 1.2 cerrada](2026-05-09-1252.md) | `phase/1.2-admin-routes` (#19) | admin.py split into sub-routers + 9-file residual debt flagged |
| 2026-05-09 13:36 | [Fase 2 cerrada](2026-05-09-1336.md) | `phase/2-regulated-whitepaper` (#20) | Whitepaper + Part 11 / Annex 11 / GAMP 5 / ALCOA+ mappings + 5 policy packs + 3 use cases |
| 2026-05-09 19:54 | [Fase 3 cerrada](2026-05-09-1954.md) | `phase/3-discovery-and-pilot` (#21) | Discovery interview kit + UAL NMR pilot |
| 2026-05-09 20:40 | [Fase 4 cerrada — master plan completo](2026-05-09-2040.md) | `phase/4-strategy-and-paper` (#22) | STRATEGY.md + paper draft + 36-entry bibliography + 5 TFG/TFM proposals + 90-min lecture |
| 2026-05-11 23:54 | [Residual debt closure session](2026-05-11-2354.md) | 11 PRs from `phase/post-*` (#23-#32, #34) | Every production `.py > 1,500` lines split; DoD literal "no file over 1,500" met across the repo |

## How to add a new entry

Filename pattern: `YYYY-MM-DD-HHMM.md` (24-hour). Get the
current value from `date +%Y-%m-%d-%H%M`.

Minimum sections (per CLAUDE.md §3.4):

```markdown
# YYYY-MM-DD HH:MM — <one-line title>

## Qué se hizo
## Resultado / DoD status
## Decisiones tomadas y por qué
## Riesgos / notas
## Próximo paso recomendado
```

After committing the entry, **update the table in this file**
with the new row.

## Naming convention

- Pre-cleanup phases of the master plan use the literal Spanish
  "Fase N" naming.
- Post-master-plan cleanup PRs use the prefix
  `phase/post-<short-slug>` so the chronology stays visually
  consistent in `git log` and in this index.

## Spin-off journals (optional)

The discovery phase (`docs/regulated/discovery/`) suggests a
`docs/_workjournal/discovery/<date>-<persona>.md` directory for
the per-interview logs once those start happening. That directory
does not yet exist; it will be created on the first real
interview.
