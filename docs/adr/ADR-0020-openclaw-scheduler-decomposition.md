# ADR-0020 — Descomposición de `scheduler.py` en módulos especializados

## Estado
Aceptado

## Contexto
`Scheduler.py` acumuló con el tiempo lógica de baseline rollout, governance bundles, runtime alerts, evidencias, jobs y helpers transversales. Esto elevó el riesgo de regresión y el coste de revisión.

## Decisión
Descomponer progresivamente `scheduler.py` en módulos especializados por dominio y mantener el scheduler principalmente como orquestador.

## Alternativas consideradas
- Mantener `scheduler.py` y solo mejorar comentarios.
- Reescribir completamente el servicio en una única iteración.
- Extraer solo helpers sin separar dominios.

## Consecuencias
- menor acoplamiento estructural;
- mejor localización de cambios;
- más puntos de extensión claros;
- necesidad de gobernar mejor mixins y composición.

## Riesgos aceptados
- aumento del número de módulos;
- necesidad de vigilar imports y dependencias cruzadas.
