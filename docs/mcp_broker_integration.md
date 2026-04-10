# Guía de integración MCP y broker HTTP

openMiura ofrece dos capas de integración externa:

- **MCP** para interoperar con clientes compatibles
- **broker HTTP** para integraciones directas y UI

## 1. Cuándo usar MCP

Usa MCP si quieres conectar openMiura con clientes como:

- Claude Desktop
- Cursor
- otros clientes compatibles con Model Context Protocol

### Arranque por STDIO

```bash
openmiura mcp stdio --config configs/
```

### Arranque por SSE

```bash
openmiura mcp sse --config configs/
```

Configura:

```yaml
mcp:
  enabled: true
  host: 127.0.0.1
  port: 8091
  sse_path: /mcp
```

## 2. Qué expone MCP

- tools registradas en openMiura
- recurso de memoria `memory://search/{query}`
- una tool `chat` para probar el pipeline completo

## 3. Cuándo usar el broker HTTP

Usa el broker si quieres:

- integrar otra app web o backend
- construir un frontend propio
- hacer tool-calling directo por HTTP
- gestionar sesiones, confirmaciones y auth desde tu propia capa

Configura:

```yaml
broker:
  enabled: true
  host: 127.0.0.1
  port: 8081
  base_path: /broker
```

## 4. Endpoints más importantes del broker

- `GET /broker/health`
- `POST /broker/chat`
- `POST /broker/chat/stream`
- `GET /broker/agents`
- `GET /broker/agents/{agent_id}/tools`
- `POST /broker/tools/call`
- `GET /broker/memory/search?q=...`
- `GET /broker/sessions`
- `GET /broker/sessions/{session_id}/messages`
- `GET /broker/confirmations`
- `POST /broker/confirmations/{session_id}/confirm`
- `POST /broker/confirmations/{session_id}/cancel`
- `GET /broker/metrics/summary`
- `GET /broker/stream/live`

## 5. Seguridad del broker

Puedes protegerlo con:

- `Authorization: Bearer ...`
- token estático de broker
- sesiones auth de UI
- cookies con CSRF en navegador

## 6. Estrategia recomendada

- UI propia o automatización HTTP: broker
- cliente MCP externo: MCP
- operación híbrida: ambos activados
