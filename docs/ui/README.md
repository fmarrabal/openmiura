# openMiura UI v2

This document describes the UI v2 architecture: the
self-contained, no-Node frontend served at `/ui/v2/...` by
the openMiura HTTP app.

> If you came here to **edit** the UI, the only commands you
> need are at the bottom. If you came to **understand** how
> the pieces fit together, read top-down.

There are **two** UIs in the repository:

- **`openmiura/ui/static/`** — the legacy UI. Vanilla JS,
  one-page console (sidebar + tabs), PWA-installable. Served
  at `/ui/`. Will be deprecated once v2 reaches full feature
  parity.
- **`openmiura/ui/v2/`** — the new UI. Tailwind v4 + Alpine.js,
  three entry points (admin / science / interview), shared
  design tokens. Served at `/ui/v2/`. **Current focus.**

The rest of this document is about the **v2** UI.

---

## What ships

Three independent profiles, each addressing a distinct user:

| Profile | Path | Audience | Endpoints | Views |
|---|---|---|---|---|
| Admin | `/ui/v2/admin.html` | Operator / SRE | Heavy on `/admin/*` | 7 |
| Science | `/ui/v2/science.html` | Lab scientist | `/http/message` + read-modeled `/admin/operator/*` | 5 |
| Interview | `/ui/v2/interview.html` | QA / RA reviewer | **none** (offline) | 3 |

Plus two utility pages:

- `/ui/v2/index.html` — design-tokens preview (Phase A1).
- `/ui/v2/components.html` — base components gallery (Phase A4).

### Admin views

| View | activeId | Backend surface | Write? |
|---|---|---|---|
| Dashboard | `dashboard` | 5 reads (status / sessions / events / runtimes / canvas) | — |
| Runtimes & dispatches | `runtimes` | 5 reads + recovery job POST | confirmed |
| Policies editor | `policies` | 2 reads + 3 read-modeled POSTs | — |
| Secrets governance | `secrets` | 4 reads + 1 read-modeled POST | — |
| Identities & RBAC | `identities` | 2 reads + 2 read-modeled POSTs | confirmed (link) |
| Channels wizard | `channels` | 1 read + 1 validate + 1 disk-write | confirmed |
| Evidence packs | `evidence` | 1 read + 1 compliance export | confirmed |

The remaining sidebar items (Dispatches, Approvals,
Workflows, System, Event log, Tool calls) are reserved as
sidebar placeholders for future work.

### Science views

| View | activeId | Backend surface |
|---|---|---|
| Chat with agent | `chat` | `POST /http/message` |
| Upload spectrum | `upload` | same (files staged client-side, metadata in `message.metadata.staged_file`) |
| Review drafts | `review` | `GET /admin/operator/overview` |
| My approvals | `approvals` | overview + `POST /admin/operator/approvals/{id}/actions/{action}` |
| My evidence | `history` | `GET /admin/compliance/summary` |

### Interview views

All three (`overview`, `walkthrough`, `evidence`) are offline.
The page loads a single `interview/demo.js` module with three
factories sharing a synthetic dataset.

---

## Architecture

### No Node, no bundler

The runtime stack is intentionally tiny:

- **Tailwind CSS v4** compiled by the standalone CLI binary
  (downloaded into `tools/` on first run, gitignored).
  Compiled output (`openmiura/ui/v2/static/openmiura.css`)
  IS committed to the repo; the input is
  `openmiura/ui/v2/src/input.css`.

- **Alpine.js 3.x** self-hosted at `static/js/alpine.min.js`
  (no CDN). Provides the `x-data`, `x-text`, `x-show`,
  `x-for`, `x-if` reactivity used across every view.

- **No JS framework** — no React, no Vue, no Svelte. Every
  view is a vanilla Alpine factory.

- **No build step** beyond `python scripts/build_ui_css.py`.

This keeps the "single Python deployable" invariant: an
operator installs openMiura via pip and the UI works at
`/ui/v2/...` without any extra step.

### Per-card state machine

Every read in every view follows the same shape:

```js
function emptyCard() {
  return { state: 'idle', data: null, error: null, raw: '' };
}
```

Card states are: `idle`, `loading`, `loaded`, `error`. The
`raw` field carries the verbatim JSON the backend returned
so a `show raw` toggle in the UI surfaces it one click away.
This is the most-used debug primitive across the project —
it removed the need for a separate "Debug pane" in Phase B.

### Cross-module communication

Modules talk via custom DOM events on `document`. No global
event bus. The four contract events:

- `om:theme` — fired when the theme switches.
- `om:auth:changed` — fired on any auth-state change.
- `om:auth:logged-in` — fired specifically on successful auth.
- `om:auth:logged-out` — fired on disconnect or 401.

A view that needs to react to login subscribes in `init()`:

```js
init() {
  if (this._authed()) this.refresh();
  document.addEventListener('om:auth:logged-in',  () => this.refresh());
  document.addEventListener('om:auth:logged-out', () => this._clear());
}
```

### Auth + API helpers

- `window.omApi` — fetch wrapper returning
  `{ok, status, data, error, raw}`. 401 emits
  `om:auth:expired`.
- `window.omAuth` — token / login / session state,
  persisted under `openmiura.v2.auth.*` localStorage keys.

