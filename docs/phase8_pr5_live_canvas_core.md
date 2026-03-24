# openMiura — FASE 8 PR5
## Live canvas core

### Objetivo
Introducir el núcleo persistente y en tiempo real del canvas operativo para representar workflows, tools, approvals, métricas y artefactos dentro de una superficie auditable y segregada por tenant/workspace/environment.

### Alcance implementado
- Migración **13**: `live_canvas_core`
- Nuevas tablas:
  - `canvas_documents`
  - `canvas_nodes`
  - `canvas_edges`
  - `canvas_views`
  - `canvas_presence`
- Nuevo servicio de aplicación: `LiveCanvasService`
- Nuevos métodos en `AuditStore` para persistencia, consulta, conteo y feed de eventos de canvas
- Integración en `AdminService`
- Endpoints HTTP admin:
  - `GET /admin/canvas/documents`
  - `POST /admin/canvas/documents`
  - `GET /admin/canvas/documents/{canvas_id}`
  - `POST /admin/canvas/documents/{canvas_id}/nodes`
  - `POST /admin/canvas/documents/{canvas_id}/edges`
  - `POST /admin/canvas/documents/{canvas_id}/views`
  - `POST /admin/canvas/documents/{canvas_id}/presence`
  - `GET /admin/canvas/documents/{canvas_id}/events`
- Endpoints broker equivalentes bajo `/broker/admin/canvas/...`
- Pestaña **Canvas** en la UI, con creación de canvas, upsert de nodos y aristas, guardado de vistas y presencia

### Modelo funcional
- **Canvas document**: unidad raíz del lienzo operativo
- **Node**: elemento visual tipado (`workflow`, `step`, `tool`, `approval`, `metric`, `artifact`, `note`, etc.)
- **Edge**: relación entre nodos
- **View**: layout/filtros persistidos para una misma representación
- **Presence**: estado efímero persistido del operador dentro del canvas
- **Events**: acciones de canvas trazadas en el event log existente con canal `canvas`

### Decisiones de diseño
- Se reutiliza el `event log` existente en lugar de abrir una tabla nueva de realtime events para mantener trazabilidad uniforme.
- La segregación se mantiene por `tenant_id`, `workspace_id` y `environment` en todas las tablas nuevas.
- PR5 deja preparado el canvas como núcleo persistente y auditable; los overlays operativos más ricos quedan para **PR6**.
- La sincronización “realtime” en este PR se apoya en presencia persistida + feed de eventos reciente; no introduce todavía un motor colaborativo avanzado.

### Criterios de aceptación cubiertos
- Persistencia íntegra de canvas, nodos, aristas, vistas y presencia
- Carga de detalle consolidada del canvas
- Registro de eventos de canvas asociados al `canvas_id`
- Segregación por tenant/workspace/environment
- Exposición coherente desde HTTP admin, broker admin y UI

### Estado de validación
Se ha verificado con compilación y pruebas específicas de PR1–PR5.
