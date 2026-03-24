# FASE 7 PR1 — Workflow builder visual

## Objetivo
Abrir la FASE 7 con una primera entrega visible y usable del visual builder sin introducir un DSL nuevo ni romper el motor de workflows ya existente.

## Qué se ha añadido

### Backend
- Nuevo servicio `WorkflowBuilderService` en `openmiura/application/workflows/builder.py`.
- Reutilización del motor actual de workflows para:
  - normalización de definiciones
  - validación estructural
  - construcción de un grafo visual (`nodes` + `edges`)
- Validaciones específicas para builder:
  - ids duplicados
  - targets inexistentes en branches
  - detección de pasos inalcanzables

### Broker API
Nuevos endpoints:
- `GET /broker/workflow-builder/schema`
- `GET /broker/workflow-builder/playbooks`
- `GET /broker/workflow-builder/playbooks/{playbook_id}`
- `POST /broker/workflow-builder/validate`
- `POST /broker/workflow-builder/create`

### UI
Se añade una nueva pestaña **Builder** en `/ui` con:
- catálogo de playbooks reutilizables
- carga de playbook al builder
- edición de `input` JSON
- edición de `definition` JSON
- validación de definición
- preview visual del grafo
- creación directa de workflow

## Decisiones de diseño
- No se introduce todavía drag-and-drop completo.
- La representación visual usa el mismo contrato declarativo del workflow engine.
- El builder queda listo para evolucionar a edición por nodos sin duplicar semántica.

## Resultado
openMiura ya tiene una primera base funcional de **workflow builder visual** sobre la que se puede construir:
- editor por nodos
- branching avanzado
- execution replay visual
- versionado visual

## Tests añadidos
- `tests/test_phase7_workflow_builder.py`

Cobertura validada:
- schema y catálogo del builder
- carga de playbook con preview visual
- validación de branches inválidos
- creación de workflow desde el builder
- surface visible en la UI
