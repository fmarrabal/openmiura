"""Smoke checks for the UI v2 static assets.

Phase A1 only ships design tokens + a preview page. These tests
guard the bare invariants:

- The compiled stylesheet exists and is non-empty.
- The preview HTML exists and references the compiled stylesheet.
- The Tailwind input file declares the brand-critical design
  tokens that downstream PRs depend on.

A future PR (A5) replaces the "input file declares X" checks with
a full "recompile and diff" verification.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UI_V2 = ROOT / "openmiura" / "ui" / "v2"
INPUT_CSS = UI_V2 / "src" / "input.css"
OUTPUT_CSS = UI_V2 / "static" / "openmiura.css"
PREVIEW_HTML = UI_V2 / "static" / "index.html"
ADMIN_HTML = UI_V2 / "static" / "admin.html"
SCIENCE_HTML = UI_V2 / "static" / "science.html"
INTERVIEW_HTML = UI_V2 / "static" / "interview.html"
JS_ALPINE = UI_V2 / "static" / "js" / "alpine.min.js"
JS_THEME = UI_V2 / "static" / "js" / "theme.js"
JS_SHELL = UI_V2 / "static" / "js" / "shell.js"
JS_API = UI_V2 / "static" / "js" / "api.js"
JS_AUTH = UI_V2 / "static" / "js" / "auth.js"
JS_ICONS = UI_V2 / "static" / "js" / "icons.js"
JS_COMPONENTS = UI_V2 / "static" / "js" / "components.js"
COMPONENTS_HTML = UI_V2 / "static" / "components.html"

REQUIRED_TOKENS = (
    "--color-primary-900",
    "--color-accent-500",
    "--color-success-500",
    "--color-warning-500",
    "--color-danger-500",
    "--color-info-500",
    "--color-surface-50",
    "--color-surface-900",
    "--font-sans",
    "--font-mono",
    "--radius-card",
    "--radius-input",
    "--shadow-card",
)


def test_compiled_stylesheet_exists() -> None:
    assert OUTPUT_CSS.exists(), f"missing compiled CSS: {OUTPUT_CSS}"
    size = OUTPUT_CSS.stat().st_size
    assert size > 5_000, (
        f"compiled CSS suspiciously small ({size} bytes); did you forget "
        f"to regenerate after editing input.css?"
    )


def test_preview_html_references_compiled_stylesheet() -> None:
    assert PREVIEW_HTML.exists(), f"missing preview HTML: {PREVIEW_HTML}"
    html = PREVIEW_HTML.read_text(encoding="utf-8")
    assert "./openmiura.css" in html, (
        "preview HTML must reference the locally-served openmiura.css "
        "(not a CDN URL); otherwise the design tokens preview breaks"
    )


def test_input_css_declares_brand_tokens() -> None:
    assert INPUT_CSS.exists(), f"missing input CSS: {INPUT_CSS}"
    text = INPUT_CSS.read_text(encoding="utf-8")
    missing = [tok for tok in REQUIRED_TOKENS if tok not in text]
    assert not missing, f"input.css is missing brand tokens: {missing}"


def test_input_css_imports_tailwind() -> None:
    text = INPUT_CSS.read_text(encoding="utf-8")
    assert '@import "tailwindcss"' in text, (
        "input.css must @import \"tailwindcss\" to activate Tailwind v4"
    )


def test_input_css_declares_theme_block() -> None:
    text = INPUT_CSS.read_text(encoding="utf-8")
    assert "@theme {" in text, (
        "input.css must wrap brand tokens in an @theme { ... } block "
        "so Tailwind v4 promotes them to utility classes"
    )


def test_preview_html_has_theme_toggle() -> None:
    """Light/dark theme switching is a Phase-A1 acceptance criterion."""
    html = PREVIEW_HTML.read_text(encoding="utf-8")
    assert 'id="themeToggle"' in html
    assert "data-theme=" in html


# --------------------------------------------------------------------
# Phase A2 — shell + 3 entry points
# --------------------------------------------------------------------


def test_alpine_bundle_present() -> None:
    assert JS_ALPINE.exists(), f"missing Alpine bundle: {JS_ALPINE}"
    size = JS_ALPINE.stat().st_size
    assert 30_000 < size < 200_000, (
        f"Alpine bundle size {size} bytes outside expected range — "
        f"check the CDN download in scripts (or whatever downloaded it)"
    )


def test_theme_module_exposes_public_api() -> None:
    assert JS_THEME.exists()
    text = JS_THEME.read_text(encoding="utf-8")
    # The four public methods every UI v2 page relies on.
    for fn in ("current()", "set(", "toggle()", "respectSystem()"):
        assert fn in text, f"theme.js must define {fn}"
    assert "openmiura.v2.theme" in text, (
        "theme.js must persist the choice under the documented localStorage key"
    )


def test_shell_module_declares_three_navigation_profiles() -> None:
    assert JS_SHELL.exists()
    text = JS_SHELL.read_text(encoding="utf-8")
    for profile in ("admin:", "science:", "interview:"):
        assert profile in text, f"shell.js NAV_GROUPS must declare {profile}"
    # The factory must be exposed globally so HTML `x-data` can reach it.
    assert "window.omShell" in text


@pytest.mark.parametrize(
    ("path", "profile"),
    [
        (ADMIN_HTML, "admin"),
        (SCIENCE_HTML, "science"),
        (INTERVIEW_HTML, "interview"),
    ],
)
def test_entry_point_mounts_shell_with_expected_profile(
    path: Path, profile: str
) -> None:
    assert path.exists(), f"missing entry point: {path}"
    html = path.read_text(encoding="utf-8")
    assert "./openmiura.css" in html
    assert "./js/theme.js" in html
    assert "./js/shell.js" in html
    assert "./js/alpine.min.js" in html
    assert f"profile: '{profile}'" in html, (
        f"{path.name} must invoke omShell with profile '{profile}'"
    )


# --------------------------------------------------------------------
# Phase A3 — auth/api module
# --------------------------------------------------------------------


def test_api_module_exposes_documented_surface() -> None:
    assert JS_API.exists()
    text = JS_API.read_text(encoding="utf-8")
    for fn in ("request(", "get(", "post(", "put(", "del("):
        assert fn in text, f"api.js must define {fn}"
    assert "window.omApi" in text
    # 401 must emit om:auth:expired so omAuth can clean up.
    assert "om:auth:expired" in text


def test_auth_module_exposes_documented_surface() -> None:
    assert JS_AUTH.exists()
    text = JS_AUTH.read_text(encoding="utf-8")
    for fn in (
        "connectWithToken",
        "connectWithLogin",
        "logout",
        "fetchMe",
        "setBaseUrl",
        "setMode",
    ):
        assert fn in text, f"auth.js must define {fn}"
    assert "window.omAuth" in text
    # Persistence keys are part of the public contract; downstream
    # code may inspect localStorage directly during debug.
    for key in (
        "openmiura.v2.auth.baseUrl",
        "openmiura.v2.auth.mode",
        "openmiura.v2.auth.token",
        "openmiura.v2.auth.username",
    ):
        assert key in text, f"auth.js must persist under {key}"
    # Three events that pages can subscribe to.
    for event in (
        "om:auth:changed",
        "om:auth:logged-in",
        "om:auth:logged-out",
    ):
        assert event in text, f"auth.js must emit {event}"


def test_shell_exposes_auth_panel_factory() -> None:
    text = JS_SHELL.read_text(encoding="utf-8")
    assert "omAuthPanel" in text, (
        "shell.js must export omAuthPanel for the topbar dropdown"
    )
    assert "window.omAuthPanel" in text


@pytest.mark.parametrize("path", [ADMIN_HTML, SCIENCE_HTML, INTERVIEW_HTML])
def test_entry_point_loads_auth_modules(path: Path) -> None:
    html = path.read_text(encoding="utf-8")
    assert "./js/api.js" in html
    assert "./js/auth.js" in html
    # x-cloak prevents the auth dropdown flash before Alpine boots.
    assert "x-cloak" in html
    # Each entry point mounts the omAuthPanel via x-data.
    assert 'x-data="omAuthPanel()"' in html


# --------------------------------------------------------------------
# Phase A4 — icon stack + base components
# --------------------------------------------------------------------


_REQUIRED_ICONS = (
    # used by the admin sidebar
    "gauge", "cpu", "send", "shield-check", "scroll-text", "circle-check",
    "key", "users", "plug", "workflow", "settings", "list", "terminal",
    # science sidebar
    "message-circle", "upload-cloud", "file-search", "history",
    # interview sidebar
    "layout-dashboard", "play-circle",
    # toasts + modal close
    "x", "info", "triangle-alert", "circle-alert",
)


def test_icons_module_exposes_required_set() -> None:
    assert JS_ICONS.exists()
    text = JS_ICONS.read_text(encoding="utf-8")
    assert "window.omIcon" in text
    assert "window.omIconNames" in text
    for name in _REQUIRED_ICONS:
        # The registry entries look like `'gauge': `<svg ...>...</svg>`,`.
        assert f"'{name}':" in text, f"icons.js missing required icon: {name}"


def test_components_module_exposes_toast_and_modal_managers() -> None:
    assert JS_COMPONENTS.exists()
    text = JS_COMPONENTS.read_text(encoding="utf-8")
    for name in (
        "window.omToasts",
        "window.omToastTray",
        "window.omModal",
        "window.omModalFor",
    ):
        assert name in text, f"components.js must expose {name}"
    # Toast helpers per type.
    for fn in ("info(", "success(", "warning(", "danger("):
        assert fn in text
    # Escape key closes the topmost modal.
    assert "Escape" in text


def test_components_gallery_page_exists_and_loads_modules() -> None:
    assert COMPONENTS_HTML.exists()
    html = COMPONENTS_HTML.read_text(encoding="utf-8")
    assert "./openmiura.css" in html
    assert "./js/icons.js" in html
    assert "./js/components.js" in html
    assert 'x-data="omToastTray()"' in html
    assert "omModal.open" in html


def test_input_css_declares_component_primitives() -> None:
    text = INPUT_CSS.read_text(encoding="utf-8")
    for cls in (
        ".om-btn",
        ".om-btn--primary",
        ".om-btn--accent",
        ".om-btn--ghost",
        ".om-btn--danger",
        ".om-badge",
        ".om-table",
        ".om-toast",
        ".om-modal",
        ".om-modal-overlay",
    ):
        assert cls in text, f"input.css must declare {cls} (A4 components)"


@pytest.mark.parametrize("path", [ADMIN_HTML, SCIENCE_HTML, INTERVIEW_HTML])
def test_entry_point_loads_icons_components_and_renders_tray(path: Path) -> None:
    html = path.read_text(encoding="utf-8")
    assert "./js/icons.js" in html
    assert "./js/components.js" in html
    # Sidebar items now render an icon via omIcon(item.icon, ...)
    assert "omIcon(item.icon" in html
    # Toast tray placed once per page.
    assert 'x-data="omToastTray()"' in html


# --------------------------------------------------------------------
# Phase A5 — CI gate
# --------------------------------------------------------------------


def test_build_ui_css_supports_check_mode() -> None:
    """The recompile-diff gate is the contract that prevents drift."""
    import subprocess
    import sys as _sys

    script = ROOT / "scripts" / "build_ui_css.py"
    result = subprocess.run(
        [_sys.executable, str(script), "--check"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"build_ui_css.py --check failed (rc {result.returncode}). "
        f"stdout: {result.stdout}; stderr: {result.stderr}"
    )
    assert "up to date" in result.stdout


def test_gitattributes_pins_web_assets_to_lf() -> None:
    """The CI diff fails on Windows-authored commits if `.gitattributes`
    does not force LF on web assets. Regression test against the
    autocrlf bug discovered while wiring A5."""
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for ext in (".css", ".js", ".html", ".svg"):
        assert f"*{ext}" in text, f".gitattributes must pin *{ext} to LF"
    assert "eol=lf" in text


def test_ui_css_check_workflow_exists() -> None:
    """The CI workflow that enforces the recompile-diff gate."""
    wf = ROOT / ".github" / "workflows" / "ui-css-check.yml"
    assert wf.exists(), "missing .github/workflows/ui-css-check.yml"
    text = wf.read_text(encoding="utf-8")
    assert "scripts/build_ui_css.py --check" in text
    # Triggered on PR + main push on UI v2 paths.
    assert "openmiura/ui/v2" in text


# --------------------------------------------------------------------
# Phase B1 — Admin Dashboard
# --------------------------------------------------------------------

JS_ADMIN_DASHBOARD = UI_V2 / "static" / "js" / "admin" / "dashboard.js"


def test_admin_dashboard_module_exposes_factory() -> None:
    assert JS_ADMIN_DASHBOARD.exists()
    text = JS_ADMIN_DASHBOARD.read_text(encoding="utf-8")
    assert "window.adminDashboard" in text
    # Consults the documented endpoints.
    for path in (
        "/admin/status",
        "/admin/sessions",
        "/admin/events",
        "/admin/openclaw/runtimes",
        "/admin/canvas/documents",
    ):
        assert path in text, f"dashboard.js must consult {path}"


def test_admin_html_loads_dashboard_factory_and_renders_view() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "./js/admin/dashboard.js" in html
    assert 'x-data="adminDashboard()"' in html
    # x-if dispatches by activeId so other sections stay lazy.
    assert "activeId === 'dashboard'" in html
    # Empty state when not authenticated.
    assert "!omAuth.state.token" in html or "omAuth.state.token" in html
    # Show-raw toggle pattern is in place.
    assert "showRaw.runtimes" in html
    assert "showRaw.events" in html


def test_index_uses_extracted_theme_module() -> None:
    """The Phase A1 inline theme bootstrap moved into js/theme.js."""
    html = PREVIEW_HTML.read_text(encoding="utf-8")
    assert "./js/theme.js" in html
    # The old inline implementation must be gone (no more raw
    # localStorage.getItem in the page).
    assert "localStorage.getItem('openmiura.v2.theme')" not in html


def test_app_mounts_ui_v2_alongside_legacy_ui() -> None:
    """The /ui/v2 mount must coexist with /ui; mount order matters
    because Starlette resolves prefixes first-match-wins. Regression
    test: declaring /ui before /ui/v2 makes the latter unreachable."""
    import tempfile
    from pathlib import Path as _P

    import yaml as _yaml
    from fastapi.testclient import TestClient

    from openmiura.interfaces.http.app import create_app

    cfg = {
        "server": {"host": "127.0.0.1", "port": 8081},
        "storage": {"backend": "sqlite", "db_path": ":memory:"},
        "admin": {"enabled": False, "token": ""},
        "auth": {"enabled": False},
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        _yaml.safe_dump(cfg, f)
        cfg_path = f.name
    try:
        app = create_app(config_path=cfg_path)
        client = TestClient(app)

        # Legacy UI still served.
        r_legacy = client.get("/ui/")
        assert r_legacy.status_code == 200, "legacy /ui/ must still serve"

        # New UI v2 served at /ui/v2/.
        r_v2 = client.get("/ui/v2/")
        assert r_v2.status_code == 200, (
            "/ui/v2/ must serve index.html; if it returns 404, the "
            "/ui mount was declared first and swallowed the prefix"
        )
        assert b"openMiura UI v2" in r_v2.content

        # Compiled CSS reachable.
        r_css = client.get("/ui/v2/openmiura.css")
        assert r_css.status_code == 200
        assert int(r_css.headers["content-length"]) > 5_000

        # Phase A2 + A3: every entry point + JS module reachable.
        for sub in (
            "/ui/v2/admin.html",
            "/ui/v2/science.html",
            "/ui/v2/interview.html",
            "/ui/v2/js/alpine.min.js",
            "/ui/v2/js/theme.js",
            "/ui/v2/js/shell.js",
            "/ui/v2/js/api.js",
            "/ui/v2/js/auth.js",
            "/ui/v2/js/icons.js",
            "/ui/v2/js/components.js",
            "/ui/v2/js/admin/dashboard.js",
            "/ui/v2/js/admin/runtimes.js",
            "/ui/v2/js/admin/policies.js",
            "/ui/v2/js/admin/secrets.js",
            "/ui/v2/js/admin/identities.js",
            "/ui/v2/js/admin/channels.js",
            "/ui/v2/js/admin/evidence.js",
            "/ui/v2/js/admin/secrets_wizard.js",
            "/ui/v2/js/admin/dispatches.js",
            "/ui/v2/js/admin/approvals.js",
            "/ui/v2/js/admin/debug.js",
            "/ui/v2/js/science/chat.js",
            "/ui/v2/js/science/upload.js",
            "/ui/v2/js/science/review.js",
            "/ui/v2/js/science/approvals.js",
            "/ui/v2/js/science/history.js",
            "/ui/v2/js/interview/demo.js",
            "/ui/v2/components.html",
        ):
            r = client.get(sub)
            assert r.status_code == 200, f"{sub} not served (got {r.status_code})"
    finally:
        _P(cfg_path).unlink(missing_ok=True)


# --------------------------------------------------------------------
# Phase B2 — Admin Runtimes & dispatches
# --------------------------------------------------------------------

JS_ADMIN_RUNTIMES = UI_V2 / "static" / "js" / "admin" / "runtimes.js"


def test_admin_runtimes_module_exposes_factory() -> None:
    assert JS_ADMIN_RUNTIMES.exists(), (
        f"missing admin runtimes module: {JS_ADMIN_RUNTIMES}"
    )
    text = JS_ADMIN_RUNTIMES.read_text(encoding="utf-8")
    assert "window.adminRuntimes" in text, (
        "runtimes.js must expose window.adminRuntimes for Alpine x-data"
    )


def test_admin_runtimes_module_consults_documented_endpoints() -> None:
    """The B2 view is read-only on five endpoints plus one POST.

    Endpoint surface is part of the PR contract; downstream PRs
    that touch these paths must keep them stable or update this
    test alongside the change.
    """
    text = JS_ADMIN_RUNTIMES.read_text(encoding="utf-8")
    for path in (
        "/admin/openclaw/runtimes",
        "/concurrency",
        "/alerts",
        "/notification-targets",
        "/alert-routing",
        "/recovery-jobs",
    ):
        assert path in text, f"runtimes.js must consult {path}"


def test_admin_runtimes_module_declares_per_card_state() -> None:
    """The per-card state machine (state/data/error/raw) and the
    show-raw toggles are reused by every B-phase view. Regress
    against an accidental rename."""
    text = JS_ADMIN_RUNTIMES.read_text(encoding="utf-8")
    for card in (
        "runtimes:",
        "concurrency:",
        "alerts:",
        "notificationTargets:",
        "alertRouting:",
    ):
        assert card in text, f"runtimes.js must declare card key {card!r}"
    # Recovery form lives in the same factory.
    assert "recoveryForm" in text
    assert "submitRecovery" in text
    assert "openRecoveryDialog" in text


def test_admin_runtimes_module_reacts_to_auth_events() -> None:
    """When the user logs in or out, the runtimes view must
    refresh/clear without a page reload."""
    text = JS_ADMIN_RUNTIMES.read_text(encoding="utf-8")
    assert "om:auth:logged-in" in text
    assert "om:auth:logged-out" in text


def test_admin_html_loads_runtimes_factory_and_renders_view() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "./js/admin/runtimes.js" in html, (
        "admin.html must load the runtimes module"
    )
    assert 'x-data="adminRuntimes()"' in html, (
        "admin.html must mount adminRuntimes() inside the runtimes template"
    )
    assert "activeId === 'runtimes'" in html, (
        "admin.html must gate the runtimes view by activeId"
    )
    # Modal id matches the manager registration.
    assert "omModalFor('runtimes-recovery')" in html
    # The placeholder template excludes both dashboard AND runtimes now.
    assert (
        "activeId !== 'dashboard' && activeId !== 'runtimes'" in html
    ), (
        "admin.html placeholder template must skip runtimes (B2) and "
        "dashboard (B1); otherwise the placeholder double-renders"
    )
    # Show-raw toggles for the four detail cards.
    for key in (
        "showRaw.concurrency",
        "showRaw.alerts",
        "showRaw.notificationTargets",
        "showRaw.alertRouting",
    ):
        assert key in html, f"admin.html runtimes view must wire {key}"


# --------------------------------------------------------------------
# Phase B3 — Admin Policies editor
# --------------------------------------------------------------------

JS_ADMIN_POLICIES = UI_V2 / "static" / "js" / "admin" / "policies.js"


def test_admin_policies_module_exposes_factory() -> None:
    assert JS_ADMIN_POLICIES.exists(), (
        f"missing admin policies module: {JS_ADMIN_POLICIES}"
    )
    text = JS_ADMIN_POLICIES.read_text(encoding="utf-8")
    assert "window.adminPolicies" in text, (
        "policies.js must expose window.adminPolicies for Alpine x-data"
    )


def test_admin_policies_module_consults_documented_endpoints() -> None:
    """The B3 view consults two GETs, three read-modeled POSTs
    (explain/simulate/diff) and one confirmed write (F1: apply
    pack to runtime). Pinning the surface keeps downstream
    refactors honest.
    """
    text = JS_ADMIN_POLICIES.read_text(encoding="utf-8")
    for path in (
        "/admin/openclaw/policy-packs",
        "/admin/policy-explorer/snapshot",
        "/admin/policies/explain",
        "/admin/policy-explorer/simulate",
        "/admin/policy-explorer/diff",
        # F1 — apply pack to runtime (confirmed write)
        "/policy-pack",
    ):
        assert path in text, f"policies.js must consult {path}"


def test_admin_policies_module_declares_apply_pack_modal() -> None:
    """F1: the apply-pack modal is the only write surface in
    the policies view. Pin its plumbing so a future refactor
    cannot silently remove it."""
    text = JS_ADMIN_POLICIES.read_text(encoding="utf-8")
    assert "applyForm" in text
    assert "submitApplyPack" in text
    assert "openApplyDialog" in text
    assert "closeApplyDialog" in text
    assert "policies-apply-pack" in text, (
        "policies.js must register its apply modal under "
        "'policies-apply-pack'"
    )


def test_admin_policies_module_declares_per_card_state() -> None:
    """Per-card { state, data, error, raw } pattern reused from B1/B2."""
    text = JS_ADMIN_POLICIES.read_text(encoding="utf-8")
    for card in (
        "packs:",
        "snapshot:",
        "explainResult:",
        "simulateResult:",
        "diffResult:",
    ):
        assert card in text, f"policies.js must declare card key {card!r}"
    # Three forms live in the factory.
    for form in ("explainForm", "simulateForm", "diffForm"):
        assert form in text, f"policies.js must declare {form}"
    # Submit handlers wired.
    for handler in ("submitExplain", "submitSimulate", "submitDiff"):
        assert handler in text, f"policies.js must declare {handler}"


def test_admin_policies_module_reacts_to_auth_events() -> None:
    text = JS_ADMIN_POLICIES.read_text(encoding="utf-8")
    assert "om:auth:logged-in" in text
    assert "om:auth:logged-out" in text


def test_admin_html_loads_policies_factory_and_renders_view() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "./js/admin/policies.js" in html, (
        "admin.html must load the policies module"
    )
    assert 'x-data="adminPolicies()"' in html, (
        "admin.html must mount adminPolicies() inside the policies template"
    )
    assert "activeId === 'policies'" in html, (
        "admin.html must gate the policies view by activeId"
    )
    # The placeholder template now excludes three live views, not two.
    assert (
        "activeId !== 'dashboard' && activeId !== 'runtimes' && "
        "activeId !== 'policies'" in html
    ), (
        "admin.html placeholder template must skip policies (B3) too; "
        "otherwise the placeholder double-renders for activeId='policies'"
    )
    # Show-raw toggles for the six cards (5 from B3 + 1 from F1).
    for key in (
        "showRaw.packs",
        "showRaw.snapshot",
        "showRaw.explainResult",
        "showRaw.simulateResult",
        "showRaw.diffResult",
        "showRaw.applyResult",
    ):
        assert key in html, f"admin.html policies view must wire {key}"
    # F1: apply-pack modal mounted.
    assert "omModalFor('policies-apply-pack')" in html


# --------------------------------------------------------------------
# Phase B4 — Admin Secrets governance
# --------------------------------------------------------------------

JS_ADMIN_SECRETS = UI_V2 / "static" / "js" / "admin" / "secrets.js"


def test_admin_secrets_module_exposes_factory() -> None:
    assert JS_ADMIN_SECRETS.exists(), (
        f"missing admin secrets module: {JS_ADMIN_SECRETS}"
    )
    text = JS_ADMIN_SECRETS.read_text(encoding="utf-8")
    assert "window.adminSecrets" in text, (
        "secrets.js must expose window.adminSecrets for Alpine x-data"
    )


def test_admin_secrets_module_consults_documented_endpoints() -> None:
    """B4 is read-only on four GETs plus one read-modeled POST.

    The wizard /admin/config-center/secrets-wizard/save is *not*
    consumed here — that write surface lands in B6 (Channels) once
    the confirmation pattern factored. Regress against an
    accidental wizard import (would be a privilege-escalation
    surface increase the PR did not commit to).
    """
    text = JS_ADMIN_SECRETS.read_text(encoding="utf-8")
    for path in (
        "/admin/secrets/summary",
        "/admin/secrets/catalog",
        "/admin/secrets/timeline",
        "/admin/secrets/usage",
        "/admin/secrets/explain",
    ):
        assert path in text, f"secrets.js must consult {path}"
    assert "/admin/config-center/secrets-wizard" not in text, (
        "secrets.js must NOT consume the wizard write path; "
        "that surface lives in secrets_wizard.js (F2)"
    )


def test_admin_secrets_module_declares_per_card_state() -> None:
    text = JS_ADMIN_SECRETS.read_text(encoding="utf-8")
    for card in (
        "summary:",
        "catalog:",
        "timeline:",
        "usage:",
        "explainResult:",
    ):
        assert card in text, f"secrets.js must declare card key {card!r}"
    assert "explainForm" in text
    assert "submitExplain" in text
    # Shared filter object (q / ref / tool / outcome / limit).
    assert "filters:" in text or "filters =" in text


def test_admin_secrets_module_reacts_to_auth_events() -> None:
    text = JS_ADMIN_SECRETS.read_text(encoding="utf-8")
    assert "om:auth:logged-in" in text
    assert "om:auth:logged-out" in text


def test_admin_html_loads_secrets_factory_and_renders_view() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "./js/admin/secrets.js" in html, (
        "admin.html must load the secrets module"
    )
    assert 'x-data="adminSecrets()"' in html, (
        "admin.html must mount adminSecrets() inside the secrets template"
    )
    assert "activeId === 'secrets'" in html, (
        "admin.html must gate the secrets view by activeId"
    )
    # The placeholder template now excludes four live views.
    assert (
        "activeId !== 'dashboard' && activeId !== 'runtimes' && "
        "activeId !== 'policies' && activeId !== 'secrets'" in html
    ), (
        "admin.html placeholder template must skip secrets (B4) too; "
        "otherwise the placeholder double-renders for activeId='secrets'"
    )
    for key in (
        "showRaw.summary",
        "showRaw.catalog",
        "showRaw.timeline",
        "showRaw.usage",
        "showRaw.explainResult",
    ):
        assert key in html, f"admin.html secrets view must wire {key}"


# --------------------------------------------------------------------
# Phase F2 — Admin Secrets wizard (config-center save path)
# --------------------------------------------------------------------

JS_ADMIN_SECRETS_WIZARD = UI_V2 / "static" / "js" / "admin" / "secrets_wizard.js"


def test_admin_secrets_wizard_module_exposes_factory() -> None:
    assert JS_ADMIN_SECRETS_WIZARD.exists()
    text = JS_ADMIN_SECRETS_WIZARD.read_text(encoding="utf-8")
    assert "window.adminSecretsWizard" in text


def test_admin_secrets_wizard_module_consults_documented_endpoints() -> None:
    """F2 ships the three wizard endpoints. Pinning the
    snapshot + validate (read-modeled) + save (confirmed
    write) contract."""
    text = JS_ADMIN_SECRETS_WIZARD.read_text(encoding="utf-8")
    for path in (
        "/admin/config-center/secrets-wizard",
        "/admin/config-center/secrets-wizard/validate",
        "/admin/config-center/secrets-wizard/save",
    ):
        assert path in text, f"secrets_wizard.js must consult {path}"


def test_admin_secrets_wizard_declares_save_modal() -> None:
    text = JS_ADMIN_SECRETS_WIZARD.read_text(encoding="utf-8")
    for card in ("snapshot:", "validateResult:", "saveResult:"):
        assert card in text
    for handler in ("submitValidate", "submitSave", "openSaveDialog", "closeSaveDialog"):
        assert handler in text
    assert "secrets-wizard-save" in text


def test_shell_admin_sidebar_includes_secrets_wizard() -> None:
    """The new nav item under Configure."""
    text = JS_SHELL.read_text(encoding="utf-8")
    assert "secrets-wizard" in text, (
        "shell.js admin nav must include 'secrets-wizard' under Configure"
    )


def test_admin_html_loads_secrets_wizard_view() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "./js/admin/secrets_wizard.js" in html
    assert 'x-data="adminSecretsWizard()"' in html
    assert "activeId === 'secrets-wizard'" in html
    assert "omModalFor('secrets-wizard-save')" in html
    # Placeholder excludes the new view too.
    assert "activeId !== 'secrets-wizard'" in html


# --------------------------------------------------------------------
# Phase F4 — Admin Dispatches view
# --------------------------------------------------------------------

JS_ADMIN_DISPATCHES = UI_V2 / "static" / "js" / "admin" / "dispatches.js"


def test_admin_dispatches_module_exposes_factory() -> None:
    assert JS_ADMIN_DISPATCHES.exists()
    text = JS_ADMIN_DISPATCHES.read_text(encoding="utf-8")
    assert "window.adminDispatches" in text


def test_admin_dispatches_module_consults_documented_endpoints() -> None:
    """F4 surfaces list + detail (read) and cancel / retry /
    reconcile (confirmed writes). The action endpoint pattern
    is part of the URL — encoded by the generic action handler
    so a future "abort" verb works without code changes."""
    text = JS_ADMIN_DISPATCHES.read_text(encoding="utf-8")
    for path in (
        "/admin/openclaw/dispatches",
    ):
        assert path in text, f"dispatches.js must consult {path}"


def test_admin_dispatches_module_declares_action_modal() -> None:
    text = JS_ADMIN_DISPATCHES.read_text(encoding="utf-8")
    for card in ("list:", "detail:", "actionResult:"):
        assert card in text
    for handler in ("openActionDialog", "closeActionDialog", "submitAction", "select("):
        assert handler in text
    assert "dispatches-action" in text


def test_admin_html_loads_dispatches_view() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "./js/admin/dispatches.js" in html
    assert 'x-data="adminDispatches()"' in html
    assert "activeId === 'dispatches'" in html
    assert "omModalFor('dispatches-action')" in html
    assert "activeId !== 'dispatches'" in html


# --------------------------------------------------------------------
# Phase F5 — Admin Approvals view
# --------------------------------------------------------------------

JS_ADMIN_APPROVALS = UI_V2 / "static" / "js" / "admin" / "approvals.js"


def test_admin_approvals_module_exposes_factory() -> None:
    assert JS_ADMIN_APPROVALS.exists()
    text = JS_ADMIN_APPROVALS.read_text(encoding="utf-8")
    assert "window.adminApprovals" in text


def test_admin_approvals_module_consults_documented_endpoints() -> None:
    text = JS_ADMIN_APPROVALS.read_text(encoding="utf-8")
    assert "/admin/operator/overview" in text
    assert "/admin/operator/approvals/" in text


def test_admin_approvals_module_declares_action_modal() -> None:
    text = JS_ADMIN_APPROVALS.read_text(encoding="utf-8")
    assert "actionForm" in text
    assert "submitAction" in text
    assert "openActionDialog" in text
    assert "admin-approval-action" in text


def test_admin_html_loads_approvals_view() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "./js/admin/approvals.js" in html
    assert 'x-data="adminApprovals()"' in html
    assert "activeId === 'approvals'" in html
    assert "omModalFor('admin-approval-action')" in html
    assert "activeId !== 'approvals'" in html


# --------------------------------------------------------------------
# Phase F8 — Admin Event log + Tool calls (Debug pane)
# --------------------------------------------------------------------

JS_ADMIN_DEBUG = UI_V2 / "static" / "js" / "admin" / "debug.js"


def test_admin_debug_module_exposes_two_factories() -> None:
    assert JS_ADMIN_DEBUG.exists()
    text = JS_ADMIN_DEBUG.read_text(encoding="utf-8")
    assert "window.adminEventLog" in text
    assert "window.adminToolCalls" in text


def test_admin_debug_module_consults_documented_endpoints() -> None:
    text = JS_ADMIN_DEBUG.read_text(encoding="utf-8")
    for path in (
        "/admin/events",
        "/admin/traces",
    ):
        assert path in text


def test_admin_debug_module_is_strictly_read_only() -> None:
    """The Debug pane never writes. Pin the absence of any
    POST so a future refactor cannot quietly turn the trace
    inspector into an action surface."""
    text = JS_ADMIN_DEBUG.read_text(encoding="utf-8")
    assert "omApi.post" not in text and "omApi.put" not in text and "omApi.del" not in text, (
        "debug.js must not write; it is strictly read-only"
    )


def test_admin_html_loads_debug_views() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "./js/admin/debug.js" in html
    assert 'x-data="adminEventLog()"' in html
    assert 'x-data="adminToolCalls()"' in html
    assert "activeId === 'events'" in html
    assert "activeId === 'tool-calls'" in html
    assert "activeId !== 'events'" in html
    assert "activeId !== 'tool-calls'" in html


# --------------------------------------------------------------------
# Phase B5 — Admin Identities & RBAC
# --------------------------------------------------------------------

JS_ADMIN_IDENTITIES = UI_V2 / "static" / "js" / "admin" / "identities.js"


def test_admin_identities_module_exposes_factory() -> None:
    assert JS_ADMIN_IDENTITIES.exists(), (
        f"missing admin identities module: {JS_ADMIN_IDENTITIES}"
    )
    text = JS_ADMIN_IDENTITIES.read_text(encoding="utf-8")
    assert "window.adminIdentities" in text, (
        "identities.js must expose window.adminIdentities for Alpine x-data"
    )


def test_admin_identities_module_consults_documented_endpoints() -> None:
    """B5 covers identity linking + the two RBAC explain endpoints."""
    text = JS_ADMIN_IDENTITIES.read_text(encoding="utf-8")
    for path in (
        "/admin/identities",
        "/admin/identities/link",
        "/admin/sessions",
        "/admin/sandbox/explain",
        "/admin/security/explain",
    ):
        assert path in text, f"identities.js must consult {path}"


def test_admin_identities_module_declares_per_card_state_and_link_form() -> None:
    text = JS_ADMIN_IDENTITIES.read_text(encoding="utf-8")
    for card in (
        "identities:",
        "sessions:",
        "sandboxResult:",
        "securityResult:",
    ):
        assert card in text, f"identities.js must declare card key {card!r}"
    # Three forms, one a confirmed write.
    for form in ("linkForm", "sandboxForm", "securityForm"):
        assert form in text, f"identities.js must declare {form}"
    # Submit handlers.
    for handler in ("submitLink", "submitSandbox", "submitSecurity"):
        assert handler in text
    # Confirmation modal plumbing.
    assert "openLinkDialog" in text
    assert "closeLinkDialog" in text
    assert "identities-link" in text, (
        "identities.js must register its modal under 'identities-link'"
    )


def test_admin_identities_module_reacts_to_auth_events() -> None:
    text = JS_ADMIN_IDENTITIES.read_text(encoding="utf-8")
    assert "om:auth:logged-in" in text
    assert "om:auth:logged-out" in text


def test_admin_html_loads_identities_factory_and_renders_view() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "./js/admin/identities.js" in html, (
        "admin.html must load the identities module"
    )
    assert 'x-data="adminIdentities()"' in html, (
        "admin.html must mount adminIdentities() inside the identities template"
    )
    assert "activeId === 'identities'" in html, (
        "admin.html must gate the identities view by activeId"
    )
    # Modal id matches the manager registration.
    assert "omModalFor('identities-link')" in html
    # The placeholder template now excludes five live views.
    assert (
        "activeId !== 'dashboard' && activeId !== 'runtimes' && "
        "activeId !== 'policies' && activeId !== 'secrets' && "
        "activeId !== 'identities'" in html
    ), (
        "admin.html placeholder template must skip identities (B5) too"
    )
    for key in (
        "showRaw.identities",
        "showRaw.sessions",
        "showRaw.sandboxResult",
        "showRaw.securityResult",
    ):
        assert key in html, f"admin.html identities view must wire {key}"


# --------------------------------------------------------------------
# Phase B6 — Admin Channels wizard
# --------------------------------------------------------------------

JS_ADMIN_CHANNELS = UI_V2 / "static" / "js" / "admin" / "channels.js"


def test_admin_channels_module_exposes_factory() -> None:
    assert JS_ADMIN_CHANNELS.exists(), (
        f"missing admin channels module: {JS_ADMIN_CHANNELS}"
    )
    text = JS_ADMIN_CHANNELS.read_text(encoding="utf-8")
    assert "window.adminChannels" in text, (
        "channels.js must expose window.adminChannels for Alpine x-data"
    )


def test_admin_channels_module_consults_documented_endpoints() -> None:
    """B6 covers the three channels-wizard endpoints. The save
    endpoint is the only B-phase write that touches disk; this
    test pins the surface so an accidental rename surfaces here."""
    text = JS_ADMIN_CHANNELS.read_text(encoding="utf-8")
    for path in (
        "/admin/config-center/channels-wizard",
        "/admin/config-center/channels-wizard/validate",
        "/admin/config-center/channels-wizard/save",
    ):
        assert path in text, f"channels.js must consult {path}"


def test_admin_channels_module_declares_per_card_state_and_save_modal() -> None:
    text = JS_ADMIN_CHANNELS.read_text(encoding="utf-8")
    for card in (
        "snapshot:",
        "validateResult:",
        "saveResult:",
    ):
        assert card in text, f"channels.js must declare card key {card!r}"
    # Editor + save form lives in the factory.
    assert "editor" in text
    assert "saveForm" in text
    for handler in ("submitValidate", "submitSave", "openSaveDialog", "closeSaveDialog"):
        assert handler in text, f"channels.js must declare {handler}"
    assert "channels-save" in text, (
        "channels.js must register its modal under 'channels-save'"
    )


def test_admin_channels_module_reacts_to_auth_events() -> None:
    text = JS_ADMIN_CHANNELS.read_text(encoding="utf-8")
    assert "om:auth:logged-in" in text
    assert "om:auth:logged-out" in text


def test_admin_html_loads_channels_factory_and_renders_view() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "./js/admin/channels.js" in html, (
        "admin.html must load the channels module"
    )
    assert 'x-data="adminChannels()"' in html, (
        "admin.html must mount adminChannels() inside the channels template"
    )
    assert "activeId === 'channels'" in html, (
        "admin.html must gate the channels view by activeId"
    )
    # Modal id matches the manager registration.
    assert "omModalFor('channels-save')" in html
    # The placeholder template now excludes six live views.
    assert (
        "activeId !== 'dashboard' && activeId !== 'runtimes' && "
        "activeId !== 'policies' && activeId !== 'secrets' && "
        "activeId !== 'identities' && activeId !== 'channels'" in html
    ), (
        "admin.html placeholder template must skip channels (B6) too"
    )
    for key in (
        "showRaw.snapshot",
        "showRaw.validateResult",
        "showRaw.saveResult",
    ):
        assert key in html, f"admin.html channels view must wire {key}"


# --------------------------------------------------------------------
# Phase B7 — Admin Evidence packs
# --------------------------------------------------------------------

JS_ADMIN_EVIDENCE = UI_V2 / "static" / "js" / "admin" / "evidence.js"


def test_admin_evidence_module_exposes_factory() -> None:
    assert JS_ADMIN_EVIDENCE.exists(), (
        f"missing admin evidence module: {JS_ADMIN_EVIDENCE}"
    )
    text = JS_ADMIN_EVIDENCE.read_text(encoding="utf-8")
    assert "window.adminEvidence" in text, (
        "evidence.js must expose window.adminEvidence for Alpine x-data"
    )


def test_admin_evidence_module_consults_documented_endpoints() -> None:
    """B7 covers the compliance summary + export pair only.

    The portfolio-scoped evidence-package endpoints under
    /admin/openclaw/alert-governance/portfolios/{id}/... are
    deferred to a follow-up sprint; assert their absence so an
    accidental import does not creep in without explicit
    review.
    """
    text = JS_ADMIN_EVIDENCE.read_text(encoding="utf-8")
    for path in (
        "/admin/compliance/summary",
        "/admin/compliance/export",
    ):
        assert path in text, f"evidence.js must consult {path}"
    assert "alert-governance/portfolios" not in text, (
        "evidence.js must NOT consume the portfolio-scoped "
        "evidence-package endpoints in B7; reserve them for a "
        "later sprint that ships portfolio-aware UI"
    )


def test_admin_evidence_module_declares_per_card_state_and_export_modal() -> None:
    text = JS_ADMIN_EVIDENCE.read_text(encoding="utf-8")
    for card in ("summary:", "exportResult:"):
        assert card in text, f"evidence.js must declare card key {card!r}"
    assert "exportForm" in text
    for handler in ("submitExport", "openExportDialog", "closeExportDialog", "refreshSummary"):
        assert handler in text, f"evidence.js must declare {handler}"
    # Section-checkbox state lives in the form.
    assert "sections" in text
    assert "evidence-export" in text, (
        "evidence.js must register its modal under 'evidence-export'"
    )


def test_admin_evidence_module_reacts_to_auth_events() -> None:
    text = JS_ADMIN_EVIDENCE.read_text(encoding="utf-8")
    assert "om:auth:logged-in" in text
    assert "om:auth:logged-out" in text


def test_admin_html_loads_evidence_factory_and_renders_view() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "./js/admin/evidence.js" in html, (
        "admin.html must load the evidence module"
    )
    assert 'x-data="adminEvidence()"' in html, (
        "admin.html must mount adminEvidence() inside the evidence template"
    )
    assert "activeId === 'evidence'" in html, (
        "admin.html must gate the evidence view by activeId"
    )
    assert "omModalFor('evidence-export')" in html
    # The placeholder template now excludes all seven live views.
    assert (
        "activeId !== 'dashboard' && activeId !== 'runtimes' && "
        "activeId !== 'policies' && activeId !== 'secrets' && "
        "activeId !== 'identities' && activeId !== 'channels' && "
        "activeId !== 'evidence'" in html
    ), (
        "admin.html placeholder template must skip evidence (B7) too"
    )
    for key in ("showRaw.summary", "showRaw.exportResult"):
        assert key in html, f"admin.html evidence view must wire {key}"


# --------------------------------------------------------------------
# Phase C1 — Science Chat with agent
# --------------------------------------------------------------------

JS_SCIENCE_CHAT = UI_V2 / "static" / "js" / "science" / "chat.js"


def test_science_chat_module_exposes_factory() -> None:
    assert JS_SCIENCE_CHAT.exists(), (
        f"missing science chat module: {JS_SCIENCE_CHAT}"
    )
    text = JS_SCIENCE_CHAT.read_text(encoding="utf-8")
    assert "window.scienceChat" in text, (
        "chat.js must expose window.scienceChat for Alpine x-data"
    )


def test_science_chat_module_consults_documented_endpoint() -> None:
    """C1 is single-endpoint: the stable POST /http/message
    chat surface. The admin chat endpoints are *not* consumed
    here — assert their absence to keep science isolated."""
    text = JS_SCIENCE_CHAT.read_text(encoding="utf-8")
    assert "/http/message" in text, "chat.js must consult /http/message"
    assert "/admin/" not in text, (
        "chat.js must NOT consume any admin endpoints; the science "
        "profile is intentionally isolated from the admin surface"
    )


def test_science_chat_module_persists_under_documented_keys() -> None:
    """The localStorage keys are part of the public contract;
    downstream debug tools may inspect them."""
    text = JS_SCIENCE_CHAT.read_text(encoding="utf-8")
    assert "openmiura.v2.science.messages" in text, (
        "chat.js must persist transcripts under "
        "openmiura.v2.science.messages"
    )
    assert "openmiura.v2.science.session_id" in text, (
        "chat.js must persist the session id under "
        "openmiura.v2.science.session_id"
    )


def test_science_chat_module_declares_send_and_reset() -> None:
    text = JS_SCIENCE_CHAT.read_text(encoding="utf-8")
    for fn in ("send(", "reset(", "authenticated("):
        assert fn in text, f"chat.js must declare {fn}"
    # The auth event a chat session listens to (logout marks
    # an end-of-session in the transcript).
    assert "om:auth:logged-out" in text


def test_science_html_loads_chat_factory_and_renders_view() -> None:
    html = SCIENCE_HTML.read_text(encoding="utf-8")
    assert "./js/science/chat.js" in html, (
        "science.html must load the chat module"
    )
    assert 'x-data="scienceChat()"' in html, (
        "science.html must mount scienceChat() inside the chat template"
    )
    assert "activeId === 'chat'" in html, (
        "science.html must gate the chat view by activeId"
    )
    # The Phase A2 placeholder is gone now — the placeholder
    # template should only catch *other* science activeIds.
    assert "activeId !== 'chat'" in html, (
        "science.html placeholder template must skip chat (C1)"
    )
    # Composer present.
    assert "composer.text" in html
    assert "composer.busy" in html


# --------------------------------------------------------------------
# Phase C2 — Science Upload spectrum
# --------------------------------------------------------------------

JS_SCIENCE_UPLOAD = UI_V2 / "static" / "js" / "science" / "upload.js"


def test_science_upload_module_exposes_factory() -> None:
    assert JS_SCIENCE_UPLOAD.exists()
    text = JS_SCIENCE_UPLOAD.read_text(encoding="utf-8")
    assert "window.scienceUpload" in text


def test_science_upload_module_uses_only_chat_endpoint() -> None:
    """C2 piggy-backs on the same /http/message endpoint as C1
    because openMiura has no dedicated upload endpoint yet.
    Pinning this contract here surfaces the day someone wires
    a real upload endpoint and needs to update the regression
    on the science profile's surface boundary."""
    text = JS_SCIENCE_UPLOAD.read_text(encoding="utf-8")
    assert "/http/message" in text
    assert "/admin/" not in text, (
        "upload.js must not consume admin endpoints"
    )


