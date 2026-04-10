# Configuración por canal

Esta guía complementa `README.md` con ejemplos listos para copiar en `configs/openmiura.yaml`.

## Reglas generales

- Mantén tokens y secretos fuera del YAML siempre que sea posible.
- Usa variables de entorno `${OPENMIURA_...}` o `env:OPENMIURA_...`.
- Para desarrollo local, empieza con `python -m openmiura doctor --config configs/openmiura.yaml`.
- Si vas a usar Discord, instala el extra: `python -m pip install -e ".[discord]"`.

## Telegram

### Config mínima

```yaml
telegram:
  enabled: true
  bot_token: "${OPENMIURA_TELEGRAM_BOT_TOKEN}"
  webhook_secret: "${OPENMIURA_TELEGRAM_WEBHOOK_SECRET}"
  allowlist:
    enabled: false
    user_ids: []
    chat_ids: []
    allow_groups: false
    deny_message: "⛔ No autorizado. Pide acceso al administrador."
```

### Config recomendada para producción

```yaml
telegram:
  enabled: true
  bot_token: "${OPENMIURA_TELEGRAM_BOT_TOKEN}"
  webhook_secret: "${OPENMIURA_TELEGRAM_WEBHOOK_SECRET}"
  allowlist:
    enabled: true
    user_ids: [123456789]
    chat_ids: []
    allow_groups: false
    deny_message: "⛔ No autorizado. Contacta con el administrador."
```

### Operación

- Endpoint: `POST /telegram/webhook`
- Cabecera de seguridad: `X-Telegram-Bot-Api-Secret-Token`
- Solo procesa mensajes de texto.
- El worker de polling sigue disponible si no quieres webhook.

## Slack

### Config mínima

```yaml
slack:
  enabled: true
  bot_token: "${OPENMIURA_SLACK_BOT_TOKEN}"
  signing_secret: "${OPENMIURA_SLACK_SIGNING_SECRET}"
  bot_user_id: "${OPENMIURA_SLACK_BOT_USER_ID}"
  reply_in_thread: true
  allowlist:
    enabled: false
    team_ids: []
    channel_ids: []
    allow_im: true
    deny_message: "⛔ No autorizado."
```

### Config recomendada para producción

```yaml
slack:
  enabled: true
  bot_token: "${OPENMIURA_SLACK_BOT_TOKEN}"
  signing_secret: "${OPENMIURA_SLACK_SIGNING_SECRET}"
  bot_user_id: "${OPENMIURA_SLACK_BOT_USER_ID}"
  reply_in_thread: true
  allowlist:
    enabled: true
    team_ids: ["T01234567"]
    channel_ids: ["C01234567", "D01234567"]
    allow_im: true
    deny_message: "⛔ No autorizado. Solicita acceso al workspace."
```

### Operación

- Endpoint: `POST /slack/events`
- Requiere firma HMAC válida (`X-Slack-Request-Timestamp`, `X-Slack-Signature`).
- Soporta `url_verification`, `app_mention` y DMs.
- Deduplica por `event_id`.
- Puede responder en thread.

## Discord

### Config mínima

```yaml
discord:
  enabled: true
  bot_token: "${OPENMIURA_DISCORD_BOT_TOKEN}"
  application_id: "${OPENMIURA_DISCORD_APPLICATION_ID}"
  mention_only: true
  reply_as_reply: true
  slash_enabled: true
  slash_command_name: "miura"
  sync_on_startup: true
  sync_guild_ids: []
  expose_native_commands: true
  include_attachments_in_text: true
  max_attachment_items: 4
  allowlist:
    enabled: false
    allow_user_ids: []
    allow_channel_ids: []
    allow_guild_ids: []
    allow_dm: true
    deny_message: "⛔ No autorizado."
```

### Config recomendada para desarrollo rápido

```yaml
discord:
  enabled: true
  bot_token: "${OPENMIURA_DISCORD_BOT_TOKEN}"
  application_id: "${OPENMIURA_DISCORD_APPLICATION_ID}"
  mention_only: true
  reply_as_reply: true
  slash_enabled: true
  slash_command_name: "miura"
  sync_on_startup: true
  sync_guild_ids: [123456789012345678]
  expose_native_commands: true
  include_attachments_in_text: true
  max_attachment_items: 4
  allowlist:
    enabled: true
    allow_user_ids: []
    allow_channel_ids: []
    allow_guild_ids: [123456789012345678]
    allow_dm: true
    deny_message: "⛔ No autorizado en este servidor."
```

### Operación

- Worker: `python scripts/discord_worker.py`
- Procesa DMs, menciones y slash commands.
- Incluye `/miura`, `/help`, `/status`, `/reset`, `/forget`, `/link`.
- Para que aparezcan los slash commands, invita al bot con scopes `bot` y `applications.commands`.
- Durante desarrollo, sincroniza por guild para que los comandos aparezcan antes.

## Admin API

### Config mínima

```yaml
admin:
  enabled: true
  token: "${OPENMIURA_ADMIN_TOKEN}"
  max_search_results: 100
```

### Operación

- `GET /admin/status`
- `POST /admin/memory/search`
- `POST /admin/memory/delete`
- Autenticación por `Authorization: Bearer ...` o `X-Admin-Token`.

## Ejemplo completo orientado a local

```yaml
server:
  host: "127.0.0.1"
  port: 8081

storage:
  db_path: "data/audit.db"

llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5:7b-instruct"
  timeout_s: 60

memory:
  enabled: true
  embed_model: "nomic-embed-text"

runtime:
  history_limit: 12

telegram:
  enabled: false
  bot_token: "${OPENMIURA_TELEGRAM_BOT_TOKEN}"
  webhook_secret: "${OPENMIURA_TELEGRAM_WEBHOOK_SECRET}"

slack:
  enabled: true
  bot_token: "${OPENMIURA_SLACK_BOT_TOKEN}"
  signing_secret: "${OPENMIURA_SLACK_SIGNING_SECRET}"
  bot_user_id: "${OPENMIURA_SLACK_BOT_USER_ID}"
  reply_in_thread: true

admin:
  enabled: true
  token: "${OPENMIURA_ADMIN_TOKEN}"
  max_search_results: 100
```
