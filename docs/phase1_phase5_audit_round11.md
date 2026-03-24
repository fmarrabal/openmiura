# Auditoría round 11 — cierre de FASE 5 PR3

## Qué se ha revisado
Se revisó el árbol tras PR2 de evaluación/regresiones para añadir una capa inicial de cost governance sin romper las fases anteriores.

## Hallazgos y decisiones
1. **No introducir migración innecesaria en esta ronda**
   - Se valoró añadir una columna nueva para `workflow_name` en `evaluation_runs`.
   - Se descartó en esta PR para evitar complejidad de rollback y mantener el alcance acotado.
   - En su lugar, el eje `workflow` usa `suite_name` como alias operativo inicial.

2. **Reutilización del ledger existente**
   - `evaluation_runs.total_cost` ya era suficiente para abrir agregación por tenant/workspace/agente/provider/modelo.
   - Se construyó la gobernanza de coste por encima de ese storage en vez de duplicar tablas.

3. **Aislamiento del cambio**
   - El cambio se encapsuló en `CostGovernanceService` y en endpoints admin/broker admin.
   - No se tocaron rutas críticas del runtime ni del workflow engine.

## Problemas corregidos o evitados
- Se evitó acoplar la gobernanza de coste al policy engine o al runtime de tools antes de tiempo.
- Se evitó una migración de esquema con rollback delicado en SQLite para esta ronda.
- Se añadieron tests dedicados para que el comportamiento de budgets/alerts quede cubierto.

## Validación ejecutada
- `pytest -q tests/test_phase5_cost_governance.py tests/test_phase5_cost_admin.py tests/test_phase5_evaluation_harness.py tests/test_phase5_evaluation_admin.py tests/test_phase5_evaluation_config.py tests/test_db_migrations.py` → OK
- `pytest -q` → OK
- `python -m compileall -q app.py openmiura tests` → OK

## Estado del roadmap
- FASE 1 cerrada
- FASE 2 cerrada
- FASE 3 cerrada
- FASE 4 cerrada
- FASE 5:
  - PR1 Evaluation harness ✅
  - PR2 Regression suite + comparación histórica + scorecards ✅
  - PR3 Cost governance inicial ✅

## Riesgo residual principal
La gobernanza de coste sigue apoyándose sobre coste declarado por evaluation runs. El siguiente salto de valor está en instrumentar coste real de ejecución del agente y workflows productivos.
