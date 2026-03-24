from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BrokerToolCallRequest(BaseModel):
    agent_id: str = "default"
    session_id: str | None = None
    user_key: str | None = None
    tool_name: str | None = None
    name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    args: dict[str, Any] | None = None
    confirmed: bool = False


class BrokerChatRequest(BaseModel):
    message: str
    agent_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrokerChatResponse(BaseModel):
    ok: bool = True
    channel: str
    user_id: str
    session_id: str
    agent_id: str
    text: str
    transport: str = "http-broker"


class BrokerPendingDecisionRequest(BaseModel):
    agent_id: str | None = None
    confirmed: bool = True


class BrokerTerminalStreamRequest(BaseModel):
    command: str
    agent_id: str = "admin_agent"
    session_id: str | None = None
    user_key: str | None = None
    cwd: str | None = None
    timeout_s: int | None = None
    confirmed: bool = False


class BrokerTokenCreateRequest(BaseModel):
    user_key: str
    label: str = "ui"
    ttl_s: int | None = Field(default=None, ge=60)
    scopes: list[str] = Field(default_factory=lambda: ["broker"])
    tenant_id: str | None = None
    workspace_id: str | None = None
    environment: str | None = None


class BrokerTokenRevokeRequest(BaseModel):
    token_id: int


class BrokerTokenRotateRequest(BaseModel):
    token_id: int
    ttl_s: int | None = Field(default=None, ge=60)


class BrokerLoginRequest(BaseModel):
    username: str
    password: str
    use_cookie_session: bool = True


class BrokerAuthUserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    user_key: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None




class BrokerAuthAuthorizeRequest(BaseModel):
    permission: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    environment: str | None = None


class BrokerAuthSessionRotateRequest(BaseModel):
    session_id: int | None = None


class BrokerAuthSessionRevokeRequest(BaseModel):
    session_id: int | None = None
    revoke_all_for_user: bool = False
    user_id: int | None = None


class BrokerWorkflowCreateRequest(BaseModel):
    name: str
    definition: dict[str, Any]
    input: dict[str, Any] = Field(default_factory=dict)
    autorun: bool = True
    playbook_id: str | None = None


class BrokerWorkflowActionRequest(BaseModel):
    reason: str = ''


class BrokerWorkflowBuilderValidateRequest(BaseModel):
    definition: dict[str, Any]


class BrokerWorkflowBuilderCreateRequest(BaseModel):
    name: str
    definition: dict[str, Any]
    input: dict[str, Any] = Field(default_factory=dict)
    autorun: bool = True
    playbook_id: str | None = None


class BrokerApprovalDecisionRequest(BaseModel):
    decision: str
    reason: str = ''


class BrokerJobCreateRequest(BaseModel):
    name: str
    workflow_definition: dict[str, Any]
    input: dict[str, Any] = Field(default_factory=dict)
    interval_s: int | None = Field(default=None, ge=1)
    next_run_at: float | None = None
    enabled: bool = True
    playbook_id: str | None = None
    schedule_kind: str = 'interval'
    schedule_expr: str | None = None
    timezone: str | None = 'UTC'
    not_before: float | None = None
    not_after: float | None = None
    max_runs: int | None = Field(default=None, ge=1)


class BrokerPlaybookPublicationRequest(BaseModel):
    version: str | None = None
    notes: str = ''


class BrokerPlaybookListRequest(BaseModel):
    published_only: bool = False
    include_versions: bool = False

class BrokerPlaybookInstantiateRequest(BaseModel):
    name: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    autorun: bool = True
