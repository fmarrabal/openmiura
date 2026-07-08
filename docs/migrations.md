# Migrations guide

openMiura includes formal migrations, schema versioning, and rollback.

## 1. Concepts

- the `schema_migrations` table records the applied version
- migrations are idempotent
- the system can apply upgrades and downgrades

## 2. View the schema version

```bash
openmiura db version --config configs/
```

## 3. Apply migrations

```bash
openmiura db migrate --config configs/
```

If `storage.auto_migrate=true`, openMiura applies the necessary migrations at
startup.

## 4. Formal rollback

By number of steps:

```bash
openmiura db rollback --config configs/ --steps 1
```

Down to a specific version:

```bash
openmiura db rollback --config configs/ --to-version 1
```

## 5. Critical recommendation

Always take a backup before migrating or rolling back:

```bash
openmiura db backup --config configs/
```

## 6. Safe schema-change flow

1. generate a backup
2. review the current version
3. apply the migration or rollback
4. run `openmiura doctor`
5. check the UI, login, memory, and audit

## 7. SQLite vs PostgreSQL

### SQLite

Some downgrades require a formal table rebuild, because SQLite does not support
all `ALTER TABLE` operations with the same flexibility as PostgreSQL.

### PostgreSQL

Downgrades can use more direct operations, such as `DROP COLUMN`.

## 8. When to use rollback

- a faulty release
- a schema change that breaks compatibility
- a need to return to a stable version

## 9. When to prefer restore over rollback

- severe logical corruption
- doubt about the intermediate state of the schema
- operational incidents where you want to return to a known snapshot
