from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
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
    RELEASE_MANIFEST_NAME = 'RELEASE_MANIFEST.json'
    RELEASE_CHECKSUMS_NAME = 'SHA256SUMS.txt'
    RELEASE_REQUIRED_KINDS = ('wheel', 'sdist', 'reproducible_bundle', 'reproducible_manifest')

    RELEASE_MANIFEST_NAME = 'RELEASE_MANIFEST.json'
    RELEASE_CHECKSUMS_NAME = 'SHA256SUMS.txt'
    RELEASE_REQUIRED_KINDS = (
        'wheel',
        'sdist',
        'reproducible_bundle',
        'reproducible_manifest',
    )

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
<<<<<<< HEAD
            'desktop': [
                str(path.relative_to(root)).replace('\\', '/')
                for path in sorted(desktop_dir.rglob('*'))
                if path.is_file()
            ],
            'mobile': [
                str(path.relative_to(root)).replace('\\', '/')
                for path in sorted(mobile_dir.rglob('*'))
                if path.is_file()
            ],
            'quickstarts': [
                str(path.relative_to(root)).replace('\\', '/')
                for path in sorted(docs_dir.glob('*.md'))
                if path.is_file()
            ],
            'workflows': [
                str(path.relative_to(root)).replace('\\', '/')
                for path in sorted(workflows_dir.glob('*.yml'))
                if path.is_file()
            ],
=======
            'desktop': [str(path.relative_to(root)).replace('\\', '/') for path in sorted(desktop_dir.rglob('*')) if path.is_file()],
            'mobile': [str(path.relative_to(root)).replace('\\', '/') for path in sorted(mobile_dir.rglob('*')) if path.is_file()],
            'quickstarts': [str(path.relative_to(root)).replace('\\', '/') for path in sorted(docs_dir.glob('*.md')) if path.is_file()],
            'workflows': [str(path.relative_to(root)).replace('\\', '/') for path in sorted(workflows_dir.glob('*.yml')) if path.is_file()],
>>>>>>> origin/main
            'release': [
                rel
                for rel in [
                    'MANIFEST.in',
                    'scripts/build_release_artifacts.py',
                    'scripts/verify_release_artifacts.py',
                    '.github/workflows/release.yml',
                    '.github/actions/setup-openmiura/action.yml',
                ]
                if (root / rel).exists()
            ],
        }
<<<<<<< HEAD

        release = self.release_summary(gw)

=======
        release = self.release_summary(gw)
>>>>>>> origin/main
        return {
            'ok': True,
            'phase': self.PHASE_LABEL,
            'targets': {
<<<<<<< HEAD
                'desktop': {
                    'enabled': desktop_dir.exists(),
                    'wrapper': 'electron',
                    'microphone_permission': 'self',
                    'deep_links': True,
                    'notifications': True,
                },
                'mobile': {
                    'enabled': mobile_dir.exists(),
                    'wrapper': 'capacitor',
                    'microphone_permission': 'self',
                    'deep_links': True,
                    'notifications': True,
                },
                'reproducible_ci': {
                    'enabled': (workflows_dir / 'package-reproducible.yml').exists(),
                    'artifact_manifest': True,
                    'hash_locked': True,
                },
=======
                'desktop': {'enabled': desktop_dir.exists(), 'wrapper': 'electron', 'microphone_permission': 'self', 'deep_links': True, 'notifications': True},
                'mobile': {'enabled': mobile_dir.exists(), 'wrapper': 'capacitor', 'microphone_permission': 'self', 'deep_links': True, 'notifications': True},
                'reproducible_ci': {'enabled': (workflows_dir / 'package-reproducible.yml').exists(), 'artifact_manifest': True, 'hash_locked': True},
>>>>>>> origin/main
                'release_alpha': release.get('release', {}),
            },
            'files': files,
            'hardening': self.hardening_summary(gw).get('profile', {}),
            'release_checks': release.get('checks', {}),
        }

    def release_summary(self, gw: AdminGatewayLike | None = None) -> dict[str, Any]:
        root = self._project_root()
<<<<<<< HEAD

