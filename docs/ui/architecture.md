# UI v2 architecture

The new UI is a static, self-contained client served by the
FastAPI app. There is **no Node.js at runtime, no SPA router, no
build pipeline in CI**; pages are real HTML files that load the
shared JS modules and Tailwind-compiled CSS that ship in the
same directory tree.

This document explains the moving parts so a future contributor
can extend the UI without having to re-derive the conventions
from the code.

## File layout

```
openmiura/ui/v2/
    src/
        input.css            # Tailwind v4 + @theme tokens (source)
        shell.html           # reference template for the shell snippet
        auth_panel.html      # reference template for the auth dropdown
    static/                  # everything served at /ui/v2/
        openmiura.css        # compiled CSS, committed
        index.html           # design-tokens preview (A1)
        admin.html           # admin UI entry point  (A2 shell, B1-B7 content)
        science.html         # science UI entry      (A2 shell, C1-C4 content)
        interview.html       # interview UI entry    (A2 shell, D1-D3 content)
        components.html      # component gallery (A4)
        js/
            theme.js         # light/dark toggle, OS detection, localStorage
            api.js           # fetch wrapper with auth headers + 401 emit
            auth.js          # connection state, token / login modes
            shell.js         # Alpine factories: omShell, omAuthPanel
            icons.js         # Lucide icon registry (34 inlined SVGs)
            components.js    # Alpine factories: omToastTray, omModalFor
            alpine.min.js    # Alpine.js 3.x self-hosted
```

## Module dependency order

Browsers execute the page top-down. The `<head>` of every entry
point loads the JS in this order; **changing the order breaks
late binding**.

```
theme.js     → applies the initial theme before paint (no FOUC)
api.js       → defines window.omApi (used by auth.js)
auth.js      → defines window.omAuth + validates a stored token
shell.js     → defines window.omShell, window.omAuthPanel
icons.js     → defines window.omIcon, window.omIconNames
components.js→ defines window.omToasts, window.omModal,
               + omToastTray, omModalFor
alpine.min.js→ Alpine.js, loaded with `defer`. Initialises after
               the DOM is ready and finds every `x-data` already
               wired to the factories above.
```

## Reactivity model

The page uses **two layers** that talk to each other through
custom DOM events:

1. **Plain modules** (`theme.js`, `api.js`, `auth.js`,
   `omToasts`, `omModal`) own the canonical state and emit
   events:

   ```
   om:theme           detail: { theme }
   om:auth:changed    detail: <auth state snapshot>
   om:auth:logged-in  detail: <auth state snapshot>
   om:auth:logged-out (no detail)
   om:auth:expired    (no detail) — fired by api.js on 401
   ```

2. **Alpine components** (`omShell`, `omAuthPanel`, `omToastTray`,
   `omModalFor`) subscribe to those events inside their `init()`
   hooks and mirror the relevant slice into reactive state.

This split means non-Alpine code (e.g. console debugging, future
features that do not use Alpine) can still trigger UI updates by
emitting the same events.

## Adding a new page to a UI

Concrete steps for adding (say) a Runtimes page to the admin UI:

1. **Add the nav item** in `shell.js` under `NAV_GROUPS.admin`.
2. **Create a new HTML file** under `openmiura/ui/v2/static/`
   that mirrors `admin.html`'s shell setup, changing only the
   `activeId`, `breadcrumbs` and the `<main>` body.
3. **Use the component primitives** from
   `docs/ui/components.md` (or the live `components.html`
   gallery) — `.om-card`, `.om-table`, `.om-btn`, etc.
4. **Hit the broker via `window.omApi`** for data fetching. The
   auth header is added automatically when the user is connected.
5. **Show feedback with `window.omToasts.success/danger`** for
   actions; use `window.omModal.open('id')` for confirmations.
6. **Re-run** `python scripts/build_ui_css.py` if any new
   utility class was introduced.

## What we do not have, by design

- **No SPA router**. Each "page" is a real HTML file with its
  own URL. The shared shell renders inside each one. A future
  contributor can introduce a router if the URL count becomes
  unmanageable; until then this keeps things honest and easy
  to debug.
- **No build step at deploy time**. CSS is precompiled and
  committed. JS is loaded as `<script src=...>`. The FastAPI
  app serves everything as-is.
- **No bundler**. Each JS module is self-contained and uses the
  global `window.om*` namespace. This is intentional; reach for
  a bundler the day a single module exceeds 500 lines (none does
  today).
- **No i18n**. Strings are inline in HTML and JS, English only.
  Add `intl` support if the audience expands beyond
  EU-pharma / UAL-internal.

## See also

- [`README.md`](README.md) — directory index and Phase progress.
- [`styling.md`](styling.md) — design tokens and CSS workflow.
- [`components.md`](components.md) — coming with the gallery
  hardening pass.
