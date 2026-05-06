# Cierre de fase de refactor de `openmiura/application/openclaw`

Este directorio recoge los artefactos formales de cierre de la fase de refactor del árbol `openmiura/application/openclaw`.

## Documentos incluidos

- [Cierre técnico formal](openclaw_refactor_phase_closure.md)
- [Changelog técnico de la fase](openclaw_refactor_changelog.md)
- [Guía de extensión para contribuidores](openclaw_extension_guide.md)
- [Checklist de revisión de PRs](openclaw_pr_review_checklist.md)

## ADRs asociados

- [ADR-0020 — Descomposición de `scheduler.py` en módulos especializados](../adr/ADR-0020-openclaw-scheduler-decomposition.md)
- [ADR-0021 — Helpers transversales para ventanas temporales, familias de jobs y runtime context](../adr/ADR-0021-openclaw-cross-cutting-helpers.md)
- [ADR-0022 — Centralización del approval bootstrap](../adr/ADR-0022-openclaw-approval-bootstrap-centralization.md)
- [ADR-0023 — Capa común de explainability y analytics shape](../adr/ADR-0023-openclaw-governance-explainability.md)
- [ADR-0024 — Separación entre baseline rollout, runtime alerts y alert governance bundles](../adr/ADR-0024-openclaw-domain-separation.md)

## Estado

La fase queda cerrada a nivel técnico. La deuda remanente aceptada se considera no bloqueante y pasa a tratarse como mantenimiento oportunista o hardening incremental cuando coincida con cambios funcionales cercanos.
