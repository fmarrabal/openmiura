from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openmiura.application.packaging import PackagingHardeningService


def _resolve_dist_dir(raw: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate.resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Verify openMiura release artifacts against RELEASE_MANIFEST.json')
    parser.add_argument('--dist-dir', default='dist', help='Directory containing release artifacts and manifest')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dist_dir = _resolve_dist_dir(args.dist_dir)
    payload = PackagingHardeningService().verify_release_artifacts(dist_dir=str(dist_dir))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
