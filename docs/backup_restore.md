# Backup and restore guide

openMiura supports backup and restore for both SQLite and PostgreSQL.

## 1. SQLite

SQLite is the default option and the most convenient for a home setup.

### Backup

```bash
openmiura db backup --config configs/
```

The backup is written to the directory configured in:

```yaml
storage:
  backup_dir: data/backups
```

### Restore

```bash
openmiura db restore --config configs/ --backup data/backups/openmiura-YYYYMMDD-HHMMSS.sqlite3
```

### Best practices

- back up before migrating or rolling back
- keep at least several generations
- test the restore on a working copy, not on the primary installation

## 2. PostgreSQL

When `storage.backend=postgresql`, openMiura uses system utilities.

### Requirements

- `pg_dump`
- `psql`

### Backup

```bash
openmiura db backup --config configs/
```

### Restore

```bash
openmiura db restore --config configs/ --backup data/backups/openmiura-YYYYMMDD-HHMMSS.sql
```

## 3. Recommended strategy

### Home environment

- SQLite
- daily backup, or before significant changes
- an extra copy outside the project folder

### Serious environment

- PostgreSQL
- automated daily backup
- retention by policy
- a test restore at least once a month

## 4. What to include in a recovery plan

- database backup
- a copy of `configs/`
- a copy of `skills/` if you customize skills
- `.env` stored securely
- an inventory of active tokens and secrets

## 5. Restore validation

After restoring, check:

- admin login
- session listing
- memory search
- audit events
- tools and agents visible
- UI operational
