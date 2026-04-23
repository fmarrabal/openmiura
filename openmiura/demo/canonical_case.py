from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway

CANONICAL_DEMO_NAME = 'Governed runtime alert policy activation'
CANONICAL_SCOPE = {
    'tenant_id': 'tenant-a',
    'workspace_id': 'ws-a',
    'environment': 'prod',
}
_DEFAULT_HEADERS = {'Authorization': 'Bearer secret-admin'}


def _weekday_utc() -> int:
    return datetime.now(timezone.utc).weekday()


def canonical_runtime_metadata() -> dict[str, Any]:
    return {
        'runtime_class': 'incident',
        'allowed_actions': ['chat'],
        'dispatch_policy': {
            'dispatch_mode': 'async',
            'poll_after_s': 0.1,
            'max_active_runs': 1,
            'max_active_runs_per_workspace': 1,
        },
        'heartbeat_policy': {
            'runtime_stale_after_s': 120,
            'active_run_stale_after_s': 60,
            'auto_reconcile_after_s': 600,
            'poll_interval_s': 5,
            'max_poll_retries': 1,
            'auto_poll_enabled': False,
            'auto_reconcile_enabled': False,
            'stale_target_status': 'timed_out',
        },
        'session_bridge': {
            'enabled': True,
            'workspace_connection': 'primary-conn',
            'external_workspace_id': 'oc-ws-a',
            'external_environment': 'prod',
            'event_bridge_enabled': True,
        },
        'governance_release_policy': {
            'approval_required': True,
            'requested_role': 'security',
            'ttl_s': 1800,
            'require_signature': True,
            'signer_key_id': 'governance-ci',
        },
    }


def canonical_candidate_policy() -> dict[str, Any]:
    return {
        'default_timezone': 'UTC',
        'quiet_hours': {
            'enabled': True,
            'timezone': 'UTC',
            'weekdays': [_weekday_utc()],
            'start_time': '00:00',
            'end_time': '23:59',
            'action': 'schedule',
        },
    }


def write_self_contained_demo_config(path: Path) -> None:
    db_path = (path.parent / 'audit.db').as_posix()
    sandbox_dir = (path.parent / 'sandbox').as_posix()
    path.write_text(
        f'''\
server:
  host: "127.0.0.1"
  port: 8081
storage:
  db_path: "{db_path}"
llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5:7b-instruct"
runtime:
  history_limit: 6
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
admin:
  enabled: true
  token: secret-admin
broker:
  enabled: true
  base_path: "/broker"
auth:
  enabled: true
  session_ttl_s: 3600
''',
        encoding='utf-8',
    )


