# Mixin-package split pattern

The openMiura codebase enforces a soft "no production `.py` over
1,500 lines" ceiling (from `CLAUDE.md` §5 criterion 1). When a
single class grows past that ceiling — as `AuditStore`,
`AdminService`, `LiveCanvasService`, several `OpenClaw*Service`
classes and the openclaw mixins all did — we apply a deterministic
**mixin-package** pattern instead of either (a) leaving the file
oversized or (b) breaking the public API.

This document captures the pattern so future refactors stay
consistent. It is a how-to, not history; for the chronology of
which file was split when, see `docs/_workjournal/`.

---

## When to apply the pattern

| Symptom | Apply mixin-package pattern? |
|---|---|
| One file > 1,500 lines, one class, many small methods | **Yes** |
| One file > 1,500 lines, mostly module-level functions | No — split into separate modules by topic |
| One method > 1,500 lines (e.g. a giant dispatcher) | First refactor the method (see "Method refactor" below); then split the file if it still exceeds the ceiling |
| Two unrelated classes in one big file | First separate the classes into two files; revisit each |
| Public API used outside the package | Compatible: the pattern preserves the public class name and signature. Always preferable to renaming |
| Heavy module-level state, complex caches | Caution. Inspect for global state before splitting |

The pattern works particularly well when the class has been
written incrementally over time and its 200+ methods naturally
cluster by sub-domain (analytical workflows, alerts, exports,
catalog management, etc.).

---

## Target layout

The single file `path/to/foo.py` becomes a **package** with the
same import path:

```
path/to/foo/
    __init__.py                   # the public class lives here
    _<domain_a>_mixin.py
    _<domain_b>_mixin.py
    _<domain_c>_mixin.py
    ...
```

Constraints:

- The public class **name** (`Foo`) is preserved unchanged.
- The public class **constructor signature** is preserved unchanged.
- The public **method set** is preserved unchanged (same names,
  same signatures, same docstrings, same decorators).
- External callers (`from path.to.foo import Foo`) keep working
  with no edit. Internal callers (`self.method(...)`) keep
  working because of Python MRO.

The package's `__init__.py` defines the final class via mixin
inheritance:

```python
class Foo(
    _FooBaselinePromotionMixin,
    _FooAlertsMixin,
    _FooDataMixin,
    _FooHelpersMixin,
):
    # original class constants + __init__ live here, unchanged.
    ...
```

Each `_<domain>_mixin.py` declares an internal class
`_Foo<Domain>Mixin` whose methods are the original methods
extracted verbatim — same body, same indentation under the
class block.

---

## Step-by-step procedure

The procedure that follows applied identically to the splits in
PRs #23, #24, #25, #26, #29, #30, #31. Use it as a checklist.

1. **Read the original file with AST**. Get the class node and
   walk its body to collect (a) class-level constants and
   `__init__` (these stay on the final class), and (b) every
   `FunctionDef` / `AsyncFunctionDef` (these move to mixins).

2. **Classify methods by domain**. Naming-prefix heuristics
   typically work (`_baseline_promotion_*` → baseline_promotion
   bucket, `_alert_*` → alerts bucket, `_canvas_node_*` →
   canvas_node bucket, etc.). When a bucket exceeds 1,500
   lines, sub-split it at line midpoint and append `_a`/`_b`
   (or `_a`/`_b`/`_c` for three-way).

3. **Generate each mixin file**. Use a single
   `MIXIN_HEADER` template that includes:
   - The full import block from the original file. **Replicate
     the whole imports section in every mixin module.**
     Stripping unused imports is what produces `NameError` on
     CI integration paths — the original file had every import
     somewhere in its body and the cost of full replication is
     trivial.
   - A module-level sentinel:
     `<PublicClassName>: type | None = None`. This declares the
     symbol so internal `<PublicClassName>.foo(...)` calls from
     `@staticmethod` bodies do not raise `NameError` at import
     time. The sentinel is rebound by the package `__init__.py`
     (see step 6).
   - The mixin class definition `class _Foo<Domain>Mixin:`
     followed by the verbatim method blocks. Indentation under
     the new class is unchanged — methods were already at the
     "indent inside a class" level in the original file.

4. **Generate the package `__init__.py`**:
   - Re-import the original module-level imports.
   - Import every mixin class with `from ._<domain>_mixin import _Foo<Domain>Mixin`.
   - Define `class Foo(_FooMixin1, _FooMixin2, ...):` with the
     original constructor and class constants in the body.
   - At the end of the file, **rebind the public class on every
     mixin module**:

     ```python
     from path.to.foo import _<domain_a>_mixin as _m_a
     # ... one import per mixin ...
     for _mod in (_m_a, _m_b, _m_c, ...):
         _mod.Foo = Foo
     del _mod
     ```

