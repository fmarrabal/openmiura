# Guía de backup y restore

openMiura soporta backup y restore tanto para SQLite como para PostgreSQL.

## 1. SQLite

SQLite es la opción por defecto y la más cómoda para un entorno casero.

### Backup

```bash
openmiura db backup --config configs/
```

El backup se guarda en el directorio configurado en:

```yaml
storage:
  backup_dir: data/backups
```

### Restore

```bash
openmiura db restore --config configs/ --backup data/backups/openmiura-YYYYMMDD-HHMMSS.sqlite3
```

### Buenas prácticas

- haz backup antes de migrar o hacer rollback
- conserva al menos varias generaciones
- prueba el restore en una copia de trabajo, no sobre la instalación principal

## 2. PostgreSQL

Cuando `storage.backend=postgresql`, openMiura usa utilidades del sistema.

### Requisitos

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

## 3. Estrategia recomendada

### Entorno casero

- SQLite
- backup diario o antes de cambios importantes
- copia adicional fuera de la carpeta del proyecto

### Entorno serio

- PostgreSQL
- backup automatizado diario
- retención por política
- restauración de prueba al menos una vez al mes

## 4. Qué incluir en un plan de recuperación

- backup de base de datos
- copia de `configs/`
- copia de `skills/` si personalizas skills
- `.env` guardado de forma segura
- inventario de tokens y secretos vigentes

## 5. Validación de restore

Tras restaurar, comprueba:

- login admin
- listado de sesiones
- búsqueda de memoria
- eventos de auditoría
- tools y agentes visibles
- UI operativa
