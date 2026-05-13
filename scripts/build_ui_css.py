"""Recompile the openMiura UI v2 stylesheet from its Tailwind source.

This script is the only step required to refresh
``openmiura/ui/v2/static/openmiura.css`` after editing
``openmiura/ui/v2/src/input.css`` or after adding/removing Tailwind
utility classes anywhere under ``openmiura/ui/v2/static/``.

It downloads the standalone Tailwind CLI binary on first use (kept
under ``tools/`` in the repo, which is gitignored) so there is no
Node.js dependency. The repository commits the compiled CSS, not
the binary or the input lockfile.

Run:
    py -3 scripts/build_ui_css.py            # default minified build
    py -3 scripts/build_ui_css.py --watch    # rebuild on change
    py -3 scripts/build_ui_css.py --no-minify
    py -3 scripts/build_ui_css.py --check    # CI: compile to a temp
                                             # file, diff against the
                                             # committed CSS, exit 1
                                             # if they differ.
"""

from __future__ import annotations

import argparse
import os
import platform
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "openmiura" / "ui" / "v2" / "src" / "input.css"
OUTPUT = ROOT / "openmiura" / "ui" / "v2" / "static" / "openmiura.css"
TOOLS = ROOT / "tools"

TAILWIND_VERSION = "v4.3.0"


def _binary_url() -> tuple[str, str]:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        return (
            f"https://github.com/tailwindlabs/tailwindcss/releases/download/"
            f"{TAILWIND_VERSION}/tailwindcss-windows-x64.exe",
            "tailwindcss.exe",
        )
    if system == "Linux":
        arch = "x64" if machine in ("x86_64", "amd64") else "arm64"
        return (
            f"https://github.com/tailwindlabs/tailwindcss/releases/download/"
            f"{TAILWIND_VERSION}/tailwindcss-linux-{arch}",
            "tailwindcss",
        )
    if system == "Darwin":
        arch = "arm64" if "arm" in machine or "aarch" in machine else "x64"
        return (
            f"https://github.com/tailwindlabs/tailwindcss/releases/download/"
            f"{TAILWIND_VERSION}/tailwindcss-macos-{arch}",
            "tailwindcss",
        )
    raise SystemExit(f"unsupported platform: {system}/{machine}")


def ensure_binary() -> Path:
    TOOLS.mkdir(exist_ok=True)
    url, filename = _binary_url()
    target = TOOLS / filename
    if target.exists():
        return target
    print(f"Downloading Tailwind CLI {TAILWIND_VERSION} for this platform...")
    print(f"  {url}")
    print(f"  -> {target}")
    urllib.request.urlretrieve(url, target)
    if platform.system() != "Windows":
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"  done ({size_mb:.1f} MB)")
    return target


def _check_mode(binary: Path) -> int:
    """CI gate: compile to a temp file and diff against the committed
    output. Exit 0 if they match byte-for-byte, 1 otherwise with a
    helpful explanation."""
    import filecmp
    import tempfile

    if not OUTPUT.exists():
        print(
            f"FAIL: {OUTPUT.relative_to(ROOT)} is not committed.\n"
            f"      Run `python scripts/build_ui_css.py` locally and "
            f"commit the result."
        )
        return 1

    with tempfile.NamedTemporaryFile(
        suffix=".css", delete=False, dir=str(TOOLS), prefix="check-"
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        cmd = [str(binary), "-i", str(INPUT), "-o", str(tmp_path), "--minify"]
        print(f"Compiling {INPUT.relative_to(ROOT)} (check mode)...")
        rc = subprocess.call(cmd)
        if rc != 0:
            print(f"FAIL: tailwindcss exited with code {rc}")
            return rc

        if filecmp.cmp(str(OUTPUT), str(tmp_path), shallow=False):
            print(f"OK: {OUTPUT.relative_to(ROOT)} is up to date.")
            return 0

        committed = OUTPUT.stat().st_size
        regenerated = tmp_path.stat().st_size
        print(
            "FAIL: the committed openmiura.css does not match what the\n"
            "      Tailwind compiler produces from the current input.css.\n"
            "      Someone edited input.css (or a *.html under the v2\n"
            "      tree referenced a new utility class) and forgot to\n"
            "      regenerate the stylesheet.\n"
            "\n"
            f"      committed: {committed:>7} bytes\n"
            f"      expected:  {regenerated:>7} bytes\n"
            "\n"
            "      Fix:\n"
            "        python scripts/build_ui_css.py\n"
            "        git add openmiura/ui/v2/static/openmiura.css\n"
            "        git commit --amend  # or a new commit\n"
        )
        return 1
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="rebuild on file changes")
    parser.add_argument("--no-minify", action="store_true", help="emit unminified CSS for debugging")
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI mode: compile to a temp file, diff against the "
             "committed CSS, exit 1 if they differ",
    )
    args = parser.parse_args()

    binary = ensure_binary()

    if args.check:
        if args.watch:
            print("--check and --watch are mutually exclusive")
            return 2
        return _check_mode(binary)

    cmd = [str(binary), "-i", str(INPUT), "-o", str(OUTPUT)]
    if not args.no_minify:
        cmd.append("--minify")
    if args.watch:
        cmd.append("--watch")

    print(f"Compiling {INPUT.relative_to(ROOT)} -> {OUTPUT.relative_to(ROOT)}")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
