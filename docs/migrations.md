# Guía de migraciones

openMiura incluye migraciones formales, versionado de esquema y rollback.

## 1. Conceptos

- la tabla `schema_migrations` guarda la versión aplicada
- las migraciones son idempotentes
- el sistema puede aplicar upgrades y downgrades

## 2. Ver versión de esquema

```bash
openmiura db version --config configs/
```

## 3. Aplicar migraciones

```bash
openmiura db migrate --config configs/
```

Si `storage.auto_migrate=true`, openMiura aplicará las migraciones necesarias al arrancar.

## 4. Rollback formal

Por número de pasos:

```bash
openmiura db rollback --config configs/ --steps 1
```

Hasta una versión concreta:

```bash
openmiura db rollback --config configs/ --to-version 1
```

## 5. Recomendación crítica

Haz siempre un backup antes de migrar o hacer rollback:

```bash
openmiura db backup --config configs/
```

## 6. Flujo seguro de cambio de esquema

1. generar backup
2. revisar versión actual
3. aplicar migración o rollback
4. arrancar `openmiura doctor`
5. comprobar UI, login, memoria y auditoría

## 7. SQLite vs PostgreSQL

### SQLite

Algunos downgrades requieren reconstrucción formal de tablas, porque SQLite no soporta todas las operaciones `ALTER TABLE` con la misma flexibilidad que PostgreSQL.

### PostgreSQL

Los downgrades pueden usar operaciones más directas, como `DROP COLUMN`.

## 8. Cuándo usar rollback

- release defectuosa
- cambio de esquema que rompe compatibilidad
- necesidad de volver a una versión estable

## 9. Cuándo preferir restore en vez de rollback

- corrupción lógica severa
- duda sobre el estado intermedio del esquema
- incidentes operativos donde quieres volver a una instantánea conocida
