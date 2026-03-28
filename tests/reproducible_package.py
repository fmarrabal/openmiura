from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]

    build_cmd = [sys.executable, str(root / "scripts" / "build_release_artifacts.py")]
    verify_cmd = [
        sys.executable,
        str(root / "scripts" / "verify_release_artifacts.py"),
        "--dist-dir",
        "dist",
    ]

    subprocess.run(build_cmd, check=True, cwd=root)
    subprocess.run(verify_cmd, check=True, cwd=root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())