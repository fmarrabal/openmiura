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

class _LiveCanvasNodeActionsMixinBaselinePromotionC:
    """Mixin: node actions methods on LiveCanvasService."""

    def _baseline_promotion_action_publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service(
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
        if normalized_action in {'export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot', 'reconcile_organizational_simulation_custody_routing_policy_pack_catalog_service', 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_reconciliation_report'}:
            if normalized_action == 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot':
                export_result = self._build_baseline_promotion_simulation_custody_organizational_catalog_snapshot_export(
                    gw,
                    actor=actor,
                    promotion_detail=promotion_detail,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    node_data=data,
                )
                updated_data = dict(data)
                updated_data['last_organizational_catalog_snapshot_routing_policy_pack'] = {
                    'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                    'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                    'service_id': str(((export_result.get('report') or {}).get('service') or {}).get('service_id') or ''),
                    'published_entry_count': int(((export_result.get('report') or {}).get('summary') or {}).get('published_entry_count') or 0),
                    'at': time.time(),
                    'by': str(actor or 'operator'),
                }
            else:
                export_result = self._build_baseline_promotion_simulation_custody_organizational_catalog_reconciliation_export(
                    gw,
                    actor=actor,
                    promotion_detail=promotion_detail,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    node_data=data,
                )
                updated_data = dict(data)
                updated_data['last_organizational_catalog_reconciliation_routing_policy_pack'] = {
                    'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                    'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                    'service_id': str(((export_result.get('report') or {}).get('service') or {}).get('service_id') or ''),
                    'overall_status': str((export_result.get('reconciliation_summary') or {}).get('overall_status') or ''),
                    'drifted_publication_count': int((export_result.get('reconciliation_summary') or {}).get('drifted_publication_count') or 0),
                    'healthy_publication_count': int((export_result.get('reconciliation_summary') or {}).get('healthy_publication_count') or 0),
                    'at': time.time(),
                    'by': str(actor or 'operator'),
                }
            node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
            data = dict(node.get('data') or {})
            result = {**export_result, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        else:
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
            elif normalized_action == 'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service' and (str(catalog_pack.get('catalog_lifecycle_state') or 'draft') != 'approved' or str(catalog_pack.get('catalog_release_state') or 'draft') not in {'released', 'rolling_out'}):
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_not_publishable'}
            elif normalized_action == 'withdraw_cataloged_simulation_custody_routing_policy_pack_from_organizational_catalog_service' and str(catalog_pack.get('organizational_publish_state') or '') != 'published':
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_not_published_to_organizational_catalog_service'}
            else:
                target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
                target_version = int(catalog_pack.get('catalog_version') or 0)
                organizational_visibility = str(raw_payload.get('organizational_visibility') or raw_payload.get('visibility') or catalog_pack.get('organizational_visibility') or 'tenant').strip() or 'tenant'
                service_id = self._baseline_promotion_simulation_custody_organizational_catalog_service_id(tenant_id=scope.get('tenant_id'))
                scope_key = self._baseline_promotion_simulation_custody_organizational_catalog_scope_key(
                    organizational_visibility,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                updated_registry = []
                for item in raw_registry_packs:
                    normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                    if str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '') == target_entry_id and int(normalized_item.get('catalog_version') or 0) == target_version:
                        if normalized_action == 'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service':
                            normalized_item['organizational_service_id'] = service_id
                            normalized_item['organizational_service_entry_id'] = str(normalized_item.get('organizational_service_entry_id') or self.openclaw_recovery_scheduler_service._stable_digest({'service_id': service_id, 'catalog_entry_id': target_entry_id, 'catalog_version': target_version})[:24])
                            normalized_item['organizational_publish_state'] = 'published'
                            normalized_item['organizational_visibility'] = organizational_visibility
                            normalized_item['organizational_service_scope_key'] = scope_key
                            normalized_item['organizational_published_at'] = time.time()
                            normalized_item['organizational_published_by'] = str(actor or 'operator')
                            normalized_item['organizational_withdrawn_at'] = None
                            normalized_item['organizational_withdrawn_by'] = ''
                            normalized_item['organizational_withdrawn_reason'] = ''
                            normalized_item['organizational_publication_manifest'] = self._baseline_promotion_simulation_custody_organizational_publication_manifest(
                                normalized_item,
                                tenant_id=scope.get('tenant_id'),
                                workspace_id=scope.get('workspace_id'),
                                environment=scope.get('environment'),
                            )
                        else:
                            normalized_item['organizational_publish_state'] = 'withdrawn'
                            normalized_item['organizational_withdrawn_at'] = time.time()
                            normalized_item['organizational_withdrawn_by'] = str(actor or 'operator')
                            normalized_item['organizational_withdrawn_reason'] = str(raw_payload.get('reason') or raw_payload.get('note') or 'manual_withdrawal')
                    updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                updated_catalog_pack = next((item for item in normalized_updated_registry if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id and int(item.get('catalog_version') or 0) == target_version), dict(catalog_pack))
                compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(updated_catalog_pack)
                updated_data = dict(data)
                updated_data['routing_policy_pack_registry'] = updated_registry
                if normalized_action == 'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service':
                    updated_data['last_organizational_catalog_publish_routing_policy_pack'] = {
                        'catalog_entry_id': target_entry_id,
                        'catalog_version': target_version,
                        'pack_id': str(compact_pack.get('pack_id') or ''),
                        'organizational_service_id': str(compact_pack.get('organizational_service_id') or ''),
                        'organizational_service_entry_id': str(compact_pack.get('organizational_service_entry_id') or ''),
                        'organizational_visibility': str(compact_pack.get('organizational_visibility') or ''),
                        'at': time.time(),
                        'by': str(actor or 'operator'),
                    }
                else:
                    updated_data['last_organizational_catalog_withdraw_routing_policy_pack'] = {
                        'catalog_entry_id': target_entry_id,
                        'catalog_version': target_version,
                        'pack_id': str(compact_pack.get('pack_id') or ''),
                        'organizational_service_entry_id': str(compact_pack.get('organizational_service_entry_id') or ''),
                        'organizational_publish_state': str(compact_pack.get('organizational_publish_state') or ''),
                        'at': time.time(),
                        'by': str(actor or 'operator'),
                    }
                node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                data = dict(node.get('data') or {})
                result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

    def _baseline_promotion_action_export_cataloged_simulation_custody_routing_policy_pack_attestation(
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
        else:
            export_result = self._build_baseline_promotion_simulation_custody_catalog_pack_attestation_export(
                pack=catalog_pack,
                actor=actor,
                promotion_detail=promotion_detail,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
                catalog_packs=self._baseline_promotion_simulation_custody_catalog_policy_packs(
                    gw,
                    promotion_detail=promotion_detail,
                    node_data=data,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                ),
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
                        normalized_item['catalog_attestation_count'] = int(normalized_item.get('catalog_attestation_count') or 0) + 1
                        normalized_item['catalog_latest_attestation'] = self._compact_baseline_promotion_simulation_export_report({
                            **dict(export_result.get('report') or {}),
                            'integrity': dict(export_result.get('integrity') or {}),
                        })
                    updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                updated_data = dict(data)
                updated_data['routing_policy_pack_registry'] = updated_registry
                updated_data['last_catalog_attestation_routing_policy_pack'] = {'pack_id': str(catalog_pack.get('pack_id') or ''), 'catalog_entry_id': target_entry_id, 'report_id': str((export_result.get('report') or {}).get('report_id') or ''), 'report_type': str((export_result.get('report') or {}).get('report_type') or ''), 'at': now, 'by': str(actor or 'operator')}
                if latest_simulation:
                    export_state = dict(latest_simulation.get('export_state') or {})
                    export_state['last_catalog_attestation_routing_policy_pack'] = dict(updated_data['last_catalog_attestation_routing_policy_pack'])
                    updated_simulation = dict(latest_simulation)
                    updated_simulation['export_state'] = export_state
                    updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                data = dict(node.get('data') or {})
                result = {**export_result, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

    def _baseline_promotion_action_bind_cataloged_simulation_custody_routing_policy_pack_effective_policy(
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
        raw_bindings = [dict(item or {}) for item in list(data.get('routing_policy_pack_bindings') or []) if isinstance(item, dict)]
        raw_binding_events = [dict(item or {}) for item in list(data.get('routing_policy_pack_binding_events') or []) if isinstance(item, dict)]
        current_catalog_context = self._baseline_promotion_simulation_custody_catalog_context(
            promotion_detail=promotion_detail,
            node_data=data,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
        requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
        all_catalog_packs = self._baseline_promotion_simulation_custody_catalog_policy_packs(
            gw,
            promotion_detail=promotion_detail,
            node_data=data,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        all_bindings = self._baseline_promotion_simulation_custody_catalog_policy_bindings(gw, tenant_id=scope.get('tenant_id'))
        now = time.time()
        if normalized_action == 'bind_cataloged_simulation_custody_routing_policy_pack_effective_policy':
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
            elif str(catalog_pack.get('catalog_lifecycle_state') or '') != 'approved' or str(catalog_pack.get('catalog_release_state') or '') not in {'released', 'rolling_out'}:
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_binding_not_releasable'}
            else:
                binding_scope = str(raw_payload.get('binding_scope') or raw_payload.get('adoption_scope') or 'promotion').strip() or 'promotion'
                binding_context = {
                    'promotion_id': str(raw_payload.get('binding_promotion_id') or current_catalog_context.get('promotion_id') or ''),
                    'workspace_id': str(raw_payload.get('binding_workspace_id') or current_catalog_context.get('workspace_id') or ''),
                    'environment': str(raw_payload.get('binding_environment') or current_catalog_context.get('environment') or ''),
                    'portfolio_family_id': str(raw_payload.get('binding_portfolio_family_id') or current_catalog_context.get('portfolio_family_id') or ''),
                    'runtime_family_id': str(raw_payload.get('binding_runtime_family_id') or current_catalog_context.get('runtime_family_id') or ''),
                }
                binding_scope_key = self._baseline_promotion_simulation_custody_catalog_binding_scope_key(binding_scope, context=binding_context)
                if binding_scope not in {'global', 'workspace', 'environment', 'portfolio_family', 'runtime_family', 'promotion'} or (binding_scope != 'global' and not binding_scope_key):
                    result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_binding_scope_invalid'}
                else:
                    new_binding = self._baseline_promotion_simulation_custody_catalog_binding({
                        'binding_id': uuid.uuid4().hex,
                        'binding_scope': binding_scope,
                        'binding_scope_key': binding_scope_key,
                        'catalog_entry_id': str(catalog_pack.get('catalog_entry_id') or ''),
                        'catalog_version_key': str(catalog_pack.get('catalog_version_key') or ''),
                        'catalog_version': int(catalog_pack.get('catalog_version') or 0),
                        'catalog_pack_id': str(catalog_pack.get('pack_id') or ''),
                        'catalog_pack_label': str(catalog_pack.get('pack_label') or ''),
                        'promotion_id': str(binding_context.get('promotion_id') or ''),
                        'workspace_id': str(binding_context.get('workspace_id') or ''),
                        'environment': str(binding_context.get('environment') or ''),
                        'portfolio_family_id': str(binding_context.get('portfolio_family_id') or ''),
                        'runtime_family_id': str(binding_context.get('runtime_family_id') or ''),
                        'bound_at': now,
                        'bound_by': str(actor or 'operator'),
                        'state': 'active',
                        'note': str(raw_payload.get('note') or raw_payload.get('reason') or ''),
                    })
                    updated_bindings = [
                        self._baseline_promotion_simulation_custody_catalog_binding(item)
                        for item in raw_bindings
                        if not (str((item or {}).get('binding_scope') or '') == binding_scope and str((item or {}).get('binding_scope_key') or '') == binding_scope_key and str((item or {}).get('state') or 'active') == 'active')
                    ]
                    updated_bindings.append(new_binding)
                    binding_event = {
                        'event_id': uuid.uuid4().hex,
                        'event_type': 'bound',
                        'binding_id': str(new_binding.get('binding_id') or ''),
                        'binding_scope': binding_scope,
                        'binding_scope_key': binding_scope_key,
                        'catalog_entry_id': str(new_binding.get('catalog_entry_id') or ''),
                        'catalog_version_key': str(new_binding.get('catalog_version_key') or ''),
                        'catalog_version': int(new_binding.get('catalog_version') or 0),
                        'at': now,
                        'by': str(actor or 'operator'),
                        'note': str(raw_payload.get('note') or raw_payload.get('reason') or ''),
                    }
                    raw_binding_events.append(binding_event)
                    all_bindings_effective = [
                        item for item in all_bindings
                        if not (str((item or {}).get('catalog_owner_canvas_id') or '') == canvas_id and str((item or {}).get('catalog_owner_node_id') or '') == node_id and str((item or {}).get('binding_scope') or '') == binding_scope and str((item or {}).get('binding_scope_key') or '') == binding_scope_key)
                    ] + updated_bindings
                    effective_binding = self._baseline_promotion_simulation_custody_effective_catalog_binding(all_bindings_effective, context=current_catalog_context, catalog_packs=all_catalog_packs)
                    target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
                    raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                    updated_registry = []
                    for item in raw_registry_packs:
                        normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                        if str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '') == target_entry_id:
                            normalized_item['catalog_binding_count'] = int(normalized_item.get('catalog_binding_count') or 0) + 1
                            normalized_item['catalog_last_bound_at'] = now
                            normalized_item['catalog_last_bound_by'] = str(actor or 'operator')
                        updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                    normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                    updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                    updated_data = dict(data)
                    updated_data['routing_policy_pack_registry'] = updated_registry
                    updated_data['routing_policy_pack_bindings'] = [self._compact_baseline_promotion_simulation_catalog_binding(item) for item in updated_bindings[-12:]]
                    updated_data['routing_policy_pack_binding_events'] = [self._compact_baseline_promotion_simulation_catalog_binding_event(item) for item in raw_binding_events[-12:]]
                    updated_data['routing_policy_pack_binding_summary'] = self._baseline_promotion_simulation_custody_catalog_binding_summary(all_bindings_effective)
                    updated_data['effective_routing_policy_pack_binding'] = self._compact_baseline_promotion_simulation_catalog_binding(effective_binding)
                    updated_data['last_catalog_binding_routing_policy_pack'] = self._compact_baseline_promotion_simulation_catalog_binding(new_binding)
                    if latest_simulation:
                        export_state = dict(latest_simulation.get('export_state') or {})
                        export_state['last_catalog_binding_routing_policy_pack'] = dict(updated_data['last_catalog_binding_routing_policy_pack'])
                        export_state['effective_routing_policy_pack_binding'] = dict(updated_data['effective_routing_policy_pack_binding'])
                        updated_simulation = dict(latest_simulation)
                        updated_simulation['export_state'] = export_state
                        updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                    node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    pack_with_binding = dict(catalog_pack)
                    pack_with_binding.update(self._baseline_promotion_simulation_custody_catalog_pack_bindings(pack_with_binding, bindings=all_bindings_effective, effective_binding=effective_binding))
                    result = {'ok': True, 'policy_pack': self._compact_baseline_promotion_simulation_routing_policy_pack(pack_with_binding), 'binding': self._compact_baseline_promotion_simulation_catalog_binding(new_binding), 'effective_binding': dict(data.get('effective_routing_policy_pack_binding') or {}), 'latest_simulation': dict(data.get('latest_simulation') or {})}
        else:
            binding_id = str(raw_payload.get('binding_id') or '').strip()
            binding_scope = str(raw_payload.get('binding_scope') or raw_payload.get('adoption_scope') or '').strip()
            binding_context = {
                'promotion_id': str(raw_payload.get('binding_promotion_id') or current_catalog_context.get('promotion_id') or ''),
                'workspace_id': str(raw_payload.get('binding_workspace_id') or current_catalog_context.get('workspace_id') or ''),
                'environment': str(raw_payload.get('binding_environment') or current_catalog_context.get('environment') or ''),
                'portfolio_family_id': str(raw_payload.get('binding_portfolio_family_id') or current_catalog_context.get('portfolio_family_id') or ''),
                'runtime_family_id': str(raw_payload.get('binding_runtime_family_id') or current_catalog_context.get('runtime_family_id') or ''),
            }
            binding_scope_key = self._baseline_promotion_simulation_custody_catalog_binding_scope_key(binding_scope, context=binding_context) if binding_scope else ''
            if not binding_id and not binding_scope:
                inferred = self._baseline_promotion_simulation_custody_effective_catalog_binding(all_bindings, context=current_catalog_context, catalog_packs=all_catalog_packs)
                binding_id = str(inferred.get('binding_id') or '')
                if not binding_id:
                    binding_scope = 'promotion'
                    binding_scope_key = self._baseline_promotion_simulation_custody_catalog_binding_scope_key(binding_scope, context=current_catalog_context)
            removed = []
            updated_bindings = []
            for item in raw_bindings:
                normalized_binding = self._baseline_promotion_simulation_custody_catalog_binding(item)
                matches = False
                if binding_id and str(normalized_binding.get('binding_id') or '') == binding_id:
                    matches = True
                elif binding_scope and str(normalized_binding.get('binding_scope') or '') == binding_scope and str(normalized_binding.get('binding_scope_key') or '') == binding_scope_key:
                    if not requested_catalog_entry_id or str(normalized_binding.get('catalog_entry_id') or '') == requested_catalog_entry_id:
                        matches = True
                if matches:
                    removed.append(normalized_binding)
                else:
                    updated_bindings.append(normalized_binding)
            if not removed:
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_binding_missing'}
            else:
                for removed_binding in removed:
                    raw_binding_events.append({
                        'event_id': uuid.uuid4().hex,
                        'event_type': 'unbound',
                        'binding_id': str(removed_binding.get('binding_id') or ''),
                        'binding_scope': str(removed_binding.get('binding_scope') or ''),
                        'binding_scope_key': str(removed_binding.get('binding_scope_key') or ''),
                        'catalog_entry_id': str(removed_binding.get('catalog_entry_id') or ''),
                        'catalog_version_key': str(removed_binding.get('catalog_version_key') or ''),
                        'catalog_version': int(removed_binding.get('catalog_version') or 0),
                        'at': now,
                        'by': str(actor or 'operator'),
                        'note': str(raw_payload.get('note') or raw_payload.get('reason') or ''),
                    })
                all_bindings_effective = [
                    item for item in all_bindings
                    if not (str((item or {}).get('catalog_owner_canvas_id') or '') == canvas_id and str((item or {}).get('catalog_owner_node_id') or '') == node_id)
                ] + updated_bindings
                effective_binding = self._baseline_promotion_simulation_custody_effective_catalog_binding(all_bindings_effective, context=current_catalog_context, catalog_packs=all_catalog_packs)
                updated_data = dict(data)
                updated_data['routing_policy_pack_bindings'] = [self._compact_baseline_promotion_simulation_catalog_binding(item) for item in updated_bindings[-12:]]
                updated_data['routing_policy_pack_binding_events'] = [self._compact_baseline_promotion_simulation_catalog_binding_event(item) for item in raw_binding_events[-12:]]
                updated_data['routing_policy_pack_binding_summary'] = self._baseline_promotion_simulation_custody_catalog_binding_summary(all_bindings_effective)
                updated_data['effective_routing_policy_pack_binding'] = self._compact_baseline_promotion_simulation_catalog_binding(effective_binding)
                updated_data['last_catalog_unbound_routing_policy_pack'] = self._compact_baseline_promotion_simulation_catalog_binding(removed[0])
                if latest_simulation:
                    export_state = dict(latest_simulation.get('export_state') or {})
                    export_state['last_catalog_unbound_routing_policy_pack'] = dict(updated_data['last_catalog_unbound_routing_policy_pack'])
                    export_state['effective_routing_policy_pack_binding'] = dict(updated_data['effective_routing_policy_pack_binding'])
                    updated_simulation = dict(latest_simulation)
                    updated_simulation['export_state'] = export_state
                    updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                data = dict(node.get('data') or {})
                result = {'ok': True, 'removed_bindings': [self._compact_baseline_promotion_simulation_catalog_binding(item) for item in removed], 'effective_binding': dict(data.get('effective_routing_policy_pack_binding') or {}), 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

    def _baseline_promotion_action_simulate_simulation_custody_routing(
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
        requested_pack_id = str(raw_payload.get('saved_pack_id') or raw_payload.get('registry_pack_id') or raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
        requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
        requested_organizational_service_entry_id = str(raw_payload.get('organizational_service_entry_id') or raw_payload.get('service_entry_id') or '').strip()
        replay_error = {}
        applied_pack = {}
        if normalized_action == 'replay_cataloged_simulation_custody_routing_policy_pack':
            applied_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
                gw,
                promotion_detail=promotion_detail,
                node_data=data,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
                pack_id=requested_pack_id or None,
                catalog_entry_id=requested_catalog_entry_id or None,
            )
            if not applied_pack:
                replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
            elif str(applied_pack.get('catalog_lifecycle_state') or 'draft') == 'deprecated':
                replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_deprecated'}
            else:
                rollout_access = self._baseline_promotion_simulation_custody_catalog_rollout_access(applied_pack, current_context={**self._baseline_promotion_simulation_custody_catalog_context(promotion_detail=promotion_detail, node_data=data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')), 'canvas_id': canvas_id, 'node_id': node_id})
                if not rollout_access.get('allowed'):
                    replay_error = {'ok': False, 'error': str(rollout_access.get('reason') or 'catalog_rollout_target_not_released')}
        elif normalized_action == 'replay_organizational_simulation_custody_routing_policy_pack':
            applied_pack = self._resolve_baseline_promotion_simulation_custody_organizational_catalog_service_pack(
                gw,
                promotion_detail=promotion_detail,
                node_data=data,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
                pack_id=requested_pack_id or None,
                catalog_entry_id=requested_catalog_entry_id or None,
                organizational_service_entry_id=requested_organizational_service_entry_id or None,
            )
            if not applied_pack:
                replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_organizational_policy_pack_missing'}
            elif str(applied_pack.get('catalog_lifecycle_state') or 'draft') != 'approved':
                replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_not_approved'}
            elif str(applied_pack.get('catalog_release_state') or 'draft') not in {'released', 'rolling_out'}:
                replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_not_released'}
        elif requested_pack_id:
            applied_pack = self._resolve_baseline_promotion_simulation_custody_policy_pack(promotion_detail=promotion_detail, raw_saved_packs=raw_saved_packs, raw_registry_packs=raw_registry_packs, pack_id=requested_pack_id)
            if not applied_pack:
                replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
        elif normalized_action in {'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'}:
            replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
        if replay_error:
            result = replay_error
        else:
            comparison_policies = [dict(item or {}) for item in list(raw_payload.get('comparison_policies') or []) if isinstance(item, dict)]
            if applied_pack:
                comparison_policies = [dict(item or {}) for item in list(applied_pack.get('comparison_policies') or []) if isinstance(item, dict)] + comparison_policies
            replay_result = self.openclaw_recovery_scheduler_service.simulate_runtime_alert_governance_baseline_promotion_simulation_custody_routing(gw, promotion_id=promotion_id, actor=actor, alert_id=str(raw_payload.get('alert_id') or '').strip() or None, policy_overrides=dict(raw_payload.get('policy_overrides') or {}), comparison_policies=comparison_policies, alert_overrides=dict(raw_payload.get('alert_overrides') or {}), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            if not replay_result.get('ok'):
                result = replay_result
            else:
                raw_replay = dict(replay_result.get('routing_replay') or {})
                if applied_pack:
                    raw_replay['applied_pack'] = self._compact_baseline_promotion_simulation_routing_policy_pack(applied_pack)
                compact_replay = self._compact_baseline_promotion_simulation_routing_replay(raw_replay)
                if normalized_action in {'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'}:
                    updated_data = dict(data)
                    if normalized_action in {'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'} and applied_pack:
                        target_entry_id = str(applied_pack.get('catalog_entry_id') or applied_pack.get('registry_entry_id') or '')
                        updated_registry = []
                        for item in raw_registry_packs:
                            normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                            if str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '') == target_entry_id:
                                normalized_item['catalog_replay_count'] = int(normalized_item.get('catalog_replay_count') or 0) + 1
                                normalized_item['catalog_last_replayed_at'] = time.time()
                                normalized_item['catalog_last_replayed_by'] = str(actor or 'operator')
                                normalized_item['catalog_last_replay_source'] = normalized_action
                            updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                        if updated_registry:
                            normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                            updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                            updated_data['routing_policy_pack_registry'] = updated_registry
                    if applied_pack:
                        updated_data['last_used_routing_policy_pack'] = {
                            'catalog_entry_id': str((compact_replay.get('applied_pack') or {}).get('catalog_entry_id') or ''),
                            'catalog_version': int((compact_replay.get('applied_pack') or {}).get('catalog_version') or 0),
                            'pack_id': str((compact_replay.get('applied_pack') or {}).get('pack_id') or ''),
                            'pack_label': str((compact_replay.get('applied_pack') or {}).get('pack_label') or ''),
                            'usage_source': normalized_action,
                            'used_at': time.time(),
                            'used_by': str(actor or 'operator'),
                        }
                        if normalized_action == 'replay_organizational_simulation_custody_routing_policy_pack':
                            updated_data['last_organizational_catalog_replay_routing_policy_pack'] = {
                                'catalog_entry_id': str((compact_replay.get('applied_pack') or {}).get('catalog_entry_id') or ''),
                                'catalog_version': int((compact_replay.get('applied_pack') or {}).get('catalog_version') or 0),
                                'pack_id': str((compact_replay.get('applied_pack') or {}).get('pack_id') or ''),
                                'organizational_service_entry_id': str((compact_replay.get('applied_pack') or {}).get('organizational_service_entry_id') or ''),
                                'usage_source': normalized_action,
                                'used_at': time.time(),
                                'used_by': str(actor or 'operator'),
                            }
                    node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    result = {**replay_result, 'latest_simulation': dict(data.get('latest_simulation') or {}), 'routing_replay': compact_replay}
                else:
                    updated_data = dict(data)
                    updated_data['last_simulation_routing_replay'] = {'alert_id': str(compact_replay.get('alert_id') or ''), 'scenario_count': int(compact_replay.get('scenario_count') or 0), 'applied_pack': dict(compact_replay.get('applied_pack') or {})}
                    if latest_simulation:
                        export_state = dict(latest_simulation.get('export_state') or {})
                        export_state['latest_routing_replay'] = compact_replay
                        updated_simulation = dict(latest_simulation)
                        updated_simulation['export_state'] = export_state
                        updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                    node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    result = {**replay_result, 'latest_simulation': dict(data.get('latest_simulation') or {}), 'routing_replay': compact_replay}
        return result

    def _baseline_promotion_action_acknowledge_simulation_custody_alert(
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
        lifecycle_action = normalized_action.replace('_simulation_custody_alert', '')
        promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
        alert_items = [dict(item) for item in list((((promotion_detail.get('simulation_custody_monitoring') or {}).get('alerts')) or {}).get('items') or [])]
        active_alert = next((item for item in alert_items if bool(item.get('active'))), {})
        muted_alert = next((item for item in alert_items if str(item.get('status') or '') == 'muted'), {})
        target_alert = muted_alert if lifecycle_action == 'unmute' else active_alert
        lifecycle_result = self.openclaw_recovery_scheduler_service.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            gw,
            promotion_id=promotion_id,
            actor=actor,
            action=lifecycle_action,
            alert_id=str(raw_payload.get('alert_id') or target_alert.get('alert_id') or '').strip() or None,
            reason=str(reason or raw_payload.get('reason') or ''),
            mute_for_s=(int(raw_payload.get('mute_for_s')) if raw_payload.get('mute_for_s') is not None else None),
            owner_id=str(raw_payload.get('owner_id') or '').strip() or None,
            owner_role=str(raw_payload.get('owner_role') or '').strip() or None,
            queue_id=str(raw_payload.get('queue_id') or '').strip() or None,
            queue_label=str(raw_payload.get('queue_label') or '').strip() or None,
            route_id=str(raw_payload.get('route_id') or '').strip() or None,
            route_label=str(raw_payload.get('route_label') or '').strip() or None,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        if not lifecycle_result.get('ok'):
            result = lifecycle_result
        else:
            export_state = dict(latest_simulation.get('export_state') or {})
            monitoring = dict(lifecycle_result.get('simulation_custody_monitoring') or {})
            alert_payload = dict(lifecycle_result.get('alert') or {})
            export_state['custody_guard'] = self._compact_baseline_promotion_simulation_custody_guard(monitoring.get('guard') or {})
            export_state['custody_alerts_summary'] = self._compact_baseline_promotion_simulation_custody_alerts_summary(((monitoring.get('alerts') or {}).get('summary')) or {})
            export_state['custody_active_alert'] = self._compact_baseline_promotion_simulation_custody_active_alert(alert_payload)
            export_state['last_alert_action'] = self._compact_baseline_promotion_simulation_last_alert_action({
                'action': lifecycle_action,
                'alert_id': str(alert_payload.get('alert_id') or ''),
                'status': str(alert_payload.get('status') or ''),
                'ownership_status': str((alert_payload.get('ownership') or {}).get('status') or ''),
                'owner_id': str((alert_payload.get('ownership') or {}).get('owner_id') or ''),
                'queue_id': str((alert_payload.get('ownership') or {}).get('queue_id') or ((alert_payload.get('routing') or {}).get('queue_id')) or ''),
                'route_id': str((alert_payload.get('routing') or {}).get('route_id') or ''),
                'at': time.time(),
                'by': str(actor or 'operator'),
            })
            updated_simulation = dict(latest_simulation)
            updated_simulation['export_state'] = export_state
            updated_data = dict(data)
            updated_data['last_simulation_custody_alert_action'] = dict(export_state.get('last_alert_action') or {})
            updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(
                simulation=updated_simulation,
                actor=str(updated_simulation.get('simulated_by') or actor or 'operator'),
                request=dict(updated_simulation.get('request') or {}),
                review=dict(updated_simulation.get('review') or {}),
                created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])],
            )
            node = dict((self._replace_node_data(
                gw,
                canvas_id=canvas_id,
                node=node,
                actor=actor,
                data=updated_data,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            ) or {}).get('node') or node)
            data = dict(node.get('data') or {})
            result = {**lifecycle_result, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

    def _baseline_promotion_action_create_rollout(
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
        create_result = self.openclaw_recovery_scheduler_service.create_runtime_alert_governance_baseline_promotion_from_simulation(
            gw,
            simulation=latest_simulation,
            actor=actor,
            reason=str(reason or raw_payload.get('reason') or ''),
            auto_approve=normalized_action == 'create_and_approve_rollout',
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        if not create_result.get('ok'):
            result = create_result
        else:
            created_release = dict(create_result.get('release') or {})
            created_promotion_id = str(created_release.get('release_id') or create_result.get('promotion_id') or '').strip()
            created_node = {}
            created_edge = {}
            if bool(raw_payload.get('create_canvas_node', True)) and created_promotion_id:
                created_label = str(raw_payload.get('label') or f'Baseline promotion {created_promotion_id[:8]}').strip() or f'Baseline promotion {created_promotion_id[:8]}'
                created_node_payload = self.upsert_node(
                    gw,
                    canvas_id=canvas_id,
                    actor=actor,
                    node_type='baseline_promotion',
                    label=created_label,
                    position_x=float(node.get('position_x') or 0.0) + 320.0,
                    position_y=float(node.get('position_y') or 0.0),
                    width=float(node.get('width') or 240.0),
                    height=float(node.get('height') or 120.0),
                    data={
                        'promotion_id': created_promotion_id,
                        'created_from_simulation': {
                            'source_node_id': str(node.get('node_id') or ''),
                            'source_promotion_id': promotion_id,
                            'simulation_id': str(latest_simulation.get('simulation_id') or ''),
                        },
                    },
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                created_node = dict(created_node_payload.get('node') or {})
                if created_node:
                    created_edge = dict((self.upsert_edge(
                        gw,
                        canvas_id=canvas_id,
                        actor=actor,
                        source_node_id=str(node.get('node_id') or ''),
                        target_node_id=str(created_node.get('node_id') or ''),
                        label='derived_from_simulation',
                        edge_type='derived_from_simulation',
                        data={
                            'simulation_id': str(latest_simulation.get('simulation_id') or ''),
                            'created_promotion_id': created_promotion_id,
                            'diverged': bool((((create_result.get('created_from_simulation') or {}).get('comparison') or {}).get('diverged'))),
                        },
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    ) or {}).get('edge') or {})
            created_promotions = [dict(item) for item in list(latest_simulation.get('created_promotions') or [])]
            created_promotions.append({
                'promotion_id': created_promotion_id,
                'status': str(created_release.get('status') or ''),
                'created_at': time.time(),
                'created_by': str(actor or 'operator'),
                'auto_approved': normalized_action == 'create_and_approve_rollout',
                'simulation_id': str(latest_simulation.get('simulation_id') or ''),
                'created_node_id': str(created_node.get('node_id') or ''),
                'diverged': bool((((create_result.get('created_from_simulation') or {}).get('comparison') or {}).get('diverged'))),
                'divergence_count': len(list((((create_result.get('created_from_simulation') or {}).get('comparison') or {}).get('items') or []))),
            })
            updated_state = self._baseline_promotion_simulation_state(
                simulation=latest_simulation,
                actor=str(latest_simulation.get('simulated_by') or actor or 'operator'),
                request=dict(latest_simulation.get('request') or {}),
                review=dict(latest_simulation.get('review') or {}),
                created_promotions=created_promotions,
            )
            updated_data = dict(data)
            updated_data['latest_simulation'] = updated_state
            updated_data['last_created_promotion'] = {
                'promotion_id': created_promotion_id,
                'status': str(created_release.get('status') or ''),
                'created_node_id': str(created_node.get('node_id') or ''),
                'simulation_id': str(latest_simulation.get('simulation_id') or ''),
                'diverged': bool((((create_result.get('created_from_simulation') or {}).get('comparison') or {}).get('diverged'))),
            }
            node = dict((self._replace_node_data(
                gw,
                canvas_id=canvas_id,
                node=node,
                actor=actor,
                data=updated_data,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            ) or {}).get('node') or node)
            data = dict(node.get('data') or {})
            create_result['created_node'] = created_node
            create_result['created_edge'] = created_edge
            create_result['canvas_simulation'] = updated_state
            result = create_result
        return result

    def _baseline_promotion_action_export_attestation(
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
        result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_attestation(
            gw,
            promotion_id=promotion_id,
            actor=actor,
            timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        return result

    def _baseline_promotion_action_export_postmortem(
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
        result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_postmortem(
            gw,
            promotion_id=promotion_id,
            actor=actor,
            timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        return result

