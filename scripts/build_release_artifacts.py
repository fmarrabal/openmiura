from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MANIFEST_PATH = DIST / "RELEASE_MANIFEST.json"
SHA_PATH = DIST / "SHA256SUMS.txt"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> None:
    os.environ.setdefault("PYTHONHASHSEED", "0")
    DIST.mkdir(exist_ok=True)

    for pattern in ("*.whl", "*.tar.gz", "RELEASE_MANIFEST.json", "SHA256SUMS.txt"):
        for p in DIST.glob(pattern):
            p.unlink()

    run(["python", "-m", "build"])

    artifacts = []
    for path in sorted(DIST.iterdir()):
        if path.is_file() and path.suffix in {".whl", ".gz"}:
            artifacts.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )

    manifest = {
        "product": "openMiura",
        "channel": "enterprise-alpha",
        "artifacts": artifacts,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    lines = [f"{item['sha256']}  {item['name']}" for item in artifacts]
    lines.append(f"{sha256_file(MANIFEST_PATH)}  {MANIFEST_PATH.name}")
    SHA_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
