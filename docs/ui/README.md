# openMiura UI

There are **two** UIs in the repository:

- **`openmiura/ui/static/`** — the legacy UI. Vanilla JS,
  one-page console (sidebar + tabs), PWA-installable. Served at
  `/ui/`. Will be deprecated when the v2 UI reaches feature
  parity.
- **`openmiura/ui/v2/`** — the new UI. Tailwind v4 + Alpine.js,
  three entry points (admin / science / interview), shared
  design tokens. Served at `/ui/v2/`. **Current focus.**

This directory (`docs/ui/`) holds the contribution and
maintenance docs for the v2 UI. See:

- [`styling.md`](styling.md) — design tokens, colour palette,
  typography, how to recompile the CSS.
- [`architecture.md`](architecture.md) — coming with PR-A2.
- [`components.md`](components.md) — coming with PR-A4.
- [`testing.md`](testing.md) — coming with PR-A5.

## Current status

Phase A (foundations) is in progress:

| PR | Title | Status |
|---|---|---|
| A1 | Tailwind v4 + design tokens + branding + tooling | **this PR** |
| A2 | Layout shell (sidebar, topbar, theme switcher, breadcrumbs) | pending |
| A3 | Auth / session module shared by the 3 UIs | pending |
| A4 | Icon stack (Lucide) + base components | pending |
| A5 | CI gate (recompile-diff) + .gitattributes + docs finalised | **this PR** |

After Phase A, the actual UI surfaces ship in:

- **Phase B (admin UI)** — 7 PRs.
- **Phase C (science UI)** — 4 PRs.
- **Phase D (interview UI)** — 3 PRs.
- **Phase E (polish + a11y)** — 4 PRs.

For the full plan see the session message that opens the UI
refactor on `phase/ui-a1-tailwind-foundations`.