def test_science_upload_module_persists_metadata_only() -> None:
    """The contract: only metadata under openmiura.v2.science.uploads."""
    text = JS_SCIENCE_UPLOAD.read_text(encoding="utf-8")
    assert "openmiura.v2.science.uploads" in text
    # SHA-256 hashing via the Web Crypto API is the identity
    # primitive that lets operator + agent agree on a file
    # without round-tripping the bytes.
    assert "SHA-256" in text or "sha256" in text


def test_science_upload_module_caps_file_size_and_staging() -> None:
    """Both caps are part of the documented contract; assert
    they appear so a future regression that drops them is
    explicit."""
    text = JS_SCIENCE_UPLOAD.read_text(encoding="utf-8")
    assert "MAX_FILE_BYTES" in text
    assert "MAX_STAGED" in text


def test_science_html_loads_upload_factory_and_renders_view() -> None:
    html = SCIENCE_HTML.read_text(encoding="utf-8")
    assert "./js/science/upload.js" in html
    assert 'x-data="scienceUpload()"' in html
    assert "activeId === 'upload'" in html
    # The placeholder template now excludes both chat AND upload.
    assert (
        "activeId !== 'chat' && activeId !== 'upload'" in html
    ), (
        "science.html placeholder must skip both chat (C1) and upload (C2)"
    )
    # Drop-zone wiring.
    assert "@dragover" in html
    assert "@drop.prevent" in html


