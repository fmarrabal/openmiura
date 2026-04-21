from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openmiura.application.packaging import PackagingHardeningService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit


def _resolve_dist_dir(raw: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate.resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build openMiura release artifacts and manifest')
    parser.add_argument('--dist-dir', default='dist', help='Output directory for wheel/sdist and release metadata')
    parser.add_argument('--tag', default='v-local', help='Release tag to record in RELEASE_MANIFEST.json')
    parser.add_argument('--target', default='desktop', help='Target label recorded in RELEASE_MANIFEST.json')
    parser.add_argument('--release-notes-name', default='RELEASE_NOTES.md', help='Release notes filename when present')
    parser.add_argument('--strict', action='store_true', help='Return non-zero when release verification is not green')
    return parser.parse_args(argv)


def _ensure_build_available() -> None:
    if importlib.util.find_spec('build') is None:
        raise SystemExit('Missing dependency: python package "build" is required. Install dev extras or `pip install build`.')


def _clean_dist(dist: Path) -> None:
    dist.mkdir(parents=True, exist_ok=True)
    for pattern in ('*.whl', '*.tar.gz', '*.zip', '*.manifest.json', 'RELEASE_MANIFEST.json', 'SHA256SUMS.txt'):
        for path in dist.glob(pattern):
            path.unlink()


def _run_build(dist: Path) -> None:
    cmd = [sys.executable, '-m', 'build', '--sdist', '--wheel', '--outdir', str(dist)]
    subprocess.run(cmd, check=True, cwd=ROOT)


def _build_reproducible_bundle(dist: Path, *, tag: str, target: str) -> dict:
    service = PackagingHardeningService()
    audit = AuditStore(':memory:')
    audit.init_db()
    gw = _GW(audit)
    return service.create_reproducible_build(
        gw,
        actor='release-bot',
        target=target,
        label=f'Release {tag}',
        version=tag,
        source_root=str(ROOT),
        output_dir=str(dist),
    )

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dist_dir = _resolve_dist_dir(args.dist_dir)

    os.environ.setdefault('PYTHONHASHSEED', '0')
    _ensure_build_available()
    _clean_dist(dist_dir)
    _run_build(dist_dir)

    reproducible = _build_reproducible_bundle(dist_dir, tag=args.tag, target=args.target)

    service = PackagingHardeningService()
    manifest = service.generate_release_manifest(
        dist_dir=str(dist_dir),
        tag=args.tag,
        target=args.target,
        release_notes_name=args.release_notes_name,
    )
    verification = service.verify_release_artifacts(dist_dir=str(dist_dir))

    payload = {
        'ok': bool(reproducible.get('ok')) and bool(manifest.get('ok')) and bool(verification.get('ok')),
        'dist_dir': str(dist_dir),
        'reproducible': reproducible,
        'manifest': manifest,
        'verification': verification,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict and not payload['ok']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())