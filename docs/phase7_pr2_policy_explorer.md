# FASE 7 PR2 — Policy explorer + simulación y diff de políticas

## Objetivo
Abrir la segunda pieza visible de FASE 7: una superficie de exploración de políticas para operadores y admins que permita:

- inspeccionar la política efectiva cargada en runtime
- simular decisiones sobre tools, memory, secrets, channels y approvals
- comparar una política candidata frente a la política actual
- visualizar el impacto de cambios antes de publicarlos

## Lo implementado

### Backend
- `PolicyEngine.from_mapping(...)` y normalización de documentos de política en memoria.
- `PolicyExplorer` embebido en `AdminService` con tres capacidades principales:
  - `policy_explorer_snapshot(...)`
  - `policy_explorer_simulate(...)`
  - `policy_explorer_diff(...)`
- Endpoints HTTP admin:
  - `GET /admin/policy-explorer/snapshot`
  - `POST /admin/policy-explorer/simulate`
  - `POST /admin/policy-explorer/diff`
- Endpoints equivalentes en broker admin:
  - `GET /broker/admin/policy-explorer/snapshot`
  - `POST /broker/admin/policy-explorer/simulate`
  - `POST /broker/admin/policy-explorer/diff`

### Qué devuelve cada endpoint
- **snapshot**
  - firma de la política activa
  - documento de política cargado
  - resumen por sección (`defaults`, `tool_rules`, `memory_rules`, etc.)
  - scopes soportados y ejemplos de request
- **simulate**
  - decisión baseline con la política activa
  - decisión candidate con una política proporcionada inline
  - `change_summary` con campos que cambian (`allowed`, `requires_confirmation`, `requires_approval`, `reason`, `matched_rules`)
- **diff**
  - diff por secciones
  - altas, bajas y cambios de reglas
  - evaluación de muestras (`samples`) para ver impacto funcional

### UI
Nueva pestaña **Policies** en `/ui` con:
- snapshot de política actual
- request de simulación editable en JSON
- política candidata editable en texto
- botones de:
  - cargar política actual
  - simular current
  - simular candidate
  - diff
- paneles para resultado de simulación y diff

## Decisiones de diseño
- La política candidata se acepta como YAML inline para facilitar iteración rápida en la UI.
- El diff es estructural por secciones y además admite muestras funcionales (`samples`) para aproximar impacto runtime.
- La política en memoria ya no intenta recargarse desde fichero: se corrigió este bug durante la ronda.

## Problema real corregido
Había una regresión en `PolicyEngine.from_mapping(...)`: al reutilizar métodos como `snapshot()` o `signature()`, el engine en memoria intentaba recargar desde un path inexistente y terminaba vaciando el documento de política.

Se corrigió introduciendo semántica explícita de engine **in-memory**.

## Tests añadidos
- `tests/test_phase7_policy_explorer.py`

Cobertura principal:
- surface UI de Policy Explorer
- snapshot del documento activo
- simulación baseline vs candidate
- diff de políticas con muestras funcionales

## Validación ejecutada
- `python -m compileall -q app.py openmiura tests`
- `pytest -q`

Resultado: **OK**.
