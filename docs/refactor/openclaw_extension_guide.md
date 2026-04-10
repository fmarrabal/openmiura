# Guía de extensión para `openmiura/application/openclaw` tras la fase de refactor

## Objetivo

Esta guía define cómo extender `openmiura/application/openclaw` sin reintroducir duplicación, mezcla de responsabilidades ni un nuevo crecimiento monolítico del scheduler.

## 1. Regla base

`Scheduler.py` debe comportarse principalmente como **orquestador**. No debe volver a convertirse en contenedor de utilidades transversales ni en lugar por defecto para lógica nueva.

## 2. Dónde debe vivir cada tipo de lógica

### Lógica de dominio
Debe vivir en módulos de dominio ya existentes o en uno nuevo si el bloque tiene identidad propia. Ejemplos:
- baseline rollout → `baseline_rollout_*`
- runtime alerts → `runtime_alert_*`
- governance bundles → `alert_governance_bundle_*`

### Helpers transversales
Deben ir a módulos reutilizables si cumplen dos condiciones:
1. sirven a más de un dominio;
2. contienen un patrón repetible y estable.

Ejemplos actuales:
- ventanas temporales → `temporal_windows.py`
- jobs comunes → `job_family_common.py`
- runtime context → `runtime_context.py`
- approvals → `approval_common.py`
- explainability/analytics shape → `governance_explainability.py`

## 3. Cuándo crear un módulo nuevo

Crea un módulo nuevo cuando:
- el bloque tiene semántica propia;
- la lógica supera claramente el uso local de un solo método;
- hay más de un consumidor o previsión razonable de reutilización;
- su separación reduce el riesgo de regresión o mejora la testabilidad.

No crees un módulo nuevo si:
- solo mueve una función aislada sin frontera clara;
- el supuesto helper tiene acoplamiento excesivo con un único flujo;
- la división es puramente cosmética.

## 4. Cómo decidir si algo va en `scheduler.py`

Debe quedarse en `scheduler.py` si:
- es pura orquestación entre varios servicios/módulos;
- coordina secuencias de alto nivel sin aportar lógica reusable;
- necesita ser punto central de composición del servicio.

No debe ir en `scheduler.py` si:
- es un helper reusable;
- es validación temporal;
- es bootstrap de approvals;
- es cálculo de analytics/explainability;
- es manejo genérico de jobs;
- es normalización de policy.

## 5. Reglas para no reintroducir duplicación

- No implementar parseo temporal fuera de `temporal_windows.py`.
- No implementar families de jobs nuevas sin revisar `job_family_common.py`.
- No cargar contexto runtime de forma directa si `runtime_context.py` cubre el caso.
- No crear approvals desde cero si `approval_common.py` cubre el patrón.
- No construir shapes ad hoc de explainability si `governance_explainability.py` ya define el formato.
- No añadir builders de evidence/export duplicados fuera de `evidence_builders.py` salvo caso excepcional justificado.

## 6. Regla de tests

Toda extracción o nueva abstracción en `openclaw` debe acompañarse de:
- tests focalizados del bloque tocado;
- regresión mínima del flujo que consume el helper;
- validación de que el shape de salida no rompe consumidores existentes.

## 7. Deuda remanente aceptada

A día de hoy sigue siendo aceptable:
- cierta semiduplicación entre policies derivadas de `runtime` y `runtime_summary`;
- algunas llamadas directas a `get_runtime(...)` en caminos no críticos;
- algunos jobs especiales aún no totalmente homogeneizados.

Eso no debe servir como excusa para abrir nuevas duplicaciones en áreas ya saneadas.
