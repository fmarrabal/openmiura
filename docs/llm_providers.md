# Guía de providers LLM

openMiura soporta varios proveedores para chat y tool-calling.

## 1. Ollama

Ideal para uso local o doméstico.

Configuración típica:

```yaml
llm:
  provider: ollama
  base_url: http://127.0.0.1:11434
  model: qwen2.5:7b-instruct
```

Ventajas:

- sin coste por token en API externa
- privacidad local
- buena opción para laboratorio y pruebas

## 2. OpenAI

Configuración típica:

```yaml
llm:
  provider: openai
  base_url: https://api.openai.com/v1
  model: gpt-4.1-mini
  api_key_env_var: OPENMIURA_LLM_API_KEY
```

Exporta la clave:

```bash
export OPENMIURA_LLM_API_KEY=...
```

## 3. Anthropic / Claude

```yaml
llm:
  provider: anthropic
  base_url: https://api.anthropic.com
  model: claude-3-5-sonnet-latest
  api_key_env_var: OPENMIURA_LLM_API_KEY
  anthropic_version: 2023-06-01
```

## 4. Kimi

openMiura lo trata como proveedor compatible con la forma OpenAI.

```yaml
llm:
  provider: kimi
  base_url: https://api.moonshot.ai/v1
  model: kimi-k2-0905-preview
  api_key_env_var: OPENMIURA_LLM_API_KEY
```

## 5. Embeddings

Los embeddings pueden seguir usando un backend distinto del chat.

Ejemplo:

```yaml
memory:
  embed_base_url: http://127.0.0.1:11434
  embed_model: nomic-embed-text
```

Eso permite, por ejemplo:

- chat en OpenAI o Claude
- embeddings locales en Ollama

## 6. Diagnóstico

```bash
openmiura doctor --config configs/
```

El doctor comprueba:

- provider configurado
- presencia de API key en providers remotos
- Ollama reachable cuando aplica

## 7. Recomendación práctica

- casa/laboratorio: Ollama
- trabajo mixto: chat remoto + embeddings locales
- producción: proveedor remoto bien monitorizado + fallback planificado
