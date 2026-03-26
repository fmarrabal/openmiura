from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from openmiura.application.admin import AdminService
from openmiura.gateway import Gateway

router = APIRouter(tags=["admin"])
_RATE_LIMIT_LOCK = threading.Lock()
_ADMIN_SERVICE = AdminService()


class AdminMemorySearchBody(BaseModel):
    user_key: Optional[str] = Field(default=None)
    kind: Optional[str] = Field(default=None)
    text_contains: Optional[str] = Field(default=None)
    limit: int = Field(default=20, ge=1, le=500)


class AdminMemoryDeleteRequest(BaseModel):
    user_key: str
    kind: Optional[str] = Field(default=None)
    dry_run: bool = Field(default=False)


class IdentityLinkRequest(BaseModel):
    channel_user_key: Optional[str] = None
    channel_key: Optional[str] = None
    global_user_key: str
    linked_by: str = "admin"


class PolicyExplainRequest(BaseModel):
    scope: str = Field(..., description="tool|memory|secret|channel|approval")
    resource_name: str = Field(..., description="Tool name, memory kind, secret ref, channel name or approval action")
    action: str = Field(default="use")
    agent_name: Optional[str] = Field(default=None)
    tool_name: Optional[str] = Field(default=None)
    user_role: Optional[str] = Field(default=None)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)
    channel: Optional[str] = Field(default=None)
    domain: Optional[str] = Field(default=None)
    extra: dict = Field(default_factory=dict)


class PolicyExplorerSimulateRequest(BaseModel):
    request: PolicyExplainRequest
    candidate_policy: dict = Field(default_factory=dict)
    candidate_policy_yaml: Optional[str] = Field(default=None)


class PolicyExplorerDiffRequest(BaseModel):
    candidate_policy: dict = Field(default_factory=dict)
    candidate_policy_yaml: Optional[str] = Field(default=None)
    baseline_policy: dict = Field(default_factory=dict)
    baseline_policy_yaml: Optional[str] = Field(default=None)
    samples: list[dict] = Field(default_factory=list)


class SandboxExplainRequest(BaseModel):
    user_role: Optional[str] = Field(default=None)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)
    channel: Optional[str] = Field(default=None)
    agent_name: Optional[str] = Field(default=None)
    tool_name: Optional[str] = Field(default=None)


class SecurityExplainRequest(BaseModel):
    scope: str = Field(..., description="tool|memory|secret|channel|approval")
    resource_name: str = Field(...)
    action: str = Field(default="use")
    agent_name: Optional[str] = Field(default=None)
    tool_name: Optional[str] = Field(default=None)
    user_role: Optional[str] = Field(default=None)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)
    channel: Optional[str] = Field(default=None)
    domain: Optional[str] = Field(default=None)
    extra: dict = Field(default_factory=dict)


class ComplianceExportRequest(BaseModel):
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)
    window_hours: int = Field(default=72, ge=1, le=24 * 30)
    limit_per_section: int = Field(default=100, ge=1, le=1000)
    sections: list[str] = Field(default_factory=lambda: ["overview", "security", "secret_usage", "approvals", "config_changes", "tool_calls", "sessions"])
    report_label: str = Field(default="initial")


class EvaluationObservation(BaseModel):
    case_id: str = Field(...)
    response_text: Optional[str] = Field(default=None)
    tools_used: list[str] = Field(default_factory=list)
    latency_ms: float = Field(default=0.0, ge=0.0)
    cost: float = Field(default=0.0, ge=0.0)
    policy_ok: Optional[bool] = Field(default=None)
    rubric_score: Optional[float] = Field(default=None)
    metadata: dict = Field(default_factory=dict)


class EvaluationRunRequest(BaseModel):
    suite_name: str = Field(...)
    observations: list[EvaluationObservation] = Field(default_factory=list)
    requested_by: str = Field(default="admin")
    provider: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)
    agent_name: Optional[str] = Field(default=None)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class ReplayCompareRequest(BaseModel):
    left_kind: str = Field(..., description="session|workflow")
    left_id: str = Field(...)
    right_kind: str = Field(..., description="session|workflow")
    right_id: str = Field(...)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)
    limit: int = Field(default=200, ge=1, le=500)


class OperatorActionRequest(BaseModel):
    reason: str = Field(default='')
    action: Optional[str] = Field(default=None)
    actor: Optional[str] = Field(default=None)



class ReleaseBundleItemRequest(BaseModel):
    item_kind: str = Field(...)
    item_key: str = Field(...)
    item_version: str = Field(default="")
    payload: dict = Field(default_factory=dict)


class ReleaseCreateRequest(BaseModel):
    kind: str = Field(...)
    name: str = Field(...)
    version: str = Field(...)
    created_by: str = Field(default="admin")
    items: list[ReleaseBundleItemRequest] = Field(default_factory=list)
    environment: Optional[str] = Field(default=None)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    notes: str = Field(default="")
    metadata: dict = Field(default_factory=dict)


class ReleaseActionRequest(BaseModel):
    actor: str = Field(default="admin")
    reason: str = Field(default="")
    to_environment: Optional[str] = Field(default=None)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)


class ReleaseCanaryRequest(BaseModel):
    actor: str = Field(default="admin")
    target_environment: str = Field(...)
    strategy: str = Field(default="percentage")
    traffic_percent: float = Field(default=0, ge=0, le=100)
    step_percent: float = Field(default=0, ge=0, le=100)
    bake_minutes: int = Field(default=0, ge=0)
    status: str = Field(default="draft")
    metric_guardrails: dict = Field(default_factory=dict)
    analysis_summary: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)


class ReleaseGateRunRequest(BaseModel):
    actor: str = Field(default="system")
    gate_name: str = Field(...)
    status: str = Field(...)
    score: Optional[float] = Field(default=None)
    threshold: Optional[float] = Field(default=None)
    details: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class ReleaseChangeReportRequest(BaseModel):
    actor: str = Field(default="system")
    risk_level: str = Field(default="unknown")
    summary: dict = Field(default_factory=dict)
    diff: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)



class VoiceSessionStartRequest(BaseModel):
    actor: str = Field(default="admin")
    user_key: str = Field(...)
    locale: str = Field(default="es-ES")
    stt_provider: str = Field(default="simulated-stt")
    tts_provider: str = Field(default="simulated-tts")
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class VoiceTranscriptRequest(BaseModel):
    actor: str = Field(default="admin")
    transcript_text: str = Field(...)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    language: str = Field(default="")
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class VoiceRespondRequest(BaseModel):
    actor: str = Field(default="admin")
    text: str = Field(default="")
    voice_name: str = Field(default="assistant")
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class VoiceConfirmRequest(BaseModel):
    actor: str = Field(default="admin")
    decision: str = Field(default="confirm")
    confirmation_text: str = Field(default="")
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class VoiceCloseRequest(BaseModel):
    actor: str = Field(default="admin")
    reason: str = Field(default="")
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)

class AppInstallationRequest(BaseModel):
    actor: str = Field(default="admin")
    user_key: str = Field(...)
    platform: str = Field(default="pwa")
    device_label: str = Field(default="")
    push_capable: bool = Field(default=False)
    notification_permission: str = Field(default="default")
    deep_link_base: str = Field(default="/ui/")
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class AppNotificationRequest(BaseModel):
    actor: str = Field(default="admin")
    title: str = Field(...)
    body: str = Field(default="")
    category: str = Field(default="operator")
    installation_id: Optional[str] = Field(default=None)
    target_path: str = Field(default="/ui/?tab=operator")
    require_interaction: bool = Field(default=False)
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class AppDeepLinkRequest(BaseModel):
    actor: str = Field(default="admin")
    view: str = Field(default="operator")
    target_type: str = Field(...)
    target_id: str = Field(...)
    params: dict = Field(default_factory=dict)
    expires_in_s: int = Field(default=3600, ge=60, le=60 * 24 * 7)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class PackageBuildRequest(BaseModel):
    actor: str = Field(default="admin")
    target: str = Field(default="desktop")
    label: str = Field(...)
    version: str = Field(default="phase8-pr8")
    artifact_path: str = Field(default="")
    status: str = Field(default="ready")
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)



