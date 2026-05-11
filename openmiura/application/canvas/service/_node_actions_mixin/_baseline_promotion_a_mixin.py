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

class _LiveCanvasNodeActionsMixinBaselinePromotionA:
    """Mixin: node actions methods on LiveCanvasService."""

    def _baseline_promotion_action_simulate(
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
        baseline_promotion = dict(promotion_detail.get('baseline_promotion') or {})
        promotion_policy = dict(baseline_promotion.get('promotion_policy') or {})
        simulation_request = {
            'catalog_id': str(baseline_promotion.get('catalog_id') or ''),
            'candidate_baselines': dict(raw_payload.get('environment_policy_baselines') or raw_payload.get('candidate_baselines') or baseline_promotion.get('candidate_baselines') or {}),
            'version': (str(raw_payload.get('version')).strip() if raw_payload.get('version') is not None else None),
            'rollout_policy': (dict(raw_payload.get('rollout_policy') or {}) if 'rollout_policy' in raw_payload else dict(promotion_policy.get('rollout_policy') or {})),
            'gate_policy': (dict(raw_payload.get('gate_policy') or {}) if 'gate_policy' in raw_payload else dict(promotion_policy.get('gate_policy') or {})),
            'rollback_policy': (dict(raw_payload.get('rollback_policy') or {}) if 'rollback_policy' in raw_payload else dict(promotion_policy.get('rollback_policy') or {})),
            'reason': str(reason or raw_payload.get('reason') or ''),
        }
        result = self.openclaw_recovery_scheduler_service.simulate_existing_runtime_alert_governance_baseline_promotion(
            gw,
            promotion_id=promotion_id,
            actor=actor,
            candidate_baselines=dict(simulation_request.get('candidate_baselines') or {}),
            version=simulation_request.get('version'),
            rollout_policy=dict(simulation_request.get('rollout_policy') or {}),
            gate_policy=dict(simulation_request.get('gate_policy') or {}),
            rollback_policy=dict(simulation_request.get('rollback_policy') or {}),
            reason=reason,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        if result.get('ok'):
            updated_data = dict(data)
            updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(
                simulation=result,
                actor=actor,
                request=simulation_request,
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
            result['canvas_simulation'] = dict(updated_data.get('latest_simulation') or {})
        return result

    def _baseline_promotion_action_approve_simulation(
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
        review_result = self.openclaw_recovery_scheduler_service.review_runtime_alert_governance_baseline_promotion_simulation(
            gw,
            simulation=latest_simulation,
            actor=actor,
            decision='approve' if normalized_action == 'approve_simulation' else 'reject',
            reason=str(reason or raw_payload.get('reason') or ''),
            layer_id=(str(raw_payload.get('layer_id')).strip() if raw_payload.get('layer_id') is not None else None),
            requested_role=(str(raw_payload.get('requested_role')).strip() if raw_payload.get('requested_role') is not None else None),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        if not review_result.get('ok'):
            result = review_result
        else:
            updated_state = self._baseline_promotion_simulation_state(
                simulation=dict(review_result.get('simulation') or latest_simulation),
                actor=str(latest_simulation.get('simulated_by') or actor or 'operator'),
                request=dict(latest_simulation.get('request') or {}),
                created_promotions=[dict(item) for item in list(latest_simulation.get('created_promotions') or [])],
            )
            updated_data = dict(data)
            updated_data['latest_simulation'] = updated_state
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
            result = {'ok': True, 'latest_simulation': updated_state, 'review_action': dict(review_result.get('review_action') or {})}
        return result

    def _baseline_promotion_action_export_simulation_attestation(
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
        package_id = str(raw_payload.get('package_id') or (((latest_simulation.get('export_state') or {}).get('latest_evidence_package') or {}).get('package_id')) or ((((promotion_detail.get('simulation_evidence_packages') or {}).get('items') or [{}])[0]).get('package_id')) or '').strip() or None
        if normalized_action == 'export_simulation_attestation':
            export_result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_simulation_attestation(
                gw,
                simulation=latest_simulation,
                actor=actor,
                timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        elif normalized_action == 'export_simulation_review_audit':
            export_result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_simulation_review_audit(
                gw,
                simulation=latest_simulation,
                actor=actor,
                timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        elif normalized_action == 'export_simulation_evidence_package':
            export_result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
                gw,
                simulation=latest_simulation,
                actor=actor,
                timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        elif normalized_action == 'verify_simulation_evidence_package':
            export_result = self.openclaw_recovery_scheduler_service.verify_runtime_alert_governance_baseline_promotion_simulation_evidence_artifact(
                gw,
                promotion_id=promotion_id,
                actor=actor,
                package_id=package_id,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        elif normalized_action == 'restore_simulation_evidence_package':
            export_result = self.openclaw_recovery_scheduler_service.restore_runtime_alert_governance_baseline_promotion_simulation_evidence_artifact(
                gw,
                promotion_id=promotion_id,
                actor=actor,
                package_id=package_id,
                persist_restore_session=bool(raw_payload.get('persist_restore_session', True)),
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        else:
            export_result = self.openclaw_recovery_scheduler_service.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
                gw,
                promotion_id=promotion_id,
                actor=actor,
                package_id=package_id,
                persist_reconciliation_session=bool(raw_payload.get('persist_reconciliation_session', True)),
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        if not export_result.get('ok'):
            result = export_result
        else:
            export_state = dict(latest_simulation.get('export_state') or {})
            report = dict(export_result.get('report') or {})
            integrity = dict(export_result.get('integrity') or {})
            export_summary = {
                'report_id': str(report.get('report_id') or ''),
                'report_type': str(report.get('report_type') or ''),
                'generated_at': report.get('generated_at'),
                'generated_by': report.get('generated_by'),
                'integrity': integrity,
            }
            updated_simulation = dict(latest_simulation)
            updated_data = dict(data)
            if normalized_action == 'export_simulation_attestation':
                export_state['attestation_count'] = int(export_state.get('attestation_count') or 0) + 1
                export_state['latest_attestation'] = export_summary
            elif normalized_action == 'export_simulation_review_audit':
                export_state['review_audit_count'] = int(export_state.get('review_audit_count') or 0) + 1
                export_state['latest_review_audit'] = export_summary
            elif normalized_action == 'export_simulation_evidence_package':
                artifact = dict(export_result.get('artifact') or {})
                registry_entry = dict(export_result.get('registry_entry') or {})
                export_state['evidence_package_count'] = int(export_state.get('evidence_package_count') or 0) + 1
                export_state['custody_job'] = dict(export_result.get('custody_job') or {})
                export_state['latest_evidence_package'] = {
                    'package_id': str(export_result.get('package_id') or ''),
                    'report_type': str(((export_result.get('package') or {}).get('report_type') or '')),
                    'generated_at': (export_result.get('package') or {}).get('generated_at'),
                    'generated_by': (export_result.get('package') or {}).get('generated_by'),
                    'integrity': integrity,
                    'artifact': {
                        'artifact_type': str(artifact.get('artifact_type') or ''),
                        'sha256': str(artifact.get('sha256') or ''),
                        'size_bytes': int(artifact.get('size_bytes') or 0),
                        'filename': str(artifact.get('filename') or ''),
                    },
                    'registry_entry': {
                        'entry_id': str(registry_entry.get('entry_id') or ''),
                        'sequence': int(registry_entry.get('sequence') or 0),
                        'entry_hash': str(registry_entry.get('entry_hash') or ''),
                        'previous_entry_hash': str(registry_entry.get('previous_entry_hash') or ''),
                        'immutable': bool(registry_entry.get('immutable')),
                    },
                    'escrow': dict(export_result.get('escrow') or {}),
                }
                export_state['registry_summary'] = dict(export_result.get('registry_summary') or {})
            elif normalized_action == 'verify_simulation_evidence_package':
                export_state['verification_count'] = int(export_state.get('verification_count') or 0) + 1
                export_state['latest_verification'] = {
                    'package_id': str(export_result.get('package_id') or package_id or ''),
                    'verified_at': time.time(),
                    'verified_by': str(actor or 'operator'),
                    'status': str(((export_result.get('verification') or {}).get('status')) or ''),
                    'valid': bool(((export_result.get('verification') or {}).get('valid'))),
                    'failures': [str(item) for item in list(((export_result.get('verification') or {}).get('failures')) or []) if str(item)],
                    'artifact_sha256': str(((export_result.get('artifact') or {}).get('sha256')) or ''),
                    'artifact_source': str(((export_result.get('artifact') or {}).get('source')) or ''),
                    'escrow_status': str((((export_result.get('verification') or {}).get('escrow') or {}).get('status')) or ''),
                    'registry_entry': {
                        'entry_id': str(((export_result.get('registry_entry') or {}).get('entry_id')) or ''),
                        'sequence': int(((export_result.get('registry_entry') or {}).get('sequence')) or 0),
                    },
                }
                updated_data['last_simulation_evidence_verification'] = dict(export_state.get('latest_verification') or {})
            elif normalized_action == 'reconcile_simulation_evidence_custody':
                reconciliation = dict(export_result.get('reconciliation') or {})
                summary = dict(reconciliation.get('summary') or {})
                export_state['reconciliation_count'] = int(export_state.get('reconciliation_count') or 0) + 1
                export_state['latest_reconciliation'] = {
                    'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''),
                    'package_id': str(export_result.get('package_id') or package_id or ''),
                    'reconciled_at': reconciliation.get('reconciled_at'),
                    'reconciled_by': str(reconciliation.get('reconciled_by') or actor or 'operator'),
                    'overall_status': str(summary.get('overall_status') or ''),
                    'drifted_count': int(summary.get('drifted_count') or 0),
                    'missing_archive_count': int(summary.get('missing_archive_count') or 0),
                    'lock_drift_count': int(summary.get('lock_drift_count') or 0),
                    'registry_drift_count': int(summary.get('registry_drift_count') or 0),
                    'latest_package_id': str(summary.get('latest_package_id') or ''),
                }
                updated_data['last_simulation_evidence_reconciliation'] = dict(export_state.get('latest_reconciliation') or {})
                metadata = dict(((export_result.get('release') or {}).get('release') or {}).get('metadata') or {}) if isinstance(export_result.get('release'), dict) and 'release' in export_result.get('release') else dict((export_result.get('release') or {}).get('metadata') or {})
                promotion_meta = dict(metadata.get('baseline_promotion') or {})
                monitoring_guard = ((export_result.get('custody_monitoring') or {}).get('guard') or {})
                export_state['custody_guard'] = self._compact_baseline_promotion_simulation_custody_guard(monitoring_guard or promotion_meta.get('simulation_custody_guard') or {})
                raw_alert_items = [dict(item) for item in list(promotion_meta.get('simulation_custody_alerts') or [])]
                monitoring_alerts = (export_result.get('custody_monitoring') or {}).get('alerts')
                monitoring_alert_items = []
                monitoring_alert_summary = {}
                if isinstance(monitoring_alerts, dict):
                    monitoring_alert_items = [dict(item) for item in list(monitoring_alerts.get('items') or [])]
                    monitoring_alert_summary = dict(monitoring_alerts.get('summary') or {})
                elif isinstance(monitoring_alerts, list):
                    monitoring_alert_items = [dict(item) for item in list(monitoring_alerts or [])]
                alert_items = monitoring_alert_items or raw_alert_items
                if monitoring_alert_summary:
                    export_state['custody_alerts_summary'] = self._compact_baseline_promotion_simulation_custody_alerts_summary(monitoring_alert_summary)
                else:
                    export_state['custody_alerts_summary'] = self._compact_baseline_promotion_simulation_custody_alerts_summary({
                        'count': len(alert_items),
                        'active_count': sum(1 for item in alert_items if bool(item.get('active'))),
                        'acknowledged_count': sum(1 for item in alert_items if str(item.get('status') or '') == 'acknowledged'),
                        'muted_count': sum(1 for item in alert_items if str(item.get('status') or '') == 'muted'),
                        'escalated_count': sum(1 for item in alert_items if int(item.get('escalation_level') or item.get('escalation_count') or 0) > 0),
                        'suppressed_count': sum(1 for item in alert_items if bool((item.get('suppression_state') or {}).get('suppressed'))),
                        'pending_handoff_count': sum(1 for item in alert_items if bool((item.get('handoff') or {}).get('pending'))),
                        'sla_breached_count': sum(1 for item in alert_items if bool((item.get('sla') or item.get('sla_state') or {}).get('breached'))),
                        'latest_alert_id': str((alert_items[0] or {}).get('alert_id') or '') if alert_items else '',
                    })
                active_alert = next((item for item in alert_items if bool(item.get('active'))), {})
                export_state['custody_active_alert'] = self._compact_baseline_promotion_simulation_custody_active_alert(active_alert)
            else:
                restored_simulation = dict(export_result.get('replayed_simulation') or export_result.get('restored_simulation') or {})
                export_state = dict((restored_simulation.get('export_state') or export_state))
                export_state['verification_count'] = int(export_state.get('verification_count') or 0) + 1
                export_state['latest_verification'] = {
                    'package_id': str(export_result.get('package_id') or package_id or ''),
                    'verified_at': time.time(),
                    'verified_by': str(actor or 'operator'),
                    'status': str(((export_result.get('verification') or {}).get('status')) or ''),
                    'valid': bool(((export_result.get('verification') or {}).get('valid'))),
                    'failures': [str(item) for item in list(((export_result.get('verification') or {}).get('failures')) or []) if str(item)],
                    'artifact_sha256': str(((export_result.get('artifact') or {}).get('sha256')) or ''),
                    'artifact_source': str(((export_result.get('artifact') or {}).get('source')) or ''),
                    'escrow_status': str((((export_result.get('verification') or {}).get('escrow') or {}).get('status')) or ''),
                    'registry_entry': {
                        'entry_id': str(((export_result.get('registry_entry') or {}).get('entry_id')) or ''),
                        'sequence': int(((export_result.get('registry_entry') or {}).get('sequence')) or 0),
                    },
                }
                export_state['restore_count'] = int(export_state.get('restore_count') or 0) + 1
                export_state['latest_restore'] = {
                    'restore_id': str(((export_result.get('restore_session') or {}).get('restore_id')) or ''),
                    'package_id': str(export_result.get('package_id') or package_id or ''),
                    'restored_at': ((export_result.get('restore_session') or {}).get('restored_at')),
                    'restored_by': str(((export_result.get('restore_session') or {}).get('restored_by')) or actor or 'operator'),
                    'simulation_status': str((restored_simulation.get('simulation_status') or '')),
                    'stale': bool(restored_simulation.get('stale')),
                    'expired': bool(restored_simulation.get('expired')),
                    'blocked': bool(restored_simulation.get('blocked')),
                    'why_blocked': str(restored_simulation.get('why_blocked') or ''),
                }
                restored_simulation['export_state'] = export_state
                updated_simulation = restored_simulation
                updated_data['last_simulation_restore'] = dict(export_state.get('latest_restore') or {})
            if normalized_action in {'export_simulation_attestation', 'export_simulation_review_audit', 'export_simulation_evidence_package', 'verify_simulation_evidence_package', 'reconcile_simulation_evidence_custody'}:
                updated_simulation['export_state'] = export_state
            if updated_simulation:
                updated_state = self._baseline_promotion_simulation_state(
                    simulation=updated_simulation,
                    actor=str(updated_simulation.get('simulated_by') or latest_simulation.get('simulated_by') or actor or 'operator'),
                    request=dict(updated_simulation.get('request') or latest_simulation.get('request') or {}),
                    review=dict(updated_simulation.get('review') or latest_simulation.get('review') or {}),
                    created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or latest_simulation.get('created_promotions') or [])],
                )
                updated_data['latest_simulation'] = updated_state
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
            result = {**export_result, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

    def _baseline_promotion_action_save_simulation_custody_routing_policy_pack(
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
        builtin_pack_ids = {str(item.get('pack_id') or '') for item in builtin_packs}
        raw_saved_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
        raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
        preset_pack_id = str(raw_payload.get('preset_pack_id') or raw_payload.get('builtin_pack_id') or '').strip()
        save_error = {}
        if preset_pack_id:
            policy_pack = self._resolve_baseline_promotion_simulation_custody_policy_pack(promotion_detail=promotion_detail, raw_saved_packs=raw_saved_packs, raw_registry_packs=raw_registry_packs, pack_id=preset_pack_id)
            if not policy_pack:
                save_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
            else:
                policy_pack = dict(policy_pack)
                policy_pack['source'] = 'saved'
                policy_pack['created_by'] = str(actor or 'operator')
                policy_pack['created_at'] = time.time()
                policy_pack['last_used_at'] = None
                policy_pack['use_count'] = 0
        else:
            raw_pack = dict(raw_payload.get('policy_pack') or raw_payload.get('pack') or {})
            if not raw_pack:
                raw_pack = {
                    'pack_id': raw_payload.get('pack_id'),
                    'pack_label': raw_payload.get('pack_label') or raw_payload.get('label'),
                    'description': raw_payload.get('description'),
                    'category_keys': list(raw_payload.get('category_keys') or raw_payload.get('categories') or []),
                    'tags': list(raw_payload.get('tags') or []),
                    'comparison_policies': [dict(item or {}) for item in list(raw_payload.get('comparison_policies') or []) if isinstance(item, dict)],
                }
            policy_pack = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(raw_pack, actor=str(actor or 'operator'), index=len(raw_saved_packs) + 1, source='saved')
            if not list(policy_pack.get('comparison_policies') or []):
                save_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_empty'}
        if save_error:
            result = save_error
        else:
            updated_saved = [item for item in raw_saved_packs if str(item.get('pack_id') or '') != str(policy_pack.get('pack_id') or '')]
            if str(policy_pack.get('pack_id') or '') in builtin_pack_ids or str(policy_pack.get('promoted_from_pack_id') or '') in builtin_pack_ids:
                saved_storage_pack = {
                    'pack_id': str(policy_pack.get('pack_id') or ''),
                    'pack_label': str(policy_pack.get('pack_label') or ''),
                    'source': 'saved',
                    'category_keys': [str(item) for item in list(policy_pack.get('category_keys') or []) if str(item)][:8],
                    'tags': [str(item) for item in list(policy_pack.get('tags') or []) if str(item)][:8],
                    'created_at': policy_pack.get('created_at'),
                    'created_by': str(policy_pack.get('created_by') or ''),
                    'scenario_count': int(policy_pack.get('scenario_count') or 0),
                }
            else:
                saved_storage_pack = self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(policy_pack)
            updated_saved.append(saved_storage_pack)
            normalized_saved = self._baseline_promotion_simulation_custody_saved_policy_packs(updated_saved)
            normalized_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(raw_registry_packs)
            compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(policy_pack)
            updated_data = dict(data)
            updated_data['saved_routing_policy_packs'] = updated_saved
            updated_data['last_saved_routing_policy_pack'] = dict(compact_pack)
            if latest_simulation:
                export_state = dict(latest_simulation.get('export_state') or {})
                export_state['routing_policy_what_if_presets'] = [
                    {'pack_id': str(item.get('pack_id') or ''), 'pack_label': str(item.get('pack_label') or ''), 'source': str(item.get('source') or ''), 'category_keys': [str(v) for v in list(item.get('category_keys') or []) if str(v)][:8], 'scenario_count': int(item.get('scenario_count') or 0)}
                    for item in builtin_packs[:6]
                ]
                export_state['saved_routing_policy_packs'] = [
                    {'pack_id': str(item.get('pack_id') or ''), 'pack_label': str(item.get('pack_label') or ''), 'source': str(item.get('source') or ''), 'category_keys': [str(v) for v in list(item.get('category_keys') or []) if str(v)][:8], 'scenario_count': int(item.get('scenario_count') or 0), 'created_at': item.get('created_at'), 'created_by': str(item.get('created_by') or ''), 'last_used_at': item.get('last_used_at'), 'use_count': int(item.get('use_count') or 0)}
                    for item in normalized_saved[:6]
                ]
                export_state['routing_policy_pack_registry'] = [
                    {
                        'pack_id': str(item.get('pack_id') or ''),
                        'pack_label': str(item.get('pack_label') or ''),
                        'source': str(item.get('source') or ''),
                        'registry_entry_id': str(item.get('registry_entry_id') or ''),
                        'registry_scope': str(item.get('registry_scope') or ''),
                        'catalog_entry_id': str(item.get('catalog_entry_id') or ''),
                        'catalog_scope': str(item.get('catalog_scope') or ''),
                        'catalog_scope_key': str(item.get('catalog_scope_key') or ''),
                        'catalog_version_key': str(item.get('catalog_version_key') or ''),
                        'catalog_version': int(item.get('catalog_version') or 0),
                        'workspace_id': str(item.get('workspace_id') or ''),
                        'environment': str(item.get('environment') or ''),
                        'promotion_id': str(item.get('promotion_id') or ''),
                        'catalog_lifecycle_state': str(item.get('catalog_lifecycle_state') or 'draft'),
                        'catalog_approval_required': bool(item.get('catalog_approval_required', False)),
                        'catalog_required_approvals': int(item.get('catalog_required_approvals') or 0),
                        'catalog_approval_count': int(item.get('catalog_approval_count') or 0),
                        'catalog_approval_state': str(item.get('catalog_approval_state') or ''),
                        'catalog_attestation_count': int(item.get('catalog_attestation_count') or 0),
                        'catalog_latest_attestation': LiveCanvasService._compact_baseline_promotion_simulation_export_report(item.get('catalog_latest_attestation') or {}),
                        'catalog_evidence_package_count': int(item.get('catalog_evidence_package_count') or 0),
                        'catalog_latest_evidence_package': LiveCanvasService._compact_baseline_promotion_simulation_export_report(item.get('catalog_latest_evidence_package') or {}),
                        'catalog_release_bundle_count': int(item.get('catalog_release_bundle_count') or 0),
                        'catalog_latest_release_bundle': LiveCanvasService._compact_baseline_promotion_simulation_export_report(item.get('catalog_latest_release_bundle') or {}),
                        'catalog_review_state': str(item.get('catalog_review_state') or ''),
                        'catalog_review_assigned_reviewer': str(item.get('catalog_review_assigned_reviewer') or ''),
                        'catalog_review_assigned_role': str(item.get('catalog_review_assigned_role') or ''),
                        'catalog_review_claimed_by': str(item.get('catalog_review_claimed_by') or ''),
                        'catalog_review_claimed_at': item.get('catalog_review_claimed_at'),
                        'catalog_review_decision': str(item.get('catalog_review_decision') or ''),
                        'catalog_review_decision_at': item.get('catalog_review_decision_at'),
                        'catalog_review_decision_by': str(item.get('catalog_review_decision_by') or ''),
                        'catalog_review_latest_note': str(item.get('catalog_review_latest_note') or ''),
                        'catalog_review_note_count': int(item.get('catalog_review_note_count') or 0),
                        'catalog_review_last_transition_at': item.get('catalog_review_last_transition_at'),
                        'catalog_review_last_transition_by': str(item.get('catalog_review_last_transition_by') or ''),
                        'catalog_review_last_transition_action': str(item.get('catalog_review_last_transition_action') or ''),
                        'catalog_review_events': [{
                            'event_id': str(v.get('event_id') or ''),
                            'event_type': str(v.get('event_type') or ''),
                            'state': str(v.get('state') or ''),
                            'actor': str(v.get('actor') or ''),
                            'role': str(v.get('role') or ''),
                            'at': v.get('at'),
                            'note': str(v.get('note') or '')[:80],
                            'decision': str(v.get('decision') or ''),
                            'assigned_reviewer': str(v.get('assigned_reviewer') or '')[:80],
                        } for v in list(item.get('catalog_review_events') or [])[:8] if isinstance(v, dict)],
                        'catalog_release_state': str(item.get('catalog_release_state') or 'draft'),
                        'catalog_release_train_id': str(item.get('catalog_release_train_id') or ''),
                        'catalog_rollout_train_id': str(item.get('catalog_rollout_train_id') or ''),
                        'catalog_rollout_policy': LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_policy(item.get('catalog_rollout_policy') or {}),
                        'catalog_rollout_enabled': bool(item.get('catalog_rollout_enabled', False)),
                        'catalog_rollout_state': str(item.get('catalog_rollout_state') or ''),
                        'catalog_rollout_current_wave_index': int(item.get('catalog_rollout_current_wave_index') or 0),
                        'catalog_rollout_completed_wave_count': int(item.get('catalog_rollout_completed_wave_count') or 0),
                        'catalog_rollout_paused': bool(item.get('catalog_rollout_paused', False)),
                        'catalog_rollout_frozen': bool(item.get('catalog_rollout_frozen', False)),
                        'catalog_rollout_targets': [
                            {
                                'target_key': str(v.get('target_key') or ''),
                                'promotion_id': str(v.get('promotion_id') or ''),
                                'workspace_id': str(v.get('workspace_id') or ''),
                                'environment': str(v.get('environment') or ''),
                                'released': bool(v.get('released', False)),
                                'released_wave_index': int(v.get('released_wave_index') or 0),
                            }
                            for v in list(item.get('catalog_rollout_targets') or [])[:12]
                            if isinstance(v, dict)
                        ],
                        'catalog_rollout_waves': [
                            {
                                'wave_index': int(v.get('wave_index') or 0),
                                'status': str(v.get('status') or ''),
                                'target_keys': [str(k) for k in list(v.get('target_keys') or []) if str(k)][:12],
                            }
                            for v in list(item.get('catalog_rollout_waves') or [])[:8]
                            if isinstance(v, dict)
                        ],
                        'catalog_rollout_policy': LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_policy(item.get('catalog_rollout_policy') or {}),
                        'catalog_dependency_refs': LiveCanvasService._baseline_promotion_simulation_custody_catalog_dependency_refs(item.get('catalog_dependency_refs') or []),
                        'catalog_conflict_rules': LiveCanvasService._baseline_promotion_simulation_custody_catalog_conflict_rules(item.get('catalog_conflict_rules') or {}),
                        'catalog_freeze_windows': LiveCanvasService._baseline_promotion_simulation_custody_catalog_freeze_windows(item.get('catalog_freeze_windows') or []),
                        'catalog_dependency_summary': dict(item.get('catalog_dependency_summary') or {}),
                        'catalog_conflict_summary': dict(item.get('catalog_conflict_summary') or {}),
                        'catalog_freeze_summary': dict(item.get('catalog_freeze_summary') or {}),
                        'catalog_release_guard': dict(item.get('catalog_release_guard') or {}),
                        'scenario_count': int(item.get('scenario_count') or 0),
                        'share_count': int(item.get('share_count') or 0),
                    }
                    for item in normalized_registry[:4]
                ]
                export_state['last_saved_routing_policy_pack'] = {'pack_id': str(policy_pack.get('pack_id') or ''), 'pack_label': str(policy_pack.get('pack_label') or ''), 'source': str(policy_pack.get('source') or ''), 'category_keys': [str(v) for v in list(policy_pack.get('category_keys') or []) if str(v)][:8], 'scenario_count': int(policy_pack.get('scenario_count') or 0), 'created_at': policy_pack.get('created_at'), 'created_by': str(policy_pack.get('created_by') or ''), 'last_used_at': policy_pack.get('last_used_at'), 'use_count': int(policy_pack.get('use_count') or 0)}
                updated_simulation = dict(latest_simulation)
                updated_simulation['export_state'] = export_state
                updated_data.pop('routing_policy_pack_catalog', None)
                updated_data.pop('routing_policy_pack_catalog_summary', None)
                updated_data.pop('routing_policy_pack_compliance_summary', None)
                updated_data.pop('effective_routing_policy_pack_compliance', None)
                updated_data.pop('routing_policy_pack_analytics_summary', None)
                updated_data.pop('routing_policy_pack_operator_dashboard', None)
                updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
            node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
            data = dict(node.get('data') or {})
            result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

    def _baseline_promotion_action_promote_simulation_custody_routing_policy_pack_to_registry(
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
        builtin_pack_ids = {str(item.get('pack_id') or '') for item in builtin_packs}
        raw_saved_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
        raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
        requested_pack_id = str(raw_payload.get('registry_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('saved_pack_id') or raw_payload.get('preset_pack_id') or raw_payload.get('pack_id') or '').strip()
        if not requested_pack_id:
            result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
        else:
            source_pack = self._resolve_baseline_promotion_simulation_custody_policy_pack(promotion_detail=promotion_detail, raw_saved_packs=raw_saved_packs, raw_registry_packs=raw_registry_packs, pack_id=requested_pack_id)
            if not source_pack:
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
            else:
                existing_registry = next((item for item in self._baseline_promotion_simulation_custody_registry_policy_packs(raw_registry_packs) if str(item.get('pack_id') or '') == requested_pack_id), {})
                promoted_pack = dict(source_pack)
                promoted_pack['source'] = 'registry'
                promoted_pack['registry_entry_id'] = str(existing_registry.get('registry_entry_id') or raw_payload.get('registry_entry_id') or f'registry_{requested_pack_id}').strip() or f'registry_{requested_pack_id}'
                promoted_pack['registry_scope'] = str(raw_payload.get('registry_scope') or existing_registry.get('registry_scope') or 'promotion').strip() or 'promotion'
                promoted_pack['promoted_at'] = time.time()
                promoted_pack['promoted_by'] = str(actor or 'operator')
                promoted_pack['promoted_from_pack_id'] = str(source_pack.get('promoted_from_pack_id') or source_pack.get('pack_id') or '')
                source_origin = str(source_pack.get('promoted_from_source') or source_pack.get('shared_from_source') or source_pack.get('source') or 'saved')
                if str(source_pack.get('pack_id') or '') in builtin_pack_ids or str(promoted_pack.get('promoted_from_pack_id') or '') in builtin_pack_ids:
                    source_origin = 'builtin'
                promoted_pack['promoted_from_source'] = source_origin
                promoted_pack['share_count'] = int(existing_registry.get('share_count') or 0)
                promoted_pack['last_shared_at'] = existing_registry.get('last_shared_at')
                promoted_pack['last_shared_by'] = str(existing_registry.get('last_shared_by') or '')
                promoted_pack['share_targets'] = [str(item) for item in list(existing_registry.get('share_targets') or raw_payload.get('share_targets') or []) if str(item)][:8]
                if str(promoted_pack.get('promoted_from_source') or '') == 'builtin':
                    registry_storage_pack = {
                        'pack_id': str(promoted_pack.get('pack_id') or ''),
                        'pack_label': str(promoted_pack.get('pack_label') or ''),
                        'source': 'registry',
                        'registry_entry_id': str(promoted_pack.get('registry_entry_id') or ''),
                        'registry_scope': str(promoted_pack.get('registry_scope') or ''),
                        'promoted_at': promoted_pack.get('promoted_at'),
                        'promoted_by': str(promoted_pack.get('promoted_by') or ''),
                        'promoted_from_pack_id': str(promoted_pack.get('promoted_from_pack_id') or ''),
                        'promoted_from_source': str(promoted_pack.get('promoted_from_source') or ''),
                        'share_count': int(promoted_pack.get('share_count') or 0),
                        'share_targets': [str(item) for item in list(promoted_pack.get('share_targets') or []) if str(item)][:8],
                    }
                else:
                    registry_storage_pack = self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(promoted_pack)
                updated_registry = [item for item in raw_registry_packs if str(item.get('pack_id') or '') != str(promoted_pack.get('pack_id') or '')]
                updated_registry.append(registry_storage_pack)
                normalized_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)
                updated_saved = [item for item in raw_saved_packs if str(item.get('pack_id') or '') != str(promoted_pack.get('pack_id') or '')]
                normalized_saved = self._baseline_promotion_simulation_custody_saved_policy_packs(updated_saved)
                compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(promoted_pack)
                updated_data = dict(data)
                updated_data['saved_routing_policy_packs'] = [
                    LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item)
                    )
                    for item in list(updated_saved or [])[-1:]
                    if isinstance(item, dict)
                ]
                if not updated_saved or str(((data.get('last_saved_routing_policy_pack') or {}).get('pack_id')) or '') == str(promoted_pack.get('pack_id') or ''):
                    updated_data.pop('last_saved_routing_policy_pack', None)
                updated_data['routing_policy_pack_registry'] = [
                    LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item)
                    )
                    for item in list(updated_registry or [])[:4]
                    if isinstance(item, dict)
                ]
                updated_data['last_promoted_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'pack_label': str(compact_pack.get('pack_label') or ''), 'source': str(compact_pack.get('source') or ''), 'registry_entry_id': str(compact_pack.get('registry_entry_id') or ''), 'registry_scope': str(compact_pack.get('registry_scope') or ''), 'scenario_count': int(compact_pack.get('scenario_count') or 0)}
                if latest_simulation:
                    updated_data['latest_simulation'] = dict(data.get('latest_simulation') or latest_simulation)
                node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                data = dict(node.get('data') or {})
                result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

    def _baseline_promotion_action_promote_simulation_custody_routing_policy_pack_to_catalog(
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
        builtin_pack_ids = {str(item.get('pack_id') or '') for item in builtin_packs}
        raw_saved_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
        raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
        requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('registry_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('saved_pack_id') or raw_payload.get('preset_pack_id') or raw_payload.get('pack_id') or '').strip()
        if not requested_pack_id:
            result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
        else:
            source_pack = self._resolve_baseline_promotion_simulation_custody_policy_pack(promotion_detail=promotion_detail, raw_saved_packs=raw_saved_packs, raw_registry_packs=raw_registry_packs, pack_id=requested_pack_id)
            if not source_pack:
                result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
            else:
                promotion_meta = dict((promotion_detail.get('baseline_promotion') or {}))
                normalized_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(raw_registry_packs)
                catalog_scope = str(raw_payload.get('catalog_scope') or raw_payload.get('registry_scope') or source_pack.get('catalog_scope') or source_pack.get('registry_scope') or 'promotion').strip() or 'promotion'
                promotion_id_value = str(promotion_meta.get('promotion_id') or promotion_id or data.get('promotion_id') or '')
                workspace_value = str(scope.get('workspace_id') or '')
                environment_value = str(scope.get('environment') or '')
                portfolio_family_id = str(raw_payload.get('portfolio_family_id') or data.get('portfolio_family_id') or promotion_meta.get('portfolio_family_id') or '')
                runtime_family_id = str(raw_payload.get('runtime_family_id') or data.get('runtime_family_id') or promotion_meta.get('runtime_family_id') or '')
                if catalog_scope == 'promotion':
                    catalog_scope_key = f'promotion:{promotion_id_value}'
                elif catalog_scope == 'workspace':
                    catalog_scope_key = f'workspace:{workspace_value}'
                elif catalog_scope == 'environment':
                    catalog_scope_key = f'environment:{workspace_value}:{environment_value}'
                elif catalog_scope == 'portfolio_family':
                    catalog_scope_key = f'portfolio_family:{portfolio_family_id}'
                elif catalog_scope == 'runtime_family':
                    catalog_scope_key = f'runtime_family:{runtime_family_id}'
                elif catalog_scope == 'global':
                    catalog_scope_key = 'global'
                else:
                    catalog_scope_key = str(raw_payload.get('catalog_scope_key') or '') or f'{catalog_scope}:{workspace_value}'
                catalog_version_key = str(raw_payload.get('catalog_version_key') or f'{requested_pack_id}:{catalog_scope_key}').strip() or f'{requested_pack_id}:{catalog_scope_key}'
                existing_versions = [dict(item or {}) for item in normalized_registry if str(item.get('catalog_version_key') or '') == catalog_version_key]
                requested_version = int(raw_payload.get('catalog_version') or 0)
                if requested_version <= 0:
                    requested_version = max([int(item.get('catalog_version') or 0) for item in existing_versions] + [0]) + 1
                requested_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
                existing_registry = next((item for item in existing_versions if str(item.get('catalog_entry_id') or '') == requested_entry_id or int(item.get('catalog_version') or 0) == requested_version), {})
                lifecycle_state = str(raw_payload.get('catalog_lifecycle_state') or existing_registry.get('catalog_lifecycle_state') or source_pack.get('catalog_lifecycle_state') or 'draft').strip() or 'draft'
                generated_entry_seed = f'{catalog_version_key}:{requested_version}'
                generated_entry_suffix = uuid.uuid5(uuid.NAMESPACE_URL, generated_entry_seed).hex[:12]
                generated_entry_id = f'catalog_{requested_pack_id}_{catalog_scope}_{generated_entry_suffix}_{requested_version}'
                promoted_pack = dict(source_pack)
                promoted_pack['source'] = 'catalog'
                promoted_pack['registry_entry_id'] = str(existing_registry.get('registry_entry_id') or requested_entry_id or generated_entry_id).strip() or generated_entry_id
                promoted_pack['registry_scope'] = catalog_scope
                promoted_pack['catalog_entry_id'] = str(existing_registry.get('catalog_entry_id') or requested_entry_id or promoted_pack.get('registry_entry_id') or '').strip()
                promoted_pack['catalog_scope'] = catalog_scope
                promoted_pack['catalog_scope_key'] = catalog_scope_key
                promoted_pack['catalog_version_key'] = catalog_version_key
                promoted_pack['catalog_version'] = requested_version
                promoted_pack['catalog_lifecycle_state'] = lifecycle_state
                promoted_pack['promotion_id'] = promotion_id_value
                promoted_pack['workspace_id'] = workspace_value
                promoted_pack['environment'] = environment_value
                promoted_pack['portfolio_family_id'] = portfolio_family_id
                promoted_pack['runtime_family_id'] = runtime_family_id
                promoted_pack['catalog_promoted_at'] = time.time()
                promoted_pack['catalog_promoted_by'] = str(actor or 'operator')
                promoted_pack['promoted_at'] = promoted_pack.get('catalog_promoted_at')
                promoted_pack['promoted_by'] = promoted_pack.get('catalog_promoted_by')
                promoted_pack['promoted_from_pack_id'] = str(source_pack.get('promoted_from_pack_id') or source_pack.get('pack_id') or '')
                source_origin = str(source_pack.get('promoted_from_source') or source_pack.get('shared_from_source') or source_pack.get('source') or 'saved')
                if str(source_pack.get('pack_id') or '') in builtin_pack_ids or str(promoted_pack.get('promoted_from_pack_id') or '') in builtin_pack_ids:
                    source_origin = 'builtin'
                promoted_pack['promoted_from_source'] = source_origin
                promoted_pack['share_count'] = int(existing_registry.get('share_count') or 0)
                promoted_pack['catalog_share_count'] = int(existing_registry.get('catalog_share_count') or promoted_pack.get('share_count') or 0)
                promoted_pack['last_shared_at'] = existing_registry.get('last_shared_at')
                promoted_pack['last_shared_by'] = str(existing_registry.get('last_shared_by') or '')
                promoted_pack['catalog_last_shared_at'] = existing_registry.get('catalog_last_shared_at') or promoted_pack.get('last_shared_at')
                promoted_pack['catalog_last_shared_by'] = str(existing_registry.get('catalog_last_shared_by') or promoted_pack.get('last_shared_by') or '')
                promoted_pack['share_targets'] = [str(item) for item in list(existing_registry.get('share_targets') or raw_payload.get('share_targets') or []) if str(item)][:8]
                promoted_pack['catalog_curated_at'] = existing_registry.get('catalog_curated_at')
                promoted_pack['catalog_curated_by'] = str(existing_registry.get('catalog_curated_by') or '')
                promoted_pack['catalog_approved_at'] = existing_registry.get('catalog_approved_at')
                promoted_pack['catalog_approved_by'] = str(existing_registry.get('catalog_approved_by') or '')
                promoted_pack['catalog_deprecated_at'] = existing_registry.get('catalog_deprecated_at')
                promoted_pack['catalog_deprecated_by'] = str(existing_registry.get('catalog_deprecated_by') or '')
                promoted_pack['catalog_replaced_by_version'] = int(existing_registry.get('catalog_replaced_by_version') or 0)
                promoted_pack['catalog_is_latest'] = True
                approval_required = bool(raw_payload.get('catalog_approval_required', existing_registry.get('catalog_approval_required', False)))
                required_approvals = int(raw_payload.get('catalog_required_approvals') or existing_registry.get('catalog_required_approvals') or (1 if approval_required else 0))
                approvals = [dict(item or {}) for item in list(existing_registry.get('catalog_approvals') or []) if isinstance(item, dict)]
                approval_count = int(existing_registry.get('catalog_approval_count') or len([item for item in approvals if str(item.get('decision') or '') == 'approved']))
                approval_state = str(existing_registry.get('catalog_approval_state') or ('approved' if approval_required and approval_count >= max(1, required_approvals) else ('not_required' if not approval_required or required_approvals <= 0 else 'pending')))
                promoted_pack['catalog_approval_required'] = approval_required
                promoted_pack['catalog_required_approvals'] = max(0, required_approvals)
                promoted_pack['catalog_approval_count'] = approval_count
                promoted_pack['catalog_approval_state'] = approval_state
                promoted_pack['catalog_approval_requested_at'] = existing_registry.get('catalog_approval_requested_at')
                promoted_pack['catalog_approval_requested_by'] = str(existing_registry.get('catalog_approval_requested_by') or '')
                promoted_pack['catalog_approval_rejected_at'] = existing_registry.get('catalog_approval_rejected_at')
                promoted_pack['catalog_approval_rejected_by'] = str(existing_registry.get('catalog_approval_rejected_by') or '')
                promoted_pack['catalog_approvals'] = approvals[:12]
                promoted_pack['catalog_release_state'] = str(existing_registry.get('catalog_release_state') or raw_payload.get('catalog_release_state') or 'draft')
                promoted_pack['catalog_release_notes'] = str(existing_registry.get('catalog_release_notes') or raw_payload.get('catalog_release_notes') or '')
                promoted_pack['catalog_release_train_id'] = str(existing_registry.get('catalog_release_train_id') or raw_payload.get('catalog_release_train_id') or '')
                promoted_pack['catalog_release_staged_at'] = existing_registry.get('catalog_release_staged_at')
                promoted_pack['catalog_release_staged_by'] = str(existing_registry.get('catalog_release_staged_by') or '')
                promoted_pack['catalog_released_at'] = existing_registry.get('catalog_released_at')
                promoted_pack['catalog_released_by'] = str(existing_registry.get('catalog_released_by') or '')
                promoted_pack['catalog_withdrawn_at'] = existing_registry.get('catalog_withdrawn_at')
                promoted_pack['catalog_withdrawn_by'] = str(existing_registry.get('catalog_withdrawn_by') or '')
                promoted_pack['catalog_withdrawn_reason'] = str(existing_registry.get('catalog_withdrawn_reason') or '')
                promoted_pack['catalog_attestation_count'] = int(existing_registry.get('catalog_attestation_count') or 0)
                promoted_pack['catalog_latest_attestation'] = dict(existing_registry.get('catalog_latest_attestation') or {})
                promoted_pack['catalog_review_state'] = str(existing_registry.get('catalog_review_state') or '')
                promoted_pack['catalog_review_requested_at'] = existing_registry.get('catalog_review_requested_at')
                promoted_pack['catalog_review_requested_by'] = str(existing_registry.get('catalog_review_requested_by') or '')
                promoted_pack['catalog_review_assigned_reviewer'] = str(existing_registry.get('catalog_review_assigned_reviewer') or raw_payload.get('catalog_review_assigned_reviewer') or '')
                promoted_pack['catalog_review_assigned_role'] = str(existing_registry.get('catalog_review_assigned_role') or raw_payload.get('catalog_review_assigned_role') or '')
                promoted_pack['catalog_review_claimed_by'] = str(existing_registry.get('catalog_review_claimed_by') or '')
                promoted_pack['catalog_review_claimed_at'] = existing_registry.get('catalog_review_claimed_at')
                promoted_pack['catalog_review_last_transition_at'] = existing_registry.get('catalog_review_last_transition_at')
                promoted_pack['catalog_review_last_transition_by'] = str(existing_registry.get('catalog_review_last_transition_by') or '')
                promoted_pack['catalog_review_last_transition_action'] = str(existing_registry.get('catalog_review_last_transition_action') or '')
                promoted_pack['catalog_review_decision_at'] = existing_registry.get('catalog_review_decision_at')
                promoted_pack['catalog_review_decision_by'] = str(existing_registry.get('catalog_review_decision_by') or '')
                promoted_pack['catalog_review_decision'] = str(existing_registry.get('catalog_review_decision') or '')
                promoted_pack['catalog_review_note_count'] = int(existing_registry.get('catalog_review_note_count') or len(list(existing_registry.get('catalog_review_events') or [])) or 0)
                promoted_pack['catalog_review_events'] = [dict(item or {}) for item in list(existing_registry.get('catalog_review_events') or []) if isinstance(item, dict)][:12]
                promoted_pack['catalog_evidence_package_count'] = int(existing_registry.get('catalog_evidence_package_count') or 0)
                promoted_pack['catalog_latest_evidence_package'] = dict(existing_registry.get('catalog_latest_evidence_package') or {})
                promoted_pack['catalog_release_bundle_count'] = int(existing_registry.get('catalog_release_bundle_count') or 0)
                promoted_pack['catalog_latest_release_bundle'] = dict(existing_registry.get('catalog_latest_release_bundle') or {})
                promoted_pack['catalog_compliance_report_count'] = int(existing_registry.get('catalog_compliance_report_count') or 0)
                promoted_pack['catalog_latest_compliance_report'] = dict(existing_registry.get('catalog_latest_compliance_report') or {})
                promoted_pack['catalog_replay_count'] = int(existing_registry.get('catalog_replay_count') or 0)
                promoted_pack['catalog_last_replayed_at'] = existing_registry.get('catalog_last_replayed_at')
                promoted_pack['catalog_last_replayed_by'] = str(existing_registry.get('catalog_last_replayed_by') or '')
                promoted_pack['catalog_last_replay_source'] = str(existing_registry.get('catalog_last_replay_source') or '')
                promoted_pack['catalog_binding_count'] = int(existing_registry.get('catalog_binding_count') or 0)
                promoted_pack['catalog_last_bound_at'] = existing_registry.get('catalog_last_bound_at')
                promoted_pack['catalog_last_bound_by'] = str(existing_registry.get('catalog_last_bound_by') or '')
                promoted_pack['catalog_analytics_report_count'] = int(existing_registry.get('catalog_analytics_report_count') or 0)
                promoted_pack['catalog_latest_analytics_report'] = dict(existing_registry.get('catalog_latest_analytics_report') or {})
                promoted_pack['catalog_dependency_refs'] = self._baseline_promotion_simulation_custody_catalog_dependency_refs(raw_payload.get('catalog_dependency_refs') or existing_registry.get('catalog_dependency_refs') or [])
                promoted_pack['catalog_conflict_rules'] = self._baseline_promotion_simulation_custody_catalog_conflict_rules(raw_payload.get('catalog_conflict_rules') or existing_registry.get('catalog_conflict_rules') or {})
                promoted_pack['catalog_freeze_windows'] = self._baseline_promotion_simulation_custody_catalog_freeze_windows(raw_payload.get('catalog_freeze_windows') or existing_registry.get('catalog_freeze_windows') or [])
                if lifecycle_state == 'curated' and not promoted_pack.get('catalog_curated_at'):
                    promoted_pack['catalog_curated_at'] = promoted_pack.get('catalog_promoted_at')
                    promoted_pack['catalog_curated_by'] = str(actor or 'operator')
                if lifecycle_state == 'approved' and not promoted_pack.get('catalog_approved_at'):
                    promoted_pack['catalog_approved_at'] = promoted_pack.get('catalog_promoted_at')
                    promoted_pack['catalog_approved_by'] = str(actor or 'operator')
                if lifecycle_state == 'deprecated' and not promoted_pack.get('catalog_deprecated_at'):
                    promoted_pack['catalog_deprecated_at'] = promoted_pack.get('catalog_promoted_at')
                    promoted_pack['catalog_deprecated_by'] = str(actor or 'operator')
                updated_registry = []
                for item in raw_registry_packs:
                    normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                    if str(normalized_item.get('catalog_version_key') or '') == catalog_version_key and int(normalized_item.get('catalog_version') or 0) == requested_version:
                        continue
                    updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                if str(promoted_pack.get('promoted_from_source') or '') == 'builtin':
                    catalog_storage_pack = {
                        'pack_id': str(promoted_pack.get('pack_id') or ''),
                        'pack_label': str(promoted_pack.get('pack_label') or ''),
                        'source': 'catalog',
                        'registry_entry_id': str(promoted_pack.get('registry_entry_id') or ''),
                        'registry_scope': str(promoted_pack.get('registry_scope') or ''),
                        'catalog_entry_id': str(promoted_pack.get('catalog_entry_id') or ''),
                        'catalog_scope': str(promoted_pack.get('catalog_scope') or ''),
                        'catalog_scope_key': str(promoted_pack.get('catalog_scope_key') or ''),
                        'catalog_version_key': str(promoted_pack.get('catalog_version_key') or ''),
                        'catalog_version': int(promoted_pack.get('catalog_version') or 0),
                        'catalog_lifecycle_state': str(promoted_pack.get('catalog_lifecycle_state') or 'draft'),
                        'catalog_curated_at': promoted_pack.get('catalog_curated_at'),
                        'catalog_curated_by': str(promoted_pack.get('catalog_curated_by') or ''),
                        'catalog_approved_at': promoted_pack.get('catalog_approved_at'),
                        'catalog_approved_by': str(promoted_pack.get('catalog_approved_by') or ''),
                        'catalog_deprecated_at': promoted_pack.get('catalog_deprecated_at'),
                        'catalog_deprecated_by': str(promoted_pack.get('catalog_deprecated_by') or ''),
                        'catalog_replaced_by_version': int(promoted_pack.get('catalog_replaced_by_version') or 0),
                        'catalog_is_latest': bool(promoted_pack.get('catalog_is_latest', False)),
                        'promoted_from_pack_id': str(promoted_pack.get('promoted_from_pack_id') or ''),
                        'promoted_from_source': str(promoted_pack.get('promoted_from_source') or ''),
                        'promotion_id': str(promoted_pack.get('promotion_id') or ''),
                        'workspace_id': str(promoted_pack.get('workspace_id') or ''),
                        'environment': str(promoted_pack.get('environment') or ''),
                        'portfolio_family_id': str(promoted_pack.get('portfolio_family_id') or ''),
                        'runtime_family_id': str(promoted_pack.get('runtime_family_id') or ''),
                        'catalog_promoted_at': promoted_pack.get('catalog_promoted_at'),
                        'catalog_promoted_by': str(promoted_pack.get('catalog_promoted_by') or ''),
                        'catalog_share_count': int(promoted_pack.get('catalog_share_count') or 0),
                        'catalog_approval_required': bool(promoted_pack.get('catalog_approval_required', False)),
                        'catalog_required_approvals': int(promoted_pack.get('catalog_required_approvals') or 0),
                        'catalog_approval_count': int(promoted_pack.get('catalog_approval_count') or 0),
                        'catalog_approval_state': str(promoted_pack.get('catalog_approval_state') or ''),
                        'catalog_approval_requested_at': promoted_pack.get('catalog_approval_requested_at'),
                        'catalog_approval_requested_by': str(promoted_pack.get('catalog_approval_requested_by') or ''),
                        'catalog_approval_rejected_at': promoted_pack.get('catalog_approval_rejected_at'),
                        'catalog_approval_rejected_by': str(promoted_pack.get('catalog_approval_rejected_by') or ''),
                        'catalog_approvals': [dict(item or {}) for item in list(promoted_pack.get('catalog_approvals') or [])[:8]],
                        'catalog_release_state': str(promoted_pack.get('catalog_release_state') or 'draft'),
                        'catalog_release_notes': str(promoted_pack.get('catalog_release_notes') or ''),
                        'catalog_release_train_id': str(promoted_pack.get('catalog_release_train_id') or ''),
                        'catalog_release_staged_at': promoted_pack.get('catalog_release_staged_at'),
                        'catalog_release_staged_by': str(promoted_pack.get('catalog_release_staged_by') or ''),
                        'catalog_released_at': promoted_pack.get('catalog_released_at'),
                        'catalog_released_by': str(promoted_pack.get('catalog_released_by') or ''),
                        'catalog_withdrawn_at': promoted_pack.get('catalog_withdrawn_at'),
                        'catalog_withdrawn_by': str(promoted_pack.get('catalog_withdrawn_by') or ''),
                        'catalog_withdrawn_reason': str(promoted_pack.get('catalog_withdrawn_reason') or ''),
                        'catalog_attestation_count': int(promoted_pack.get('catalog_attestation_count') or 0),
                        'catalog_latest_attestation': dict(promoted_pack.get('catalog_latest_attestation') or {}),
                        'catalog_review_state': str(promoted_pack.get('catalog_review_state') or ''),
                        'catalog_review_requested_at': promoted_pack.get('catalog_review_requested_at'),
                        'catalog_review_requested_by': str(promoted_pack.get('catalog_review_requested_by') or ''),
                        'catalog_review_assigned_reviewer': str(promoted_pack.get('catalog_review_assigned_reviewer') or ''),
                        'catalog_review_assigned_role': str(promoted_pack.get('catalog_review_assigned_role') or ''),
                        'catalog_review_claimed_by': str(promoted_pack.get('catalog_review_claimed_by') or ''),
                        'catalog_review_claimed_at': promoted_pack.get('catalog_review_claimed_at'),
                        'catalog_review_last_transition_at': promoted_pack.get('catalog_review_last_transition_at'),
                        'catalog_review_last_transition_by': str(promoted_pack.get('catalog_review_last_transition_by') or ''),
                        'catalog_review_last_transition_action': str(promoted_pack.get('catalog_review_last_transition_action') or ''),
                        'catalog_review_decision_at': promoted_pack.get('catalog_review_decision_at'),
                        'catalog_review_decision_by': str(promoted_pack.get('catalog_review_decision_by') or ''),
                        'catalog_review_decision': str(promoted_pack.get('catalog_review_decision') or ''),
                        'catalog_review_note_count': int(promoted_pack.get('catalog_review_note_count') or 0),
                        'catalog_review_events': [dict(item or {}) for item in list(promoted_pack.get('catalog_review_events') or [])[:12]],
                        'catalog_evidence_package_count': int(promoted_pack.get('catalog_evidence_package_count') or 0),
                        'catalog_latest_evidence_package': dict(promoted_pack.get('catalog_latest_evidence_package') or {}),
                        'catalog_release_bundle_count': int(promoted_pack.get('catalog_release_bundle_count') or 0),
                        'catalog_latest_release_bundle': dict(promoted_pack.get('catalog_latest_release_bundle') or {}),
                        'catalog_dependency_refs': self._baseline_promotion_simulation_custody_catalog_dependency_refs(promoted_pack.get('catalog_dependency_refs') or []),
                        'catalog_conflict_rules': self._baseline_promotion_simulation_custody_catalog_conflict_rules(promoted_pack.get('catalog_conflict_rules') or {}),
                        'catalog_freeze_windows': self._baseline_promotion_simulation_custody_catalog_freeze_windows(promoted_pack.get('catalog_freeze_windows') or []),
                    }
                else:
                    catalog_storage_pack = self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(promoted_pack)
                updated_registry.append(catalog_storage_pack)
                updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry))]
                updated_data = dict(data)
                updated_data['routing_policy_pack_registry'] = updated_registry
                updated_data['last_catalog_promoted_routing_policy_pack'] = {'pack_id': str(promoted_pack.get('pack_id') or ''), 'pack_label': str(promoted_pack.get('pack_label') or ''), 'source': str(promoted_pack.get('source') or ''), 'catalog_entry_id': str(promoted_pack.get('catalog_entry_id') or ''), 'catalog_scope': str(promoted_pack.get('catalog_scope') or ''), 'catalog_scope_key': str(promoted_pack.get('catalog_scope_key') or ''), 'catalog_version_key': str(promoted_pack.get('catalog_version_key') or ''), 'catalog_version': int(promoted_pack.get('catalog_version') or 0), 'catalog_lifecycle_state': str(promoted_pack.get('catalog_lifecycle_state') or ''), 'scenario_count': int(promoted_pack.get('scenario_count') or 0)}
                if latest_simulation:
                    export_state = dict(latest_simulation.get('export_state') or {})
                    export_state['last_catalog_promoted_routing_policy_pack'] = dict(updated_data['last_catalog_promoted_routing_policy_pack'])
                    updated_simulation = dict(latest_simulation)
                    updated_simulation['export_state'] = export_state
                    updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                data = dict(node.get('data') or {})
                compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(promoted_pack)
                result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
        return result

