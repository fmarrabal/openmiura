# Troubleshooting

## 1. `openmiura doctor` falla con config no encontrada

Comprueba:

```bash
openmiura doctor --config configs/
```

Si `--config` apunta a un directorio, openMiura busca `openmiura.yaml` dentro.

## 2. Error con `cryptography`

Si activas Context Vault y no tienes instalada la dependencia:

```bash
pip install cryptography
```

Con Vault desactivado, openMiura no debería necesitarla para arrancar.

## 3. Error con `prometheus_client`

Si no lo tienes instalado, openMiura usa un fallback básico para `/metrics`, pero para operación real conviene instalar:

```bash
pip install prometheus-client
```

## 4. Error con `mcp`

Para usar el servidor MCP:

```bash
pip install mcp
```

## 5. En Windows, `terminal_exec` con `echo` o `dir`

En Windows esos comandos son built-ins de `cmd.exe`. openMiura ya incluye una ruta compatible, pero si falla revisa:

- allowlist del rol
- `allow_shell`
- `allow_shell_metacharacters`

## 6. El chat streaming o SSE se cortan detrás del proxy

Revisa:

- `proxy_buffering off` en Nginx
- timeouts del proxy
- cabeceras `X-Forwarded-*`

## 7. `403 CSRF validation failed`

Si usas auth por cookie:

- comprueba que la cookie CSRF existe
- envía `X-CSRF-Token`
- revisa `OPENMIURA_AUTH_CSRF_ENABLED`
- revisa `OPENMIURA_AUTH_COOKIE_SECURE` si estás en HTTP local

## 8. `429 Rate limit exceeded`

Revisa:

- `broker.rate_limit_per_minute`
- `broker.auth_rate_limit_per_minute`

Si estás probando desde scripts o CI local, quizá estás reusando siempre la misma IP o token.

## 9. El provider LLM remoto no responde

Comprueba:

- `OPENMIURA_LLM_API_KEY`
- `llm.base_url`
- `llm.model`
- conectividad saliente

## 10. Migraciones o rollback fallan

Haz primero un backup:

```bash
openmiura db backup --config configs/
```

Luego comprueba la versión:

```bash
openmiura db version --config configs/
```

## 11. El login admin no funciona

Comprueba:

- `OPENMIURA_UI_ADMIN_USERNAME`
- `OPENMIURA_UI_ADMIN_PASSWORD`
- que el bootstrap se haya ejecutado sobre la DB correcta

## 12. La memoria no devuelve lo esperado

Revisa:

- `memory.enabled`
- `memory.embed_model`
- backend de embeddings disponible
- que la base de datos restaurada sea la correcta

## 13. Slack / Telegram / Discord no responden

Verifica tokens, firma de Slack, permisos del bot y que el canal esté habilitado en config.

## 14. Grafana o Alertmanager no levantan

Comprueba:

- `docker compose --profile observability up --build`
- variables de entorno de alerta
- que no haya puertos 3000, 9090 o 9093 ocupados