# --------------------------------------------------------------------
# Phase C3+C4 — Science Review / Approvals / History
# --------------------------------------------------------------------

JS_SCIENCE_REVIEW    = UI_V2 / "static" / "js" / "science" / "review.js"
JS_SCIENCE_APPROVALS = UI_V2 / "static" / "js" / "science" / "approvals.js"
JS_SCIENCE_HISTORY   = UI_V2 / "static" / "js" / "science" / "history.js"


def test_science_review_module_exposes_factory_and_uses_overview() -> None:
    assert JS_SCIENCE_REVIEW.exists()
    text = JS_SCIENCE_REVIEW.read_text(encoding="utf-8")
    assert "window.scienceReview" in text
    assert "/admin/operator/overview" in text
    # Review is strictly read-only — no action endpoint.
    assert "/admin/operator/approvals/" not in text, (
        "review.js must not POST to the approvals action endpoint; "
        "act-on-it lives in approvals.js"
    )


def test_science_approvals_module_exposes_factory_and_action_modal() -> None:
    assert JS_SCIENCE_APPROVALS.exists()
    text = JS_SCIENCE_APPROVALS.read_text(encoding="utf-8")
    assert "window.scienceApprovals" in text
    # The two endpoints consumed.
    assert "/admin/operator/overview" in text
    assert "/admin/operator/approvals/" in text
    # Modal + confirmed-action plumbing.
    assert "openActionDialog" in text
    assert "closeActionDialog" in text
    assert "submitAction" in text
    assert "science-approval-action" in text, (
        "approvals.js must register its modal under "
        "'science-approval-action'"
    )