=======
>>>>>>> origin/main
        checks = {
            'manifest_in': (root / 'MANIFEST.in').exists(),
            'release_build_script': (root / 'scripts' / 'build_release_artifacts.py').exists(),
            'release_verify_script': (root / 'scripts' / 'verify_release_artifacts.py').exists(),
            'release_workflow': (root / '.github' / 'workflows' / 'release.yml').exists(),
<<<<<<< HEAD
            'reproducible_workflow': (
                root / '.github' / 'workflows' / 'package-reproducible.yml'
            ).exists(),
            'local_setup_action': (
                root / '.github' / 'actions' / 'setup-openmiura' / 'action.yml'
            ).exists(),
        }

=======
            'reproducible_workflow': (root / '.github' / 'workflows' / 'package-reproducible.yml').exists(),
            'local_setup_action': (root / '.github' / 'actions' / 'setup-openmiura' / 'action.yml').exists(),
        }
>>>>>>> origin/main
        return {
            'ok': all(checks.values()),
            'phase': self.PHASE_LABEL,
            'release': {
                'sdist': True,
                'wheel': True,
                'reproducible_bundle': True,
                'checksums': True,
                'manifest': True,
                'self_hosted_base': True,
            },
            'checks': checks,
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

        gw.audit.log_event(
            'admin',
            'packaging',
            str(actor or 'admin'),
            build['build_id'],
            {
                'action': 'package_build_recorded',
                'target': build['target'],
                'label': build['label'],
                'artifact_path': build['artifact_path'],
            },
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

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
        items = gw.audit.list_package_builds(
            limit=limit,
            target=target,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

        return {
            'ok': True,
            'items': items,
            'summary': {
                'count': len(items),
                'targets': sorted(
                    {
                        str(item.get('target') or '')
                        for item in items
                        if str(item.get('target') or '')
                    }
                ),
            },
        }

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

        base_name = (
            f"openmiura-{str(target or 'bundle').strip()}-"
            f"{str(version or 'phase9').strip()}-{manifest_hash[:12]}"
        )

        artifact_path = dist_dir / f'{base_name}.zip'
        manifest_path = dist_dir / f'{base_name}.manifest.json'

        self._write_reproducible_zip(root, artifact_path, manifest['files'])
        manifest_path.write_text(manifest_json + '\n', encoding='utf-8')

        build = gw.audit.create_package_build(
            target=str(target or 'bundle').strip() or 'bundle',
            label=str(label or 'Reproducible build').strip() or 'Reproducible build',
            version=(
                str(version or 'phase9-operational-hardening').strip()
                or 'phase9-operational-hardening'
            ),
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

        gw.audit.log_event(
            'admin',
            'packaging',
            str(actor or 'admin'),
            build['build_id'],
            {
                'action': 'reproducible_package_built',
                'artifact_path': str(artifact_path),
                'manifest_hash': manifest_hash,
            },
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

        return {
            'ok': True,
            'build': build,
            'artifact_path': str(artifact_path),
            'manifest_path': str(manifest_path),
            'manifest_hash': manifest_hash,
            'file_count': len(manifest['files']),
        }

    def verify_reproducible_manifest(self, *, manifest_path: str) -> dict[str, Any]:
        path = Path(manifest_path).resolve()
        if not path.exists():
            raise FileNotFoundError(path)

        payload = json.loads(path.read_text(encoding='utf-8'))
        root = Path(payload.get('root') or path.parent).resolve()
        expected_files = list(payload.get('files') or [])

        current = self._manifest_for_root(
            root,
            include=[item['path'] for item in expected_files],
        )

        expected = {item['path']: item['sha256'] for item in expected_files}
        actual = {item['path']: item['sha256'] for item in current['files']}

<<<<<<< HEAD
        missing = sorted(item_path for item_path in expected if item_path not in actual)
        changed = sorted(
            item_path
            for item_path in expected
            if item_path in actual and actual[item_path] != expected[item_path]
        )
        extra = sorted(item_path for item_path in actual if item_path not in expected)

        return {
            'ok': not missing and not changed,
            'manifest_path': str(path),
            'root': str(root),
            'missing': missing,
            'changed': changed,
            'extra': extra,
            'expected_count': len(expected),
            'actual_count': len(actual),
        }

=======
>>>>>>> origin/main
    def generate_release_manifest(
        self,
        *,
        dist_dir: str,
        tag: str,
        target: str = 'desktop',
        release_notes_name: str = 'RELEASE_NOTES.md',
    ) -> dict[str, Any]:
        dist = Path(dist_dir).resolve()
        dist.mkdir(parents=True, exist_ok=True)
<<<<<<< HEAD

=======
>>>>>>> origin/main
        artifacts: list[dict[str, Any]] = []
        for path in sorted(dist.iterdir()):
            if not path.is_file():
                continue
            if path.name in {self.RELEASE_MANIFEST_NAME, self.RELEASE_CHECKSUMS_NAME}:
                continue
<<<<<<< HEAD

            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            artifacts.append(
                {
                    'filename': path.name,
                    'sha256': sha,
                    'size': path.stat().st_size,
                    'kind': self._classify_release_artifact(path.name),
                }
            )

        checksums_path = dist / self.RELEASE_CHECKSUMS_NAME
        checksum_lines = [f"{item['sha256']} {item['filename']}" for item in artifacts]
        checksums_path.write_text(
            '\n'.join(checksum_lines) + ('\n' if checksum_lines else ''),
            encoding='utf-8',
        )

        kinds_present = sorted(
            {
                str(item.get('kind') or '')
                for item in artifacts
                if str(item.get('kind') or '')
            }
        )
        missing_required = [
            kind for kind in self.RELEASE_REQUIRED_KINDS if kind not in kinds_present
        ]

=======
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            artifacts.append({
                'filename': path.name,
                'sha256': sha,
                'size': path.stat().st_size,
                'kind': self._classify_release_artifact(path.name),
            })
        checksums_path = dist / self.RELEASE_CHECKSUMS_NAME
        checksum_lines = [f"{item['sha256']}  {item['filename']}" for item in artifacts]
        checksums_path.write_text('\n'.join(checksum_lines) + ('\n' if checksum_lines else ''), encoding='utf-8')
        kinds_present = sorted({str(item.get('kind') or '') for item in artifacts if str(item.get('kind') or '')})
        missing_required = [kind for kind in self.RELEASE_REQUIRED_KINDS if kind not in kinds_present]
>>>>>>> origin/main
        notes_path = dist / release_notes_name
        manifest = {
            'tag': str(tag or '').strip(),
            'target': str(target or 'desktop').strip() or 'desktop',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'artifacts': artifacts,
            'checksums_path': checksums_path.name,
            'release_notes': notes_path.name if notes_path.exists() else None,
            'required_kinds': list(self.RELEASE_REQUIRED_KINDS),
            'missing_required': missing_required,
            'artifact_count': len(artifacts),
        }
<<<<<<< HEAD

        manifest_path = dist / self.RELEASE_MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n',
            encoding='utf-8',
        )

=======
        manifest_path = dist / self.RELEASE_MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
>>>>>>> origin/main
        return {
            'ok': not missing_required,
            'manifest_path': str(manifest_path),
            'checksums_path': str(checksums_path),
            'missing_required': missing_required,
            'artifact_count': len(artifacts),
            'artifacts': artifacts,
        }

    def verify_release_artifacts(self, *, dist_dir: str) -> dict[str, Any]:
        dist = Path(dist_dir).resolve()
        manifest_path = dist / self.RELEASE_MANIFEST_NAME
        checksums_path = dist / self.RELEASE_CHECKSUMS_NAME
<<<<<<< HEAD

        missing: list[str] = []
        changed: list[str] = []

        if not manifest_path.exists():
            missing.append(self.RELEASE_MANIFEST_NAME)
            return {
                'ok': False,
                'dist_dir': str(dist),
                'missing': missing,
                'changed': changed,
                'missing_required': list(self.RELEASE_REQUIRED_KINDS),
            }

        if not checksums_path.exists():
            missing.append(self.RELEASE_CHECKSUMS_NAME)

        payload = json.loads(manifest_path.read_text(encoding='utf-8'))
        artifacts = list(payload.get('artifacts') or [])

=======
        missing: list[str] = []
        changed: list[str] = []
        if not manifest_path.exists():
            missing.append(self.RELEASE_MANIFEST_NAME)
            return {'ok': False, 'dist_dir': str(dist), 'missing': missing, 'changed': changed, 'missing_required': list(self.RELEASE_REQUIRED_KINDS)}
        if not checksums_path.exists():
            missing.append(self.RELEASE_CHECKSUMS_NAME)
        payload = json.loads(manifest_path.read_text(encoding='utf-8'))
        artifacts = list(payload.get('artifacts') or [])
>>>>>>> origin/main
        checksum_map: dict[str, str] = {}
        if checksums_path.exists():
            for raw in checksums_path.read_text(encoding='utf-8').splitlines():
                line = raw.strip()
                if not line:
                    continue
<<<<<<< HEAD
                digest, _, filename = line.partition(' ')
                if digest and filename:
                    checksum_map[filename] = digest

=======
                digest, _, filename = line.partition('  ')
                if digest and filename:
                    checksum_map[filename] = digest
>>>>>>> origin/main
        kinds_present: set[str] = set()
        for item in artifacts:
            filename = str(item.get('filename') or '')
            if not filename:
                continue
<<<<<<< HEAD

=======
>>>>>>> origin/main
            path = dist / filename
            if not path.exists():
                missing.append(filename)
                continue
<<<<<<< HEAD

=======
>>>>>>> origin/main
            current_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if current_sha != str(item.get('sha256') or ''):
                changed.append(filename)
            elif checksum_map.get(filename) not in {None, current_sha}:
                changed.append(filename)
<<<<<<< HEAD

            kinds_present.add(str(item.get('kind') or ''))

        missing_required = [
            kind for kind in self.RELEASE_REQUIRED_KINDS if kind not in kinds_present
        ]

=======
            kinds_present.add(str(item.get('kind') or ''))
        missing_required = [kind for kind in self.RELEASE_REQUIRED_KINDS if kind not in kinds_present]
>>>>>>> origin/main
        return {
            'ok': not missing and not changed and not missing_required,
            'dist_dir': str(dist),
            'manifest_path': str(manifest_path),
            'checksums_path': str(checksums_path),
            'missing': sorted(set(missing)),
            'changed': sorted(set(changed)),
            'missing_required': missing_required,
            'artifact_count': len(artifacts),
        }

    def _classify_release_artifact(self, filename: str) -> str:
        name = str(filename or '').strip()
        lower = name.lower()
<<<<<<< HEAD

=======
>>>>>>> origin/main
        if lower.endswith('.whl'):
            return 'wheel'
        if lower.endswith('.tar.gz'):
            return 'sdist'
        if lower.endswith('.manifest.json'):
            return 'reproducible_manifest'
        if lower.endswith('.zip'):
            return 'reproducible_bundle'
        if lower == 'release_notes.md':
            return 'release_notes'
<<<<<<< HEAD

        return 'other'

    def _manifest_for_root(
        self,
        root: Path,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
=======
        return 'other'

    def _manifest_for_root(self, root: Path, include: list[str] | None = None) -> dict[str, Any]:
>>>>>>> origin/main
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

        digest = hashlib.sha256(
            json.dumps(ordered, ensure_ascii=False, sort_keys=True).encode('utf-8')
        ).hexdigest()

        return {
            'root': str(root),
            'digest': digest,
            'files': ordered,
        }

    def _file_manifest_entry(self, root: Path, path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        return {
            'path': str(path.relative_to(root)).replace('\\', '/'),
            'sha256': hashlib.sha256(raw).hexdigest(),
            'size': len(raw),
        }

    def _write_reproducible_zip(
        self,
        root: Path,
        artifact_path: Path,
        files: list[dict[str, Any]],
    ) -> None:
        with zipfile.ZipFile(
            artifact_path,
            'w',
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as zf:
            for item in files:
                rel = str(item['path'])
                src = root / rel

                info = zipfile.ZipInfo(rel, self.ZIP_TS)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o644 << 16

                zf.writestr(info, src.read_bytes())