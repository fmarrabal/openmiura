# Styling — design tokens & CSS workflow

The openMiura UI v2 is built on **Tailwind CSS v4** with all
design tokens declared in a single `@theme` block under
[`openmiura/ui/v2/src/input.css`](../../openmiura/ui/v2/src/input.css).

The compiled stylesheet
[`openmiura/ui/v2/static/openmiura.css`](../../openmiura/ui/v2/static/openmiura.css)
is **checked in**. Editing the input file requires recompiling.

## Branding

> The brand is deliberately **regulatory-serious**, not
> chatbot-y. The palette and typography emphasise trust and
> readability over playfulness.

### Palette

| Scale | Use | Anchor (500) |
|---|---|---|
| `primary` | Brand navy. Headers, primary actions, brand chrome. | `#2d619c` (50–950 around `#0a2540`) |
| `accent` | Cyan. Interactive accents, focus rings, links on dark surfaces. | `#06b6d4` (cyan-500) |
| `success` | Approvals, healthy state, stable releases. | `#10b981` (emerald-500) |
| `warning` | Pending approvals, partial controls. | `#f59e0b` (amber-500) |
| `danger`  | Denied actions, broken controls, errors. | `#dc2626` (red-500) |
| `info`    | Informational hints, neutral notifications. | `#0ea5e9` (sky-500) |
| `surface` | Backgrounds, borders, text. Slate-based, neutral in both themes. | `#64748b` (slate-500) |

All scales expose tokens for `50` through `950`. Use the closer
weight to the contrast you need — `bg-primary-900` for solid
brand chrome, `bg-primary-100` for subtle backgrounds.

### Typography

| Family | Token | Where |
|---|---|---|
| **Inter** | `--font-sans` | Default everywhere |
| **JetBrains Mono** | `--font-mono` | `code`, `pre`, IDs, hashes |

Inter is loaded from `https://rsms.me/inter/inter.css` and
JetBrains Mono from a CDN; both will be self-hosted in **Phase E
(PR-E2)** so deployments survive air-gap installs.

### Radius & shadows

| Token | Value | Use |
|---|---|---|
| `--radius-card` | 10 px | Cards, panels, modals |
| `--radius-input` | 8 px | Buttons, inputs, badges |
| `--shadow-card` | subtle | Default card elevation |
| `--shadow-overlay` | medium | Popovers, dropdowns, modals |

### Theme switching

Themes are toggled by setting `data-theme="dark"` on the
`<html>` element. The `input.css` `@layer base` block flips
background and text colours; component-level dark overrides
read `html[data-theme="dark"] &`.

User preference is persisted in `localStorage` under
`openmiura.v2.theme`; initial value falls back to the OS
preference via `(prefers-color-scheme: dark)`.

## How to recompile

The repository commits the compiled CSS. After editing the
input file (or adding new Tailwind utility classes anywhere
under `openmiura/ui/v2/`), regenerate:

```bash
python scripts/build_ui_css.py
```

The script:

1. Downloads the Tailwind CLI standalone binary
   (`tools/tailwindcss` or `.exe`) on first use — no Node.js
   required. The binary is gitignored.
2. Runs the compiler with `--minify` against
   `openmiura/ui/v2/src/input.css` and writes to
   `openmiura/ui/v2/static/openmiura.css`.

For iterative work:

```bash
python scripts/build_ui_css.py --watch
```

To inspect generated output without minification:

```bash
python scripts/build_ui_css.py --no-minify
```

## How to add a new utility or token

1. **Token addition** (colour, font, radius, shadow): edit
   `@theme` in `input.css`. Every value declared there becomes
   a Tailwind utility automatically (`bg-primary-900`,
   `font-mono`, etc.).
2. **Component class**: prefer composing Tailwind utilities in
   HTML. Reserve `@layer components` in `input.css` for primitives
   that are reused everywhere with significant body (currently:
   `om-shell`, `om-card`).
3. **Regenerate** with `scripts/build_ui_css.py` and commit
   both `input.css` and `openmiura.css`.

## CI / verification

A dedicated GitHub Actions workflow,
[`ui-css-check`](../../.github/workflows/ui-css-check.yml), enforces
that the committed `openmiura.css` matches what the compiler
produces from the current `input.css`. It runs on every PR that
touches the UI v2 tree and on every push to `main`. The job:

1. Downloads the Tailwind v4 standalone binary for Linux on the
   runner (~130 MB; under 30 s including cache miss).
2. Runs `python scripts/build_ui_css.py --check` which compiles to
   a temp file and diffs against the committed CSS.
3. Fails with a helpful message if they differ — the message
   spells out the byte sizes and the exact fix command.

This prevents the "edited input.css, forgot to recompile" failure
mode from leaking past review.

### `.gitattributes` enforces LF line endings

Web assets (`*.css`, `*.js`, `*.html`, `*.svg`, `*.json`) are
checked in with LF endings via [`/.gitattributes`](../../.gitattributes).
On Windows, `core.autocrlf` would otherwise rewrite the compiled
CSS to CRLF on checkout, breaking the byte-for-byte CI diff.
`git add --renormalize .` was used once to apply the rule to
already-checked-in files; future contributors do not need to
think about it.

### Local pre-push check

Before pushing changes to anything under `openmiura/ui/v2/`:

```bash
python scripts/build_ui_css.py --check
```

If it fails:

```bash
python scripts/build_ui_css.py
git add openmiura/ui/v2/static/openmiura.css
git commit --amend  # or a new commit
```

## What lives where

```
openmiura/ui/v2/
    src/
        input.css                  # source of truth for tokens
    static/
        openmiura.css              # compiled (commit), served at /ui/v2/openmiura.css
        index.html                 # design-tokens preview (this PR only)
        js/                        # populated in PR-A2..A4
    # admin.html / science.html / interview.html land in subsequent PRs
```

```
scripts/
    build_ui_css.py                # recompile entry point
tools/
    tailwindcss(.exe)              # standalone binary, gitignored, auto-downloaded
docs/ui/
    README.md                      # index
    styling.md                     # this file
```
