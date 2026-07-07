# Upgrades

> Status: `beta`. openMiura's database carries a versioned, forward-only
> migration chain. Upgrades are safe when you **back up first** and apply
> migrations deliberately.

## Golden rule: back up before you upgrade

```bash
openmiura db backup --config configs/openmiura.yaml
```

This writes a timestamped copy under the configured `storage.backup_dir`
(default `data/backups`) for SQLite, or runs `pg_dump` for PostgreSQL. Restore
with:

```bash
openmiura db restore --backup data/backups/openmiura-YYYYMMDD-HHMMSS.sqlite3
```

See [Backup and restore](backup_restore.md) for details, and
[Secrets and keys](secrets_and_keys.md) — the signing key / KEK are **not** in
the database and must be backed up separately.

## Upgrade procedure

1. **Check the current versions.**
   ```bash
   openmiura version           # package version
   openmiura db version        # applied schema version vs. available
   ```
2. **Back up** the database (above).
3. **Install the new version.**
   - pip: `pip install --upgrade openmiura`
   - container: `docker pull ghcr.io/fmarrabal/openmiura:X.Y.Z` and recreate the
     container with the same data volume.
4. **Apply migrations.**
   ```bash
   openmiura db migrate --config configs/openmiura.yaml
   ```
   Migrations are additive and idempotent; re-running is safe.
5. **Verify.**
   ```bash
   openmiura doctor
   openmiura db verify-chain      # the audit chain still hashes to its head
   ```

## Rolling back

If a migration causes trouble, roll the schema back to a known version and
restore the pre-upgrade backup if needed:

```bash
openmiura db rollback --config configs/openmiura.yaml --to-version <N>
```

Then reinstall the previous package/image version. Because the hash-chain is
genesis-re-anchored, rows written before a feature existed remain valid; a
restore from backup returns the database to exactly its backed-up state.

## Notes

- **Migrations are forward-only by design**; a rollback undoes schema changes
  where a reversible down-migration exists, but the safe recovery path for data
  is always the pre-upgrade backup.
- Pin to an exact `X.Y.Z` release/image in production and upgrade deliberately,
  one version line at a time.
- The dependency set caps each major version, so a `pip install --upgrade`
  cannot silently pull a breaking major of a signing/crypto dependency.

See also: [Migrations](migrations.md), [Backup and restore](backup_restore.md),
[Container image](container_image.md).
