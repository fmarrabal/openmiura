from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openmiura.application.openclaw.scheduler import OpenClawRecoverySchedulerService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Verify an openMiura portfolio evidence artifact offline.')
    parser.add_argument('artifact', help='Path to a portfolio evidence artifact ZIP file')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON output')
    return parser


def verify_artifact_file(path: str | Path) -> dict[str, Any]:
    artifact_path = Path(path)
    raw = artifact_path.read_bytes()
    service = OpenClawRecoverySchedulerService()
    verification = service._verify_portfolio_evidence_artifact_payload(
        artifact={
            'filename': artifact_path.name,
            'size_bytes': len(raw),
        },
        artifact_b64=base64.b64encode(raw).decode('ascii'),
    )
    verification['offline'] = {
        'mode': 'artifact_file',
        'artifact_path': artifact_path.as_posix(),
        'independent_of_runtime_state': True,
    }
    return verification


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    payload = verify_artifact_file(args.artifact)
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    verification = dict(payload.get('verification') or {}) if isinstance(payload, dict) else {}
    return 0 if payload.get('ok') and verification.get('valid') else 1


if __name__ == '__main__':
    raise SystemExit(main())
