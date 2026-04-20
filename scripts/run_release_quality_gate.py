from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openmiura.application.packaging import PackagingHardeningService
from openmiura.core.audit import AuditStore
DEFAULT_REQUIRED = ROOT / 'ops' / 'quality_gate' / 'release_required.txt'
DEFAULT_EXTENDED = ROOT / 'ops' / 'quality_gate' / 'release_extended.txt'
COLLECT_RE = re.compile(r'^(tests/.+?):\s+(\d+)$')


@dataclass
class CommandResult:
    name: str
    command: list[str]
    returncode: int
    duration_s: float
    stdout: str
    stderr: str
    log_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'command': self.command,
            'returncode': self.returncode,
            'duration_s': round(self.duration_s, 3),
            'stdout_tail': self.stdout[-4000:],
            'stderr_tail': self.stderr[-4000:],
            'log_path': self.log_path,
            'ok': self.returncode == 0,
        }


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run the openMiura release quality gate')
    parser.add_argument('--config', default='configs/openmiura.yaml')
    parser.add_argument('--output-dir', default='reports/quality_gate')
    parser.add_argument('--required-list', default=str(DEFAULT_REQUIRED))
    parser.add_argument('--extended-list', default=str(DEFAULT_EXTENDED))
    parser.add_argument('--include-extended', action='store_true')
    parser.add_argument('--skip-coverage', action='store_true')
    parser.add_argument('--skip-doctor', action='store_true')
    parser.add_argument('--skip-build', action='store_true')
    return parser.parse_args(argv)


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def load_test_list(path: Path) -> list[str]:
    tests: list[str] = []
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        tests.append(line)
    return tests


def _write_log(output_dir: Path, name: str, stdout: str, stderr: str) -> str:
    log_path = output_dir / f'{name}.log'
    log_path.write_text(stdout + ('\n\n[stderr]\n' + stderr if stderr else ''), encoding='utf-8')
    return str(log_path)


def run_command(name: str, command: list[str], *, output_dir: Path, cwd: Path = ROOT) -> CommandResult:
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    elapsed = time.perf_counter() - started
    log_path = _write_log(output_dir, name, completed.stdout, completed.stderr)
    return CommandResult(
        name=name,
        command=command,
        returncode=completed.returncode,
        duration_s=elapsed,
        stdout=completed.stdout,
        stderr=completed.stderr,
        log_path=log_path,
    )


def parse_collect_inventory(stdout: str) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for line in stdout.splitlines():
        match = COLLECT_RE.match(line.strip())
        if match:
            counts[match.group(1)] = int(match.group(2))
    return {'file_count': len(counts), 'total_tests': sum(counts.values()), 'files': counts}


def coverage_summary(coverage_xml: Path) -> dict[str, Any] | None:
    if not coverage_xml.exists():
        return None
    root = ET.fromstring(coverage_xml.read_text(encoding='utf-8'))
    line_rate = float(root.attrib.get('line-rate', '0'))
    branch_rate = float(root.attrib.get('branch-rate', '0'))
    return {'line_rate': round(line_rate * 100, 2), 'branch_rate': round(branch_rate * 100, 2), 'path': str(coverage_xml)}


def run_packaging_smoke(output_dir: Path) -> dict[str, Any]:
    smoke_root = output_dir / 'packaging_smoke'
    smoke_root.mkdir(parents=True, exist_ok=True)
    audit = AuditStore(str(smoke_root / 'reproducible-builds.db'))
    audit.init_db()
    gw = _GW(audit)
    service = PackagingHardeningService()
    created = service.create_reproducible_build(
        gw,
        actor='quality-gate',
        target='desktop',
        label='Release quality gate smoke',
        version='quality-gate',
        source_root=str(ROOT),
        output_dir=str(smoke_root / 'dist'),
    )
    verified = service.verify_reproducible_manifest(manifest_path=created['manifest_path'])
    return {'created': created, 'verified': verified, 'ok': bool(created.get('ok')) and bool(verified.get('ok'))}


def maybe_run_full_release_build(output_dir: Path, *, skip_build: bool) -> dict[str, Any]:
    if skip_build:
        return {'ok': False, 'skipped': True, 'reason': 'skipped by flag'}
    if importlib.util.find_spec('build') is None:
        return {'ok': False, 'skipped': True, 'reason': 'python package "build" is not installed'}
    dist_dir = output_dir / 'release_dist'
    build_cmd = run_command(
        'build_release_artifacts',
        [sys.executable, 'scripts/build_release_artifacts.py', '--dist-dir', str(dist_dir), '--tag', 'v-quality-gate', '--target', 'desktop', '--strict'],
        output_dir=output_dir,
    )
    verify_cmd = run_command(
        'verify_release_artifacts',
        [sys.executable, 'scripts/verify_release_artifacts.py', '--dist-dir', str(dist_dir)],
        output_dir=output_dir,
    )
    return {'ok': build_cmd.returncode == 0 and verify_cmd.returncode == 0, 'skipped': False, 'dist_dir': str(dist_dir), 'build': build_cmd.to_dict(), 'verify': verify_cmd.to_dict()}


def _pytest_command(tests: list[str], *, junit_path: Path, coverage_xml: Path | None) -> list[str]:
    command = [sys.executable, '-m', 'pytest', '-q', '--junitxml', str(junit_path)]
    if coverage_xml is not None:
        command.extend(['--cov=openmiura', f'--cov-report=xml:{coverage_xml}', '--cov-report=term-missing:skip-covered'])
    command.extend(tests)
    return command


def chunk_tests(tests: list[str], *, size: int = 5) -> list[list[str]]:
    return [tests[idx: idx + size] for idx in range(0, len(tests), size)]