def test_science_history_module_exposes_factory_and_uses_summary() -> None:
    assert JS_SCIENCE_HISTORY.exists()
    text = JS_SCIENCE_HISTORY.read_text(encoding="utf-8")
    assert "window.scienceHistory" in text
    assert "/admin/compliance/summary" in text
    # No export trigger here — the science user drops into the
    # admin Evidence packs view to actually export.
    assert "/admin/compliance/export" not in text, (
        "history.js must NOT trigger an export; that surface "
        "lives on the admin Evidence packs view"
    )


def test_science_html_loads_three_modules_and_renders_three_views() -> None:
    html = SCIENCE_HTML.read_text(encoding="utf-8")
    for src in (
        "./js/science/review.js",
        "./js/science/approvals.js",
        "./js/science/history.js",
    ):
        assert src in html, f"science.html must load {src}"
    for x_data in (
        'x-data="scienceReview()"',
        'x-data="scienceApprovals()"',
        'x-data="scienceHistory()"',
    ):
        assert x_data in html, f"science.html must mount {x_data}"
    for active in (
        "activeId === 'review'",
        "activeId === 'approvals'",
        "activeId === 'history'",
    ):
        assert active in html, f"science.html must gate {active}"
    # Fallback excludes all five live views.
    assert (
        "activeId !== 'chat' && activeId !== 'upload' && "
        "activeId !== 'review' && activeId !== 'approvals' && "
        "activeId !== 'history'" in html
    )
    # Approvals modal id is wired.
    assert "omModalFor('science-approval-action')" in html


