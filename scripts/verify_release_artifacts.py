from __future__ import annotations

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
