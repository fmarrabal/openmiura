from __future__ import annotations

from typing import Any


class OpenClawRuntimeContextMixin:
    def _load_runtime_context(
        self,
        gw,
        *,
        runtime_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.openclaw_adapter_service.get_runtime(
            gw,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        runtime = dict(detail.get('runtime') or {})
        runtime_summary = dict(detail.get('runtime_summary') or self.openclaw_adapter_service._build_runtime_summary(runtime))
        scope = dict(runtime_summary.get('scope') or self._scope(
            tenant_id=tenant_id if tenant_id is not None else runtime.get('tenant_id'),
            workspace_id=workspace_id if workspace_id is not None else runtime.get('workspace_id'),
            environment=environment if environment is not None else runtime.get('environment'),
        ))
        return {
            'ok': True,
            'detail': detail,
            'runtime': runtime,
            'runtime_summary': runtime_summary,
            'scope': scope,
        }
