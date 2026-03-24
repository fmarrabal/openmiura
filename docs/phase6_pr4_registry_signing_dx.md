# FASE 6 PR4 — firma/verificación fuerte del registry, políticas por tenant y cierre DX

## Objetivo

Cerrar la FASE 6 llevando el registry privado a un nivel más enterprise y dejando la DX de extensiones lista para uso interno serio.

## Qué se ha implementado

### 1. Firma y verificación más fuerte del registry

Se añade firma HMAC-SHA256 sobre metadatos inmutables de la publicación:

- namespace
- name
- version
- kind
- submitted_by
- created_at
- package checksum
- manifest checksum
- contract_version

Además del checksum del árbol completo del paquete, ahora se conserva también un checksum específico de `manifest.yaml`.

Cada `RegistryEntry` pasa a incluir:

- `signature`
- `signature_algorithm`
- `signer_key_id`
- `manifest_checksum`

### 2. Gestión de claves del registry

El `registry init` crea la estructura de claves y una clave por defecto.

Se añade:

- `generate_signing_key(...)`
- `list_signing_keys(...)`
- CLI `openmiura registry keygen`

### 3. Políticas de instalación por tenant

Se introduce `TenantInstallPolicy` y almacenamiento persistente en `install_policies.json`.

Capacidades:

- `allowed_namespaces`
- `allowed_kinds`
- `allowed_extensions`
- `blocked_extensions`
- `allowed_submitters`
- `allowed_statuses`
- `min_required_approvals`
- `require_signature`
- `require_approved`
- `require_compatibility`

Se añaden métodos:

- `set_install_policy(...)`
- `get_install_policy(...)`
- `explain_install_policy(...)`

### 4. Instalación controlada

`install(...)` ahora evalúa:

- aprobación requerida
- policy del tenant consumidor
- checksum del paquete
- checksum del manifest
- firma válida
- compatibilidad declarada

Se soporta contexto de instalación:

- `tenant_id`
- `workspace_id`

### 5. Cierre DX

Se añade:

- `openmiura sdk quickstart`
- documentación nueva:
  - `docs/extensions_sdk.md`
  - `docs/extensions_registry.md`
- actualización del índice de documentación
- README generado por scaffold más orientado al flujo real de publicación, verificación e instalación

## Corrección relevante realizada durante la ronda

La firma se estaba invalidando tras un `approve(...)` porque el payload firmado incluía `status`, que es mutable dentro del workflow de revisión.

Se corrige eliminando `status` del payload firmado y dejando la firma anclada solo a metadatos inmutables de publicación.

## Resultado

Con esta ronda, la FASE 6 queda cerrada con:

- SDK oficial usable
- scaffolding completo
- harness contractual y de seguridad
- registry privado con revisión formal
- firma y verificación más fuerte
- políticas de instalación por tenant
- cierre razonable de DX/documentación
