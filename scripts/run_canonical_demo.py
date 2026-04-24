from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openmiura.demo.canonical_case import build_live_demo_report, build_self_contained_demo_report, write_demo_report


def main() -> int:
    parser = argparse.ArgumentParser(description='Run the canonical openMiura governed runtime demo.')
    parser.add_argument('--output', default='demo_artifacts/canonical-demo-report.json', help='Path to write the JSON report.')
    parser.add_argument('--base-url', default='', help='Optional live openMiura base URL. If omitted, use a self-contained in-process demo.')
    parser.add_argument('--admin-token', default='secret-admin', help='Admin bearer token for live mode.')
    parser.add_argument('--timeout-s', type=float, default=30.0, help='HTTP timeout for live mode.')
    args = parser.parse_args()

    if str(args.base_url or '').strip():
        report = build_live_demo_report(base_url=str(args.base_url), admin_token=str(args.admin_token), timeout_s=float(args.timeout_s))
    else:
        report = build_self_contained_demo_report()

    target = write_demo_report(Path(args.output), report)
    print(f'canonical demo report written to {target}')
    print(f'success={bool(report.get("success"))}')
    print(f'runtime_id={((report.get("demo") or {}).get("runtime_id"))}')
    print(f'approval_id={((report.get("demo") or {}).get("approval_id"))}')
    return 0 if bool(report.get('success')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