5. **Delete the original file** with `git rm path/to/foo.py`.
   Because step 4 created `path/to/foo/__init__.py` with the
   same module path, all existing `from path.to.foo import Foo`
   imports keep resolving.

6. **Verify**:
   - `python -c "from path.to.foo import Foo; instance = Foo(...)"` — basic import smoke.
   - `pytest tests/unit` — fast feedback.
   - `python scripts/run_canonical_demo.py` — confirm the demo
     report still says `success=True`.
   - `pytest -q` (full suite, ~10-15 minutes locally) — final
     check before pushing.

7. **CI is the canonical signal**. Local pytest can miss things
   that CI catches:
   - `NameError` in lazily-executed code paths (e.g. HTTP
     endpoints that only fire under specific test fixtures).
   - Late-binding chains that need extra propagation (see
     "Sub-package late-binding" below).

   Push the branch and watch the full pytest job on CI before
   merging.

---

## Six lessons that bit us during the cleanup

These are formalised from the workjournal entries of the
2026-05 cleanup session. Read them before applying the pattern
again.

### 1. Replicate the full imports block in every mixin

When sub-splitting a single file, the temptation is to ship a
trimmed-down import set per mixin (only the names that mixin
actually uses). This fails on CI for at least three reasons:

- Some imports are *side-effecting* (they register handlers,
  populate registries, install monkeypatches). A trimmed mixin
  inadvertently changes ordering or skips the side effect.
- Lint tools are happy because the unused-import warning is
  suppressed by the import being used somewhere in the class
  body; but the *body* references it indirectly (through a
  string literal passed to `getattr`, or through a class
  attribute set in `__init__`).
- The cost of replication is zero (a few lines per file). The
  cost of debugging the failure mode is hours.

**Rule:** copy the original file's full imports block into every
sub-file. Don't try to be clever. Memory:
`feedback_split_imports.md`.

### 2. Relative imports become absolute when the package deepens

If the original file had `from .helpers import canvas_safe_call`,
and the file is now `path/to/foo/_alerts_mixin.py`, the relative
import still works (the helpers module is one level up: `..helpers`).
But if we later sub-split `_alerts_mixin.py` into
`_alerts_mixin/_a.py` + `_alerts_mixin/_b.py`, the import has to
become absolute (`from path.to.helpers import canvas_safe_call`).
Otherwise the deeper sub-modules import nothing.

**Rule:** when a single-file mixin becomes a sub-package, rewrite
all relative imports inside that sub-tree to absolute form.

### 3. Late-binding sentinel must be in every mixin module

`@staticmethod`s that reference the public class by name
(`Foo._foo(arg)`) cannot resolve the name at import time after
the split. The pattern `<PublicClassName>: type | None = None`
at module scope makes the name *available*; the rebind at the
end of `__init__.py` gives it a *value* at the moment the
package finishes loading.

If you skip the sentinel in a mixin, every call to
`<PublicClassName>.foo(...)` from inside that mixin's
`@staticmethod` raises `NameError` at call time. Tests pass
locally if the path is not exercised; CI fails the moment a
production code path hits it.

**Rule:** declare the sentinel in every mixin module, no
exceptions.

### 4. Late-binding propagation in sub-packages

When the parent package rebinds `Foo = <cls>` on a sub-package
module (`some_sub_package.Foo = Foo`), Python does not
automatically propagate the assignment to the sub-package's
child modules.

If the sub-package itself contains sub-mixins that also reference
`<PublicClassName>` by name, we need a small `_PackageProxy`
helper in the sub-package's `__init__.py` that intercepts
`__setattr__` and pushes the value down to every sub-module.
See `openmiura/application/canvas/service/_node_actions_mixin/__init__.py`
for the canonical implementation.

**Rule:** if your split goes two levels deep, add the
`_PackageProxy` propagation. One level deep does not need it.

### 5. Class-header truncation when halving a mixin

Halving an oversized mixin at the line midpoint requires careful
identification of where the class body **ends for the first half
and begins for the second**. The cut point must be **before the
first decorator of the next method**, never at
`methods[0].lineno - 1` of the second half.

If you cut wrong, the first method of the second half receives an
orphan `@staticmethod` decorator at the top of its class body,
silently turning an instance method into a `@staticmethod` with
`self` as a positional parameter. Tests pass because Python is
happy to call a `@staticmethod` with `self` as first positional
arg, but the method silently loses its identity in `isinstance`
checks and in `inspect.signature`.

