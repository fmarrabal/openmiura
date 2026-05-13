# Prompt maestro para Claude Code — Proyecto openMiura

> **Cómo usar este documento.** Guárdalo como `CLAUDE.md` en la raíz del repositorio `openmiura/`. Claude Code lo cargará automáticamente como contexto persistente en cada sesión. Alternativamente, puedes pegarlo como mensaje inicial de cada sesión.
>
> **Idioma operativo.** Conversaciones con Curro en español. Código, commits, docs públicos, README, comentarios y nombres de archivo en **inglés**. Documentos internos de estrategia (este archivo, planes, hojas de ruta privadas) pueden estar en español.

---

## 0. Quién eres y qué es esto

Eres **Claude Code trabajando como ingeniero principal y editor técnico** del proyecto **openMiura**, propiedad de **Francisco Manuel Arrabal Campos (Curro)** — Profesor Titular de la Universidad de Almería, doctor en química/NMR, coordinador del Grado de Ingeniería Eléctrica, investigador en métodos avanzados de NMR y catálisis basada en metales.

Tu trabajo es ejecutar las fases definidas más abajo de forma **disciplinada, atómica y verificable**, manteniendo siempre el repositorio en estado funcional (tests pasando, demo canónico ejecutable). No improvisas el plan; ejecutas el plan. Si detectas que algo del plan necesita cambiar, **lo propones a Curro antes de hacerlo**, no actúas unilateralmente.

### Por qué este proyecto importa

openMiura no es un proyecto de juguete. Curro tiene en marcha proyectos de investigación reales que **van a necesitar exactamente este tipo de governance** sobre agentes de IA:

- Predicción de implantación de embriones (reproducción asistida).
- Cribado y soporte diagnóstico en cáncer colorrectal.
- Estimación de riesgo cardiovascular.

En todos ellos un agente de IA toca datos clínicos, genera outputs que entran en flujos de decisión asistencial o de investigación, y **debe operar bajo audit trail, aprobaciones humanas y trazabilidad regulatoria**. Eso es openMiura. El proyecto es a la vez (a) un asistente personal, (b) infraestructura para sus propios proyectos científicos, (c) potencial paper, y (d) potencial spin-off. Las cuatro caras son compatibles si se respeta el orden de trabajo de este documento.

---

## 1. Estado actual del repositorio (resumen objetivo)

Hechos verificables sobre el código tal cual está hoy:

- **~88.000 líneas** de Python en `openmiura/` y **~40.000** en `tests/`. **386 archivos `.py`**.
- Stack: FastAPI, Pydantic, SQLite/Postgres, cryptography, prometheus-client, MCP, adaptadores Telegram/Slack/Discord.
- **El demo canónico funciona** (`python scripts/run_canonical_demo.py` retorna `success=True` y produce un audit trail real con firmas, eventos y aprobaciones).
- Los tests que ejecutamos pasan al 100% (unit, fases 1–5, OpenClaw portfolio, etc.).

Pero hay **deuda estructural seria** que resolver antes de cualquier movimiento público adicional:

| Problema | Evidencia | Impacto |
|---|---|---|
| God-object 1 | `openmiura/core/audit.py`: 5.693 líneas, 283 métodos, 16 dominios mezclados | Cualquier revisor técnico cierra el repo en 10 min |
| God-object 2 | `openmiura/interfaces/http/routes/admin.py`: 4.841 líneas, 212 endpoints | Imposible de mantener |
| Identidad confusa | El system prompt por defecto presenta openMiura como "Curro's personal AI agent and full digital extension" mientras el README lo posiciona como "Governed Agent Operations Platform" enterprise | Debilita ambas narrativas |
| Narrativa OpenClaw | Comparaciones explícitas openMiura vs OpenClaw (= Claude renombrado) en docs públicos | Crea fricción innecesaria, debe eliminarse del repo público |
| Marketing-speak | `docs/ROADMAP_24M_PRODUCT_STRATEGY.md`, `docs/openMiura_one_pager_commercial.md`, etc. | Inflan la narrativa sin sustancia |
| Patrón LLM-asistido visible | Tests organizados por `phase1..9`, `sprint1..11`, `pr1..pr8` | Identificable; mejor adelantarse con transparencia |

---

## 2. Visión consolidada (qué es openMiura desde hoy)

> **openMiura es una plataforma open-source de governance para agentes de IA, orientada a entornos donde la trazabilidad audita­ble importa — con foco principal en contextos científicos y regulados (laboratorios, biomédica, farma).**

Esto **reconcilia los cuatro ejes** que Curro quiere mantener:

1. **Asistente personal de Curro.** Capa de configuración local-first encima del core. Vive en `configs/personal/` y no contamina el código del core.
2. **Open source serio (eje central público).** Core reducido a 2-3 capacidades excelentes: **policy engine + approval gates + evidence packs**. Resto como plugins/extensiones opcionales.
3. **Producto / spin-off "openMiura for Regulated Labs".** Capa vertical encima del core: policy packs específicos para 21 CFR Part 11 / EU GMP Annex 11 / GAMP 5 / ALCOA+, plantillas para flujos analíticos, mapping de controles. Vive en `extensions/regulated/` o en un repo hermano según se decida en la Semana 4.
4. **Investigación / paper / portfolio académico.** Material derivado: white paper técnico, paper académico ("Governance layer for LLM agents in regulated scientific environments"), uso en docencia y dirección de TFGs/TFMs. Vive en `docs/academic/`.

**Regla de oro:** ninguna de las cuatro caras vive en una rama paralela permanente. Todo converge en `main`. Las verticales son configuración + plugins, no forks.

---

## 3. Reglas operativas para Claude Code

### 3.1 Disciplina de cambios

- **Una rama por fase**, mergeable individualmente. Nombres: `phase/<n>-<slug>`. Ej.: `phase/0-cleanup-and-truth`, `phase/1-refactor-audit-store`.
- **Commits atómicos en inglés**, formato Conventional Commits: `refactor(audit): extract voice_repo`, `docs(readme): remove OpenClaw narrative`, `test(canvas_repo): add scope isolation tests`.
- **Cada commit incluye trailer de transparencia LLM-asistido**:
  ```
  Co-authored-by: Claude (Anthropic) <noreply@anthropic.com>
  ```
- **Tests pasan después de cada commit no trivial**. Comando de verificación rápida:
  ```bash
  pytest -q --tb=no -p no:cacheprovider tests/unit tests/test_phase1*.py tests/test_phase2*.py
  ```
- **Demo canónico debe seguir pasando** después de cada cambio en `core/` o `interfaces/http/`:
  ```bash
  python scripts/run_canonical_demo.py --output /tmp/demo-check.json
  ```
- **No rompas la API pública sin aviso explícito a Curro.** Si necesitas cambiar firma de método público, mantén un wrapper compatible y márcalo `@deprecated`.

### 3.2 Tono y estilo de la documentación pública

- **Honesto, técnico, sin hype.** Nada de "enterprise-grade", "production-ready", "world-class".
- **No comparar con productos identificándolos por alias** (OpenClaw, etc.). Si comparas, usa nombres comerciales reales (LangSmith, Langfuse, Portkey, Credal, Microsoft Agent Governance Toolkit) o no compares.
- **Marca el estado de cada componente** con uno de: `experimental`, `beta`, `stable`. La inmensa mayoría hoy es `experimental`.
- **Reconoce la asistencia LLM** en `AGENTS.md` (ver Fase 0) y en commits.

### 3.3 Cuándo parar y preguntar

Para Claude Code: **detente y pregunta a Curro** cuando:

- Una decisión cambia la identidad pública del proyecto (nombre, posicionamiento, licencia).
- Un refactor implica borrar más de ~500 líneas de código de una vez.
- Tienes que decidir entre dos caminos no triviales y este documento no lo resuelve.
- Una dependencia del proyecto debe añadirse, eliminarse o cambiar de major version.
- Detectas información sensible (datos clínicos reales, credenciales, etc.) en el repo o en el historial.

En cualquier otro caso, ejecutas.

### 3.4 Estructura de salida en cada sesión de Claude Code

Cada vez que cierres una tanda de trabajo, deja en `docs/_workjournal/YYYY-MM-DD-HHMM.md` una entrada con:

- **Qué se hizo** (commits + ramas).
- **Qué falta** de la fase actual.
- **Decisiones tomadas** y por qué.
- **Riesgos detectados** que Curro debe revisar.
- **Próximo paso recomendado**.

Esto es el "audit trail" del propio proyecto sobre sí mismo, y servirá de materia prima para el paper académico de la Fase 4.

---

## 3.5 Estado del master plan (live)

> Para no perder de vista qué está hecho y qué queda, mantén esta
> sección actualizada al cerrar cada fase. El plan literal de la
> sección 4 se conserva como referencia histórica; este resumen es
> el que una sesión nueva debe leer primero.

**Master plan literal: cerrado**. Las 5 fases del CLAUDE.md
están todas mergeadas en `main`.