# --------------------------------------------------------------------
# Phase D1–D3 — Interview UI
# --------------------------------------------------------------------

JS_INTERVIEW_DEMO = UI_V2 / "static" / "js" / "interview" / "demo.js"


def test_interview_demo_module_exposes_three_factories() -> None:
    assert JS_INTERVIEW_DEMO.exists()
    text = JS_INTERVIEW_DEMO.read_text(encoding="utf-8")
    for name in (
        "window.interviewOverview",
        "window.interviewWalkthrough",
        "window.interviewEvidence",
    ):
        assert name in text, f"demo.js must expose {name}"


def test_interview_demo_module_is_offline_only() -> None:
    """The interview profile must not call the backend. This
    keeps the demo working without a running broker and is
    part of the documented contract: synthetic data only.

    Regress against an accidental window.omApi.* import that
    would silently re-introduce live calls. Endpoint *strings*
    are allowed as documentation inside the synthetic step
    detail (they show the reviewer what the live equivalent
    would look like); the contract is the absence of the
    actual omApi handle, fetch() and XMLHttpRequest.
    """
    text = JS_INTERVIEW_DEMO.read_text(encoding="utf-8")
    assert "omApi" not in text, (
        "demo.js must not reach for window.omApi; the interview "
        "profile is offline by design"
    )
    assert "fetch(" not in text, (
        "demo.js must not call fetch() directly"
    )
    assert "XMLHttpRequest" not in text, (
        "demo.js must not call XMLHttpRequest directly"
    )


