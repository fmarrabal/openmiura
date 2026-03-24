# Auditoría round 5 — cierre de FASE 4 PR2

## Estado general

Se ha retomado el árbol limpio posterior a FASE 4 PR1 y se ha implementado el siguiente paso del roadmap dentro de FASE 4:

- **PR2 — policy engine formal unificado**

## Qué se ha auditado

- compatibilidad del motor de políticas previo
- integración del runtime de tools con scopes enterprise
- integración del Secret Broker con policy formal
- surface de explainability por admin API
- regresión completa sobre todas las fases ya cerradas

## Incidencias corregidas en esta ronda

### 1. Limitación estructural del policy engine
El engine existente seguía siendo esencialmente un motor de tools legacy.

Problema real:
- no había un modelo formal reutilizable para memory, secrets, channels y approvals
- no existía traza explainable homogénea
- el runtime de tools no propagaba scope suficiente a la evaluación

Corrección aplicada:
- ampliación del engine con decisiones y trazas formales
- nuevas familias de reglas
- evaluación con `tenant/workspace/environment/user_role`

### 2. Falta de enforcement formal sobre secretos
El Secret Broker validaba solo la ref local.

Problema real:
- el gobierno centralizado de secretos no podía imponerse desde la policy declarativa

Corrección aplicada:
- integración opcional del `PolicyEngine` dentro de `SecretBroker`
- denegación por policy aunque la ref local permita el uso

### 3. Falta de explainability operativa para políticas
No existía un endpoint admin formal para simular / explicar decisiones.

Corrección aplicada:
- nuevo endpoint `POST /admin/policies/explain`
- auditoría del uso del endpoint
- inclusión de firma de políticas en status snapshot

## Verificación

- `pytest -q` → **OK**
- `python -m compileall -q app.py openmiura tests` → **OK**

## Conclusión

A estas alturas:

- **FASE 1**: cerrada
- **FASE 2**: cerrada
- **FASE 3**: cerrada
- **FASE 4**: ya tiene base real en:
  - Secret Broker
  - zero-secret redaction
  - policy engine formal unificado
  - explainability básica de seguridad por admin API

## Próximo paso sugerido

Seguir con **FASE 4 PR3 — sandboxing por perfiles** para cerrar el carril:

- policy → sandbox profile → execution limits → audit / explainability
