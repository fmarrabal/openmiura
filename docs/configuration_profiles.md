# Configuration profiles

openMiura now ships with a **secure-by-default** runtime posture.

That means:
- `web_fetch` does **not** allow every domain unless you opt in.
- `terminal_exec` is **disabled** unless you opt in.
- when `terminal_exec` is enabled in secure profiles, shell mode and metacharacters stay off, and an explicit allowlist is expected.

## Precedence

1. CLI flag `--config`
2. `OPENMIURA_CONFIG`
3. values resolved from the YAML file
4. environment overrides referenced in YAML with the form `env:NOMBRE_VARIABLE|valor_por_defecto`
5. built-in defaults from the Python settings layer

For list-like controls, openMiura also accepts comma-separated environment overrides such as:
- `OPENMIURA_WEB_FETCH_ALLOWED_DOMAINS=api.openai.com,example.org`
- `OPENMIURA_TERMINAL_ALLOWED_COMMANDS=python,echo`

## Baseline profiles

### `ops/env/insecure-dev.env`
Permissive local developer posture. It keeps the old convenience behavior for shell execution and open web access. Use only on a trusted machine.

### `ops/env/secure-default.env`
Recommended baseline for first real deployments. It keeps auth and broker enabled, disables broad web access, and disables terminal execution unless you explicitly relax it.

## Compatibility profiles

### `ops/env/local-dev.env`
Compatibility-friendly local profile for fast laptop setup. Similar to `insecure-dev.env`.

### `ops/env/local-secure.env`
Compatibility-friendly local secure profile. Similar to `secure-default.env` but tuned for a single node.

### `ops/env/demo.env`
Demo profile for screenshots or guided trials. Keeps the system locked down while still being easy to boot.

### `ops/env/production-like.env`
Single-node or small-server baseline intended to sit behind TLS and a reverse proxy. Replace every placeholder before real use.

## Quick start

### Linux/macOS

```bash
cp ops/env/secure-default.env .env
python -m openmiura doctor --config configs/openmiura.yaml
python app.py
```

### Windows PowerShell

```powershell
Copy-Item ops\env\secure-default.env .env
python -m openmiura doctor --config configs/openmiura.yaml
python app.py
```

## Critical variables to review

- `OPENMIURA_ADMIN_TOKEN`
- `OPENMIURA_UI_ADMIN_PASSWORD`
- `OPENMIURA_BROKER_TOKEN`
- `OPENMIURA_VAULT_PASSPHRASE`
- `OPENMIURA_WEB_FETCH_ALLOW_ALL_DOMAINS`
- `OPENMIURA_WEB_FETCH_ALLOWED_DOMAINS`
- `OPENMIURA_TERMINAL_ENABLED`
- `OPENMIURA_TERMINAL_REQUIRE_EXPLICIT_ALLOWLIST`
- `OPENMIURA_TERMINAL_ALLOWED_COMMANDS`