**Rule:** in the AST traversal, compute the cut point as
`min(d.lineno for d in target_method.decorator_list)` of the
first method that goes to the second half, **not** the method's
own `lineno`. If a method has no decorators, fall back to
`method.lineno`.

### 6. `@staticmethod` with `self` as first parameter is a real pattern

In a handful of places the original code defines a
`@staticmethod` that takes `self, gw, ...` as parameters, and
the caller does `ClassName._static_method(self, gw=...)`. This
is intentional in legacy code — it bypasses the `self` binding
to let the static-context method be called from any instance.

After a split, this pattern still works (Python doesn't care), but
any inadvertent duplication of `@staticmethod` decorators (see
lesson 5) breaks it loudly. Worth a `# legacy staticmethod
calling pattern` comment next to these methods when found, so a
future maintainer doesn't "fix" it by removing the decorator.

---

## Method refactor (before splitting the file)

When the bottleneck is **one method**, not the file, refactor
the method first. The classic example was `execute_node_action`
in the canvas service: 2,957 lines in one function, an outer
`if node_type == ...` dispatcher with 4 branches and a deeply
nested `if normalized_action == ...` dispatcher in the largest
branch with 19 sub-branches.

The two-pass refactor that worked:

1. **Outer dispatch**. Each branch of the outer `if` becomes
   its own private method (`_execute_workflow_action`,
   `_execute_approval_action`, etc.). The dispatcher calls them
   with the outer-scope locals passed as `**ctx` kwargs and
   returns the result dict.

2. **Inner dispatch**. The largest branch (`baseline_promotion`)
   gets the same treatment: each `normalized_action` slug
   becomes a private method
   (`_baseline_promotion_action_<slug>`). The
   `_execute_baseline_promotion_action` reduces to a thin
   dispatcher.

Mechanics:

- Each handler receives the **complete set of outer locals** as
  `**ctx` kwargs. Identifying which specific names a branch
  uses with AST analysis is fragile; passing everything is
  simpler and only costs a bit of kwarg verbosity.
- The body of each handler is the original branch body with
  indentation dedented by 4 spaces (the branch lived at indent
  12 inside an `if`/`elif`; the new method body lives at indent
  8). Use AST to compute the exact line range; don't try to
  guess by string matching.
- The final statement of the handler returns the value that the
  original branch assigned to the outer `result` variable.

After this refactor, the largest method on the class drops from
2,957 lines to under 500. The file as a whole stays oversized
(handler signatures with many kwargs are verbose), so apply the
mixin-package split next.

---

## Worked examples

| Original file | Lines | Refactor type | Result |
|---|---:|---|---|
| `openmiura/core/audit.py` | 5,693 | Persistence repos behind facade + delegator compaction | 755 lines (facade) + 12 repos |
| `openmiura/interfaces/http/routes/admin.py` | 4,841 | Sub-router package | 16 sub-routers, none > 1,500 |
| `openmiura/application/canvas/service.py` | 11,519 | Mixin package + method refactor + sub-package | 13 mixins, all < 1,500 |
| `openmiura/application/admin/service.py` | 6,734 | Mixin package | 17 mixins, all < 1,500 |
| `openmiura/application/runtime_adapters/external/baseline_rollout_support.py` | 7,961 | Sub-mixin package | 11 sub-mixins, all < 1,500 |
| `openmiura/application/runtime_adapters/external/scheduler.py` | 7,263 | Sub-mixin package | 8 sub-mixins, all < 1,500 |
| `openmiura/interfaces/broker/routes/admin.py` | 4,216 | Sub-route package | 15 sub-routes, all < 1,500 |
| `openmiura/core/migrations.py` | 2,747 | Batch sub-modules | All batches < 1,500 |
| `openmiura/application/runtime_adapters/external/baseline_rollout_management.py` | 2,709 | Sub-mixin package | 5 sub-mixins, all < 1,500 |
| `openmiura/application/runtime_adapters/external/service.py` | 2,579 | Sub-mixin package | 8 sub-mixins, all < 1,500 |
| `openmiura/application/runtime_adapters/external/evidence_builders.py` | 1,629 | Sub-mixin package | 5 sub-mixins, all < 1,500 |

The corresponding architecture docs that describe each split:

- [`persistence.md`](persistence.md)
- [`canvas_service.md`](canvas_service.md)
- [`admin_service.md`](admin_service.md)
- [`runtime_adapters.md`](runtime_adapters.md)
