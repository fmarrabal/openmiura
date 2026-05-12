# Test coverage baseline

> **Snapshot only — not a gate.** This document records the state of
> test coverage as of 2026-05-12, immediately after the residual
> 1,500-line debt cleanup. There is no CI threshold yet; this
> baseline is the input for deciding whether one is worth setting
> and where the floor should land.

## Methodology

- Tool: `pytest-cov` 7.1.0 / `coverage` 7.14.0 (installed in the
  local conda env `openmiura-clean`; not added to
  `pyproject.toml`).
- Command:
  ```bash
  pytest -q --tb=no -p no:cacheprovider \
      --cov=openmiura --cov-report=term --cov-report=json:reports/coverage_baseline.json
  ```
- Source of truth: `reports/coverage_baseline.json`.

## Headline number

| | Statements | Missing | Covered |
|---|---:|---:|---:|
| **Total** | **41,179** | **7,496** | **81.8 %** |

For context: 178 test files containing ~5,128 assertions. The
suite runs in roughly 10–15 minutes locally.

## Per top-level package

| Package | Statements | Miss | Coverage |
|---|---:|---:|---:|
| `openmiura/application/` | 24,879 | 3,527 | **85.8 %** |
| `openmiura/extensions/` | 978 | 118 | **87.9 %** |
| `openmiura/agents/` | 187 | 22 | **88.2 %** |
| `openmiura/persistence/` | 3,283 | 510 | **84.5 %** |
| `openmiura/observability.py` *(top-level)* | 49 | 3 | 94 % |
| `openmiura/realtime.py` *(top-level)* | 98 | 17 | 83 % |
| `openmiura/core/` | 3,171 | 686 | 78.4 % |
| `openmiura/_top_level/` files | 1,503 | 350 | 76.7 % |
| `openmiura/infrastructure/` | 22 | 5 | 77.3 % |
| `openmiura/demo/` | 118 | 34 | 71.2 % |
| `openmiura/interfaces/` | 6,162 | 1,901 | 69.1 % |
| `openmiura/tools/` | 562 | 199 | 64.6 % |
| `openmiura/channels/` | 296 | 136 | 54.1 % |
| `openmiura/endpoints/` (compat shim) | 10 | 0 | 100 % |
| `openmiura/workers/` (stubs only) | 8 | 8 | 0 % |
| `openmiura/builtin_skills/` (empty) | 0 | 0 | — |

The four governance-relevant packages — `application`,
`extensions`, `persistence`, `agents` — sit comfortably above
84 %. Coverage drops on `interfaces`, `tools`, `channels` which
are largely IO-bound surfaces.

## Where the 7,496 missing lines live

The 20 files with the lowest coverage (≥ 20 statements):

| Coverage | Stmts | Missing | File |
|---:|---:|---:|---|
| 0 % | 31 | 31 | `core/workflows/models.py` |
| 11 % | 123 | 110 | `core/llm/anthropic_client.py` |
| 17 % | 111 | 92 | `tools/web_fetch.py` |
| 18 % | 77 | 63 | `core/llm/openai_compat.py` |
| 19 % | 57 | 46 | `core/llm/ollama.py` |
| 25 % | 624 | 466 | `interfaces/broker/routes/admin/_openclaw_a.py` |
| 30 % | 69 | 48 | `channels/mcp_server.py` |
| 33 % | 94 | 63 | `channels/telegram.py` |
| 36 % | 285 | 183 | `interfaces/broker/routes/admin/_openclaw_b.py` |
| 39 % | 70 | 43 | `interfaces/broker/routes/admin/_evaluations.py` |
| 41 % | 212 | 125 | `interfaces/broker/routes/admin/_canvas.py` |
| 42 % | 171 | 100 | `interfaces/broker/routes/admin/_releases.py` |
| 42 % | 72 | 42 | `interfaces/http/routes/admin/secrets.py` |
| 46 % | 113 | 61 | `core/db.py` |
| 49 % | 51 | 26 | `interfaces/broker/routes/admin/_apps.py` |
| 49 % | 79 | 40 | `application/runtime_adapters/external/service/_health_mixin.py` |
| 50 % | 30 | 15 | `interfaces/broker/routes/admin/_costs.py` |
| 50 % | 90 | 45 | `interfaces/broker/routes/admin/_voice.py` |
| 53 % | 38 | 18 | `interfaces/http/routes/admin/workflows.py` |
| 53 % | 36 | 17 | `application/memory/service.py` |

### What these gaps mean

1. **LLM clients** (`anthropic_client.py`, `openai_compat.py`,
   `ollama.py`) sit at 11–19 %. They are real-network adapters;
   tests do not call live LLM APIs. This is the expected state
   for a project that does not bundle mock-LLM fixtures.
2. **`tools/web_fetch.py`** at 17 % — same reasoning. Outbound
   HTTP is mocked only minimally.
3. **`channels/mcp_server.py`, `channels/telegram.py`** at
   30–33 % — channel adapters whose integration tests would
   require running the actual transports.
4. **`interfaces/broker/routes/admin/_openclaw_*.py`** at 25–36 %
   — broker admin endpoints; many run only when the broker
   surface is enabled in a deployment profile. The equivalent
   HTTP routes under `interfaces/http/routes/admin/` are
   substantially better covered (see below).
5. **`core/workflows/models.py`** at 0 % stands out and warrants
   inspection — it is the only ≥ 20-stmt file with zero coverage
   despite living in a path that tests reach often.
6. **`core/db.py`** at 46 % — the SQLite/Postgres connection
   adapter. The split between backends produces branches that
   only one CI configuration hits at a time.

## What is well covered

33 files with ≥ 10 statements sit at 100 %. Notably:

- Every `__init__.py` aggregator in `application/admin/service/`,
  `application/canvas/service/`, and the four `external/*/`
  sub-packages — the late-binding propagation pattern is
  exercised end-to-end.
- All `tests/test_regulated_policy_packs.py` targets.
- `openmiura/endpoints/admin.py` compat shim.

## Practical interpretation

- **81.8 % is in a healthy band** for a project of this size and
  scope. It is consistent with a codebase whose external
  adapters (LLM providers, channel transports, broker surfaces)
  are intentionally not exercised in CI.
- **Setting a CI gate today** at 80 % would be both reasonable
  and unlikely to bite false positives, *if* we accept that
  the LLM/HTTP integration paths will not move it up. A gate
  at 85 % would force test additions on every PR that touches
  the LLM/channel layers — friction for little marginal value.
- **No urgent action is required** before raising the question
  "should we add a coverage gate?" — that is the next
  decision, captured separately if/when it is made.

## What this baseline does **not** cover

- **Branch coverage**: only line coverage is captured here.
  Branch / arc coverage would surface a different shape (lower
  numbers on the dispatch-heavy mixins). Worth measuring later
  if it becomes a question.
- **Mutation coverage**: untouched.
- **Property-based testing**: untouched.
- **External integration**: by design — the figure here
  represents *unit + in-process integration only*.

## How to refresh

```bash
# From the project root, with an env that has pytest-cov installed:
pytest -q --tb=no -p no:cacheprovider \
    --cov=openmiura --cov-report=term \
    --cov-report=json:reports/coverage_baseline.json
python scripts/_analyze_coverage.py   # if re-creating the helper

# Then rewrite this document with the new numbers.
```

`reports/coverage_baseline.json` is checked in as the
machine-readable counterpart to this human-readable summary.
