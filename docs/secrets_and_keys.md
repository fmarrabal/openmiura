# Secrets and keys

> Status: `beta`. openMiura's guarantees (a tamper-evident, signed audit trail
> and signature-grade approvals) are only as strong as the keys behind them.
> This page lists every secret an operator manages, how to set it, and how to
> back it up and rotate it. **Never commit secrets to the repo or an image.**

## At a glance

| Secret | Env var | Used for | If unset |
|---|---|---|---|
| Admin API token | `OPENMIURA_ADMIN_TOKEN` (or `admin.token` in config) | Authenticating `/admin/*` calls | admin API refuses privileged calls |
| UI admin login | `OPENMIURA_UI_ADMIN_USERNAME` / `OPENMIURA_UI_ADMIN_PASSWORD` | Broker login for the web UIs | login disabled |
| Evidence signing key | `OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_B64` / `_PEM_PATH`, or `OPENMIURA_EVIDENCE_SIGNING_SEED` | ed25519-signing evidence packs & approvals | falls back to the **public dev seed** — signatures are marked NON-authoritative |
| TOTP key-encryption key | `OPENMIURA_OTP_KEK` | Encrypting enrolled TOTP secrets at rest | TOTP enrolment/verification fail closed |
| Vault passphrase | `OPENMIURA_VAULT_PASSPHRASE` (with `OPENMIURA_VAULT_ENABLED`) | Local encrypted secret storage | vault disabled |

## Evidence signing key

Evidence packs and signature-grade approvals are signed with an ed25519 key.
Configure a **real** key in production (any one of):

```bash
# a base64-encoded PEM private key
export OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_B64="$(base64 -w0 signing_key.pem)"
# ...or a path to the PEM
export OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_PATH=/secrets/signing_key.pem
# ...or a high-entropy operator seed (derives the key)
export OPENMIURA_EVIDENCE_SIGNING_SEED="$(openssl rand -hex 32)"
```

If none is set, openMiura signs with a **public, source-reproducible
development seed** and stamps the signature `dev_signing_key: true`.
`openmiura verify` reports such packs as **non-authoritative** (exit `2`) — it
re-derives the dev key by fingerprint, so the flag cannot be stripped. KMS/HSM
providers are also supported (`OPENMIURA_EVIDENCE_KMS_*`, `_HSM_*`).

Bind a pack to a *known* signer at verification time with
`openmiura verify pack.zip --trust-anchor signer.pem`.

**Backup:** store the signing key (or seed) in a secret manager, separate from
the database backups. Losing it means new packs cannot be signed with the same
identity; leaking it lets anyone forge authoritative-looking packs. **Rotate**
by issuing a new key and distributing its public key / fingerprint to verifiers
as a new trust anchor; previously signed packs remain verifiable against the
old public key.

## TOTP key-encryption key (KEK)

Signature-grade approvals can require a TOTP second factor. The per-user TOTP
secret is **encrypted at rest** with a key derived from `OPENMIURA_OTP_KEK`:

```bash
export OPENMIURA_OTP_KEK="$(openssl rand -hex 32)"
```

With no KEK configured, TOTP enrolment and verification **fail closed** (a
second factor stored in the clear is not a second factor). **Rotate carefully:**
the KEK decrypts existing enrolments, so changing it invalidates every enrolled
secret — re-enrol users after a rotation. Back up the KEK alongside (but stored
separately from) the database.

## Admin token and UI login

```bash
export OPENMIURA_ADMIN_TOKEN="$(openssl rand -hex 24)"
export OPENMIURA_UI_ADMIN_USERNAME=admin
export OPENMIURA_UI_ADMIN_PASSWORD="$(openssl rand -hex 16)"
```

Rotate the admin token by setting a new value and restarting; existing API
tokens minted through the admin API are unaffected and are revoked/rotated via
the admin API itself.

## Vault passphrase

The optional local secret vault (`OPENMIURA_VAULT_ENABLED=true`) encrypts
stored secrets with `OPENMIURA_VAULT_PASSPHRASE`. Treat it like the signing key:
back it up separately, and note that rotating it re-keys the vault contents.

## Backup checklist

Back these up **separately from the database** (so a single leaked backup does
not contain both the data and the keys that protect it):

- the evidence signing key / seed,
- `OPENMIURA_OTP_KEK`,
- the vault passphrase (if the vault is enabled),
- the admin token and UI credentials.

See also: [Backup and restore](backup_restore.md),
[Upgrades](upgrades.md), [Configuration profiles](configuration_profiles.md).
