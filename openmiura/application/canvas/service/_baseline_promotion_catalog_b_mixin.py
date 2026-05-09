"""openmiura.application.canvas.service._baseline_promotion_catalog_b_mixin

Part of the canvas service split. Methods originally lived on
``openmiura.application.canvas.service.LiveCanvasService``; they
have been moved verbatim into this mixin so that no individual
file in the package exceeds the project's ``max 1,500 lines``
ceiling. The public class still inherits from this mixin and
exposes every method unchanged.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from typing import Any

from openmiura.application.canvas.helpers import (
    enforce_canvas_counts as canvas_enforce_counts,
    enforce_canvas_payload as canvas_enforce_payload,
    enforce_scope_limits as canvas_enforce_scope_limits,
    normalize_toggles as canvas_normalize_toggles,
    payload_size as canvas_payload_size,
    redact_sensitive as canvas_redact_sensitive,
    safe_call as canvas_safe_call,
    sanitize_scope as canvas_sanitize_scope,
)
from openmiura.application.packaging import PackagingHardeningService
from openmiura.core.contracts import AdminGatewayLike


class _LiveCanvasBaselinePromotionCatalogBMixin:
    """Mixin: baseline promotion catalog b methods on LiveCanvasService."""

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_binding_matches(binding: dict[str, Any] | None, *, context: dict[str, Any] | None) -> bool:
        item = dict(binding or {})
        current = dict(context or {})
        scope = str(item.get('binding_scope') or '').strip()
        if str(item.get('state') or 'active') != 'active':
            return False
        workspace_id = str(current.get('workspace_id') or '')
        environment = str(current.get('environment') or '')
        promotion_id = str(current.get('promotion_id') or '')
        portfolio_family_id = str(current.get('portfolio_family_id') or '')
        runtime_family_id = str(current.get('runtime_family_id') or '')
        binding_workspace_id = str(item.get('workspace_id') or '')
        binding_environment = str(item.get('environment') or '')
        if binding_workspace_id and workspace_id and binding_workspace_id != workspace_id:
            return False
        if scope == 'global':
            return True
        if scope == 'workspace':
            return bool(binding_workspace_id) and binding_workspace_id == workspace_id
        if scope == 'environment':
            return bool(binding_workspace_id and binding_environment) and binding_workspace_id == workspace_id and binding_environment == environment
        if scope == 'portfolio_family':
            return bool(binding_workspace_id and binding_environment and str(item.get('portfolio_family_id') or '')) and binding_workspace_id == workspace_id and binding_environment == environment and str(item.get('portfolio_family_id') or '') == portfolio_family_id
        if scope == 'runtime_family':
            return bool(binding_workspace_id and binding_environment and str(item.get('runtime_family_id') or '')) and binding_workspace_id == workspace_id and binding_environment == environment and str(item.get('runtime_family_id') or '') == runtime_family_id
        if scope == 'promotion':
            return bool(str(item.get('promotion_id') or '')) and str(item.get('promotion_id') or '') == promotion_id
        return False

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_binding_summary(bindings: list[dict[str, Any]] | None) -> dict[str, Any]:
        items = [dict(item or {}) for item in list(bindings or []) if isinstance(item, dict) and str((item or {}).get('state') or 'active') == 'active']
        scope_counts: dict[str, int] = {}
        version_keys: set[str] = set()
        latest = {}
        for item in items:
            scope = str(item.get('binding_scope') or '')
            scope_counts[scope] = scope_counts.get(scope, 0) + 1
            if str(item.get('catalog_version_key') or ''):
                version_keys.add(str(item.get('catalog_version_key') or ''))
            if not latest or float(item.get('bound_at') or 0.0) >= float(latest.get('bound_at') or 0.0):
                latest = dict(item)
        return {
            'active_binding_count': len(items),
            'scope_counts': scope_counts,
            'version_key_count': len(version_keys),
            'latest_binding': LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding(latest),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_last_used_pack(node_data: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(node_data or {})
        last_used = dict(payload.get('last_used_routing_policy_pack') or {})
        if last_used:
            return last_used
        latest_simulation = dict(payload.get('latest_simulation') or {})
        export_state = dict(latest_simulation.get('export_state') or {})
        latest_replay = dict(export_state.get('latest_routing_replay') or {})
        applied_pack = dict(latest_replay.get('applied_pack') or {})
        usage_source = 'latest_routing_replay'
        if not applied_pack:
            replay = dict(payload.get('last_simulation_routing_replay') or {})
            applied_pack = dict(replay.get('applied_pack') or {})
            usage_source = 'last_simulation_routing_replay'
        if not applied_pack:
            return {}
        compact = LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(applied_pack)
        compact['usage_source'] = usage_source
        return compact

    def _baseline_promotion_simulation_custody_catalog_pack_compliance(
        self,
        pack: dict[str, Any] | None,
        *,
        context: dict[str, Any] | None,
        bindings: list[dict[str, Any]] | None,
        effective_binding: dict[str, Any] | None,
        node_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        current_context = dict(context or {})
        entry_id = str(payload.get('catalog_entry_id') or payload.get('registry_entry_id') or '')
        version = int(payload.get('catalog_version') or 0)
        matching_bindings = []
        for raw_binding in list(bindings or []):
            if not isinstance(raw_binding, dict):
                continue
            normalized_binding = self._baseline_promotion_simulation_custody_catalog_binding(raw_binding)
            if not self._baseline_promotion_simulation_custody_catalog_binding_matches(normalized_binding, context=current_context):
                continue
            if str(normalized_binding.get('catalog_entry_id') or '') == entry_id and int(normalized_binding.get('catalog_version') or 0) == version:
                matching_bindings.append(normalized_binding)
        last_used_pack = self._baseline_promotion_simulation_custody_catalog_last_used_pack(node_data)
        last_used_entry_id = str(last_used_pack.get('catalog_entry_id') or last_used_pack.get('registry_entry_id') or '')
        last_used_version = int(last_used_pack.get('catalog_version') or 0)
        last_used_matches = bool(entry_id and last_used_entry_id == entry_id and last_used_version == version)
        current_effective_binding = dict(effective_binding or {})
        effective_entry_id = str(current_effective_binding.get('catalog_entry_id') or '')
        effective_version = int(current_effective_binding.get('catalog_version') or 0)
        is_effective = bool(entry_id and effective_entry_id == entry_id and effective_version == version)
        rollout_access = self._baseline_promotion_simulation_custody_catalog_rollout_access(payload, current_context=current_context)
        drift_reasons: list[str] = []
        if is_effective and not bool(current_effective_binding.get('binding_ready', False)):
            drift_reasons.append(str(current_effective_binding.get('binding_ready_reason') or 'effective_binding_not_ready'))
        if is_effective and last_used_pack and not last_used_matches:
            drift_reasons.append('effective_binding_usage_mismatch')
        if last_used_matches:
            if str(payload.get('catalog_lifecycle_state') or 'draft') != 'approved':
                drift_reasons.append('used_pack_not_approved')
            if str(payload.get('catalog_release_state') or 'draft') not in {'released', 'rolling_out'}:
                drift_reasons.append('used_pack_not_released')
            if not bool(rollout_access.get('allowed', False)):
                drift_reasons.append(str(rollout_access.get('reason') or 'catalog_rollout_target_not_released'))
            if current_effective_binding and not is_effective:
                drift_reasons.append('used_pack_not_effective_binding')
            if not current_effective_binding:
                drift_reasons.append('used_pack_without_effective_binding')
        applicable = bool(is_effective or matching_bindings or last_used_matches)
        overall_status = 'not_applicable'
        if applicable:
            overall_status = 'drifted' if drift_reasons else 'conformant'
        return {
            'overall_status': overall_status,
            'applicable': applicable,
            'binding_count': len(matching_bindings),
            'binding_scopes': [str(item.get('binding_scope') or '') for item in matching_bindings[:6]],
            'is_effective_for_current_scope': is_effective,
            'effective_binding_ready': bool(current_effective_binding.get('binding_ready', False)) if is_effective else False,
            'effective_binding_reason': str(current_effective_binding.get('binding_ready_reason') or '') if is_effective else '',
            'last_used_matches': last_used_matches,
            'usage_source': str(last_used_pack.get('usage_source') or ''),
            'usage_present': bool(last_used_pack),
            'used_catalog_entry_id': last_used_entry_id,
            'used_catalog_version': last_used_version,
            'drift_reasons': list(dict.fromkeys([str(reason) for reason in drift_reasons if str(reason)]))[:12],
            'release_state': str(payload.get('catalog_release_state') or 'draft'),
            'lifecycle_state': str(payload.get('catalog_lifecycle_state') or 'draft'),
            'rollout_access_allowed': bool(rollout_access.get('allowed', False)),
            'rollout_access_reason': str(rollout_access.get('reason') or ''),
        }

    def _baseline_promotion_simulation_custody_catalog_compliance_summary(
        self,
        packs: list[dict[str, Any]] | None,
        *,
        context: dict[str, Any] | None,
        bindings: list[dict[str, Any]] | None,
        effective_binding: dict[str, Any] | None,
        node_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        evaluated_items: list[dict[str, Any]] = []
        for item in list(packs or []):
            if not isinstance(item, dict):
                continue
            compliance = dict(item.get('catalog_compliance_summary') or {})
            if not compliance:
                compliance = self._baseline_promotion_simulation_custody_catalog_pack_compliance(
                    item,
                    context=context,
                    bindings=bindings,
                    effective_binding=effective_binding,
                    node_data=node_data,
                )
            if not bool(compliance.get('applicable')):
                continue
            evaluated_items.append({
                'catalog_entry_id': str(item.get('catalog_entry_id') or item.get('registry_entry_id') or ''),
                'catalog_version': int(item.get('catalog_version') or 0),
                'pack_id': str(item.get('pack_id') or ''),
                'pack_label': str(item.get('pack_label') or ''),
                'overall_status': str(compliance.get('overall_status') or ''),
                'is_effective_for_current_scope': bool(compliance.get('is_effective_for_current_scope')),
                'last_used_matches': bool(compliance.get('last_used_matches')),
                'binding_count': int(compliance.get('binding_count') or 0),
                'drift_reasons': [str(reason) for reason in list(compliance.get('drift_reasons') or []) if str(reason)][:12],
                'effective_binding_ready': bool(compliance.get('effective_binding_ready', False)),
                'effective_binding_reason': str(compliance.get('effective_binding_reason') or ''),
            })
        drift_reasons: list[str] = []
        for item in evaluated_items:
            drift_reasons.extend([str(reason) for reason in list(item.get('drift_reasons') or []) if str(reason)])
        last_used_pack = self._baseline_promotion_simulation_custody_catalog_last_used_pack(node_data)
        effective_pack = next((dict(item) for item in evaluated_items if bool(item.get('is_effective_for_current_scope'))), {})
        overall_status = 'unbound'
        if any(str(item.get('overall_status') or '') == 'drifted' for item in evaluated_items):
            overall_status = 'drifted'
        elif effective_pack or last_used_pack:
            overall_status = 'conformant'
        return {
            'overall_status': overall_status,
            'applicable_pack_count': len(evaluated_items),
            'drifted_count': len([item for item in evaluated_items if str(item.get('overall_status') or '') == 'drifted']),
            'conformant_count': len([item for item in evaluated_items if str(item.get('overall_status') or '') == 'conformant']),
            'effective_binding_present': bool(effective_binding),
            'effective_binding_ready': bool((effective_binding or {}).get('binding_ready', False)) if effective_binding else False,
            'effective_binding_reason': str((effective_binding or {}).get('binding_ready_reason') or '') if effective_binding else '',
            'effective_catalog_entry_id': str((effective_binding or {}).get('catalog_entry_id') or ''),
            'effective_catalog_version': int((effective_binding or {}).get('catalog_version') or 0),
            'last_used_catalog_entry_id': str(last_used_pack.get('catalog_entry_id') or last_used_pack.get('registry_entry_id') or ''),
            'last_used_catalog_version': int(last_used_pack.get('catalog_version') or 0),
            'usage_evidence_present': bool(last_used_pack),
            'drift_reasons': list(dict.fromkeys(drift_reasons))[:12],
            'effective_pack': effective_pack,
            'items': evaluated_items[:6],
        }

    def _baseline_promotion_simulation_custody_catalog_pack_analytics(
        self,
        pack: dict[str, Any] | None,
        *,
        context: dict[str, Any] | None,
        bindings: list[dict[str, Any]] | None,
        effective_binding: dict[str, Any] | None,
        node_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        binding_summary = dict(payload.get('catalog_binding_summary') or {})
        if not binding_summary:
            binding_summary = dict(self._baseline_promotion_simulation_custody_catalog_pack_bindings(payload, bindings=bindings, effective_binding=effective_binding).get('catalog_binding_summary') or {})
        compliance = dict(payload.get('catalog_compliance_summary') or {})
        if not compliance:
            compliance = self._baseline_promotion_simulation_custody_catalog_pack_compliance(
                payload,
                context=context,
                bindings=bindings,
                effective_binding=effective_binding,
                node_data=node_data,
            )
        review_state = self._baseline_promotion_simulation_custody_catalog_pack_review_state(payload)
        approval_state = self._baseline_promotion_simulation_custody_catalog_pack_approval_state(payload)
        active_binding_count = int(binding_summary.get('active_binding_count') or 0)
        replay_count = int(payload.get('catalog_replay_count') or 0)
        share_count = int(payload.get('catalog_share_count') or payload.get('share_count') or 0)
        binding_count = max(int(payload.get('catalog_binding_count') or 0), active_binding_count)
        attention_reasons: list[str] = []
        if review_state in {'pending_review', 'in_review', 'review_changes_requested', 'review_rejected'}:
            attention_reasons.append(review_state)
        if approval_state in {'pending', 'rejected'}:
            attention_reasons.append(f'approval_{approval_state}')
        guard_reason = str(((payload.get('catalog_release_guard') or {}).get('reason')) or '')
        if guard_reason:
            attention_reasons.append(guard_reason)
        compliance_status = str((compliance.get('overall_status') or '')).strip() or 'unbound'
        if compliance_status == 'drifted':
            attention_reasons.append('compliance_drifted')
        if bool(payload.get('catalog_emergency_withdrawal_active', False)):
            attention_reasons.append('emergency_withdrawn')
        if str(payload.get('catalog_release_state') or '') == 'withdrawn' and not str(payload.get('catalog_restored_from_entry_id') or ''):
            attention_reasons.append('release_withdrawn')
        activity_points: list[float] = []
        for candidate in [
            payload.get('catalog_last_replayed_at'),
            payload.get('catalog_last_shared_at'),
            payload.get('catalog_last_bound_at'),
            payload.get('catalog_review_last_transition_at'),
            payload.get('catalog_approval_requested_at'),
            payload.get('catalog_approved_at'),
            payload.get('catalog_released_at'),
            payload.get('catalog_withdrawn_at'),
            payload.get('catalog_promoted_at'),
        ]:
            try:
                if candidate is not None:
                    activity_points.append(float(candidate))
            except Exception:
                continue
        last_activity_at = max(activity_points) if activity_points else None
        attention_reasons = list(dict.fromkeys([str(reason) for reason in attention_reasons if str(reason)]))[:8]
        return {
            'catalog_entry_id': str(payload.get('catalog_entry_id') or payload.get('registry_entry_id') or ''),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'pack_id': str(payload.get('pack_id') or ''),
            'pack_label': str(payload.get('pack_label') or ''),
            'catalog_scope': str(payload.get('catalog_scope') or payload.get('registry_scope') or ''),
            'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
            'release_state': str(payload.get('catalog_release_state') or 'draft'),
            'lifecycle_state': str(payload.get('catalog_lifecycle_state') or 'draft'),
            'approval_state': approval_state,
            'review_state': review_state,
            'compliance_status': compliance_status,
            'active_binding_count': active_binding_count,
            'binding_count': binding_count,
            'replay_count': replay_count,
            'share_count': share_count,
            'review_note_count': int(payload.get('catalog_review_note_count') or 0),
            'approval_count': int(payload.get('catalog_approval_count') or 0),
            'analytics_report_count': int(payload.get('catalog_analytics_report_count') or 0),
            'compliance_report_count': int(payload.get('catalog_compliance_report_count') or 0),
            'is_effective_for_current_scope': bool(payload.get('catalog_is_effective_for_current_scope', False)),
            'effective_binding_ready': bool((effective_binding or {}).get('binding_ready', False)) if payload.get('catalog_is_effective_for_current_scope', False) else False,
            'last_replayed_at': payload.get('catalog_last_replayed_at'),
            'last_replayed_by': str(payload.get('catalog_last_replayed_by') or ''),
            'last_shared_at': payload.get('catalog_last_shared_at'),
            'last_shared_by': str(payload.get('catalog_last_shared_by') or ''),
            'last_bound_at': payload.get('catalog_last_bound_at'),
            'last_bound_by': str(payload.get('catalog_last_bound_by') or ''),
            'last_activity_at': last_activity_at,
            'attention_required': bool(attention_reasons),
            'attention_reasons': attention_reasons,
        }

    def _baseline_promotion_simulation_custody_catalog_analytics_summary(
        self,
        packs: list[dict[str, Any]] | None,
        *,
        context: dict[str, Any] | None,
        bindings: list[dict[str, Any]] | None,
        effective_binding: dict[str, Any] | None,
        node_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        evaluated_items: list[dict[str, Any]] = []
        for item in list(packs or []):
            if not isinstance(item, dict):
                continue
            analytics = dict(item.get('catalog_analytics_summary') or {})
            if not analytics:
                analytics = self._baseline_promotion_simulation_custody_catalog_pack_analytics(
                    item,
                    context=context,
                    bindings=bindings,
                    effective_binding=effective_binding,
                    node_data=node_data,
                )
            evaluated_items.append(analytics)
        sorted_items = sorted(evaluated_items, key=lambda item: (int(item.get('attention_required') or 0), float(item.get('last_activity_at') or 0.0), int(item.get('replay_count') or 0)), reverse=True)
        top_replayed = sorted(evaluated_items, key=lambda item: (int(item.get('replay_count') or 0), float(item.get('last_replayed_at') or 0.0)), reverse=True)[:3]
        top_shared = sorted(evaluated_items, key=lambda item: (int(item.get('share_count') or 0), float(item.get('last_shared_at') or 0.0)), reverse=True)[:3]
        top_adopted = sorted(evaluated_items, key=lambda item: (int(item.get('active_binding_count') or 0), int(item.get('binding_count') or 0), float(item.get('last_bound_at') or 0.0)), reverse=True)[:3]
        latest_activity_at = max([float(item.get('last_activity_at') or 0.0) for item in evaluated_items] or [0.0]) or None
        overall_status = 'healthy'
        if any(bool(item.get('attention_required')) for item in evaluated_items):
            overall_status = 'attention_required'
        elif any(str(item.get('compliance_status') or '') == 'drifted' for item in evaluated_items):
            overall_status = 'drifted'
        elif not evaluated_items:
            overall_status = 'empty'
        return {
            'overall_status': overall_status,
            'catalog_entry_count': len(evaluated_items),
            'active_binding_count': sum(int(item.get('active_binding_count') or 0) for item in evaluated_items),
            'effective_scope_count': len([item for item in evaluated_items if bool(item.get('is_effective_for_current_scope'))]),
            'total_replay_count': sum(int(item.get('replay_count') or 0) for item in evaluated_items),
            'total_share_count': sum(int(item.get('share_count') or 0) for item in evaluated_items),
            'attention_required_count': len([item for item in evaluated_items if bool(item.get('attention_required'))]),
            'drifted_count': len([item for item in evaluated_items if str(item.get('compliance_status') or '') == 'drifted']),
            'released_count': len([item for item in evaluated_items if str(item.get('release_state') or '') == 'released']),
            'review_pending_count': len([item for item in evaluated_items if str(item.get('review_state') or '') in {'pending_review', 'in_review', 'review_changes_requested'}]),
            'approval_pending_count': len([item for item in evaluated_items if str(item.get('approval_state') or '') == 'pending']),
            'analytics_reported_count': len([item for item in evaluated_items if int(item.get('analytics_report_count') or 0) > 0]),
            'latest_activity_at': latest_activity_at,
            'top_replayed_packs': top_replayed,
            'top_shared_packs': top_shared,
            'top_adopted_packs': top_adopted,
            'attention_items': sorted_items[:6],
            'items': evaluated_items[:6],
        }

    def _baseline_promotion_simulation_custody_catalog_operator_dashboard(
        self,
        packs: list[dict[str, Any]] | None,
        *,
        context: dict[str, Any] | None,
        bindings: list[dict[str, Any]] | None,
        effective_binding: dict[str, Any] | None,
        node_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        analytics_summary = self._baseline_promotion_simulation_custody_catalog_analytics_summary(
            packs,
            context=context,
            bindings=bindings,
            effective_binding=effective_binding,
            node_data=node_data,
        )
        attention_queue = [
            {
                'catalog_entry_id': str(item.get('catalog_entry_id') or ''),
                'pack_label': str(item.get('pack_label') or ''),
                'attention_reasons': [str(reason) for reason in list(item.get('attention_reasons') or []) if str(reason)][:6],
                'review_state': str(item.get('review_state') or ''),
                'approval_state': str(item.get('approval_state') or ''),
                'release_state': str(item.get('release_state') or ''),
                'compliance_status': str(item.get('compliance_status') or ''),
                'last_activity_at': item.get('last_activity_at'),
            }
            for item in list(analytics_summary.get('attention_items') or [])[:6]
        ]
        return {
            'dashboard_type': 'openmiura_routing_policy_pack_operator_dashboard_v1',
            'generated_at': time.time(),
            'scope': dict(context or {}),
            'overall_status': str(analytics_summary.get('overall_status') or ''),
            'operational_posture': {
                'attention_required_count': int(analytics_summary.get('attention_required_count') or 0),
                'drifted_count': int(analytics_summary.get('drifted_count') or 0),
                'released_count': int(analytics_summary.get('released_count') or 0),
                'effective_scope_count': int(analytics_summary.get('effective_scope_count') or 0),
            },
            'leaderboards': {
                'replays': list(analytics_summary.get('top_replayed_packs') or []),
                'shares': list(analytics_summary.get('top_shared_packs') or []),
                'adoption': list(analytics_summary.get('top_adopted_packs') or []),
            },
            'attention_queue': attention_queue,
            'summary': analytics_summary,
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_organizational_catalog_service_id(*, tenant_id: str | None) -> str:
        tenant_key = str(tenant_id or 'global').strip() or 'global'
        return f'openmiura-routing-policy-pack-org-catalog::{tenant_key}'

    @staticmethod
    def _baseline_promotion_simulation_custody_organizational_catalog_scope_key(
        visibility: str | None,
        *,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> str:
        tenant_key = str(tenant_id or 'global').strip() or 'global'
        workspace_key = str(workspace_id or '').strip()
        environment_key = str(environment or '').strip()
        normalized_visibility = str(visibility or 'tenant').strip() or 'tenant'
        if normalized_visibility == 'environment':
            return ':'.join(part for part in (tenant_key, workspace_key or '*', environment_key or '*'))
        if normalized_visibility == 'workspace':
            return ':'.join(part for part in (tenant_key, workspace_key or '*'))
        return tenant_key

    def _baseline_promotion_simulation_custody_organizational_catalog_pack_visible(
        self,
        pack: dict[str, Any] | None,
        *,
        context: dict[str, Any] | None,
    ) -> bool:
        payload = dict(pack or {})
        if str(payload.get('organizational_publish_state') or '') != 'published':
            return False
        current = dict(context or {})
        visibility = str(payload.get('organizational_visibility') or 'tenant').strip() or 'tenant'
        if visibility == 'workspace':
            target_workspace = str(payload.get('workspace_id') or '').strip()
            current_workspace = str(current.get('workspace_id') or '').strip()
            return not target_workspace or not current_workspace or target_workspace == current_workspace
        if visibility == 'environment':
            target_workspace = str(payload.get('workspace_id') or '').strip()
            target_environment = str(payload.get('environment') or '').strip()
            current_workspace = str(current.get('workspace_id') or '').strip()
            current_environment = str(current.get('environment') or '').strip()
            workspace_ok = not target_workspace or not current_workspace or target_workspace == current_workspace
            environment_ok = not target_environment or not current_environment or target_environment == current_environment
            return workspace_ok and environment_ok
        return True

    def _baseline_promotion_simulation_custody_organizational_publication_health(
        self,
        pack: dict[str, Any] | None,
        *,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        visibility = str(payload.get('organizational_visibility') or 'tenant').strip() or 'tenant'
        expected_scope_key = self._baseline_promotion_simulation_custody_organizational_catalog_scope_key(
            visibility,
            tenant_id=tenant_id,
            workspace_id=str(payload.get('workspace_id') or workspace_id or ''),
            environment=str(payload.get('environment') or environment or ''),
        )
        stored_manifest = dict(payload.get('organizational_publication_manifest') or {})
        current_manifest = self._baseline_promotion_simulation_custody_organizational_publication_manifest(
            payload,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        issues: list[str] = []
        if str(payload.get('organizational_publish_state') or '') != 'published':
            issues.append('publish_state_mismatch')
        if str(payload.get('catalog_lifecycle_state') or 'draft') != 'approved':
            issues.append('lifecycle_state_drift')
        if str(payload.get('catalog_release_state') or 'draft') not in {'released', 'rolling_out'}:
            issues.append('release_state_drift')
        if not str(payload.get('organizational_service_id') or '').strip() or not str(payload.get('organizational_service_entry_id') or '').strip():
            issues.append('service_reference_missing')
        if str(payload.get('organizational_service_scope_key') or expected_scope_key) != expected_scope_key:
            issues.append('service_scope_drift')
        if not str(payload.get('catalog_owner_canvas_id') or '').strip() or not str(payload.get('catalog_owner_node_id') or '').strip():
            issues.append('owner_reference_missing')
        stored_manifest_digest = str(stored_manifest.get('manifest_digest') or '')
        if not stored_manifest_digest:
            issues.append('publication_manifest_missing')
        elif stored_manifest_digest != str(current_manifest.get('manifest_digest') or ''):
            issues.append('publication_manifest_drift')
        issue_counts: dict[str, int] = {}
        for issue in issues:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
        return {
            'status': 'healthy' if not issues else 'drifted',
            'issue_count': len(issues),
            'issue_codes': issues[:8],
            'issue_counts': issue_counts,
            'organizational_service_id': str(payload.get('organizational_service_id') or current_manifest.get('organizational_service_id') or ''),
            'organizational_service_entry_id': str(payload.get('organizational_service_entry_id') or current_manifest.get('organizational_service_entry_id') or ''),
            'catalog_entry_id': str(payload.get('catalog_entry_id') or payload.get('registry_entry_id') or ''),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'pack_id': str(payload.get('pack_id') or ''),
            'pack_label': str(payload.get('pack_label') or ''),
            'organizational_visibility': visibility,
            'organizational_service_scope_key': str(payload.get('organizational_service_scope_key') or ''),
            'expected_scope_key': expected_scope_key,
            'catalog_lifecycle_state': str(payload.get('catalog_lifecycle_state') or 'draft'),
            'catalog_release_state': str(payload.get('catalog_release_state') or 'draft'),
            'published_at': payload.get('organizational_published_at'),
            'published_by': str(payload.get('organizational_published_by') or ''),
            'manifest_digest': stored_manifest_digest,
            'current_manifest_digest': str(current_manifest.get('manifest_digest') or ''),
        }

    def _baseline_promotion_simulation_custody_organizational_catalog_service_packs(
        self,
        gw: AdminGatewayLike,
        *,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> list[dict[str, Any]]:
        current_context = {
            'tenant_id': str(tenant_id or ''),
            'workspace_id': str(workspace_id or ''),
            'environment': str(environment or ''),
        }
        service_id = self._baseline_promotion_simulation_custody_organizational_catalog_service_id(tenant_id=tenant_id)
        documents = self._safe_call(
            gw.audit,
            'list_canvas_documents',
            [],
            limit=200,
            tenant_id=tenant_id,
            workspace_id=None,
            environment=None,
        )
        collected: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int]] = set()
        for document in list(documents or []):
            canvas_id = str((document or {}).get('canvas_id') or '')
            if not canvas_id:
                continue
            nodes = self._safe_call(
                gw.audit,
                'list_canvas_nodes',
                [],
                canvas_id=canvas_id,
                tenant_id=(document or {}).get('tenant_id'),
                workspace_id=(document or {}).get('workspace_id'),
                environment=(document or {}).get('environment'),
            )
            for node in list(nodes or []):
                if str((node or {}).get('node_type') or '').strip().lower() not in {'baseline_promotion', 'policy_baseline_promotion'}:
                    continue
                raw_registry = [dict(item or {}) for item in list(((node or {}).get('data') or {}).get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                for index, item in enumerate(raw_registry, start=1):
                    normalized = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(
                        item,
                        actor=str(item.get('created_by') or item.get('promoted_by') or ''),
                        index=index,
                        source=str(item.get('source') or 'registry'),
                    )
                    if not self._baseline_promotion_simulation_custody_organizational_catalog_pack_visible(normalized, context=current_context):
                        continue
                    normalized['organizational_service_id'] = str(normalized.get('organizational_service_id') or service_id)
                    if not str(normalized.get('organizational_service_scope_key') or '').strip():
                        normalized['organizational_service_scope_key'] = self._baseline_promotion_simulation_custody_organizational_catalog_scope_key(
                            normalized.get('organizational_visibility') or 'tenant',
                            tenant_id=tenant_id,
                            workspace_id=normalized.get('workspace_id') or document.get('workspace_id'),
                            environment=normalized.get('environment') or document.get('environment'),
                        )
                    if not str(normalized.get('organizational_service_entry_id') or '').strip():
                        normalized['organizational_service_entry_id'] = str(self.openclaw_recovery_scheduler_service._stable_digest({
                            'service_id': normalized.get('organizational_service_id') or service_id,
                            'catalog_entry_id': str(normalized.get('catalog_entry_id') or normalized.get('registry_entry_id') or ''),
                            'catalog_version': int(normalized.get('catalog_version') or 0),
                        })[:24])
                    normalized['catalog_owner_canvas_id'] = str((node or {}).get('canvas_id') or canvas_id)
                    normalized['catalog_owner_node_id'] = str((node or {}).get('node_id') or '')
                    normalized['catalog_owner_node_label'] = str((node or {}).get('label') or '')
                    normalized['organizational_publication_manifest'] = dict(normalized.get('organizational_publication_manifest') or self._baseline_promotion_simulation_custody_organizational_publication_manifest(
                        normalized,
                        tenant_id=tenant_id,
                        workspace_id=normalized.get('workspace_id') or document.get('workspace_id'),
                        environment=normalized.get('environment') or document.get('environment'),
                    ))
                    normalized['organizational_publication_health'] = self._baseline_promotion_simulation_custody_organizational_publication_health(
                        normalized,
                        tenant_id=tenant_id,
                        workspace_id=normalized.get('workspace_id') or document.get('workspace_id'),
                        environment=normalized.get('environment') or document.get('environment'),
                    )
                    dedupe_key = (
                        str(normalized.get('organizational_service_entry_id') or ''),
                        str(normalized.get('catalog_entry_id') or normalized.get('registry_entry_id') or ''),
                        int(normalized.get('catalog_version') or 0),
                    )
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    collected.append(normalized)
        release_order = {'released': 3, 'rolling_out': 2, 'staged': 1, 'withdrawn': 0, 'draft': -1}
        collected.sort(
            key=lambda item: (
                release_order.get(str(item.get('catalog_release_state') or 'draft'), -1),
                float(item.get('organizational_published_at') or item.get('catalog_released_at') or item.get('catalog_promoted_at') or item.get('created_at') or 0.0),
                int(item.get('catalog_version') or 0),
            ),
            reverse=True,
        )
        return self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(collected))

    def _baseline_promotion_simulation_custody_organizational_catalog_service_summary(
        self,
        packs: list[dict[str, Any]] | None,
        *,
        tenant_id: str | None,
        effective_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        items = [dict(item or {}) for item in list(packs or []) if isinstance(item, dict)]
        visibility_counts: dict[str, int] = {}
        release_counts: dict[str, int] = {}
        lifecycle_counts: dict[str, int] = {}
        publication_health_counts: dict[str, int] = {}
        publication_issue_counts: dict[str, int] = {}
        total_replay_count = 0
        total_binding_count = 0
        attention_required_count = 0
        effective_entry_id = str((effective_binding or {}).get('catalog_entry_id') or '')
        effective_version = int((effective_binding or {}).get('catalog_version') or 0)
        latest_publication = {}
        latest_reconciliation_report = {}
        for item in items:
            visibility = str(item.get('organizational_visibility') or 'tenant')
            visibility_counts[visibility] = visibility_counts.get(visibility, 0) + 1
            release_state = str(item.get('catalog_release_state') or 'draft')
            release_counts[release_state] = release_counts.get(release_state, 0) + 1
            lifecycle = str(item.get('catalog_lifecycle_state') or 'draft')
            lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + 1
            total_replay_count += int(item.get('catalog_replay_count') or 0)
            total_binding_count += int(item.get('catalog_binding_count') or 0)
            if bool(((item.get('catalog_analytics_summary') or {}).get('attention_required', False))):
                attention_required_count += 1
            publication_health = dict(item.get('organizational_publication_health') or {})
            health_status = str(publication_health.get('status') or 'healthy')
            publication_health_counts[health_status] = publication_health_counts.get(health_status, 0) + 1
            for issue_code, count in dict(publication_health.get('issue_counts') or {}).items():
                publication_issue_counts[str(issue_code)] = publication_issue_counts.get(str(issue_code), 0) + int(count or 0)
            latest_report = dict(item.get('organizational_latest_reconciliation_report') or {})
            if latest_report and (not latest_reconciliation_report or float(latest_report.get('generated_at') or 0.0) >= float(latest_reconciliation_report.get('generated_at') or 0.0)):
                latest_reconciliation_report = latest_report
            if not latest_publication or float(item.get('organizational_published_at') or 0.0) >= float(latest_publication.get('organizational_published_at') or 0.0):
                latest_publication = item
        effective_service_entry = next(
            (
                item for item in items
                if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == effective_entry_id and int(item.get('catalog_version') or 0) == effective_version
            ),
            {},
        )
        return {
            'service_id': self._baseline_promotion_simulation_custody_organizational_catalog_service_id(tenant_id=tenant_id),
            'published_entry_count': len(items),
            'released_entry_count': len([item for item in items if str(item.get('catalog_release_state') or '') in {'released', 'rolling_out'}]),
            'effective_entry_count': 1 if effective_service_entry else 0,
            'visibility_counts': visibility_counts,
            'release_counts': release_counts,
            'lifecycle_counts': lifecycle_counts,
            'publication_health_counts': publication_health_counts,
            'publication_issue_counts': publication_issue_counts,
            'healthy_publication_count': int(publication_health_counts.get('healthy', 0) or 0),
            'drifted_publication_count': int(publication_health_counts.get('drifted', 0) or 0),
            'overall_publication_status': 'drifted' if int(publication_health_counts.get('drifted', 0) or 0) > 0 else 'healthy',
            'total_replay_count': total_replay_count,
            'total_binding_count': total_binding_count,
            'attention_required_count': attention_required_count,
            'latest_publication': {
                'organizational_service_entry_id': str(latest_publication.get('organizational_service_entry_id') or ''),
                'catalog_entry_id': str(latest_publication.get('catalog_entry_id') or latest_publication.get('registry_entry_id') or ''),
                'catalog_version': int(latest_publication.get('catalog_version') or 0),
                'pack_id': str(latest_publication.get('pack_id') or ''),
                'pack_label': str(latest_publication.get('pack_label') or ''),
                'organizational_visibility': str(latest_publication.get('organizational_visibility') or ''),
                'organizational_published_at': latest_publication.get('organizational_published_at'),
                'organizational_published_by': str(latest_publication.get('organizational_published_by') or ''),
            },
            'latest_reconciliation_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(latest_reconciliation_report),
            'effective_entry': {
                'organizational_service_entry_id': str(effective_service_entry.get('organizational_service_entry_id') or ''),
                'catalog_entry_id': str(effective_service_entry.get('catalog_entry_id') or ''),
                'catalog_version': int(effective_service_entry.get('catalog_version') or 0),
                'pack_id': str(effective_service_entry.get('pack_id') or ''),
                'pack_label': str(effective_service_entry.get('pack_label') or ''),
            } if effective_service_entry else {},
        }

    def _baseline_promotion_simulation_custody_catalog_policy_bindings(
        self,
        gw: AdminGatewayLike,
        *,
        tenant_id: str | None,
    ) -> list[dict[str, Any]]:
        documents = self._safe_call(
            gw.audit,
            'list_canvas_documents',
            [],
            limit=200,
            tenant_id=tenant_id,
            workspace_id=None,
            environment=None,
        )
        collected: list[dict[str, Any]] = []
        for document in list(documents or []):
            canvas_id = str((document or {}).get('canvas_id') or '')
            if not canvas_id:
                continue
            nodes = self._safe_call(
                gw.audit,
                'list_canvas_nodes',
                [],
                canvas_id=canvas_id,
                tenant_id=(document or {}).get('tenant_id'),
                workspace_id=(document or {}).get('workspace_id'),
                environment=(document or {}).get('environment'),
            )
            for node in list(nodes or []):
                if str((node or {}).get('node_type') or '').strip().lower() not in {'baseline_promotion', 'policy_baseline_promotion'}:
                    continue
                for raw_item in list(((node or {}).get('data') or {}).get('routing_policy_pack_bindings') or []):
                    if not isinstance(raw_item, dict):
                        continue
                    binding = self._baseline_promotion_simulation_custody_catalog_binding(raw_item)
                    binding['catalog_owner_canvas_id'] = canvas_id
                    binding['catalog_owner_node_id'] = str((node or {}).get('node_id') or '')
                    binding['catalog_owner_node_label'] = str((node or {}).get('label') or '')
                    collected.append(binding)
        return collected

    def _baseline_promotion_simulation_custody_effective_catalog_binding(
        self,
        bindings: list[dict[str, Any]] | None,
        *,
        context: dict[str, Any] | None,
        catalog_packs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        current = dict(context or {})
        packs = [dict(item or {}) for item in list(catalog_packs or []) if isinstance(item, dict)]
        candidates: list[dict[str, Any]] = []
        for binding in list(bindings or []):
            if not isinstance(binding, dict):
                continue
            normalized = self._baseline_promotion_simulation_custody_catalog_binding(binding)
            if not self._baseline_promotion_simulation_custody_catalog_binding_matches(normalized, context=current):
                continue
            pack = next((item for item in packs if str(item.get('catalog_entry_id') or '') == str(normalized.get('catalog_entry_id') or '') and int(item.get('catalog_version') or 0) == int(normalized.get('catalog_version') or 0)), {})
            if not pack and str(normalized.get('catalog_version_key') or ''):
                pack = next((item for item in packs if str(item.get('catalog_version_key') or '') == str(normalized.get('catalog_version_key') or '') and int(item.get('catalog_version') or 0) == int(normalized.get('catalog_version') or 0)), {})
            ready = False
            ready_reason = ''
            if not pack:
                ready_reason = 'catalog_binding_pack_missing'
            elif str(pack.get('catalog_lifecycle_state') or '') != 'approved':
                ready_reason = 'catalog_binding_pack_not_approved'
            elif str(pack.get('catalog_release_state') or '') not in {'released', 'rolling_out'}:
                ready_reason = 'catalog_binding_pack_not_released'
            else:
                rollout_access = self._baseline_promotion_simulation_custody_catalog_rollout_access(pack, current_context=current)
                if not bool(rollout_access.get('allowed')):
                    ready_reason = str(rollout_access.get('reason') or 'catalog_rollout_target_not_released')
                else:
                    ready = True
            candidate = dict(normalized)
            candidate['binding_ready'] = ready
            candidate['binding_ready_reason'] = ready_reason
            if pack:
                candidate['catalog_pack_id'] = str(pack.get('pack_id') or normalized.get('catalog_pack_id') or '')
                candidate['catalog_pack_label'] = str(pack.get('pack_label') or normalized.get('catalog_pack_label') or '')
            candidates.append(candidate)
        if not candidates:
            return {}
        candidates.sort(key=lambda item: (1 if bool(item.get('binding_ready')) else 0, self._baseline_promotion_simulation_custody_catalog_binding_scope_order(item.get('binding_scope')), float(item.get('bound_at') or 0.0), int(item.get('catalog_version') or 0)), reverse=True)
        return candidates[0]

    def _baseline_promotion_simulation_custody_catalog_pack_bindings(
        self,
        pack: dict[str, Any] | None,
        *,
        bindings: list[dict[str, Any]] | None,
        effective_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        entry_id = str(payload.get('catalog_entry_id') or '')
        version = int(payload.get('catalog_version') or 0)
        matches = [
            self._baseline_promotion_simulation_custody_catalog_binding(item)
            for item in list(bindings or [])
            if isinstance(item, dict) and str((item or {}).get('catalog_entry_id') or '') == entry_id and int((item or {}).get('catalog_version') or 0) == version and str((item or {}).get('state') or 'active') == 'active'
        ]
        summary = self._baseline_promotion_simulation_custody_catalog_binding_summary(matches)
        effective = dict(effective_binding or {})
        is_effective = bool(entry_id and str(effective.get('catalog_entry_id') or '') == entry_id and int(effective.get('catalog_version') or 0) == version and bool(effective.get('binding_ready', False)))
        return {
            'catalog_binding_summary': summary,
            'catalog_effective_binding': effective if is_effective else {},
            'catalog_is_effective_for_current_scope': is_effective,
        }

    def _baseline_promotion_simulation_custody_rebind_catalog_bindings(
        self,
        gw: AdminGatewayLike,
        *,
        from_pack: dict[str, Any] | None,
        to_pack: dict[str, Any] | None,
        actor: str,
        tenant_id: str | None,
        reason: str,
    ) -> dict[str, Any]:
        source = dict(from_pack or {})
        target = dict(to_pack or {})
        from_entry_id = str(source.get('catalog_entry_id') or '')
        from_version = int(source.get('catalog_version') or 0)
        to_entry_id = str(target.get('catalog_entry_id') or '')
        to_version = int(target.get('catalog_version') or 0)
        if not from_entry_id or not to_entry_id or not to_version:
            return {'updated_binding_count': 0, 'updated_nodes': []}
        now = time.time()
        updated_count = 0
        updated_nodes: list[dict[str, Any]] = []
        documents = self._safe_call(
            gw.audit,
            'list_canvas_documents',
            [],
            limit=200,
            tenant_id=tenant_id,
            workspace_id=None,
            environment=None,
        )
        for document in list(documents or []):
            canvas_id = str((document or {}).get('canvas_id') or '')
            if not canvas_id:
                continue
            nodes = self._safe_call(
                gw.audit,
                'list_canvas_nodes',
                [],
                canvas_id=canvas_id,
                tenant_id=(document or {}).get('tenant_id'),
                workspace_id=(document or {}).get('workspace_id'),
                environment=(document or {}).get('environment'),
            )
            for node in list(nodes or []):
                if str((node or {}).get('node_type') or '').strip().lower() not in {'baseline_promotion', 'policy_baseline_promotion'}:
                    continue
                raw_bindings = [dict(item or {}) for item in list(((node or {}).get('data') or {}).get('routing_policy_pack_bindings') or []) if isinstance(item, dict)]
                if not raw_bindings:
                    continue
                raw_events = [dict(item or {}) for item in list(((node or {}).get('data') or {}).get('routing_policy_pack_binding_events') or []) if isinstance(item, dict)]
                changed = False
                rebound_binding = {}
                updated_bindings = []
                for raw_binding in raw_bindings:
                    binding = self._baseline_promotion_simulation_custody_catalog_binding(raw_binding)
                    if str(binding.get('state') or 'active') == 'active' and str(binding.get('catalog_entry_id') or '') == from_entry_id and int(binding.get('catalog_version') or 0) == from_version:
                        binding['catalog_entry_id'] = to_entry_id
                        binding['catalog_version_key'] = str(target.get('catalog_version_key') or binding.get('catalog_version_key') or '')
                        binding['catalog_version'] = to_version
                        binding['catalog_pack_id'] = str(target.get('pack_id') or binding.get('catalog_pack_id') or '')
                        binding['catalog_pack_label'] = str(target.get('pack_label') or binding.get('catalog_pack_label') or '')
                        binding['rebound_at'] = now
                        binding['rebound_by'] = str(actor or 'operator')
                        binding['rebound_reason'] = str(reason or 'release_rollback')
                        rebound_binding = dict(binding)
                        raw_events.append({
                            'event_id': self.openclaw_recovery_scheduler_service._stable_digest({'binding_id': str(binding.get('binding_id') or ''), 'catalog_entry_id': to_entry_id, 'catalog_version': to_version, 'at': now, 'kind': 'binding_rebound'})[:24],
                            'event_type': 'binding_rebound',
                            'binding_id': str(binding.get('binding_id') or ''),
                            'binding_scope': str(binding.get('binding_scope') or ''),
                            'binding_scope_key': str(binding.get('binding_scope_key') or ''),
                            'catalog_entry_id': to_entry_id,
                            'catalog_version_key': str(binding.get('catalog_version_key') or ''),
                            'catalog_version': to_version,
                            'rebound_to_catalog_entry_id': to_entry_id,
                            'rebound_to_catalog_version': to_version,
                            'at': now,
                            'by': str(actor or 'operator'),
                            'note': str(reason or 'release_rollback'),
                        })
                        changed = True
                        updated_count += 1
                    updated_bindings.append(binding)
                if not changed:
                    continue
                updated_data = dict((node or {}).get('data') or {})
                updated_data['routing_policy_pack_bindings'] = [self._compact_baseline_promotion_simulation_catalog_binding(item) for item in updated_bindings[-12:]]
                updated_data['routing_policy_pack_binding_events'] = [self._compact_baseline_promotion_simulation_catalog_binding_event(item) for item in raw_events[-12:]]
                if rebound_binding:
                    updated_data['last_catalog_binding_routing_policy_pack'] = self._compact_baseline_promotion_simulation_catalog_binding(rebound_binding)
                replacement = self._replace_node_data(
                    gw,
                    canvas_id=canvas_id,
                    node=dict(node or {}),
                    actor=str(actor or 'operator'),
                    data=updated_data,
                    tenant_id=(document or {}).get('tenant_id'),
                    workspace_id=(document or {}).get('workspace_id'),
                    environment=(document or {}).get('environment'),
                )
                if isinstance(replacement, dict):
                    updated_nodes.append({'canvas_id': canvas_id, 'node_id': str((replacement.get('node') or {}).get('node_id') or (node or {}).get('node_id') or '')})
        return {'updated_binding_count': updated_count, 'updated_nodes': updated_nodes}

    def _baseline_promotion_simulation_custody_catalog_pack_visible(
        self,
        pack: dict[str, Any] | None,
        *,
        context: dict[str, str] | None,
    ) -> bool:
        payload = dict(pack or {})
        current = dict(context or {})
        scope = str(payload.get('catalog_scope') or payload.get('registry_scope') or 'promotion').strip() or 'promotion'
        workspace_id = str(current.get('workspace_id') or '')
        environment = str(current.get('environment') or '')
        promotion_id = str(current.get('promotion_id') or '')
        portfolio_family_id = str(current.get('portfolio_family_id') or '')
        runtime_family_id = str(current.get('runtime_family_id') or '')
        pack_workspace_id = str(payload.get('workspace_id') or '')
        pack_environment = str(payload.get('environment') or '')
        pack_promotion_id = str(payload.get('promotion_id') or '')
        if workspace_id and pack_workspace_id and pack_workspace_id != workspace_id:
            return False
        if scope == 'promotion':
            return bool(promotion_id) and pack_promotion_id == promotion_id
        if scope == 'workspace':
            return not workspace_id or not pack_workspace_id or pack_workspace_id == workspace_id
        if scope == 'environment':
            return (not workspace_id or not pack_workspace_id or pack_workspace_id == workspace_id) and (not environment or not pack_environment or pack_environment == environment)
        if scope == 'portfolio_family':
            return bool(portfolio_family_id) and str(payload.get('portfolio_family_id') or '') == portfolio_family_id and (not environment or not pack_environment or pack_environment == environment)
        if scope == 'runtime_family':
            return bool(runtime_family_id) and str(payload.get('runtime_family_id') or '') == runtime_family_id and (not environment or not pack_environment or pack_environment == environment)
        return True

    def _baseline_promotion_simulation_custody_catalog_policy_packs(
        self,
        gw: AdminGatewayLike,
        *,
        promotion_detail: dict[str, Any] | None,
        node_data: dict[str, Any] | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> list[dict[str, Any]]:
        context = self._baseline_promotion_simulation_custody_catalog_context(
            promotion_detail=promotion_detail,
            node_data=node_data,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        documents = self._safe_call(
            gw.audit,
            'list_canvas_documents',
            [],
            limit=200,
            tenant_id=tenant_id,
            workspace_id=None,
            environment=None,
        )
        seen: set[tuple[str, str, str, str, str, str]] = set()
        collected: list[dict[str, Any]] = []
        for document in list(documents or []):
            canvas_id = str((document or {}).get('canvas_id') or '')
            if not canvas_id:
                continue
            nodes = self._safe_call(
                gw.audit,
                'list_canvas_nodes',
                [],
                canvas_id=canvas_id,
                tenant_id=(document or {}).get('tenant_id'),
                workspace_id=(document or {}).get('workspace_id'),
                environment=(document or {}).get('environment'),
            )
            for node in list(nodes or []):
                if str((node or {}).get('node_type') or '').strip().lower() not in {'baseline_promotion', 'policy_baseline_promotion'}:
                    continue
                raw_registry = [dict(item or {}) for item in list(((node or {}).get('data') or {}).get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                for index, item in enumerate(raw_registry, start=1):
                    normalized = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(
                        item,
                        actor=str(item.get('created_by') or item.get('promoted_by') or ''),
                        index=index,
                        source=str(item.get('source') or 'registry'),
                    )
                    normalized['catalog_owner_canvas_id'] = str((node or {}).get('canvas_id') or canvas_id)
                    normalized['catalog_owner_node_id'] = str((node or {}).get('node_id') or '')
                    normalized['catalog_owner_node_label'] = str((node or {}).get('label') or '')
                    if not self._baseline_promotion_simulation_custody_catalog_pack_visible(normalized, context=context):
                        continue
                    if bool(normalized.get('catalog_rollout_enabled', False)) or str(normalized.get('catalog_release_state') or '') in {'rolling_out', 'released'}:
                        normalized = self._baseline_promotion_simulation_custody_catalog_refresh_rollout_state(gw, pack=normalized, current_context=context)
                    key = (
                        str(normalized.get('catalog_entry_id') or normalized.get('registry_entry_id') or normalized.get('pack_id') or ''),
                        str(normalized.get('catalog_scope') or normalized.get('registry_scope') or ''),
                        str(normalized.get('promotion_id') or ''),
                        str(normalized.get('workspace_id') or ''),
                        str(normalized.get('portfolio_family_id') or ''),
                        str(normalized.get('runtime_family_id') or ''),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    collected.append(normalized)
        lifecycle_order = {'approved': 3, 'curated': 2, 'draft': 1, 'deprecated': 0}
        collected.sort(
            key=lambda item: (
                lifecycle_order.get(str(item.get('catalog_lifecycle_state') or 'draft'), 0),
                int(item.get('catalog_version') or 0),
                float(item.get('catalog_promoted_at') or item.get('promoted_at') or item.get('created_at') or 0.0),
            ),
            reverse=True,
        )
        return self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(collected))

    def _baseline_promotion_simulation_custody_apply_catalog_version_flags(self, packs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        normalized = [dict(item or {}) for item in list(packs or []) if isinstance(item, dict)]
        latest_versions: dict[str, int] = {}
        for item in normalized:
            version_key = str(item.get('catalog_version_key') or '')
            if not version_key:
                continue
            latest_versions[version_key] = max(latest_versions.get(version_key, 0), int(item.get('catalog_version') or 0))
        for item in normalized:
            version_key = str(item.get('catalog_version_key') or '')
            item['catalog_is_latest'] = bool(version_key and int(item.get('catalog_version') or 0) == int(latest_versions.get(version_key) or 0))
        return normalized

