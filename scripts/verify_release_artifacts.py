from __future__ import annotations

<<<<<<< HEAD
import hashlib
import json
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


def main() -> None:
    if not MANIFEST_PATH.exists():
        raise SystemExit("Missing RELEASE_MANIFEST.json")
    if not SHA_PATH.exists():
        raise SystemExit("Missing SHA256SUMS.txt")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts") or []
    if not artifacts:
        raise SystemExit("Manifest contains no artifacts")

    for item in artifacts:
        path = DIST / item["name"]
        if not path.exists():
            raise SystemExit(f"Missing artifact: {path.name}")
        digest = sha256_file(path)
        if digest != item["sha256"]:
            raise SystemExit(f"Checksum mismatch: {path.name}")

    sha_lines = SHA_PATH.read_text(encoding="utf-8").splitlines()
    if not sha_lines:
        raise SystemExit("SHA256SUMS.txt is empty")


if __name__ == "__main__":
    main()
=======
import argparse
import json

from openmiura.application.packaging import PackagingHardeningService


def main() -> int:
    parser = argparse.ArgumentParser(description='Verify release artifacts against RELEASE_MANIFEST.json and SHA256SUMS.txt')
    parser.add_argument('--dist-dir', default='dist')
    args = parser.parse_args()

    service = PackagingHardeningService()
    result = service.verify_release_artifacts(dist_dir=args.dist_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok', False) else 1


if __name__ == '__main__':
    raise SystemExit(main())
>>>>>>> origin/main
