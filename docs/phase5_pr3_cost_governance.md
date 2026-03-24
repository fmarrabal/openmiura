# FASE 5 PR3 — Cost governance por tenant/workspace/agente/workflow/provider/modelo

## Objetivo
Abrir la capa inicial de gobernanza de coste en openMiura con métricas agregadas, presupuestos configurables y alertas operativas.

## Alcance implementado

### 1. Cost governance service
Se añade `CostGovernanceService` con tres capacidades base:
- `summary(...)`: agregación de coste y volumen de ejecuciones
- `budgets(...)`: evaluación de presupuestos configurados
- `alerts(...)`: generación de alertas warning/critical en función de la utilización

### 2. Dimensiones soportadas
La agregación se puede realizar por:
- tenant
- workspace
- agent
- workflow
- provider
- model
- tenant_workspace
- agent_provider_model

### 3. Fuente de verdad usada en esta PR
La PR reutiliza `evaluation_runs` como ledger inicial de coste porque ya registra:
- tenant/workspace/environment
- agent_name
- provider/model
- total_cost
- total_cases

**Nota importante:** en esta iteración el eje `workflow` se resuelve como `workflow_name` si existiera y, si no, cae en `suite_name` del evaluation harness. Es una aproximación deliberada y explícita para no introducir todavía una migración extra ni duplicar almacenamiento antes de tener trazabilidad de coste también en workflows productivos fuera del harness.

### 4. Configuración nueva
Se añade el bloque:

```yaml
cost_governance:
  enabled: true
  default_window_hours: 720
  default_scan_limit: 2000
  budgets:
    - name: tenant-monthly
      group_by: tenant
      budget_amount: 50.0
      window_hours: 720
      warning_threshold: 0.8
      critical_threshold: 1.0
      tenant_id: acme
      workspace_id: ops
      environment: prod
```

Cada presupuesto puede filtrar por:
- tenant_id
- workspace_id
- environment
- agent_name
- workflow_name
- provider
- model

### 5. Endpoints nuevos
HTTP admin:
- `GET /admin/costs/summary`
- `GET /admin/costs/budgets`
- `GET /admin/costs/alerts`

Broker admin:
- `GET /admin/costs/summary`
- `GET /admin/costs/budgets`
- `GET /admin/costs/alerts`

### 6. Salidas principales
`/admin/costs/summary` devuelve:
- total_spend
- run_count
- total_cases
- agrupaciones con coste total, coste medio por run y últimos runs

`/admin/costs/budgets` devuelve por presupuesto:
- budget_amount
- current_spend
- remaining_budget
- utilization
- status (`ok`, `warning`, `critical`)

`/admin/costs/alerts` devuelve alertas derivadas de los presupuestos.

## Validación
Se han añadido tests para:
- parseo de configuración de cost governance
- agregación por dimensiones
- presupuestos y alertas
- endpoints admin de summary/budgets/alerts

## Siguiente paso natural
El siguiente PR lógico dentro de FASE 5 sería enriquecer el coste desde ejecución real del agente y no solo desde evaluation runs, conectando:
- uso de tokens
- tool execution cost
- coste por workflow run real
- presupuestos y cuotas accionables en UI
