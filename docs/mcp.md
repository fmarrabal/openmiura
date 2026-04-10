# MCP en openMiura

## Requisitos

```bash
pip install mcp
```

## STDIO

```bash
openmiura mcp stdio --config configs/
```

## SSE

```bash
openmiura mcp sse --config configs/
```

Configura `mcp.enabled: true` en `configs/openmiura.yaml`.

## Claude Desktop / clientes MCP

Ejemplo conceptual de comando local:

```json
{
  "mcpServers": {
    "openmiura": {
      "command": "openmiura",
      "args": ["mcp", "stdio", "--config", "configs/"]
    }
  }
}
```

openMiura expone:
- tools registradas como tools MCP
- recurso `memory://search/{query}` para memoria semántica
- una tool `chat` para probar el pipeline completo
