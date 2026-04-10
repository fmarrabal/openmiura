from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from tests.test_openclaw_portfolio_evidence_packaging_v2 import (
    _create_runtime,
    _create_submitted_portfolio,
    _set_now,
    _write_config,
)


def _tamper_artifact_content(artifact_b64: str) -> str:
    raw = base64.b64decode(artifact_b64.encode('ascii'))
    source = io.BytesIO(raw)
    target = io.BytesIO()
    with zipfile.ZipFile(source, 'r') as src, zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            payload = src.read(name)
            if name == 'package.json':
                content = json.loads(payload.decode('utf-8'))
                content['report_type'] = 'tampered_portfolio_evidence_package_v1'
                payload = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')
            dst.writestr(name, payload)
    return base64.b64encode(target.getvalue()).decode('ascii')


def test_portfolio_evidence_artifact_verify_and_restore_by_package_id(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_760_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-evidence-artifact')
        portfolio_id = _create_submitted_portfolio(client, headers, base_now=base_now, runtime_id=runtime_id)

        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        exported = export.json()
        assert exported['artifact']['artifact_type'] == 'openmiura_portfolio_evidence_artifact_v1'
        assert exported['artifact']['filename'].endswith('.zip')
        assert exported['artifact']['content_b64']

        verify = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify',
            headers=headers,
            json={
                'actor': 'auditor',
                'package_id': exported['package_id'],
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert verify.status_code == 200, verify.text
        verified = verify.json()
        assert verified['verification']['status'] == 'verified'
        assert verified['verification']['checks']['package_integrity_valid'] is True
        assert verified['verification']['checks']['notarization_valid'] is True
        assert verified['verification']['restorable'] is True

        restore = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-restore',
            headers=headers,
            json={
                'actor': 'auditor',
                'package_id': exported['package_id'],
                'persist_restore_session': True,
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert restore.status_code == 200, restore.text
        restored = restore.json()
        assert restored['verification']['status'] == 'verified'
        assert restored['restore']['summary']['persisted'] is True
        assert restored['restore']['summary']['replay_count'] >= 1
        assert restored['restore']['restore_session']['package_id'] == exported['package_id']
        assert restored['restore']['replay']['summary']['count'] >= 1



def test_portfolio_evidence_artifact_verify_detects_tampering(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_770_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-evidence-tamper')
        portfolio_id = _create_submitted_portfolio(client, headers, base_now=base_now, runtime_id=runtime_id)

        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        exported = export.json()
        tampered_b64 = _tamper_artifact_content(exported['artifact']['content_b64'])

        verify = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify',
            headers=headers,
            json={
                'actor': 'auditor',
                'artifact': {
                    **{k: v for k, v in exported['artifact'].items() if k != 'content_b64'},
                    'content_b64': tampered_b64,
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert verify.status_code == 200, verify.text
        verified = verify.json()
        assert verified['verification']['status'] == 'failed'
        assert verified['verification']['checks']['archive_hash_valid'] is False or verified['verification']['checks']['package_integrity_valid'] is False
        assert verified['verification']['restorable'] is False



def test_canvas_runtime_node_exposes_verify_and_restore_artifact_actions(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_780_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-canvas-evidence-artifact')
        portfolio_id = _create_submitted_portfolio(client, headers, base_now=base_now, runtime_id=runtime_id)

        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        package_id = export.json()['package_id']

        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Artifact canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']
        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={
                'actor': 'admin',
                'node_type': 'runtime',
                'label': 'Runtime node',
                'data': {'runtime_id': runtime_id},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert node.status_code == 200, node.text
        node_id = node.json()['node']['node_id']

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        payload = inspector.json()
        assert 'verify_portfolio_evidence_artifact' in payload['available_actions']
        assert 'restore_portfolio_evidence_artifact' in payload['available_actions']

        verify = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/verify_portfolio_evidence_artifact?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'payload': {'portfolio_id': portfolio_id, 'package_id': package_id}, 'session_id': 'canvas-admin'},
        )
        assert verify.status_code == 200, verify.text
        assert verify.json()['result']['verification']['status'] == 'verified'

        restore = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/restore_portfolio_evidence_artifact?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'payload': {'portfolio_id': portfolio_id, 'package_id': package_id}, 'session_id': 'canvas-admin'},
        )
        assert restore.status_code == 200, restore.text
        assert restore.json()['result']['restore']['summary']['replay_count'] >= 1
