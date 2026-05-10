"""baseline_rollout_management._approval_mixin"""
from __future__ import annotations

import time
import uuid
from typing import Any




OpenClawBaselineRolloutManagementMixin: type | None = None  # late-bound by __init__.py


class _OpenClawBaselineRolloutManagementMixinApprovalMixin:
    """Sub-mixin: approval."""

    def _create_baseline_promotion_layer_approval_request(self, gw, *, release: dict[str, Any], layer: dict[str, Any], actor: str) -> dict[str, Any]:
        promotion_id = str(release.get('release_id') or '')
        return self._ensure_step_approval_request(
            gw,
            workflow_id=self._baseline_promotion_approval_workflow_id(promotion_id),
            step_id=f'baseline-promotion-layer:{str(layer.get("layer_id") or "")}',
            requested_role=str(layer.get('requested_role') or 'approver'),
            requested_by=str(actor or 'system'),
            payload={
                'promotion_id': promotion_id,
                'catalog_id': str(((release.get('metadata') or {}).get('baseline_promotion') or {}).get('catalog_id') or ''),
                'layer_id': str(layer.get('layer_id') or ''),
                'layer_label': str(layer.get('label') or layer.get('layer_id') or ''),
            },
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        )

    def _baseline_promotion_approval_state(self, *, approval_policy: dict[str, Any], approvals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return self._portfolio_approval_state(portfolio_id='baseline-promotion', approval_policy=approval_policy, approvals=approvals)

    def _ensure_baseline_promotion_approvals(self, gw, *, release: dict[str, Any], actor: str, approval_policy: dict[str, Any]) -> dict[str, Any]:
        promotion_id = str(release.get('release_id') or '')
        approvals = self._list_workflow_approvals(gw, limit=max(20, len(list((approval_policy or {}).get('layers') or [])) * 3 + 5), workflow_id=self._baseline_promotion_approval_workflow_id(promotion_id), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        state = self._baseline_promotion_approval_state(approval_policy=approval_policy, approvals=approvals)
        for layer in list((approval_policy or {}).get('layers') or []):
            layer_id = str(layer.get('layer_id') or '')
            layer_state = dict((state.get('by_layer') or {}).get(layer_id) or {})
            if bool(layer.get('required', True)) and str(layer_state.get('status') or '') == 'not_requested':
                self._create_baseline_promotion_layer_approval_request(gw, release=release, layer=layer, actor=actor)
        approvals = self._list_workflow_approvals(gw, limit=max(20, len(list((approval_policy or {}).get('layers') or [])) * 3 + 5), workflow_id=self._baseline_promotion_approval_workflow_id(promotion_id), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        return self._baseline_promotion_approval_state(approval_policy=approval_policy, approvals=approvals)

