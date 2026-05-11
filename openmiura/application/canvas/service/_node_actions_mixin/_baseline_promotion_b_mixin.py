"""openmiura.application.canvas.service._node_actions_mixin

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


LiveCanvasService: type | None = None  # late-bound by service/__init__.py

class _LiveCanvasNodeActionsMixinBaselinePromotionB:
    """Mixin: node actions methods on LiveCanvasService."""

    def _baseline_promotion_action_share_registered_simulation_custody_routing_policy_pack(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id,
        node_id,
        action,
        actor,
        reason,
        payload,
        user_role,
        user_key,
        session_id,
        tenant_id,
        workspace_id,
        environment,
        inspected,
        scope,
        node,
        inspected_node,
        raw_node,
        node_type,
        data,
        normalized_action,
        raw_payload,
        precheck,
        promotion_id,
        latest_simulation,
    ) -> dict[str, Any]:
        promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
        builtin_packs = self._baseline_promotion_simulation_custody_builtin_policy_packs(promotion_detail)
        raw_saved_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
        raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
        normalized_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(raw_registry_packs)
        requested_pack_id = str(raw_payload.get('registry_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
        target_pack_id = str(raw_payload.get('target_pack_id') or raw_payload.get('shared_pack_id') or requested_pack_id).strip() or requested_pack_id
        registry_pack = self._resolve_baseline_promotion_simulation_custody_policy_pack(promotion_detail=promotion_detail, raw_saved_packs=raw_saved_packs, raw_registry_packs=raw_registry_packs, pack_id=requested_pack_id)
        if not registry_pack or str(registry_pack.get('source') or '') not in {'registry', 'shared_registry'}:
            result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
        else:
            shared_pack = dict(registry_pack)
            shared_pack['pack_id'] = target_pack_id
            shared_pack['source'] = 'shared_registry'
            shared_pack['shared_from_pack_id'] = str(registry_pack.get('pack_id') or '')
            shared_pack['shared_from_source'] = 'registry'
            shared_pack['created_at'] = time.time()
            shared_pack['created_by'] = str(actor or 'operator')
            shared_pack['last_used_at'] = None
            shared_pack['use_count'] = 0
            share_targets = [str(item) for item in list(raw_payload.get('share_targets') or registry_pack.get('share_targets') or []) if str(item)][:8]
            shared_pack['share_targets'] = share_targets
            shared_pack['last_shared_at'] = time.time()
            shared_pack['last_shared_by'] = str(actor or 'operator')
            updated_saved = [item for item in raw_saved_packs if str(item.get('pack_id') or '') != str(shared_pack.get('pack_id') or '')]
            if str(registry_pack.get('promoted_from_source') or '') == 'builtin':
                shared_storage_pack = {
                    'pack_id': str(shared_pack.get('pack_id') or ''),
                    'pack_label': str(shared_pack.get('pack_label') or ''),
                    'source': 'shared_registry',
                    'shared_from_pack_id': str(shared_pack.get('shared_from_pack_id') or ''),
                    'shared_from_source': str(shared_pack.get('shared_from_source') or ''),
                    'scenario_count': int(shared_pack.get('scenario_count') or 0),
                }
            else:
                shared_storage_pack = self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(shared_pack)
            updated_saved.append(shared_storage_pack)
            updated_registry = []
            for item in raw_registry_packs:
                if str(item.get('pack_id') or '') == str(registry_pack.get('pack_id') or ''):
                    registry_item = dict(item or {})
                    registry_item['source'] = 'registry'
                    registry_item['share_count'] = int(registry_item.get('share_count') or 0) + 1
                    registry_item['last_shared_at'] = shared_pack.get('last_shared_at')
                    registry_item['last_shared_by'] = str(actor or 'operator')
                    registry_item['share_targets'] = share_targets
                    updated_registry.append(registry_item)
                else:
                    updated_registry.append(dict(item or {}))
            normalized_saved = self._baseline_promotion_simulation_custody_saved_policy_packs(updated_saved)
            normalized_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)
            normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
            updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
            compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(shared_pack)
            updated_data = dict(data)
            updated_data['saved_routing_policy_packs'] = updated_saved
            updated_data['routing_policy_pack_registry'] = updated_registry
            updated_data['last_shared_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'pack_label': str(compact_pack.get('pack_label') or ''), 'source': str(compact_pack.get('source') or ''), 'shared_from_pack_id': str(compact_pack.get('shared_from_pack_id') or ''), 'shared_from_source': str(compact_pack.get('shared_from_source') or ''), 'scenario_count': int(compact_pack.get('scenario_count') or 0)}
            if latest_simulation:
                updated_data['latest_simulation'] = dict(data.get('latest_simulation') or latest_simulation)
            node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
            data = dict(node.get('data') or {})
            result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

    def _baseline_promotion_action_share_cataloged_simulation_custody_routing_policy_pack(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id,
        node_id,
        action,
        actor,
        reason,
        payload,
        user_role,
        user_key,
        session_id,
        tenant_id,
        workspace_id,
        environment,
        inspected,
        scope,
        node,
        inspected_node,
        raw_node,
        node_type,
        data,
        normalized_action,
        raw_payload,
        precheck,
        promotion_id,
        latest_simulation,
    ) -> dict[str, Any]:
        promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
        raw_saved_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
        raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
        requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
        requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
        target_pack_id = str(raw_payload.get('target_pack_id') or raw_payload.get('shared_pack_id') or requested_pack_id or requested_catalog_entry_id).strip() or requested_pack_id or requested_catalog_entry_id
        catalog_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
            gw,
            promotion_detail=promotion_detail,
            node_data=data,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            pack_id=requested_pack_id or None,
            catalog_entry_id=requested_catalog_entry_id or None,
        )
        if not catalog_pack:
            result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
        elif str(catalog_pack.get('catalog_lifecycle_state') or 'draft') == 'deprecated':
            result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_deprecated'}
        elif not self._baseline_promotion_simulation_custody_catalog_rollout_access(catalog_pack, current_context={**self._baseline_promotion_simulation_custody_catalog_context(promotion_detail=promotion_detail, node_data=data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')), 'canvas_id': canvas_id, 'node_id': node_id}).get('allowed'):
            result = {'ok': False, 'error': self._baseline_promotion_simulation_custody_catalog_rollout_access(catalog_pack, current_context={**self._baseline_promotion_simulation_custody_catalog_context(promotion_detail=promotion_detail, node_data=data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')), 'canvas_id': canvas_id, 'node_id': node_id}).get('reason') or 'catalog_rollout_target_not_released'}
        else:
            shared_pack = dict(catalog_pack)
            shared_pack['pack_id'] = target_pack_id
            shared_pack['source'] = 'shared_catalog'
            shared_pack['shared_from_pack_id'] = str(catalog_pack.get('pack_id') or '')
            shared_pack['shared_from_source'] = 'catalog'
            shared_pack['catalog_entry_id'] = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
            shared_pack['created_at'] = time.time()
            shared_pack['created_by'] = str(actor or 'operator')
            shared_pack['last_used_at'] = None
            shared_pack['use_count'] = 0
            updated_saved = [item for item in raw_saved_packs if str(item.get('pack_id') or '') != str(shared_pack.get('pack_id') or '')]
            if str(catalog_pack.get('promoted_from_source') or '') == 'builtin':
                saved_storage_pack = {
                    'pack_id': str(shared_pack.get('pack_id') or ''),
                    'pack_label': str(shared_pack.get('pack_label') or ''),
                    'source': 'shared_catalog',
                    'shared_from_pack_id': str(shared_pack.get('shared_from_pack_id') or ''),
                    'shared_from_source': str(shared_pack.get('shared_from_source') or ''),
                    'catalog_entry_id': str(shared_pack.get('catalog_entry_id') or ''),
                    'catalog_scope': str(shared_pack.get('catalog_scope') or ''),
                    'catalog_version_key': str(shared_pack.get('catalog_version_key') or ''),
                    'catalog_version': int(shared_pack.get('catalog_version') or 0),
                    'catalog_lifecycle_state': str(shared_pack.get('catalog_lifecycle_state') or 'draft'),
                    'scenario_count': int(shared_pack.get('scenario_count') or 0),
                }
            else:
                saved_storage_pack = self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(shared_pack)
            updated_saved.append(saved_storage_pack)
            target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
            updated_registry = []
            for item in raw_registry_packs:
                normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                if str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '') == target_entry_id:
                    normalized_item['catalog_share_count'] = int(normalized_item.get('catalog_share_count') or 0) + 1
                    normalized_item['catalog_last_shared_at'] = shared_pack.get('created_at')
                    normalized_item['catalog_last_shared_by'] = str(actor or 'operator')
                updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
            compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(shared_pack)
            updated_data = dict(data)
            updated_data['saved_routing_policy_packs'] = updated_saved
            updated_data['routing_policy_pack_registry'] = updated_registry
            updated_data['last_shared_catalog_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'pack_label': str(compact_pack.get('pack_label') or ''), 'source': str(compact_pack.get('source') or ''), 'shared_from_pack_id': str(compact_pack.get('shared_from_pack_id') or ''), 'shared_from_source': str(compact_pack.get('shared_from_source') or ''), 'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''), 'scenario_count': int(compact_pack.get('scenario_count') or 0)}
            if latest_simulation:
                export_state = dict(latest_simulation.get('export_state') or {})
                export_state['last_shared_catalog_routing_policy_pack'] = dict(updated_data['last_shared_catalog_routing_policy_pack'])
                updated_simulation = dict(latest_simulation)
                updated_simulation['export_state'] = export_state
                updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
            node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
            data = dict(node.get('data') or {})
            result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

    def _baseline_promotion_action_request_cataloged_simulation_custody_routing_policy_pack_review(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id,
        node_id,
        action,
        actor,
        reason,
        payload,
        user_role,
        user_key,
        session_id,
        tenant_id,
        workspace_id,
        environment,
        inspected,
        scope,
        node,
        inspected_node,
        raw_node,
        node_type,
        data,
        normalized_action,
        raw_payload,
        precheck,
        promotion_id,
        latest_simulation,
    ) -> dict[str, Any]:
        promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
        raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
        requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
        requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
        catalog_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
            gw,
            promotion_detail=promotion_detail,
            node_data=data,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            pack_id=requested_pack_id or None,
            catalog_entry_id=requested_catalog_entry_id or None,
        )
        if not catalog_pack:
            result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
        else:
            now = time.time()
            target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
            review_note = str(raw_payload.get('note') or raw_payload.get('review_note') or raw_payload.get('comment') or raw_payload.get('review_comment') or '').strip()
            review_role = str(raw_payload.get('role') or raw_payload.get('reviewer_role') or raw_payload.get('assigned_role') or '').strip()
            requested_reviewer = str(raw_payload.get('assigned_reviewer') or raw_payload.get('reviewer_id') or raw_payload.get('reviewer') or '').strip()
            review_decision_input = str(raw_payload.get('decision') or raw_payload.get('review_decision') or '').strip().lower()
            review_decision = {
                'approved': 'review_approved',
                'review_approved': 'review_approved',
                'changes_requested': 'review_changes_requested',
                'review_changes_requested': 'review_changes_requested',
                'rejected': 'review_rejected',
                'review_rejected': 'review_rejected',
            }.get(review_decision_input, '')
            current_review_state = self._baseline_promotion_simulation_custody_catalog_pack_review_state(catalog_pack)
            assigned_reviewer = str(catalog_pack.get('catalog_review_assigned_reviewer') or '')
            if normalized_action == 'claim_cataloged_simulation_custody_routing_policy_pack_review' and assigned_reviewer and assigned_reviewer != str(actor or 'operator'):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_review_assigned_to_other'}
            elif normalized_action == 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision' and not review_decision:
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_review_decision_invalid'}
            elif normalized_action in {'add_cataloged_simulation_custody_routing_policy_pack_review_note', 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision'} and current_review_state == 'not_requested':
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_review_not_requested'}
            else:
                updated_registry = []
                for item in raw_registry_packs:
                    normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                    entry_id = str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '')
                    if entry_id == target_entry_id:
                        review_events = [dict(v or {}) for v in list(normalized_item.get('catalog_review_events') or []) if isinstance(v, dict)]
                        if normalized_action == 'request_cataloged_simulation_custody_routing_policy_pack_review':
                            assigned = requested_reviewer or str(normalized_item.get('catalog_review_assigned_reviewer') or '')
                            assigned_role = review_role or str(normalized_item.get('catalog_review_assigned_role') or '')
                            normalized_item['catalog_review_state'] = 'pending_review'
                            normalized_item['catalog_review_requested_at'] = now
                            normalized_item['catalog_review_requested_by'] = str(actor or 'operator')
                            normalized_item['catalog_review_assigned_reviewer'] = assigned
                            normalized_item['catalog_review_assigned_role'] = assigned_role
                            normalized_item['catalog_review_claimed_by'] = ''
                            normalized_item['catalog_review_claimed_at'] = None
                            normalized_item['catalog_review_decision'] = ''
                            normalized_item['catalog_review_decision_at'] = None
                            normalized_item['catalog_review_decision_by'] = ''
                            normalized_item['catalog_review_latest_note'] = review_note or str(normalized_item.get('catalog_review_latest_note') or '')
                            event = self._baseline_promotion_simulation_custody_catalog_pack_review_event(
                                event_type='request_review',
                                state='pending_review',
                                actor=str(actor or 'operator'),
                                at=now,
                                role=assigned_role,
                                note=review_note,
                                assigned_reviewer=assigned,
                            )
                            review_events.append(event)
                        elif normalized_action == 'claim_cataloged_simulation_custody_routing_policy_pack_review':
                            normalized_item['catalog_review_state'] = 'in_review'
                            normalized_item['catalog_review_claimed_by'] = str(actor or 'operator')
                            normalized_item['catalog_review_claimed_at'] = now
                            normalized_item['catalog_review_assigned_reviewer'] = str(actor or 'operator')
                            normalized_item['catalog_review_assigned_role'] = review_role or str(normalized_item.get('catalog_review_assigned_role') or '')
                            event = self._baseline_promotion_simulation_custody_catalog_pack_review_event(
                                event_type='claim_review',
                                state='in_review',
                                actor=str(actor or 'operator'),
                                at=now,
                                role=str(normalized_item.get('catalog_review_assigned_role') or review_role or ''),
                                note=review_note,
                                assigned_reviewer=str(actor or 'operator'),
                            )
                            review_events.append(event)
                        elif normalized_action == 'add_cataloged_simulation_custody_routing_policy_pack_review_note':
                            normalized_item['catalog_review_state'] = 'in_review'
                            normalized_item['catalog_review_claimed_by'] = str(normalized_item.get('catalog_review_claimed_by') or actor or 'operator')
                            normalized_item['catalog_review_claimed_at'] = normalized_item.get('catalog_review_claimed_at') or now
                            if not str(normalized_item.get('catalog_review_assigned_reviewer') or '').strip():
                                normalized_item['catalog_review_assigned_reviewer'] = str(actor or 'operator')
                            if review_role and not str(normalized_item.get('catalog_review_assigned_role') or '').strip():
                                normalized_item['catalog_review_assigned_role'] = review_role
                            normalized_item['catalog_review_latest_note'] = review_note
                            event = self._baseline_promotion_simulation_custody_catalog_pack_review_event(
                                event_type='add_review_note',
                                state='in_review',
                                actor=str(actor or 'operator'),
                                at=now,
                                role=review_role or str(normalized_item.get('catalog_review_assigned_role') or ''),
                                note=review_note,
                                assigned_reviewer=str(normalized_item.get('catalog_review_assigned_reviewer') or ''),
                            )
                            review_events.append(event)
                        else:
                            normalized_item['catalog_review_state'] = review_decision
                            normalized_item['catalog_review_claimed_by'] = str(normalized_item.get('catalog_review_claimed_by') or actor or 'operator')
                            normalized_item['catalog_review_claimed_at'] = normalized_item.get('catalog_review_claimed_at') or now
                            if not str(normalized_item.get('catalog_review_assigned_reviewer') or '').strip():
                                normalized_item['catalog_review_assigned_reviewer'] = str(normalized_item.get('catalog_review_claimed_by') or actor or 'operator')
                            normalized_item['catalog_review_decision'] = review_decision
                            normalized_item['catalog_review_decision_at'] = now
                            normalized_item['catalog_review_decision_by'] = str(actor or 'operator')
                            normalized_item['catalog_review_latest_note'] = review_note or str(normalized_item.get('catalog_review_latest_note') or '')
                            event = self._baseline_promotion_simulation_custody_catalog_pack_review_event(
                                event_type='submit_review_decision',
                                state=review_decision,
                                actor=str(actor or 'operator'),
                                at=now,
                                role=review_role or str(normalized_item.get('catalog_review_assigned_role') or ''),
                                note=review_note,
                                decision=review_decision,
                                assigned_reviewer=str(normalized_item.get('catalog_review_assigned_reviewer') or ''),
                            )
                            review_events.append(event)
                        review_events = review_events[-20:]
                        normalized_item['catalog_review_events'] = review_events
                        normalized_item['catalog_review_note_count'] = len([evt for evt in review_events if str((evt or {}).get('event_type') or '') in {'add_review_note', 'submit_review_decision', 'request_review'} and str((evt or {}).get('note') or '').strip()])
                        normalized_item['catalog_review_timeline'] = review_events[-5:]
                        normalized_item['catalog_review_last_transition_at'] = now
                        normalized_item['catalog_review_last_transition_by'] = str(actor or 'operator')
                        normalized_item['catalog_review_last_transition_action'] = {
                            'request_cataloged_simulation_custody_routing_policy_pack_review': 'request_review',
                            'claim_cataloged_simulation_custody_routing_policy_pack_review': 'claim_review',
                            'add_cataloged_simulation_custody_routing_policy_pack_review_note': 'add_review_note',
                            'submit_cataloged_simulation_custody_routing_policy_pack_review_decision': 'submit_review_decision',
                        }.get(normalized_action, '')
                    updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                updated_catalog_pack = next((item for item in normalized_updated_registry if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id), dict(catalog_pack))
                compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(updated_catalog_pack)
                if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report':
                    compact_pack['catalog_compliance_report_count'] = max(1, int(compact_pack.get('catalog_compliance_report_count') or 0))
                    compact_pack['catalog_latest_compliance_report'] = self._compact_baseline_promotion_simulation_export_report({
                        **dict(export_result.get('report') or {}),
                        'integrity': dict(export_result.get('integrity') or {}),
                    })
                elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report':
                    compact_pack['catalog_analytics_report_count'] = max(1, int(compact_pack.get('catalog_analytics_report_count') or 0))
                    compact_pack['catalog_latest_analytics_report'] = self._compact_baseline_promotion_simulation_export_report({
                        **dict(export_result.get('report') or {}),
                        'integrity': dict(export_result.get('integrity') or {}),
                    })
                updated_data = dict(data)
                updated_data['routing_policy_pack_registry'] = updated_registry
                updated_data['last_catalog_review_transition_routing_policy_pack'] = {
                    'pack_id': str(compact_pack.get('pack_id') or ''),
                    'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''),
                    'catalog_review_state': str(compact_pack.get('catalog_review_state') or ''),
                    'catalog_review_assigned_reviewer': str(compact_pack.get('catalog_review_assigned_reviewer') or ''),
                    'catalog_review_claimed_by': str(compact_pack.get('catalog_review_claimed_by') or ''),
                    'catalog_review_decision': str(compact_pack.get('catalog_review_decision') or ''),
                    'catalog_review_note_count': int(compact_pack.get('catalog_review_note_count') or 0),
                    'at': now,
                    'by': str(actor or 'operator'),
                }
                if latest_simulation:
                    export_state = dict(latest_simulation.get('export_state') or {})
                    export_state['last_catalog_review_transition_routing_policy_pack'] = dict(updated_data['last_catalog_review_transition_routing_policy_pack'])
                    updated_simulation = dict(latest_simulation)
                    export_state['routing_policy_pack_catalog_summary'] = self._baseline_promotion_simulation_custody_catalog_summary(normalized_updated_registry)
                    updated_simulation['export_state'] = export_state
                    updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                data = dict(node.get('data') or {})
                result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

    def _baseline_promotion_action_request_cataloged_simulation_custody_routing_policy_pack_approval(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id,
        node_id,
        action,
        actor,
        reason,
        payload,
        user_role,
        user_key,
        session_id,
        tenant_id,
        workspace_id,
        environment,
        inspected,
        scope,
        node,
        inspected_node,
        raw_node,
        node_type,
        data,
        normalized_action,
        raw_payload,
        precheck,
        promotion_id,
        latest_simulation,
    ) -> dict[str, Any]:
        promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
        raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
        requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
        requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
        catalog_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
            gw,
            promotion_detail=promotion_detail,
            node_data=data,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            pack_id=requested_pack_id or None,
            catalog_entry_id=requested_catalog_entry_id or None,
        )
        if not catalog_pack:
            result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
        else:
            now = time.time()
            target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
            version_key = str(catalog_pack.get('catalog_version_key') or '')
            target_version = int(catalog_pack.get('catalog_version') or 0)
            target_scope_key = str(catalog_pack.get('catalog_scope_key') or '')
            approval_note = str(raw_payload.get('note') or raw_payload.get('reason') or '').strip()
            approval_role = str(raw_payload.get('role') or raw_payload.get('requested_role') or '').strip()
            rollout_summary = self._baseline_promotion_simulation_custody_catalog_rollout_summary(catalog_pack)
            current_catalog_context = self._baseline_promotion_simulation_custody_catalog_context(
                promotion_detail=promotion_detail,
                node_data=data,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            catalog_packs_context = self._baseline_promotion_simulation_custody_catalog_policy_packs(
                gw,
                promotion_detail=promotion_detail,
                node_data=data,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            stage_guard = self._baseline_promotion_simulation_custody_catalog_release_guard(catalog_pack, catalog_packs=catalog_packs_context, action='stage')
            release_guard = self._baseline_promotion_simulation_custody_catalog_release_guard(catalog_pack, catalog_packs=catalog_packs_context, action='release')
            if normalized_action == 'stage_cataloged_simulation_custody_routing_policy_pack_release' and not bool(stage_guard.get('passed')) and str(stage_guard.get('reason') or ''):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_blocked', 'guard_evaluation': stage_guard}
            elif normalized_action == 'stage_cataloged_simulation_custody_routing_policy_pack_release' and not self._baseline_promotion_simulation_custody_catalog_pack_release_ready(catalog_pack):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_not_ready'}
            elif normalized_action == 'stage_cataloged_simulation_custody_routing_policy_pack_release' and not bool(stage_guard.get('passed')):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_blocked', 'guard_evaluation': stage_guard}
            elif normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack' and not bool(release_guard.get('passed')) and str(release_guard.get('reason') or ''):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_blocked', 'guard_evaluation': release_guard}
            elif normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack' and not self._baseline_promotion_simulation_custody_catalog_pack_release_ready(catalog_pack):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_not_ready'}
            elif normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack' and not bool(release_guard.get('passed')):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_blocked', 'guard_evaluation': release_guard}
            elif normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack' and str(catalog_pack.get('catalog_release_state') or 'draft') not in {'staged', 'released', 'rolling_out'}:
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_not_staged'}
            elif normalized_action == 'advance_cataloged_simulation_custody_routing_policy_pack_rollout' and not bool(rollout_summary.get('enabled')):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing'}
            elif normalized_action == 'advance_cataloged_simulation_custody_routing_policy_pack_rollout' and str(rollout_summary.get('state') or '') != 'rolling_out':
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_active'}
            elif normalized_action == 'advance_cataloged_simulation_custody_routing_policy_pack_rollout' and not self._baseline_promotion_simulation_custody_catalog_rollout_gate(catalog_pack, catalog_packs=catalog_packs_context).get('passed'):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_gate_failed', 'gate_evaluation': self._baseline_promotion_simulation_custody_catalog_rollout_gate(catalog_pack, catalog_packs=catalog_packs_context)}
            elif normalized_action == 'pause_cataloged_simulation_custody_routing_policy_pack_rollout' and str(rollout_summary.get('state') or '') != 'rolling_out':
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_active'}
            elif normalized_action == 'resume_cataloged_simulation_custody_routing_policy_pack_rollout' and not bool(catalog_pack.get('catalog_rollout_paused', False)):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_paused'}
            elif normalized_action == 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout' and not bool(rollout_summary.get('enabled')):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing'}
            elif normalized_action == 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout' and not bool(catalog_pack.get('catalog_rollout_frozen', False)):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_frozen'}
            elif normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout' and not bool(rollout_summary.get('enabled')):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing'}
            elif normalized_action == 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release' and str(catalog_pack.get('catalog_release_state') or 'draft') not in {'staged', 'rolling_out', 'released'}:
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_not_active'}
            elif normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_release' and not self._baseline_promotion_simulation_custody_catalog_previous_restore_candidate(catalog_pack, catalog_packs=catalog_packs_context):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_rollback_target_missing'}
            else:
                updated_registry = []
                for item in raw_registry_packs:
                    normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                    entry_id = str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '')
                    if entry_id == target_entry_id:
                        approvals = [dict(v or {}) for v in list(normalized_item.get('catalog_approvals') or []) if isinstance(v, dict)]
                        approval_required = bool(normalized_item.get('catalog_approval_required', False))
                        required_approvals = max(0, int(normalized_item.get('catalog_required_approvals') or 0))
                        if normalized_action == 'request_cataloged_simulation_custody_routing_policy_pack_approval':
                            approval_required = bool(raw_payload.get('catalog_approval_required', True if required_approvals <= 0 else approval_required))
                            required_approvals = max(0, int(raw_payload.get('catalog_required_approvals') or required_approvals or (1 if approval_required else 0)))
                            normalized_item['catalog_approval_required'] = approval_required
                            normalized_item['catalog_required_approvals'] = required_approvals
                            normalized_item['catalog_approval_state'] = 'pending' if approval_required and required_approvals > 0 else 'not_required'
                            normalized_item['catalog_approval_requested_at'] = now
                            normalized_item['catalog_approval_requested_by'] = str(actor or 'operator')
                            normalized_item['catalog_approval_rejected_at'] = None
                            normalized_item['catalog_approval_rejected_by'] = ''
                            if approval_note or approval_role:
                                approvals.append({'approval_id': f'approval_request_{int(now)}', 'decision': 'requested', 'actor': str(actor or 'operator'), 'role': approval_role, 'at': now, 'note': approval_note})
                        elif normalized_action == 'reject_cataloged_simulation_custody_routing_policy_pack_approval':
                            normalized_item['catalog_approval_state'] = 'rejected'
                            normalized_item['catalog_approval_rejected_at'] = now
                            normalized_item['catalog_approval_rejected_by'] = str(actor or 'operator')
                            approvals.append({'approval_id': f'approval_reject_{int(now)}', 'decision': 'rejected', 'actor': str(actor or 'operator'), 'role': approval_role, 'at': now, 'note': approval_note})
                        elif normalized_action == 'curate_cataloged_simulation_custody_routing_policy_pack':
                            normalized_item['catalog_lifecycle_state'] = 'curated'
                            normalized_item['catalog_curated_at'] = now
                            normalized_item['catalog_curated_by'] = str(actor or 'operator')
                        elif normalized_action == 'approve_cataloged_simulation_custody_routing_policy_pack':
                            if approval_required and required_approvals <= 0:
                                required_approvals = 1
                                normalized_item['catalog_required_approvals'] = 1
                            existing_approved_count = max(0, int(normalized_item.get('catalog_approval_count') or 0))
                            appended_approval = False
                            if not any(str(approval.get('actor') or '') == str(actor or 'operator') and str(approval.get('decision') or '') == 'approved' for approval in approvals):
                                approvals.append({'approval_id': f'approval_{int(now)}_{len(approvals)+1}', 'decision': 'approved', 'actor': str(actor or 'operator'), 'role': approval_role, 'at': now, 'note': approval_note})
                                appended_approval = True
                            approved_count = len([approval for approval in approvals if str(approval.get('decision') or '') == 'approved'])
                            approved_count = max(approved_count, existing_approved_count + (1 if appended_approval else 0))
                            normalized_item['catalog_approval_count'] = approved_count
                            normalized_item['catalog_approval_rejected_at'] = None
                            normalized_item['catalog_approval_rejected_by'] = ''
                            if approval_required and required_approvals > 0 and approved_count < required_approvals:
                                normalized_item['catalog_approval_state'] = 'pending'
                                normalized_item['catalog_lifecycle_state'] = 'curated' if str(normalized_item.get('catalog_lifecycle_state') or 'draft') == 'draft' else str(normalized_item.get('catalog_lifecycle_state') or 'curated')
                                normalized_item['catalog_curated_at'] = normalized_item.get('catalog_curated_at') or now
                                normalized_item['catalog_curated_by'] = str(normalized_item.get('catalog_curated_by') or actor or 'operator')
                            else:
                                normalized_item['catalog_approval_state'] = 'approved' if approval_required and required_approvals > 0 else 'not_required'
                                normalized_item['catalog_lifecycle_state'] = 'approved'
                                normalized_item['catalog_curated_at'] = normalized_item.get('catalog_curated_at') or now
                                normalized_item['catalog_curated_by'] = str(normalized_item.get('catalog_curated_by') or actor or 'operator')
                                normalized_item['catalog_approved_at'] = now
                                normalized_item['catalog_approved_by'] = str(actor or 'operator')
                                normalized_item['catalog_deprecated_at'] = None
                                normalized_item['catalog_deprecated_by'] = ''
                                normalized_item['catalog_replaced_by_version'] = 0
                        elif normalized_action == 'deprecate_cataloged_simulation_custody_routing_policy_pack':
                            normalized_item['catalog_lifecycle_state'] = 'deprecated'
                            normalized_item['catalog_deprecated_at'] = now
                            normalized_item['catalog_deprecated_by'] = str(actor or 'operator')
                        elif normalized_action == 'stage_cataloged_simulation_custody_routing_policy_pack_release':
                            rollout_policy = self._baseline_promotion_simulation_custody_catalog_rollout_policy(raw_payload.get('catalog_rollout_policy') or normalized_item.get('catalog_rollout_policy') or {})
                            normalized_item['catalog_release_state'] = 'staged'
                            normalized_item['catalog_release_notes'] = str(raw_payload.get('catalog_release_notes') or normalized_item.get('catalog_release_notes') or '')
                            normalized_item['catalog_release_train_id'] = str(raw_payload.get('catalog_release_train_id') or normalized_item.get('catalog_release_train_id') or '')
                            normalized_item['catalog_release_staged_at'] = now
                            normalized_item['catalog_release_staged_by'] = str(actor or 'operator')
                            normalized_item['catalog_rollout_policy'] = rollout_policy
                            normalized_item['catalog_rollout_enabled'] = bool(rollout_policy.get('enabled'))
                            if bool(rollout_policy.get('enabled')):
                                targets = self._baseline_promotion_simulation_custody_catalog_rollout_targets(gw, pack=normalized_item, current_context=current_catalog_context)
                                waves = self._baseline_promotion_simulation_custody_catalog_rollout_waves(targets, wave_size=int(rollout_policy.get('wave_size') or 1), existing_waves=normalized_item.get('catalog_rollout_waves') or [])
                                normalized_item['catalog_rollout_targets'] = targets
                                normalized_item['catalog_rollout_waves'] = waves
                                normalized_item['catalog_rollout_train_id'] = str(raw_payload.get('catalog_rollout_train_id') or normalized_item.get('catalog_rollout_train_id') or normalized_item.get('catalog_release_train_id') or f'rollout-{target_entry_id[:12]}')
                                normalized_item['catalog_rollout_state'] = 'staged'
                                normalized_item['catalog_rollout_current_wave_index'] = 0
                                normalized_item['catalog_rollout_completed_wave_count'] = 0
                                normalized_item['catalog_rollout_paused'] = False
                                normalized_item['catalog_rollout_frozen'] = False
                        elif normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack':
                            rollout_policy = self._baseline_promotion_simulation_custody_catalog_rollout_policy(raw_payload.get('catalog_rollout_policy') or normalized_item.get('catalog_rollout_policy') or {})
                            normalized_item['catalog_release_notes'] = str(raw_payload.get('catalog_release_notes') or normalized_item.get('catalog_release_notes') or '')
                            normalized_item['catalog_release_train_id'] = str(raw_payload.get('catalog_release_train_id') or normalized_item.get('catalog_release_train_id') or '')
                            normalized_item['catalog_released_at'] = now
                            normalized_item['catalog_released_by'] = str(actor or 'operator')
                            normalized_item['catalog_release_staged_at'] = normalized_item.get('catalog_release_staged_at') or now
                            normalized_item['catalog_release_staged_by'] = str(normalized_item.get('catalog_release_staged_by') or actor or 'operator')
                            normalized_item['catalog_withdrawn_at'] = None
                            normalized_item['catalog_withdrawn_by'] = ''
                            normalized_item['catalog_withdrawn_reason'] = ''
                            normalized_item['catalog_emergency_withdrawal_active'] = False
                            normalized_item['catalog_emergency_withdrawal_at'] = None
                            normalized_item['catalog_emergency_withdrawal_by'] = ''
                            normalized_item['catalog_emergency_withdrawal_reason'] = ''
                            normalized_item['catalog_emergency_withdrawal_incident_id'] = ''
                            normalized_item['catalog_emergency_withdrawal_severity'] = ''
                            normalized_item['catalog_rollback_release_state'] = ''
                            normalized_item['catalog_rollback_release_at'] = None
                            normalized_item['catalog_rollback_release_by'] = ''
                            normalized_item['catalog_rollback_release_reason'] = ''
                            normalized_item['catalog_rollback_target_entry_id'] = ''
                            normalized_item['catalog_rollback_target_version'] = 0
                            normalized_item['catalog_restored_from_entry_id'] = ''
                            normalized_item['catalog_restored_from_version'] = 0
                            normalized_item['catalog_restored_at'] = None
                            normalized_item['catalog_restored_by'] = ''
                            normalized_item['catalog_restored_reason'] = ''
                            normalized_item['catalog_rollout_policy'] = rollout_policy
                            previous_release = next((dict(item or {}) for item in list(catalog_packs_context or []) if isinstance(item, dict) and str(item.get('catalog_version_key') or '') == version_key and str(item.get('catalog_scope_key') or '') == target_scope_key and str(item.get('catalog_release_state') or '') in {'released', 'rolling_out'} and str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') != target_entry_id), {})
                            normalized_item['catalog_supersedes_entry_id'] = str(previous_release.get('catalog_entry_id') or previous_release.get('registry_entry_id') or '')
                            normalized_item['catalog_supersedes_version'] = int(previous_release.get('catalog_version') or 0)
                            normalized_item['catalog_rollout_enabled'] = bool(rollout_policy.get('enabled'))
                            if bool(rollout_policy.get('enabled')):
                                targets = self._baseline_promotion_simulation_custody_catalog_rollout_targets(gw, pack=normalized_item, current_context=current_catalog_context)
                                waves = self._baseline_promotion_simulation_custody_catalog_rollout_waves(targets, wave_size=int(rollout_policy.get('wave_size') or 1), existing_waves=normalized_item.get('catalog_rollout_waves') or [])
                                normalized_item['catalog_rollout_targets'] = targets
                                normalized_item['catalog_rollout_waves'] = waves
                                normalized_item['catalog_rollout_train_id'] = str(raw_payload.get('catalog_rollout_train_id') or normalized_item.get('catalog_rollout_train_id') or normalized_item.get('catalog_release_train_id') or f'rollout-{target_entry_id[:12]}')
                                normalized_item['catalog_rollout_started_at'] = normalized_item.get('catalog_rollout_started_at') or now
                                normalized_item['catalog_rollout_started_by'] = str(normalized_item.get('catalog_rollout_started_by') or actor or 'operator')
                                normalized_item['catalog_rollout_paused'] = False
                                normalized_item['catalog_rollout_frozen'] = False
                                if waves:
                                    normalized_item = self._baseline_promotion_simulation_custody_catalog_rollout_activate_wave(normalized_item, wave_index=1, actor=str(actor or 'operator'), at=now)
                                    if len(waves) == 1:
                                        normalized_item['catalog_rollout_waves'][0]['status'] = 'completed'
                                        normalized_item['catalog_rollout_completed_wave_count'] = 1
                                        normalized_item['catalog_rollout_state'] = 'completed'
                                        normalized_item['catalog_release_state'] = 'released'
                                        normalized_item['catalog_rollout_completed_at'] = now
                                        normalized_item['catalog_rollout_completed_by'] = str(actor or 'operator')
                                    else:
                                        normalized_item['catalog_rollout_state'] = 'rolling_out'
                                        normalized_item['catalog_release_state'] = 'rolling_out'
                                else:
                                    normalized_item['catalog_rollout_state'] = 'completed'
                                    normalized_item['catalog_release_state'] = 'released'
                                    normalized_item['catalog_rollout_completed_at'] = now
                                    normalized_item['catalog_rollout_completed_by'] = str(actor or 'operator')
                            else:
                                normalized_item['catalog_release_state'] = 'released'
                        elif normalized_action == 'advance_cataloged_simulation_custody_routing_policy_pack_rollout':
                            waves = [dict(v or {}) for v in list(normalized_item.get('catalog_rollout_waves') or []) if isinstance(v, dict)]
                            current_wave_index = int(normalized_item.get('catalog_rollout_current_wave_index') or 0)
                            gate = self._baseline_promotion_simulation_custody_catalog_rollout_gate(normalized_item, wave_index=current_wave_index, catalog_packs=catalog_packs_context)
                            normalized_item['catalog_rollout_latest_gate'] = gate
                            for wave in waves:
                                if int(wave.get('wave_index') or 0) == current_wave_index:
                                    wave['status'] = 'completed'
                                    wave['gate_evaluation'] = dict(gate)
                            normalized_item['catalog_rollout_waves'] = waves
                            normalized_item['catalog_rollout_completed_wave_count'] = len([wave for wave in waves if str(wave.get('status') or '') == 'completed'])
                            next_wave_index = current_wave_index + 1
                            if next_wave_index <= len(waves):
                                normalized_item = self._baseline_promotion_simulation_custody_catalog_rollout_activate_wave(normalized_item, wave_index=next_wave_index, actor=str(actor or 'operator'), at=now)
                                normalized_item['catalog_rollout_state'] = 'rolling_out'
                                normalized_item['catalog_release_state'] = 'rolling_out'
                            else:
                                normalized_item['catalog_rollout_state'] = 'completed'
                                normalized_item['catalog_release_state'] = 'released'
                                normalized_item['catalog_rollout_completed_at'] = now
                                normalized_item['catalog_rollout_completed_by'] = str(actor or 'operator')
                        elif normalized_action == 'pause_cataloged_simulation_custody_routing_policy_pack_rollout':
                            normalized_item['catalog_rollout_paused'] = True
                            normalized_item['catalog_rollout_state'] = 'paused'
                        elif normalized_action == 'resume_cataloged_simulation_custody_routing_policy_pack_rollout':
                            normalized_item['catalog_rollout_paused'] = False
                            normalized_item['catalog_rollout_state'] = 'rolling_out'
                        elif normalized_action == 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout':
                            normalized_item['catalog_rollout_frozen'] = True
                        elif normalized_action == 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout':
                            normalized_item['catalog_rollout_frozen'] = False
                        elif normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout':
                            normalized_item['catalog_rollout_state'] = 'rolled_back'
                            normalized_item['catalog_rollout_rolled_back_at'] = now
                            normalized_item['catalog_rollout_rolled_back_by'] = str(actor or 'operator')
                            normalized_item['catalog_rollout_rolled_back_reason'] = str(raw_payload.get('catalog_rollout_rolled_back_reason') or approval_note or 'manual_rollback')
                            normalized_item['catalog_release_state'] = 'withdrawn'
                            normalized_item['catalog_withdrawn_at'] = now
                            normalized_item['catalog_withdrawn_by'] = str(actor or 'operator')
                            normalized_item['catalog_withdrawn_reason'] = str(raw_payload.get('catalog_withdrawn_reason') or normalized_item.get('catalog_rollout_rolled_back_reason') or '')
                        elif normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_release':
                            rollback_target = self._baseline_promotion_simulation_custody_catalog_previous_restore_candidate(normalized_item, catalog_packs=catalog_packs_context)
                            normalized_item['catalog_release_state'] = 'withdrawn'
                            normalized_item['catalog_withdrawn_at'] = now
                            normalized_item['catalog_withdrawn_by'] = str(actor or 'operator')
                            normalized_item['catalog_withdrawn_reason'] = str(raw_payload.get('catalog_withdrawn_reason') or raw_payload.get('catalog_rollback_release_reason') or 'rollback_to_previous_release')
                            normalized_item['catalog_rollback_release_state'] = 'rolled_back_to_previous_release' if rollback_target else 'rolled_back_without_restore'
                            normalized_item['catalog_rollback_release_at'] = now
                            normalized_item['catalog_rollback_release_by'] = str(actor or 'operator')
                            normalized_item['catalog_rollback_release_reason'] = str(raw_payload.get('catalog_rollback_release_reason') or normalized_item.get('catalog_withdrawn_reason') or 'rollback_to_previous_release')
                            normalized_item['catalog_rollback_target_entry_id'] = str((rollback_target or {}).get('catalog_entry_id') or '')
                            normalized_item['catalog_rollback_target_version'] = int((rollback_target or {}).get('catalog_version') or 0)
                            if bool(normalized_item.get('catalog_rollout_enabled', False)):
                                normalized_item['catalog_rollout_state'] = 'rolled_back'
                                normalized_item['catalog_rollout_rolled_back_at'] = now
                                normalized_item['catalog_rollout_rolled_back_by'] = str(actor or 'operator')
                                normalized_item['catalog_rollout_rolled_back_reason'] = str(normalized_item.get('catalog_rollback_release_reason') or 'release_rollback')
                        elif normalized_action == 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release':
                            normalized_item['catalog_release_state'] = 'withdrawn'
                            normalized_item['catalog_withdrawn_at'] = now
                            normalized_item['catalog_withdrawn_by'] = str(actor or 'operator')
                            normalized_item['catalog_withdrawn_reason'] = str(raw_payload.get('catalog_withdrawn_reason') or raw_payload.get('catalog_emergency_withdrawal_reason') or approval_note or 'emergency_withdrawal')
                            normalized_item['catalog_emergency_withdrawal_active'] = True
                            normalized_item['catalog_emergency_withdrawal_at'] = now
                            normalized_item['catalog_emergency_withdrawal_by'] = str(actor or 'operator')
                            normalized_item['catalog_emergency_withdrawal_reason'] = str(raw_payload.get('catalog_emergency_withdrawal_reason') or normalized_item.get('catalog_withdrawn_reason') or 'emergency_withdrawal')
                            normalized_item['catalog_emergency_withdrawal_incident_id'] = str(raw_payload.get('incident_id') or raw_payload.get('catalog_emergency_withdrawal_incident_id') or '')
                            normalized_item['catalog_emergency_withdrawal_severity'] = str(raw_payload.get('severity') or raw_payload.get('catalog_emergency_withdrawal_severity') or 'high')
                            if bool(normalized_item.get('catalog_rollout_enabled', False)):
                                normalized_item['catalog_rollout_state'] = 'rolled_back'
                                normalized_item['catalog_rollout_rolled_back_at'] = now
                                normalized_item['catalog_rollout_rolled_back_by'] = str(actor or 'operator')
                                normalized_item['catalog_rollout_rolled_back_reason'] = str(normalized_item.get('catalog_emergency_withdrawal_reason') or 'emergency_withdrawal')
                        else:
                            normalized_item['catalog_release_state'] = 'withdrawn'
                            normalized_item['catalog_withdrawn_at'] = now
                            normalized_item['catalog_withdrawn_by'] = str(actor or 'operator')
                            normalized_item['catalog_withdrawn_reason'] = str(raw_payload.get('catalog_withdrawn_reason') or approval_note or normalized_item.get('catalog_withdrawn_reason') or '')
                            if bool(normalized_item.get('catalog_rollout_enabled', False)):
                                normalized_item['catalog_rollout_state'] = 'rolled_back'
                                normalized_item['catalog_rollout_rolled_back_at'] = now
                                normalized_item['catalog_rollout_rolled_back_by'] = str(actor or 'operator')
                                normalized_item['catalog_rollout_rolled_back_reason'] = str(normalized_item.get('catalog_withdrawn_reason') or 'release_withdrawn')
                        normalized_item['catalog_rollout_last_transition_at'] = now
                        normalized_item['catalog_rollout_last_transition_by'] = str(actor or 'operator')
                        normalized_item['catalog_rollout_last_transition_action'] = normalized_action
                        normalized_item['catalog_approvals'] = approvals[:12]
                        if not normalized_item.get('catalog_approval_count'):
                            normalized_item['catalog_approval_count'] = len([approval for approval in approvals if str(approval.get('decision') or '') == 'approved'])
                        updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                        continue
                    if normalized_action == 'approve_cataloged_simulation_custody_routing_policy_pack' and version_key and str(normalized_item.get('catalog_version_key') or '') == version_key and str(normalized_item.get('catalog_lifecycle_state') or '') == 'approved':
                        normalized_item['catalog_lifecycle_state'] = 'deprecated'
                        normalized_item['catalog_deprecated_at'] = now
                        normalized_item['catalog_deprecated_by'] = str(actor or 'operator')
                        normalized_item['catalog_replaced_by_version'] = target_version
                    if normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack' and version_key and target_scope_key and str(normalized_item.get('catalog_version_key') or '') == version_key and str(normalized_item.get('catalog_scope_key') or '') == target_scope_key and str(normalized_item.get('catalog_release_state') or '') in {'released', 'rolling_out'}:
                        normalized_item['catalog_release_state'] = 'withdrawn'
                        normalized_item['catalog_withdrawn_at'] = now
                        normalized_item['catalog_withdrawn_by'] = str(actor or 'operator')
                        normalized_item['catalog_withdrawn_reason'] = 'replaced_by_new_release'
                        normalized_item['catalog_supersedence_state'] = 'superseded'
                        normalized_item['catalog_superseded_at'] = now
                        normalized_item['catalog_superseded_by'] = str(actor or 'operator')
                        normalized_item['catalog_superseded_reason'] = 'replaced_by_new_release'
                        normalized_item['catalog_superseded_by_entry_id'] = target_entry_id
                        normalized_item['catalog_superseded_by_version'] = target_version
                        if bool(normalized_item.get('catalog_rollout_enabled', False)):
                            normalized_item['catalog_rollout_state'] = 'rolled_back'
                            normalized_item['catalog_rollout_rolled_back_at'] = now
                            normalized_item['catalog_rollout_rolled_back_by'] = str(actor or 'operator')
                            normalized_item['catalog_rollout_rolled_back_reason'] = 'replaced_by_new_release'
                    if normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_release' and version_key and target_scope_key and str(normalized_item.get('catalog_version_key') or '') == version_key and str(normalized_item.get('catalog_scope_key') or '') == target_scope_key and str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '') == str((self._baseline_promotion_simulation_custody_catalog_previous_restore_candidate(catalog_pack, catalog_packs=catalog_packs_context) or {}).get('catalog_entry_id') or ''):
                        normalized_item['catalog_release_state'] = 'released'
                        normalized_item['catalog_lifecycle_state'] = 'approved'
                        normalized_item['catalog_deprecated_at'] = None
                        normalized_item['catalog_deprecated_by'] = ''
                        normalized_item['catalog_replaced_by_version'] = 0
                        normalized_item['catalog_withdrawn_at'] = None
                        normalized_item['catalog_withdrawn_by'] = ''
                        normalized_item['catalog_withdrawn_reason'] = ''
                        normalized_item['catalog_restored_from_entry_id'] = target_entry_id
                        normalized_item['catalog_restored_from_version'] = target_version
                        normalized_item['catalog_restored_at'] = now
                        normalized_item['catalog_restored_by'] = str(actor or 'operator')
                        normalized_item['catalog_restored_reason'] = str(raw_payload.get('catalog_rollback_release_reason') or 'release_rollback_restore')
                        normalized_item['catalog_emergency_withdrawal_active'] = False
                        normalized_item['catalog_emergency_withdrawal_at'] = None
                        normalized_item['catalog_emergency_withdrawal_by'] = ''
                        normalized_item['catalog_emergency_withdrawal_reason'] = ''
                        normalized_item['catalog_emergency_withdrawal_incident_id'] = ''
                        normalized_item['catalog_emergency_withdrawal_severity'] = ''
                        normalized_item['catalog_supersedence_state'] = ''
                        normalized_item['catalog_superseded_at'] = None
                        normalized_item['catalog_superseded_by'] = ''
                        normalized_item['catalog_superseded_reason'] = ''
                        normalized_item['catalog_superseded_by_entry_id'] = ''
                        normalized_item['catalog_superseded_by_version'] = 0
                        normalized_item['catalog_superseded_by_bundle_id'] = ''
                        if bool(normalized_item.get('catalog_rollout_enabled', False)):
                            normalized_item['catalog_rollout_state'] = 'completed'
                            normalized_item['catalog_rollout_completed_at'] = now
                            normalized_item['catalog_rollout_completed_by'] = str(actor or 'operator')
                    updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                updated_catalog_pack = next((item for item in normalized_updated_registry if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id), dict(catalog_pack))
                compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(updated_catalog_pack)
                if normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_release':
                    rollback_target = self._baseline_promotion_simulation_custody_catalog_previous_restore_candidate(catalog_pack, catalog_packs=catalog_packs_context)
                    if rollback_target:
                        self._baseline_promotion_simulation_custody_rebind_catalog_bindings(
                            gw,
                            from_pack=updated_catalog_pack,
                            to_pack=rollback_target,
                            actor=str(actor or 'operator'),
                            tenant_id=scope.get('tenant_id'),
                            reason=str(raw_payload.get('catalog_rollback_release_reason') or 'release_rollback_restore'),
                        )
                if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report':
                    compact_pack['catalog_compliance_report_count'] = max(1, int(compact_pack.get('catalog_compliance_report_count') or 0))
                    compact_pack['catalog_latest_compliance_report'] = self._compact_baseline_promotion_simulation_export_report({
                        **dict(export_result.get('report') or {}),
                        'integrity': dict(export_result.get('integrity') or {}),
                    })
                elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report':
                    compact_pack['catalog_analytics_report_count'] = max(1, int(compact_pack.get('catalog_analytics_report_count') or 0))
                    compact_pack['catalog_latest_analytics_report'] = self._compact_baseline_promotion_simulation_export_report({
                        **dict(export_result.get('report') or {}),
                        'integrity': dict(export_result.get('integrity') or {}),
                    })
                updated_data = dict(data)
                updated_data['routing_policy_pack_registry'] = updated_registry
                if normalized_action in {'request_cataloged_simulation_custody_routing_policy_pack_approval', 'reject_cataloged_simulation_custody_routing_policy_pack_approval', 'approve_cataloged_simulation_custody_routing_policy_pack'}:
                    updated_data['last_catalog_approval_transition_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''), 'catalog_approval_state': str(compact_pack.get('catalog_approval_state') or ''), 'catalog_approval_count': int(compact_pack.get('catalog_approval_count') or 0), 'catalog_required_approvals': int(compact_pack.get('catalog_required_approvals') or 0), 'at': now, 'by': str(actor or 'operator')}
                elif normalized_action in {'stage_cataloged_simulation_custody_routing_policy_pack_release', 'release_cataloged_simulation_custody_routing_policy_pack', 'rollback_cataloged_simulation_custody_routing_policy_pack_release', 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release', 'withdraw_cataloged_simulation_custody_routing_policy_pack_release'}:
                    updated_data['last_catalog_release_transition_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''), 'catalog_release_state': str(compact_pack.get('catalog_release_state') or ''), 'catalog_version_key': str(compact_pack.get('catalog_version_key') or ''), 'catalog_version': int(compact_pack.get('catalog_version') or 0), 'at': now, 'by': str(actor or 'operator')}
                elif normalized_action in {'advance_cataloged_simulation_custody_routing_policy_pack_rollout', 'pause_cataloged_simulation_custody_routing_policy_pack_rollout', 'resume_cataloged_simulation_custody_routing_policy_pack_rollout', 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout'}:
                    updated_data['last_catalog_rollout_transition_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''), 'catalog_rollout_train_id': str(compact_pack.get('catalog_rollout_train_id') or ''), 'catalog_rollout_state': str(compact_pack.get('catalog_rollout_state') or ''), 'catalog_rollout_current_wave_index': int(compact_pack.get('catalog_rollout_current_wave_index') or 0), 'catalog_rollout_completed_wave_count': int(compact_pack.get('catalog_rollout_completed_wave_count') or 0), 'catalog_rollout_frozen': bool(compact_pack.get('catalog_rollout_frozen', False)), 'catalog_rollout_paused': bool(compact_pack.get('catalog_rollout_paused', False)), 'at': now, 'by': str(actor or 'operator')}
                else:
                    updated_data['last_catalog_lifecycle_transition_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'pack_label': str(compact_pack.get('pack_label') or ''), 'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''), 'catalog_version_key': str(compact_pack.get('catalog_version_key') or ''), 'catalog_version': int(compact_pack.get('catalog_version') or 0), 'catalog_lifecycle_state': str(compact_pack.get('catalog_lifecycle_state') or ''), 'at': now, 'by': str(actor or 'operator')}
                if latest_simulation:
                    export_state = dict(latest_simulation.get('export_state') or {})
                    if 'last_catalog_lifecycle_transition_routing_policy_pack' in updated_data:
                        export_state['last_catalog_lifecycle_transition_routing_policy_pack'] = dict(updated_data['last_catalog_lifecycle_transition_routing_policy_pack'])
                    if 'last_catalog_approval_transition_routing_policy_pack' in updated_data:
                        export_state['last_catalog_approval_transition_routing_policy_pack'] = dict(updated_data['last_catalog_approval_transition_routing_policy_pack'])
                    if 'last_catalog_release_transition_routing_policy_pack' in updated_data:
                        export_state['last_catalog_release_transition_routing_policy_pack'] = dict(updated_data['last_catalog_release_transition_routing_policy_pack'])
                    if 'last_catalog_rollout_transition_routing_policy_pack' in updated_data:
                        export_state['last_catalog_rollout_transition_routing_policy_pack'] = dict(updated_data['last_catalog_rollout_transition_routing_policy_pack'])
                    export_state['routing_policy_pack_catalog_summary'] = self._baseline_promotion_simulation_custody_catalog_summary(normalized_updated_registry)
                    updated_simulation = dict(latest_simulation)
                    updated_simulation['export_state'] = export_state
                    updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                data = dict(node.get('data') or {})
                result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

    def _baseline_promotion_action_export_cataloged_simulation_custody_routing_policy_pack_evidence_package(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id,
        node_id,
        action,
        actor,
        reason,
        payload,
        user_role,
        user_key,
        session_id,
        tenant_id,
        workspace_id,
        environment,
        inspected,
        scope,
        node,
        inspected_node,
        raw_node,
        node_type,
        data,
        normalized_action,
        raw_payload,
        precheck,
        promotion_id,
        latest_simulation,
    ) -> dict[str, Any]:
        promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
        requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
        requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
        catalog_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
            gw,
            promotion_detail=promotion_detail,
            node_data=data,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            pack_id=requested_pack_id or None,
            catalog_entry_id=requested_catalog_entry_id or None,
        )
        if not catalog_pack:
            result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
        elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle' and str(catalog_pack.get('catalog_release_state') or 'draft') == 'draft':
            result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_bundle_not_ready'}
        else:
            catalog_packs = self._baseline_promotion_simulation_custody_catalog_policy_packs(
                gw,
                promotion_detail=promotion_detail,
                node_data=data,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_evidence_package':
                export_result = self._build_baseline_promotion_simulation_custody_catalog_pack_evidence_package_export(
                    pack=catalog_pack,
                    actor=actor,
                    promotion_detail=promotion_detail,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    catalog_packs=catalog_packs,
                )
            elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle':
                export_result = self._build_baseline_promotion_simulation_custody_catalog_pack_signed_release_bundle_export(
                    pack=catalog_pack,
                    actor=actor,
                    promotion_detail=promotion_detail,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    catalog_packs=catalog_packs,
                )
            else:
                catalog_bindings = self._baseline_promotion_simulation_custody_catalog_policy_bindings(gw, tenant_id=scope.get('tenant_id'))
                if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report':
                    export_result = self._build_baseline_promotion_simulation_custody_catalog_pack_analytics_report_export(
                        pack=catalog_pack,
                        actor=actor,
                        promotion_detail=promotion_detail,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        node_data=data,
                        catalog_packs=catalog_packs,
                        bindings=catalog_bindings,
                    )
                else:
                    export_result = self._build_baseline_promotion_simulation_custody_catalog_pack_compliance_report_export(
                        pack=catalog_pack,
                        actor=actor,
                        promotion_detail=promotion_detail,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        node_data=data,
                        catalog_packs=catalog_packs,
                        bindings=catalog_bindings,
                    )
            if not export_result.get('ok'):
                result = export_result
            else:
                now = time.time()
                target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
                raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                updated_registry = []
                for item in raw_registry_packs:
                    normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                    entry_id = str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '')
                    if entry_id == target_entry_id:
                        if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_evidence_package':
                            normalized_item['catalog_evidence_package_count'] = int(normalized_item.get('catalog_evidence_package_count') or 0) + 1
                            normalized_item['catalog_latest_evidence_package'] = self._compact_baseline_promotion_simulation_export_report({
                                **dict(export_result.get('report') or {}),
                                'integrity': dict(export_result.get('integrity') or {}),
                            })
                        elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle':
                            normalized_item['catalog_release_bundle_count'] = int(normalized_item.get('catalog_release_bundle_count') or 0) + 1
                            normalized_item['catalog_latest_release_bundle'] = self._compact_baseline_promotion_simulation_export_report({
                                **dict(export_result.get('report') or {}),
                                'release_bundle_id': str(export_result.get('release_bundle_id') or (export_result.get('report') or {}).get('release_bundle_id') or (export_result.get('report') or {}).get('report_id') or ''),
                                'integrity': dict(export_result.get('integrity') or {}),
                            })
                        else:
                            if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report':
                                normalized_item['catalog_analytics_report_count'] = int(normalized_item.get('catalog_analytics_report_count') or 0) + 1
                                normalized_item['catalog_latest_analytics_report'] = self._compact_baseline_promotion_simulation_export_report({
                                    **dict(export_result.get('report') or {}),
                                    'integrity': dict(export_result.get('integrity') or {}),
                                })
                            else:
                                normalized_item['catalog_compliance_report_count'] = int(normalized_item.get('catalog_compliance_report_count') or 0) + 1
                                normalized_item['catalog_latest_compliance_report'] = self._compact_baseline_promotion_simulation_export_report({
                                    **dict(export_result.get('report') or {}),
                                    'integrity': dict(export_result.get('integrity') or {}),
                                })
                    updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                updated_catalog_pack = next((item for item in normalized_updated_registry if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id), dict(catalog_pack))
                compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(updated_catalog_pack)
                if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report':
                    compact_pack['catalog_compliance_report_count'] = max(1, int(compact_pack.get('catalog_compliance_report_count') or 0))
                    compact_pack['catalog_latest_compliance_report'] = self._compact_baseline_promotion_simulation_export_report({
                        **dict(export_result.get('report') or {}),
                        'integrity': dict(export_result.get('integrity') or {}),
                    })
                updated_data = dict(data)
                updated_data['routing_policy_pack_registry'] = updated_registry
                if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_evidence_package':
                    updated_data['last_catalog_evidence_package_routing_policy_pack'] = {
                        'pack_id': str(compact_pack.get('pack_id') or ''),
                        'catalog_entry_id': target_entry_id,
                        'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                        'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                        'package_id': str((export_result.get('report') or {}).get('package_id') or ''),
                        'at': now,
                        'by': str(actor or 'operator'),
                    }
                elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle':
                    updated_data['last_catalog_signed_release_bundle_routing_policy_pack'] = {
                        'pack_id': str(compact_pack.get('pack_id') or ''),
                        'catalog_entry_id': target_entry_id,
                        'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                        'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                        'release_bundle_id': str(export_result.get('release_bundle_id') or (export_result.get('report') or {}).get('release_bundle_id') or ''),
                        'at': now,
                        'by': str(actor or 'operator'),
                    }
                else:
                    if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report':
                        updated_data['last_catalog_analytics_report_routing_policy_pack'] = {
                            'pack_id': str(compact_pack.get('pack_id') or ''),
                            'catalog_entry_id': target_entry_id,
                            'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                            'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                            'overall_status': str((((export_result.get('report') or {}).get('catalog_analytics_summary')) or {}).get('overall_status') or ''),
                            'total_replay_count': int((((export_result.get('report') or {}).get('catalog_analytics_summary')) or {}).get('total_replay_count') or 0),
                            'at': now,
                            'by': str(actor or 'operator'),
                        }
                    else:
                        updated_data['last_catalog_compliance_report_routing_policy_pack'] = {
                            'pack_id': str(compact_pack.get('pack_id') or ''),
                            'catalog_entry_id': target_entry_id,
                            'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                            'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                            'overall_status': str((((export_result.get('report') or {}).get('compliance')) or {}).get('overall_status') or ''),
                            'drifted_count': int((((export_result.get('report') or {}).get('compliance_summary')) or {}).get('drifted_count') or 0),
                            'at': now,
                            'by': str(actor or 'operator'),
                        }
                node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                data = dict(node.get('data') or {})
                result = {**export_result, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

