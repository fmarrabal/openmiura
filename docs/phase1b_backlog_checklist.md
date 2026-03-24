# openMiura — backlog ejecutable tras PR1

## Estado alcanzado

PR1 ya está aplicado en este repositorio:

- PR2 auth/policy unificado ya está aplicado parcialmente y estabilizado en código.

- `application/admin`, `application/memory`, `application/sessions`
- `interfaces/http/app.py`
- `interfaces/http/routes/admin.py`
- `infrastructure/bootstrap/container.py`
- `core/contracts/admin.py`
- `endpoints/admin.py` como shim de compatibilidad

La suite actual pasa completa sobre este estado.

## Siguiente bloque recomendado

### PR2 — auth / policy unificado

#### Prioridad alta

- [x] Crear `openmiura/application/auth/__init__.py`
- [x] Crear `openmiura/application/auth/service.py`
- [x] Crear `openmiura/core/auth/models.py`
- [ ] Crear `openmiura/core/auth/contracts.py`
- [x] Crear `openmiura/core/policies/engine.py`
- [x] Crear `openmiura/core/policies/models.py`
- [x] Localizar checks duplicados de permisos en `openmiura/channels/http_broker.py`
- [x] Mover la evaluación de permisos a un servicio único consumido desde broker y endpoints
- [x] Mantener compatibilidad observable en respuestas y códigos HTTP

#### Tests a tocar o añadir

- [x] `tests/test_http_broker.py`
- [x] `tests/test_terminal_tool_permissions.py`
- [x] `tests/test_phase4_token_metrics.py`
- [ ] añadir tests de precedencia allow/deny
- [ ] añadir tests de auditoría de decisiones de autorización

#### Criterio de aceptación

- [x] no quedan matrices de permisos relevantes embebidas en rutas del broker
- [x] la autorización sale de un punto único reutilizable
- [x] la suite actual sigue pasando

---

### PR3 — trocear broker HTTP

#### Prioridad alta

- [x] Crear `openmiura/interfaces/broker/__init__.py`
- [x] Crear `openmiura/interfaces/broker/router.py`
- [x] Crear `openmiura/interfaces/broker/schemas.py`
- [x] Crear `openmiura/interfaces/broker/routes/auth.py`
- [x] Crear `openmiura/interfaces/broker/routes/chat.py`
- [x] Crear `openmiura/interfaces/broker/routes/tools.py`
- [ ] Crear `openmiura/interfaces/broker/routes/terminal.py`
- [x] Crear `openmiura/interfaces/broker/routes/admin.py`
- [ ] Crear `openmiura/interfaces/broker/routes/sessions.py`
- [x] Dejar `openmiura/channels/http_broker.py` como fachada o shim temporal
- [ ] Extraer helpers internos del broker a módulos propios

#### Tests a tocar o añadir

- [x] `tests/test_http_broker.py`
- [ ] `tests/test_phase2_beta.py`
- [ ] `tests/test_phase2_e2e.py`
- [ ] `tests/test_phase5_ui_auth_stream_admin.py`

#### Criterio de aceptación

- [x] `http_broker.py` deja de ser el monolito funcional principal
- [x] las rutas del broker delegan en application
- [ ] el prefijo y contratos actuales siguen siendo compatibles


---

### PR4 — contratos estables de extensibilidad

#### Prioridad alta

- [x] Crear `openmiura/extensions/__init__.py`
- [x] Crear `openmiura/extensions/loader.py`
- [x] Crear `openmiura/extensions/sdk/__init__.py`
- [x] Crear `openmiura/extensions/sdk/manifests.py`
- [x] Crear `openmiura/extensions/sdk/context.py`
- [x] Crear contratos públicos para tool, skill, provider, channel, storage, auth y observability
- [x] Crear namespaces estables `openmiura/extensions/tools|skills|providers|channels|storage|auth|observability`
- [x] Añadir bridge desde `SkillManifest` a manifest público del SDK
- [x] Documentar el contrato y ejemplo de manifest

#### Tests a tocar o añadir

- [x] `tests/unit/test_extension_sdk.py`
- [x] mantener `tests/unit/test_skills.py`

#### Criterio de aceptación

