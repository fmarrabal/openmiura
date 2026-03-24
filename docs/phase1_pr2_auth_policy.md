# PR2 — auth / policy unificado

## Objetivo

Seguir el roadmap de Fase 1 consolidando un modelo común de permisos/capacidades sin romper el broker actual.

## Cambios aplicados

- Extracción del modelo de autenticación a `openmiura/core/auth/models.py`.
- Extracción del motor de políticas a `openmiura/core/policies/engine.py`.
- Mantenimiento de `openmiura/core/policy.py` como shim de compatibilidad.
- Centralización de permisos y resolución de contexto broker en `openmiura/application/auth/service.py`.
- Eliminación de la matriz `_ROLE_PERMISSIONS` y del cálculo duplicado desde `openmiura/channels/http_broker.py`.

## Estado del roadmap

Este cambio cae dentro de la **FASE 1 — Arquitectura, contratos y posicionamiento**, concretamente en:

- modelo unificado de permisos
- contratos más limpios para evolución futura
- preparación del broker HTTP v1 antes de trocearlo por verticales

## Siguiente paso estricto del roadmap

El siguiente movimiento es **PR3 — trocear broker HTTP por verticales** sin cambiar el contrato externo `/broker/*`.
