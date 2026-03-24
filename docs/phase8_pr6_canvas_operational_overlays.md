# openMiura — FASE 8 — PR6 Canvas operational overlays

## Objetivo
Convertir el canvas en una superficie operativa real, reutilizando capacidades ya existentes de policy, costes, approvals, fallos, trazas y gobierno de secretos.

## Alcance implementado
- Migración **14** con la tabla `canvas_overlay_states`.
- Extensión de `LiveCanvasService` para overlays operativos persistidos y consultables.
- Persistencia de estados de overlay por canvas mediante:
  - `state_key`
  - `toggles_json`
  - `inspector_json`
- Nuevos endpoints HTTP admin y broker para:
  - guardar estado de overlay
  - consultar overlays operativos calculados
- Integración UI en la pestaña **Canvas** con:
  - panel de toggles
  - guardado de estado
  - inspector operativo
- Reutilización explícita de servicios ya existentes:
  - `CostGovernanceService`
  - `OperatorConsoleService`
  - `SecretGovernanceService`
  - decision traces y approvals desde `AuditStore`

## Superficies nuevas
### Persistencia
- `canvas_overlay_states`

### Overlay families
- `policy`
- `cost`
- `traces`
- `failures`
- `approvals`
- `secrets`

## Comportamiento funcional
- Los overlays se calculan desde señales reales del backend y no desde mock visual.
- El inspector puede enfocarse en un nodo concreto (`selected_node_id`) o trabajar sobre el canvas completo.
- Los overlays respetan scope de:
  - `tenant_id`
  - `workspace_id`
  - `environment`
- La información sensible de secretos se sanea antes de exponerse al canvas.
- El estado visual/operativo del overlay queda persistido por canvas y reutilizable.

## Criterios de aceptación cubiertos
- Coherencia entre overlay y backend.
- No exposición de secretos sensibles.
- Lectura correcta del estado de approvals y fallos.
- Persistencia del estado de overlay por canvas.
- Segregación multi-tenant/workspace/environment.

## Validación realizada
- `python -m compileall -q app.py openmiura tests`
- `node --check openmiura/ui/static/app.js`
- `pytest -q tests/test_phase8_release_service.py tests/test_phase8_release_admin.py tests/test_phase8_pr2_release_governance.py tests/test_phase8_pr2_release_governance_admin.py tests/test_phase8_pr3_voice_runtime.py tests/test_phase8_pr3_voice_runtime_admin.py tests/test_phase8_pr4_pwa_foundation.py tests/test_phase8_pr4_pwa_admin.py tests/test_phase8_pr5_live_canvas_core.py tests/test_phase8_pr5_live_canvas_admin.py tests/test_phase8_pr6_canvas_operational_overlays.py tests/test_phase8_pr6_canvas_overlays_admin.py tests/test_db_migrations.py`
- Resultado: **18 tests OK**

## Nota de madurez
PR6 deja el canvas ya conectado con overlays operativos útiles para operación real. La siguiente pieza natural es **PR7**, centrada en colaboración, comentarios, snapshots y presencia compartida en tiempo real.
