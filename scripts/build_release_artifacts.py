from __future__ import annotations

import argparse
import json

from openmiura.application.packaging import PackagingHardeningService


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate checksums and a release manifest for openMiura dist artifacts')
    parser.add_argument('--dist-dir', default='dist')
    parser.add_argument('--tag', required=True)
    parser.add_argument('--target', default='desktop')
    parser.add_argument('--release-notes-name', default='RELEASE_NOTES.md')
    parser.add_argument('--strict', action='store_true', help='Fail if required artifact kinds are missing')
    args = parser.parse_args()

    service = PackagingHardeningService()
    result = service.generate_release_manifest(
        dist_dir=args.dist_dir,
        tag=args.tag,
        target=args.target,
        release_notes_name=args.release_notes_name,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict and not result.get('ok', False):
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
