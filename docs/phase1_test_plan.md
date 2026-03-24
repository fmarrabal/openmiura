# Plan de pruebas de FASE 1

## Objetivo
Validar que la arquitectura, el broker HTTP v1, el modelo de permisos y los contratos de extensibilidad introducidos en la fase 1 siguen funcionando sin regresiones.

## Suite mínima obligatoria

```bash
pytest -q tests/test_admin_integration.py \
          tests/test_http_broker.py \
          tests/test_phase1_phase2_audit_closure.py \
          tests/unit/test_extension_sdk.py
```

## Puntos a comprobar
- routers HTTP canónicos bajo `openmiura.interfaces.*`
- shims legacy (`openmiura.endpoints.*`, `openmiura.channels.http_broker`)
- broker HTTP v1 y compatibilidad con monkeypatching en tests
- contratos del SDK de extensiones
- imports canónicos de persistencia en `openmiura.infrastructure.persistence.*`
