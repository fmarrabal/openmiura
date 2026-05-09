"""openmiura.application.canvas.service._node_inspector_mixin

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

class _LiveCanvasNodeInspectorMixin:
    """Mixin: node inspector methods on LiveCanvasService."""

    def get_node_inspector(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node_id: str,
        state_key: str = 'default',
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        actor: str = '',
    ) -> dict[str, Any]:
        detail = self.get_document(
            gw,
            canvas_id=canvas_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        scope = dict(detail.get('scope') or {})
        nodes = list(detail.get('nodes') or [])
        node = next((item for item in nodes if str(item.get('node_id') or '') == str(node_id or '')), None)
        if node is None:
            return {'ok': False, 'reason': 'node_not_found', 'canvas_id': canvas_id, 'node_id': node_id, 'scope': scope}
        refs = self._collect_refs(nodes, selected_node_id=node_id)
        overlays = self.get_operational_overlays(
            gw,
            canvas_id=canvas_id,
            selected_node_id=node_id,
            state_key=state_key,
            limit=limit,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        node_type = str(node.get('node_type') or '').strip().lower()
        data = dict(node.get('data') or {})
        related: dict[str, Any] = {}
        if node_type == 'workflow':
            workflow_id = str(data.get('workflow_id') or (refs.get('workflow_ids') or [''])[0] or '').strip()
            if workflow_id:
                related['workflow'] = self.operator_console_service.workflow_console(
                    gw,
                    workflow_id=workflow_id,
                    limit=limit,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
        elif node_type == 'approval':
            approval_id = str(data.get('approval_id') or (refs.get('approval_ids') or [''])[0] or '').strip()
            if approval_id:
                related['approval'] = self._safe_call(
                    gw.audit, 'get_approval', None, approval_id,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
        elif node_type in {'runtime', 'openclaw_runtime'}:
            runtime_id = str(data.get('runtime_id') or '').strip()
            if runtime_id:
                related['runtime'] = self.openclaw_adapter_service.get_runtime(
                    gw,
                    runtime_id=runtime_id,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                related['runtime_runboard'] = self._runtime_board_entry(
                    gw,
                    node=node,
                    scope=scope,
                    limit=limit,
                )
                related['runtime_concurrency'] = dict((related.get('runtime_runboard') or {}).get('concurrency') or {})
                related['runtime_alerts'] = dict((related.get('runtime_runboard') or {}).get('alerts') or {})
                related['runtime_alert_approvals'] = dict((related.get('runtime_runboard') or {}).get('alert_approvals') or {})
                related['runtime_notification_targets'] = dict((related.get('runtime_runboard') or {}).get('notification_targets') or {})
                related['runtime_alert_dispatches'] = dict((related.get('runtime_runboard') or {}).get('alert_dispatches') or {})
                related['runtime_alert_routing'] = dict((related.get('runtime_runboard') or {}).get('alert_routing') or {})
                related['runtime_alert_governance'] = dict((related.get('runtime_runboard') or {}).get('alert_governance') or {})
                related['runtime_alert_governance_versions'] = dict((related.get('runtime_runboard') or {}).get('alert_governance_versions') or {})
                related['runtime_alert_governance_promotion_approvals'] = dict((related.get('runtime_runboard') or {}).get('alert_governance_promotion_approvals') or {})
                related['runtime_alert_governance_bundles'] = dict((related.get('runtime_runboard') or {}).get('alert_governance_bundles') or {})
                related['runtime_alert_governance_portfolios'] = dict((related.get('runtime_runboard') or {}).get('alert_governance_portfolios') or {})
                related['runtime_alert_delivery_jobs'] = dict((related.get('runtime_runboard') or {}).get('alert_delivery_jobs') or {})
        elif node_type in {'baseline_promotion', 'policy_baseline_promotion'}:
            promotion_id = str(data.get('promotion_id') or node.get('label') or '').strip()
            if promotion_id:
                related['baseline_promotion'] = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_baseline_promotion(
                    gw,
                    promotion_id=promotion_id,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                related['baseline_promotion_board'] = self._baseline_promotion_board_entry(
                    gw,
                    node=node,
                    scope=scope,
                    limit=limit,
                )
            latest_simulation = dict(data.get('latest_simulation') or {})
            if latest_simulation:
                evaluated_simulation = self.openclaw_recovery_scheduler_service.evaluate_baseline_promotion_simulation_state(
                    gw,
                    simulation=latest_simulation,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                if evaluated_simulation:
                    data = dict(data)
                    data['latest_simulation'] = evaluated_simulation
                    node = {**dict(node), 'data': data}
                    related['latest_simulation'] = evaluated_simulation
            current_catalog_context = self._baseline_promotion_simulation_custody_catalog_context(
                promotion_detail=dict(related.get('baseline_promotion') or {}),
                node_data=data,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            catalog_packs = self._baseline_promotion_simulation_custody_catalog_policy_packs(
                gw,
                promotion_detail=dict(related.get('baseline_promotion') or {}),
                node_data=data,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            all_bindings = self._baseline_promotion_simulation_custody_catalog_policy_bindings(
                gw,
                tenant_id=scope.get('tenant_id'),
            )
            effective_binding = self._baseline_promotion_simulation_custody_effective_catalog_binding(
                all_bindings,
                context={**current_catalog_context, 'canvas_id': canvas_id, 'node_id': node_id},
                catalog_packs=catalog_packs,
            )
            enriched_catalog_packs = []
            analytics_context = {**current_catalog_context, 'canvas_id': canvas_id, 'node_id': node_id}
            for item in list(catalog_packs or []):
                current_item = dict(item or {})
                current_item.update(self._baseline_promotion_simulation_custody_catalog_pack_bindings(current_item, bindings=all_bindings, effective_binding=effective_binding))
                current_item['catalog_compliance_summary'] = self._baseline_promotion_simulation_custody_catalog_pack_compliance(current_item, context=analytics_context, bindings=all_bindings, effective_binding=effective_binding, node_data=data)
                current_item['catalog_analytics_summary'] = self._baseline_promotion_simulation_custody_catalog_pack_analytics(current_item, context=analytics_context, bindings=all_bindings, effective_binding=effective_binding, node_data=data)
                enriched_catalog_packs.append(current_item)
            catalog_summary = self._baseline_promotion_simulation_custody_catalog_summary(enriched_catalog_packs)
            compliance_summary = self._baseline_promotion_simulation_custody_catalog_compliance_summary(enriched_catalog_packs, context=analytics_context, bindings=all_bindings, effective_binding=effective_binding, node_data=data)
            analytics_summary = self._baseline_promotion_simulation_custody_catalog_analytics_summary(enriched_catalog_packs, context=analytics_context, bindings=all_bindings, effective_binding=effective_binding, node_data=data)
            operator_dashboard = self._baseline_promotion_simulation_custody_catalog_operator_dashboard(enriched_catalog_packs, context=analytics_context, bindings=all_bindings, effective_binding=effective_binding, node_data=data)
            service_packs = self._baseline_promotion_simulation_custody_organizational_catalog_service_packs(
                gw,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            enriched_service_packs = []
            for item in list(service_packs or []):
                current_item = dict(item or {})
                current_item.update(self._baseline_promotion_simulation_custody_catalog_pack_bindings(current_item, bindings=all_bindings, effective_binding=effective_binding))
                current_item['catalog_compliance_summary'] = self._baseline_promotion_simulation_custody_catalog_pack_compliance(current_item, context=analytics_context, bindings=all_bindings, effective_binding=effective_binding, node_data=data)
                current_item['catalog_analytics_summary'] = self._baseline_promotion_simulation_custody_catalog_pack_analytics(current_item, context=analytics_context, bindings=all_bindings, effective_binding=effective_binding, node_data=data)
                enriched_service_packs.append(current_item)
            organizational_summary = self._baseline_promotion_simulation_custody_organizational_catalog_service_summary(
                enriched_service_packs,
                tenant_id=scope.get('tenant_id'),
                effective_binding=effective_binding,
            )
            data = dict(data)
            data['routing_policy_pack_catalog'] = [self._compact_baseline_promotion_simulation_routing_policy_pack(item) for item in list(enriched_catalog_packs)[:6]]
            data['routing_policy_pack_catalog_summary'] = catalog_summary
            data['routing_policy_pack_bindings'] = [self._compact_baseline_promotion_simulation_catalog_binding(item) for item in list(dict(node.get('data') or {}).get('routing_policy_pack_bindings') or []) if isinstance(item, dict)][:6]
            data['routing_policy_pack_binding_events'] = [self._compact_baseline_promotion_simulation_catalog_binding_event(item) for item in list(dict(node.get('data') or {}).get('routing_policy_pack_binding_events') or []) if isinstance(item, dict)][:6]
            data['routing_policy_pack_binding_summary'] = self._baseline_promotion_simulation_custody_catalog_binding_summary(all_bindings)
            data['routing_policy_pack_compliance_summary'] = compliance_summary
            data['routing_policy_pack_analytics_summary'] = analytics_summary
            data['routing_policy_pack_operator_dashboard'] = operator_dashboard
            data['routing_policy_pack_organizational_catalog_service'] = {
                'service_id': str(organizational_summary.get('service_id') or ''),
                'entries': [self._compact_baseline_promotion_simulation_routing_policy_pack(item) for item in list(enriched_service_packs)[:6]],
                'summary': organizational_summary,
            }
            data['routing_policy_pack_organizational_catalog_service_summary'] = organizational_summary
            data['routing_policy_pack_organizational_catalog_reconciliation_summary'] = {
                'overall_status': str(organizational_summary.get('overall_publication_status') or ''),
                'healthy_publication_count': int(organizational_summary.get('healthy_publication_count') or 0),
                'drifted_publication_count': int(organizational_summary.get('drifted_publication_count') or 0),
                'publication_issue_counts': dict(organizational_summary.get('publication_issue_counts') or {}),
                'latest_reconciliation_report': dict(organizational_summary.get('latest_reconciliation_report') or {}),
            }
            data['effective_routing_policy_pack_binding'] = self._compact_baseline_promotion_simulation_catalog_binding(effective_binding)
            data['effective_routing_policy_pack_compliance'] = dict(compliance_summary.get('effective_pack') or {})
            node = {**dict(node), 'data': data}
            related['routing_policy_pack_catalog'] = {'items': data['routing_policy_pack_catalog'], 'summary': catalog_summary}
            related['routing_policy_pack_bindings'] = {'items': data['routing_policy_pack_bindings'], 'summary': data['routing_policy_pack_binding_summary'], 'effective_binding': data['effective_routing_policy_pack_binding']}
            related['routing_policy_pack_compliance'] = {'summary': compliance_summary, 'effective': data['effective_routing_policy_pack_compliance']}
            related['routing_policy_pack_analytics'] = {'summary': analytics_summary, 'dashboard': operator_dashboard}
            related['routing_policy_pack_organizational_catalog_service'] = {
                'entries': list((data.get('routing_policy_pack_organizational_catalog_service') or {}).get('entries') or []),
                'summary': organizational_summary,
                'reconciliation_summary': dict(data.get('routing_policy_pack_organizational_catalog_reconciliation_summary') or {}),
            }
        available_actions = self._node_available_actions(node, related=related)
        action_prechecks = {
            action_name: self._node_action_precheck(node=node, related=related, action=action_name, actor=actor)
            for action_name in available_actions
        }
        node_timeline = self.get_node_timeline(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            limit=limit,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'node': node,
            'references': refs,
            'related': related,
            'available_actions': available_actions,
            'action_prechecks': action_prechecks,
            'overlay_focus': overlays.get('overlays') if overlays.get('ok') else {},
            'node_timeline': node_timeline.get('items') if node_timeline.get('ok') else [],
            'scope': scope,
        }

    def _node_available_actions(self, node: dict[str, Any], *, related: dict[str, Any] | None = None) -> list[str]:
        node_type = str(node.get('node_type') or '').strip().lower()
        if node_type == 'workflow':
            workflow = dict((related or {}).get('workflow', {}).get('workflow') or {})
            status = str(workflow.get('status') or '').strip().lower()
            if status in {'succeeded', 'failed', 'rejected', 'cancelled'}:
                return ['run']
            available = list(workflow.get('available_actions') or [])
            return available or ['cancel']
        if node_type == 'approval':
            approval = dict((related or {}).get('approval') or {})
            available = list(approval.get('available_actions') or [])
            return available or ['claim', 'approve', 'reject']
        if node_type in {'runtime', 'openclaw_runtime'}:
            return ['health_check', 'ping', 'dry_run', 'cancel_run', 'retry_run', 'manual_close', 'reconcile_run', 'poll_run', 'recover_stale_runs', 'ack_alert', 'silence_alert', 'escalate_alert', 'dispatch_alert_notification', 'approve_alert_escalation', 'reject_alert_escalation', 'simulate_alert_governance', 'activate_alert_governance', 'rollback_alert_governance', 'approve_governance_promotion', 'reject_governance_promotion', 'simulate_portfolio_calendar', 'detect_portfolio_drift', 'report_portfolio_policy_conformance', 'report_portfolio_policy_baseline_drift', 'reconcile_portfolio_custody_anchors', 'validate_portfolio_providers', 'attest_portfolio_custody_anchor', 'request_portfolio_policy_deviation_exception', 'approve_portfolio_policy_deviation_exception', 'reject_portfolio_policy_deviation_exception', 'request_portfolio_approval', 'approve_portfolio_approval', 'reject_portfolio_approval', 'export_portfolio_attestation', 'export_portfolio_postmortem', 'export_portfolio_evidence_package', 'verify_portfolio_evidence_artifact', 'restore_portfolio_evidence_artifact', 'prune_portfolio_evidence_packages']
        if node_type in {'baseline_promotion', 'policy_baseline_promotion'}:
            return ['simulate', 'approve_simulation', 'reject_simulation', 'export_simulation_attestation', 'export_simulation_review_audit', 'export_simulation_evidence_package', 'verify_simulation_evidence_package', 'restore_simulation_evidence_package', 'reconcile_simulation_evidence_custody', 'simulate_simulation_custody_routing', 'replay_simulation_custody_routing', 'save_simulation_custody_routing_policy_pack', 'promote_simulation_custody_routing_policy_pack_to_registry', 'promote_simulation_custody_routing_policy_pack_to_catalog', 'request_cataloged_simulation_custody_routing_policy_pack_review', 'claim_cataloged_simulation_custody_routing_policy_pack_review', 'add_cataloged_simulation_custody_routing_policy_pack_review_note', 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision', 'request_cataloged_simulation_custody_routing_policy_pack_approval', 'reject_cataloged_simulation_custody_routing_policy_pack_approval', 'curate_cataloged_simulation_custody_routing_policy_pack', 'approve_cataloged_simulation_custody_routing_policy_pack', 'deprecate_cataloged_simulation_custody_routing_policy_pack', 'export_cataloged_simulation_custody_routing_policy_pack_attestation', 'export_cataloged_simulation_custody_routing_policy_pack_evidence_package', 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle', 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report', 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report', 'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service', 'withdraw_cataloged_simulation_custody_routing_policy_pack_from_organizational_catalog_service', 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot', 'reconcile_organizational_simulation_custody_routing_policy_pack_catalog_service', 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_reconciliation_report', 'bind_cataloged_simulation_custody_routing_policy_pack_effective_policy', 'unbind_cataloged_simulation_custody_routing_policy_pack_effective_policy', 'stage_cataloged_simulation_custody_routing_policy_pack_release', 'release_cataloged_simulation_custody_routing_policy_pack', 'advance_cataloged_simulation_custody_routing_policy_pack_rollout', 'pause_cataloged_simulation_custody_routing_policy_pack_rollout', 'resume_cataloged_simulation_custody_routing_policy_pack_rollout', 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_release', 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release', 'withdraw_cataloged_simulation_custody_routing_policy_pack_release', 'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack', 'share_registered_simulation_custody_routing_policy_pack', 'share_cataloged_simulation_custody_routing_policy_pack', 'acknowledge_simulation_custody_alert', 'mute_simulation_custody_alert', 'unmute_simulation_custody_alert', 'resolve_simulation_custody_alert', 'claim_simulation_custody_alert', 'assign_simulation_custody_alert', 'release_simulation_custody_alert', 'reroute_simulation_custody_alert', 'handoff_simulation_custody_alert', 'create_rollout', 'create_and_approve_rollout', 'approve', 'reject', 'advance', 'rollback', 'pause', 'resume', 'export_attestation', 'export_postmortem']
        return []

    @staticmethod
    def _node_references(node: dict[str, Any]) -> dict[str, set[str]]:
        data = dict(node.get('data') or {})
        refs = {
            'workflow_ids': set(),
            'approval_ids': set(),
            'session_ids': set(),
            'trace_ids': set(),
            'tool_names': set(),
            'secret_refs': set(),
            'policy_names': set(),
        }
        mapping = {
            'workflow_id': 'workflow_ids',
            'approval_id': 'approval_ids',
            'session_id': 'session_ids',
            'trace_id': 'trace_ids',
            'tool_name': 'tool_names',
            'secret_ref': 'secret_refs',
            'policy_name': 'policy_names',
        }
        for key, bucket_name in mapping.items():
            value = str(data.get(key) or '').strip()
            if value:
                refs[bucket_name].add(value)
        node_type = str(node.get('node_type') or '').strip().lower()
        label = str(node.get('label') or '').strip()
        if node_type == 'workflow' and label and not refs['workflow_ids']:
            refs['workflow_ids'].add(label)
        if node_type == 'approval' and label and not refs['approval_ids']:
            refs['approval_ids'].add(label)
        if node_type == 'tool' and label and not refs['tool_names']:
            refs['tool_names'].add(label)
        if node_type == 'policy' and label and not refs['policy_names']:
            refs['policy_names'].add(label)
        return refs

    def _collect_refs(self, nodes: list[dict[str, Any]], *, selected_node_id: str | None = None) -> dict[str, list[str]]:
        buckets = {key: set() for key in self._node_references({}).keys()}
        chosen = [node for node in nodes if not selected_node_id or str(node.get('node_id') or '') == str(selected_node_id)]
        if not chosen:
            chosen = list(nodes or [])
        for node in chosen:
            refs = self._node_references(node)
            for key, values in refs.items():
                buckets.setdefault(key, set()).update(str(item).strip() for item in values if str(item).strip())
        return {key: sorted(values) for key, values in buckets.items()}

