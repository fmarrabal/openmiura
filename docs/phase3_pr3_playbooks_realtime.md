# FASE 3 — PR3: playbooks más ricos + realtime más formal

## Qué se ha añadido

### Playbooks
- catálogo enriquecido con:
  - `version`
  - `category`
  - `tags`
  - `defaults`
  - `input_schema`
  - `schedule_hints`
  - `examples`
- nuevo endpoint:
  - `GET /broker/playbooks/{playbook_id}`
- instanciación con:
  - validación simple de inputs
  - merge de defaults
  - renderizado de plantillas `{{input.*}}` y `{{scope.*}}`
- nuevos playbooks base:
  - `ticket_triage`
  - `document_validation`

### Realtime
- `RealtimeBus` ahora mantiene historial circular para replay
- filtros de historial por:
  - `topic`
  - `workflow_id`
  - `session_id`
  - scope de tenancy
  - `since_id`
  - `event_types`
- nuevos endpoints:
  - `GET /broker/realtime/events`
  - `GET /broker/realtime/stream`
  - `GET /broker/workflows/{workflow_id}/stream`
- los eventos de workflow se publican con envelope más formal:
  - `topic`
  - `entity_kind`
  - `entity_id`
  - `session_id`
  - `workflow_id`
  - scope de tenancy

### Approvals
- claim y decision publican eventos realtime
- claim y decision quedan también registrados en la timeline del workflow

## Cobertura añadida
- metadatos y validación de playbooks
- renderizado de plantillas en instanciación
- replay de eventos realtime
- stream SSE por workflow
- aislamiento de acceso por workspace en streaming
