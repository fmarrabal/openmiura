# Troubleshooting

## 1. `openmiura doctor` fails with config not found

Check:

```bash
openmiura doctor --config configs/
```

If `--config` points to a directory, openMiura looks for `openmiura.yaml` inside
it.

## 2. `cryptography` error

If you enable the Context Vault and the dependency is not installed:

```bash
pip install cryptography
```

With the Vault disabled, openMiura should not need it to start.

## 3. `prometheus_client` error

If it is not installed, openMiura uses a basic fallback for `/metrics`, but for
real operation you should install:

```bash
pip install prometheus-client
```

## 4. `mcp` error

To use the MCP server:

```bash
pip install mcp
```

## 5. On Windows, `terminal_exec` with `echo` or `dir`

On Windows those commands are `cmd.exe` built-ins. openMiura already includes a
compatible path, but if it fails, check:

- the role allowlist
- `allow_shell`
- `allow_shell_metacharacters`

## 6. Streaming chat or SSE cuts off behind the proxy

Check:

- `proxy_buffering off` in Nginx
- proxy timeouts
- the `X-Forwarded-*` headers

## 7. `403 CSRF validation failed`

If you use cookie auth:

- check that the CSRF cookie exists
- send `X-CSRF-Token`
- check `OPENMIURA_AUTH_CSRF_ENABLED`
- check `OPENMIURA_AUTH_COOKIE_SECURE` if you are on local HTTP

## 8. `429 Rate limit exceeded`

Check:

- `broker.rate_limit_per_minute`
- `broker.auth_rate_limit_per_minute`

If you are testing from scripts or local CI, you may be reusing the same IP or
token every time.

## 9. The remote LLM provider does not respond

Check:

- `OPENMIURA_LLM_API_KEY`
- `llm.base_url`
- `llm.model`
- outbound connectivity

## 10. Migrations or rollback fail

Take a backup first:

```bash
openmiura db backup --config configs/
```

Then check the version:

```bash
openmiura db version --config configs/
```

## 11. Admin login does not work

Check:

- `OPENMIURA_UI_ADMIN_USERNAME`
- `OPENMIURA_UI_ADMIN_PASSWORD`
- that the bootstrap ran against the correct DB

## 12. Memory does not return what you expect

Check:

- `memory.enabled`
- `memory.embed_model`
- an available embeddings backend
- that the restored database is the correct one

## 13. Slack / Telegram / Discord do not respond

Verify tokens, the Slack signature, bot permissions, and that the channel is
enabled in the config.

## 14. Grafana or Alertmanager do not start

Check:

- `docker compose --profile observability up --build`
- the alert environment variables
- that ports 3000, 9090, or 9093 are not already in use