class VoiceAudioTranscribeRequest(BaseModel):
    actor: str = Field(default="admin")
    audio_b64: str = Field(...)
    mime_type: str = Field(default="audio/wav")
    sample_rate_hz: int = Field(default=16000, ge=8000, le=96000)
    language: str = Field(default="")
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class ReleaseCanaryActivateRequest(BaseModel):
    actor: str = Field(default="admin")
    baseline_release_id: Optional[str] = Field(default=None)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)


class ReleaseCanaryRouteRequest(BaseModel):
    actor: str = Field(default="admin")
    routing_key: str = Field(...)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)


class ReleaseCanaryObservationRequest(BaseModel):
    actor: str = Field(default="admin")
    success: bool = Field(...)
    latency_ms: Optional[float] = Field(default=None, ge=0.0)
    cost_estimate: Optional[float] = Field(default=None, ge=0.0)
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)


class ReproducibleBuildRequest(BaseModel):
    actor: str = Field(default="admin")
    target: str = Field(default="desktop")
    label: str = Field(...)
    version: str = Field(default="phase9-operational-hardening")
    source_root: Optional[str] = Field(default=None)
    output_dir: Optional[str] = Field(default=None)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class VerifyManifestRequest(BaseModel):
    manifest_path: str = Field(...)


class CanvasCreateRequest(BaseModel):
    actor: str = Field(default="admin")
    title: str = Field(...)
    description: str = Field(default="")
    status: str = Field(default="active")
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class CanvasNodeRequest(BaseModel):
    actor: str = Field(default="admin")
    node_id: Optional[str] = Field(default=None)
    node_type: str = Field(default="note")
    label: str = Field(default="")
    position_x: float = Field(default=0.0)
    position_y: float = Field(default=0.0)
    width: float = Field(default=240.0)
    height: float = Field(default=120.0)
    data: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class CanvasEdgeRequest(BaseModel):
    actor: str = Field(default="admin")
    edge_id: Optional[str] = Field(default=None)
    source_node_id: str = Field(...)
    target_node_id: str = Field(...)
    label: str = Field(default="")
    edge_type: str = Field(default="default")
    data: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class CanvasViewRequest(BaseModel):
    actor: str = Field(default="admin")
    view_id: Optional[str] = Field(default=None)
    name: str = Field(default="Default")
    layout: dict = Field(default_factory=dict)
    filters: dict = Field(default_factory=dict)
    is_default: bool = Field(default=False)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class CanvasPresenceRequest(BaseModel):
    actor: str = Field(default="admin")
    user_key: str = Field(...)
    cursor_x: float = Field(default=0.0)
    cursor_y: float = Field(default=0.0)
    selected_node_id: Optional[str] = Field(default=None)
    status: str = Field(default="active")
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)



class CanvasOverlayStateRequest(BaseModel):
    actor: str = Field(default="admin")
    state_key: str = Field(default="default")
    toggles: dict = Field(default_factory=dict)
    inspector: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class CanvasCommentRequest(BaseModel):
    actor: str = Field(default="admin")
    body: str = Field(...)
    node_id: Optional[str] = Field(default=None)
    status: str = Field(default="active")
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class CanvasSnapshotRequest(BaseModel):
    actor: str = Field(default="admin")
    label: str = Field(default="")
    snapshot_kind: str = Field(default="manual")
    view_id: Optional[str] = Field(default=None)
    selected_node_id: Optional[str] = Field(default=None)
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class CanvasShareViewRequest(BaseModel):
    actor: str = Field(default="admin")
    view_id: Optional[str] = Field(default=None)
    label: str = Field(default="Shared view")
    selected_node_id: Optional[str] = Field(default=None)
    metadata: dict = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)


class CanvasNodeActionRequest(BaseModel):
    actor: str = Field(default="admin")
    reason: str = Field(default="")
    payload: dict = Field(default_factory=dict)
    session_id: str = Field(default="canvas")
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)

class SecretGovernanceExplainRequest(BaseModel):
    ref: str = Field(...)
    tool_name: str = Field(...)
    user_role: Optional[str] = Field(default=None)
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)
    environment: Optional[str] = Field(default=None)
    domain: Optional[str] = Field(default=None)


def _get_gw(request: Request) -> Gateway:
    gw: Gateway | None = getattr(request.app.state, "gw", None)
    if gw is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return gw


def _extract_admin_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.headers.get("X-Admin-Token", "").strip()


def _rate_limit_buckets(request: Request) -> dict[str, deque[float]]:
    buckets = getattr(request.app.state, "admin_rate_limit_buckets", None)
    if buckets is None:
        buckets = defaultdict(deque)
        request.app.state.admin_rate_limit_buckets = buckets
    return buckets


def _rate_limit_key(request: Request) -> str:
    token_prefix = _extract_admin_token(request)[:12] or "anonymous"
    client_ip = request.client.host if request.client else "unknown"
    app_id = hex(id(request.app))
    return f"{app_id}:{token_prefix}:{client_ip}"


def _rate_limit(request: Request, limit_per_minute: int) -> None:
    limit = int(limit_per_minute or 0)
    if limit <= 0:
        return
    now = time.time()
    window = now - 60.0
    key = _rate_limit_key(request)
    with _RATE_LIMIT_LOCK:
        q = _rate_limit_buckets(request)[key]
        while q and q[0] < window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
        q.append(now)


def _audit_admin(gw: Gateway, action: str, payload: dict) -> int | None:
    try:
        return gw.audit.log_event(
            direction="system",
            channel="admin",
            user_id="admin",
            session_id="admin",
            payload={"action": action, **payload},
        )
    except Exception:
        return None


def _require_admin(request: Request) -> Gateway:
    gw = _get_gw(request)
    admin_cfg = getattr(gw.settings, "admin", None)
    if not admin_cfg or not getattr(admin_cfg, "enabled", False):
        raise HTTPException(status_code=503, detail="Admin API not enabled")
    _rate_limit(request, int(getattr(admin_cfg, "rate_limit_per_minute", 60) or 60))
    configured_token = (getattr(admin_cfg, "token", "") or "").strip()
    if not configured_token:
        raise HTTPException(status_code=503, detail="Admin API token not configured")
    provided_token = _extract_admin_token(request)
    if not provided_token or not secrets.compare_digest(provided_token, configured_token):
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return gw


