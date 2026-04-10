# ADR-0022 — Centralización del approval bootstrap

## Estado
Aceptado

## Contexto
El bootstrap de approvals aparecía repetido en varios flujos de governance y runtime alerts.

## Decisión
Centralizar el patrón de `get/create` de approvals por `workflow_id + step_id` en `approval_common.py`.

## Alternativas consideradas
- mantener lógica local por flujo;
- centralizar solo listados y no creación.

## Consecuencias
- menos duplicación;
- semántica más uniforme de approvals;
- menor probabilidad de divergencia entre workflows.

## Riesgos aceptados
- algunos casos especiales siguen necesitando enriquecimiento local;
- la centralización no elimina la necesidad de tests por flujo.