def test_interview_demo_walkthrough_navigation_methods() -> None:
    text = JS_INTERVIEW_DEMO.read_text(encoding="utf-8")
    for fn in ("next(", "prev(", "goto(", "toggleAutoplay(", "currentStep("):
        assert fn in text, f"walkthrough factory must declare {fn}"
    # The canonical demo has 6 steps; pin the count so a
    # rewrite that drops one is visible.
    assert "STEPS" in text


def test_interview_demo_evidence_has_synthetic_signature() -> None:
    """The evidence sample must include an algorithm + digest +
    actor — the three fields a reviewer reaches for first."""
    text = JS_INTERVIEW_DEMO.read_text(encoding="utf-8")
    assert "ed25519" in text
    assert "digest_sha256" in text
    assert "actor" in text


def test_interview_html_renders_three_views() -> None:
    html = INTERVIEW_HTML.read_text(encoding="utf-8")
    assert "./js/interview/demo.js" in html
    for x_data in (
        'x-data="interviewOverview()"',
        'x-data="interviewWalkthrough()"',
        'x-data="interviewEvidence()"',
    ):
        assert x_data in html, f"interview.html must mount {x_data}"
    for active in (
        "activeId === 'overview'",
        "activeId === 'walkthrough'",
        "activeId === 'evidence'",
    ):
        assert active in html
    # The old Phase A2 placeholder is gone.
    assert "Phase A2 placeholder" not in html, (
        "interview.html must replace the Phase A2 placeholder banner"
    )


