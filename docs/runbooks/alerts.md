# Runbooks de alertas operativas

## OpenMiuraTargetDown

**Qué significa**
El endpoint `/metrics` de openMiura no está respondiendo al scrape de Prometheus.

**Qué hacer**
1. Verifica que el contenedor o proceso `openmiura` esté levantado.
2. Comprueba `docker compose ps` y los logs de aplicación.
3. Revisa que el puerto 8081 y el reverse proxy sigan publicando `/metrics`.
4. Si hubo despliegue reciente, valida healthcheck, variables de entorno y migraciones.

## OpenMiuraHighErrorRate

**Qué significa**
La tasa de `openmiura_errors_total` está por encima del umbral durante 10 minutos.

**Qué hacer**
1. Abre el dashboard **Operations Overview** y revisa `Errors by type`.
2. Filtra logs por `request_id` y por tipo de error dominante.
3. Revisa proveedor LLM, broker, UI y tools según el tipo de error.
4. Si hay impacto en usuarios, escala a `operator` o `admin` y considera rollback de la última release.

## OpenMiuraHighLatencyP95

**Qué significa**
La latencia p95 agregada es elevada de forma sostenida.

**Qué hacer**
1. Revisa el dashboard **Latency & Capacity**.
2. Comprueba si la latencia afecta a un canal concreto (`http`, `telegram`, `slack`, `discord`).
3. Revisa si hay atasco en proveedor LLM, terminal, red o base de datos.
4. Reduce concurrencia, sube timeouts o conmuta a un modelo/proveedor menos cargado si hace falta.

## OpenMiuraToolErrorsBurst

**Qué significa**
Las tools están fallando con frecuencia sostenida.

**Qué hacer**
1. Abre el dashboard **Security & Broker** y el panel `Tool error ratio`.
2. Identifica la tool con más errores.
3. Revisa permisos, confirmaciones y configuración del sandbox.
4. Si la tool es `terminal_exec`, valida allowlists y comandos bloqueados.

## OpenMiuraNoActiveSessions

**Qué significa**
No se observan sesiones activas durante una ventana larga.

**Qué hacer**
1. Confirma si el sistema debería estar recibiendo tráfico.
2. Si no hay tráfico esperado, no es incidente; puede ser horario valle.
3. Si sí debería haber tráfico, revisa canales, reverse proxy, auth y provider LLM.

## OpenMiuraBrokerAuthFailures

**Qué significa**
Se están acumulando fallos de autenticación o validación CSRF.

**Qué hacer**
1. Revisa intentos de login fallidos y eventos de CSRF en auditoría.
2. Comprueba expiración de sesiones, cookies y cabeceras CSRF.
3. Si el patrón es malicioso, rota tokens y endurece rate limits.
4. Si es un cambio reciente de frontend/proxy, corrige origen, cookies `SameSite` y `Secure`.

## OpenMiuraTokenUsageDrop

**Qué significa**
Hay peticiones correctas pero no se observa consumo de tokens.

**Qué hacer**
1. Comprueba si el proveedor LLM cambió o está devolviendo metadatos incompletos.
2. Revisa los paneles por modelo y por canal.
3. Verifica instrumentación en `agent_runtime` y compatibilidad del proveedor.
4. Si el servicio funciona, clasifica el incidente como observabilidad parcial y crea tarea de ajuste.

## OpenMiuraSyntheticCritical

Alerta sintética para verificar que la ruta crítica de Alertmanager llega a sus receptores.

## OpenMiuraSyntheticWarning

Alerta sintética para verificar que la ruta warning llega a Slack o al canal equivalente.