@router.get("/admin/openclaw/runtimes")
def admin_openclaw_runtimes(
    request: Request,
    limit: int = Query(default=100, ge=1, le=300),
    status: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_runtimes(gw, limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtimes', {'count': len(response.get('items', [])), 'status': status, 'tenant_id': tenant_id, 'workspace_id': workspace_id, 'environment': environment})
    return response


@router.post("/admin/openclaw/runtimes")
async def admin_openclaw_register_runtime(request: Request):
    gw = _require_admin(request)
    payload = await request.json()
    response = _ADMIN_SERVICE.register_openclaw_runtime(
        gw,
        actor=str(payload.get('actor') or 'admin'),
        name=str(payload.get('name') or ''),
        base_url=str(payload.get('base_url') or ''),
        transport=str(payload.get('transport') or 'http'),
        auth_secret_ref=str(payload.get('auth_secret_ref') or ''),
        capabilities=list(payload.get('capabilities') or []),
        allowed_agents=list(payload.get('allowed_agents') or []),
        metadata=dict(payload.get('metadata') or {}),
        runtime_id=payload.get('runtime_id'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    _audit_admin(gw, 'openclaw_runtime_register', {'runtime_id': response.get('runtime', {}).get('runtime_id'), 'tenant_id': payload.get('tenant_id'), 'workspace_id': payload.get('workspace_id'), 'environment': payload.get('environment')})
    return response


@router.get("/admin/openclaw/runtimes/{runtime_id}")
def admin_openclaw_runtime_detail(
    runtime_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_runtime(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtime_detail', {'runtime_id': runtime_id, 'ok': response.get('ok')})
    return response


@router.get("/admin/openclaw/dispatches")
def admin_openclaw_dispatches(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_dispatches(gw, runtime_id=runtime_id, action=action, status=status, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_dispatches', {'count': len(response.get('items', [])), 'runtime_id': runtime_id, 'status': status})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/dispatch")
async def admin_openclaw_dispatch(runtime_id: str, request: Request):
    gw = _require_admin(request)
    payload = await request.json()
    response = _ADMIN_SERVICE.dispatch_openclaw_runtime(
        gw,
        runtime_id=runtime_id,
        actor=str(payload.get('actor') or 'admin'),
        action=str(payload.get('action') or ''),
        payload=dict(payload.get('payload') or {}),
        agent_id=str(payload.get('agent_id') or ''),
        user_role=str(payload.get('user_role') or 'admin'),
        user_key=str(payload.get('user_key') or 'admin'),
        session_id=str(payload.get('session_id') or 'admin'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
        dry_run=bool(payload.get('dry_run', False)),
    )
    _audit_admin(gw, 'openclaw_dispatch', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'dispatch_id': response.get('dispatch', {}).get('dispatch_id')})
    return response


@router.get("/admin/status")
def admin_status(request: Request):
    gw = _require_admin(request)
    payload = _ADMIN_SERVICE.status_snapshot(gw)
    _audit_admin(gw, "status_read", {})
    return payload


@router.get("/admin/memory/search")
def admin_memory_search_get(
    request: Request,
    q: Optional[str] = Query(default=None),
    user_key: Optional[str] = Query(default=None),
    top_k: int = Query(default=5, ge=1, le=100),
):
    gw = _require_admin(request)
    payload = _ADMIN_SERVICE.search_memory_semantic_or_table(gw, q=q, user_key=user_key, top_k=top_k)
    _audit_admin(gw, f"memory_{payload['mode']}_search", {
        "q": q,
        "user_key": user_key,
        "top_k": top_k,
        "returned": len(payload.get("items", [])),
    })
    return payload


@router.post("/admin/memory/search")
def admin_memory_search_post(payload: AdminMemorySearchBody, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.search_memory(
        gw,
        user_key=payload.user_key,
        kind=payload.kind,
        text_contains=payload.text_contains,
        limit=payload.limit,
    )
    _audit_admin(gw, "memory_search", {
        "filters": response["filters"],
        "returned": response["returned"],
    })
    return response


@router.post("/admin/memory/delete")
def admin_memory_delete(payload: AdminMemoryDeleteRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.delete_memory(
        gw,
        user_key=payload.user_key,
        kind=payload.kind,
        dry_run=payload.dry_run,
    )
    if payload.dry_run:
        _audit_admin(gw, "memory_delete_dry_run", {
            "user_key": payload.user_key,
            "kind": payload.kind,
            "would_delete": response["would_delete"],
        })
    else:
        _audit_admin(gw, "memory_delete", {
            "user_key": payload.user_key,
            "kind": payload.kind,
            "deleted": response["deleted"],
        })
    return response


@router.delete("/admin/memory/{item_id}")
def admin_memory_delete_by_id(item_id: int, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.delete_memory_by_id(gw, item_id=item_id)
    _audit_admin(gw, "memory_delete_by_id", {"item_id": item_id, "deleted": response["deleted"]})
    return response


@router.get("/admin/sessions")
def admin_sessions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    channel: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_sessions(gw, limit=limit, channel=channel)
    _audit_admin(gw, "sessions_list", {"limit": limit, "channel": channel, "returned": len(response["items"])})
    return response


@router.get("/admin/events")
def admin_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    channel: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_events(gw, limit=limit, channel=channel)
    _audit_admin(gw, "events_list", {"limit": limit, "channel": channel, "returned": len(response["items"])})
    return response


@router.post("/admin/reload")
def admin_reload(request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.reload(gw)
    _audit_admin(gw, "reload", {k: v for k, v in response.items() if k != "ok"})
    return response


@router.get("/admin/identities")
def admin_identities(request: Request, global_user_key: Optional[str] = Query(default=None)):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_identities(gw, global_user_key=global_user_key)
    _audit_admin(gw, "identities_list", {"global_user_key": global_user_key, "returned": len(response["items"])})
    return response


@router.post("/admin/identities/link")
def admin_identities_link(payload: IdentityLinkRequest, request: Request):
    gw = _require_admin(request)
    channel_user_key = payload.channel_user_key or payload.channel_key
    if not channel_user_key:
        raise HTTPException(status_code=422, detail="channel_user_key is required")
    response = _ADMIN_SERVICE.link_identity(
        gw,
        channel_user_key=channel_user_key,
        global_user_key=payload.global_user_key,
        linked_by=payload.linked_by,
    )
    _audit_admin(gw, "identity_link", response)
    return response




@router.get("/admin/releases")
def admin_releases(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    name: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    payload = _ADMIN_SERVICE.list_releases(
        gw,
        limit=limit,
        status=status,
        kind=kind,
        name=name,
        environment=environment,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    _audit_admin(gw, "releases_list", {"count": len(payload.get("items", [])), "status": status, "kind": kind, "environment": environment})
    return payload


@router.get("/admin/releases/{release_id}")
def admin_release_detail(
    release_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    payload = _ADMIN_SERVICE.get_release(gw, release_id=release_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, "release_detail", {"release_id": release_id, "ok": payload.get("ok")})
    return payload


@router.post("/admin/releases")
def admin_release_create(payload: ReleaseCreateRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.create_release(
            gw,
            kind=payload.kind,
            name=payload.name,
            version=payload.version,
            created_by=payload.created_by,
            items=[item.model_dump() for item in payload.items],
            environment=payload.environment,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            notes=payload.notes,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_create", {"release_id": response.get("release", {}).get("release_id"), "kind": payload.kind, "name": payload.name, "version": payload.version})
    return response


@router.post("/admin/releases/{release_id}/submit")
def admin_release_submit(release_id: str, payload: ReleaseActionRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.submit_release(gw, release_id=release_id, actor=payload.actor, reason=payload.reason, tenant_id=payload.tenant_id, workspace_id=payload.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_submit", {"release_id": release_id, "actor": payload.actor})
    return response


@router.post("/admin/releases/{release_id}/approve")
def admin_release_approve(release_id: str, payload: ReleaseActionRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.approve_release(gw, release_id=release_id, actor=payload.actor, reason=payload.reason, tenant_id=payload.tenant_id, workspace_id=payload.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_approve", {"release_id": release_id, "actor": payload.actor})
    return response


@router.post("/admin/releases/{release_id}/promote")
def admin_release_promote(release_id: str, payload: ReleaseActionRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.promote_release(
            gw,
            release_id=release_id,
            to_environment=str(payload.to_environment or "").strip(),
            actor=payload.actor,
            reason=payload.reason,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_promote", {"release_id": release_id, "actor": payload.actor, "to_environment": payload.to_environment})
    return response


@router.post("/admin/releases/{release_id}/canary")
def admin_release_canary(release_id: str, payload: ReleaseCanaryRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.configure_release_canary(
            gw,
            release_id=release_id,
            target_environment=payload.target_environment,
            actor=payload.actor,
            strategy=payload.strategy,
            traffic_percent=payload.traffic_percent,
            step_percent=payload.step_percent,
            bake_minutes=payload.bake_minutes,
            status=payload.status,
            metric_guardrails=payload.metric_guardrails,
            analysis_summary=payload.analysis_summary,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_canary", {"release_id": release_id, "actor": payload.actor, "target_environment": payload.target_environment})
    return response


@router.post("/admin/releases/{release_id}/gates")
def admin_release_gate_run(release_id: str, payload: ReleaseGateRunRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.record_release_gate_run(
            gw,
            release_id=release_id,
            gate_name=payload.gate_name,
            status=payload.status,
            actor=payload.actor,
            score=payload.score,
            threshold=payload.threshold,
            details=payload.details,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_gate_run", {"release_id": release_id, "gate_name": payload.gate_name, "status": payload.status})
    return response


@router.post("/admin/releases/{release_id}/change-report")
def admin_release_change_report(release_id: str, payload: ReleaseChangeReportRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.set_release_change_report(
            gw,
            release_id=release_id,
            risk_level=payload.risk_level,
            actor=payload.actor,
            summary=payload.summary,
            diff=payload.diff,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_change_report", {"release_id": release_id, "risk_level": payload.risk_level})
    return response


@router.post("/admin/releases/{release_id}/rollback")
def admin_release_rollback(release_id: str, payload: ReleaseActionRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.rollback_release(gw, release_id=release_id, actor=payload.actor, reason=payload.reason, tenant_id=payload.tenant_id, workspace_id=payload.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_rollback", {"release_id": release_id, "actor": payload.actor})
    return response




@router.get("/admin/voice/sessions")
def admin_voice_sessions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_voice_sessions(
        gw,
        limit=limit,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "voice_sessions_list", {"count": len(payload.get("items", [])), "status": status})
    return payload


@router.get("/admin/voice/sessions/{voice_session_id}")
def admin_voice_session_detail(
    voice_session_id: str,
    request: Request,
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.get_voice_session(
        gw,
        voice_session_id=voice_session_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "voice_session_detail", {"voice_session_id": voice_session_id, "ok": payload.get("ok")})
    return payload


@router.post("/admin/voice/sessions")
def admin_voice_session_start(payload: VoiceSessionStartRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.start_voice_session(
        gw,
        actor=payload.actor,
        user_key=payload.user_key,
        locale=payload.locale,
        stt_provider=payload.stt_provider,
        tts_provider=payload.tts_provider,
        metadata=payload.metadata,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "voice_session_start", {"voice_session_id": response.get("session", {}).get("voice_session_id"), "actor": payload.actor})
    return response


@router.post("/admin/voice/sessions/{voice_session_id}/transcribe")
def admin_voice_session_transcribe(voice_session_id: str, payload: VoiceTranscriptRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.transcribe_voice_turn(
            gw,
            voice_session_id=voice_session_id,
            actor=payload.actor,
            transcript_text=payload.transcript_text,
            confidence=payload.confidence,
            language=payload.language,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "voice_session_transcribe", {"voice_session_id": voice_session_id, "actor": payload.actor})
    return response


@router.post("/admin/voice/sessions/{voice_session_id}/respond")
def admin_voice_session_respond(voice_session_id: str, payload: VoiceRespondRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.respond_voice_turn(
            gw,
            voice_session_id=voice_session_id,
            actor=payload.actor,
            text=payload.text,
            voice_name=payload.voice_name,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
    _audit_admin(gw, "voice_session_respond", {"voice_session_id": voice_session_id, "actor": payload.actor})
    return response


@router.post("/admin/voice/sessions/{voice_session_id}/confirm")
def admin_voice_session_confirm(voice_session_id: str, payload: VoiceConfirmRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.confirm_voice_turn(
            gw,
            voice_session_id=voice_session_id,
            actor=payload.actor,
            decision=payload.decision,
            confirmation_text=payload.confirmation_text,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "voice_session_confirm", {"voice_session_id": voice_session_id, "actor": payload.actor, "decision": payload.decision})
    return response


@router.post("/admin/voice/sessions/{voice_session_id}/close")
def admin_voice_session_close(voice_session_id: str, payload: VoiceCloseRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.close_voice_session(
            gw,
            voice_session_id=voice_session_id,
            actor=payload.actor,
            reason=payload.reason,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
    _audit_admin(gw, "voice_session_close", {"voice_session_id": voice_session_id, "actor": payload.actor})
    return response


@router.get("/admin/app/installations")
def admin_app_installations(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_app_installations(
        gw,
        limit=limit,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "app_installations_list", {"count": len(payload.get("items", [])), "status": status})
    return payload


@router.post("/admin/app/installations")
def admin_app_installation_register(payload: AppInstallationRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.register_app_installation(
        gw,
        actor=payload.actor,
        user_key=payload.user_key,
        platform=payload.platform,
        device_label=payload.device_label,
        push_capable=payload.push_capable,
        notification_permission=payload.notification_permission,
        deep_link_base=payload.deep_link_base,
        metadata=payload.metadata,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "app_installation_register", {"installation_id": response.get("installation", {}).get("installation_id"), "actor": payload.actor})
    return response


@router.get("/admin/app/notifications")
def admin_app_notifications(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    installation_id: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_app_notifications(
        gw,
        limit=limit,
        installation_id=installation_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "app_notifications_list", {"count": len(payload.get("items", [])), "installation_id": installation_id})
    return payload


@router.post("/admin/app/notifications")
def admin_app_notification_create(payload: AppNotificationRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.create_app_notification(
        gw,
        actor=payload.actor,
        title=payload.title,
        body=payload.body,
        category=payload.category,
        installation_id=payload.installation_id,
        target_path=payload.target_path,
        require_interaction=payload.require_interaction,
        metadata=payload.metadata,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "app_notification_create", {"notification_id": response.get("notification", {}).get("notification_id"), "actor": payload.actor})
    return response


@router.get("/admin/app/deep-links")
def admin_app_deep_links(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_app_deep_links(
        gw,
        limit=limit,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "app_deep_links_list", {"count": len(payload.get("items", [])), "status": status})
    return payload


@router.post("/admin/app/deep-links")
def admin_app_deep_link_create(payload: AppDeepLinkRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.create_app_deep_link(
        gw,
        actor=payload.actor,
        view=payload.view,
        target_type=payload.target_type,
        target_id=payload.target_id,
        params=payload.params,
        expires_in_s=payload.expires_in_s,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "app_deep_link_create", {"link_token": response.get("deep_link", {}).get("link_token"), "actor": payload.actor})
    return response


@router.get("/app/deep-links/{link_token}")
def app_deep_link_redirect(link_token: str, request: Request):
    gw = _get_gw(request)
    response = _ADMIN_SERVICE.resolve_app_deep_link(gw, link_token=link_token)
    if not response.get("ok"):
        raise HTTPException(status_code=404 if response.get("reason") == "not_found" else 410, detail=response.get("reason") or "deep_link_unavailable")
    return RedirectResponse(url=response["ui_path"], status_code=307)


@router.get("/admin/phase8/packaging/summary")
def admin_phase8_packaging_summary(request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = {
        'ok': True,
        'packaging': _ADMIN_SERVICE.phase8_packaging_summary(gw),
        'hardening': _ADMIN_SERVICE.phase8_hardening_summary(gw),
    }
    _audit_admin(gw, "phase8_packaging_summary", {"ok": True})
    return response


@router.get("/admin/phase8/packaging/builds")
def admin_phase8_package_builds(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    target: str | None = Query(default=None),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.list_package_builds(
        gw,
        limit=limit,
        target=target,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "phase8_package_builds", {"count": len(response.get("items", [])), "target": target, "status": status})
    return response


@router.post("/admin/phase8/packaging/builds")
def admin_phase8_package_build_create(payload: PackageBuildRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.create_package_build(
        gw,
        actor=payload.actor,
        target=payload.target,
        label=payload.label,
        version=payload.version,
        artifact_path=payload.artifact_path,
        status=payload.status,
        metadata=payload.metadata,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "phase8_package_build_create", {"build_id": response.get("build", {}).get("build_id"), "target": payload.target, "actor": payload.actor})
    return response



@router.get("/admin/canvas/documents")
def admin_canvas_documents(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_canvas_documents(
        gw,
        limit=limit,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_documents_list", {"count": len(payload.get("items", [])), "status": status})
    return payload


@router.post("/admin/canvas/documents")
def admin_canvas_document_create(payload: CanvasCreateRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.create_canvas_document(
        gw,
        actor=payload.actor,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        metadata=payload.metadata,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "canvas_document_create", {"canvas_id": response.get("document", {}).get("canvas_id"), "actor": payload.actor})
    return response


@router.get("/admin/canvas/documents/{canvas_id}")
def admin_canvas_document_detail(
    canvas_id: str,
    request: Request,
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.get_canvas_document(
        gw,
        canvas_id=canvas_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_document_detail", {"canvas_id": canvas_id, "ok": payload.get("ok")})
    return payload


@router.post("/admin/canvas/documents/{canvas_id}/nodes")
def admin_canvas_node_upsert(canvas_id: str, payload: CanvasNodeRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.upsert_canvas_node(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            node_id=payload.node_id,
            node_type=payload.node_type,
            label=payload.label,
            position_x=payload.position_x,
            position_y=payload.position_y,
            width=payload.width,
            height=payload.height,
            data=payload.data,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_node_upsert", {"canvas_id": canvas_id, "node_id": response.get("node", {}).get("node_id")})
    return response


@router.post("/admin/canvas/documents/{canvas_id}/edges")
def admin_canvas_edge_upsert(canvas_id: str, payload: CanvasEdgeRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.upsert_canvas_edge(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            edge_id=payload.edge_id,
            source_node_id=payload.source_node_id,
            target_node_id=payload.target_node_id,
            label=payload.label,
            edge_type=payload.edge_type,
            data=payload.data,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_edge_upsert", {"canvas_id": canvas_id, "edge_id": response.get("edge", {}).get("edge_id")})
    return response


@router.post("/admin/canvas/documents/{canvas_id}/views")
def admin_canvas_view_save(canvas_id: str, payload: CanvasViewRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.save_canvas_view(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            view_id=payload.view_id,
            name=payload.name,
            layout=payload.layout,
            filters=payload.filters,
            is_default=payload.is_default,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_view_save", {"canvas_id": canvas_id, "view_id": response.get("view", {}).get("view_id")})
    return response


@router.post("/admin/canvas/documents/{canvas_id}/presence")
def admin_canvas_presence_update(canvas_id: str, payload: CanvasPresenceRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.update_canvas_presence(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            user_key=payload.user_key,
            cursor_x=payload.cursor_x,
            cursor_y=payload.cursor_y,
            selected_node_id=payload.selected_node_id,
            status=payload.status,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    _audit_admin(gw, "canvas_presence_update", {"canvas_id": canvas_id, "user_key": payload.user_key})
    return response


@router.get("/admin/canvas/documents/{canvas_id}/comments")
def admin_canvas_comments(
    canvas_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    payload = _ADMIN_SERVICE.list_canvas_comments(
        gw,
        canvas_id=canvas_id,
        limit=limit,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_comments", {"canvas_id": canvas_id, "count": len(payload.get("items", []))})
    return payload


@router.post("/admin/canvas/documents/{canvas_id}/comments")
def admin_canvas_comment_create(canvas_id: str, payload: CanvasCommentRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.add_canvas_comment(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            body=payload.body,
            node_id=payload.node_id,
            status=payload.status,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_comment_create", {"canvas_id": canvas_id, "comment_id": response.get("comment", {}).get("comment_id")})
    return response


@router.get("/admin/canvas/documents/{canvas_id}/snapshots")
def admin_canvas_snapshots(
    canvas_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    snapshot_kind: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    payload = _ADMIN_SERVICE.list_canvas_snapshots(
        gw,
        canvas_id=canvas_id,
        limit=limit,
        snapshot_kind=snapshot_kind,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_snapshots", {"canvas_id": canvas_id, "count": len(payload.get("items", []))})
    return payload


@router.post("/admin/canvas/documents/{canvas_id}/snapshots")
def admin_canvas_snapshot_create(canvas_id: str, payload: CanvasSnapshotRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.create_canvas_snapshot(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            label=payload.label,
            snapshot_kind=payload.snapshot_kind,
            view_id=payload.view_id,
            selected_node_id=payload.selected_node_id,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_snapshot_create", {"canvas_id": canvas_id, "snapshot_id": response.get("snapshot", {}).get("snapshot_id")})
    return response


@router.post("/admin/canvas/documents/{canvas_id}/share-view")
def admin_canvas_share_view(canvas_id: str, payload: CanvasShareViewRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.share_canvas_view(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            view_id=payload.view_id,
            label=payload.label,
            selected_node_id=payload.selected_node_id,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    _audit_admin(gw, "canvas_share_view", {"canvas_id": canvas_id, "share_token": response.get("share_token")})
    return response


@router.get("/admin/canvas/snapshots/compare")
def admin_canvas_snapshots_compare(
    request: Request,
    snapshot_a_id: str = Query(...),
    snapshot_b_id: str = Query(...),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    payload = _ADMIN_SERVICE.compare_canvas_snapshots(
        gw,
        snapshot_a_id=snapshot_a_id,
        snapshot_b_id=snapshot_b_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_snapshots_compare", {"snapshot_a_id": snapshot_a_id, "snapshot_b_id": snapshot_b_id, "ok": payload.get("ok")})
    return payload


@router.get("/admin/canvas/documents/{canvas_id}/presence-events")
def admin_canvas_presence_events(
    canvas_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    payload = _ADMIN_SERVICE.list_canvas_presence_events(
        gw,
        canvas_id=canvas_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_presence_events", {"canvas_id": canvas_id, "count": len(payload.get("items", []))})
    return payload


@router.post("/admin/canvas/documents/{canvas_id}/overlay-state")
def admin_canvas_overlay_state_save(canvas_id: str, payload: CanvasOverlayStateRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.save_canvas_overlay_state(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            state_key=payload.state_key,
            toggles=payload.toggles,
            inspector=payload.inspector,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    _audit_admin(gw, "canvas_overlay_state_save", {"canvas_id": canvas_id, "state_key": payload.state_key})
    return response


@router.get("/admin/canvas/documents/{canvas_id}/overlays")
def admin_canvas_overlays(
    canvas_id: str,
    request: Request,
    selected_node_id: str | None = Query(default=None),
    state_key: str = Query(default='default'),
    limit: int = Query(default=50, ge=1, le=200),
    overlay_policy: bool = Query(default=True),
    overlay_cost: bool = Query(default=True),
    overlay_traces: bool = Query(default=True),
    overlay_failures: bool = Query(default=True),
    overlay_approvals: bool = Query(default=True),
    overlay_secrets: bool = Query(default=True),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.get_canvas_operational_overlays(
        gw,
        canvas_id=canvas_id,
        selected_node_id=selected_node_id,
        state_key=state_key,
        limit=limit,
        toggles={
            'policy': overlay_policy,
            'cost': overlay_cost,
            'traces': overlay_traces,
            'failures': overlay_failures,
            'approvals': overlay_approvals,
            'secrets': overlay_secrets,
        },
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_overlays", {"canvas_id": canvas_id, "selected_node_id": selected_node_id, "state_key": state_key})
    return payload


@router.get("/admin/canvas/documents/{canvas_id}/views/operational")
def admin_canvas_operational_views(
    canvas_id: str,
    request: Request,
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_canvas_operational_views(
        gw,
        canvas_id=canvas_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_operational_views", {"canvas_id": canvas_id, "ok": payload.get("ok")})
    return payload


@router.get("/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector")
def admin_canvas_node_inspector(
    canvas_id: str,
    node_id: str,
    request: Request,
    state_key: str = Query(default='default'),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.inspect_canvas_node(
        gw,
        canvas_id=canvas_id,
        node_id=node_id,
        state_key=state_key,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_node_inspector", {"canvas_id": canvas_id, "node_id": node_id, "ok": payload.get("ok")})
    return payload


@router.get("/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline")
def admin_canvas_node_timeline(
    canvas_id: str,
    node_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.canvas_node_timeline(
        gw,
        canvas_id=canvas_id,
        node_id=node_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_node_timeline", {"canvas_id": canvas_id, "node_id": node_id, "ok": payload.get("ok")})
    return payload


@router.post("/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/{action}")
def admin_canvas_node_action(
    canvas_id: str,
    node_id: str,
    action: str,
    payload: CanvasNodeActionRequest,
    request: Request,
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.execute_canvas_node_action(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            action=action,
            actor=payload.actor,
            reason=payload.reason,
            payload=payload.payload,
            user_role='admin',
            user_key=str(payload.actor or 'admin'),
            session_id=payload.session_id or f'canvas:{canvas_id}',
            tenant_id=tenant_id or payload.tenant_id,
            workspace_id=workspace_id or payload.workspace_id,
            environment=environment or payload.environment,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        status_code = 409 if 'claimed' in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_node_action", {"canvas_id": canvas_id, "node_id": node_id, "action": action, "actor": payload.actor})
    return response


@router.get("/admin/canvas/documents/{canvas_id}/events")
def admin_canvas_events(
    canvas_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_canvas_events(
        gw,
        canvas_id=canvas_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_events", {"canvas_id": canvas_id, "count": len(payload.get("items", []))})
    return payload

@router.get("/admin/evals/suites")
def admin_evaluation_suites(request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_evaluation_suites(gw)
    _audit_admin(gw, "evaluation_suites_list", {"count": len(response.get("suites", []))})
    return response


@router.post("/admin/evals/run")
def admin_evaluation_run(payload: EvaluationRunRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.run_evaluation_suite(
        gw,
        suite_name=payload.suite_name,
        observations=[item.model_dump() for item in payload.observations],
        requested_by=payload.requested_by,
        provider=payload.provider,
        model=payload.model,
        agent_name=payload.agent_name,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "evaluation_run", {
        "suite_name": payload.suite_name,
        "requested_by": payload.requested_by,
        "status": response.get("status"),
        "run_id": response.get("run_id"),
    })
    return response


@router.get("/admin/evals/runs")
def admin_evaluation_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
    suite_name: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_evaluation_runs(
        gw,
        limit=limit,
        suite_name=suite_name,
        status=status,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "evaluation_runs_list", {"limit": limit, "suite_name": suite_name, "status": status, "agent_name": agent_name, "provider": provider, "model": model, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/evals/runs/{run_id}")
def admin_evaluation_run_detail(run_id: str, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_evaluation_run(gw, run_id=run_id)
    _audit_admin(gw, "evaluation_run_detail", {"run_id": run_id, "ok": response.get("ok")})
    return response


@router.get("/admin/evals/runs/{run_id}/compare")
def admin_evaluation_run_compare(run_id: str, request: Request, baseline_run_id: Optional[str] = Query(default=None)):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.compare_evaluation_run(gw, run_id=run_id, baseline_run_id=baseline_run_id)
    _audit_admin(gw, "evaluation_run_compare", {"run_id": run_id, "baseline_run_id": baseline_run_id, "ok": response.get("ok")})
    return response


@router.get("/admin/evals/regressions")
def admin_evaluation_regressions(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
    suite_name: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_evaluation_regressions(
        gw,
        limit=limit,
        suite_name=suite_name,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "evaluation_regressions_list", {"limit": limit, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/evals/scorecards")
def admin_evaluation_scorecards(
    request: Request,
    group_by: str = Query(default="agent_provider_model"),
    limit: int = Query(default=20, ge=1, le=200),
    suite_name: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.evaluation_scorecards(
        gw,
        group_by=group_by,
        limit=limit,
        suite_name=suite_name,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "evaluation_scorecards", {"group_by": group_by, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/evals/leaderboard")
def admin_evaluation_leaderboard(
    request: Request,
    group_by: str = Query(default="agent_provider_model"),
    rank_by: str = Query(default="stability_score"),
    limit: int = Query(default=20, ge=1, le=200),
    use_case: Optional[str] = Query(default=None),
    suite_name: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.evaluation_leaderboard(
        gw,
        group_by=group_by,
        rank_by=rank_by,
        limit=limit,
        use_case=use_case,
        suite_name=suite_name,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "evaluation_leaderboard", {"group_by": group_by, "rank_by": rank_by, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/evals/comparison")
def admin_evaluation_comparison(
    request: Request,
    split_by: str = Query(default="use_case"),
    compare_by: str = Query(default="agent_provider_model"),
    rank_by: str = Query(default="stability_score"),
    limit_groups: int = Query(default=20, ge=1, le=200),
    limit_per_group: int = Query(default=5, ge=1, le=50),
    suite_name: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.evaluation_comparison(
        gw,
        split_by=split_by,
        compare_by=compare_by,
        rank_by=rank_by,
        limit_groups=limit_groups,
        limit_per_group=limit_per_group,
        suite_name=suite_name,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "evaluation_comparison", {"split_by": split_by, "compare_by": compare_by, "rank_by": rank_by, "returned": len(response.get("groups", []))})
    return response

@router.get("/admin/costs/summary")
def admin_cost_summary(
    request: Request,
    group_by: str = Query(default="tenant"),
    limit: int = Query(default=20, ge=1, le=200),
    window_hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    workflow_name: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.cost_summary(
        gw,
        group_by=group_by,
        limit=limit,
        window_hours=window_hours,
        workflow_name=workflow_name,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "cost_summary", {"group_by": group_by, "window_hours": window_hours, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/costs/budgets")
def admin_cost_budgets(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.cost_budgets(
        gw,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "cost_budgets", {"returned": len(response.get("items", []))})
    return response


@router.get("/admin/costs/alerts")
def admin_cost_alerts(
    request: Request,
    severity: str = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.cost_alerts(
        gw,
        severity=severity,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "cost_alerts", {"severity": severity, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/traces")
def admin_decision_traces(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    session_id: Optional[str] = Query(default=None),
    user_key: Optional[str] = Query(default=None),
    agent_id: Optional[str] = Query(default=None),
    channel: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_decision_traces(
        gw,
        limit=limit,
        session_id=session_id,
        user_key=user_key,
        agent_id=agent_id,
        channel=channel,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "decision_traces", {"limit": limit, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/traces/{trace_id}")
def admin_decision_trace_detail(trace_id: str, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_decision_trace(gw, trace_id=trace_id)
    _audit_admin(gw, "decision_trace_detail", {"trace_id": trace_id, "ok": response.get("ok")})
    return response


@router.get("/admin/inspector/sessions/{session_id}")
def admin_session_inspector(session_id: str, request: Request, limit: int = Query(default=20, ge=1, le=200)):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.session_inspector(gw, session_id=session_id, limit=limit)
    _audit_admin(gw, "session_inspector", {"session_id": session_id, "trace_count": len(response.get("traces", []))})
    return response


@router.post("/admin/policies/explain")
def admin_policy_explain(payload: PolicyExplainRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.explain_policy(
        gw,
        scope=payload.scope,
        resource_name=payload.resource_name,
        action=payload.action,
        agent_name=payload.agent_name,
        user_role=payload.user_role,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
        channel=payload.channel,
        domain=payload.domain,
        extra=payload.extra,
        tool_name=payload.tool_name,
    )
    _audit_admin(gw, "policy_explain", {
        "scope": payload.scope,
        "resource_name": payload.resource_name,
        "requested_action": payload.action,
        "agent_name": payload.agent_name,
        "tool_name": payload.tool_name,
        "user_role": payload.user_role,
    })
    return response


@router.get("/admin/replay/sessions/{session_id}")
def admin_session_replay(
    session_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.session_replay(gw, session_id=session_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, "session_replay", {"session_id": session_id, "timeline_count": len(response.get("timeline", []))})
    return response


@router.get("/admin/replay/workflows/{workflow_id}")
def admin_workflow_replay(
    workflow_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.workflow_replay(gw, workflow_id=workflow_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, "workflow_replay", {"workflow_id": workflow_id, "timeline_count": len(response.get("timeline", []))})
    return response


@router.post("/admin/replay/compare")
def admin_replay_compare(payload: ReplayCompareRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.replay_compare(
        gw,
        left_kind=payload.left_kind,
        left_id=payload.left_id,
        right_kind=payload.right_kind,
        right_id=payload.right_id,
        limit=payload.limit,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "replay_compare", {"left_kind": payload.left_kind, "right_kind": payload.right_kind, "changed": response.get("changed")})
    return response


@router.get("/admin/operator/overview")
def admin_operator_overview(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    only_failures: bool = Query(default=False),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.operator_console_overview(
        gw,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        q=q,
        status=status,
        kind=kind,
        only_failures=only_failures,
    )
    _audit_admin(gw, "operator_console_overview", {"ok": response.get("ok"), "limit": limit, "kind": kind, "status": status, "only_failures": only_failures})
    return response


@router.get("/admin/operator/sessions/{session_id}")
def admin_operator_session(
    session_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    only_failures: bool = Query(default=False),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.operator_console_session(
        gw,
        session_id=session_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        q=q,
        status=status,
        kind=kind,
        only_failures=only_failures,
    )
    _audit_admin(gw, "operator_console_session", {"session_id": session_id, "timeline_count": len(response.get("timeline", [])), "kind": kind, "status": status})
    return response


@router.get("/admin/operator/workflows/{workflow_id}")
def admin_operator_workflow(
    workflow_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    only_failures: bool = Query(default=False),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.operator_console_workflow(
        gw,
        workflow_id=workflow_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        q=q,
        status=status,
        kind=kind,
        only_failures=only_failures,
    )
    _audit_admin(gw, "operator_console_workflow", {"workflow_id": workflow_id, "timeline_count": len(response.get("timeline", [])), "kind": kind, "status": status})
    return response


@router.post("/admin/operator/workflows/{workflow_id}/actions/{action}")
def admin_operator_workflow_action(
    workflow_id: str,
    action: str,
    payload: OperatorActionRequest,
    request: Request,
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _require_admin(request)
    actor = str(payload.actor or 'admin')
    try:
        response = _ADMIN_SERVICE.operator_console_workflow_action(
            gw,
            workflow_id=workflow_id,
            action=action,
            actor=actor,
            reason=payload.reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, 'operator_console_workflow_action', {'workflow_id': workflow_id, 'action': action, 'actor': actor})
    return response


@router.post("/admin/operator/approvals/{approval_id}/actions/{action}")
def admin_operator_approval_action(
    approval_id: str,
    action: str,
    payload: OperatorActionRequest,
    request: Request,
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _require_admin(request)
    actor = str(payload.actor or 'admin')
    try:
        response = _ADMIN_SERVICE.operator_console_approval_action(
            gw,
            approval_id=approval_id,
            action=action,
            actor=actor,
            reason=payload.reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        status_code = 409 if 'claimed' in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    _audit_admin(gw, 'operator_console_approval_action', {'approval_id': approval_id, 'action': action, 'actor': actor})
    return response


@router.get("/admin/secrets/summary")
def admin_secret_governance_summary(
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.secret_governance_summary(
        gw,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        limit=limit,
    )
    _audit_admin(gw, "secret_governance_summary", {"total_events": (response.get("summary") or {}).get("total_events", 0), "denied_events": (response.get("summary") or {}).get("denied_events", 0)})
    return response


@router.get("/admin/secrets/timeline")
def admin_secret_governance_timeline(
    request: Request,
    q: Optional[str] = Query(default=None),
    ref: Optional[str] = Query(default=None),
    tool_name: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.secret_governance_timeline(
        gw,
        q=q,
        ref=ref,
        tool_name=tool_name,
        outcome=outcome,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        limit=limit,
    )
    _audit_admin(gw, "secret_governance_timeline", {"ref": ref, "tool_name": tool_name, "outcome": outcome, "items": len(response.get("items") or [])})
    return response


@router.get("/admin/secrets/catalog")
def admin_secret_governance_catalog(
    request: Request,
    q: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.secret_governance_catalog(
        gw,
        q=q,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        limit=limit,
    )
    _audit_admin(gw, "secret_governance_catalog", {"q": q, "limit": limit, "visible_refs": len(response.get("items") or [])})
    return response


@router.get("/admin/secrets/usage")
def admin_secret_governance_usage(
    request: Request,
    q: Optional[str] = Query(default=None),
    ref: Optional[str] = Query(default=None),
    tool_name: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.secret_governance_usage(
        gw,
        q=q,
        ref=ref,
        tool_name=tool_name,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        limit=limit,
    )
    _audit_admin(gw, "secret_governance_usage", {"ref": ref, "tool_name": tool_name, "groups": len(response.get("items") or [])})
    return response


@router.post("/admin/secrets/explain")
def admin_secret_governance_explain(payload: SecretGovernanceExplainRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.secret_governance_explain(
        gw,
        ref=payload.ref,
        tool_name=payload.tool_name,
        user_role=payload.user_role or 'user',
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
        domain=payload.domain,
    )
    _audit_admin(gw, "secret_governance_explain", {"ref": payload.ref, "tool_name": payload.tool_name, "allowed": response.get("allowed")})
    return response


@router.get("/admin/policy-explorer/snapshot")
def admin_policy_explorer_snapshot(request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.policy_explorer_snapshot(gw)
    _audit_admin(gw, "policy_explorer_snapshot", {"ok": response.get("ok")})
    return response


@router.post("/admin/policy-explorer/simulate")
def admin_policy_explorer_simulate(payload: PolicyExplorerSimulateRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.policy_explorer_simulate(
        gw,
        scope=payload.request.scope,
        resource_name=payload.request.resource_name,
        action=payload.request.action,
        agent_name=payload.request.agent_name,
        tool_name=payload.request.tool_name,
        user_role=payload.request.user_role,
        tenant_id=payload.request.tenant_id,
        workspace_id=payload.request.workspace_id,
        environment=payload.request.environment,
        channel=payload.request.channel,
        domain=payload.request.domain,
        extra=payload.request.extra,
        candidate_policy=payload.candidate_policy or None,
        candidate_policy_yaml=payload.candidate_policy_yaml,
    )
    _audit_admin(gw, "policy_explorer_simulate", {"scope": payload.request.scope, "resource_name": payload.request.resource_name, "changed": response.get("changed")})
    return response


@router.post("/admin/policy-explorer/diff")
def admin_policy_explorer_diff(payload: PolicyExplorerDiffRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.policy_explorer_diff(
        gw,
        candidate_policy=payload.candidate_policy or None,
        candidate_policy_yaml=payload.candidate_policy_yaml,
        baseline_policy=payload.baseline_policy or None,
        baseline_policy_yaml=payload.baseline_policy_yaml,
        samples=list(payload.samples or []),
    )
    _audit_admin(gw, "policy_explorer_diff", {"ok": response.get("ok"), "sample_count": len(response.get("sample_results") or [])})
    return response


@router.post("/admin/sandbox/explain")
def admin_sandbox_explain(payload: SandboxExplainRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.explain_sandbox(
        gw,
        user_role=payload.user_role,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
        channel=payload.channel,
        agent_name=payload.agent_name,
        tool_name=payload.tool_name,
    )
    _audit_admin(gw, "sandbox_explain", {
        "user_role": payload.user_role,
        "tenant_id": payload.tenant_id,
        "workspace_id": payload.workspace_id,
        "environment": payload.environment,
        "channel": payload.channel,
        "agent_name": payload.agent_name,
        "tool_name": payload.tool_name,
    })
    return response


@router.post("/admin/security/explain")
def admin_security_explain(payload: SecurityExplainRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.explain_security(
        gw,
        scope=payload.scope,
        resource_name=payload.resource_name,
        action=payload.action,
        agent_name=payload.agent_name,
        user_role=payload.user_role,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
        channel=payload.channel,
        domain=payload.domain,
        extra=payload.extra,
        tool_name=payload.tool_name,
    )
    audit_event_id = _audit_admin(gw, "security_explain", {
        "scope": payload.scope,
        "resource_name": payload.resource_name,
        "requested_action": payload.action,
        "agent_name": payload.agent_name,
        "tool_name": payload.tool_name,
        "user_role": payload.user_role,
        "tenant_id": payload.tenant_id,
        "workspace_id": payload.workspace_id,
        "environment": payload.environment,
        "channel": payload.channel,
    })
    if audit_event_id is not None and isinstance(response, dict):
        response["audit_event_id"] = audit_event_id
    return response


@router.get("/admin/compliance/summary")
def admin_compliance_summary(
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    window_hours: int = Query(default=72, ge=1, le=24 * 30),
    limit_per_section: int = Query(default=20, ge=1, le=200),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.compliance_summary(
        gw,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        window_hours=window_hours,
        limit_per_section=limit_per_section,
    )
    audit_event_id = _audit_admin(gw, "compliance_summary", {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "environment": environment,
        "window_hours": window_hours,
        "limit_per_section": limit_per_section,
    })
    response["audit_event_id"] = audit_event_id
    return response


@router.post("/admin/compliance/export")
def admin_compliance_export(payload: ComplianceExportRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.export_compliance_report(
        gw,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
        window_hours=payload.window_hours,
        limit_per_section=payload.limit_per_section,
        sections=payload.sections,
        report_label=payload.report_label,
    )
    audit_event_id = _audit_admin(gw, "compliance_export", {
        "tenant_id": payload.tenant_id,
        "workspace_id": payload.workspace_id,
        "environment": payload.environment,
        "window_hours": payload.window_hours,
        "limit_per_section": payload.limit_per_section,
        "sections": payload.sections,
        "report_label": payload.report_label,
    })
    response["audit_event_id"] = audit_event_id
    return response


@router.post("/admin/voice/sessions/{voice_session_id}/audio/transcribe")
def admin_voice_session_audio_transcribe(voice_session_id: str, payload: VoiceAudioTranscribeRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.transcribe_voice_audio(
            gw,
            voice_session_id=voice_session_id,
            actor=payload.actor,
            audio_b64=payload.audio_b64,
            mime_type=payload.mime_type,
            sample_rate_hz=payload.sample_rate_hz,
            language=payload.language,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
    audit_event_id = _audit_admin(gw, "voice_session_audio_transcribe", {"voice_session_id": voice_session_id, "actor": payload.actor, "mime_type": payload.mime_type})
    if isinstance(response, dict):
        response["audit_event_id"] = audit_event_id
    return response


@router.post("/admin/releases/{release_id}/canary/activate")
def admin_release_canary_activate(release_id: str, payload: ReleaseCanaryActivateRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.activate_release_canary(
            gw,
            release_id=release_id,
            actor=payload.actor,
            baseline_release_id=payload.baseline_release_id,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_event_id = _audit_admin(gw, "release_canary_activate", {"release_id": release_id, "actor": payload.actor})
    response["audit_event_id"] = audit_event_id
    return response


@router.post("/admin/releases/{release_id}/canary/route")
def admin_release_canary_route(release_id: str, payload: ReleaseCanaryRouteRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.resolve_release_canary_route(
            gw,
            release_id=release_id,
            routing_key=payload.routing_key,
            actor=payload.actor,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_event_id = _audit_admin(gw, "release_canary_route", {"release_id": release_id, "actor": payload.actor})
    response["audit_event_id"] = audit_event_id
    return response


@router.post("/admin/releases/canary/decisions/{decision_id}/observe")
def admin_release_canary_observe(decision_id: str, payload: ReleaseCanaryObservationRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.record_release_canary_observation(
            gw,
            decision_id=decision_id,
            actor=payload.actor,
            success=payload.success,
            latency_ms=payload.latency_ms,
            cost_estimate=payload.cost_estimate,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="routing_decision_not_found") from exc
    audit_event_id = _audit_admin(gw, "release_canary_observe", {"decision_id": decision_id, "actor": payload.actor, "success": payload.success})
    response["audit_event_id"] = audit_event_id
    return response


@router.get("/admin/releases/{release_id}/canary/routing-summary")
def admin_release_canary_routing_summary(release_id: str, request: Request, tenant_id: Optional[str] = Query(default=None), workspace_id: Optional[str] = Query(default=None), target_environment: Optional[str] = Query(default=None)):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.release_canary_routing_summary(
            gw,
            release_id=release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            target_environment=target_environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    audit_event_id = _audit_admin(gw, "release_canary_routing_summary", {"release_id": release_id})
    response["audit_event_id"] = audit_event_id
    return response


@router.post("/admin/phase9/packaging/reproducible-build")
def admin_phase9_reproducible_build(payload: ReproducibleBuildRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.create_reproducible_package_build(
        gw,
        actor=payload.actor,
        target=payload.target,
        label=payload.label,
        version=payload.version,
        source_root=payload.source_root,
        output_dir=payload.output_dir,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    audit_event_id = _audit_admin(gw, "phase9_reproducible_build", {"target": payload.target, "actor": payload.actor})
    response["audit_event_id"] = audit_event_id
    return response


@router.post("/admin/phase9/packaging/verify-manifest")
def admin_phase9_verify_manifest(payload: VerifyManifestRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.verify_reproducible_package_manifest(manifest_path=payload.manifest_path)
    audit_event_id = _audit_admin(gw, "phase9_verify_manifest", {"manifest_path": payload.manifest_path, "ok": response.get("ok")})
    response["audit_event_id"] = audit_event_id
    return response