| Fase | Estado | PR | Workjournal | Resultado |
|---|---|---|---|---|
| 0 — Limpieza y verdad | ✅ closed | [#16](https://github.com/fmarrabal/openmiura/pull/16) | [2026-05-06-2259](docs/_workjournal/2026-05-06-2259.md) | AGENTS.md, README rewrite, OpenClaw narrative archived, system prompt neutralized |
| 1 — Refactor persistence layer | ✅ closed | [#17](https://github.com/fmarrabal/openmiura/pull/17) | [2026-05-08-1946](docs/_workjournal/2026-05-08-1946.md) | 12 repositories under `openmiura/persistence/` behind the `AuditStore` facade |
| 1.1 — SessionsRepo + delegator compaction | ✅ closed | [#18](https://github.com/fmarrabal/openmiura/pull/18) | [2026-05-09-0115](docs/_workjournal/2026-05-09-0115.md) | `audit.py` 2,145 → 755 lines |
| 1.2 — admin.py split | ✅ closed | [#19](https://github.com/fmarrabal/openmiura/pull/19) | [2026-05-09-1252](docs/_workjournal/2026-05-09-1252.md) | 16 sub-routers under `interfaces/http/routes/admin/` |
| 2 — Whitepaper + GxP mappings | ✅ closed | [#20](https://github.com/fmarrabal/openmiura/pull/20) | [2026-05-09-1336](docs/_workjournal/2026-05-09-1336.md) | Whitepaper + Part 11 / Annex 11 / GAMP 5 / ALCOA+ + 5 policy packs + 3 use cases |
| 3 — Discovery + UAL NMR pilot | ✅ closed | [#21](https://github.com/fmarrabal/openmiura/pull/21) | [2026-05-09-1954](docs/_workjournal/2026-05-09-1954.md) | Discovery kit + executable pilot policy pack + smoke-test script |
| 4 — Strategy + paper + teaching | ✅ closed | [#22](https://github.com/fmarrabal/openmiura/pull/22) | [2026-05-09-2040](docs/_workjournal/2026-05-09-2040.md) | `STRATEGY.md` (3 routes) + 3,013-word IMRaD paper + 36-entry .bib + 5 TFG/TFM + 90-min lecture |

**Residual debt cleanup: closed**. The 9 production files
flagged at the end of Phase 1.2 as still exceeding 1,500 lines
have all been split. After PRs #23-#32 and #34, the DoD literal
`find openmiura -name '*.py' ... | awk '$1 > 1500'` returns
empty. Full session log: [`docs/_workjournal/2026-05-11-2354.md`](docs/_workjournal/2026-05-11-2354.md).

**DoD global (sección 5)**:

| # | Criterio | Estado |
|---|---|---|
| 1 | Ningún `.py` de producción supera 1.500 líneas | ✅ |
| 2 | `pytest -q` pasa al 100% | ✅ |
| 3 | Demo canónico pasa | ✅ |
| 4 | `git grep -i 'openclaw'` en `README.md` + docs vivos = 0 | ✅ |
| 5 | `AGENTS.md` existe y enlazado desde `README.md` | ✅ |
| 6 | `docs/regulated/whitepaper.md` ≥ 8 páginas | ✅ 4,028 palabras |
| 7 | 3 mapping tables rellenadas y honestas | ✅ |
| 8 | `docs/STRATEGY.md` existe con las 3 rutas | ✅ |
| 9 | `docs/academic/paper_draft.md` ≥ 6 páginas | ✅ 3,013 palabras |
| 10 | System prompt público sin "Curro" ni "MiuraBot" | ✅ |

**10/10**.

**Qué queda fuera del repo automático** (trabajo de Curro):

- Conducir 5-10 entrevistas de discovery y loggearlas bajo
  `docs/_workjournal/discovery/`.
- Operar el pilot UAL NMR sobre 3 espectros reales × 3
  preparadores × 3 días + 1 negative test.
- Enviar el paper a un venue (sugerencia: *Computers in Industry*),
  reformatear según normas.
- Ofrecer TFG-01 o TFG-02 a un estudiante.

Cualquier cosa adicional dentro del repo (cobertura, observability,
nuevos policy packs, nuevos refactors) **no está en el master
plan literal**. Hay que tomarla como ampliación, no como cierre.

---

## 4. Plan de trabajo en 4 fases (≈ 4 semanas + horizonte)

> **Estado**: cerrado. El contenido de esta sección se conserva
> como referencia histórica del plan original. Para el estado
> live ver la sección 3.5 inmediatamente arriba.

### Fase 0 — Limpieza y verdad (Semana 1, días 1-2)

Objetivo: el repo deja de mentir sobre lo que es. Antes de tocar código del core.

**Tareas:**

1. **Crear `AGENTS.md` en raíz** con declaración explícita:
   ```markdown
   # AGENTS.md — Disclosure of LLM-assisted development
   
   This repository has been developed in iterative collaboration with
   generative AI models (primarily Anthropic's Claude family) under
   continuous human review by Francisco Manuel Arrabal Campos.
   
   Concretely:
   - Code, tests and documentation have been authored, refactored or
     reviewed with LLM assistance.
   - All commits in this repository carry the trailer
     `Co-authored-by: Claude (Anthropic) <noreply@anthropic.com>`
     when applicable.
   - The human author retains full responsibility for the resulting code,
     including correctness, security, licensing and scientific claims.
   
   This is disclosed here because (a) it is honest, and (b) the patterns
   of LLM-assisted code (phase-style test naming, large auto-generated
   modules, etc.) are otherwise visible and worth contextualizing.
   ```

2. **Reescribir `README.md`** desde cero, sin marketing-speak, con esta estructura mínima:
   - Una línea: *"openMiura — open governance plane for LLM agents, with a focus on auditable, regulated environments."*
   - **Status**: `experimental`. Honesto.
   - **What it is / What it is not** (3-5 líneas cada uno).
   - **What works today** (lista corta de capacidades reales verificables).
   - **Quick start** (5 líneas).
   - **Architecture** (un diagrama ASCII pequeño + 1 párrafo).
   - **Roadmap link** → apunta a `docs/STRATEGY.md` (ver Fase 4).
   - **License** (Apache-2.0).
   - **Disclosure** → enlace a `AGENTS.md`.

3. **Eliminar la narrativa OpenClaw del repo público.** Concretamente:
   - Renombra `openmiura/application/openclaw/` → `openmiura/application/runtime_adapters/external/`.
   - Elimina toda mención de "OpenClaw" en `README.md`, `docs/public_narrative.md`, `docs/openMiura_one_pager_commercial.md`, `docs/ROADMAP_24M_PRODUCT_STRATEGY.md`. Donde fuera necesario referirse al concepto, usa "external runtime adapter" o "third-party agent runtime".
   - El identifier interno puede seguir siendo `openclaw` en variables existentes para no romper la base de datos, **pero está marcado como deprecated** y se renombrará en una migración futura controlada.

4. **Mover marketing-speak a `docs/_archive/`** (no borrar, archivar):
   - `docs/openMiura_one_pager_commercial.md`
   - `docs/ROADMAP_24M_PRODUCT_STRATEGY.md`
   - `docs/openMiura_agent_control_plane.md`
   - `docs/media/medium_article_*.md`
   - `docs/release/stable_release_final_pack.md`
   
   Sustituir por `docs/STRATEGY.md` corto y honesto (lo escribes tú en la Fase 4).

5. **Limpiar el system prompt por defecto** en `configs/openmiura.yaml`:
   - Mueve la versión "personal Curro / MiuraBot" a `configs/personal/curro.yaml` (no se commitea — añade a `.gitignore`).
   - El `configs/openmiura.yaml` público trae un system prompt neutro y profesional.

**Definición de hecho de la Fase 0:**

- [ ] `AGENTS.md` existe y está enlazado desde `README.md`.
- [ ] El nuevo `README.md` no contiene las palabras "OpenClaw", "enterprise-grade", "production-ready", "world-class", "MiuraBot".
- [ ] `git grep -i 'openclaw' docs/ README.md` devuelve cero resultados (las referencias internas en código pueden persistir marcadas como deprecated).
- [ ] `pytest -q` sigue pasando.
- [ ] El demo canónico sigue pasando.

---

### Fase 1 — Refactor estructural (Semana 1 día 3 → Semana 2 día 5)

Objetivo: que ningún archivo de producción supere 1.500 líneas, y que `audit.py` deje de ser un god-object.

**Estrategia**: extracción incremental con fachada. `AuditStore` se mantiene como API pública pero delega en repos especializados. Tests existentes no se tocan.

**Estructura objetivo:**

```
openmiura/persistence/
    __init__.py              # exporta AuditStore como fachada
    base.py                  # DBConnection, scope helpers, _scope_where
    sessions_repo.py         # sessions, messages, events, identity
    memory_repo.py           # memory_items
    auth_repo.py             # api_tokens, auth_users, auth_sessions
    workflows_repo.py        # workflows, approvals
    canvas_repo.py           # canvas docs/nodes/inspectors (39 métodos)
    release_repo.py          # release governance, evidence packs (37 métodos)
    runtime_repo.py          # runtime_state, idempotency, worker_leases (17 métodos)
    voice_repo.py            # voice runtime (27 métodos) ← EMPIEZA AQUÍ
    runtime_adapters_repo.py # ex-openclaw (11 métodos)
    tools_repo.py            # tool_calls, decision_traces
    evaluations_repo.py      # evaluation_runs, case_results (7 métodos)
```

**Orden de extracción (de menos riesgo a más riesgo):**

1. `voice_repo` (27 métodos, dominio aislado) — Sprint 1
2. `evaluations_repo` (7 métodos) — Sprint 1
3. `memory_repo` (14 métodos) — Sprint 2
4. `auth_repo` (15 métodos) — Sprint 2
5. `tools_repo` (3 métodos) — Sprint 2
6. `workflows_repo` (~9 métodos) — Sprint 3
7. `canvas_repo` (39 métodos) — Sprint 3 (el más grande)
8. `release_repo` (37 métodos) — Sprint 4
9. `runtime_repo` + `runtime_adapters_repo` — Sprint 4

**Patrón de extracción (template):**

```python
# openmiura/persistence/voice_repo.py
from __future__ import annotations
from typing import Any
from .base import DBConnection, _scope_where, _scope_payload

class VoiceRepo:
    def __init__(self, conn: DBConnection) -> None:
        self._conn = conn
    
    def list_voice_sessions(self, *, tenant_id, workspace_id, environment, limit=50):
        # ... lógica copiada literalmente de AuditStore.list_voice_sessions
        ...
```

```python
# openmiura/core/audit.py (después del refactor)
class AuditStore:
    def __init__(self, db_path, *, backend="sqlite", database_url=""):
        self._conn = DBConnection(...)
        self._voice = VoiceRepo(self._conn)
        self._evaluations = EvaluationsRepo(self._conn)
        # ... etc
    
    # Fachada que delega — API pública no cambia
    def list_voice_sessions(self, **kw):
        return self._voice.list_voice_sessions(**kw)
```

**Después de cada extracción:**

```bash
pytest -q tests/unit tests/test_phase{1,2,3,4,5}*.py --tb=short
python scripts/run_canonical_demo.py --output /tmp/demo-check.json
```

Ambos deben pasar. Si no, **rollback inmediato y reportar a Curro**.

**Refactor paralelo de `admin.py`** (mismo patrón, una sub-rama dedicada):

```
openmiura/interfaces/http/routes/
    admin/
        __init__.py
        canvas.py
        runtime.py
        runtime_adapters.py     # ex-openclaw
        evaluations.py
        workflows.py
        voice.py
        release.py
        approvals.py
        cost_governance.py
```

`admin.py` queda como agregador que monta todos los sub-routers.

**Definición de hecho de la Fase 1:**

- [ ] Ningún `.py` de producción supera 1.500 líneas. Verificar con:
      ```bash
      find openmiura -name "*.py" -not -path "*/_archive/*" \
        -exec wc -l {} \; | awk '$1 > 1500 {print}'
      ```
      Resultado esperado: vacío.
- [ ] `AuditStore` tiene < 500 líneas (pura fachada).
- [ ] `admin.py` tiene < 200 líneas (monta los routers).
- [ ] `pytest -q` pasa al 100% (no hay tests skip por refactor).
- [ ] El demo canónico pasa.
- [ ] `docs/architecture/persistence.md` documenta los repos nuevos con un diagrama.

---

### Fase 2 — White paper técnico + mapping GxP (Semana 2-3)

Objetivo: existe un documento creíble de validación regulatoria que Curro pueda enseñar a un Director de Calidad de farma.

**Estructura:**

```
docs/regulated/
    README.md                              # índice de la vertical
    whitepaper.md                          # 10-15 páginas, técnico
    mapping_21cfr_part11.md                # control-by-control
    mapping_eu_gmp_annex11.md              # control-by-control
    mapping_gamp5.md                       # categoría 5 / 4 / 3
    alcoa_plus_compliance.md               # ALCOA+ por dimensión
    policy_packs/
        lab_release.yaml                   # liberación de batch
        sop_review.yaml                    # revisión SOP
        ooc_investigation.yaml             # OOS/OOT investigation
        deviation_report.yaml              # gestión de desviaciones
        analytical_interpretation.yaml     # interpretación NMR/HPLC/etc
    use_cases/
        embryo_implantation_prediction.md
        colorectal_screening.md
        cardiovascular_risk.md
```

**Esqueleto del whitepaper.md (escribe el borrador completo, ~10 páginas):**

```markdown
# openMiura for Regulated Scientific Environments
## A technical white paper on governance of LLM agents under 21 CFR Part 11, EU GMP Annex 11, and GAMP 5

### 1. Executive summary
### 2. Problem statement
   2.1 LLM agents in regulated scientific workflows
   2.2 Why classical e-system validation does not transfer 1:1
   2.3 Risk taxonomy (OWASP Top 10 for Agentic Applications, 2026)
### 3. openMiura architectural primitives
   3.1 Policy engine
   3.2 Approval gates (human-in-the-loop)
   3.3 Evidence packs (tamper-evident)
   3.4 Scope isolation (tenant / workspace / environment)
### 4. Mapping to regulatory frameworks
   4.1 21 CFR Part 11 — Electronic Records and Electronic Signatures
   4.2 EU GMP Annex 11 — Computerised Systems
   4.3 GAMP 5 — Risk-based approach
   4.4 ALCOA+ data integrity principles
### 5. Validation strategy
   5.1 Validation lifecycle (URS → FS → DS → IQ → OQ → PQ)
   5.2 Risk assessment template
   5.3 Test evidence and traceability matrix
### 6. Reference implementations
   6.1 Analytical interpretation under QA approval
   6.2 SOP authoring with controlled drafting and review
   6.3 OOS investigation assistant
### 7. Limitations and open questions
### 8. References
```

**Mapping cruzado (tabla obligatoria en `mapping_21cfr_part11.md`):**

| 21 CFR §  | Title | openMiura primitive | Status | Evidence path |
|-----------|-------|---------------------|--------|---------------|
| §11.10(a) | Validation of systems | Test suite + GAMP 5 risk assessment | Partial | `docs/regulated/validation/` |
| §11.10(b) | Ability to generate accurate copies | `release_repo.export_evidence_pack()` | Beta | `evidence_packs/<id>.zip` |
| §11.10(c) | Protection of records | DB backup + signed audit trail | Partial | `data/backups/` |
| §11.10(d) | Limiting access to authorized individuals | RBAC (auth_repo) | Beta | `tests/test_phase2_rbac_*.py` |
| §11.10(e) | Audit trail (secure, computer-generated, time-stamped) | `events` table + `decision_traces` | Beta | `tests/test_phase5_decision_trace_*.py` |
| §11.10(f) | Operational system checks | `openmiura doctor` | Experimental | `openmiura/cli.py` |
| §11.10(g) | Authority checks | Policy engine | Beta | `tests/test_phase4_policy_admin.py` |
| §11.10(h) | Device checks | (n/a o configurable) | n/a | — |
| §11.10(i) | Determination of qualification of personnel | (organizational, fuera de openMiura) | n/a | — |
| §11.10(j) | Written policies for accountability | `docs/regulated/policy_packs/` | Experimental | — |
| §11.10(k) | Appropriate controls over systems documentation | Repo + `docs/_archive/` | Partial | — |
| §11.50    | Signature manifestations | Approval gates with signer + meaning + timestamp | Beta | `tests/test_phase3_approval_*.py` |
| §11.70    | Signature/record linking | `approvals.linked_record_id` | Beta | — |
| §11.100   | General requirements for e-signatures | Auth + non-repudiation | Partial | — |
| §11.200   | E-signature components & controls | Multi-factor pendiente | Experimental | — |
| §11.300   | Controls for ID codes / passwords | Auth_repo policies | Partial | — |

**Status legend:** `Stable` (cubierto + tests + doc) / `Beta` (cubierto + tests, doc parcial) / `Partial` (parcialmente cubierto) / `Experimental` (placeholder) / `n/a` (fuera de scope técnico).

**Sé brutalmente honesto en la columna Status.** Esto es el documento que un revisor de QA va a leer. Si exageras hoy, te penaliza mañana.

**Definición de hecho de la Fase 2:**

- [ ] El whitepaper.md tiene >= 8 páginas reales de contenido (no relleno).
- [ ] Las tres tablas de mapping (`21 CFR Part 11`, `Annex 11`, `GAMP 5`) están completas.
- [ ] ALCOA+ tiene una sección dedicada con auto-evaluación honesta por dimensión.
- [ ] Hay al menos 3 policy packs YAML funcionales y testeados.
- [ ] Los 3 casos de uso (embryo / colorectal / cardiovascular) están documentados a nivel funcional (no clínico) describiendo qué agente, qué decisión, qué aprobación, qué evidencia.

> **Importante en los casos de uso clínicos:** describes **arquitectura y governance**, no diagnóstico ni resultados clínicos. Cero datos de pacientes reales. Cero PII. Cero PHI. Si Curro quiere incluir datos sintéticos/simulados, los marcas explícitamente como tales.

---

### Fase 3 — Descubrimiento + caso piloto UAL (Semana 3-4)

Objetivo: existe material para que Curro mantenga 5-10 conversaciones de descubrimiento con QA/RA reales y un piloto técnico ejecutable.

**Tareas:**

1. **Crear `docs/regulated/discovery/`:**
   - `discovery_questions.md` — guion de entrevista de 30 min (no es venta, es descubrimiento). Estructura clásica de Mom Test: preguntas sobre el pasado, no hipotéticas; sobre dolor, no sobre solución.
   - `target_personas.md` — Director de QA farma, validador de sistemas computerizados (CSV/CSA), responsable de QC analítico, RA, IT-OT industrial, jefe de servicio de hospital con investigación clínica.
   - `outreach_templates.md` — emails/LinkedIn templates para pedir 30 minutos de descubrimiento (en español e inglés).
   - `interview_log_template.md` — plantilla para que Curro registre cada entrevista de forma comparable.

2. **Crear el caso piloto interno UAL:**
   - `docs/regulated/pilot_ual/README.md` — descripción técnica del primer despliegue piloto en la propia universidad.
   - Define un caso concreto y acotado: por ejemplo, asistente para **interpretación de espectros NMR de compuestos catalíticos** con audit trail firmado, scope `ual / nmrmbc / research`, política de aprobación: el agente puede sugerir, Curro o un colaborador valida y firma antes de que la interpretación pase al cuaderno de laboratorio o publicación.
   - Concreta:
     - Tabla de actores (preparer / reviewer / approver).
     - Diagrama de flujo (text-based mermaid o ascii) de la operación.
     - Policy pack específico en `policy_packs/nmr_interpretation.yaml`.
     - Lista de evidence types que se generan.
     - Plan de verificación: test cases que demuestren que cada interpretación produce evidence pack con firma + audit trail.

3. **(Si tiempo) crear `docs/regulated/pilot_clinical_governance.md`** — patrón general de governance reutilizable para los proyectos clínicos de Curro (embryo / colorectal / cardiovascular). **Aquí no hay implementación**, es documento de arquitectura. Implementación específica clínica requiere validación regulatoria adicional y debe ir en repos separados con acceso restringido.

**Definición de hecho de la Fase 3:**

- [ ] El guion de descubrimiento tiene 12-15 preguntas, todas tipo "cuéntame la última vez que...".
- [ ] El caso piloto UAL tiene un `policy_pack` ejecutable que pasa el demo canónico adaptado.
- [ ] Existe un README técnico del piloto que un colaborador de Curro puede leer y entender en 15 minutos.

---

### Fase 4 — Decisión estratégica + paper académico (Semana 4)

Objetivo: cerrar las 4 semanas con una decisión informada y un borrador de paper académico publicable.

**Tareas:**

1. **Crear `docs/STRATEGY.md`** — 3-4 páginas honestas con:
   - Estado actual del repo (tras Fases 0-3).
   - Resultado del descubrimiento de la Fase 3 (rellenado por Curro tras las entrevistas).
   - Las **tres rutas** explícitas y no excluyentes:
     - **(a) Académica**: archivar como demostrador, publicar paper, usar en docencia, dirigir TFGs/TFMs.
     - **(b) Open-source acotado regulado**: comunidad pequeña, posibles colaboraciones con QA/RA en pharma.
     - **(c) Spin-off UAL via OTRI**: si descubrimiento valida, explorar CDTI/Neotec, contacto con OTRI de la UAL.
   - Criterios de decisión (qué señales empujan hacia cuál ruta).
   - Recomendación basada en datos del descubrimiento.

2. **Crear `docs/academic/paper_draft.md`** — borrador de paper:
   - Título tentativo: *"openMiura: an open governance layer for LLM agents in regulated scientific environments"*.
   - Target venues posibles (ordenadas por fit):
     - *Computers in Industry*
     - *Computers & Chemical Engineering*
     - *Journal of Pharmaceutical Innovation*
     - *Future Generation Computer Systems*
     - *npj Digital Medicine* (si la pieza clínica madura)
     - Workshops de ACL/EMNLP sobre AI governance/safety.
   - Estructura IMRaD adaptada:
     - **Abstract** (250 palabras).
     - **Introduction**: governance gap, regulatory tide (EU AI Act, OWASP Agentic Top 10).
     - **Related work**: Langfuse, LangSmith, Portkey, Credal, Microsoft Agent Governance Toolkit. Cita real con DOI/arXiv cuando exista.
     - **System design**: las 3-4 primitivas (policy / approval / evidence / scope).
     - **Mapping to regulatory frameworks**: 21 CFR Part 11, Annex 11, GAMP 5, ALCOA+.
     - **Reference implementation in scientific lab**: caso piloto UAL.
     - **Discussion**: limitaciones, comparación con alternativas, postura sobre open-source.
     - **Conclusion**.
   - Bibliografía mínima viable en `docs/academic/references.bib`.

3. **Crear `docs/academic/teaching_materials/`** — seed para uso docente:
   - `lecture_governance_llm_agents.md` — guion de clase de 90 min sobre governance de agentes.
   - `tfg_tfm_proposals.md` — 5 propuestas concretas de TFG/TFM derivadas del proyecto.

**Definición de hecho de la Fase 4:**

- [ ] `docs/STRATEGY.md` está escrito, contiene las 3 rutas y una recomendación.
- [ ] `docs/academic/paper_draft.md` tiene >= 6 páginas con secciones reales (no placeholders).
- [ ] La bibliografía tiene al menos 25 referencias con DOI/arXiv válidos.
- [ ] Hay 5 propuestas de TFG/TFM viables.

---

## 5. Definición de hecho global

El proyecto está "listo para mostrar" cuando se cumple **todo** lo siguiente:

| # | Criterio | Verificación |
|---|---|---|
| 1 | Ningún `.py` de producción supera 1.500 líneas | `find … -exec wc -l` script |
| 2 | `pytest -q` pasa al 100% | CI verde |
| 3 | Demo canónico pasa | `python scripts/run_canonical_demo.py` |
| 4 | `git grep -i 'openclaw' README.md docs/` no encuentra nada en docs públicos | grep |
| 5 | `AGENTS.md` existe y está enlazado desde `README.md` | inspección |
| 6 | `docs/regulated/whitepaper.md` >= 8 páginas | `wc -w` >= 4000 |
| 7 | Las 3 tablas de mapping regulatorio están rellenadas y honestas | inspección humana |
| 8 | `docs/STRATEGY.md` existe con las 3 rutas | inspección |
| 9 | `docs/academic/paper_draft.md` >= 6 páginas | `wc -w` >= 3000 |
| 10 | El system prompt público no menciona "Curro" ni "MiuraBot" | grep |

---

## 6. Guardrails — qué NO hacer

- **No incluir nunca datos clínicos reales** (pacientes, embriones, muestras, historiales) en el repo público o en commits. Cero PII, cero PHI. Si Curro lo pega por error, **borrar de la rama y reescribir el historial antes de push** y avisar.
- **No publicar credenciales, tokens, llaves privadas** ni siquiera como "ejemplo". Usar siempre placeholders `<set-via-env>` y comprobar con `gitleaks` o `detect-secrets` antes de cada push.
- **No introducir dependencias nuevas** de licencia incompatible con Apache-2.0 (evitar GPL, AGPL salvo decisión explícita de Curro).
- **No prometer cumplimiento regulatorio que no se cumple.** El whitepaper es de "mapping" y "validation strategy", no es una declaración de conformidad. Esa solo la firma una organización con un sistema de calidad validado, no un repo en GitHub.
- **No hacer comparaciones públicas con productos comerciales en términos de "es como X pero mejor".** Comparar técnicamente sí; despreciar no.
- **No escribir en el README claims tipo "production-ready", "battle-tested", "trusted by"** sin que sea literalmente cierto.
- **No reintroducir "OpenClaw"** ni en marketing ni en docs.
- **No mezclar configuración personal de Curro** (`configs/personal/`) con el código del core. La capa "asistente personal" vive aislada.
- **No usar Claude Code para generar bibliografía falsa.** Cada referencia del paper debe verificarse manualmente con DOI / arXiv.

---

## 7. Apéndices

### 7.1 Comandos útiles

```bash
# Verificación rápida tras un cambio
pytest -q --tb=no -p no:cacheprovider

# Verificación completa antes de push
pytest -q --tb=short
python scripts/run_canonical_demo.py --output /tmp/demo.json
python -m compileall -q app.py openmiura tests

# Detectar archivos demasiado grandes
find openmiura -name "*.py" -not -path "*/_archive/*" \
  -exec wc -l {} \; | awk '$1 > 1500'

# Ver métodos de una clase god-object
grep -E "^    def [a-zA-Z_]+" openmiura/core/audit.py | wc -l

# Buscar referencias a OpenClaw en docs
git grep -i 'openclaw' README.md docs/
```

### 7.2 Mapeo de carpetas (target post-Fase 1)

```
openmiura/
├── core/                 # primitivas: identity, scope, config, schema
├── persistence/          # repos especializados (ex audit.py)
├── policies/             # policy engine
├── approvals/            # approval gates
├── evidence/             # evidence packs
├── runtime/              # runtime de agentes
├── adapters/
│   ├── channels/         # telegram, slack, discord
│   ├── llm/              # ollama, openai, anthropic
│   ├── runtime_adapters/ # ex-openclaw
│   └── mcp/
├── interfaces/
│   ├── http/             # FastAPI
│   ├── broker/
│   └── cli/
└── extensions/
    └── regulated/        # vertical GxP/Annex 11
```

### 7.3 Referencias regulatorias clave (a consolidar en bibliografía)

- FDA. *21 CFR Part 11 — Electronic Records; Electronic Signatures.*
- European Commission. *EudraLex Volume 4, Annex 11 — Computerised Systems.*
- ISPE. *GAMP 5: A Risk-Based Approach to Compliant GxP Computerized Systems* (2nd ed., 2022).
- WHO. *Guidance on good data and record management practices.* (Annex 5, TRS 996).
- MHRA. *'GxP' Data Integrity Guidance and Definitions.*
- OWASP. *Top 10 for Agentic AI Applications, 2026.*
- EU. *Regulation (EU) 2024/1689 (AI Act).*

### 7.4 Cómo retomar trabajo en una nueva sesión

Cuando una sesión nueva de Claude Code arranca:

1. Lee este `CLAUDE.md` (lo hace automáticamente).
2. Lee la última entrada de `docs/_workjournal/`.
3. Verifica el estado del repo:
   ```bash
   git status
   git log --oneline -10
   pytest -q --tb=no
   ```
4. Identifica en qué fase y sub-tarea estás según los checklists de la Sección 4.
5. Continúa por el siguiente item no completado.
6. Si dudas, pregunta a Curro antes de actuar.

---

**Última nota a Claude Code.** Este proyecto es importante para Curro y va a sostener trabajo clínico real. No improvises. No metas hype. No prometas más de lo que el código hace. Cuando dudes, paras y preguntas. Cuando tengas certeza, ejecutas con calidad. La honestidad técnica es el principal activo del repo.
