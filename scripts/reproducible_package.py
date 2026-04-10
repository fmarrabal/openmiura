from __future__ import annotations

import argparse
import json
from pathlib import Path

from openmiura.application.packaging import PackagingHardeningService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit


def main() -> int:
    parser = argparse.ArgumentParser(description='Create a reproducible openMiura package artifact')
    parser.add_argument('--db-path', default='data/reproducible-builds.db')
    parser.add_argument('--target', default='desktop')
    parser.add_argument('--label', default='Reproducible build')
    parser.add_argument('--version', default='phase9-operational-hardening')
    parser.add_argument('--source-root', default='.')
    parser.add_argument('--output-dir', default='dist')
    parser.add_argument('--actor', default='ci-bot')
    args = parser.parse_args()

    audit = AuditStore(args.db_path)
    audit.init_db()
    gw = _GW(audit)
    service = PackagingHardeningService()
    result = service.create_reproducible_build(
        gw,
        actor=args.actor,
        target=args.target,
        label=args.label,
        version=args.version,
        source_root=str(Path(args.source_root).resolve()),
        output_dir=str(Path(args.output_dir).resolve()),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
