# Registry privado de extensiones

## Firma y verificación

Cada publicación del registry queda sellada con:

- checksum del paquete completo
- checksum específico de `manifest.yaml`
- firma HMAC-SHA256 con clave local del registry

El flujo mínimo es:

1. `openmiura registry init --root ./registry`
2. `openmiura registry publish ./my-tool --root ./registry --namespace demo`
3. `openmiura registry review-start my-tool 0.1.0 --root ./registry --namespace demo`
4. `openmiura registry approve my-tool 0.1.0 --root ./registry --namespace demo`
5. `openmiura registry verify my-tool 0.1.0 --root ./registry --namespace demo`

Para rotar o crear claves:

- `openmiura registry keygen --root ./registry --key-id default --rotate`

## Políticas de instalación por tenant

El tenant consumidor puede imponer restricciones antes de instalar una extensión.

Campos soportados:

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

Ejemplo:

```bash
openmiura registry policy-set tenant-a \
  --root ./registry \
  --allowed-namespace global \
  --allowed-namespace tenant-a \
  --allowed-kind tool \
  --allowed-kind auth_provider \
  --min-approvals 2
```

Para inspeccionar la decisión antes de instalar:

```bash
openmiura registry policy-explain my-tool \
  --root ./registry \
  --namespace global \
  --tenant tenant-a
```

## Instalación controlada

```bash
openmiura registry install my-tool \
  --root ./registry \
  --namespace global \
  --tenant tenant-a \
  --workspace prod
```

La instalación valida:

- checksum del paquete
- checksum del manifiesto
- firma del paquete
- aprobación requerida
- política del tenant consumidor
- compatibilidad declarada por la extensión