# --------------------------------------------------------------------
# Phase E — Polish (a11y + docs)
# --------------------------------------------------------------------


@pytest.mark.parametrize("path", [ADMIN_HTML, SCIENCE_HTML, INTERVIEW_HTML])
def test_sidebar_nav_has_a11y_wiring(path: Path) -> None:
    """Every sidebar must carry an aria-label, mark the active
    nav button with aria-current="page", and hide the icon
    span from screen readers. Pinned in Phase E so a future
    sidebar refactor cannot silently regress accessibility."""
    html = path.read_text(encoding="utf-8")
    assert 'aria-label="' in html, f"{path.name} sidebar must declare aria-label"
    assert 'aria-current="' in html, (
        f"{path.name} sidebar nav button must declare aria-current "
        f"so screen readers announce the active page"
    )
    # The icon span sits inside a button with a textual label;
    # the icon itself adds nothing to a screen reader.
    assert 'aria-hidden="true"' in html, (
        f"{path.name} icon span must be aria-hidden so screen "
        f"readers don't announce the SVG node"
    )


def test_input_css_declares_focus_visible_ring() -> None:
    """Phase E polish: keyboard users see a high-contrast
    accent ring on every interactive element via
    :focus-visible. Mouse users see nothing (no behaviour
    regression). Pin the rule so a future tailwind upgrade
    that drops the layer can't silently disable it."""
    text = INPUT_CSS.read_text(encoding="utf-8")
    assert ":focus-visible" in text, (
        "input.css must declare a :focus-visible ring rule"
    )
    assert "om-sr-only" in text, (
        "input.css must declare an .om-sr-only helper for "
        "screen-reader-only text"
    )


def test_docs_ui_readme_describes_phase_e_polish() -> None:
    """The contributor-facing README under docs/ui/ must
    surface the Phase E polish notes so the a11y contract is
    visible to anyone adding a new view."""
    readme = ROOT / "docs" / "ui" / "README.md"
    assert readme.exists(), f"missing {readme}"
    text = readme.read_text(encoding="utf-8")
    # Sentinel that the README has been updated past Phase A1.
    assert "aria-current" in text, (
        "docs/ui/README.md must describe the aria-current "
        "convention so contributors know to preserve it"
    )
    assert ":focus-visible" in text or "focus-visible" in text, (
        "docs/ui/README.md must mention the focus-visible "
        "convention"
    )
    # All three profiles inventoried.
    for token in ("admin", "science", "interview"):
        assert token in text.lower()