### Modal + toast managers

- `window.omModal` — `.open(id)`, `.close(id)`,
  `.closeAll()`. Esc closes the topmost.
- `window.omToasts` — `.info()`, `.success()`, `.warning()`,
  `.danger()`, `.dismiss(id)`, `.clear()`.

A view that ships a confirmed write registers its modal via
`omModalFor('my-modal-id')` in the template and calls
`omModal.open('my-modal-id')` from the factory.

### Icon registry

`window.omIcon(name, extraClass)` returns inline SVG markup
for one of 34 Lucide icons baked into `static/js/icons.js`.
No external font, no SVG sprite. Adding an icon means adding
an entry to the registry.

---

## localStorage contract

All UI v2 keys are namespaced under `openmiura.v2.*` so a
debug tool inspecting the operator's profile knows what is
ours:

| Key | Owner | Lifecycle |
|---|---|---|
| `openmiura.v2.theme` | `js/theme.js` | persists light/dark choice |
| `openmiura.v2.auth.baseUrl` | `js/auth.js` | broker base URL |
| `openmiura.v2.auth.mode` | `js/auth.js` | `token` or `login` |
| `openmiura.v2.auth.token` | `js/auth.js` | bearer token |
| `openmiura.v2.auth.username` | `js/auth.js` | last login username |
| `openmiura.v2.science.messages` | `science/chat.js` | chat transcript (capped at 200 turns) |
| `openmiura.v2.science.session_id` | `science/chat.js` | chat session id |
| `openmiura.v2.science.uploads` | `science/upload.js` | staged-file metadata (NOT the bytes) |

---

## CI gate

`.github/workflows/ui-css-check.yml` runs
`python scripts/build_ui_css.py --check` on every PR. The
script recompiles `input.css` into a temp file and diffs
against the committed `openmiura.css`. **If they differ, CI
fails.** The fix message tells the operator what to do:

```text
python scripts/build_ui_css.py
git add openmiura/ui/v2/static/openmiura.css
git commit --amend  # or a new commit
```

Line endings are pinned to LF for all web assets via
`.gitattributes` so a Windows-authored commit cannot break
the diff with autocrlf.

---

## Accessibility (Phase E polish)

- Every sidebar nav button carries `aria-current="page"` when
  active.
- The sidebar `<nav>` carries `aria-label` matching the
  profile.
- Group headers are wired via `aria-labelledby` so screen
  readers announce them as group titles.
- Icon spans have `aria-hidden="true"` so a screen reader
  doesn't try to announce the SVG.
- Every confirmed-write modal uses
  `role="dialog" aria-modal="true" aria-labelledby="..."`.
- Keyboard-only focus rings via `:focus-visible` (Phase E
  polish): mouse users see no rings, keyboard users see a
  high-contrast `accent-500` outline on every interactive
  element.

---

## Adding a new view

1. **Pick a sidebar id.** Either reuse an existing
   placeholder from `js/shell.js` (look in the `NAV_GROUPS`
   profile you are extending) or add a new entry.

2. **Write the Alpine factory.** Create
   `static/js/<profile>/<name>.js` exposing
   `window.<profileName><Name>()`. Follow the per-card state
   machine. Wire to `om:auth:logged-in` /
   `om:auth:logged-out`.

3. **Add the view template.** In the corresponding
   `<profile>.html`, add a
   `<template x-if="activeId === '<id>'">` block. Narrow the
   placeholder template's `x-if` to exclude the new id.

4. **Load the script.** Add a `<script src="...">` line in
   the page `<head>`.

5. **Recompile CSS** if your template references any new
   utility classes:
   ```
   python scripts/build_ui_css.py
   ```

6. **Add tests** to `tests/unit/test_ui_v2_assets.py`. The
   minimum set: factory exposure, endpoint surface, modal
   id (if applicable), auth event wiring, HTML mounting.
   Live-mount test gets a new `/ui/v2/js/<profile>/<name>.js`
   entry.

7. **Run the full pytest suite** before pushing — the
   project pins doc-related tests that only show up at the
   root level, not under `tests/unit`.

---

## Commands

```bash
# Local CSS rebuild
python scripts/build_ui_css.py            # minified
python scripts/build_ui_css.py --no-minify
python scripts/build_ui_css.py --watch    # live-rebuild

# CI gate (recompile + diff)
python scripts/build_ui_css.py --check

# Run the UI-only test suite
pytest tests/unit/test_ui_v2_assets.py -q

# Full project suite (matches CI)
pytest -q
```

---

## Sibling docs

- [`styling.md`](styling.md) — design tokens, colour palette,
  typography, how to recompile the CSS.
- [`architecture.md`](architecture.md) — deep-dive on shell
  + auth wiring (PR-A2 / A3).
- [`testing.md`](testing.md) — the CI gate, the regression
  tests that pin contracts (PR-A5).

---

## Map: PRs that shipped this UI

| Phase | PRs | Outcome |
|---|---|---|
| A | #41–#45 | Foundations (tokens, shell, auth, components, CI gate). |
| B | #46–#52 | 7 admin views. |
| C | #53–#55 | 5 science views. |
| D | #56 | 3 interview views. |
| E | (this PR) | Polish (a11y, focus rings, docs). |
