from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP_TS = (2020, 1, 1, 0, 0, 0)
KEEP_REPORT_FILES = {'.gitkeep'}
KEEP_DATA_FILES = {'.gitkeep'}
SKIP_PARTS = {'.git', '.pytest_cache', '__pycache__', 'dist', 'openmiura.egg-info'}
SKIP_SUFFIXES = {'.pyc', '.pyo', '.db', '.db-shm', '.db-wal'}
SKIP_NAMES = {'.env', 'pytest_first_fail.txt'}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Freeze a clean openMiura release-candidate bundle')
    parser.add_argument('--output-dir', default='dist/rc', help='Directory where the RC bundle and manifest will be written')
    parser.add_argument('--label', default='rc1', help='Human-readable label for the candidate bundle')
    parser.add_argument('--version', default='1.0.0-rc1', help='Version string to record in the manifest')
    return parser.parse_args(argv)


def _should_include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in SKIP_PARTS for part in rel.parts):
        return False
    if path.name in SKIP_NAMES:
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    rel_s = rel.as_posix()
    if rel_s.startswith('reports/') and path.name not in KEEP_REPORT_FILES:
        return False
    if rel_s.startswith('data/') and path.name not in KEEP_DATA_FILES and 'voice_assets' in rel.parts:
        return False
    return True


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob('*'):
        if not path.is_file():
            continue
        if _should_include(path):
            files.append(path)
    return sorted(files)


def _write_zip(bundle_path: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(bundle_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(rel, date_time=ZIP_TS)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            data = path.read_bytes()
            zf.writestr(info, data)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = Path(args.output_dir)
    if not out.is_absolute():
        out = (ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    files = _iter_files()
    bundle_name = f'openmiura-{args.label}-{args.version}.zip'
    bundle_path = out / bundle_name
    _write_zip(bundle_path, files)

    manifest = {
        'ok': True,
        'label': args.label,
        'version': args.version,
        'bundle': bundle_name,
        'bundle_sha256': _sha256(bundle_path),
        'file_count': len(files),
        'files': [p.relative_to(ROOT).as_posix() for p in files],
    }
    manifest_path = out / 'release_candidate_manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'bundle_path': str(bundle_path), 'manifest_path': str(manifest_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