- [x] una extensión nueva puede definirse sin importar módulos privados del broker o gateway
- [x] existe un manifest común versionado
- [x] existen protocolos públicos mínimos por tipo de extensión
- [x] la suite actual sigue pasando

---

### PR4 — chat orchestration

#### Prioridad alta

- [ ] Crear `openmiura/application/chat/__init__.py`
- [ ] Crear `openmiura/application/chat/service.py`
- [ ] Crear `openmiura/application/chat/orchestrator.py`
- [ ] Crear `openmiura/application/tools/__init__.py`
- [ ] Crear `openmiura/application/tools/service.py`
- [ ] Mover responsabilidades desde `openmiura/pipeline.py`
- [ ] Reducir acoplamiento de `openmiura/core/agent_runtime.py`
- [ ] Clarificar el papel de `openmiura/core/router.py`
- [ ] Separar contrato/registro/ejecución en `openmiura/tools/runtime.py`

#### Tests a tocar o añadir

- [ ] `tests/test_agent_tool_loop.py`
- [ ] `tests/test_router.py`
- [ ] `tests/test_tool_confirmation.py`
- [ ] `tests/test_pending_confirmations.py`
- [ ] `tests/test_status_command.py`

#### Criterio de aceptación

- [ ] el caso de uso de chat existe como servicio explícito
- [ ] tools y confirmaciones dejan de depender del flujo legado en bloque
- [ ] la respuesta observable del chat no cambia

---

### PR5 — Slack / Telegram por capas

#### Prioridad alta-media

- [ ] Crear `openmiura/interfaces/channels/slack/routes.py`
- [ ] Crear `openmiura/interfaces/channels/slack/translator.py`
- [ ] Crear `openmiura/interfaces/channels/telegram/routes.py`
- [ ] Crear `openmiura/interfaces/channels/telegram/translator.py`
- [ ] Crear `openmiura/application/channels/service.py`
- [ ] Mover verificación de firma Slack a infraestructura dedicada
- [ ] Mantener `openmiura/endpoints/slack.py` y `openmiura/endpoints/telegram.py` como shims temporales

#### Tests a tocar o añadir

- [ ] `tests/test_slack_integration.py`
- [ ] `tests/test_telegram_integration.py`
- [ ] `tests/test_identity_cross_channel.py`
- [ ] `tests/test_identity_cross_channel_validation.py`

#### Criterio de aceptación

- [ ] el transporte de canal queda fino
- [ ] la traducción a comandos internos queda explícita
- [ ] no se rompe el comportamiento multicanal actual

---

### PR6 — persistencia e infraestructura

#### Prioridad alta-media

- [ ] Crear `openmiura/infrastructure/persistence/__init__.py`
- [ ] Crear `openmiura/infrastructure/persistence/db.py`
- [ ] Crear `openmiura/infrastructure/persistence/sqlite/audit_store.py`
- [ ] Crear `openmiura/infrastructure/persistence/postgres/audit_store.py`
- [ ] Crear `openmiura/core/memory/contracts.py`
- [ ] Trocear `openmiura/core/audit.py` por responsabilidades
- [ ] Mover `openmiura/core/db.py` fuera de core
- [ ] Reducir acoplamiento entre `core/memory.py` y `audit.py`

#### Tests a tocar o añadir

- [ ] `tests/test_audit.py`
- [ ] `tests/test_db_migrations.py`
- [ ] `tests/test_memory.py`
- [ ] `tests/test_memory_clean_script.py`

#### Criterio de aceptación

- [ ] la persistencia concreta deja de vivir en `core`
- [ ] application depende de contratos, no de sqlite directo
- [ ] el repositorio queda listo para entrar después en multi-tenant serio

---

## Regla operativa para las siguientes PRs

En todas las PRs siguientes se mantiene esta secuencia:

1. tests de caracterización
2. extracción de servicio en `application`
3. mover router o transporte a `interfaces/*`
4. dejar shim legacy
5. pasar la suite completa

## Meta para abrir la verdadera fase enterprise

Se considerará listo para pasar a multi-tenant / workspace / SSO cuando:

- [ ] `app.py` sea un shim mínimo
- [ ] `http_broker.py` esté partido por verticales
- [ ] auth/policy esté unificado
- [ ] `gateway.py` quede como fachada temporal o se reduzca al mínimo
- [ ] `audit/db` estén ya claramente en infraestructura
