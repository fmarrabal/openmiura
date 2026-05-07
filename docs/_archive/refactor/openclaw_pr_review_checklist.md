# Checklist de revisión de PRs para `openmiura/application/openclaw`

Usa esta checklist en cualquier PR que toque el árbol `openmiura/application/openclaw`.

## 1. Arquitectura y responsabilidad

- [ ] El cambio no vuelve a usar `scheduler.py` como contenedor de utilidades transversales.
- [ ] La lógica nueva vive en el módulo de dominio correcto.
- [ ] Si se introduce un helper reusable, se ha colocado en un módulo transversal y no como copia local.
- [ ] No se ha creado un módulo nuevo sin una frontera funcional clara.

## 2. Tiempo y calendarios

- [ ] No se ha reimplementado lógica temporal fuera de `temporal_windows.py`.
- [ ] Timezones, clocks y ventanas recurrentes usan helpers comunes.
- [ ] No hay fallback silencioso nuevo a UTC sin visibilidad explícita.

## 3. Jobs

- [ ] No se ha reintroducido job orchestration repetida fuera de `job_family_common.py`.
- [ ] La lógica operativa no depende de listados truncados.
- [ ] Cualquier post-run bookkeeping reutiliza helpers comunes o mantiene semántica equivalente validada.

## 4. Runtime context

- [ ] No se ha añadido acceso directo innecesario a `get_runtime(...)` si `runtime_context.py` cubre el caso.
- [ ] El shape de `detail/runtime/runtime_summary/scope` permanece consistente.

## 5. Approvals

- [ ] No se crean approvals nuevos sin revisar `approval_common.py`.
- [ ] `workflow_id` y `step_id` siguen una semántica clara y estable.
- [ ] No se introduce bootstrap duplicado de approvals.

## 6. Explainability y analytics

- [ ] No se añaden shapes ad hoc que dupliquen `governance_explainability.py`.
- [ ] `reason_counts`, `analytics` y `summary` mantienen consistencia con el resto del sistema.

## 7. Limpieza técnica

- [ ] No quedan imports muertos.
- [ ] No se reintroducen builders o decorators repetidos.
- [ ] No se arrastran `__pycache__`, `.pyc`, `.pyo` o `.pytest_cache` al bundle.

## 8. Validación

- [ ] El PR incluye tests focalizados del bloque tocado.
- [ ] Hay regresión mínima del flujo consumidor.
- [ ] Si cambia el shape de salida, hay validación explícita de compatibilidad.