def run_pytest_chunks(name: str, tests: list[str], *, output_dir: Path, coverage_enabled: bool = False) -> dict[str, Any]:
    groups = chunk_tests(tests)
    results: list[dict[str, Any]] = []
    coverage = None
    all_ok = True
    for index, group in enumerate(groups, start=1):
        junit_path = output_dir / f'junit-{name}-{index}.xml'
        cov_path = output_dir / f'coverage-{name}.xml' if coverage_enabled and len(groups) == 1 else None
        cmd = run_command(f'{name}_{index}', _pytest_command(group, junit_path=junit_path, coverage_xml=cov_path), output_dir=output_dir)
        result = cmd.to_dict()
        result['tests'] = group
        result['junit_path'] = str(junit_path)
        results.append(result)
        all_ok = all_ok and result['ok']
        if cov_path is not None:
            coverage = coverage_summary(cov_path)
    return {'ok': all_ok, 'groups': results, 'coverage': coverage, 'group_count': len(groups)}


def render_markdown(report: dict[str, Any]) -> str:
    inventory = report['inventory']
    lines = [
        '# Release quality gate report',
        '',
        f"- Generated at: {report['generated_at']}",
        f"- Python: {report['environment']['python']}",
        f"- Platform: {report['environment']['platform']}",
        f"- Collected tests: {inventory.get('total_tests', 0)} across {inventory.get('file_count', 0)} files",
        f"- Required gate passed: {report['gate']['required_gate_passed']}",
        f"- Full release gate passed: {report['gate']['full_release_gate_passed']}",
        '',
        '## Required suites',
        '',
        f"- Suite files: {len(report['required_tests'])}",
        f"- Command status: {report['required_result']['ok']}",
        f"- Group count: {report['required_result']['group_count']}",
        f"- First JUnit XML: `{report['required_result']['groups'][0]['junit_path']}`",
    ]
    coverage = report['required_result'].get('coverage')
    if coverage:
        lines.append(f"- Coverage (required gate): {coverage['line_rate']}% line / {coverage['branch_rate']}% branch")
    lines.extend(['', '## Packaging smoke', '', f"- Reproducible bundle smoke: {report['packaging_smoke']['ok']}", f"- Full build stage skipped: {report['full_release_build'].get('skipped', False)}"])
    if report['full_release_build'].get('reason'):
        lines.append(f"- Reason: {report['full_release_build']['reason']}")
    if report.get('extended_result'):
        lines.extend(['', '## Extended suites', '', '- Included: True', f"- Command status: {report['extended_result']['ok']}", f"- Group count: {report['extended_result']['group_count']}", f"- First JUnit XML: `{report['extended_result']['groups'][0]['junit_path']}`"])
    else:
        lines.extend(['', '## Extended suites', '', '- Included: False'])
    lines.extend(['', '## Doctor and inventory', '', f"- Doctor executed: {report['doctor_result'] is not None}", f"- Doctor status: {report['doctor_result']['ok'] if report['doctor_result'] else 'skipped'}", '', '## Gate decision', '', '- Required gate passed when doctor, curated suites and packaging smoke are all green.', '- Full release gate additionally requires `python -m build` availability and a green artifact verification pass.'])
    return '\n'.join(lines) + '\n'


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = _resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    required_tests = load_test_list(_resolve(args.required_list))
    extended_tests = load_test_list(_resolve(args.extended_list))
    inventory_cmd = run_command('collect_only', [sys.executable, '-m', 'pytest', '--collect-only', '-q'], output_dir=output_dir)
    inventory = parse_collect_inventory(inventory_cmd.stdout)
    doctor_result = None
    if not args.skip_doctor:
        doctor_result = run_command('doctor', [sys.executable, '-m', 'openmiura', 'doctor', '--config', args.config], output_dir=output_dir).to_dict()
    packaging_smoke = run_packaging_smoke(output_dir)
    required_result = run_pytest_chunks('required', required_tests, output_dir=output_dir, coverage_enabled=not args.skip_coverage)
    extended_result = None
    if args.include_extended and extended_tests:
        extended_result = run_pytest_chunks('extended', extended_tests, output_dir=output_dir, coverage_enabled=False)
    full_release_build = maybe_run_full_release_build(output_dir, skip_build=args.skip_build)
    required_gate_passed = inventory_cmd.returncode == 0 and (doctor_result is None or bool(doctor_result.get('ok'))) and bool(packaging_smoke.get('ok')) and bool(required_result.get('ok'))
    full_release_gate_passed = required_gate_passed and bool(full_release_build.get('ok'))
    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'environment': {'python': sys.version.split()[0], 'platform': platform.platform(), 'cwd': str(ROOT)},
        'inventory': inventory,
        'collect_result': inventory_cmd.to_dict(),
        'doctor_result': doctor_result,
        'required_tests': required_tests,
        'required_result': required_result,
        'extended_tests': extended_tests if args.include_extended else [],
        'extended_result': extended_result,
        'packaging_smoke': packaging_smoke,
        'full_release_build': full_release_build,
        'gate': {'required_gate_passed': required_gate_passed, 'full_release_gate_passed': full_release_gate_passed},
    }
    json_path = output_dir / 'release_quality_gate_report.json'
    md_path = output_dir / 'release_quality_gate_report.md'
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    md_path.write_text(render_markdown(report), encoding='utf-8')
    print(json.dumps({'ok': full_release_gate_passed, 'required_gate_passed': required_gate_passed, 'report': str(json_path)}, ensure_ascii=False, indent=2))
    return 0 if required_gate_passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
