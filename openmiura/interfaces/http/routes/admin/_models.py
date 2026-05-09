"""admin/_models.py — Pydantic request/response models for the admin sub-routers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

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


class ConfigCenterValidateRequest(BaseModel):
    section: str = Field(...)
    content: str = Field(default='')
    form_payload: dict[str, Any] | None = Field(default=None)


class ConfigCenterSaveRequest(BaseModel):
    section: str = Field(...)
    content: str = Field(default='')
    form_payload: dict[str, Any] | None = Field(default=None)
    reload_after_save: bool = Field(default=False)
    actor: str = Field(default='admin')


class ChannelWizardValidateRequest(BaseModel):
    channel: str = Field(...)
    content: str = Field(default='')
    wizard_payload: dict[str, Any] | None = Field(default=None)


class ChannelWizardSaveRequest(BaseModel):
    channel: str = Field(...)
    content: str = Field(default='')
    wizard_payload: dict[str, Any] | None = Field(default=None)
    reload_after_save: bool = Field(default=False)
    actor: str = Field(default='admin')


class SecretEnvWizardValidateRequest(BaseModel):
    profile: str = Field(...)
    content: str = Field(default='')
    wizard_payload: dict[str, Any] | None = Field(default=None)
    env_prefix: str = Field(default='OPENMIURA')


class SecretEnvWizardSaveRequest(BaseModel):
    profile: str = Field(...)
    content: str = Field(default='')
    wizard_payload: dict[str, Any] | None = Field(default=None)
    env_prefix: str = Field(default='OPENMIURA')
    reload_after_save: bool = Field(default=False)
    actor: str = Field(default='admin')


class ReloadAssistantApplyRequest(BaseModel):
    sections: list[str] = Field(default_factory=list)
    apply_live_reload: bool = Field(default=False)
    request_restart: bool = Field(default=False)
    execute_restart_hook: bool = Field(default=False)
    actor: str = Field(default='admin')


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
    model_config = ConfigDict(extra="allow")

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


