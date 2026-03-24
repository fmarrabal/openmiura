from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from openmiura.core.contracts import AdminGatewayLike


class PackagingHardeningService:
    PHASE_LABEL = 'phase8-pr8'
    DEFAULT_HARDENING = {
        'voice': {
            'max_transcripts_per_minute': 6,
            'max_transcript_chars': 500,
            'max_output_chars': 1200,
            'sensitive_confirmation_required': True,
        },
        'canvas': {
            'max_documents_per_scope': 50,
            'max_nodes_per_canvas': 250,
            'max_edges_per_canvas': 400,
            'max_views_per_canvas': 50,
            'max_payload_chars': 24000,
            'max_comment_chars': 1000,
            'max_snapshot_bytes': 200000,
        },
        'realtime': {
            'poll_timeout_ms': 5000,
            'retry_backoff_ms': 1500,
            'max_retries': 3,
        },
        'pwa': {
            'deep_link_ttl_s': 604800,
            'notification_body_chars': 240,
            'microphone_permission': 'self',
        },
    }

    DEFAULT_REPRO_INCLUDE = [
        'app.py',
        'README.md',
        'pyproject.toml',
        'requirements.txt',
        'openmiura',
        'configs',
        'docs',
        'packaging',
        '.github/workflows',
        'scripts',
    ]
    REPRO_EXCLUDE_PARTS = {'__pycache__', '.pytest_cache', 'dist', 'data', '.git'}
    ZIP_TS = (2020, 1, 1, 0, 0, 0)

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def hardening_summary(self, gw: AdminGatewayLike | None = None) -> dict[str, Any]:
        profile = {k: dict(v) for k, v in self.DEFAULT_HARDENING.items()}
        return {
            'ok': True,
            'phase': self.PHASE_LABEL,
            'profile': profile,
            'checks': {
                'voice_rate_limiting': True,
                'canvas_payload_limits': True,
                'realtime_retry_profile': True,
                'pwa_microphone_permission': True,
                'reproducible_packaging': True,
            },
        }

    def packaging_summary(self, gw: AdminGatewayLike | None = None) -> dict[str, Any]:
        root = self._project_root()
        desktop_dir = root / 'packaging' / 'desktop' / 'electron'
        mobile_dir = root / 'packaging' / 'mobile' / 'capacitor'
        docs_dir = root / 'docs' / 'quickstarts'
        workflows_dir = root / '.github' / 'workflows'
        files = {
            'desktop': [str(path.relative_to(root)).replace('\\', '/') for path in sorted(desktop_dir.rglob('*')) if path.is_file()],
            'mobile': [str(path.relative_to(root)).replace('\\', '/') for path in sorted(mobile_dir.rglob('*')) if path.is_file()],
            'quickstarts': [str(path.relative_to(root)).replace('\\', '/') for path in sorted(docs_dir.glob('*.md')) if path.is_file()],
            'workflows': [str(path.relative_to(root)).replace('\\', '/') for path in sorted(workflows_dir.glob('*.yml')) if path.is_file()],
        }
        return {
            'ok': True,
            'phase': self.PHASE_LABEL,
            'targets': {
                'desktop': {'enabled': desktop_dir.exists(), 'wrapper': 'electron', 'microphone_permission': 'self', 'deep_links': True, 'notifications': True},
                'mobile': {'enabled': mobile_dir.exists(), 'wrapper': 'capacitor', 'microphone_permission': 'self', 'deep_links': True, 'notifications': True},
                'reproducible_ci': {'enabled': (workflows_dir / 'package-reproducible.yml').exists(), 'artifact_manifest': True, 'hash_locked': True},
            },
            'files': files,
            'hardening': self.hardening_summary(gw).get('profile', {}),
        }

    def create_package_build(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        target: str,
        label: str,
        version: str = 'phase8-pr8',
        artifact_path: str = '',
        status: str = 'ready',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        build = gw.audit.create_package_build(
            target=str(target or 'desktop').strip() or 'desktop',
            label=str(label or 'Phase 8 shell').strip() or 'Phase 8 shell',
            version=str(version or 'phase8-pr8').strip() or 'phase8-pr8',
            artifact_path=str(artifact_path or '').strip(),
            status=str(status or 'ready').strip() or 'ready',
            created_by=str(actor or 'admin'),
            metadata=dict(metadata or {}),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        gw.audit.log_event('admin', 'packaging', str(actor or 'admin'), build['build_id'], {'action': 'package_build_recorded', 'target': build['target'], 'label': build['label'], 'artifact_path': build['artifact_path']}, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {'ok': True, 'build': build}

    def list_package_builds(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        target: str | None = None,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        items = gw.audit.list_package_builds(limit=limit, target=target, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {'ok': True, 'items': items, 'summary': {'count': len(items), 'targets': sorted({str(item.get('target') or '') for item in items if str(item.get('target') or '')})}}

    def create_reproducible_build(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        target: str,
        label: str,
        version: str = 'phase9-operational-hardening',
        source_root: str | None = None,
        output_dir: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        root = Path(source_root).resolve() if source_root else self._project_root()
        dist_dir = Path(output_dir).resolve() if output_dir else root / 'dist'
        dist_dir.mkdir(parents=True, exist_ok=True)
        manifest = self._manifest_for_root(root)
        manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
        manifest_hash = hashlib.sha256(manifest_json.encode('utf-8')).hexdigest()
        base_name = f"openmiura-{str(target or 'bundle').strip()}-{str(version or 'phase9').strip()}-{manifest_hash[:12]}"
        artifact_path = dist_dir / f'{base_name}.zip'
        manifest_path = dist_dir / f'{base_name}.manifest.json'
        self._write_reproducible_zip(root, artifact_path, manifest['files'])
        manifest_path.write_text(manifest_json + '\n', encoding='utf-8')
        build = gw.audit.create_package_build(
            target=str(target or 'bundle').strip() or 'bundle',
            label=str(label or 'Reproducible build').strip() or 'Reproducible build',
            version=str(version or 'phase9-operational-hardening').strip() or 'phase9-operational-hardening',
            artifact_path=str(artifact_path),
            status='ready',
            created_by=str(actor or 'admin'),
            metadata={
                'reproducible': True,
                'manifest_hash': manifest_hash,
                'manifest_path': str(manifest_path),
                'file_count': len(manifest['files']),
                'source_root': str(root),
            },
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        gw.audit.log_event('admin', 'packaging', str(actor or 'admin'), build['build_id'], {'action': 'reproducible_package_built', 'artifact_path': str(artifact_path), 'manifest_hash': manifest_hash}, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {'ok': True, 'build': build, 'artifact_path': str(artifact_path), 'manifest_path': str(manifest_path), 'manifest_hash': manifest_hash, 'file_count': len(manifest['files'])}

    def verify_reproducible_manifest(self, *, manifest_path: str) -> dict[str, Any]:
        path = Path(manifest_path).resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        payload = json.loads(path.read_text(encoding='utf-8'))
        root = Path(payload.get('root') or path.parent).resolve()
        expected_files = list(payload.get('files') or [])
        current = self._manifest_for_root(root, include=[item['path'] for item in expected_files])
        expected = {item['path']: item['sha256'] for item in expected_files}
        actual = {item['path']: item['sha256'] for item in current['files']}
        missing = sorted(path for path in expected if path not in actual)
        changed = sorted(path for path in expected if path in actual and actual[path] != expected[path])
        extra = sorted(path for path in actual if path not in expected)
        return {'ok': not missing and not changed, 'manifest_path': str(path), 'root': str(root), 'missing': missing, 'changed': changed, 'extra': extra, 'expected_count': len(expected), 'actual_count': len(actual)}

    def _manifest_for_root(self, root: Path, include: list[str] | None = None) -> dict[str, Any]:
        selected = include or list(self.DEFAULT_REPRO_INCLUDE)
        files: list[dict[str, Any]] = []
        for relative in selected:
            rel = str(relative).replace('\\', '/').strip('./')
            if not rel:
                continue
            target = root / rel
            if not target.exists():
                continue
            if target.is_file():
                files.append(self._file_manifest_entry(root, target))
            else:
                for path in sorted(target.rglob('*')):
                    if not path.is_file():
                        continue
                    parts = set(path.parts)
                    if parts & self.REPRO_EXCLUDE_PARTS:
                        continue
                    files.append(self._file_manifest_entry(root, path))
        deduped: dict[str, dict[str, Any]] = {item['path']: item for item in files}
        ordered = [deduped[key] for key in sorted(deduped)]
        digest = hashlib.sha256(json.dumps(ordered, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        return {'root': str(root), 'digest': digest, 'files': ordered}

    def _file_manifest_entry(self, root: Path, path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        return {'path': str(path.relative_to(root)).replace('\\', '/'), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}

    def _write_reproducible_zip(self, root: Path, artifact_path: Path, files: list[dict[str, Any]]) -> None:
        with zipfile.ZipFile(artifact_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for item in files:
                rel = str(item['path'])
                src = root / rel
                info = zipfile.ZipInfo(rel, self.ZIP_TS)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o644 << 16
                zf.writestr(info, src.read_bytes())