def _json(client: Any, method: str, url: str, *, headers: dict[str, str] | None = None, json_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    method_name = method.lower()
    call = getattr(client, method_name)
    kwargs: dict[str, Any] = {'headers': headers}
    if json_payload is not None and method_name not in {'get', 'head', 'delete'}:
        kwargs['json'] = json_payload
    response = call(url, **kwargs)
    if int(getattr(response, 'status_code', 500)) >= 400:
        detail = getattr(response, 'text', '')
        raise RuntimeError(f'{method} {url} failed: {getattr(response, "status_code", "?")} {detail}')
    return dict(response.json())


def _admin_headers(token: str = 'secret-admin') -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


def run_canonical_demo(client: Any, *, admin_token: str = 'secret-admin') -> dict[str, Any]:
    headers = _admin_headers(admin_token)
    scope = dict(CANONICAL_SCOPE)

    runtime = _json(
        client,
        'POST',
        '/admin/openclaw/runtimes',
        headers=headers,
        json_payload={
            'actor': 'admin',
            'name': 'canonical-governed-runtime',
            'base_url': 'simulated://openclaw',
            'transport': 'simulated',
            'allowed_agents': ['default'],
            **scope,
            'metadata': canonical_runtime_metadata(),
        },
    )
    runtime_id = str((runtime.get('runtime') or {}).get('runtime_id') or '')
    if not runtime_id:
        raise RuntimeError('canonical demo did not return a runtime_id')

    dispatch = _json(
        client,
        'POST',
        f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
        headers=headers,
        json_payload={
            'actor': 'admin',
            'action': 'chat',
            'agent_id': 'default',
            'payload': {'message': 'openMiura canonical demo dispatch'},
            'session_id': 'canonical-demo-session',
            **scope,
        },
    )

    activation = _json(
        client,
        'POST',
        f'/admin/openclaw/runtimes/{runtime_id}/alert-governance/activate',
        headers=headers,
        json_payload={
            'actor': 'platform-admin',
            'candidate_policy': canonical_candidate_policy(),
            'reason': 'activate governed quiet-hours policy for incident runtime',
            **scope,
        },
    )
    approval_id = str(((activation.get('approval') or {}).get('approval_id')) or '')
    version_id = str(((activation.get('version') or {}).get('version_id')) or '')

    approvals_before = _json(
        client,
        'GET',
        f'/admin/openclaw/alert-governance-promotion-approvals?runtime_id={runtime_id}&tenant_id={scope["tenant_id"]}&workspace_id={scope["workspace_id"]}&environment={scope["environment"]}',
        headers=headers,
    )

    canvas = _json(
        client,
        'POST',
        '/admin/canvas/documents',
        headers=headers,
        json_payload={'actor': 'platform-admin', 'title': 'Canonical governance approval canvas', **scope},
    )
    canvas_id = str(((canvas.get('document') or {}).get('canvas_id')) or '')
    node = _json(
        client,
        'POST',
        f'/admin/canvas/documents/{canvas_id}/nodes',
        headers=headers,
        json_payload={
            'actor': 'platform-admin',
            'node_type': 'openclaw_runtime',
            'label': 'Canonical runtime node',
            'data': {'runtime_id': runtime_id},
            **scope,
        },
    )
    node_id = str(((node.get('node') or {}).get('node_id')) or '')

    inspector = _json(
        client,
        'GET',
        f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id={scope["tenant_id"]}&workspace_id={scope["workspace_id"]}&environment={scope["environment"]}',
        headers=headers,
    )

    canvas_approval = _json(
        client,
        'POST',
        f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_governance_promotion?tenant_id={scope["tenant_id"]}&workspace_id={scope["workspace_id"]}&environment={scope["environment"]}',
        headers=headers,
        json_payload={
            'actor': 'security-admin',
            'reason': 'approved from canonical demo canvas',
            'payload': {'approval_id': approval_id},
        },
    )
    approval_result = dict(canvas_approval.get('result') or {})

    versions = _json(
        client,
        'GET',
        f'/admin/openclaw/runtimes/{runtime_id}/alert-governance/versions?tenant_id={scope["tenant_id"]}&workspace_id={scope["workspace_id"]}&environment={scope["environment"]}',
        headers=headers,
    )

    runtime_timeline = _json(
        client,
        'GET',
        f'/admin/openclaw/runtimes/{runtime_id}/timeline?tenant_id={scope["tenant_id"]}&workspace_id={scope["workspace_id"]}&environment={scope["environment"]}&limit=25',
        headers=headers,
    )

    admin_events = _json(client, 'GET', '/admin/events?limit=25', headers=headers)

    validation = {
        'approval_required': bool(activation.get('approval_required')),
        'blocked_before_approval': str(((activation.get('version') or {}).get('status')) or '') == 'pending_approval' and not bool(((activation.get('runtime_summary') or {}).get('alert_governance_policy') or {}).get('quiet_hours', {}).get('enabled')),
        'pending_approval_visible': int((approvals_before.get('summary') or {}).get('pending_count') or 0) >= 1,
        'canvas_operator_action_visible': 'approve_governance_promotion' in list(inspector.get('available_actions') or []),
        'executed_after_approval': str((approval_result.get('version') or {}).get('status') or '') == 'active',
        'signed_release_present': bool(((approval_result.get('version') or {}).get('release') or {}).get('signed')),
        'runtime_timeline_available': len(list(runtime_timeline.get('timeline') or [])) > 0,
        'admin_events_available': len(list(admin_events.get('items') or [])) > 0,
        'current_version_matches': str(((versions.get('current_version') or {}).get('version_id')) or '') == version_id,
    }

    return {
        'demo': {
            'name': CANONICAL_DEMO_NAME,
            'objective': 'Govern a sensitive operational policy change on a runtime, require human approval, execute only after approval, and leave an auditable signed trail.',
            'scope': scope,
            'actors': {
                'requester': 'platform-admin',
                'approver': 'security-admin',
                'operator_surface': 'canvas runtime inspector',
            },
            'runtime_id': runtime_id,
            'approval_id': approval_id,
            'version_id': version_id,
        },
        'steps': {
            'runtime_created': runtime,
            'runtime_dispatched': dispatch,
            'governance_activation_requested': activation,
            'pending_approvals_before_decision': approvals_before,
            'canvas_document': canvas,
            'canvas_node': node,
            'canvas_inspector': inspector,
            'canvas_approval_result': canvas_approval,
            'versions_after_approval': versions,
            'runtime_timeline': runtime_timeline,
            'admin_events': admin_events,
        },
        'validation': validation,
        'success': all(validation.values()),
    }


def build_self_contained_demo_report() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix='openmiura-canonical-demo-') as tmpdir:
        tmp_path = Path(tmpdir)
        cfg = tmp_path / 'openmiura.yaml'
        write_self_contained_demo_config(cfg)
        app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
        report = None
        try:
            with TestClient(app) as client:
                report = run_canonical_demo(client)
        finally:
            gw = getattr(app.state, 'gw', None)
            try:
                close_fn = getattr(gw, 'close', None)
                if callable(close_fn):
                    close_fn()
            except Exception:
                pass
        report['execution'] = {
            'mode': 'self_contained_testclient',
            'config_path': str(cfg),
            'temp_dir': str(tmp_path),
        }
        return report


def build_live_demo_report(*, base_url: str, admin_token: str = 'secret-admin', timeout_s: float = 30.0) -> dict[str, Any]:
    with httpx.Client(base_url=base_url.rstrip('/'), timeout=timeout_s) as client:
        report = run_canonical_demo(client, admin_token=admin_token)
    report['execution'] = {'mode': 'live_http', 'base_url': base_url.rstrip('/')}
    return report


def write_demo_report(report: dict[str, Any], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')
    return output


# Windows-safe override for Sprint 3 canonical demo self-contained report.
def build_self_contained_demo_report() -> dict[str, Any]:
    tmp_path = Path(tempfile.mkdtemp(prefix='openmiura-canonical-demo-'))
    cfg = tmp_path / 'openmiura.yaml'
    write_self_contained_demo_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    report = None
    try:
        with TestClient(app) as client:
            report = run_canonical_demo(client)
    finally:
        gw = getattr(app.state, 'gw', None)
        try:
            close_fn = getattr(gw, 'close', None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass
    report['execution'] = {
        'mode': 'self_contained_testclient',
        'config_path': str(cfg),
        'temp_dir': str(tmp_path),
    }
    return report


# Compatibility override for Sprint 3/5 demo report writing.
def write_demo_report(arg1, arg2) -> Path:
    if isinstance(arg1, (str, Path)):
        output_path = Path(arg1)
        report = arg2
    else:
        report = arg1
        output_path = Path(arg2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')
    return output_path

