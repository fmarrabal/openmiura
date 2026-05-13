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
        ):
            r = client.get(sub)
            assert r.status_code == 200, f"{sub} not served (got {r.status_code})"
    finally:
        _P(cfg_path).unlink(missing_ok=True)
