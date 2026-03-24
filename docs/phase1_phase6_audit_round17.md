# Auditoría round 17 — cierre FASE 6

## Alcance auditado

- `openmiura/extensions/sdk/registry.py`
- `openmiura/extensions/sdk/scaffold.py`
- `openmiura/extensions/sdk/__init__.py`
- `openmiura/cli.py`
- documentación SDK/registry
- tests nuevos de firma y políticas

## Hallazgos y correcciones

### 1. Firma rota tras aprobación

**Problema**
La firma de publicación se calculaba incluyendo `status`. Después de `review-start`, `approve` o `deprecate`, la firma dejaba de validar aunque el paquete no hubiese sido alterado.

**Corrección**
Se redefine el payload firmado para incluir solo campos inmutables de publicación.

### 2. Falta de enforcement por tenant consumidor

**Problema**
El registry resolvía publicación, revisión e instalación, pero no existía una política explícita de consumo por tenant.

**Corrección**
Se introduce `TenantInstallPolicy` y evaluación explícita previa a instalar.

### 3. DX insuficiente para el flujo completo

**Problema**
El scaffolding y el harness ya existían, pero faltaba una narrativa corta y operativa para el flujo completo scaffold → test → publish → approve → verify → install.

**Corrección**
Se añade `sdk quickstart` y documentación específica para SDK y registry.

## Validación ejecutada

### Tests dirigidos

```bash
pytest -q tests/test_phase6_* tests/test_phase5_* tests/test_phase4_* tests/test_cli_* tests/unit/test_extension_sdk.py
```

Resultado: **OK**

### Compilación

```bash
python -m compileall -q app.py openmiura tests
```

Resultado: **OK**

## Conclusión

No veo un bloqueo estructural en FASE 6 tras esta ronda. El registry queda claramente más sólido y la experiencia de extensión queda bastante mejor cerrada.
