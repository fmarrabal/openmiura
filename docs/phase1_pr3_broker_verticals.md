# PR3 — Broker HTTP v1 troceado por verticales

Este cambio sigue la **FASE 1** del roadmap y aplica el siguiente paso previsto:

- formalización del broker HTTP v1
- separación por verticales
- reducción del archivo monolítico `openmiura/channels/http_broker.py`
- mantenimiento de compatibilidad hacia atrás

## Resultado

El broker deja de vivir en un único archivo grande y pasa a organizarse en:

- `openmiura/interfaces/broker/router.py`
- `openmiura/interfaces/broker/common.py`
- `openmiura/interfaces/broker/schemas.py`
- `openmiura/interfaces/broker/routes/auth.py`
- `openmiura/interfaces/broker/routes/tools.py`
- `openmiura/interfaces/broker/routes/state.py`
- `openmiura/interfaces/broker/routes/chat.py`
- `openmiura/interfaces/broker/routes/admin.py`

## Compatibilidad

Se conserva `openmiura/channels/http_broker.py` como **shim legado**:

- sigue exportando `build_broker_router`
- sigue exportando los modelos request/response del broker
- sigue exponiendo `process_message` para monkeypatch y tests existentes

## Beneficio arquitectónico

La separación queda alineada con el roadmap:

- `interfaces/broker/*` = transporte HTTP del broker
- `application/auth/*` = auth centralizada
- `core/policies/*` = modelo común de permisos/capacidades

## Estado

- compatibilidad observable preservada
- suite completa en verde
- broker listo para el siguiente paso del roadmap sin volver al monolito
