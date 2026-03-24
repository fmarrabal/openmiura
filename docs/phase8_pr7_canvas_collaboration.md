# openMiura — FASE 8 PR7
## Collaboration y experiencia compartida

### Objetivo
Convertir el canvas en una superficie colaborativa real, con comentarios, snapshots, presencia compartida y comparación de estados entre iteraciones operativas.

### Alcance implementado
- Migración **15**: `canvas_collaboration_shared_experience`
- Nuevas tablas:
  - `canvas_comments`
  - `canvas_snapshots`
  - `canvas_presence_events`
- Extensión de `LiveCanvasService` con:
  - creación y listado de comentarios
  - creación y listado de snapshots
  - generación de vistas compartidas mediante snapshot con `share_token`
  - comparación entre snapshots A/B
  - listado de eventos de presencia
- Enriquecimiento del detalle de canvas con:
  - `comments`
  - `snapshots`
  - `presence_events`
- Endpoints admin HTTP y broker para:
  - comentarios
  - snapshots
  - compare snapshots
  - share view
  - presence events
- UI del canvas enriquecida con bloque **Collaboration**

### Criterios de aceptación cubiertos
- Varios operadores pueden dejar comentarios sobre un mismo canvas sin fuga entre tenants/workspaces.
- Los snapshots capturan el estado del canvas y permiten comparar dos estados distintos.
- La presencia compartida queda registrada además del estado vivo actual.
- La experiencia compartida queda alineada con segregación multi-tenant y auditoría existente.

### Decisiones de diseño
- **Shared view** se implementa como snapshot especializado (`snapshot_kind=shared_view`) para reutilizar persistencia y comparación.
- La comparación A/B se expresa como delta estructural de nodos, aristas, comentarios y presencia.
- Los eventos de presencia no sustituyen al estado vivo de presencia; lo complementan para trazabilidad histórica.

### Estado funcional
PR7 queda **persistido, auditable y operativo** como base de colaboración en canvas. La edición concurrente avanzada en tiempo real sigue apoyándose en la base de presencia ya introducida en PR5, mientras que los mecanismos de comentario, snapshot y comparación ya están cerrados en este PR.
