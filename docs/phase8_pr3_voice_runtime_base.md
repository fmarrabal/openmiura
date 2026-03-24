# openMiura — FASE 8 PR3
## Voice runtime base

## Objetivo
Añadir una base de runtime de voz gobernada para openMiura, con sesiones auditables, transcripción, respuesta hablada, confirmación obligatoria para acciones sensibles y cierre formal de sesión.

## Qué incluye
- Modelo persistente para:
  - `voice_sessions`
  - `voice_transcripts`
  - `voice_outputs`
  - `voice_commands`
- Migración de esquema `11`.
- Servicio de aplicación `VoiceRuntimeService`.
- Endpoints HTTP admin:
  - `GET /admin/voice/sessions`
  - `GET /admin/voice/sessions/{voice_session_id}`
  - `POST /admin/voice/sessions`
  - `POST /admin/voice/sessions/{voice_session_id}/transcribe`
  - `POST /admin/voice/sessions/{voice_session_id}/respond`
  - `POST /admin/voice/sessions/{voice_session_id}/confirm`
  - `POST /admin/voice/sessions/{voice_session_id}/close`
- Endpoints broker equivalentes bajo `/broker/admin/voice/...`.
- Pestaña inicial **Voice Runtime** en la UI para operar sesiones, ver transcripciones, outputs y comandos.

## Modelo funcional
### 1. Inicio de sesión
Se crea una `voice_session` con ámbito multi-tenant (`tenant_id`, `workspace_id`, `environment`), locale y proveedores STT/TTS nominales.

### 2. Transcripción
Cada turno de voz genera una fila en `voice_transcripts` y una evaluación simple del comando detectado.

### 3. Policy enforcement de voz
Se distinguen dos rutas:
- **Nominal**: comandos no sensibles quedan ejecutados y producen respuesta hablada.
- **Sensibles**: comandos como promote, deploy, approve, rollback, send, transfer o delete pasan a `pending_confirmation`.

### 4. Confirmación
La confirmación resuelve el `voice_command`, deja rastro en transcripción y genera un `voice_output` adicional.

### 5. Cierre
La sesión se marca como `closed`, con `closed_at` y metadata de cierre.

## Decisiones de diseño
- PR3 no acopla todavía STT/TTS reales a proveedores externos; deja el runtime listo con proveedores simulados y contratos persistentes.
- La enforcement policy específica de voz se modela como artefacto auditable por comando.
- Las acciones sensibles no se ejecutan a ciegas: primero quedan en espera de confirmación.
- Se mantiene segregación estricta por tenant/workspace/environment.

## Criterios de aceptación cubiertos
- Comando simple transcrito y respondido.
- Acción sensible requiere confirmación.
- Toda interacción queda persistida y auditable.
- Superficie admin y broker disponible.
- UI con base de operación de voz visible.

## Siguiente paso natural
PR4 — App foundation: PWA operativa.
