from __future__ import annotations

import time
from collections import Counter
import json
import uuid
from typing import Any

from openmiura.application.packaging import PackagingHardeningService

from openmiura.application.costs import CostGovernanceService
from openmiura.application.operator import OperatorConsoleService
from openmiura.application.openclaw import OpenClawAdapterService, OpenClawRecoverySchedulerService
from openmiura.application.secrets import SecretGovernanceService
from openmiura.core.contracts import AdminGatewayLike


class LiveCanvasService:
    _CANVAS_LIMITS = PackagingHardeningService.DEFAULT_HARDENING['canvas']
    MAX_DOCUMENTS_PER_SCOPE = int(_CANVAS_LIMITS['max_documents_per_scope'])
    MAX_NODES_PER_CANVAS = int(_CANVAS_LIMITS['max_nodes_per_canvas'])
    MAX_EDGES_PER_CANVAS = int(_CANVAS_LIMITS['max_edges_per_canvas'])
    MAX_VIEWS_PER_CANVAS = int(_CANVAS_LIMITS['max_views_per_canvas'])
    MAX_PAYLOAD_CHARS = int(_CANVAS_LIMITS['max_payload_chars'])
    MAX_COMMENT_CHARS = int(_CANVAS_LIMITS['max_comment_chars'])
    MAX_SNAPSHOT_BYTES = int(_CANVAS_LIMITS['max_snapshot_bytes'])

    _DEFAULT_TOGGLES = {
        'policy': True,
        'cost': True,
        'traces': True,
        'failures': True,
        'approvals': True,
        'secrets': True,
    }

    def __init__(
        self,
        *,
        cost_governance_service: CostGovernanceService | None = None,
        operator_console_service: OperatorConsoleService | None = None,
        secret_governance_service: SecretGovernanceService | None = None,
        openclaw_adapter_service: OpenClawAdapterService | None = None,
        openclaw_recovery_scheduler_service: OpenClawRecoverySchedulerService | None = None,
    ) -> None:
        self.cost_governance_service = cost_governance_service or CostGovernanceService()
        self.operator_console_service = operator_console_service or OperatorConsoleService()
        self.secret_governance_service = secret_governance_service or SecretGovernanceService()
        self.openclaw_adapter_service = openclaw_adapter_service or OpenClawAdapterService()
        self.openclaw_recovery_scheduler_service = openclaw_recovery_scheduler_service or OpenClawRecoverySchedulerService(openclaw_adapter_service=self.openclaw_adapter_service)

    @staticmethod
    def _payload_size(payload: Any) -> int:
        try:
            return len(json.dumps(payload, ensure_ascii=False))
        except Exception:
            return len(str(payload))

    @staticmethod
    
    def _minimize_node_data_for_storage(payload: dict[str, Any] | None, *, node_type: str) -> dict[str, Any]:
        data = dict(payload or {})
        if node_type in {'baseline_promotion', 'policy_baseline_promotion'}:
            minimal_registry_snapshot: list[dict[str, Any]] = []
            last_simulation_routing_replay = dict(data.get('last_simulation_routing_replay') or {})
            data.pop('last_simulation_routing_replay', None)
            data.pop('routing_policy_pack_catalog', None)
            data.pop('routing_policy_pack_catalog_summary', None)
            data.pop('routing_policy_pack_compliance_summary', None)
            data.pop('effective_routing_policy_pack_compliance', None)
            data.pop('routing_policy_pack_analytics_summary', None)
            data.pop('routing_policy_pack_operator_dashboard', None)
            saved_routing_policy_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
            saved_routing_policy_packs = saved_routing_policy_packs[-1:]
            last_saved_routing_policy_pack = dict(data.get('last_saved_routing_policy_pack') or {})
            last_promoted_routing_policy_pack = dict(data.get('last_promoted_routing_policy_pack') or {})
            last_catalog_promoted_routing_policy_pack = dict(data.get('last_catalog_promoted_routing_policy_pack') or {})
            last_shared_routing_policy_pack = dict(data.get('last_shared_routing_policy_pack') or {})
            last_saved_routing_policy_pack = (
                LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        last_saved_routing_policy_pack
                    )
                )
                if last_saved_routing_policy_pack
                else {}
            )
            last_promoted_routing_policy_pack = (
                LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        last_promoted_routing_policy_pack
                    )
                )
                if last_promoted_routing_policy_pack
                else {}
            )
            last_catalog_promoted_routing_policy_pack = (
                LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        last_catalog_promoted_routing_policy_pack
                    )
                )
                if last_catalog_promoted_routing_policy_pack
                else {}
            )
            last_shared_routing_policy_pack = (
                LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        last_shared_routing_policy_pack
                    )
                )
                if last_shared_routing_policy_pack
                else {}
            )
            for key in [
                'saved_routing_policy_packs',
                'last_saved_routing_policy_pack',
                'last_promoted_routing_policy_pack',
                'last_catalog_promoted_routing_policy_pack',
            ]:
                data.pop(key, None)
            latest_simulation = dict(data.get('latest_simulation') or {})
            if latest_simulation:
                export_state = dict(latest_simulation.get('export_state') or {})
                compact_latest_routing_replay = LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_replay(
                        export_state.get('latest_routing_replay') or {}
                    )
                )
                if 'scenario_count' not in compact_latest_routing_replay and last_simulation_routing_replay:
                    fallback_count = int(last_simulation_routing_replay.get('scenario_count') or 0)
                    fallback_pack = LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                            last_simulation_routing_replay.get('applied_pack') or {}
                        )
                    )
                    if fallback_count > 0 or fallback_pack:
                        compact_latest_routing_replay = {
                            **compact_latest_routing_replay,
                            'scenario_count': fallback_count,
                        }
                        if fallback_pack and not compact_latest_routing_replay.get('applied_pack'):
                            compact_latest_routing_replay['applied_pack'] = fallback_pack
                export_state['latest_routing_replay'] = compact_latest_routing_replay
                export_state['routing_policy_what_if_presets'] = [
                    LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item)
                    )
                    for item in list(export_state.get('routing_policy_what_if_presets') or [])[:4]
                    if isinstance(item, dict)
                ]
                export_state['saved_routing_policy_packs'] = [
                    LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item)
                    )
                    for item in list(export_state.get('saved_routing_policy_packs') or saved_routing_policy_packs or [])[:4]
                    if isinstance(item, dict)
                ]
                export_state['routing_policy_pack_registry'] = [
                    LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item)
                    )
                    for item in list(export_state.get('routing_policy_pack_registry') or data.get('routing_policy_pack_registry') or [])[:4]
                    if isinstance(item, dict)
                ]
                export_state['shared_routing_policy_packs'] = [
                    LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item)
                    )
                    for item in list(export_state.get('shared_routing_policy_packs') or [])[:4]
                    if isinstance(item, dict)
                ]
                export_state['custody_guard'] = LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_custody_guard(
                        export_state.get('custody_guard') or {}
                    )
                )
                export_state['custody_active_alert'] = LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_custody_active_alert(
                        export_state.get('custody_active_alert') or {}
                    )
                )
                export_state['last_saved_routing_policy_pack'] = LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        export_state.get('last_saved_routing_policy_pack') or last_saved_routing_policy_pack or {}
                    )
                )
                export_state['last_promoted_routing_policy_pack'] = LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        export_state.get('last_promoted_routing_policy_pack') or last_promoted_routing_policy_pack or {}
                    )
                )
                export_state['last_catalog_promoted_routing_policy_pack'] = LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        export_state.get('last_catalog_promoted_routing_policy_pack') or last_catalog_promoted_routing_policy_pack or {}
                    )
                )
                export_state['last_shared_routing_policy_pack'] = LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        export_state.get('last_shared_routing_policy_pack') or last_shared_routing_policy_pack or {}
                    )
                )
                request = dict(latest_simulation.get('request') or {})
                compact_request = {
                    'mode': str(request.get('mode') or ''),
                    'actor': str(request.get('actor') or request.get('requested_by') or ''),
                    'catalog_id': str(request.get('catalog_id') or latest_simulation.get('catalog_id') or ''),
                    'catalog_name': str(request.get('catalog_name') or latest_simulation.get('catalog_name') or ''),
                    'version': (request.get('version') if request else None),
                    'candidate_catalog_version': str(request.get('candidate_catalog_version') or latest_simulation.get('candidate_catalog_version') or ''),
                    'tenant_id': str(request.get('tenant_id') or ''),
                    'workspace_id': str(request.get('workspace_id') or ''),
                    'environment': str(request.get('environment') or ''),
                    'candidate_baselines': dict(request.get('candidate_baselines') or latest_simulation.get('candidate_baselines') or {}),
                    'rollout_policy': dict(request.get('rollout_policy') or {}),
                    'gate_policy': dict(request.get('gate_policy') or {}),
                    'rollback_policy': dict(request.get('rollback_policy') or {}),
                    'reason': str(request.get('reason') or ''),
                    'auto_approve': bool(request.get('auto_approve', False)),
                }
                review = dict(latest_simulation.get('review') or {})
                compact_review = {}
                if review:
                    compact_review = {
                        'required': bool(review.get('required')),
                        'approved': bool(review.get('approved')),
                        'rejected': bool(review.get('rejected')),
                        'reviewed_at': review.get('reviewed_at'),
                        'review_count': int(review.get('review_count') or len(list(review.get('reviews') or [])) or 0),
                        'reviews': [
                            {
                                'layer_id': str(item.get('layer_id') or ''),
                                'actor': str(item.get('actor') or ''),
                                'decision': str(item.get('decision') or ''),
                                'reason': str(item.get('reason') or '')[:160],
                                'requested_role': str(item.get('requested_role') or ''),
                                'at': item.get('at'),
                            }
                            for item in list(review.get('reviews') or [])[:8]
                            if isinstance(item, dict)
                        ],
                    }
                simulation_source = dict(latest_simulation.get('simulation_source') or {})
                compact_simulation_source = {}
                if simulation_source:
                    compact_simulation_source = {
                        'kind': str(simulation_source.get('kind') or ''),
                        'promotion_id': str(simulation_source.get('promotion_id') or ''),
                        'catalog_id': str(simulation_source.get('catalog_id') or ''),
                        'release_id': str(simulation_source.get('release_id') or ''),
                    }
                review_state = dict(latest_simulation.get('review_state') or {})
                compact_review_state = {}
                if review_state:
                    compact_review_state = {
                        'overall_status': str(review_state.get('overall_status') or ''),
                        'required': bool(review_state.get('required')),
                        'approved': bool(review_state.get('approved')),
                        'rejected': bool(review_state.get('rejected')),
                        'review_count': int(review_state.get('review_count') or 0),
                        'approved_count': int(review_state.get('approved_count') or 0),
                        'rejected_count': int(review_state.get('rejected_count') or 0),
                        'pending_count': int(review_state.get('pending_count') or 0),
                        'mode': str(review_state.get('mode') or ''),
                        'allow_self_review': bool(review_state.get('allow_self_review', True)),
                        'require_reason': bool(review_state.get('require_reason', False)),
                        'block_on_rejection': bool(review_state.get('block_on_rejection', True)),
                        'pending_layers': [str(item) for item in list(review_state.get('pending_layers') or []) if str(item)][:6],
                        'next_layer': dict(review_state.get('next_layer') or {}),
                        'layers': [
                            {
                                'layer_id': str(item.get('layer_id') or ''),
                                'label': str(item.get('label') or ''),
                                'requested_role': str(item.get('requested_role') or ''),
                                'required': bool(item.get('required', True)),
                            }
                            for item in list(review_state.get('layers') or [])[:8]
                            if isinstance(item, dict)
                        ],
                        'items': [
                            {
                                'review_id': str(item.get('review_id') or ''),
                                'layer_id': str(item.get('layer_id') or ''),
                                'label': str(item.get('label') or ''),
                                'requested_role': str(item.get('requested_role') or ''),
                                'decision': str(item.get('decision') or ''),
                                'actor': str(item.get('actor') or ''),
                                'reason': str(item.get('reason') or '')[:160],
                                'created_at': item.get('created_at'),
                                'decided_at': item.get('decided_at'),
                            }
                            for item in list(review_state.get('items') or [])[:8]
                            if isinstance(item, dict)
                        ],
                    }
                validation = dict(latest_simulation.get('validation') or {})
                compact_validation = {}
                if validation:
                    compact_validation = {
                        'status': str(validation.get('status') or ''),
                        'errors': [str(item) for item in list(validation.get('errors') or []) if str(item)][:6],
                    }
                compact_latest_simulation = {
                    'simulation_id': str(latest_simulation.get('simulation_id') or ''),
                    'kind': str(latest_simulation.get('kind') or ''),
                    'simulated_at': latest_simulation.get('simulated_at'),
                    'simulated_by': str(latest_simulation.get('simulated_by') or ''),
                    'mode': str(latest_simulation.get('mode') or ''),
                    'catalog_id': str(latest_simulation.get('catalog_id') or compact_request.get('catalog_id') or ''),
                    'catalog_name': str(latest_simulation.get('catalog_name') or compact_request.get('catalog_name') or ''),
                    'candidate_catalog_version': str(latest_simulation.get('candidate_catalog_version') or compact_request.get('version') or ''),
                    'summary': dict(latest_simulation.get('summary') or {}),
                    'simulation_status': str(latest_simulation.get('simulation_status') or ''),
                    'simulation_source': compact_simulation_source,
                    'stale': bool(latest_simulation.get('stale', False)),
                    'expired': bool(latest_simulation.get('expired', False)),
                    'blocked': bool(latest_simulation.get('blocked', False)),
                    'reviewed_at': latest_simulation.get('reviewed_at'),
                    'request': compact_request,
                    'review': compact_review,
                    'review_state': compact_review_state,
                    'validation': compact_validation,
                    'observed_versions': dict(latest_simulation.get('observed_versions') or {}),
                    'source_observed_versions': dict(latest_simulation.get('source_observed_versions') or latest_simulation.get('observed_versions') or {}),
                    'fingerprints': dict(latest_simulation.get('fingerprints') or {}),
                    'source_fingerprints': dict(latest_simulation.get('source_fingerprints') or latest_simulation.get('fingerprints') or {}),
                    'export_state': export_state,
                }
                data['latest_simulation'] = compact_latest_simulation
            if saved_routing_policy_packs:
                data['saved_routing_policy_packs'] = [
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item)
                    for item in saved_routing_policy_packs[:6]
                ]
            if last_saved_routing_policy_pack:
                data['last_saved_routing_policy_pack'] = LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        last_saved_routing_policy_pack
                    )
                )
            if last_promoted_routing_policy_pack:
                data['last_promoted_routing_policy_pack'] = LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        last_promoted_routing_policy_pack
                    )
                )
            if last_catalog_promoted_routing_policy_pack:
                data['last_catalog_promoted_routing_policy_pack'] = LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        last_catalog_promoted_routing_policy_pack
                    )
                )
            if last_shared_routing_policy_pack:
                data['last_shared_routing_policy_pack'] = LiveCanvasService._prune_canvas_payload(
                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(
                        last_shared_routing_policy_pack
                    )
                )
            registry = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
            if registry:
                rich_registry = []
                minimal_registry = []
                for item in registry[:8]:
                    trimmed = dict(item)
                    trimmed['catalog_approvals'] = [
                        {
                            'approval_id': str(entry.get('approval_id') or ''),
                            'decision': str(entry.get('decision') or ''),
                            'actor': str(entry.get('actor') or ''),
                            'role': str(entry.get('role') or ''),
                            'at': entry.get('at'),
                            'note': str(entry.get('note') or '')[:80],
                        }
                        for entry in list(trimmed.get('catalog_approvals') or [])[:4]
                        if isinstance(entry, dict)
                    ]
                    trimmed['catalog_review_events'] = [
                        {
                            'event_id': str(entry.get('event_id') or ''),
                            'event_type': str(entry.get('event_type') or ''),
                            'state': str(entry.get('state') or ''),
                            'actor': str(entry.get('actor') or ''),
                            'role': str(entry.get('role') or ''),
                            'at': entry.get('at'),
                            'note': str(entry.get('note') or '')[:80],
                            'decision': str(entry.get('decision') or ''),
                            'assigned_reviewer': str(entry.get('assigned_reviewer') or '')[:80],
                        }
                        for entry in list(trimmed.get('catalog_review_events') or [])[:4]
                        if isinstance(entry, dict)
                    ]
                    rich_registry.append(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(trimmed))
                    minimal_registry.append({
                        'pack_id': str(trimmed.get('pack_id') or ''),
                        'pack_label': str(trimmed.get('pack_label') or trimmed.get('label') or ''),
                        'source': str(trimmed.get('source') or 'registry'),
                        'scenario_count': int(trimmed.get('scenario_count') or len(list(trimmed.get('comparison_policies') or [])) or 0),
                        'registry_entry_id': str(trimmed.get('registry_entry_id') or ''),
                        'registry_scope': str(trimmed.get('registry_scope') or ''),
                        'catalog_entry_id': str(trimmed.get('catalog_entry_id') or ''),
                        'catalog_scope': str(trimmed.get('catalog_scope') or ''),
                        'catalog_scope_key': str(trimmed.get('catalog_scope_key') or ''),
                        'catalog_version_key': str(trimmed.get('catalog_version_key') or ''),
                        'catalog_version': int(trimmed.get('catalog_version') or 0),
                        'workspace_id': str(trimmed.get('workspace_id') or ''),
                        'environment': str(trimmed.get('environment') or ''),
                        'catalog_lifecycle_state': str(trimmed.get('catalog_lifecycle_state') or 'draft'),
                        'catalog_approval_state': str(trimmed.get('catalog_approval_state') or ''),
                        'catalog_review_state': str(trimmed.get('catalog_review_state') or ''),
                        'catalog_review_assigned_reviewer': str(trimmed.get('catalog_review_assigned_reviewer') or ''),
                        'catalog_review_assigned_role': str(trimmed.get('catalog_review_assigned_role') or ''),
                        'catalog_review_claimed_by': str(trimmed.get('catalog_review_claimed_by') or ''),
                        'catalog_review_last_transition_at': trimmed.get('catalog_review_last_transition_at'),
                        'catalog_review_last_transition_by': str(trimmed.get('catalog_review_last_transition_by') or ''),
                        'catalog_review_last_transition_action': str(trimmed.get('catalog_review_last_transition_action') or ''),
                        'catalog_review_events': [
                            {
                                'event_id': str(item.get('event_id') or ''),
                                'event_type': str(item.get('event_type') or ''),
                                'state': str(item.get('state') or ''),
                                'actor': str(item.get('actor') or ''),
                                'role': str(item.get('role') or ''),
                                'at': item.get('at'),
                                'note': str(item.get('note') or '')[:80],
                                'decision': str(item.get('decision') or ''),
                            }
                            for item in list(trimmed.get('catalog_review_events') or [])[:6]
                            if isinstance(item, dict)
                        ],
                        'catalog_release_state': str(trimmed.get('catalog_release_state') or 'draft'),
                        'catalog_rollout_policy': LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_policy(trimmed.get('catalog_rollout_policy') or {}),
                        'catalog_rollout_state': str(trimmed.get('catalog_rollout_state') or ''),
                        'catalog_rollout_enabled': bool(trimmed.get('catalog_rollout_enabled', False)),
                        'catalog_rollout_current_wave_index': int(trimmed.get('catalog_rollout_current_wave_index') or 0),
                        'catalog_rollout_completed_wave_count': int(trimmed.get('catalog_rollout_completed_wave_count') or 0),
                        'catalog_rollout_paused': bool(trimmed.get('catalog_rollout_paused', False)),
                        'catalog_rollout_frozen': bool(trimmed.get('catalog_rollout_frozen', False)),
                        'catalog_rollout_targets': [
                            {
                                'target_key': str(item.get('target_key') or ''),
                                'promotion_id': str(item.get('promotion_id') or ''),
                                'workspace_id': str(item.get('workspace_id') or ''),
                                'environment': str(item.get('environment') or ''),
                                'released': bool(item.get('released', False)),
                                'released_wave_index': int(item.get('released_wave_index') or 0),
                            }
                            for item in list(trimmed.get('catalog_rollout_targets') or [])[:12]
                            if isinstance(item, dict)
                        ],
                        'catalog_rollout_waves': [
                            {
                                'wave_index': int(item.get('wave_index') or 0),
                                'status': str(item.get('status') or ''),
                                'target_keys': [str(key) for key in list(item.get('target_keys') or []) if str(key)][:12],
                            }
                            for item in list(trimmed.get('catalog_rollout_waves') or [])[:8]
                            if isinstance(item, dict)
                        ],
                        'catalog_rollout_policy': LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_policy(trimmed.get('catalog_rollout_policy') or {}),
                        'catalog_dependency_refs': LiveCanvasService._baseline_promotion_simulation_custody_catalog_dependency_refs(trimmed.get('catalog_dependency_refs') or []),
                        'catalog_conflict_rules': LiveCanvasService._baseline_promotion_simulation_custody_catalog_conflict_rules(trimmed.get('catalog_conflict_rules') or {}),
                        'catalog_freeze_windows': LiveCanvasService._baseline_promotion_simulation_custody_catalog_freeze_windows(trimmed.get('catalog_freeze_windows') or []),
                        'catalog_dependency_summary': dict(trimmed.get('catalog_dependency_summary') or {}),
                        'catalog_conflict_summary': dict(trimmed.get('catalog_conflict_summary') or {}),
                        'catalog_freeze_summary': dict(trimmed.get('catalog_freeze_summary') or {}),
                        'catalog_release_guard': dict(trimmed.get('catalog_release_guard') or {}),
                        'catalog_approval_required': bool(trimmed.get('catalog_approval_required', False)),
                        'catalog_required_approvals': int(trimmed.get('catalog_required_approvals') or 0),
                        'catalog_approval_count': int(trimmed.get('catalog_approval_count') or 0),
                        'catalog_approvals': [
                            {
                                'approval_id': str(item.get('approval_id') or ''),
                                'decision': str(item.get('decision') or ''),
                                'actor': str(item.get('actor') or ''),
                                'role': str(item.get('role') or ''),
                                'at': item.get('at'),
                                'note': str(item.get('note') or '')[:80],
                            }
                            for item in list(trimmed.get('catalog_approvals') or [])[:8]
                            if isinstance(item, dict)
                        ],
                        'catalog_attestation_count': int(trimmed.get('catalog_attestation_count') or 0),
                        'catalog_evidence_package_count': int(trimmed.get('catalog_evidence_package_count') or 0),
                        'catalog_release_bundle_count': int(trimmed.get('catalog_release_bundle_count') or 0),
                        'catalog_latest_attestation': LiveCanvasService._compact_baseline_promotion_simulation_export_report(trimmed.get('catalog_latest_attestation') or {}),
                        'catalog_latest_evidence_package': LiveCanvasService._compact_baseline_promotion_simulation_export_report(trimmed.get('catalog_latest_evidence_package') or {}),
                        'catalog_latest_release_bundle': LiveCanvasService._compact_baseline_promotion_simulation_export_report(trimmed.get('catalog_latest_release_bundle') or {}),
                        'catalog_latest_compliance_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(trimmed.get('catalog_latest_compliance_report') or {}),
                        'catalog_replay_count': int(trimmed.get('catalog_replay_count') or 0),
                        'catalog_binding_count': int(trimmed.get('catalog_binding_count') or 0),
                        'catalog_share_count': int(trimmed.get('catalog_share_count') or 0),
                        'catalog_last_shared_at': trimmed.get('catalog_last_shared_at'),
                        'catalog_last_shared_by': str(trimmed.get('catalog_last_shared_by') or ''),
                        'catalog_analytics_report_count': int(trimmed.get('catalog_analytics_report_count') or 0),
                        'catalog_latest_analytics_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(trimmed.get('catalog_latest_analytics_report') or {}),
                        'catalog_supersedence_state': str(trimmed.get('catalog_supersedence_state') or ''),
                        'catalog_superseded_by_entry_id': str(trimmed.get('catalog_superseded_by_entry_id') or ''),
                        'catalog_superseded_by_version': int(trimmed.get('catalog_superseded_by_version') or 0),
                        'catalog_supersedes_entry_id': str(trimmed.get('catalog_supersedes_entry_id') or ''),
                        'catalog_supersedes_version': int(trimmed.get('catalog_supersedes_version') or 0),
                        'catalog_restored_from_entry_id': str(trimmed.get('catalog_restored_from_entry_id') or ''),
                        'catalog_restored_from_version': int(trimmed.get('catalog_restored_from_version') or 0),
                        'catalog_restored_at': trimmed.get('catalog_restored_at'),
                        'catalog_restored_by': str(trimmed.get('catalog_restored_by') or ''),
                        'catalog_restored_reason': str(trimmed.get('catalog_restored_reason') or ''),
                        'catalog_rollback_release_state': str(trimmed.get('catalog_rollback_release_state') or ''),
                        'catalog_rollback_release_at': trimmed.get('catalog_rollback_release_at'),
                        'catalog_rollback_release_by': str(trimmed.get('catalog_rollback_release_by') or ''),
                        'catalog_rollback_release_reason': str(trimmed.get('catalog_rollback_release_reason') or ''),
                        'catalog_rollback_target_entry_id': str(trimmed.get('catalog_rollback_target_entry_id') or ''),
                        'catalog_rollback_target_version': int(trimmed.get('catalog_rollback_target_version') or 0),
                        'catalog_emergency_withdrawal_active': bool(trimmed.get('catalog_emergency_withdrawal_active', False)),
                        'organizational_service_id': str(trimmed.get('organizational_service_id') or ''),
                        'organizational_service_entry_id': str(trimmed.get('organizational_service_entry_id') or ''),
                        'organizational_publish_state': str(trimmed.get('organizational_publish_state') or ''),
                        'organizational_visibility': str(trimmed.get('organizational_visibility') or 'tenant'),
                        'organizational_service_scope_key': str(trimmed.get('organizational_service_scope_key') or ''),
                        'organizational_published_at': trimmed.get('organizational_published_at'),
                        'organizational_published_by': str(trimmed.get('organizational_published_by') or ''),
                        'organizational_publication_manifest': {
                            'manifest_type': str((trimmed.get('organizational_publication_manifest') or {}).get('manifest_type') or ''),
                            'manifest_digest': str((trimmed.get('organizational_publication_manifest') or {}).get('manifest_digest') or ''),
                            'policy_digest': str((trimmed.get('organizational_publication_manifest') or {}).get('policy_digest') or ''),
                            'published_at': (trimmed.get('organizational_publication_manifest') or {}).get('published_at'),
                            'published_by': str((trimmed.get('organizational_publication_manifest') or {}).get('published_by') or ''),
                        },
                        'organizational_reconciliation_report_count': int(trimmed.get('organizational_reconciliation_report_count') or 0),
                        'organizational_latest_reconciliation_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(trimmed.get('organizational_latest_reconciliation_report') or {}),
                        'catalog_binding_summary': dict(trimmed.get('catalog_binding_summary') or {}),
                    })
                data['routing_policy_pack_registry'] = rich_registry
                minimal_registry_snapshot = [dict(item) for item in minimal_registry]
                if LiveCanvasService._payload_size(data) > int(LiveCanvasService.MAX_PAYLOAD_CHARS * 0.9):
                    data['routing_policy_pack_registry'] = minimal_registry_snapshot
            bindings = [dict(item or {}) for item in list(data.get('routing_policy_pack_bindings') or []) if isinstance(item, dict)]
            if bindings:
                data['routing_policy_pack_bindings'] = [
                    LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding(item)
                    for item in bindings[:8]
                ]
            binding_events = [dict(item or {}) for item in list(data.get('routing_policy_pack_binding_events') or []) if isinstance(item, dict)]
            if binding_events:
                data['routing_policy_pack_binding_events'] = [
                    LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding_event(item)
                    for item in binding_events[:8]
                ]
            binding_summary = dict(data.get('routing_policy_pack_binding_summary') or {})
            if binding_summary:
                data['routing_policy_pack_binding_summary'] = {
                    'active_binding_count': int(binding_summary.get('active_binding_count') or 0),
                    'scope_counts': dict(binding_summary.get('scope_counts') or {}),
                    'latest_binding': LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding(binding_summary.get('latest_binding') or {}),
                }
            effective_binding = dict(data.get('effective_routing_policy_pack_binding') or {})
            if effective_binding:
                data['effective_routing_policy_pack_binding'] = LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding(effective_binding)
            if LiveCanvasService._payload_size(data) > int(LiveCanvasService.MAX_PAYLOAD_CHARS * 0.9):
                if minimal_registry_snapshot:
                    data['routing_policy_pack_registry'] = [dict(item) for item in minimal_registry_snapshot[:6]]
                if 'routing_policy_pack_bindings' in data:
                    data['routing_policy_pack_bindings'] = [
                        LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding(item)
                        for item in list(data.get('routing_policy_pack_bindings') or [])[-6:]
                        if isinstance(item, dict)
                    ]
                if 'routing_policy_pack_binding_events' in data:
                    data['routing_policy_pack_binding_events'] = [
                        LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding_event(item)
                        for item in list(data.get('routing_policy_pack_binding_events') or [])[-6:]
                        if isinstance(item, dict)
                    ]
            if LiveCanvasService._payload_size(data) > int(LiveCanvasService.MAX_PAYLOAD_CHARS * 0.85):
                for key in (
                    'routing_policy_pack_organizational_catalog_service',
                    'routing_policy_pack_organizational_catalog_service_summary',
                    'routing_policy_pack_organizational_catalog_reconciliation_summary',
                ):
                    data.pop(key, None)
                latest_simulation = dict(data.get('latest_simulation') or {})
                if latest_simulation:
                    compact_latest_simulation = dict(latest_simulation)
                    compact_latest_simulation['summary'] = {
                        'status': str((latest_simulation.get('summary') or {}).get('status') or latest_simulation.get('simulation_status') or ''),
                        'baseline_count': int((latest_simulation.get('summary') or {}).get('baseline_count') or 0),
                        'risk_count': int((latest_simulation.get('summary') or {}).get('risk_count') or 0),
                        'change_count': int((latest_simulation.get('summary') or {}).get('change_count') or 0),
                    }
                    compact_latest_simulation['export_state'] = {
                        key: value
                        for key, value in dict(latest_simulation.get('export_state') or {}).items()
                        if key.startswith('last_') or key in {
                            'simulation_registry_summary',
                            'routing_policy_pack_binding_summary',
                            'latest_routing_replay',
                            'saved_routing_policy_packs',
                            'attestation_count',
                            'review_audit_count',
                            'evidence_package_count',
                            'latest_attestation',
                            'latest_review_audit',
                            'latest_evidence_package',
                            'registry_summary',
                            'verification_count',
                            'latest_verification',
                            'reconciliation_count',
                            'latest_reconciliation',
                            'restore_count',
                            'latest_restore',
                            'custody_guard',
                            'custody_alerts_summary',
                            'custody_active_alert',
                        }
                    }
                    compact_export_state = dict(compact_latest_simulation.get('export_state') or {})
                    for key, value in list(compact_export_state.items()):
                        if key.endswith('_routing_policy_pack') and isinstance(value, dict):
                            compact_export_state[key] = LiveCanvasService._prune_canvas_payload(
                                LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(value)
                            )
                        elif key in {'saved_routing_policy_packs', 'routing_policy_pack_registry', 'shared_routing_policy_packs'}:
                            compact_export_state[key] = [
                                LiveCanvasService._prune_canvas_payload(
                                    LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item)
                                )
                                for item in list(value or [])[:4]
                                if isinstance(item, dict)
                            ]
                    compact_latest_simulation['export_state'] = compact_export_state
                    data['latest_simulation'] = compact_latest_simulation
        return data

    def _enforce_scope_limits(self, gw: AdminGatewayLike, *, scope: dict[str, Any]) -> None:
        count = int(gw.audit.count_canvas_documents(tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or 0)
        if count >= self.MAX_DOCUMENTS_PER_SCOPE:
            raise ValueError('canvas document scope limit exceeded')

    def _enforce_canvas_payload(self, *, payload: Any) -> None:
        if self._payload_size(payload) > self.MAX_PAYLOAD_CHARS:
            raise ValueError("canvas payload exceeds max size")

    def _enforce_canvas_counts(self, gw: AdminGatewayLike, *, canvas_id: str, kind: str, tenant_id: str | None, workspace_id: str | None, environment: str | None) -> None:
        if kind == 'node':
            current = int(gw.audit.count_canvas_nodes(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or 0)
            if current >= self.MAX_NODES_PER_CANVAS:
                raise ValueError('canvas node limit exceeded')
        elif kind == 'edge':
            current = int(gw.audit.count_canvas_edges(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or 0)
            if current >= self.MAX_EDGES_PER_CANVAS:
                raise ValueError('canvas edge limit exceeded')
        elif kind == 'view':
            current = int(gw.audit.count_canvas_views(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or 0)
            if current >= self.MAX_VIEWS_PER_CANVAS:
                raise ValueError('canvas view limit exceeded')


    def _sanitize_scope(
        self,
        gw: AdminGatewayLike,
        *,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> dict[str, Any]:
        tenancy = getattr(gw, 'tenancy', None)
        if tenancy is not None and hasattr(tenancy, 'normalize_scope'):
            try:
                return tenancy.normalize_scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
            except Exception:
                pass
        return {
            'tenant_id': tenant_id,
            'workspace_id': workspace_id,
            'environment': environment,
        }

    def _normalize_toggles(self, toggles: dict[str, Any] | None) -> dict[str, bool]:
        normalized = dict(self._DEFAULT_TOGGLES)
        for key, value in dict(toggles or {}).items():
            if key in normalized:
                normalized[key] = bool(value)
        return normalized

    @staticmethod
    def _safe_call(obj: Any, method_name: str, default: Any, /, *args: Any, **kwargs: Any) -> Any:
        method = getattr(obj, method_name, None)
        if not callable(method):
            return default
        try:
            return method(*args, **kwargs)
        except Exception:
            return default

    @staticmethod
    def _redact_sensitive(value: Any) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(token in lowered for token in ('secret', 'token', 'password', 'value', 'credential')):
                    redacted[key] = '***redacted***'
                else:
                    redacted[key] = LiveCanvasService._redact_sensitive(item)
            return redacted
        if isinstance(value, list):
            return [LiveCanvasService._redact_sensitive(item) for item in value]
        return value

    def _replace_node_data(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node: dict[str, Any],
        actor: str,
        data: dict[str, Any],
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> dict[str, Any]:
        payload = dict(data or {})
        if str(node.get('node_type') or '').strip().lower() in {'baseline_promotion', 'policy_baseline_promotion'}:
            payload.pop('routing_policy_pack_catalog', None)
            payload.pop('routing_policy_pack_catalog_summary', None)
        if self._payload_size(payload) > int(self.MAX_PAYLOAD_CHARS * 0.9):
            payload = self._minimize_node_data_for_storage(payload, node_type=str(node.get('node_type') or 'note'))
        if self._payload_size(payload) > self.MAX_PAYLOAD_CHARS:
            payload = self._minimize_node_data_for_storage(payload, node_type=str(node.get('node_type') or 'note'))
        if self._payload_size(payload) > self.MAX_PAYLOAD_CHARS and str(node.get('node_type') or '').strip().lower() in {'baseline_promotion', 'policy_baseline_promotion'}:
            squeezed = dict(payload or {})

            saved = [dict(item or {}) for item in list(squeezed.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
            if saved:
                last_saved = dict(saved[-1] or {})
                squeezed['saved_routing_policy_packs'] = [{
                    'pack_id': str(last_saved.get('pack_id') or ''),
                    'pack_label': str(last_saved.get('pack_label') or ''),
                    'source': str(last_saved.get('source') or ''),
                    'category_keys': [str(v) for v in list(last_saved.get('category_keys') or []) if str(v)][:8],
                    'scenario_count': int(last_saved.get('scenario_count') or 0),
                    'created_at': last_saved.get('created_at'),
                    'created_by': str(last_saved.get('created_by') or ''),
                    'last_used_at': last_saved.get('last_used_at'),
                    'use_count': int(last_saved.get('use_count') or 0),
                    'registry_entry_id': str(last_saved.get('registry_entry_id') or ''),
                    'registry_scope': str(last_saved.get('registry_scope') or ''),
                    'promoted_from_pack_id': str(last_saved.get('promoted_from_pack_id') or ''),
                    'promoted_from_source': str(last_saved.get('promoted_from_source') or ''),
                    'shared_from_pack_id': str(last_saved.get('shared_from_pack_id') or ''),
                    'shared_from_source': str(last_saved.get('shared_from_source') or ''),
                    'share_count': int(last_saved.get('share_count') or 0),
                    'catalog_entry_id': str(last_saved.get('catalog_entry_id') or ''),
                    'catalog_scope': str(last_saved.get('catalog_scope') or ''),
                    'catalog_scope_key': str(last_saved.get('catalog_scope_key') or ''),
                    'catalog_version_key': str(last_saved.get('catalog_version_key') or ''),
                    'catalog_version': int(last_saved.get('catalog_version') or 0),
                    'catalog_lifecycle_state': str(last_saved.get('catalog_lifecycle_state') or 'draft'),
                }]
            else:
                squeezed.pop('saved_routing_policy_packs', None)

            registry = [dict(item or {}) for item in list(squeezed.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
            if registry:
                squeezed['routing_policy_pack_registry'] = [{
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
                    'portfolio_family_id': str(item.get('portfolio_family_id') or ''),
                    'runtime_family_id': str(item.get('runtime_family_id') or ''),
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
                    'catalog_withdrawn_at': item.get('catalog_withdrawn_at'),
                    'catalog_withdrawn_by': str(item.get('catalog_withdrawn_by') or ''),
                    'catalog_withdrawn_reason': str(item.get('catalog_withdrawn_reason') or ''),
                    'catalog_supersedence_state': str(item.get('catalog_supersedence_state') or ''),
                    'catalog_superseded_at': item.get('catalog_superseded_at'),
                    'catalog_superseded_by': str(item.get('catalog_superseded_by') or ''),
                    'catalog_superseded_reason': str(item.get('catalog_superseded_reason') or ''),
                    'catalog_superseded_by_entry_id': str(item.get('catalog_superseded_by_entry_id') or ''),
                    'catalog_superseded_by_version': int(item.get('catalog_superseded_by_version') or 0),
                    'catalog_superseded_by_bundle_id': str(item.get('catalog_superseded_by_bundle_id') or ''),
                    'catalog_supersedes_entry_id': str(item.get('catalog_supersedes_entry_id') or ''),
                    'catalog_supersedes_version': int(item.get('catalog_supersedes_version') or 0),
                    'catalog_restored_from_entry_id': str(item.get('catalog_restored_from_entry_id') or ''),
                    'catalog_restored_from_version': int(item.get('catalog_restored_from_version') or 0),
                    'catalog_restored_at': item.get('catalog_restored_at'),
                    'catalog_restored_by': str(item.get('catalog_restored_by') or ''),
                    'catalog_restored_reason': str(item.get('catalog_restored_reason') or ''),
                    'catalog_rollback_release_state': str(item.get('catalog_rollback_release_state') or ''),
                    'catalog_rollback_release_at': item.get('catalog_rollback_release_at'),
                    'catalog_rollback_release_by': str(item.get('catalog_rollback_release_by') or ''),
                    'catalog_rollback_release_reason': str(item.get('catalog_rollback_release_reason') or ''),
                    'catalog_rollback_target_entry_id': str(item.get('catalog_rollback_target_entry_id') or ''),
                    'catalog_rollback_target_version': int(item.get('catalog_rollback_target_version') or 0),
                    'catalog_emergency_withdrawal_active': bool(item.get('catalog_emergency_withdrawal_active', False)),
                    'catalog_emergency_withdrawal_at': item.get('catalog_emergency_withdrawal_at'),
                    'catalog_emergency_withdrawal_by': str(item.get('catalog_emergency_withdrawal_by') or ''),
                    'catalog_emergency_withdrawal_reason': str(item.get('catalog_emergency_withdrawal_reason') or ''),
                    'catalog_emergency_withdrawal_incident_id': str(item.get('catalog_emergency_withdrawal_incident_id') or ''),
                    'catalog_emergency_withdrawal_severity': str(item.get('catalog_emergency_withdrawal_severity') or ''),
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
                    'catalog_is_latest': bool(item.get('catalog_is_latest', False)),
                    'catalog_replay_count': int(item.get('catalog_replay_count') or 0),
                    'catalog_last_replayed_at': item.get('catalog_last_replayed_at'),
                    'catalog_last_replayed_by': str(item.get('catalog_last_replayed_by') or ''),
                    'catalog_last_replay_source': str(item.get('catalog_last_replay_source') or ''),
                    'catalog_binding_count': int(item.get('catalog_binding_count') or 0),
                    'catalog_last_bound_at': item.get('catalog_last_bound_at'),
                    'catalog_last_bound_by': str(item.get('catalog_last_bound_by') or ''),
                    'catalog_share_count': int(item.get('catalog_share_count') or 0),
                    'catalog_last_shared_at': item.get('catalog_last_shared_at'),
                    'catalog_last_shared_by': str(item.get('catalog_last_shared_by') or ''),
                    'catalog_analytics_summary': dict(item.get('catalog_analytics_summary') or {}),
                    'catalog_analytics_report_count': int(item.get('catalog_analytics_report_count') or 0),
                    'catalog_latest_analytics_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(item.get('catalog_latest_analytics_report') or {}),
                    'organizational_service_id': str(item.get('organizational_service_id') or ''),
                    'organizational_service_entry_id': str(item.get('organizational_service_entry_id') or ''),
                    'organizational_publish_state': str(item.get('organizational_publish_state') or ''),
                    'organizational_visibility': str(item.get('organizational_visibility') or 'tenant'),
                    'organizational_service_scope_key': str(item.get('organizational_service_scope_key') or ''),
                    'organizational_published_at': item.get('organizational_published_at'),
                    'organizational_published_by': str(item.get('organizational_published_by') or ''),
                    'organizational_withdrawn_at': item.get('organizational_withdrawn_at'),
                    'organizational_withdrawn_by': str(item.get('organizational_withdrawn_by') or ''),
                    'organizational_withdrawn_reason': str(item.get('organizational_withdrawn_reason') or ''),
                    'organizational_publication_manifest': {
                        'manifest_type': str((item.get('organizational_publication_manifest') or {}).get('manifest_type') or ''),
                        'manifest_digest': str((item.get('organizational_publication_manifest') or {}).get('manifest_digest') or ''),
                        'policy_digest': str((item.get('organizational_publication_manifest') or {}).get('policy_digest') or ''),
                        'published_at': (item.get('organizational_publication_manifest') or {}).get('published_at'),
                        'published_by': str((item.get('organizational_publication_manifest') or {}).get('published_by') or ''),
                    },
                    'organizational_publication_health': dict(item.get('organizational_publication_health') or {}),
                    'organizational_reconciliation_report_count': int(item.get('organizational_reconciliation_report_count') or 0),
                    'organizational_latest_reconciliation_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(item.get('organizational_latest_reconciliation_report') or {}),
                    'share_count': int(item.get('share_count') or 0),
                    'scenario_count': int(item.get('scenario_count') or 0),
                } for item in registry[:4]]
            else:
                squeezed.pop('routing_policy_pack_registry', None)


            for heavy_key in (
                'routing_policy_pack_catalog',
                'routing_policy_pack_catalog_summary',
                'routing_policy_pack_compliance_summary',
                'effective_routing_policy_pack_compliance',
                'routing_policy_pack_analytics_summary',
                'routing_policy_pack_operator_dashboard',
                'routing_policy_pack_organizational_catalog_service',
                'routing_policy_pack_organizational_catalog_service_summary',
                'routing_policy_pack_organizational_catalog_reconciliation_summary',
            ):
                squeezed.pop(heavy_key, None)

            latest_simulation = dict(squeezed.get('latest_simulation') or {})
            if latest_simulation:
                slim_latest_simulation = {}
                for key in (
                    'simulation_id',
                    'simulation_type',
                    'status',
                    'simulation_status',
                    'stale',
                    'expired',
                    'blocked',
                    'why_blocked',
                    'generated_at',
                    'recorded_at',
                    'created_at',
                    'updated_at',
                    'promotion_id',
                    'runtime_id',
                    'environment',
                    'catalog_id',
                ):
                    value = latest_simulation.get(key)
                    if value not in (None, '', [], {}):
                        slim_latest_simulation[key] = value

                for dict_key in (
                    'summary',
                    'validation',
                    'request',
                    'simulation_source',
                    'review',
                    'review_state',
                    'simulation_policy',
                    'observed_context',
                    'observed_versions',
                    'fingerprints',
                    'source_observed_versions',
                    'source_fingerprints',
                ):
                    dict_value = latest_simulation.get(dict_key)
                    if isinstance(dict_value, dict) and dict_value:
                        slim_latest_simulation[dict_key] = LiveCanvasService._prune_canvas_payload(dict(dict_value))

                export_state = dict(latest_simulation.get('export_state') or {})
                slim_export_state = {}

                latest_routing_replay = dict(export_state.get('latest_routing_replay') or {})
                if latest_routing_replay:
                    slim_export_state['latest_routing_replay'] = LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_routing_replay(latest_routing_replay)
                    )

                latest_evidence_package = dict(export_state.get('latest_evidence_package') or {})
                if latest_evidence_package:
                    slim_export_state['evidence_package_count'] = int(export_state.get('evidence_package_count') or 0)
                    slim_export_state['latest_evidence_package'] = LiveCanvasService._compact_baseline_promotion_simulation_export_report(latest_evidence_package)

                latest_verification = dict(export_state.get('latest_verification') or {})
                if latest_verification:
                    slim_export_state['verification_count'] = int(export_state.get('verification_count') or 0)
                    slim_export_state['latest_verification'] = {
                        'package_id': str(latest_verification.get('package_id') or ''),
                        'verified_at': latest_verification.get('verified_at'),
                        'verified_by': str(latest_verification.get('verified_by') or ''),
                        'status': str(latest_verification.get('status') or ''),
                        'valid': bool(latest_verification.get('valid')),
                        'failures': [str(item) for item in list(latest_verification.get('failures') or []) if str(item)],
                        'artifact_sha256': str(latest_verification.get('artifact_sha256') or ''),
                        'artifact_source': str(latest_verification.get('artifact_source') or ''),
                        'escrow_status': str(latest_verification.get('escrow_status') or ''),
                        'registry_entry': {
                            'entry_id': str((latest_verification.get('registry_entry') or {}).get('entry_id') or ''),
                            'sequence': int((latest_verification.get('registry_entry') or {}).get('sequence') or 0),
                        },
                    }

                latest_restore = dict(export_state.get('latest_restore') or {})
                if latest_restore:
                    slim_export_state['restore_count'] = int(export_state.get('restore_count') or 0)
                    slim_export_state['latest_restore'] = {
                        'restore_id': str(latest_restore.get('restore_id') or ''),
                        'package_id': str(latest_restore.get('package_id') or ''),
                        'restored_at': latest_restore.get('restored_at'),
                        'restored_by': str(latest_restore.get('restored_by') or ''),
                        'simulation_status': str(latest_restore.get('simulation_status') or ''),
                        'stale': bool(latest_restore.get('stale')),
                        'expired': bool(latest_restore.get('expired')),
                        'blocked': bool(latest_restore.get('blocked')),
                        'why_blocked': str(latest_restore.get('why_blocked') or ''),
                    }


                custody_alerts_summary = dict(export_state.get('custody_alerts_summary') or {})
                if custody_alerts_summary:
                    slim_export_state['custody_alerts_summary'] = LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_custody_alerts_summary(custody_alerts_summary)
                    )

                custody_active_alert = dict(export_state.get('custody_active_alert') or {})
                if custody_active_alert:
                    slim_export_state['custody_active_alert'] = LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_custody_active_alert(custody_active_alert)
                    )

                custody_guard = dict(export_state.get('custody_guard') or {})
                if custody_guard:
                    slim_export_state['custody_guard'] = LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_custody_guard(custody_guard)
                    )

                latest_reconciliation = dict(export_state.get('latest_reconciliation') or {})
                if latest_reconciliation:
                    slim_export_state['reconciliation_count'] = int(export_state.get('reconciliation_count') or 0)
                    slim_export_state['latest_reconciliation'] = {
                        'reconciliation_id': str(latest_reconciliation.get('reconciliation_id') or ''),
                        'package_id': str(latest_reconciliation.get('package_id') or ''),
                        'reconciled_at': latest_reconciliation.get('reconciled_at'),
                        'reconciled_by': str(latest_reconciliation.get('reconciled_by') or ''),
                        'overall_status': str(latest_reconciliation.get('overall_status') or ''),
                        'drifted_count': int(latest_reconciliation.get('drifted_count') or 0),
                        'missing_archive_count': int(latest_reconciliation.get('missing_archive_count') or 0),
                        'lock_drift_count': int(latest_reconciliation.get('lock_drift_count') or 0),
                        'registry_drift_count': int(latest_reconciliation.get('registry_drift_count') or 0),
                        'latest_package_id': str(latest_reconciliation.get('latest_package_id') or ''),
                    }

                last_saved_export = dict(export_state.get('last_saved_routing_policy_pack') or {})
                if last_saved_export:
                    slim_export_state['last_saved_routing_policy_pack'] = {
                        'pack_id': str(last_saved_export.get('pack_id') or ''),
                        'pack_label': str(last_saved_export.get('pack_label') or ''),
                        'source': str(last_saved_export.get('source') or ''),
                        'category_keys': [str(v) for v in list(last_saved_export.get('category_keys') or []) if str(v)][:8],
                        'scenario_count': int(last_saved_export.get('scenario_count') or 0),
                        'created_at': last_saved_export.get('created_at'),
                        'created_by': str(last_saved_export.get('created_by') or ''),
                        'last_used_at': last_saved_export.get('last_used_at'),
                        'use_count': int(last_saved_export.get('use_count') or 0),
                        'registry_entry_id': str(last_saved_export.get('registry_entry_id') or ''),
                        'registry_scope': str(last_saved_export.get('registry_scope') or ''),
                        'promoted_from_pack_id': str(last_saved_export.get('promoted_from_pack_id') or ''),
                        'promoted_from_source': str(last_saved_export.get('promoted_from_source') or ''),
                        'shared_from_pack_id': str(last_saved_export.get('shared_from_pack_id') or ''),
                        'shared_from_source': str(last_saved_export.get('shared_from_source') or ''),
                        'share_count': int(last_saved_export.get('share_count') or 0),
                        'catalog_entry_id': str(last_saved_export.get('catalog_entry_id') or ''),
                        'catalog_scope': str(last_saved_export.get('catalog_scope') or ''),
                        'catalog_scope_key': str(last_saved_export.get('catalog_scope_key') or ''),
                        'catalog_version_key': str(last_saved_export.get('catalog_version_key') or ''),
                        'catalog_version': int(last_saved_export.get('catalog_version') or 0),
                        'catalog_lifecycle_state': str(last_saved_export.get('catalog_lifecycle_state') or 'draft'),
                    }

                export_registry = [dict(item or {}) for item in list(export_state.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                if export_registry:
                    slim_export_state['routing_policy_pack_registry'] = [{
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
                    'organizational_service_id': str(item.get('organizational_service_id') or ''),
                    'organizational_service_entry_id': str(item.get('organizational_service_entry_id') or ''),
                    'organizational_publish_state': str(item.get('organizational_publish_state') or ''),
                    'organizational_visibility': str(item.get('organizational_visibility') or 'tenant'),
                    'organizational_service_scope_key': str(item.get('organizational_service_scope_key') or ''),
                    'organizational_published_at': item.get('organizational_published_at'),
                    'organizational_published_by': str(item.get('organizational_published_by') or ''),
                    'organizational_withdrawn_at': item.get('organizational_withdrawn_at'),
                    'organizational_withdrawn_by': str(item.get('organizational_withdrawn_by') or ''),
                    'organizational_withdrawn_reason': str(item.get('organizational_withdrawn_reason') or ''),
                    'organizational_publication_manifest': {
                        'manifest_type': str((item.get('organizational_publication_manifest') or {}).get('manifest_type') or ''),
                        'manifest_digest': str((item.get('organizational_publication_manifest') or {}).get('manifest_digest') or ''),
                        'policy_digest': str((item.get('organizational_publication_manifest') or {}).get('policy_digest') or ''),
                        'published_at': (item.get('organizational_publication_manifest') or {}).get('published_at'),
                        'published_by': str((item.get('organizational_publication_manifest') or {}).get('published_by') or ''),
                    },
                    'organizational_publication_health': dict(item.get('organizational_publication_health') or {}),
                    'organizational_reconciliation_report_count': int(item.get('organizational_reconciliation_report_count') or 0),
                    'organizational_latest_reconciliation_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(item.get('organizational_latest_reconciliation_report') or {}),
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
                    } for item in export_registry[:4]]


                if slim_export_state:
                    slim_latest_simulation['export_state'] = slim_export_state

                squeezed['latest_simulation'] = slim_latest_simulation

            payload = squeezed
        if self._payload_size(payload) > self.MAX_PAYLOAD_CHARS and str(node.get('node_type') or '').strip().lower() in {'baseline_promotion', 'policy_baseline_promotion'}:
            ultra = dict(payload or {})

            ultra.pop('routing_policy_pack_binding_events', None)
            ultra.pop('routing_policy_pack_catalog', None)
            ultra.pop('routing_policy_pack_catalog_summary', None)
            ultra.pop('routing_policy_pack_compliance_summary', None)
            ultra.pop('effective_routing_policy_pack_compliance', None)
            ultra.pop('routing_policy_pack_analytics_summary', None)
            ultra.pop('routing_policy_pack_operator_dashboard', None)
            ultra.pop('routing_policy_pack_organizational_catalog_service', None)
            ultra.pop('routing_policy_pack_organizational_catalog_service_summary', None)
            ultra.pop('routing_policy_pack_organizational_catalog_reconciliation_summary', None)

            saved = [dict(item or {}) for item in list(ultra.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
            if saved:
                last_saved = dict(saved[-1] or {})
                ultra['saved_routing_policy_packs'] = [{
                    'pack_id': str(last_saved.get('pack_id') or ''),
                    'pack_label': str(last_saved.get('pack_label') or ''),
                    'source': str(last_saved.get('source') or ''),
                    'catalog_entry_id': str(last_saved.get('catalog_entry_id') or ''),
                    'catalog_version': int(last_saved.get('catalog_version') or 0),
                    'registry_entry_id': str(last_saved.get('registry_entry_id') or ''),
                    'registry_scope': str(last_saved.get('registry_scope') or ''),
                    'shared_from_pack_id': str(last_saved.get('shared_from_pack_id') or ''),
                }]
            else:
                ultra.pop('saved_routing_policy_packs', None)

            registry = [dict(item or {}) for item in list(ultra.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
            if registry:
                ultra['routing_policy_pack_registry'] = [{
                    'pack_id': str(item.get('pack_id') or ''),
                    'pack_label': str(item.get('pack_label') or ''),
                    'source': str(item.get('source') or ''),
                    'catalog_entry_id': str(item.get('catalog_entry_id') or ''),
                    'catalog_version_key': str(item.get('catalog_version_key') or ''),
                    'catalog_version': int(item.get('catalog_version') or 0),
                    'catalog_scope': str(item.get('catalog_scope') or ''),
                    'catalog_lifecycle_state': str(item.get('catalog_lifecycle_state') or 'draft'),
                    'catalog_release_state': str(item.get('catalog_release_state') or 'draft'),
                    'catalog_rollout_state': str(item.get('catalog_rollout_state') or ''),
                    'catalog_is_effective_for_current_scope': bool(item.get('catalog_is_effective_for_current_scope', False)),
                    'catalog_replay_count': int(item.get('catalog_replay_count') or 0),
                    'catalog_binding_count': int(item.get('catalog_binding_count') or 0),
                    'catalog_share_count': int(item.get('catalog_share_count') or 0),
                    'organizational_service_id': str(item.get('organizational_service_id') or ''),
                    'organizational_service_entry_id': str(item.get('organizational_service_entry_id') or ''),
                    'organizational_publish_state': str(item.get('organizational_publish_state') or ''),
                    'organizational_visibility': str(item.get('organizational_visibility') or 'tenant'),
                    'organizational_service_scope_key': str(item.get('organizational_service_scope_key') or ''),
                    'organizational_published_at': item.get('organizational_published_at'),
                    'organizational_published_by': str(item.get('organizational_published_by') or ''),
                    'organizational_withdrawn_at': item.get('organizational_withdrawn_at'),
                    'organizational_withdrawn_by': str(item.get('organizational_withdrawn_by') or ''),
                    'organizational_withdrawn_reason': str(item.get('organizational_withdrawn_reason') or ''),
                    'organizational_publication_manifest': {
                        'manifest_type': str((item.get('organizational_publication_manifest') or {}).get('manifest_type') or ''),
                        'manifest_digest': str((item.get('organizational_publication_manifest') or {}).get('manifest_digest') or ''),
                        'policy_digest': str((item.get('organizational_publication_manifest') or {}).get('policy_digest') or ''),
                        'published_at': (item.get('organizational_publication_manifest') or {}).get('published_at'),
                        'published_by': str((item.get('organizational_publication_manifest') or {}).get('published_by') or ''),
                    },
                    'organizational_publication_health': dict(item.get('organizational_publication_health') or {}),
                    'organizational_reconciliation_report_count': int(item.get('organizational_reconciliation_report_count') or 0),
                    'organizational_latest_reconciliation_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(item.get('organizational_latest_reconciliation_report') or {}),
                } for item in registry[:4]]
            else:
                ultra.pop('routing_policy_pack_registry', None)

            bindings = [dict(item or {}) for item in list(ultra.get('routing_policy_pack_bindings') or []) if isinstance(item, dict)]
            if bindings:
                ultra['routing_policy_pack_bindings'] = [
                    {

                        'binding_id': str(item.get('binding_id') or ''),
                        'binding_scope': str(item.get('binding_scope') or ''),
                        'binding_scope_key': str(item.get('binding_scope_key') or ''),
                        'catalog_entry_id': str(item.get('catalog_entry_id') or ''),
                        'catalog_version_key': str(item.get('catalog_version_key') or ''),
                        'catalog_version': int(item.get('catalog_version') or 0),
                        'catalog_pack_id': str(item.get('catalog_pack_id') or ''),
                        'catalog_pack_label': str(item.get('catalog_pack_label') or ''),
                        'promotion_id': str(item.get('promotion_id') or ''),
                        'workspace_id': str(item.get('workspace_id') or ''),
                        'environment': str(item.get('environment') or ''),
                        'portfolio_family_id': str(item.get('portfolio_family_id') or ''),
                        'runtime_family_id': str(item.get('runtime_family_id') or ''),
                        'state': str(item.get('state') or 'active'),
                        'note': str(item.get('note') or ''),
                        'bound_at': item.get('bound_at'),
                        'bound_by': str(item.get('bound_by') or ''),
                        'binding_ready': bool(item.get('binding_ready', False)),
                        'binding_ready_reason': str(item.get('binding_ready_reason') or ''),
                        'catalog_owner_canvas_id': str(item.get('catalog_owner_canvas_id') or ''),
                        'catalog_owner_node_id': str(item.get('catalog_owner_node_id') or ''),
                        'rebound_at': item.get('rebound_at'),
                        'rebound_by': str(item.get('rebound_by') or ''),
                        'rebound_reason': str(item.get('rebound_reason') or ''),

                    }
                    for item in bindings[-4:]
                ]
            else:
                ultra.pop('routing_policy_pack_bindings', None)

            binding_summary = dict(ultra.get('routing_policy_pack_binding_summary') or {})
            if binding_summary:
                ultra['routing_policy_pack_binding_summary'] = {
                    'active_binding_count': int(binding_summary.get('active_binding_count') or 0),
                    'scope_counts': dict(binding_summary.get('scope_counts') or {}),
                    'latest_binding': LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding(binding_summary.get('latest_binding') or {}),
                }
            else:
                ultra.pop('routing_policy_pack_binding_summary', None)

            effective_binding = dict(ultra.get('effective_routing_policy_pack_binding') or {})
            if effective_binding:
                ultra['effective_routing_policy_pack_binding'] = {

                    'binding_id': str(effective_binding.get('binding_id') or ''),
                    'binding_scope': str(effective_binding.get('binding_scope') or ''),
                    'binding_scope_key': str(effective_binding.get('binding_scope_key') or ''),
                    'catalog_entry_id': str(effective_binding.get('catalog_entry_id') or ''),
                    'catalog_version_key': str(effective_binding.get('catalog_version_key') or ''),
                    'catalog_version': int(effective_binding.get('catalog_version') or 0),
                    'catalog_pack_id': str(effective_binding.get('catalog_pack_id') or ''),
                    'catalog_pack_label': str(effective_binding.get('catalog_pack_label') or ''),
                    'promotion_id': str(effective_binding.get('promotion_id') or ''),
                    'workspace_id': str(effective_binding.get('workspace_id') or ''),
                    'environment': str(effective_binding.get('environment') or ''),
                    'portfolio_family_id': str(effective_binding.get('portfolio_family_id') or ''),
                    'runtime_family_id': str(effective_binding.get('runtime_family_id') or ''),
                    'bound_at': effective_binding.get('bound_at'),
                    'bound_by': str(effective_binding.get('bound_by') or ''),
                    'state': str(effective_binding.get('state') or 'active'),
                    'note': str(effective_binding.get('note') or ''),
                    'catalog_owner_canvas_id': str(effective_binding.get('catalog_owner_canvas_id') or ''),
                    'catalog_owner_node_id': str(effective_binding.get('catalog_owner_node_id') or ''),
                    'rebound_at': effective_binding.get('rebound_at'),
                    'rebound_by': str(effective_binding.get('rebound_by') or ''),
                    'rebound_reason': str(effective_binding.get('rebound_reason') or ''),
                    'binding_ready': bool(effective_binding.get('binding_ready', False)),
                    'binding_ready_reason': str(effective_binding.get('binding_ready_reason') or ''),

                }
            else:
                ultra.pop('effective_routing_policy_pack_binding', None)

            latest_simulation = dict(ultra.get('latest_simulation') or {})
            if latest_simulation:
                slim_latest_simulation = {}
                for key in (
                    'simulation_id',
                    'simulation_type',
                    'status',
                    'simulation_status',
                    'stale',
                    'generated_at',
                    'recorded_at',
                    'created_at',
                    'updated_at',
                    'promotion_id',
                    'runtime_id',
                    'environment',
                ):
                    value = latest_simulation.get(key)
                    if value not in (None, '', [], {}):
                        slim_latest_simulation[key] = value

                export_state = dict(latest_simulation.get('export_state') or {})
                slim_export_state = {}

                latest_routing_replay = dict(export_state.get('latest_routing_replay') or {})
                if latest_routing_replay:
                    slim_export_state['latest_routing_replay'] = LiveCanvasService._prune_canvas_payload(
                        LiveCanvasService._compact_baseline_promotion_simulation_routing_replay(latest_routing_replay)
                    )

                last_saved_export = dict(export_state.get('last_saved_routing_policy_pack') or {})
                if last_saved_export:
                    slim_export_state['last_saved_routing_policy_pack'] = {
                        'pack_id': str(last_saved_export.get('pack_id') or ''),
                        'pack_label': str(last_saved_export.get('pack_label') or ''),
                        'source': str(last_saved_export.get('source') or ''),
                        'catalog_entry_id': str(last_saved_export.get('catalog_entry_id') or ''),
                        'catalog_version': int(last_saved_export.get('catalog_version') or 0),
                    }

                if slim_export_state:
                    slim_latest_simulation['export_state'] = slim_export_state

                ultra['latest_simulation'] = slim_latest_simulation
            else:
                ultra.pop('latest_simulation', None)

            payload = ultra
        return self.upsert_node(

            gw,
            canvas_id=canvas_id,
            node_id=str(node.get('node_id') or ''),
            actor=actor,
            node_type=str(node.get('node_type') or 'note'),
            label=str(node.get('label') or ''),
            position_x=float(node.get('position_x') or 0.0),
            position_y=float(node.get('position_y') or 0.0),
            width=float(node.get('width') or 240.0),
            height=float(node.get('height') or 120.0),
            data=payload,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )


    @staticmethod
    def _compact_baseline_promotion_simulation_export_report(report: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(report or {})
        if not payload:
            return {}
        integrity = dict(payload.get('integrity') or {})
        return {
            'report_id': str(payload.get('report_id') or payload.get('package_id') or ''),
            'package_id': str(payload.get('package_id') or ''),
            'report_type': str(payload.get('report_type') or ''),
            'generated_at': payload.get('generated_at'),
            'generated_by': str(payload.get('generated_by') or ''),
            'integrity': {
                'signed': bool(integrity.get('signed', False)),
                'payload_hash': str(integrity.get('payload_hash') or ''),
            },
            'registry_entry': {
                'entry_id': str((payload.get('registry_entry') or {}).get('entry_id') or ''),
                'sequence': int((payload.get('registry_entry') or {}).get('sequence') or 0),
                'immutable': bool((payload.get('registry_entry') or {}).get('immutable', False)),
            },
            'artifact': {
                'artifact_type': str((payload.get('artifact') or {}).get('artifact_type') or ''),
                'sha256': str((payload.get('artifact') or {}).get('sha256') or ''),
                'size_bytes': int((payload.get('artifact') or {}).get('size_bytes') or 0),
                'filename': str((payload.get('artifact') or {}).get('filename') or ''),
            },
            'escrow': {
                'receipt_id': str((payload.get('escrow') or {}).get('receipt_id') or ''),
                'provider': str((payload.get('escrow') or {}).get('provider') or ''),
                'archived': bool((payload.get('escrow') or {}).get('archived', False)),
                'archived_at': (payload.get('escrow') or {}).get('archived_at'),
                'immutable_until': (payload.get('escrow') or {}).get('immutable_until'),
                'lock_path': str((payload.get('escrow') or {}).get('lock_path') or ''),
                'object_lock_enabled': bool((payload.get('escrow') or {}).get('object_lock_enabled', False)),
            },
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_registry_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(summary or {})
        if not payload:
            return {}
        return {
            'count': int(payload.get('count') or 0),
            'package_count': int(payload.get('package_count') or 0),
            'chain_ok': bool(payload.get('chain_ok', False)),
            'broken_sequence_count': int(payload.get('broken_sequence_count') or 0),
            'immutable_count': int(payload.get('immutable_count') or 0),
            'escrowed_count': int(payload.get('escrowed_count') or 0),
            'immutable_archive_count': int(payload.get('immutable_archive_count') or 0),
            'latest_entry_id': str(payload.get('latest_entry_id') or ''),
            'latest_package_id': str(payload.get('latest_package_id') or ''),
            'latest_entry_hash': str(payload.get('latest_entry_hash') or ''),
            'latest_archive_path': str(payload.get('latest_archive_path') or ''),
            'latest_receipt_id': str(payload.get('latest_receipt_id') or ''),
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_catalog_binding(binding: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(binding or {})
        if not payload:
            return {}
        return {
            'binding_id': str(payload.get('binding_id') or ''),
            'binding_scope': str(payload.get('binding_scope') or ''),
            'binding_scope_key': str(payload.get('binding_scope_key') or ''),
            'catalog_entry_id': str(payload.get('catalog_entry_id') or ''),
            'catalog_version_key': str(payload.get('catalog_version_key') or ''),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'catalog_pack_id': str(payload.get('catalog_pack_id') or payload.get('pack_id') or ''),
            'catalog_pack_label': str(payload.get('catalog_pack_label') or payload.get('pack_label') or ''),
            'promotion_id': str(payload.get('promotion_id') or ''),
            'workspace_id': str(payload.get('workspace_id') or ''),
            'environment': str(payload.get('environment') or ''),
            'portfolio_family_id': str(payload.get('portfolio_family_id') or ''),
            'runtime_family_id': str(payload.get('runtime_family_id') or ''),
            'bound_at': payload.get('bound_at'),
            'bound_by': str(payload.get('bound_by') or ''),
            'state': str(payload.get('state') or 'active'),
            'note': str(payload.get('note') or '')[:160],
            'catalog_owner_canvas_id': str(payload.get('catalog_owner_canvas_id') or ''),
            'catalog_owner_node_id': str(payload.get('catalog_owner_node_id') or ''),
            'rebound_at': payload.get('rebound_at'),
            'rebound_by': str(payload.get('rebound_by') or ''),
            'rebound_reason': str(payload.get('rebound_reason') or ''),
            'binding_ready': bool(payload.get('binding_ready', False)),
            'binding_ready_reason': str(payload.get('binding_ready_reason') or ''),
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_catalog_binding_event(event: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(event or {})
        if not payload:
            return {}
        return {
            'event_id': str(payload.get('event_id') or ''),
            'event_type': str(payload.get('event_type') or ''),
            'binding_id': str(payload.get('binding_id') or ''),
            'binding_scope': str(payload.get('binding_scope') or ''),
            'binding_scope_key': str(payload.get('binding_scope_key') or ''),
            'catalog_entry_id': str(payload.get('catalog_entry_id') or ''),
            'catalog_version_key': str(payload.get('catalog_version_key') or ''),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'rebound_to_catalog_entry_id': str(payload.get('rebound_to_catalog_entry_id') or ''),
            'rebound_to_catalog_version': int(payload.get('rebound_to_catalog_version') or 0),
            'at': payload.get('at'),
            'by': str(payload.get('by') or ''),
            'note': str(payload.get('note') or '')[:160],
        }

    @staticmethod
    @staticmethod
    def _compact_baseline_promotion_simulation_request(request: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(request or {})
        candidate_baselines = dict(payload.get('candidate_baselines') or {})
        rollout_policy = dict(payload.get('rollout_policy') or {})
        gate_policy = dict(payload.get('gate_policy') or {})
        rollback_policy = dict(payload.get('rollback_policy') or {})
        return {
            'promotion_id': str(payload.get('promotion_id') or ''),
            'catalog_id': str(payload.get('catalog_id') or ''),
            'candidate_catalog_version': str(payload.get('candidate_catalog_version') or ''),
            'version': payload.get('version'),
            'candidate_environment_count': len(candidate_baselines),
            'candidate_environments': [str(key) for key in sorted(candidate_baselines.keys()) if str(key)],
            'rollout_policy': {
                'enabled': bool(rollout_policy.get('enabled', False)),
                'wave_size': int(rollout_policy.get('wave_size') or 0),
                'auto_apply_first_wave': bool(rollout_policy.get('auto_apply_first_wave', False)),
                'require_manual_advance': bool(rollout_policy.get('require_manual_advance', False)),
                'max_concurrent_waves': int(rollout_policy.get('max_concurrent_waves') or 0),
            },
            'gate_policy': {
                'enabled': bool(gate_policy.get('enabled', False)),
                'mode': str(gate_policy.get('mode') or ''),
                'require_all': bool(gate_policy.get('require_all', False)),
                'min_bake_time_s': int(gate_policy.get('min_bake_time_s') or 0),
            },
            'rollback_policy': {
                'enabled': bool(rollback_policy.get('enabled', False)),
                'auto_rollback_on_failure': bool(rollback_policy.get('auto_rollback_on_failure', False)),
                'attestation_required': bool(rollback_policy.get('attestation_required', False)),
            },
            'reason': str(payload.get('reason') or ''),
            'auto_approve': bool(payload.get('auto_approve', False)),
        }

    @staticmethod
    def _prune_canvas_payload(value: Any) -> Any:
        if isinstance(value, dict):
            pruned: dict[str, Any] = {}
            for key, raw_item in value.items():
                item = LiveCanvasService._prune_canvas_payload(raw_item)
                if item in (None, '', [], {}):
                    continue
                if isinstance(item, (int, float)) and not isinstance(item, bool) and item == 0:
                    continue
                pruned[str(key)] = item
            return pruned
        if isinstance(value, list):
            items = [LiveCanvasService._prune_canvas_payload(item) for item in value]
            return [item for item in items if item not in (None, '', [], {})]
        return value

    def _compact_baseline_promotion_simulation_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(policy or {})
        approval_policy = dict(payload.get('approval_policy') or {})
        custody_policy = dict(payload.get('custody_monitoring_policy') or {})
        return {
            'ttl_s': int(payload.get('ttl_s') or 0),
            'allow_self_review': bool(payload.get('allow_self_review', True)),
            'require_reason': bool(payload.get('require_reason', False)),
            'block_on_rejection': bool(payload.get('block_on_rejection', True)),
            'approval_policy': {
                'enabled': bool(approval_policy.get('enabled', False)),
                'mode': str(approval_policy.get('mode') or ''),
                'layers': [
                    {
                        'layer_id': str(layer.get('layer_id') or ''),
                        'label': str(layer.get('label') or ''),
                        'requested_role': str(layer.get('requested_role') or ''),
                        'required': bool(layer.get('required', True)),
                    }
                    for layer in list(approval_policy.get('layers') or [])
                ],
            },
            'custody_monitoring_policy': {
                'enabled': bool(custody_policy.get('enabled', False)),
                'auto_schedule': bool(custody_policy.get('auto_schedule', False)),
                'interval_s': int(custody_policy.get('interval_s') or 0),
                'notify_on_drift': bool(custody_policy.get('notify_on_drift', False)),
                'notify_on_recovery': bool(custody_policy.get('notify_on_recovery', False)),
                'block_on_drift': bool(custody_policy.get('block_on_drift', False)),
                'severity': str(custody_policy.get('severity') or ''),
                'load_aware_routing_enabled': bool(custody_policy.get('load_aware_routing_enabled', False)),
                'routing_enabled': bool(custody_policy.get('routing_enabled', False)),
                'ownership_enabled': bool(custody_policy.get('ownership_enabled', False)),
                'handoff_enabled': bool(custody_policy.get('handoff_enabled', False)),
                'default_route': {
                    'route_id': str((custody_policy.get('default_route') or {}).get('route_id') or ''),
                    'queue_id': str((custody_policy.get('default_route') or {}).get('queue_id') or ''),
                    'owner_role': str((custody_policy.get('default_route') or {}).get('owner_role') or ''),
                },
                'routing_routes': [
                    {
                        'route_id': str(route.get('route_id') or ''),
                        'queue_id': str(route.get('queue_id') or ''),
                        'owner_role': str(route.get('owner_role') or ''),
                        'min_escalation_level': int(route.get('min_escalation_level') or 0),
                        'queue_capacity': int(route.get('queue_capacity') or 0),
                    }
                    for route in list(custody_policy.get('routing_routes') or [])[:6]
                ],
            },
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_custody_guard(guard: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(guard or {})
        return {
            'status': str(payload.get('status') or ''),
            'blocked': bool(payload.get('blocked', False)),
            'block_reason': str(payload.get('block_reason') or payload.get('reason') or ''),
            'drifted': bool(payload.get('drifted', False)),
            'alert_status': str(payload.get('alert_status') or ''),
            'escalated': bool(payload.get('escalated', False)),
            'escalation_level': int(payload.get('escalation_level') or 0),
            'severity': str(payload.get('severity') or ''),
            'suppressed': bool(payload.get('suppressed', False)),
            'suppression_reasons': [str(item) for item in list(payload.get('suppression_reasons') or []) if str(item)],
            'pending_escalation_level': int(payload.get('pending_escalation_level') or 0),
            'owner_id': str(payload.get('owner_id') or ''),
            'owner_role': str(payload.get('owner_role') or ''),
            'ownership_status': str(payload.get('ownership_status') or ''),
            'queue_id': str(payload.get('queue_id') or ''),
            'queue_label': str(payload.get('queue_label') or ''),
            'route_id': str(payload.get('route_id') or ''),
            'route_label': str(payload.get('route_label') or ''),
            'queue_active_count': int(payload.get('queue_active_count') or 0),
            'queue_capacity': int(payload.get('queue_capacity') or 0),
            'queue_available': payload.get('queue_available'),
            'queue_load_ratio': float(payload.get('queue_load_ratio') or 0.0),
            'queue_at_capacity': bool(payload.get('queue_at_capacity', False)),
            'queue_over_capacity': bool(payload.get('queue_over_capacity', False)),
            'reservation_enabled': bool(payload.get('reservation_enabled', False)),
            'reserved_capacity': int(payload.get('reserved_capacity') or 0),
            'general_capacity': int(payload.get('general_capacity') or 0),
            'general_available': payload.get('general_available'),
            'reserved_available': payload.get('reserved_available'),
            'reservation_eligible': bool(payload.get('reservation_eligible', False)),
            'reservation_applied': bool(payload.get('reservation_applied', False)),
            'lease_active': bool(payload.get('lease_active', False)),
            'lease_expired': bool(payload.get('lease_expired', False)),
            'leased_capacity': int(payload.get('leased_capacity') or 0),
            'lease_available': payload.get('lease_available'),
            'lease_expires_at': payload.get('lease_expires_at'),
            'lease_reason': str(payload.get('lease_reason') or ''),
            'lease_holder': str(payload.get('lease_holder') or ''),
            'lease_eligible': bool(payload.get('lease_eligible', False)),
            'lease_applied': bool(payload.get('lease_applied', False)),
            'starvation_lease_capacity_borrowed': bool(payload.get('starvation_lease_capacity_borrowed', False)),
            'expedite_lease_capacity_borrowed': bool(payload.get('expedite_lease_capacity_borrowed', False)),
            'temporary_hold_count': int(payload.get('temporary_hold_count') or 0),
            'temporary_hold_capacity': int(payload.get('temporary_hold_capacity') or 0),
            'temporary_hold_available': payload.get('temporary_hold_available'),
            'temporary_hold_reason': str((list(payload.get('temporary_hold_reasons') or ['']) or [''])[0] or ''),
            'temporary_hold_eligible': bool(payload.get('temporary_hold_eligible', False)),
            'temporary_hold_applied': bool(payload.get('temporary_hold_applied', False)),
            'starvation_temporary_hold_borrowed': bool(payload.get('starvation_temporary_hold_borrowed', False)),
            'expedite_temporary_hold_borrowed': bool(payload.get('expedite_temporary_hold_borrowed', False)),
            'expired_temporary_hold_count': int(payload.get('expired_temporary_hold_count') or 0),
            'effective_capacity': int(payload.get('effective_capacity') or 0),
            'alert_wait_age_s': int(payload.get('alert_wait_age_s') or 0),
            'aging_applied': bool(payload.get('aging_applied', False)),
            'starving': bool(payload.get('starving', False)),
            'queue_oldest_alert_age_s': int(payload.get('queue_oldest_alert_age_s') or 0),
            'queue_aged_alert_count': int(payload.get('queue_aged_alert_count') or 0),
            'queue_starving_alert_count': int(payload.get('queue_starving_alert_count') or 0),
            'starvation_reserved_capacity_borrowed': bool(payload.get('starvation_reserved_capacity_borrowed', False)),
            'starvation_prevention_applied': bool(payload.get('starvation_prevention_applied', False)),
            'starvation_prevention_reason': str(payload.get('starvation_prevention_reason') or ''),
            'load_aware_routing': bool(payload.get('load_aware_routing', False)),
            'selection_reason': str(payload.get('selection_reason') or ''),
            'anti_thrashing_applied': bool(payload.get('anti_thrashing_applied', False)),
            'anti_thrashing_reason': str(payload.get('anti_thrashing_reason') or ''),
            'queue_family_id': str(payload.get('queue_family_id') or ''),
            'queue_family_label': str(payload.get('queue_family_label') or ''),
            'queue_family_enabled': bool(payload.get('queue_family_enabled', False)),
            'queue_family_member_count': int(payload.get('queue_family_member_count') or 0),
            'recent_queue_hop_count': int(payload.get('recent_queue_hop_count') or 0),
            'recent_family_hop_count': int(payload.get('recent_family_hop_count') or 0),
            'family_hysteresis_applied': bool(payload.get('family_hysteresis_applied', False)),
            'family_hysteresis_reason': str(payload.get('family_hysteresis_reason') or ''),
            'route_history_queue_ids': [str(item) for item in list(payload.get('route_history_queue_ids') or []) if str(item)],
            'route_history_family_ids': [str(item) for item in list(payload.get('route_history_family_ids') or []) if str(item)],
            'sla_deadline_target': str(payload.get('sla_deadline_target') or ''),
            'time_to_breach_s': payload.get('time_to_breach_s'),
            'predicted_wait_time_s': payload.get('predicted_wait_time_s'),
            'predicted_sla_margin_s': payload.get('predicted_sla_margin_s'),
            'predicted_sla_breach': bool(payload.get('predicted_sla_breach', False)),
            'breach_risk_score': float(payload.get('breach_risk_score') or 0.0),
            'breach_risk_level': str(payload.get('breach_risk_level') or ''),
            'expected_service_time_s': int(payload.get('expected_service_time_s') or 0),
            'forecast_window_s': int(payload.get('forecast_window_s') or 0),
            'forecast_arrivals_count': int(payload.get('forecast_arrivals_count') or 0),
            'forecast_departures_count': int(payload.get('forecast_departures_count') or 0),
            'projected_active_count': int(payload.get('projected_active_count') or 0),
            'projected_load_ratio': float(payload.get('projected_load_ratio') or 0.0),
            'projected_wait_time_s': int(payload.get('projected_wait_time_s') or 0),
            'forecasted_over_capacity': bool(payload.get('forecasted_over_capacity', False)),
            'surge_predicted': bool(payload.get('surge_predicted', False)),
            'proactive_routing_eligible': bool(payload.get('proactive_routing_eligible', False)),
            'proactive_routing_applied': bool(payload.get('proactive_routing_applied', False)),
            'proactive_reason': str(payload.get('proactive_reason') or ''),
            'admission_control_enabled': bool(payload.get('admission_control_enabled', False)),
            'admission_action': str(payload.get('admission_action') or ''),
            'admission_exempt': bool(payload.get('admission_exempt', False)),
            'admission_exempt_reason': str(payload.get('admission_exempt_reason') or ''),
            'admission_decision': str(payload.get('admission_decision') or ''),
            'admission_blocked': bool(payload.get('admission_blocked', False)),
            'admission_reason': str(payload.get('admission_reason') or ''),
            'admission_review_required': bool(payload.get('admission_review_required', False)),
            'overload_governance_enabled': bool(payload.get('overload_governance_enabled', False)),
            'overload_governance_applied': bool(payload.get('overload_governance_applied', False)),
            'overload_action': str(payload.get('overload_action') or ''),
            'overload_projected_load_ratio_threshold': float(payload.get('overload_projected_load_ratio_threshold') or 0.0),
            'overload_projected_wait_time_threshold_s': int(payload.get('overload_projected_wait_time_threshold_s') or 0),
            'overload_predicted': bool(payload.get('overload_predicted', False)),
            'overload_reason': str(payload.get('overload_reason') or ''),
            'expedite_eligible': bool(payload.get('expedite_eligible', False)),
            'expedite_reserved_capacity_borrowed': bool(payload.get('expedite_reserved_capacity_borrowed', False)),
            'expedite_applied': bool(payload.get('expedite_applied', False)),
            'expedite_reason': str(payload.get('expedite_reason') or ''),
            'handoff_pending': bool(payload.get('handoff_pending', False)),
            'handoff_count': int(payload.get('handoff_count') or 0),
            'sla_status': str(payload.get('sla_status') or ''),
            'sla_breached': bool(payload.get('sla_breached', False)),
            'sla_breached_targets': [str(item) for item in list(payload.get('sla_breached_targets') or []) if str(item)],
            'sla_warning_targets': [str(item) for item in list(payload.get('sla_warning_targets') or []) if str(item)],
            'sla_rerouted': bool(payload.get('sla_rerouted', False)),
            'sla_reroute_status': str(payload.get('sla_reroute_status') or ''),
            'sla_reroute_count': int(payload.get('sla_reroute_count') or 0),
            'team_queue_id': str(payload.get('team_queue_id') or ''),
            'updated_at': payload.get('updated_at'),
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_custody_alerts_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(summary or {})
        return {
            'count': int(payload.get('count') or 0),
            'active_count': int(payload.get('active_count') or 0),
            'acknowledged_count': int(payload.get('acknowledged_count') or 0),
            'muted_count': int(payload.get('muted_count') or 0),
            'escalated_count': int(payload.get('active_escalated_count') or payload.get('escalated_count') or 0),
            'suppressed_count': int(payload.get('active_suppressed_count') or payload.get('suppressed_count') or 0),
            'owned_count': int(payload.get('active_owned_count') or payload.get('owned_count') or 0),
            'claimed_count': int(payload.get('active_claimed_count') or payload.get('claimed_count') or 0),
            'unowned_count': int(payload.get('active_unowned_count') or payload.get('unassigned_count') or 0),
            'routed_count': int(payload.get('routed_count') or 0),
            'handoff_pending_count': int(payload.get('active_handoff_pending_count') or payload.get('pending_handoff_count') or 0),
            'sla_breached_count': int(payload.get('active_sla_breached_count') or payload.get('sla_breached_count') or 0),
            'sla_rerouted_count': int(payload.get('active_sla_rerouted_count') or payload.get('sla_rerouted_count') or 0),
            'team_queue_alert_count': int(payload.get('active_team_queue_alert_count') or payload.get('team_queue_alert_count') or 0),
            'queue_at_capacity_count': int(payload.get('active_queue_at_capacity_count') or payload.get('queue_at_capacity_count') or 0),
            'queue_over_capacity_count': int(payload.get('active_queue_over_capacity_count') or payload.get('queue_over_capacity_count') or 0),
            'load_aware_routed_count': int(payload.get('active_load_aware_routed_count') or payload.get('load_aware_routed_count') or 0),
            'reservation_protected_alert_count': int(payload.get('active_reservation_protected_alert_count') or payload.get('reservation_protected_alert_count') or 0),
            'lease_protected_alert_count': int(payload.get('active_lease_protected_alert_count') or payload.get('lease_protected_alert_count') or 0),
            'temporary_hold_protected_alert_count': int(payload.get('active_temporary_hold_protected_alert_count') or payload.get('temporary_hold_protected_alert_count') or 0),
            'anti_thrashing_kept_alert_count': int(payload.get('active_anti_thrashing_kept_alert_count') or payload.get('anti_thrashing_kept_alert_count') or 0),
            'queue_family_alert_count': int(payload.get('active_queue_family_alert_count') or payload.get('queue_family_alert_count') or 0),
            'family_hysteresis_kept_alert_count': int(payload.get('active_family_hysteresis_kept_alert_count') or payload.get('family_hysteresis_kept_alert_count') or 0),
            'aging_alert_count': int(payload.get('active_aging_alert_count') or payload.get('aging_alert_count') or 0),
            'starving_alert_count': int(payload.get('active_starving_alert_count') or payload.get('starving_alert_count') or 0),
            'starvation_prevented_alert_count': int(payload.get('active_starvation_prevented_alert_count') or payload.get('starvation_prevented_alert_count') or 0),
            'alerts_at_risk_count': int(payload.get('active_alerts_at_risk_count') or payload.get('alerts_at_risk_count') or 0),
            'predicted_sla_breach_count': int(payload.get('active_predicted_sla_breach_count') or payload.get('predicted_sla_breach_count') or 0),
            'expedite_routed_alert_count': int(payload.get('active_expedite_routed_alert_count') or payload.get('expedite_routed_alert_count') or 0),
            'proactive_routed_alert_count': int(payload.get('active_proactive_routed_alert_count') or payload.get('proactive_routed_alert_count') or 0),
            'forecasted_surge_alert_count': int(payload.get('active_forecasted_surge_alert_count') or payload.get('forecasted_surge_alert_count') or 0),
            'overload_governed_alert_count': int(payload.get('active_overload_governed_alert_count') or payload.get('overload_governed_alert_count') or 0),
            'overload_blocked_alert_count': int(payload.get('active_overload_blocked_alert_count') or payload.get('overload_blocked_alert_count') or 0),
            'admission_deferred_alert_count': int(payload.get('active_admission_deferred_alert_count') or payload.get('admission_deferred_alert_count') or 0),
            'manual_gate_alert_count': int(payload.get('active_manual_gate_alert_count') or payload.get('manual_gate_alert_count') or 0),
            'latest_alert_id': str(payload.get('latest_alert_id') or ''),
            'latest_status': str(payload.get('latest_status') or ''),
            'latest_owner_id': str(payload.get('latest_owner_id') or ''),
            'latest_queue_id': str(payload.get('latest_queue_id') or ''),
            'latest_route_id': str(payload.get('latest_route_id') or ''),
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_custody_active_alert(alert: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(alert or {})
        ownership = dict(payload.get('ownership') or {})
        routing = dict(payload.get('routing') or {})
        suppression = dict(payload.get('suppression_state') or {})
        handoff = dict(payload.get('handoff') or {})
        sla = dict(payload.get('sla') or payload.get('sla_state') or {})
        return {
            'alert_id': str(payload.get('alert_id') or ''),
            'status': str(payload.get('status') or ''),
            'active': bool(payload.get('active', False)),
            'severity': str(payload.get('severity') or ''),
            'escalation_level': int(payload.get('escalation_level') or 0),
            'ownership': {
                'status': str(ownership.get('status') or ''),
                'owner_id': str(ownership.get('owner_id') or ''),
                'owner_role': str(ownership.get('owner_role') or ''),
                'queue_id': str(ownership.get('queue_id') or ''),
                'queue_label': str(ownership.get('queue_label') or ''),
                'claimed_at': ownership.get('claimed_at'),
                'updated_at': ownership.get('updated_at'),
            },
            'routing': {
                'route_id': str(routing.get('route_id') or ''),
                'route_label': str(routing.get('route_label') or ''),
                'queue_id': str(routing.get('queue_id') or ''),
                'queue_label': str(routing.get('queue_label') or ''),
                'owner_role': str(routing.get('owner_role') or ''),
                'source': str(routing.get('source') or ''),
                'manual_override': bool(routing.get('manual_override', False)),
                'load_aware': bool(routing.get('load_aware', False)),
                'selection_reason': str(routing.get('selection_reason') or ''),
                'queue_active_count': int(routing.get('queue_active_count') or 0),
                'queue_capacity': int(routing.get('queue_capacity') or 0),
                'queue_available': routing.get('queue_available'),
                'queue_load_ratio': float(routing.get('queue_load_ratio') or 0.0),
                'queue_at_capacity': bool(routing.get('queue_at_capacity', False)),
                'queue_over_capacity': bool(routing.get('queue_over_capacity', False)),
                'reservation_enabled': bool(routing.get('reservation_enabled', False)),
                'reserved_capacity': int(routing.get('reserved_capacity') or 0),
                'general_capacity': int(routing.get('general_capacity') or 0),
                'general_available': routing.get('general_available'),
                'reserved_available': routing.get('reserved_available'),
                'reservation_eligible': bool(routing.get('reservation_eligible', False)),
                'reservation_applied': bool(routing.get('reservation_applied', False)),
                'lease_active': bool(routing.get('lease_active', False)),
                'lease_expired': bool(routing.get('lease_expired', False)),
                'leased_capacity': int(routing.get('leased_capacity') or 0),
                'lease_available': routing.get('lease_available'),
                'lease_expires_at': routing.get('lease_expires_at'),
                'lease_reason': str(routing.get('lease_reason') or ''),
                'lease_holder': str(routing.get('lease_holder') or ''),
                'lease_eligible': bool(routing.get('lease_eligible', False)),
                'lease_applied': bool(routing.get('lease_applied', False)),
                'starvation_lease_capacity_borrowed': bool(routing.get('starvation_lease_capacity_borrowed', False)),
                'expedite_lease_capacity_borrowed': bool(routing.get('expedite_lease_capacity_borrowed', False)),
                'temporary_hold_count': int(routing.get('temporary_hold_count') or 0),
                'temporary_hold_capacity': int(routing.get('temporary_hold_capacity') or 0),
                'temporary_hold_available': routing.get('temporary_hold_available'),
                'temporary_hold_reason': str((list(routing.get('temporary_hold_reasons') or ['']) or [''])[0] or ''),
                'temporary_hold_eligible': bool(routing.get('temporary_hold_eligible', False)),
                'temporary_hold_applied': bool(routing.get('temporary_hold_applied', False)),
                'starvation_temporary_hold_borrowed': bool(routing.get('starvation_temporary_hold_borrowed', False)),
                'expedite_temporary_hold_borrowed': bool(routing.get('expedite_temporary_hold_borrowed', False)),
                'expired_temporary_hold_count': int(routing.get('expired_temporary_hold_count') or 0),
                'effective_capacity': int(routing.get('effective_capacity') or 0),
                'alert_wait_age_s': int(routing.get('alert_wait_age_s') or 0),
                'aging_applied': bool(routing.get('aging_applied', False)),
                'starving': bool(routing.get('starving', False)),
                'queue_oldest_alert_age_s': int(routing.get('queue_oldest_alert_age_s') or 0),
                'queue_aged_alert_count': int(routing.get('queue_aged_alert_count') or 0),
                'queue_starving_alert_count': int(routing.get('queue_starving_alert_count') or 0),
                'starvation_reserved_capacity_borrowed': bool(routing.get('starvation_reserved_capacity_borrowed', False)),
                'starvation_prevention_applied': bool(routing.get('starvation_prevention_applied', False)),
                'starvation_prevention_reason': str(routing.get('starvation_prevention_reason') or ''),
                'anti_thrashing_applied': bool(routing.get('anti_thrashing_applied', False)),
                'anti_thrashing_reason': str(routing.get('anti_thrashing_reason') or ''),
                'queue_family_id': str(routing.get('queue_family_id') or ''),
                'queue_family_label': str(routing.get('queue_family_label') or ''),
                'queue_family_enabled': bool(routing.get('queue_family_enabled', False)),
                'queue_family_member_count': int(routing.get('queue_family_member_count') or 0),
                'recent_queue_hop_count': int(routing.get('recent_queue_hop_count') or 0),
                'recent_family_hop_count': int(routing.get('recent_family_hop_count') or 0),
                'family_hysteresis_applied': bool(routing.get('family_hysteresis_applied', False)),
                'family_hysteresis_reason': str(routing.get('family_hysteresis_reason') or ''),
                'route_history_queue_ids': [str(item) for item in list(routing.get('route_history_queue_ids') or []) if str(item)],
                'route_history_family_ids': [str(item) for item in list(routing.get('route_history_family_ids') or []) if str(item)],
                'sla_deadline_target': str(routing.get('sla_deadline_target') or ''),
                'time_to_breach_s': routing.get('time_to_breach_s'),
                'predicted_wait_time_s': routing.get('predicted_wait_time_s'),
                'predicted_sla_margin_s': routing.get('predicted_sla_margin_s'),
                'predicted_sla_breach': bool(routing.get('predicted_sla_breach', False)),
                'breach_risk_score': float(routing.get('breach_risk_score') or 0.0),
                'breach_risk_level': str(routing.get('breach_risk_level') or ''),
                'expected_service_time_s': int(routing.get('expected_service_time_s') or 0),
                'forecast_window_s': int(routing.get('forecast_window_s') or 0),
                'forecast_arrivals_count': int(routing.get('forecast_arrivals_count') or 0),
                'forecast_departures_count': int(routing.get('forecast_departures_count') or 0),
                'projected_active_count': int(routing.get('projected_active_count') or 0),
                'projected_load_ratio': float(routing.get('projected_load_ratio') or 0.0),
                'projected_wait_time_s': int(routing.get('projected_wait_time_s') or 0),
                'forecasted_over_capacity': bool(routing.get('forecasted_over_capacity', False)),
                'surge_predicted': bool(routing.get('surge_predicted', False)),
                'proactive_routing_eligible': bool(routing.get('proactive_routing_eligible', False)),
                'proactive_routing_applied': bool(routing.get('proactive_routing_applied', False)),
                'proactive_reason': str(routing.get('proactive_reason') or ''),
                'admission_control_enabled': bool(routing.get('admission_control_enabled', False)),
                'admission_action': str(routing.get('admission_action') or ''),
                'admission_exempt': bool(routing.get('admission_exempt', False)),
                'admission_exempt_reason': str(routing.get('admission_exempt_reason') or ''),
                'admission_decision': str(routing.get('admission_decision') or ''),
                'admission_blocked': bool(routing.get('admission_blocked', False)),
                'admission_reason': str(routing.get('admission_reason') or ''),
                'admission_review_required': bool(routing.get('admission_review_required', False)),
                'overload_governance_enabled': bool(routing.get('overload_governance_enabled', False)),
                'overload_governance_applied': bool(routing.get('overload_governance_applied', False)),
                'overload_action': str(routing.get('overload_action') or ''),
                'overload_projected_load_ratio_threshold': float(routing.get('overload_projected_load_ratio_threshold') or 0.0),
                'overload_projected_wait_time_threshold_s': int(routing.get('overload_projected_wait_time_threshold_s') or 0),
                'overload_predicted': bool(routing.get('overload_predicted', False)),
                'overload_reason': str(routing.get('overload_reason') or ''),
                'expedite_eligible': bool(routing.get('expedite_eligible', False)),
                'expedite_reserved_capacity_borrowed': bool(routing.get('expedite_reserved_capacity_borrowed', False)),
                'expedite_applied': bool(routing.get('expedite_applied', False)),
                'expedite_reason': str(routing.get('expedite_reason') or ''),
            },
            'suppression_state': {
                'suppressed': bool(suppression.get('suppressed', False)),
                'reasons': [str(item) for item in list(suppression.get('reasons') or []) if str(item)],
                'pending_escalation_level': int(suppression.get('pending_escalation_level') or 0),
                'pending_route_id': str(suppression.get('pending_route_id') or ''),
                'pending_queue_id': str(suppression.get('pending_queue_id') or ''),
                'pending_owner_role': str(suppression.get('pending_owner_role') or ''),
            },
            'handoff': {
                'count': int(handoff.get('count') or 0),
                'pending': bool(handoff.get('pending', False)),
                'active_handoff_id': str(handoff.get('active_handoff_id') or ''),
                'pending_to_owner_id': str(handoff.get('pending_to_owner_id') or ''),
                'pending_to_owner_role': str(handoff.get('pending_to_owner_role') or ''),
                'pending_to_queue_id': str(handoff.get('pending_to_queue_id') or ''),
                'pending_since': handoff.get('pending_since'),
            },
            'sla': {
                'status': str(sla.get('status') or ''),
                'breached': bool(sla.get('breached', False)),
                'breached_targets': [str(item) for item in list(sla.get('breached_targets') or []) if str(item)],
                'warning_targets': [str(item) for item in list(sla.get('warning_targets') or []) if str(item)],
                'next_deadline': sla.get('next_deadline'),
            },
            'sla_routing': {
                'status': str((payload.get('sla_routing_state') or {}).get('status') or ('routed' if str(routing.get('source') or '') == 'sla_breach_routing' else '')),
                'reroute_count': int(((payload.get('sla_routing_state') or {}).get('reroute_count')) or (1 if str(routing.get('source') or '') == 'sla_breach_routing' else 0)),
                'last_route_id': str(((payload.get('sla_routing_state') or {}).get('last_route_id')) or routing.get('route_id') or ''),
                'last_queue_id': str(((payload.get('sla_routing_state') or {}).get('last_queue_id')) or routing.get('queue_id') or ''),
                'last_owner_role': str(((payload.get('sla_routing_state') or {}).get('last_owner_role')) or routing.get('owner_role') or ''),
                'pending': bool(((payload.get('sla_routing_state') or {}).get('pending'))),
            },
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_last_alert_action(action: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(action or {})
        return {
            'action': str(payload.get('action') or ''),
            'alert_id': str(payload.get('alert_id') or ''),
            'status': str(payload.get('status') or ''),
            'ownership_status': str(payload.get('ownership_status') or ''),
            'owner_id': str(payload.get('owner_id') or ''),
            'queue_id': str(payload.get('queue_id') or ''),
            'route_id': str(payload.get('route_id') or ''),
            'at': payload.get('at'),
            'by': str(payload.get('by') or ''),
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_routing_policy_pack(payload: dict[str, Any] | None) -> dict[str, Any]:
        pack = dict(payload or {})
        if not pack:
            return {}
        review_timeline = [dict(item or {}) for item in list(pack.get('catalog_review_timeline') or pack.get('catalog_review_events') or []) if isinstance(item, dict)]
        latest_review_note = next(
            (
                item for item in reversed(review_timeline)
                if str(item.get('event_type') or '') in {'review_note', 'review_comment', 'review_decision', 'review_requested'}
            ),
            {},
        )
        return {
            'pack_id': str(pack.get('pack_id') or ''),
            'pack_label': str(pack.get('pack_label') or pack.get('label') or ''),
            'description': str(pack.get('description') or ''),
            'source': str(pack.get('source') or ''),
            'category_keys': [str(item) for item in list(pack.get('category_keys') or []) if str(item)][:8],
            'tags': [str(item) for item in list(pack.get('tags') or []) if str(item)][:8],
            'scenario_count': int(pack.get('scenario_count') or len(list(pack.get('comparison_policies') or [])) or 0),
            'created_at': pack.get('created_at'),
            'created_by': str(pack.get('created_by') or ''),
            'last_used_at': pack.get('last_used_at'),
            'use_count': int(pack.get('use_count') or 0),
            'registry_entry_id': str(pack.get('registry_entry_id') or ''),
            'registry_scope': str(pack.get('registry_scope') or ''),
            'promoted_at': pack.get('promoted_at'),
            'promoted_by': str(pack.get('promoted_by') or ''),
            'promoted_from_pack_id': str(pack.get('promoted_from_pack_id') or ''),
            'promoted_from_source': str(pack.get('promoted_from_source') or ''),
            'shared_from_pack_id': str(pack.get('shared_from_pack_id') or ''),
            'shared_from_source': str(pack.get('shared_from_source') or ''),
            'last_shared_at': pack.get('last_shared_at'),
            'last_shared_by': str(pack.get('last_shared_by') or ''),
            'share_count': int(pack.get('share_count') or 0),
            'share_targets': [str(item) for item in list(pack.get('share_targets') or []) if str(item)][:8],
            'catalog_entry_id': str(pack.get('catalog_entry_id') or ''),
            'catalog_scope': str(pack.get('catalog_scope') or ''),
            'catalog_scope_key': str(pack.get('catalog_scope_key') or ''),
            'promotion_id': str(pack.get('promotion_id') or ''),
            'workspace_id': str(pack.get('workspace_id') or ''),
            'environment': str(pack.get('environment') or ''),
            'portfolio_family_id': str(pack.get('portfolio_family_id') or ''),
            'runtime_family_id': str(pack.get('runtime_family_id') or ''),
            'catalog_promoted_at': pack.get('catalog_promoted_at'),
            'catalog_promoted_by': str(pack.get('catalog_promoted_by') or ''),
            'catalog_share_count': int(pack.get('catalog_share_count') or 0),
            'catalog_last_shared_at': pack.get('catalog_last_shared_at'),
            'catalog_last_shared_by': str(pack.get('catalog_last_shared_by') or ''),
            'catalog_version_key': str(pack.get('catalog_version_key') or ''),
            'catalog_version': int(pack.get('catalog_version') or 0),
            'catalog_lifecycle_state': str(pack.get('catalog_lifecycle_state') or 'draft'),
            'catalog_curated_at': pack.get('catalog_curated_at'),
            'catalog_curated_by': str(pack.get('catalog_curated_by') or ''),
            'catalog_approved_at': pack.get('catalog_approved_at'),
            'catalog_approved_by': str(pack.get('catalog_approved_by') or ''),
            'catalog_deprecated_at': pack.get('catalog_deprecated_at'),
            'catalog_deprecated_by': str(pack.get('catalog_deprecated_by') or ''),
            'catalog_replaced_by_version': int(pack.get('catalog_replaced_by_version') or 0),
            'catalog_is_latest': bool(pack.get('catalog_is_latest', False)),
            'catalog_approval_required': bool(pack.get('catalog_approval_required', False)),
            'catalog_required_approvals': int(pack.get('catalog_required_approvals') or 0),
            'catalog_approval_count': int(pack.get('catalog_approval_count') or 0),
            'catalog_approval_state': str(pack.get('catalog_approval_state') or ''),
            'catalog_approval_requested_at': pack.get('catalog_approval_requested_at'),
            'catalog_approval_requested_by': str(pack.get('catalog_approval_requested_by') or ''),
            'catalog_approval_rejected_at': pack.get('catalog_approval_rejected_at'),
            'catalog_approval_rejected_by': str(pack.get('catalog_approval_rejected_by') or ''),
            'catalog_approvals': [
                {
                    'approval_id': str(item.get('approval_id') or ''),
                    'decision': str(item.get('decision') or ''),
                    'actor': str(item.get('actor') or ''),
                    'role': str(item.get('role') or ''),
                    'at': item.get('at'),
                }
                for item in list(pack.get('catalog_approvals') or [])[:6]
                if isinstance(item, dict)
            ],
            'catalog_review_state': str(pack.get('catalog_review_state') or ''),
            'catalog_review_requested_at': pack.get('catalog_review_requested_at'),
            'catalog_review_requested_by': str(pack.get('catalog_review_requested_by') or ''),
            'catalog_review_assigned_reviewer': str(pack.get('catalog_review_assigned_reviewer') or ''),
            'catalog_review_assigned_role': str(pack.get('catalog_review_assigned_role') or ''),
            'catalog_review_claimed_by': str(pack.get('catalog_review_claimed_by') or ''),
            'catalog_review_claimed_at': pack.get('catalog_review_claimed_at'),
            'catalog_review_last_transition_at': pack.get('catalog_review_last_transition_at'),
            'catalog_review_last_transition_by': str(pack.get('catalog_review_last_transition_by') or ''),
            'catalog_review_last_transition_action': str(pack.get('catalog_review_last_transition_action') or ''),
            'catalog_review_decision_at': pack.get('catalog_review_decision_at'),
            'catalog_review_decision_by': str(pack.get('catalog_review_decision_by') or ''),
            'catalog_review_decision': str(pack.get('catalog_review_decision') or ''),
            'catalog_review_note_count': int(pack.get('catalog_review_note_count') or len(review_timeline) or 0),
            'catalog_review_latest_note': {
                'event_type': str(latest_review_note.get('event_type') or ''),
                'actor': str(latest_review_note.get('actor') or ''),
                'role': str(latest_review_note.get('role') or ''),
                'at': latest_review_note.get('at'),
                'note': str(latest_review_note.get('note') or ''),
                'decision': str(latest_review_note.get('decision') or ''),
            },
            'catalog_review_timeline': [
                {
                    'event_id': str(item.get('event_id') or ''),
                    'event_type': str(item.get('event_type') or ''),
                    'state': str(item.get('state') or ''),
                    'actor': str(item.get('actor') or ''),
                    'role': str(item.get('role') or ''),
                    'at': item.get('at'),
                    'note': str(item.get('note') or '')[:160],
                    'decision': str(item.get('decision') or ''),
                }
                for item in review_timeline[:6]
            ],
            'catalog_dependency_refs': [
                {
                    'dependency_id': str(item.get('dependency_id') or ''),
                    'catalog_entry_id': str(item.get('catalog_entry_id') or ''),
                    'catalog_version_key': str(item.get('catalog_version_key') or ''),
                    'min_catalog_version': int(item.get('min_catalog_version') or 0),
                    'required_lifecycle_state': str(item.get('required_lifecycle_state') or ''),
                    'required_release_state': str(item.get('required_release_state') or ''),
                }
                for item in list(pack.get('catalog_dependency_refs') or [])[:6]
                if isinstance(item, dict)
            ],
            'catalog_dependency_summary': dict(pack.get('catalog_dependency_summary') or {}),
            'catalog_conflict_rules': dict(pack.get('catalog_conflict_rules') or {}),
            'catalog_conflict_summary': dict(pack.get('catalog_conflict_summary') or {}),
            'catalog_freeze_windows': [
                {
                    'window_id': str(item.get('window_id') or ''),
                    'label': str(item.get('label') or ''),
                    'start_at': item.get('start_at'),
                    'end_at': item.get('end_at'),
                    'reason': str(item.get('reason') or ''),
                    'block_stage': bool(item.get('block_stage', False)),
                    'block_release': bool(item.get('block_release', False)),
                    'block_advance': bool(item.get('block_advance', False)),
                }
                for item in list(pack.get('catalog_freeze_windows') or [])[:6]
                if isinstance(item, dict)
            ],
            'catalog_freeze_summary': dict(pack.get('catalog_freeze_summary') or {}),
            'catalog_release_guard': dict(pack.get('catalog_release_guard') or {}),
            'catalog_release_state': str(pack.get('catalog_release_state') or 'draft'),
            'catalog_release_notes': str(pack.get('catalog_release_notes') or ''),
            'catalog_release_train_id': str(pack.get('catalog_release_train_id') or ''),
            'catalog_release_staged_at': pack.get('catalog_release_staged_at'),
            'catalog_release_staged_by': str(pack.get('catalog_release_staged_by') or ''),
            'catalog_released_at': pack.get('catalog_released_at'),
            'catalog_released_by': str(pack.get('catalog_released_by') or ''),
            'catalog_withdrawn_at': pack.get('catalog_withdrawn_at'),
            'catalog_withdrawn_by': str(pack.get('catalog_withdrawn_by') or ''),
            'catalog_withdrawn_reason': str(pack.get('catalog_withdrawn_reason') or ''),
            'catalog_supersedence_summary': LiveCanvasService._baseline_promotion_simulation_custody_catalog_supersedence_summary(pack),
            'catalog_release_rollback_summary': LiveCanvasService._baseline_promotion_simulation_custody_catalog_release_rollback_summary(pack),
            'catalog_emergency_withdrawal_summary': LiveCanvasService._baseline_promotion_simulation_custody_catalog_emergency_withdrawal_summary(pack),
            'catalog_rollout_summary': LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_summary(pack),
            'catalog_rollout_enabled': bool(pack.get('catalog_rollout_enabled', False)),
            'catalog_rollout_train_id': str(pack.get('catalog_rollout_train_id') or ''),
            'catalog_rollout_state': str(pack.get('catalog_rollout_state') or ''),
            'catalog_rollout_current_wave_index': int(pack.get('catalog_rollout_current_wave_index') or 0),
            'catalog_rollout_completed_wave_count': int(pack.get('catalog_rollout_completed_wave_count') or 0),
            'catalog_rollout_paused': bool(pack.get('catalog_rollout_paused', False)),
            'catalog_rollout_frozen': bool(pack.get('catalog_rollout_frozen', False)),
            'catalog_rollout_last_transition_at': pack.get('catalog_rollout_last_transition_at'),
            'catalog_rollout_last_transition_by': str(pack.get('catalog_rollout_last_transition_by') or ''),
            'catalog_rollout_last_transition_action': str(pack.get('catalog_rollout_last_transition_action') or ''),
            'catalog_rollout_latest_gate': dict(pack.get('catalog_rollout_latest_gate') or {}),
            'catalog_rollout_waves': [
                {
                    'wave_index': int(item.get('wave_index') or 0),
                    'status': str(item.get('status') or ''),
                    'target_count': len([key for key in list(item.get('target_keys') or []) if str(key)]),
                    'released_at': item.get('released_at'),
                    'released_by': str(item.get('released_by') or ''),
                    'gate_evaluation': dict(item.get('gate_evaluation') or {}),
                }
                for item in list(pack.get('catalog_rollout_waves') or [])[:4]
                if isinstance(item, dict)
            ],
            'catalog_rollout_targets': [
                {
                    'target_key': str(item.get('target_key') or ''),
                    'promotion_id': str(item.get('promotion_id') or ''),
                    'workspace_id': str(item.get('workspace_id') or ''),
                    'environment': str(item.get('environment') or ''),
                    'released': bool(item.get('released', False)),
                    'released_wave_index': int(item.get('released_wave_index') or 0),
                }
                for item in list(pack.get('catalog_rollout_targets') or [])[:6]
                if isinstance(item, dict)
            ],
            'catalog_attestation_count': int(pack.get('catalog_attestation_count') or 0),
            'catalog_latest_attestation': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_attestation') or {}),
            'catalog_evidence_package_count': int(pack.get('catalog_evidence_package_count') or 0),
            'catalog_latest_evidence_package': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_evidence_package') or {}),
            'catalog_release_bundle_count': int(pack.get('catalog_release_bundle_count') or 0),
            'catalog_latest_release_bundle': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_release_bundle') or {}),
            'catalog_compliance_summary': dict(pack.get('catalog_compliance_summary') or {}),
            'catalog_compliance_report_count': int(pack.get('catalog_compliance_report_count') or 0),
            'catalog_latest_compliance_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_compliance_report') or {}),
            'catalog_replay_count': int(pack.get('catalog_replay_count') or 0),
            'catalog_last_replayed_at': pack.get('catalog_last_replayed_at'),
            'catalog_last_replayed_by': str(pack.get('catalog_last_replayed_by') or ''),
            'catalog_last_replay_source': str(pack.get('catalog_last_replay_source') or ''),
            'catalog_binding_count': int(pack.get('catalog_binding_count') or 0),
            'catalog_last_bound_at': pack.get('catalog_last_bound_at'),
            'catalog_last_bound_by': str(pack.get('catalog_last_bound_by') or ''),
            'catalog_analytics_summary': dict(pack.get('catalog_analytics_summary') or {}),
            'catalog_analytics_report_count': int(pack.get('catalog_analytics_report_count') or 0),
            'catalog_latest_analytics_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_analytics_report') or {}),
            'organizational_service_id': str(pack.get('organizational_service_id') or ''),
            'organizational_service_entry_id': str(pack.get('organizational_service_entry_id') or ''),
            'organizational_publish_state': str(pack.get('organizational_publish_state') or ''),
            'organizational_visibility': str(pack.get('organizational_visibility') or 'tenant'),
            'organizational_service_scope_key': str(pack.get('organizational_service_scope_key') or ''),
            'organizational_published_at': pack.get('organizational_published_at'),
            'organizational_published_by': str(pack.get('organizational_published_by') or ''),
            'organizational_withdrawn_at': pack.get('organizational_withdrawn_at'),
            'organizational_withdrawn_by': str(pack.get('organizational_withdrawn_by') or ''),
            'organizational_withdrawn_reason': str(pack.get('organizational_withdrawn_reason') or ''),
            'organizational_publication_manifest': {
                'manifest_type': str((pack.get('organizational_publication_manifest') or {}).get('manifest_type') or ''),
                'manifest_digest': str((pack.get('organizational_publication_manifest') or {}).get('manifest_digest') or ''),
                'policy_digest': str((pack.get('organizational_publication_manifest') or {}).get('policy_digest') or ''),
                'published_at': (pack.get('organizational_publication_manifest') or {}).get('published_at'),
                'published_by': str((pack.get('organizational_publication_manifest') or {}).get('published_by') or ''),
            },
            'organizational_publication_health': dict(pack.get('organizational_publication_health') or {}),
            'organizational_reconciliation_report_count': int(pack.get('organizational_reconciliation_report_count') or 0),
            'organizational_latest_reconciliation_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('organizational_latest_reconciliation_report') or {}),
            'catalog_binding_summary': dict(pack.get('catalog_binding_summary') or {}),
            'catalog_effective_binding': LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding(pack.get('catalog_effective_binding') or {}),
            'catalog_is_effective_for_current_scope': bool(pack.get('catalog_is_effective_for_current_scope', False)),
            'report_id': str(pack.get('report_id') or ''),
            'report_type': str(pack.get('report_type') or ''),
            'at': pack.get('at'),
            'by': str(pack.get('by') or ''),
            'catalog_owner_canvas_id': str(pack.get('catalog_owner_canvas_id') or ''),
            'catalog_owner_node_id': str(pack.get('catalog_owner_node_id') or ''),
            'scenarios': [
                {
                    'scenario_id': str(item.get('scenario_id') or ''),
                    'scenario_label': str(item.get('scenario_label') or item.get('label') or ''),
                    'policy_delta_keys': [str(key) for key in list(item.get('policy_delta_keys') or []) if str(key)][:12],
                }
                for item in list(pack.get('comparison_policies') or pack.get('scenarios') or [])[:6]
                if isinstance(item, dict)
            ],
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_routing_replay(payload: dict[str, Any] | None) -> dict[str, Any]:
        replay = dict(payload or {})
        current_route = dict(replay.get('current_route') or {})
        current_policy = dict(replay.get('current_policy') or {})
        current_explainability = dict(current_policy.get('explainability') or {})
        compact_scenarios = []
        raw_scenarios = list(replay.get('scenarios') or [])

        for item in raw_scenarios[:6]:
            scenario = dict(item or {})
            route = dict(scenario.get('route') or {})
            explainability = dict(scenario.get('explainability') or {})
            compact_scenarios.append({
                'scenario_id': str(scenario.get('scenario_id') or ''),
                'scenario_label': str(scenario.get('scenario_label') or ''),
                'policy_delta_keys': [str(key) for key in list(scenario.get('policy_delta_keys') or []) if str(key)][:12],
                'route': {
                    'route_id': str(route.get('route_id') or ''),
                    'queue_id': str(route.get('queue_id') or ''),
                    'queue_label': str(route.get('queue_label') or ''),
                    'queue_family_id': str(route.get('queue_family_id') or ''),
                    'selection_reason': str(route.get('selection_reason') or ''),
                    'anti_thrashing_applied': bool(route.get('anti_thrashing_applied', False)),
                    'family_hysteresis_applied': bool(route.get('family_hysteresis_applied', False)),
                    'expedite_applied': bool(route.get('expedite_applied', False)),
                    'proactive_routing_applied': bool(route.get('proactive_routing_applied', False)),
                    'admission_blocked': bool(route.get('admission_blocked', False)),
                },
                'explainability': {
                    'kept_current_queue': bool(explainability.get('kept_current_queue', False)),
                    'queue_changed': bool(explainability.get('queue_changed', False)),
                    'why_kept_current_queue': str(explainability.get('why_kept_current_queue') or ''),
                    'bypassed_hysteresis': bool(explainability.get('bypassed_hysteresis', False)),
                    'why_bypassed_hysteresis': str(explainability.get('why_bypassed_hysteresis') or ''),
                    'selection_reason': str(explainability.get('selection_reason') or ''),
                },
            })

        current_policy_present = bool(current_policy) and bool(
            str(current_policy.get('scenario_id') or '')
            or str(current_policy.get('scenario_label') or '')
            or str(((current_policy.get('route') or {}).get('queue_id')) or '')
            or str(((current_policy.get('route') or {}).get('route_id')) or '')
        )

        current_policy_scenario_id = str(current_policy.get('scenario_id') or '')
        current_policy_already_listed = bool(current_policy_scenario_id) and any(
            str((item or {}).get('scenario_id') or '') == current_policy_scenario_id
            for item in raw_scenarios
        )
        current_policy_extra = 1 if (current_policy_present and not current_policy_already_listed) else 0

        computed_scenario_count = max(
            len(compact_scenarios) + current_policy_extra,
            len(raw_scenarios) + current_policy_extra,
        )

        return {
            'alert_id': str(replay.get('alert_id') or ''),
            'applied_pack': LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(replay.get('applied_pack') or {}),
            'current_route': {
                'route_id': str(current_route.get('route_id') or ''),
                'queue_id': str(current_route.get('queue_id') or ''),
                'queue_label': str(current_route.get('queue_label') or ''),
                'queue_family_id': str(current_route.get('queue_family_id') or ''),
                'selection_reason': str(current_route.get('selection_reason') or ''),
            },
            'current_policy': {
                'scenario_id': str(current_policy.get('scenario_id') or ''),
                'scenario_label': str(current_policy.get('scenario_label') or ''),
                'route': {
                    'route_id': str(((current_policy.get('route') or {}).get('route_id')) or ''),
                    'queue_id': str(((current_policy.get('route') or {}).get('queue_id')) or ''),
                    'queue_label': str(((current_policy.get('route') or {}).get('queue_label')) or ''),
                    'selection_reason': str(((current_policy.get('route') or {}).get('selection_reason')) or ''),
                },
                'explainability': {
                    'kept_current_queue': bool(current_explainability.get('kept_current_queue', False)),
                    'queue_changed': bool(current_explainability.get('queue_changed', False)),
                    'why_kept_current_queue': str(current_explainability.get('why_kept_current_queue') or ''),
                    'bypassed_hysteresis': bool(current_explainability.get('bypassed_hysteresis', False)),
                    'why_bypassed_hysteresis': str(current_explainability.get('why_bypassed_hysteresis') or ''),
                    'selection_reason': str(current_explainability.get('selection_reason') or ''),
                    'policy_delta_keys': [str(key) for key in list(current_explainability.get('policy_delta_keys') or []) if str(key)][:12],
                },
            },
            'scenario_count': computed_scenario_count,
            'scenarios': compact_scenarios,
        }
    @staticmethod
    def _compact_baseline_promotion_simulation_routing_policy_pack_for_storage(payload: dict[str, Any] | None) -> dict[str, Any]:
        pack = dict(payload or {})
        return {
            'pack_id': str(pack.get('pack_id') or ''),
            'pack_label': str(pack.get('pack_label') or pack.get('label') or ''),
            'source': str(pack.get('source') or 'saved'),
            'category_keys': [str(item) for item in list(pack.get('category_keys') or []) if str(item)][:8],
            'tags': [str(item) for item in list(pack.get('tags') or []) if str(item)][:8],
            'created_at': pack.get('created_at'),
            'created_by': str(pack.get('created_by') or ''),
            'last_used_at': pack.get('last_used_at'),
            'use_count': int(pack.get('use_count') or 0),
            'registry_entry_id': str(pack.get('registry_entry_id') or ''),
            'registry_scope': str(pack.get('registry_scope') or ''),
            'promoted_at': pack.get('promoted_at'),
            'promoted_by': str(pack.get('promoted_by') or ''),
            'promoted_from_pack_id': str(pack.get('promoted_from_pack_id') or ''),
            'promoted_from_source': str(pack.get('promoted_from_source') or ''),
            'shared_from_pack_id': str(pack.get('shared_from_pack_id') or ''),
            'shared_from_source': str(pack.get('shared_from_source') or ''),
            'last_shared_at': pack.get('last_shared_at'),
            'last_shared_by': str(pack.get('last_shared_by') or ''),
            'share_count': int(pack.get('share_count') or 0),
            'share_targets': [str(item) for item in list(pack.get('share_targets') or []) if str(item)][:8],
            'catalog_entry_id': str(pack.get('catalog_entry_id') or ''),
            'catalog_scope': str(pack.get('catalog_scope') or ''),
            'catalog_scope_key': str(pack.get('catalog_scope_key') or ''),
            'promotion_id': str(pack.get('promotion_id') or ''),
            'workspace_id': str(pack.get('workspace_id') or ''),
            'environment': str(pack.get('environment') or ''),
            'portfolio_family_id': str(pack.get('portfolio_family_id') or ''),
            'runtime_family_id': str(pack.get('runtime_family_id') or ''),
            'catalog_promoted_at': pack.get('catalog_promoted_at'),
            'catalog_promoted_by': str(pack.get('catalog_promoted_by') or ''),
            'catalog_share_count': int(pack.get('catalog_share_count') or 0),
            'catalog_last_shared_at': pack.get('catalog_last_shared_at'),
            'catalog_last_shared_by': str(pack.get('catalog_last_shared_by') or ''),
            'catalog_version_key': str(pack.get('catalog_version_key') or ''),
            'catalog_version': int(pack.get('catalog_version') or 0),
            'catalog_lifecycle_state': str(pack.get('catalog_lifecycle_state') or 'draft'),
            'catalog_curated_at': pack.get('catalog_curated_at'),
            'catalog_curated_by': str(pack.get('catalog_curated_by') or ''),
            'catalog_approved_at': pack.get('catalog_approved_at'),
            'catalog_approved_by': str(pack.get('catalog_approved_by') or ''),
            'catalog_deprecated_at': pack.get('catalog_deprecated_at'),
            'catalog_deprecated_by': str(pack.get('catalog_deprecated_by') or ''),
            'catalog_replaced_by_version': int(pack.get('catalog_replaced_by_version') or 0),
            'catalog_is_latest': bool(pack.get('catalog_is_latest', False)),
            'catalog_approval_required': bool(pack.get('catalog_approval_required', False)),
            'catalog_required_approvals': int(pack.get('catalog_required_approvals') or 0),
            'catalog_approval_count': int(pack.get('catalog_approval_count') or 0),
            'catalog_approval_state': str(pack.get('catalog_approval_state') or ''),
            'catalog_approval_requested_at': pack.get('catalog_approval_requested_at'),
            'catalog_approval_requested_by': str(pack.get('catalog_approval_requested_by') or ''),
            'catalog_approval_rejected_at': pack.get('catalog_approval_rejected_at'),
            'catalog_approval_rejected_by': str(pack.get('catalog_approval_rejected_by') or ''),
            'catalog_approvals': [
                {
                    'approval_id': str(item.get('approval_id') or ''),
                    'decision': str(item.get('decision') or ''),
                    'actor': str(item.get('actor') or ''),
                    'role': str(item.get('role') or ''),
                    'at': item.get('at'),
                    'note': str(item.get('note') or ''),
                }
                for item in list(pack.get('catalog_approvals') or [])[:8]
                if isinstance(item, dict)
            ],
            'catalog_review_state': str(pack.get('catalog_review_state') or ''),
            'catalog_review_requested_at': pack.get('catalog_review_requested_at'),
            'catalog_review_requested_by': str(pack.get('catalog_review_requested_by') or ''),
            'catalog_review_assigned_reviewer': str(pack.get('catalog_review_assigned_reviewer') or ''),
            'catalog_review_assigned_role': str(pack.get('catalog_review_assigned_role') or ''),
            'catalog_review_claimed_by': str(pack.get('catalog_review_claimed_by') or ''),
            'catalog_review_claimed_at': pack.get('catalog_review_claimed_at'),
            'catalog_review_last_transition_at': pack.get('catalog_review_last_transition_at'),
            'catalog_review_last_transition_by': str(pack.get('catalog_review_last_transition_by') or ''),
            'catalog_review_last_transition_action': str(pack.get('catalog_review_last_transition_action') or ''),
            'catalog_review_decision_at': pack.get('catalog_review_decision_at'),
            'catalog_review_decision_by': str(pack.get('catalog_review_decision_by') or ''),
            'catalog_review_decision': str(pack.get('catalog_review_decision') or ''),
            'catalog_review_note_count': int(pack.get('catalog_review_note_count') or 0),
            'catalog_review_events': [
                {
                    'event_id': str(item.get('event_id') or ''),
                    'event_type': str(item.get('event_type') or ''),
                    'state': str(item.get('state') or ''),
                    'actor': str(item.get('actor') or ''),
                    'role': str(item.get('role') or ''),
                    'at': item.get('at'),
                    'note': str(item.get('note') or '')[:160],
                    'decision': str(item.get('decision') or ''),
                }
                for item in list(pack.get('catalog_review_events') or pack.get('catalog_review_timeline') or [])[:8]
                if isinstance(item, dict)
            ],
            'catalog_dependency_refs': LiveCanvasService._baseline_promotion_simulation_custody_catalog_dependency_refs(pack.get('catalog_dependency_refs') or []),
            'catalog_conflict_rules': LiveCanvasService._baseline_promotion_simulation_custody_catalog_conflict_rules(pack.get('catalog_conflict_rules') or {}),
            'catalog_freeze_windows': LiveCanvasService._baseline_promotion_simulation_custody_catalog_freeze_windows(pack.get('catalog_freeze_windows') or []),
            'catalog_release_state': str(pack.get('catalog_release_state') or 'draft'),
            'catalog_release_notes': str(pack.get('catalog_release_notes') or ''),
            'catalog_release_train_id': str(pack.get('catalog_release_train_id') or ''),
            'catalog_release_staged_at': pack.get('catalog_release_staged_at'),
            'catalog_release_staged_by': str(pack.get('catalog_release_staged_by') or ''),
            'catalog_released_at': pack.get('catalog_released_at'),
            'catalog_released_by': str(pack.get('catalog_released_by') or ''),
            'catalog_withdrawn_at': pack.get('catalog_withdrawn_at'),
            'catalog_withdrawn_by': str(pack.get('catalog_withdrawn_by') or ''),
            'catalog_withdrawn_reason': str(pack.get('catalog_withdrawn_reason') or ''),
            'catalog_supersedence_state': str(pack.get('catalog_supersedence_state') or ''),
            'catalog_superseded_at': pack.get('catalog_superseded_at'),
            'catalog_superseded_by': str(pack.get('catalog_superseded_by') or ''),
            'catalog_superseded_reason': str(pack.get('catalog_superseded_reason') or ''),
            'catalog_superseded_by_entry_id': str(pack.get('catalog_superseded_by_entry_id') or ''),
            'catalog_superseded_by_version': int(pack.get('catalog_superseded_by_version') or 0),
            'catalog_superseded_by_bundle_id': str(pack.get('catalog_superseded_by_bundle_id') or ''),
            'catalog_supersedes_entry_id': str(pack.get('catalog_supersedes_entry_id') or ''),
            'catalog_supersedes_version': int(pack.get('catalog_supersedes_version') or 0),
            'catalog_restored_from_entry_id': str(pack.get('catalog_restored_from_entry_id') or ''),
            'catalog_restored_from_version': int(pack.get('catalog_restored_from_version') or 0),
            'catalog_restored_at': pack.get('catalog_restored_at'),
            'catalog_restored_by': str(pack.get('catalog_restored_by') or ''),
            'catalog_restored_reason': str(pack.get('catalog_restored_reason') or ''),
            'catalog_rollback_release_state': str(pack.get('catalog_rollback_release_state') or ''),
            'catalog_rollback_release_at': pack.get('catalog_rollback_release_at'),
            'catalog_rollback_release_by': str(pack.get('catalog_rollback_release_by') or ''),
            'catalog_rollback_release_reason': str(pack.get('catalog_rollback_release_reason') or ''),
            'catalog_rollback_target_entry_id': str(pack.get('catalog_rollback_target_entry_id') or ''),
            'catalog_rollback_target_version': int(pack.get('catalog_rollback_target_version') or 0),
            'catalog_emergency_withdrawal_active': bool(pack.get('catalog_emergency_withdrawal_active', False)),
            'catalog_emergency_withdrawal_at': pack.get('catalog_emergency_withdrawal_at'),
            'catalog_emergency_withdrawal_by': str(pack.get('catalog_emergency_withdrawal_by') or ''),
            'catalog_emergency_withdrawal_reason': str(pack.get('catalog_emergency_withdrawal_reason') or ''),
            'catalog_emergency_withdrawal_incident_id': str(pack.get('catalog_emergency_withdrawal_incident_id') or ''),
            'catalog_emergency_withdrawal_severity': str(pack.get('catalog_emergency_withdrawal_severity') or ''),
            'catalog_rollout_enabled': bool(pack.get('catalog_rollout_enabled', False)),
            'catalog_rollout_policy': LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_policy(pack.get('catalog_rollout_policy') or {}),
            'catalog_rollout_train_id': str(pack.get('catalog_rollout_train_id') or ''),
            'catalog_rollout_state': str(pack.get('catalog_rollout_state') or ''),
            'catalog_rollout_current_wave_index': int(pack.get('catalog_rollout_current_wave_index') or 0),
            'catalog_rollout_completed_wave_count': int(pack.get('catalog_rollout_completed_wave_count') or 0),
            'catalog_rollout_paused': bool(pack.get('catalog_rollout_paused', False)),
            'catalog_rollout_frozen': bool(pack.get('catalog_rollout_frozen', False)),
            'catalog_rollout_started_at': pack.get('catalog_rollout_started_at'),
            'catalog_rollout_started_by': str(pack.get('catalog_rollout_started_by') or ''),
            'catalog_rollout_completed_at': pack.get('catalog_rollout_completed_at'),
            'catalog_rollout_completed_by': str(pack.get('catalog_rollout_completed_by') or ''),
            'catalog_rollout_rolled_back_at': pack.get('catalog_rollout_rolled_back_at'),
            'catalog_rollout_rolled_back_by': str(pack.get('catalog_rollout_rolled_back_by') or ''),
            'catalog_rollout_rolled_back_reason': str(pack.get('catalog_rollout_rolled_back_reason') or ''),
            'catalog_rollout_last_transition_at': pack.get('catalog_rollout_last_transition_at'),
            'catalog_rollout_last_transition_by': str(pack.get('catalog_rollout_last_transition_by') or ''),
            'catalog_rollout_last_transition_action': str(pack.get('catalog_rollout_last_transition_action') or ''),
            'catalog_rollout_latest_gate': dict(pack.get('catalog_rollout_latest_gate') or {}),
            'catalog_rollout_targets': [
                {
                    'target_key': str(item.get('target_key') or ''),
                    'promotion_id': str(item.get('promotion_id') or ''),
                    'workspace_id': str(item.get('workspace_id') or ''),
                    'environment': str(item.get('environment') or ''),
                    'released': bool(item.get('released', False)),
                    'released_wave_index': int(item.get('released_wave_index') or 0),
                    'released_at': item.get('released_at'),
                    'released_by': str(item.get('released_by') or ''),
                }
                for item in list(pack.get('catalog_rollout_targets') or [])[:24]
                if isinstance(item, dict)
            ],
            'catalog_rollout_waves': [
                {
                    'wave_index': int(item.get('wave_index') or 0),
                    'target_keys': [str(key) for key in list(item.get('target_keys') or []) if str(key)][:24],
                    'status': str(item.get('status') or ''),
                    'released_target_count': int(item.get('released_target_count') or 0),
                    'released_at': item.get('released_at'),
                    'released_by': str(item.get('released_by') or ''),
                    'gate_evaluation': dict(item.get('gate_evaluation') or {}),
                }
                for item in list(pack.get('catalog_rollout_waves') or [])[:12]
                if isinstance(item, dict)
            ],
            'catalog_attestation_count': int(pack.get('catalog_attestation_count') or 0),
            'catalog_latest_attestation': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_attestation') or {}),
            'catalog_evidence_package_count': int(pack.get('catalog_evidence_package_count') or 0),
            'catalog_latest_evidence_package': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_evidence_package') or {}),
            'catalog_release_bundle_count': int(pack.get('catalog_release_bundle_count') or 0),
            'catalog_latest_release_bundle': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_release_bundle') or {}),
            'catalog_compliance_report_count': int(pack.get('catalog_compliance_report_count') or 0),
            'catalog_latest_compliance_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_compliance_report') or {}),
            'catalog_replay_count': int(pack.get('catalog_replay_count') or 0),
            'catalog_last_replayed_at': pack.get('catalog_last_replayed_at'),
            'catalog_last_replayed_by': str(pack.get('catalog_last_replayed_by') or ''),
            'catalog_last_replay_source': str(pack.get('catalog_last_replay_source') or ''),
            'catalog_binding_count': int(pack.get('catalog_binding_count') or 0),
            'catalog_last_bound_at': pack.get('catalog_last_bound_at'),
            'catalog_last_bound_by': str(pack.get('catalog_last_bound_by') or ''),
            'catalog_analytics_report_count': int(pack.get('catalog_analytics_report_count') or 0),
            'catalog_latest_analytics_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_analytics_report') or {}),
            'organizational_service_id': str(pack.get('organizational_service_id') or ''),
            'organizational_service_entry_id': str(pack.get('organizational_service_entry_id') or ''),
            'organizational_publish_state': str(pack.get('organizational_publish_state') or ''),
            'organizational_visibility': str(pack.get('organizational_visibility') or 'tenant'),
            'organizational_service_scope_key': str(pack.get('organizational_service_scope_key') or ''),
            'organizational_published_at': pack.get('organizational_published_at'),
            'organizational_published_by': str(pack.get('organizational_published_by') or ''),
            'organizational_withdrawn_at': pack.get('organizational_withdrawn_at'),
            'organizational_withdrawn_by': str(pack.get('organizational_withdrawn_by') or ''),
            'organizational_withdrawn_reason': str(pack.get('organizational_withdrawn_reason') or ''),
            'organizational_publication_manifest': {
                'manifest_type': str((pack.get('organizational_publication_manifest') or {}).get('manifest_type') or ''),
                'manifest_digest': str((pack.get('organizational_publication_manifest') or {}).get('manifest_digest') or ''),
                'policy_digest': str((pack.get('organizational_publication_manifest') or {}).get('policy_digest') or ''),
                'published_at': (pack.get('organizational_publication_manifest') or {}).get('published_at'),
                'published_by': str((pack.get('organizational_publication_manifest') or {}).get('published_by') or ''),
            },
            'organizational_publication_health': dict(pack.get('organizational_publication_health') or {}),
            'organizational_reconciliation_report_count': int(pack.get('organizational_reconciliation_report_count') or 0),
            'organizational_latest_reconciliation_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('organizational_latest_reconciliation_report') or {}),
            'catalog_binding_summary': dict(pack.get('catalog_binding_summary') or {}),
            'catalog_effective_binding': LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding(pack.get('catalog_effective_binding') or {}),
            'catalog_is_effective_for_current_scope': bool(pack.get('catalog_is_effective_for_current_scope', False)),
            'report_id': str(pack.get('report_id') or ''),
            'report_type': str(pack.get('report_type') or ''),
            'at': pack.get('at'),
            'by': str(pack.get('by') or ''),
            'comparison_policies': [
                {
                    'scenario_id': str(item.get('scenario_id') or ''),
                    'scenario_label': str(item.get('scenario_label') or item.get('label') or ''),
                    'policy_overrides': dict(item.get('policy_overrides') or item.get('overrides') or {}),
                }
                for item in list(pack.get('comparison_policies') or [])[:8]
                if isinstance(item, dict)
            ],
        }

    def _baseline_promotion_simulation_custody_builtin_policy_packs(self, promotion_detail: dict[str, Any] | None) -> list[dict[str, Any]]:
        monitoring = dict(((promotion_detail or {}).get('simulation_custody_monitoring') or {}))
        policy = dict(monitoring.get('policy') or {})
        return self.openclaw_recovery_scheduler_service._baseline_promotion_simulation_custody_builtin_policy_what_if_packs(policy)

    def _baseline_promotion_simulation_custody_saved_policy_packs(self, raw_packs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(list(raw_packs or []), start=1):
            if not isinstance(item, dict):
                continue
            normalized.append(self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str(item.get('created_by') or ''), index=index, source=str(item.get('source') or 'saved')))
        return normalized

    def _baseline_promotion_simulation_custody_registry_policy_packs(self, raw_packs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(list(raw_packs or []), start=1):
            if not isinstance(item, dict):
                continue
            normalized.append(self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str(item.get('created_by') or item.get('promoted_by') or ''), index=index, source=str(item.get('source') or 'registry')))
        return normalized

    def _resolve_baseline_promotion_simulation_custody_policy_pack(self, *, promotion_detail: dict[str, Any] | None, raw_saved_packs: list[dict[str, Any]] | None, pack_id: str | None, raw_registry_packs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        target_pack_id = str(pack_id or '').strip()
        if not target_pack_id:
            return {}
        saved = self._baseline_promotion_simulation_custody_saved_policy_packs(raw_saved_packs)
        registry = self._baseline_promotion_simulation_custody_registry_policy_packs(raw_registry_packs)
        builtins = self._baseline_promotion_simulation_custody_builtin_policy_packs(promotion_detail)
        saved_match = next((item for item in saved if str(item.get('pack_id') or '') == target_pack_id), {})
        if saved_match:
            if list(saved_match.get('comparison_policies') or []):
                return saved_match
            fallback_ids = [
                str(saved_match.get('shared_from_pack_id') or ''),
                str(saved_match.get('promoted_from_pack_id') or ''),
                target_pack_id,
            ]
            fallback = {}
            for candidate_id in [item for item in fallback_ids if item]:
                fallback = next((item for item in builtins if str(item.get('pack_id') or '') == candidate_id), {})
                if fallback:
                    break
                fallback = next((item for item in registry if str(item.get('pack_id') or '') == candidate_id), {})
                if fallback and list(fallback.get('comparison_policies') or []):
                    break
            if fallback:
                merged = dict(fallback)
                merged.update(saved_match)
                merged['comparison_policies'] = [dict(item or {}) for item in list(fallback.get('comparison_policies') or []) if isinstance(item, dict)]
                merged['scenario_count'] = int(saved_match.get('scenario_count') or fallback.get('scenario_count') or len(list(merged.get('comparison_policies') or [])) or 0)
                return merged
            return saved_match
        registry_match = next((item for item in registry if str(item.get('pack_id') or '') == target_pack_id), {})
        if registry_match:
            if list(registry_match.get('comparison_policies') or []):
                return registry_match
            fallback_ids = [
                str(registry_match.get('promoted_from_pack_id') or ''),
                str(registry_match.get('shared_from_pack_id') or ''),
                target_pack_id,
            ]
            fallback = {}
            for candidate_id in [item for item in fallback_ids if item]:
                fallback = next((item for item in saved if str(item.get('pack_id') or '') == candidate_id), {})
                if fallback:
                    break
                fallback = next((item for item in builtins if str(item.get('pack_id') or '') == candidate_id), {})
                if fallback:
                    break
            if fallback:
                merged = dict(fallback)
                merged.update(registry_match)
                merged['comparison_policies'] = [dict(item or {}) for item in list(fallback.get('comparison_policies') or []) if isinstance(item, dict)]
                merged['scenario_count'] = int(registry_match.get('scenario_count') or fallback.get('scenario_count') or len(list(merged.get('comparison_policies') or [])) or 0)
                return merged
            return registry_match

        return next((item for item in builtins if str(item.get('pack_id') or '') == target_pack_id), {})

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_summary(packs: list[dict[str, Any]] | None) -> dict[str, Any]:
        items = [dict(item or {}) for item in list(packs or []) if isinstance(item, dict)]
        scope_counts: dict[str, int] = {}
        lifecycle_counts: dict[str, int] = {}
        approval_counts: dict[str, int] = {}
        review_counts: dict[str, int] = {}
        release_counts: dict[str, int] = {}
        rollout_counts: dict[str, int] = {}
        version_keys: set[str] = set()
        latest_count = 0
        attested_count = 0
        release_ready_count = 0
        evidence_packaged_count = 0
        signed_bundle_count = 0
        compliance_reported_count = 0
        compliance_drifted_count = 0
        compliance_conformant_count = 0
        analytics_reported_count = 0
        total_replay_count = 0
        total_binding_count = 0
        attention_required_count = 0
        paused_rollout_count = 0
        frozen_rollout_count = 0
        dependency_blocked_count = 0
        conflict_blocked_count = 0
        freeze_active_count = 0
        superseded_count = 0
        emergency_withdrawn_count = 0
        rollback_release_count = 0
        for item in items:
            scope = str(item.get('catalog_scope') or item.get('registry_scope') or 'promotion')
            scope_counts[scope] = scope_counts.get(scope, 0) + 1
            lifecycle = str(item.get('catalog_lifecycle_state') or 'draft')
            lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + 1
            approval_state = LiveCanvasService._baseline_promotion_simulation_custody_catalog_pack_approval_state(item)
            approval_counts[approval_state] = approval_counts.get(approval_state, 0) + 1
            review_state = LiveCanvasService._baseline_promotion_simulation_custody_catalog_pack_review_state(item)
            review_counts[review_state] = review_counts.get(review_state, 0) + 1
            release_state = str(item.get('catalog_release_state') or 'draft')
            release_counts[release_state] = release_counts.get(release_state, 0) + 1
            rollout_state = str(item.get('catalog_rollout_state') or ('not_configured' if not bool(item.get('catalog_rollout_enabled', False)) else 'staged'))
            rollout_counts[rollout_state] = rollout_counts.get(rollout_state, 0) + 1
            paused_rollout_count += 1 if bool(item.get('catalog_rollout_paused', False)) else 0
            frozen_rollout_count += 1 if bool(item.get('catalog_rollout_frozen', False)) else 0
            if int(item.get('catalog_attestation_count') or 0) > 0 or str(((item.get('catalog_latest_attestation') or {}).get('report_id')) or ''):
                attested_count += 1
            if int(item.get('catalog_evidence_package_count') or 0) > 0 or str((((item.get('catalog_latest_evidence_package') or {}).get('report_id')) or ((item.get('catalog_latest_evidence_package') or {}).get('package_id')) or '')):
                evidence_packaged_count += 1
            if int(item.get('catalog_release_bundle_count') or 0) > 0 or str((((item.get('catalog_latest_release_bundle') or {}).get('report_id')) or ((item.get('catalog_latest_release_bundle') or {}).get('release_bundle_id')) or '')):
                signed_bundle_count += 1
            if int(item.get('catalog_compliance_report_count') or 0) > 0 or str((((item.get('catalog_latest_compliance_report') or {}).get('report_id')) or ((item.get('catalog_latest_compliance_report') or {}).get('package_id')) or '')):
                compliance_reported_count += 1
            if int(item.get('catalog_analytics_report_count') or 0) > 0 or str((((item.get('catalog_latest_analytics_report') or {}).get('report_id')) or ((item.get('catalog_latest_analytics_report') or {}).get('package_id')) or '')):
                analytics_reported_count += 1
            total_replay_count += int(item.get('catalog_replay_count') or 0)
            total_binding_count += int(((item.get('catalog_binding_summary') or {}).get('active_binding_count')) or item.get('catalog_binding_count') or 0)
            analytics_summary = dict(item.get('catalog_analytics_summary') or {})
            attention_required_count += 1 if bool(analytics_summary.get('attention_required')) else 0
            compliance_status = str(((item.get('catalog_compliance_summary') or {}).get('overall_status')) or '')
            if compliance_status == 'drifted':
                compliance_drifted_count += 1
            elif compliance_status == 'conformant':
                compliance_conformant_count += 1
            dependency_blocked_count += 1 if bool(((item.get('catalog_dependency_summary') or {}).get('blocking'))) else 0
            conflict_blocked_count += 1 if bool(((item.get('catalog_conflict_summary') or {}).get('blocking'))) else 0
            freeze_active_count += 1 if int(((item.get('catalog_freeze_summary') or {}).get('active_window_count')) or 0) > 0 else 0
            superseded_count += 1 if str(((item.get('catalog_supersedence_summary') or {}).get('state')) or '') == 'superseded' else 0
            emergency_withdrawn_count += 1 if bool(((item.get('catalog_emergency_withdrawal_summary') or {}).get('active'))) else 0
            rollback_release_count += 1 if str(((item.get('catalog_release_rollback_summary') or {}).get('state')) or '') in {'rolled_back_to_previous_release', 'rolled_back_without_restore'} else 0
            if LiveCanvasService._baseline_promotion_simulation_custody_catalog_pack_release_ready(item) and not str(((item.get('catalog_release_guard') or {}).get('reason')) or ''):
                release_ready_count += 1
            version_key = str(item.get('catalog_version_key') or '')
            if version_key:
                version_keys.add(version_key)
            if bool(item.get('catalog_is_latest', False)):
                latest_count += 1
        return {
            'catalog_entry_count': len(items),
            'catalog_scope_counts': scope_counts,
            'catalog_lifecycle_counts': lifecycle_counts,
            'catalog_approval_counts': approval_counts,
            'catalog_review_counts': review_counts,
            'catalog_release_counts': release_counts,
            'catalog_rollout_counts': rollout_counts,
            'workspace_scope_count': int(scope_counts.get('workspace') or 0),
            'environment_scope_count': int(scope_counts.get('environment') or 0),
            'promotion_scope_count': int(scope_counts.get('promotion') or 0),
            'portfolio_family_scope_count': int(scope_counts.get('portfolio_family') or 0),
            'runtime_family_scope_count': int(scope_counts.get('runtime_family') or 0),
            'global_scope_count': int(scope_counts.get('global') or 0),
            'draft_count': int(lifecycle_counts.get('draft') or 0),
            'curated_count': int(lifecycle_counts.get('curated') or 0),
            'approved_count': int(lifecycle_counts.get('approved') or 0),
            'deprecated_count': int(lifecycle_counts.get('deprecated') or 0),
            'approval_pending_count': int(approval_counts.get('pending') or 0),
            'approval_approved_count': int(approval_counts.get('approved') or 0),
            'approval_rejected_count': int(approval_counts.get('rejected') or 0),
            'review_pending_count': int(review_counts.get('pending_review') or 0),
            'review_in_progress_count': int(review_counts.get('in_review') or 0),
            'review_changes_requested_count': int(review_counts.get('review_changes_requested') or 0),
            'review_approved_count': int(review_counts.get('review_approved') or 0),
            'review_rejected_count': int(review_counts.get('review_rejected') or 0),
            'released_count': int(release_counts.get('released') or 0),
            'staged_count': int(release_counts.get('staged') or 0),
            'withdrawn_count': int(release_counts.get('withdrawn') or 0),
            'attested_count': attested_count,
            'evidence_packaged_count': evidence_packaged_count,
            'signed_bundle_count': signed_bundle_count,
            'compliance_reported_count': compliance_reported_count,
            'compliance_drifted_count': compliance_drifted_count,
            'compliance_conformant_count': compliance_conformant_count,
            'analytics_reported_count': analytics_reported_count,
            'total_replay_count': total_replay_count,
            'total_binding_count': total_binding_count,
            'attention_required_count': attention_required_count,
            'release_ready_count': release_ready_count,
            'rollout_active_count': int(rollout_counts.get('rolling_out') or 0),
            'rollout_completed_count': int(rollout_counts.get('completed') or 0),
            'rollout_rolled_back_count': int(rollout_counts.get('rolled_back') or 0),
            'rollout_paused_count': paused_rollout_count,
            'rollout_frozen_count': frozen_rollout_count,
            'dependency_blocked_count': dependency_blocked_count,
            'conflict_blocked_count': conflict_blocked_count,
            'freeze_active_count': freeze_active_count,
            'superseded_count': superseded_count,
            'emergency_withdrawn_count': emergency_withdrawn_count,
            'rollback_release_count': rollback_release_count,
            'versioned_line_count': len(version_keys),
            'latest_entry_count': latest_count,
        }


    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_pack_approval_state(pack: dict[str, Any] | None) -> str:
        payload = dict(pack or {})
        state = str(payload.get('catalog_approval_state') or '').strip().lower()
        required = max(0, int(payload.get('catalog_required_approvals') or 0))
        count = max(0, int(payload.get('catalog_approval_count') or 0))
        if state:
            return state
        if not bool(payload.get('catalog_approval_required', False)) or required <= 0:
            return 'not_required'
        if str(payload.get('catalog_approval_rejected_by') or ''):
            return 'rejected'
        if count >= required:
            return 'approved'
        return 'pending'

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_pack_review_state(pack: dict[str, Any] | None) -> str:
        payload = dict(pack or {})
        state = str(payload.get('catalog_review_state') or '').strip().lower()
        if state:
            return state
        decision = str(payload.get('catalog_review_decision') or '').strip().lower()
        if decision in {'approved', 'review_approved'}:
            return 'review_approved'
        if decision in {'changes_requested', 'review_changes_requested'}:
            return 'review_changes_requested'
        if decision in {'rejected', 'review_rejected'}:
            return 'review_rejected'
        if str(payload.get('catalog_review_claimed_by') or '').strip():
            return 'in_review'
        if str(payload.get('catalog_review_requested_by') or '').strip() or str(payload.get('catalog_review_assigned_reviewer') or '').strip():
            return 'pending_review'
        return 'not_requested'

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_pack_review_ready(pack: dict[str, Any] | None) -> bool:
        state = LiveCanvasService._baseline_promotion_simulation_custody_catalog_pack_review_state(pack)
        return state in {'not_requested', 'review_approved'}

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_pack_review_event(
        *,
        event_type: str,
        state: str,
        actor: str,
        at: float,
        role: str = '',
        note: str = '',
        decision: str = '',
        assigned_reviewer: str = '',
    ) -> dict[str, Any]:
        return {
            'event_id': f'review_{int(at)}_{abs(hash((event_type, actor, state, decision, note))) % 100000}',
            'event_type': str(event_type or '').strip(),
            'state': str(state or '').strip(),
            'actor': str(actor or '').strip(),
            'role': str(role or '').strip(),
            'at': at,
            'note': str(note or '').strip(),
            'decision': str(decision or '').strip(),
            'assigned_reviewer': str(assigned_reviewer or '').strip(),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_pack_release_ready(pack: dict[str, Any] | None) -> bool:
        payload = dict(pack or {})
        lifecycle = str(payload.get('catalog_lifecycle_state') or 'draft').strip().lower()
        approval_state = LiveCanvasService._baseline_promotion_simulation_custody_catalog_pack_approval_state(payload)
        review_state = LiveCanvasService._baseline_promotion_simulation_custody_catalog_pack_review_state(payload)
        if lifecycle != 'approved':
            return False
        if bool(payload.get('catalog_approval_required', False)) and approval_state != 'approved':
            return False
        if review_state not in {'not_requested', 'review_approved'}:
            return False
        return True

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_rollout_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        enabled = bool(payload.get('enabled', False))
        return {
            'enabled': enabled,
            'wave_size': max(1, int(payload.get('wave_size') or 1)),
            'require_manual_advance': bool(payload.get('require_manual_advance', True)),
            'require_evidence_package': bool(payload.get('require_evidence_package', False)),
            'require_signed_bundle': bool(payload.get('require_signed_bundle', False)),
        }


    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_dependency_refs(raw_refs: Any) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int, str, str]] = set()
        for index, raw_item in enumerate(list(raw_refs or []), start=1):
            item = {'catalog_version_key': str(raw_item).strip()} if isinstance(raw_item, str) else dict(raw_item or {})
            entry_id = str(item.get('catalog_entry_id') or item.get('entry_id') or '').strip()
            version_key = str(item.get('catalog_version_key') or item.get('version_key') or '').strip()
            if not entry_id and not version_key:
                continue
            ref = {
                'dependency_id': str(item.get('dependency_id') or f'dependency-{index}').strip() or f'dependency-{index}',
                'catalog_entry_id': entry_id,
                'catalog_version_key': version_key,
                'min_catalog_version': max(0, int(item.get('min_catalog_version') or item.get('min_version') or 0)),
                'required_lifecycle_state': str(item.get('required_lifecycle_state') or item.get('required_state') or 'approved').strip() or 'approved',
                'required_release_state': str(item.get('required_release_state') or 'released').strip() or 'released',
                'reason': str(item.get('reason') or item.get('note') or '').strip(),
            }
            dedupe = (
                ref['catalog_entry_id'],
                ref['catalog_version_key'],
                int(ref['min_catalog_version'] or 0),
                ref['required_lifecycle_state'],
                ref['required_release_state'],
            )
            if dedupe in seen:
                continue
            seen.add(dedupe)
            refs.append(ref)
        return refs[:12]

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_conflict_rules(raw_rules: Any) -> dict[str, Any]:
        payload = {'conflict_version_keys': [str(item).strip() for item in list(raw_rules or []) if str(item).strip()]} if isinstance(raw_rules, list) else dict(raw_rules or {})
        return {
            'conflict_entry_ids': [str(item).strip() for item in list(payload.get('conflict_entry_ids') or payload.get('entry_ids') or []) if str(item).strip()][:16],
            'conflict_version_keys': [str(item).strip() for item in list(payload.get('conflict_version_keys') or payload.get('version_keys') or []) if str(item).strip()][:16],
            'conflict_category_keys': [str(item).strip() for item in list(payload.get('conflict_category_keys') or payload.get('category_keys') or []) if str(item).strip()][:16],
            'conflict_tags': [str(item).strip() for item in list(payload.get('conflict_tags') or payload.get('tags') or []) if str(item).strip()][:16],
            'enforce_same_scope': bool(payload.get('enforce_same_scope', True)),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_freeze_windows(raw_windows: Any) -> list[dict[str, Any]]:
        windows: list[dict[str, Any]] = []
        for index, raw_item in enumerate(list(raw_windows or []), start=1):
            item = dict(raw_item or {})
            start_at = item.get('start_at')
            end_at = item.get('end_at')
            try:
                start_at = float(start_at) if start_at is not None else None
            except Exception:
                start_at = None
            try:
                end_at = float(end_at) if end_at is not None else None
            except Exception:
                end_at = None
            block_actions = [str(v).strip() for v in list(item.get('block_actions') or []) if str(v).strip()]
            windows.append({
                'window_id': str(item.get('window_id') or f'catalog-freeze-{index}').strip() or f'catalog-freeze-{index}',
                'label': str(item.get('label') or item.get('name') or f'catalog-freeze-{index}').strip() or f'catalog-freeze-{index}',
                'start_at': start_at,
                'end_at': end_at,
                'reason': str(item.get('reason') or '').strip(),
                'block_stage': bool(item.get('block_stage', True if not block_actions else 'stage' in block_actions)),
                'block_release': bool(item.get('block_release', True if not block_actions else 'release' in block_actions)),
                'block_advance': bool(item.get('block_advance', True if not block_actions else 'advance' in block_actions)),
            })
        return windows[:12]

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_lifecycle_rank(state: str) -> int:
        return {'deprecated': 0, 'draft': 1, 'curated': 2, 'approved': 3}.get(str(state or '').strip().lower(), 0)

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_release_rank(state: str) -> int:
        return {'withdrawn': 0, 'draft': 1, 'staged': 2, 'rolling_out': 3, 'released': 4}.get(str(state or '').strip().lower(), 0)

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_supersedence_summary(pack: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(pack or {})
        return {
            'state': str(payload.get('catalog_supersedence_state') or ''),
            'superseded_at': payload.get('catalog_superseded_at'),
            'superseded_by': str(payload.get('catalog_superseded_by') or ''),
            'superseded_reason': str(payload.get('catalog_superseded_reason') or ''),
            'superseded_by_entry_id': str(payload.get('catalog_superseded_by_entry_id') or ''),
            'superseded_by_version': int(payload.get('catalog_superseded_by_version') or 0),
            'superseded_by_bundle_id': str(payload.get('catalog_superseded_by_bundle_id') or ''),
            'supersedes_entry_id': str(payload.get('catalog_supersedes_entry_id') or ''),
            'supersedes_version': int(payload.get('catalog_supersedes_version') or 0),
            'restored_from_entry_id': str(payload.get('catalog_restored_from_entry_id') or ''),
            'restored_from_version': int(payload.get('catalog_restored_from_version') or 0),
            'restored_at': payload.get('catalog_restored_at'),
            'restored_by': str(payload.get('catalog_restored_by') or ''),
            'restored_reason': str(payload.get('catalog_restored_reason') or ''),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_release_rollback_summary(pack: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(pack or {})
        return {
            'state': str(payload.get('catalog_rollback_release_state') or ''),
            'rolled_back_at': payload.get('catalog_rollback_release_at'),
            'rolled_back_by': str(payload.get('catalog_rollback_release_by') or ''),
            'reason': str(payload.get('catalog_rollback_release_reason') or ''),
            'target_entry_id': str(payload.get('catalog_rollback_target_entry_id') or ''),
            'target_version': int(payload.get('catalog_rollback_target_version') or 0),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_emergency_withdrawal_summary(pack: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(pack or {})
        return {
            'active': bool(payload.get('catalog_emergency_withdrawal_active', False)),
            'at': payload.get('catalog_emergency_withdrawal_at'),
            'by': str(payload.get('catalog_emergency_withdrawal_by') or ''),
            'reason': str(payload.get('catalog_emergency_withdrawal_reason') or ''),
            'incident_id': str(payload.get('catalog_emergency_withdrawal_incident_id') or ''),
            'severity': str(payload.get('catalog_emergency_withdrawal_severity') or ''),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_previous_restore_candidate(
        pack: dict[str, Any] | None,
        *,
        catalog_packs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        version_key = str(payload.get('catalog_version_key') or '')
        scope_key = str(payload.get('catalog_scope_key') or '')
        current_version = int(payload.get('catalog_version') or 0)
        candidates: list[dict[str, Any]] = []
        for item in list(catalog_packs or []):
            if not isinstance(item, dict):
                continue
            current = dict(item)
            if str(current.get('catalog_version_key') or '') != version_key:
                continue
            if str(current.get('catalog_scope_key') or '') != scope_key:
                continue
            if int(current.get('catalog_version') or 0) >= current_version:
                continue
            lifecycle_state = str(current.get('catalog_lifecycle_state') or '')
            if lifecycle_state not in {'approved', 'deprecated'}:
                continue
            if bool(current.get('catalog_emergency_withdrawal_active', False)):
                continue
            candidates.append(current)
        if not candidates:
            return {}
        candidates.sort(key=lambda item: (int(item.get('catalog_version') or 0), LiveCanvasService._baseline_promotion_simulation_custody_catalog_release_rank(str(item.get('catalog_release_state') or ''))), reverse=True)
        return dict(candidates[0])

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_dependency_cycle_nodes(graph: dict[str, list[str]] | None) -> set[str]:
        adjacency = {str(node): [str(item) for item in list(edges or []) if str(item)] for node, edges in dict(graph or {}).items()}
        cycle_nodes: set[str] = set()
        state: dict[str, int] = {}
        stack: list[str] = []

        def dfs(node: str) -> None:
            visit_state = state.get(node, 0)
            if visit_state == 1:
                if node in stack:
                    cycle_nodes.update(stack[stack.index(node):])
                else:
                    cycle_nodes.add(node)
                return
            if visit_state == 2:
                return
            state[node] = 1
            stack.append(node)
            for child in adjacency.get(node, []):
                dfs(child)
            stack.pop()
            state[node] = 2

        for node in list(adjacency):
            if state.get(node, 0) == 0:
                dfs(node)
        return cycle_nodes

    def _baseline_promotion_simulation_custody_catalog_dependency_summary(
        self,
        pack: dict[str, Any] | None,
        *,
        catalog_packs: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        refs = self._baseline_promotion_simulation_custody_catalog_dependency_refs(payload.get('catalog_dependency_refs') or [])
        items = [dict(item or {}) for item in list(catalog_packs or []) if isinstance(item, dict)]
        entry_index = {str(item.get('catalog_entry_id') or item.get('registry_entry_id') or ''): dict(item) for item in items if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '')}
        version_index: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            version_key = str(item.get('catalog_version_key') or '')
            if version_key:
                version_index.setdefault(version_key, []).append(dict(item))
        for values in version_index.values():
            values.sort(key=lambda value: int(value.get('catalog_version') or 0), reverse=True)
        resolved_refs = []
        missing_count = 0
        unsatisfied_count = 0
        graph: dict[str, list[str]] = {}
        for item in items:
            source_id = str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '')
            refs_for_item = self._baseline_promotion_simulation_custody_catalog_dependency_refs(item.get('catalog_dependency_refs') or [])
            edges: list[str] = []
            for ref in refs_for_item:
                candidate = {}
                if str(ref.get('catalog_entry_id') or ''):
                    candidate = dict(entry_index.get(str(ref.get('catalog_entry_id') or '')) or {})
                elif str(ref.get('catalog_version_key') or ''):
                    versions = [dict(v) for v in version_index.get(str(ref.get('catalog_version_key') or ''), [])]
                    minimum = int(ref.get('min_catalog_version') or 0)
                    candidate = next((dict(v) for v in versions if int(v.get('catalog_version') or 0) >= minimum), dict(versions[0]) if versions else {})
                target_id = str(candidate.get('catalog_entry_id') or candidate.get('registry_entry_id') or '')
                if target_id:
                    edges.append(target_id)
            if source_id:
                graph[source_id] = edges
        cycle_nodes = self._baseline_promotion_simulation_custody_catalog_dependency_cycle_nodes(graph)
        current_entry_id = str(payload.get('catalog_entry_id') or payload.get('registry_entry_id') or '')
        for ref in refs:
            resolved = {}
            if str(ref.get('catalog_entry_id') or ''):
                resolved = dict(entry_index.get(str(ref.get('catalog_entry_id') or '')) or {})
            elif str(ref.get('catalog_version_key') or ''):
                versions = [dict(v) for v in version_index.get(str(ref.get('catalog_version_key') or ''), [])]
                minimum = int(ref.get('min_catalog_version') or 0)
                resolved = next((dict(v) for v in versions if int(v.get('catalog_version') or 0) >= minimum), {})
            satisfied = bool(resolved)
            if not resolved:
                missing_count += 1
            else:
                lifecycle_ok = self._baseline_promotion_simulation_custody_catalog_lifecycle_rank(str(resolved.get('catalog_lifecycle_state') or 'draft')) >= self._baseline_promotion_simulation_custody_catalog_lifecycle_rank(str(ref.get('required_lifecycle_state') or 'approved'))
                release_ok = self._baseline_promotion_simulation_custody_catalog_release_rank(str(resolved.get('catalog_release_state') or 'draft')) >= self._baseline_promotion_simulation_custody_catalog_release_rank(str(ref.get('required_release_state') or 'released'))
                satisfied = lifecycle_ok and release_ok
                if not satisfied:
                    unsatisfied_count += 1
            resolved_refs.append({
                'dependency_id': str(ref.get('dependency_id') or ''),
                'catalog_entry_id': str(ref.get('catalog_entry_id') or ''),
                'catalog_version_key': str(ref.get('catalog_version_key') or ''),
                'min_catalog_version': int(ref.get('min_catalog_version') or 0),
                'required_lifecycle_state': str(ref.get('required_lifecycle_state') or ''),
                'required_release_state': str(ref.get('required_release_state') or ''),
                'reason': str(ref.get('reason') or ''),
                'resolved_catalog_entry_id': str(resolved.get('catalog_entry_id') or resolved.get('registry_entry_id') or ''),
                'resolved_catalog_version': int(resolved.get('catalog_version') or 0),
                'resolved_lifecycle_state': str(resolved.get('catalog_lifecycle_state') or ''),
                'resolved_release_state': str(resolved.get('catalog_release_state') or ''),
                'satisfied': bool(satisfied),
            })
        cycle_detected = bool(current_entry_id and current_entry_id in cycle_nodes)
        return {
            'dependency_count': len(refs),
            'missing_count': missing_count,
            'unsatisfied_count': unsatisfied_count,
            'cycle_detected': cycle_detected,
            'blocking': bool(missing_count or unsatisfied_count or cycle_detected),
            'items': resolved_refs[:8],
        }

    def _baseline_promotion_simulation_custody_catalog_conflict_summary(
        self,
        pack: dict[str, Any] | None,
        *,
        catalog_packs: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        rules = self._baseline_promotion_simulation_custody_catalog_conflict_rules(payload.get('catalog_conflict_rules') or {})
        if not any(bool(rules.get(key)) for key in ('conflict_entry_ids', 'conflict_version_keys', 'conflict_category_keys', 'conflict_tags')):
            return {'blocking': False, 'active_conflict_count': 0, 'rule_count': 0, 'items': []}
        current_entry_id = str(payload.get('catalog_entry_id') or payload.get('registry_entry_id') or '')
        current_scope_key = str(payload.get('catalog_scope_key') or '')
        conflicts = []
        for item in list(catalog_packs or []):
            other = dict(item or {})
            other_entry_id = str(other.get('catalog_entry_id') or other.get('registry_entry_id') or '')
            if not other_entry_id or other_entry_id == current_entry_id:
                continue
            if self._baseline_promotion_simulation_custody_catalog_release_rank(str(other.get('catalog_release_state') or 'draft')) < self._baseline_promotion_simulation_custody_catalog_release_rank('staged'):
                continue
            if self._baseline_promotion_simulation_custody_catalog_lifecycle_rank(str(other.get('catalog_lifecycle_state') or 'draft')) < self._baseline_promotion_simulation_custody_catalog_lifecycle_rank('approved'):
                continue
            if bool(rules.get('enforce_same_scope', True)) and current_scope_key and str(other.get('catalog_scope_key') or '') != current_scope_key:
                continue
            conflict_types = []
            if other_entry_id in set(rules.get('conflict_entry_ids') or []):
                conflict_types.append('catalog_entry_id')
            if str(other.get('catalog_version_key') or '') in set(rules.get('conflict_version_keys') or []):
                conflict_types.append('catalog_version_key')
            if set(str(v) for v in list(other.get('category_keys') or []) if str(v)) & set(rules.get('conflict_category_keys') or []):
                conflict_types.append('category_key')
            if set(str(v) for v in list(other.get('tags') or []) if str(v)) & set(rules.get('conflict_tags') or []):
                conflict_types.append('tag')
            if conflict_types:
                conflicts.append({
                    'catalog_entry_id': other_entry_id,
                    'catalog_version_key': str(other.get('catalog_version_key') or ''),
                    'catalog_version': int(other.get('catalog_version') or 0),
                    'catalog_release_state': str(other.get('catalog_release_state') or ''),
                    'catalog_lifecycle_state': str(other.get('catalog_lifecycle_state') or ''),
                    'conflict_types': conflict_types,
                })
        return {
            'blocking': bool(conflicts),
            'active_conflict_count': len(conflicts),
            'rule_count': sum(len(list(rules.get(key) or [])) for key in ('conflict_entry_ids', 'conflict_version_keys', 'conflict_category_keys', 'conflict_tags')),
            'items': conflicts[:8],
        }

    def _baseline_promotion_simulation_custody_catalog_freeze_summary(
        self,
        pack: dict[str, Any] | None,
        *,
        action: str,
        at: float | None = None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        now = float(at or time.time())
        windows = self._baseline_promotion_simulation_custody_catalog_freeze_windows(payload.get('catalog_freeze_windows') or [])
        action_key = {'stage': 'block_stage', 'release': 'block_release', 'advance': 'block_advance'}.get(str(action or ''), 'block_release')
        active = []
        for window in windows:
            start_at = window.get('start_at')
            end_at = window.get('end_at')
            start_ok = start_at is None or float(start_at) <= now
            end_ok = end_at is None or now < float(end_at)
            is_active = bool(start_ok and end_ok)
            if not is_active:
                continue
            active.append({
                'window_id': str(window.get('window_id') or ''),
                'label': str(window.get('label') or ''),
                'start_at': start_at,
                'end_at': end_at,
                'reason': str(window.get('reason') or ''),
                'blocks_action': bool(window.get(action_key, False)),
            })
        blocking = [item for item in active if bool(item.get('blocks_action'))]
        return {
            'window_count': len(windows),
            'active_window_count': len(active),
            'blocking_window_count': len(blocking),
            'blocking': bool(blocking),
            'action': str(action or ''),
            'items': active[:8],
        }

    def _baseline_promotion_simulation_custody_catalog_release_guard(
        self,
        pack: dict[str, Any] | None,
        *,
        catalog_packs: list[dict[str, Any]] | None,
        action: str,
        at: float | None = None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        dependency_summary = self._baseline_promotion_simulation_custody_catalog_dependency_summary(payload, catalog_packs=catalog_packs)
        conflict_summary = self._baseline_promotion_simulation_custody_catalog_conflict_summary(payload, catalog_packs=catalog_packs)
        freeze_summary = self._baseline_promotion_simulation_custody_catalog_freeze_summary(payload, action=action, at=at)
        reason = ''
        if bool(dependency_summary.get('blocking')):
            reason = 'catalog_dependency_unsatisfied'
        elif bool(conflict_summary.get('blocking')):
            reason = 'catalog_conflict_detected'
        elif bool(freeze_summary.get('blocking')):
            reason = 'catalog_freeze_window_active'
        return {
            'passed': not bool(reason),
            'reason': reason,
            'action': str(action or ''),
            'checked_at': float(at or time.time()),
            'dependency_summary': dependency_summary,
            'conflict_summary': conflict_summary,
            'freeze_summary': freeze_summary,
        }

    def _baseline_promotion_simulation_custody_catalog_enrich_packs(self, packs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        normalized = [dict(item or {}) for item in list(packs or []) if isinstance(item, dict)]
        enriched: list[dict[str, Any]] = []
        for item in normalized:
            current = dict(item)
            current['catalog_dependency_refs'] = self._baseline_promotion_simulation_custody_catalog_dependency_refs(current.get('catalog_dependency_refs') or [])
            current['catalog_conflict_rules'] = self._baseline_promotion_simulation_custody_catalog_conflict_rules(current.get('catalog_conflict_rules') or {})
            current['catalog_freeze_windows'] = self._baseline_promotion_simulation_custody_catalog_freeze_windows(current.get('catalog_freeze_windows') or [])
            current['catalog_dependency_summary'] = self._baseline_promotion_simulation_custody_catalog_dependency_summary(current, catalog_packs=normalized)
            current['catalog_conflict_summary'] = self._baseline_promotion_simulation_custody_catalog_conflict_summary(current, catalog_packs=normalized)
            current['catalog_freeze_summary'] = self._baseline_promotion_simulation_custody_catalog_freeze_summary(current, action='release')
            current['catalog_release_guard'] = self._baseline_promotion_simulation_custody_catalog_release_guard(current, catalog_packs=normalized, action='release')
            enriched.append(current)
        return enriched

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_rollout_target_key(payload: dict[str, Any] | None) -> str:
        item = dict(payload or {})
        promotion_id = str(item.get('promotion_id') or '').strip()
        workspace_id = str(item.get('workspace_id') or '').strip()
        environment = str(item.get('environment') or '').strip()
        if promotion_id:
            return '|'.join([promotion_id, workspace_id, environment])
        return ''

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_rollout_summary(pack: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(pack or {})
        policy = LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_policy(payload.get('catalog_rollout_policy') or {})
        targets = [dict(item or {}) for item in list(payload.get('catalog_rollout_targets') or []) if isinstance(item, dict)]
        waves = [dict(item or {}) for item in list(payload.get('catalog_rollout_waves') or []) if isinstance(item, dict)]
        released_targets = [item for item in targets if bool(item.get('released'))]
        return {
            'enabled': bool(payload.get('catalog_rollout_enabled', policy.get('enabled', False))),
            'train_id': str(payload.get('catalog_rollout_train_id') or ''),
            'state': str(payload.get('catalog_rollout_state') or ('not_configured' if not policy.get('enabled') else 'staged')),
            'wave_size': int(policy.get('wave_size') or 1),
            'require_manual_advance': bool(policy.get('require_manual_advance', True)),
            'require_evidence_package': bool(policy.get('require_evidence_package', False)),
            'require_signed_bundle': bool(policy.get('require_signed_bundle', False)),
            'wave_count': len(waves),
            'released_wave_count': len([item for item in waves if str(item.get('status') or '') in {'released', 'completed'}]),
            'completed_wave_count': int(payload.get('catalog_rollout_completed_wave_count') or 0),
            'current_wave_index': int(payload.get('catalog_rollout_current_wave_index') or 0),
            'target_count': len(targets),
            'released_target_count': len(released_targets),
            'paused': bool(payload.get('catalog_rollout_paused', False)),
            'frozen': bool(payload.get('catalog_rollout_frozen', False)),
            'started_at': payload.get('catalog_rollout_started_at'),
            'completed_at': payload.get('catalog_rollout_completed_at'),
            'rolled_back_at': payload.get('catalog_rollout_rolled_back_at'),
            'last_transition_at': payload.get('catalog_rollout_last_transition_at'),
            'last_transition_by': str(payload.get('catalog_rollout_last_transition_by') or ''),
            'last_transition_action': str(payload.get('catalog_rollout_last_transition_action') or ''),
            'current_wave': next((dict(item) for item in waves if int(item.get('wave_index') or 0) == int(payload.get('catalog_rollout_current_wave_index') or 0)), {}),
            'latest_gate': dict((payload.get('catalog_rollout_latest_gate') or {}) or {}),
        }

    def _baseline_promotion_simulation_custody_catalog_rollout_gate(self, pack: dict[str, Any] | None, *, wave_index: int | None = None, catalog_packs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload = dict(pack or {})
        policy = LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_policy(payload.get('catalog_rollout_policy') or {})
        state = str(payload.get('catalog_rollout_state') or '')
        checked_at = time.time()
        base = {
            'wave_index': int(wave_index or payload.get('catalog_rollout_current_wave_index') or 0),
            'checked_at': checked_at,
            'require_evidence_package': bool(policy.get('require_evidence_package', False)),
            'require_signed_bundle': bool(policy.get('require_signed_bundle', False)),
        }
        if not bool(payload.get('catalog_rollout_enabled', policy.get('enabled', False))):
            return {'passed': True, 'reason': '', **base}
        if bool(payload.get('catalog_rollout_frozen', False)):
            return {'passed': False, 'reason': 'catalog_rollout_frozen', **base}
        if state == 'paused' or bool(payload.get('catalog_rollout_paused', False)):
            return {'passed': False, 'reason': 'catalog_rollout_paused', **base}
        if bool(policy.get('require_evidence_package')) and not str((((payload.get('catalog_latest_evidence_package') or {}).get('report_id')) or ((payload.get('catalog_latest_evidence_package') or {}).get('package_id')) or '')):
            return {'passed': False, 'reason': 'catalog_rollout_requires_evidence_package', **base}
        if bool(policy.get('require_signed_bundle')) and not str((((payload.get('catalog_latest_release_bundle') or {}).get('report_id')) or ((payload.get('catalog_latest_release_bundle') or {}).get('release_bundle_id')) or '')):
            return {'passed': False, 'reason': 'catalog_rollout_requires_signed_bundle', **base}
        guard = self._baseline_promotion_simulation_custody_catalog_release_guard(payload, catalog_packs=catalog_packs, action='advance', at=checked_at)
        if not bool(guard.get('passed')):
            return {'passed': False, 'reason': str(guard.get('reason') or ''), 'dependency_summary': dict(guard.get('dependency_summary') or {}), 'conflict_summary': dict(guard.get('conflict_summary') or {}), 'freeze_summary': dict(guard.get('freeze_summary') or {}), **base}
        return {'passed': True, 'reason': '', 'dependency_summary': dict(guard.get('dependency_summary') or {}), 'conflict_summary': dict(guard.get('conflict_summary') or {}), 'freeze_summary': dict(guard.get('freeze_summary') or {}), **base}

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_rollout_access(pack: dict[str, Any] | None, *, current_context: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(pack or {})
        summary = LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_summary(payload)
        if not bool(summary.get('enabled')):
            return {'allowed': True, 'reason': ''}
        if str(payload.get('catalog_release_state') or '') == 'withdrawn' or str(summary.get('state') or '') == 'rolled_back':
            return {'allowed': False, 'reason': 'catalog_rollout_withdrawn'}
        target_key = LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_target_key(current_context or {})
        if not target_key:
            return {'allowed': False, 'reason': 'catalog_rollout_target_missing'}
        targets = [dict(item or {}) for item in list(payload.get('catalog_rollout_targets') or []) if isinstance(item, dict)]
        if not targets:
            return {'allowed': True, 'reason': ''}
        target = next((item for item in targets if str(item.get('target_key') or '') == target_key), {})
        if not target:
            return {'allowed': False, 'reason': 'catalog_rollout_target_not_planned'}
        if bool(target.get('released', False)):
            return {'allowed': True, 'reason': ''}
        return {'allowed': False, 'reason': 'catalog_rollout_target_not_released'}

    def _baseline_promotion_simulation_custody_catalog_rollout_targets(
        self,
        gw: AdminGatewayLike,
        *,
        pack: dict[str, Any] | None,
        current_context: dict[str, str] | None,
    ) -> list[dict[str, Any]]:
        payload = dict(pack or {})
        context = dict(current_context or {})
        owner_canvas_id = str(payload.get('catalog_owner_canvas_id') or '')
        owner_node_id = str(payload.get('catalog_owner_node_id') or '')
        documents = self._safe_call(
            gw.audit,
            'list_canvas_documents',
            [],
            limit=200,
            tenant_id=context.get('tenant_id') or None,
            workspace_id=None,
            environment=None,
        )
        existing_targets = {
            str(item.get('target_key') or ''): dict(item or {})
            for item in list(payload.get('catalog_rollout_targets') or [])
            if isinstance(item, dict) and str((item or {}).get('target_key') or '')
        }
        targets: list[dict[str, Any]] = []
        seen: set[str] = set()
        ordered_documents = [
            (position, dict(item or {}))
            for position, item in enumerate(list(documents or []), start=1)
            if isinstance(item, dict)
        ]
        ordered_documents.sort(
            key=lambda pair: (
                0 if str((pair[1] or {}).get('canvas_id') or '') == owner_canvas_id else 1,
                float((pair[1] or {}).get('created_at') or 0.0),
                int(pair[0]),
            ),
        )
        for _, document in ordered_documents:
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
            ordered_nodes = [
                (position, dict(item or {}))
                for position, item in enumerate(list(nodes or []), start=1)
                if isinstance(item, dict)
            ]
            ordered_nodes.sort(
                key=lambda pair: (
                    0 if str((pair[1] or {}).get('node_id') or '') == owner_node_id else 1,
                    float((pair[1] or {}).get('created_at') or 0.0),
                    int(pair[0]),
                ),
            )
            for _, node in ordered_nodes:
                if str((node or {}).get('node_type') or '').strip().lower() not in {'baseline_promotion', 'policy_baseline_promotion'}:
                    continue
                node_data = dict((node or {}).get('data') or {})
                promotion_context = {
                    'promotion_id': str(node_data.get('promotion_id') or ''),
                    'tenant_id': str((document or {}).get('tenant_id') or context.get('tenant_id') or ''),
                    'workspace_id': str((document or {}).get('workspace_id') or ''),
                    'environment': str((document or {}).get('environment') or ''),
                    'portfolio_family_id': str(node_data.get('portfolio_family_id') or ''),
                    'runtime_family_id': str(node_data.get('runtime_family_id') or ''),
                    'canvas_id': canvas_id,
                    'node_id': str((node or {}).get('node_id') or ''),
                    'node_label': str((node or {}).get('label') or ''),
                }
                if not self._baseline_promotion_simulation_custody_catalog_pack_visible(payload, context=promotion_context):
                    continue
                target_key = self._baseline_promotion_simulation_custody_catalog_rollout_target_key(promotion_context)
                if not target_key or target_key in seen:
                    continue
                seen.add(target_key)
                existing = dict(existing_targets.get(target_key) or {})
                targets.append({
                    'target_key': target_key,
                    'promotion_id': promotion_context['promotion_id'],
                    'workspace_id': promotion_context['workspace_id'],
                    'environment': promotion_context['environment'],
                    'released': bool(existing.get('released', False)),
                    'released_wave_index': int(existing.get('released_wave_index') or 0),
                    'released_at': existing.get('released_at'),
                    'released_by': str(existing.get('released_by') or ''),
                })
        owner_promotion_id = str(payload.get('promotion_id') or '')
        targets.sort(key=lambda item: 0 if str(item.get('promotion_id') or '') == owner_promotion_id else 1)
        return targets

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_rollout_waves(
        targets: list[dict[str, Any]] | None,
        *,
        wave_size: int,
        existing_waves: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        items = [dict(item or {}) for item in list(targets or []) if isinstance(item, dict)]
        prior = {int(item.get('wave_index') or 0): dict(item or {}) for item in list(existing_waves or []) if isinstance(item, dict)}
        waves: list[dict[str, Any]] = []
        step = max(1, int(wave_size or 1))
        for offset in range(0, len(items), step):
            wave_index = len(waves) + 1
            target_keys = [str(item.get('target_key') or '') for item in items[offset:offset + step] if str(item.get('target_key') or '')]
            previous = dict(prior.get(wave_index) or {})
            waves.append({
                'wave_index': wave_index,
                'target_keys': target_keys,
                'status': str(previous.get('status') or 'planned'),
                'released_target_count': len([item for item in items[offset:offset + step] if bool(item.get('released'))]),
                'released_at': previous.get('released_at'),
                'released_by': str(previous.get('released_by') or ''),
                'gate_evaluation': dict(previous.get('gate_evaluation') or {}),
            })
        return waves

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_rollout_activate_wave(
        pack: dict[str, Any] | None,
        *,
        wave_index: int,
        actor: str,
        at: float,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        targets = [dict(item or {}) for item in list(payload.get('catalog_rollout_targets') or []) if isinstance(item, dict)]
        waves = [dict(item or {}) for item in list(payload.get('catalog_rollout_waves') or []) if isinstance(item, dict)]
        target_keys = set()
        for wave in waves:
            if int(wave.get('wave_index') or 0) == int(wave_index or 0):
                wave['status'] = 'released'
                wave['released_at'] = at
                wave['released_by'] = str(actor or 'operator')
                target_keys = {str(item) for item in list(wave.get('target_keys') or []) if str(item)}
                break
        for target in targets:
            if str(target.get('target_key') or '') in target_keys:
                target['released'] = True
                target['released_wave_index'] = int(wave_index or 0)
                target['released_at'] = at
                target['released_by'] = str(actor or 'operator')
        payload['catalog_rollout_targets'] = targets
        payload['catalog_rollout_waves'] = waves
        payload['catalog_rollout_current_wave_index'] = int(wave_index or 0)
        payload['catalog_rollout_completed_wave_count'] = len([item for item in waves if str(item.get('status') or '') == 'completed'])
        return payload

    def _baseline_promotion_simulation_custody_catalog_refresh_rollout_state(
        self,
        gw: AdminGatewayLike,
        *,
        pack: dict[str, Any] | None,
        current_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        policy = LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_policy(payload.get('catalog_rollout_policy') or {})
        if not bool(payload.get('catalog_rollout_enabled', policy.get('enabled', False))):
            return payload
        targets = self._baseline_promotion_simulation_custody_catalog_rollout_targets(gw, pack=payload, current_context={str(key): str(value) for key, value in dict(current_context or {}).items()})
        waves = self._baseline_promotion_simulation_custody_catalog_rollout_waves(
            targets,
            wave_size=int(policy.get('wave_size') or 1),
            existing_waves=payload.get('catalog_rollout_waves') or [],
        )
        state = str(payload.get('catalog_rollout_state') or '')
        actor = str(
            payload.get('catalog_rollout_last_transition_by')
            or payload.get('catalog_released_by')
            or payload.get('catalog_release_staged_by')
            or payload.get('catalog_promoted_by')
            or payload.get('created_by')
            or 'operator'
        )
        at = (
            payload.get('catalog_rollout_last_transition_at')
            or payload.get('catalog_released_at')
            or payload.get('catalog_release_staged_at')
            or payload.get('catalog_promoted_at')
            or payload.get('created_at')
            or time.time()
        )
        current_wave_index = max(0, min(int(payload.get('catalog_rollout_current_wave_index') or 0), len(waves)))
        released_target_keys: dict[str, int] = {}
        completed_wave_count = 0
        for wave in waves:
            wave_idx = int(wave.get('wave_index') or 0)
            target_keys = [str(item) for item in list(wave.get('target_keys') or []) if str(item)]
            if current_wave_index and wave_idx < current_wave_index:
                wave['status'] = 'completed'
                wave['released_at'] = at
                wave['released_by'] = actor
                completed_wave_count += 1
                for key in target_keys:
                    released_target_keys[key] = wave_idx
            elif current_wave_index and wave_idx == current_wave_index:
                if state == 'completed':
                    wave['status'] = 'completed'
                    completed_wave_count += 1
                elif state in {'rolling_out', 'paused'}:
                    wave['status'] = 'released'
                elif state == 'rolled_back':
                    wave['status'] = 'planned'
                else:
                    wave['status'] = str(wave.get('status') or 'released')
                if str(wave.get('status') or '') in {'released', 'completed'}:
                    wave['released_at'] = wave.get('released_at') or at
                    wave['released_by'] = str(wave.get('released_by') or actor)
                    for key in target_keys:
                        released_target_keys[key] = wave_idx
            else:
                wave['status'] = 'planned' if state != 'completed' else str(wave.get('status') or 'planned')
        for target in targets:
            target_key = str(target.get('target_key') or '')
            if target_key in released_target_keys:
                target['released'] = True
                target['released_wave_index'] = int(released_target_keys[target_key] or 0)
                target['released_at'] = target.get('released_at') or at
                target['released_by'] = str(target.get('released_by') or actor)
            else:
                target['released'] = False
                target['released_wave_index'] = 0
                target['released_at'] = None
                target['released_by'] = ''
        payload['catalog_rollout_targets'] = targets
        payload['catalog_rollout_waves'] = waves
        payload['catalog_rollout_completed_wave_count'] = completed_wave_count
        payload['catalog_rollout_current_wave_index'] = current_wave_index
        return payload

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_pack_policy_delta_summary(pack: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(pack or {})
        scenarios = [dict(item or {}) for item in list(payload.get('comparison_policies') or payload.get('scenarios') or []) if isinstance(item, dict)]
        delta_keys: set[str] = set()
        compact_scenarios = []
        for item in scenarios[:8]:
            keys = [str(key) for key in list(item.get('policy_delta_keys') or []) if str(key)][:16]
            delta_keys.update(keys)
            compact_scenarios.append({
                'scenario_id': str(item.get('scenario_id') or ''),
                'scenario_label': str(item.get('scenario_label') or item.get('label') or ''),
                'policy_delta_keys': keys,
            })
        return {
            'scenario_count': len(scenarios),
            'policy_delta_key_count': len(delta_keys),
            'policy_delta_keys': sorted(delta_keys)[:24],
            'scenarios': compact_scenarios,
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_pack_lineage(
        pack: dict[str, Any] | None,
        *,
        catalog_packs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        items = [dict(item or {}) for item in list(catalog_packs or []) if isinstance(item, dict)]
        version_key = str(payload.get('catalog_version_key') or '')
        current_version = int(payload.get('catalog_version') or 0)
        related = [item for item in items if str(item.get('catalog_version_key') or '') == version_key]
        previous = next((item for item in sorted(related, key=lambda x: int(x.get('catalog_version') or 0), reverse=True) if int(item.get('catalog_version') or 0) < current_version), {})
        replaced_by_version = int(payload.get('catalog_replaced_by_version') or 0)
        replaced_by = next((item for item in related if int(item.get('catalog_version') or 0) == replaced_by_version), {}) if replaced_by_version > 0 else {}
        return {
            'catalog_version_key': version_key,
            'catalog_version': current_version,
            'catalog_scope': str(payload.get('catalog_scope') or ''),
            'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
            'catalog_lifecycle_state': str(payload.get('catalog_lifecycle_state') or 'draft'),
            'catalog_release_state': str(payload.get('catalog_release_state') or 'draft'),
            'catalog_is_latest': bool(payload.get('catalog_is_latest', False)),
            'supersedence': LiveCanvasService._baseline_promotion_simulation_custody_catalog_supersedence_summary(payload),
            'release_rollback': LiveCanvasService._baseline_promotion_simulation_custody_catalog_release_rollback_summary(payload),
            'emergency_withdrawal': LiveCanvasService._baseline_promotion_simulation_custody_catalog_emergency_withdrawal_summary(payload),
            'previous_version': {
                'catalog_entry_id': str(previous.get('catalog_entry_id') or ''),
                'catalog_version': int(previous.get('catalog_version') or 0),
                'catalog_lifecycle_state': str(previous.get('catalog_lifecycle_state') or ''),
                'catalog_release_state': str(previous.get('catalog_release_state') or ''),
            } if previous else None,
            'replaced_by': {
                'catalog_entry_id': str(replaced_by.get('catalog_entry_id') or ''),
                'catalog_version': int(replaced_by.get('catalog_version') or 0),
                'catalog_lifecycle_state': str(replaced_by.get('catalog_lifecycle_state') or ''),
                'catalog_release_state': str(replaced_by.get('catalog_release_state') or ''),
            } if replaced_by else None,
        }

    def _build_baseline_promotion_simulation_custody_catalog_pack_attestation_export(
        self,
        *,
        pack: dict[str, Any] | None,
        actor: str,
        promotion_detail: dict[str, Any] | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        catalog_packs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        promotion = dict(((promotion_detail or {}).get('baseline_promotion')) or {})
        generated_at = time.time()
        approval_state = self._baseline_promotion_simulation_custody_catalog_pack_approval_state(payload)
        review_state = self._baseline_promotion_simulation_custody_catalog_pack_review_state(payload)
        scope = {
            'tenant_id': str(tenant_id or ''),
            'workspace_id': str(workspace_id or payload.get('workspace_id') or ''),
            'environment': str(environment or payload.get('environment') or ''),
            'promotion_id': str(payload.get('promotion_id') or promotion.get('promotion_id') or ''),
            'catalog_scope': str(payload.get('catalog_scope') or payload.get('registry_scope') or ''),
            'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
            'catalog_entry_id': str(payload.get('catalog_entry_id') or payload.get('registry_entry_id') or ''),
        }
        compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(payload)
        review_timeline = [dict(item or {}) for item in list(payload.get('catalog_review_events') or payload.get('catalog_review_timeline') or []) if isinstance(item, dict)]
        report_type = 'openmiura_routing_policy_pack_catalog_attestation_v1'
        report_id = str(self.openclaw_recovery_scheduler_service._stable_digest({
            'report_type': report_type,
            'catalog_entry_id': scope.get('catalog_entry_id'),
            'catalog_version_key': str(payload.get('catalog_version_key') or ''),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'generated_by': str(actor or 'system'),
            'approval_state': approval_state,
            'review_state': review_state,
            'release_state': str(payload.get('catalog_release_state') or 'draft'),
        })[:24])
        report = {
            'report_id': report_id,
            'report_type': report_type,
            'generated_at': generated_at,
            'generated_by': str(actor or 'system'),
            'scope': scope,
            'policy_pack': compact_pack,
            'approval': {
                'required': bool(payload.get('catalog_approval_required', False)),
                'required_approvals': int(payload.get('catalog_required_approvals') or 0),
                'approval_count': int(payload.get('catalog_approval_count') or 0),
                'approval_state': approval_state,
                'requested_at': payload.get('catalog_approval_requested_at'),
                'requested_by': str(payload.get('catalog_approval_requested_by') or ''),
                'rejected_at': payload.get('catalog_approval_rejected_at'),
                'rejected_by': str(payload.get('catalog_approval_rejected_by') or ''),
                'approvals': [
                    {
                        'approval_id': str(item.get('approval_id') or ''),
                        'decision': str(item.get('decision') or ''),
                        'actor': str(item.get('actor') or ''),
                        'role': str(item.get('role') or ''),
                        'at': item.get('at'),
                        'note': str(item.get('note') or ''),
                    }
                    for item in list(payload.get('catalog_approvals') or [])
                    if isinstance(item, dict)
                ],
            },
            'review': {
                'review_state': review_state,
                'assigned_reviewer': str(payload.get('catalog_review_assigned_reviewer') or ''),
                'assigned_role': str(payload.get('catalog_review_assigned_role') or ''),
                'claimed_by': str(payload.get('catalog_review_claimed_by') or ''),
                'claimed_at': payload.get('catalog_review_claimed_at'),
                'requested_at': payload.get('catalog_review_requested_at'),
                'requested_by': str(payload.get('catalog_review_requested_by') or ''),
                'decision': str(payload.get('catalog_review_decision') or ''),
                'decision_at': payload.get('catalog_review_decision_at'),
                'decision_by': str(payload.get('catalog_review_decision_by') or ''),
                'note_count': int(payload.get('catalog_review_note_count') or len(review_timeline) or 0),
                'timeline': [
                    {
                        'event_id': str(item.get('event_id') or ''),
                        'event_type': str(item.get('event_type') or ''),
                        'state': str(item.get('state') or ''),
                        'actor': str(item.get('actor') or ''),
                        'role': str(item.get('role') or ''),
                        'at': item.get('at'),
                        'note': str(item.get('note') or ''),
                        'decision': str(item.get('decision') or ''),
                    }
                    for item in review_timeline[:10]
                ],
            },
            'release': {
                'release_ready': self._baseline_promotion_simulation_custody_catalog_pack_release_ready(payload),
                'release_state': str(payload.get('catalog_release_state') or 'draft'),
                'release_train_id': str(payload.get('catalog_release_train_id') or ''),
                'release_notes': str(payload.get('catalog_release_notes') or ''),
                'staged_at': payload.get('catalog_release_staged_at'),
                'staged_by': str(payload.get('catalog_release_staged_by') or ''),
                'released_at': payload.get('catalog_released_at'),
                'released_by': str(payload.get('catalog_released_by') or ''),
                'withdrawn_at': payload.get('catalog_withdrawn_at'),
                'withdrawn_by': str(payload.get('catalog_withdrawn_by') or ''),
                'withdrawn_reason': str(payload.get('catalog_withdrawn_reason') or ''),
                'supersedence': self._baseline_promotion_simulation_custody_catalog_supersedence_summary(payload),
                'release_rollback': self._baseline_promotion_simulation_custody_catalog_release_rollback_summary(payload),
                'emergency_withdrawal': self._baseline_promotion_simulation_custody_catalog_emergency_withdrawal_summary(payload),
                'rollout': self._baseline_promotion_simulation_custody_catalog_rollout_summary(payload),
            },
            'catalog_lineage': self._baseline_promotion_simulation_custody_catalog_pack_lineage(payload, catalog_packs=catalog_packs),
            'owner': {
                'canvas_id': str(payload.get('catalog_owner_canvas_id') or ''),
                'node_id': str(payload.get('catalog_owner_node_id') or ''),
                'node_label': str(payload.get('catalog_owner_node_label') or ''),
            },
        }
        report['integrity_manifest'] = {
            'manifest_type': 'openmiura_routing_policy_pack_catalog_attestation_manifest_v1',
            'generated_at': generated_at,
            'section_digests': {
                'policy_pack': self.openclaw_recovery_scheduler_service._stable_digest(report.get('policy_pack') or {}),
                'approval': self.openclaw_recovery_scheduler_service._stable_digest(report.get('approval') or {}),
                'review': self.openclaw_recovery_scheduler_service._stable_digest(report.get('review') or {}),
                'release': self.openclaw_recovery_scheduler_service._stable_digest(report.get('release') or {}),
                'catalog_lineage': self.openclaw_recovery_scheduler_service._stable_digest(report.get('catalog_lineage') or {}),
            },
        }
        integrity = self.openclaw_recovery_scheduler_service._portfolio_evidence_integrity(
            report_type=report_type,
            scope=scope,
            payload=report,
            actor=str(actor or 'system'),
            export_policy={'require_signature': True, 'signer_key_id': str(payload.get('catalog_version_key') or payload.get('pack_id') or 'routing-policy-pack-catalog')},
            signing_policy={'enabled': True, 'provider': 'local-ed25519', 'key_id': str(payload.get('catalog_version_key') or payload.get('pack_id') or 'routing-policy-pack-catalog')},
        )
        return {'ok': True, 'report': report, 'integrity': integrity}

    def _build_baseline_promotion_simulation_custody_catalog_pack_evidence_package_export(
        self,
        *,
        pack: dict[str, Any] | None,
        actor: str,
        promotion_detail: dict[str, Any] | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        catalog_packs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        generated_at = time.time()
        attestation = self._build_baseline_promotion_simulation_custody_catalog_pack_attestation_export(
            pack=payload,
            actor=actor,
            promotion_detail=promotion_detail,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            catalog_packs=catalog_packs,
        )
        if not attestation.get('ok'):
            return attestation
        scope = dict(((attestation.get('report') or {}).get('scope')) or {})
        policy_summary = self._baseline_promotion_simulation_custody_catalog_pack_policy_delta_summary(payload)
        lineage = self._baseline_promotion_simulation_custody_catalog_pack_lineage(payload, catalog_packs=catalog_packs)
        package_id = str(self.openclaw_recovery_scheduler_service._stable_digest({
            'catalog_entry_id': scope.get('catalog_entry_id'),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'generated_at': generated_at,
            'actor': str(actor or 'system'),
            'kind': 'catalog_evidence_package',
        })[:24])
        evidence_report = {
            'package_id': package_id,
            'report_id': package_id,
            'report_type': 'openmiura_routing_policy_pack_catalog_evidence_package_v1',
            'generated_at': generated_at,
            'generated_by': str(actor or 'system'),
            'scope': scope,
            'metadata': {
                'pack_id': str(payload.get('pack_id') or ''),
                'pack_label': str(payload.get('pack_label') or ''),
                'description': str(payload.get('description') or ''),
                'source': str(payload.get('source') or ''),
                'catalog_entry_id': str(payload.get('catalog_entry_id') or ''),
                'catalog_scope': str(payload.get('catalog_scope') or ''),
                'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
                'catalog_version_key': str(payload.get('catalog_version_key') or ''),
                'catalog_version': int(payload.get('catalog_version') or 0),
                'catalog_lifecycle_state': str(payload.get('catalog_lifecycle_state') or 'draft'),
                'catalog_release_state': str(payload.get('catalog_release_state') or 'draft'),
            },
            'governance': {
                'approval_state': self._baseline_promotion_simulation_custody_catalog_pack_approval_state(payload),
                'review_state': self._baseline_promotion_simulation_custody_catalog_pack_review_state(payload),
                'release_state': str(payload.get('catalog_release_state') or 'draft'),
                'release_ready': self._baseline_promotion_simulation_custody_catalog_pack_release_ready(payload),
                'supersedence': self._baseline_promotion_simulation_custody_catalog_supersedence_summary(payload),
                'release_rollback': self._baseline_promotion_simulation_custody_catalog_release_rollback_summary(payload),
                'emergency_withdrawal': self._baseline_promotion_simulation_custody_catalog_emergency_withdrawal_summary(payload),
                'rollout': self._baseline_promotion_simulation_custody_catalog_rollout_summary(payload),
            },
            'attestation_linkage': {
                'report_id': str(((attestation.get('report') or {}).get('report_id')) or ''),
                'report_type': str(((attestation.get('report') or {}).get('report_type')) or ''),
                'payload_hash': str(((attestation.get('integrity') or {}).get('payload_hash')) or ''),
                'signed': bool(((attestation.get('integrity') or {}).get('signed'))),
                'latest_attestation': self._compact_baseline_promotion_simulation_export_report(payload.get('catalog_latest_attestation') or {}),
            },
            'policy_delta_summary': policy_summary,
            'lineage': lineage,
        }
        evidence_report['integrity_manifest'] = {
            'manifest_type': 'openmiura_routing_policy_pack_catalog_evidence_manifest_v1',
            'generated_at': generated_at,
            'section_digests': {
                'metadata': self.openclaw_recovery_scheduler_service._stable_digest(evidence_report.get('metadata') or {}),
                'governance': self.openclaw_recovery_scheduler_service._stable_digest(evidence_report.get('governance') or {}),
                'attestation_linkage': self.openclaw_recovery_scheduler_service._stable_digest(evidence_report.get('attestation_linkage') or {}),
                'policy_delta_summary': self.openclaw_recovery_scheduler_service._stable_digest(evidence_report.get('policy_delta_summary') or {}),
                'lineage': self.openclaw_recovery_scheduler_service._stable_digest(evidence_report.get('lineage') or {}),
            },
        }
        integrity = self.openclaw_recovery_scheduler_service._portfolio_evidence_integrity(
            report_type=str(evidence_report.get('report_type') or ''),
            scope=scope,
            payload=evidence_report,
            actor=str(actor or 'system'),
            export_policy={'require_signature': True, 'signer_key_id': str(payload.get('catalog_version_key') or payload.get('pack_id') or 'routing-policy-pack-catalog-evidence')},
            signing_policy={'enabled': True, 'provider': 'local-ed25519', 'key_id': str(payload.get('catalog_version_key') or payload.get('pack_id') or 'routing-policy-pack-catalog-evidence')},
        )
        return {'ok': True, 'package_id': package_id, 'report': evidence_report, 'integrity': integrity, 'attestation': {'report_id': str(((attestation.get('report') or {}).get('report_id')) or ''), 'report_type': str(((attestation.get('report') or {}).get('report_type')) or '')}}

    def _build_baseline_promotion_simulation_custody_catalog_pack_signed_release_bundle_export(
        self,
        *,
        pack: dict[str, Any] | None,
        actor: str,
        promotion_detail: dict[str, Any] | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        catalog_packs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        generated_at = time.time()
        scope = {
            'tenant_id': str(tenant_id or ''),
            'workspace_id': str(workspace_id or payload.get('workspace_id') or ''),
            'environment': str(environment or payload.get('environment') or ''),
            'catalog_entry_id': str(payload.get('catalog_entry_id') or payload.get('registry_entry_id') or ''),
            'catalog_scope': str(payload.get('catalog_scope') or payload.get('registry_scope') or ''),
            'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
        }
        lineage = self._baseline_promotion_simulation_custody_catalog_pack_lineage(payload, catalog_packs=catalog_packs)
        policy_summary = self._baseline_promotion_simulation_custody_catalog_pack_policy_delta_summary(payload)
        release_bundle_id = str(self.openclaw_recovery_scheduler_service._stable_digest({
            'catalog_entry_id': scope.get('catalog_entry_id'),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'release_state': str(payload.get('catalog_release_state') or 'draft'),
            'generated_at': generated_at,
        })[:24])
        bundle_manifest = {
            'manifest_type': 'openmiura_routing_policy_pack_signed_release_bundle_manifest_v1',
            'release_bundle_id': release_bundle_id,
            'catalog_entry_id': scope.get('catalog_entry_id'),
            'catalog_version_key': str(payload.get('catalog_version_key') or ''),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'catalog_scope': str(payload.get('catalog_scope') or ''),
            'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
            'catalog_lifecycle_state': str(payload.get('catalog_lifecycle_state') or 'draft'),
            'catalog_release_state': str(payload.get('catalog_release_state') or 'draft'),
            'bundle_created_at': generated_at,
            'created_by': str(actor or 'system'),
            'section_digests': {
                'metadata': self.openclaw_recovery_scheduler_service._stable_digest({
                    'pack_id': str(payload.get('pack_id') or ''),
                    'pack_label': str(payload.get('pack_label') or ''),
                    'catalog_entry_id': scope.get('catalog_entry_id'),
                }),
                'governance': self.openclaw_recovery_scheduler_service._stable_digest({
                    'approval_state': self._baseline_promotion_simulation_custody_catalog_pack_approval_state(payload),
                    'review_state': self._baseline_promotion_simulation_custody_catalog_pack_review_state(payload),
                    'release_state': str(payload.get('catalog_release_state') or 'draft'),
                }),
                'policy_delta_summary': self.openclaw_recovery_scheduler_service._stable_digest(policy_summary),
                'lineage': self.openclaw_recovery_scheduler_service._stable_digest(lineage),
                'supersedence': self.openclaw_recovery_scheduler_service._stable_digest(self._baseline_promotion_simulation_custody_catalog_supersedence_summary(payload)),
                'release_rollback': self.openclaw_recovery_scheduler_service._stable_digest(self._baseline_promotion_simulation_custody_catalog_release_rollback_summary(payload)),
                'emergency_withdrawal': self.openclaw_recovery_scheduler_service._stable_digest(self._baseline_promotion_simulation_custody_catalog_emergency_withdrawal_summary(payload)),
            },
        }
        bundle_digest = self.openclaw_recovery_scheduler_service._stable_digest(bundle_manifest)
        bundle_report = {
            'report_id': release_bundle_id,
            'report_type': 'openmiura_routing_policy_pack_signed_release_bundle_v1',
            'generated_at': generated_at,
            'generated_by': str(actor or 'system'),
            'release_bundle_id': release_bundle_id,
            'scope': scope,
            'bundle_manifest': bundle_manifest,
            'bundle_digest': bundle_digest,
            'signature_material': {
                'catalog_version_key': str(payload.get('catalog_version_key') or ''),
                'catalog_entry_id': scope.get('catalog_entry_id'),
                'catalog_release_state': str(payload.get('catalog_release_state') or 'draft'),
                'bundle_digest': bundle_digest,
            },
            'policy_pack': self._compact_baseline_promotion_simulation_routing_policy_pack(payload),
            'lineage': lineage,
            'supersedence': self._baseline_promotion_simulation_custody_catalog_supersedence_summary(payload),
            'release_rollback': self._baseline_promotion_simulation_custody_catalog_release_rollback_summary(payload),
            'emergency_withdrawal': self._baseline_promotion_simulation_custody_catalog_emergency_withdrawal_summary(payload),
            'policy_delta_summary': policy_summary,
            'rollout': self._baseline_promotion_simulation_custody_catalog_rollout_summary(payload),
        }
        integrity = self.openclaw_recovery_scheduler_service._portfolio_evidence_integrity(
            report_type=str(bundle_report.get('report_type') or ''),
            scope=scope,
            payload=bundle_report,
            actor=str(actor or 'system'),
            export_policy={'require_signature': True, 'signer_key_id': str(payload.get('catalog_version_key') or payload.get('pack_id') or 'routing-policy-pack-release-bundle')},
            signing_policy={'enabled': True, 'provider': 'local-ed25519', 'key_id': str(payload.get('catalog_version_key') or payload.get('pack_id') or 'routing-policy-pack-release-bundle')},
        )
        return {'ok': True, 'release_bundle_id': release_bundle_id, 'report': bundle_report, 'integrity': integrity}

    def _build_baseline_promotion_simulation_custody_catalog_pack_compliance_report_export(
        self,
        *,
        pack: dict[str, Any] | None,
        actor: str,
        promotion_detail: dict[str, Any] | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        node_data: dict[str, Any] | None,
        catalog_packs: list[dict[str, Any]] | None = None,
        bindings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        generated_at = time.time()
        current_context = self._baseline_promotion_simulation_custody_catalog_context(
            promotion_detail=promotion_detail,
            node_data=node_data,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        resolved_catalog_packs = [dict(item or {}) for item in list(catalog_packs or []) if isinstance(item, dict)]
        resolved_bindings = [dict(item or {}) for item in list(bindings or []) if isinstance(item, dict)]
        effective_binding = self._baseline_promotion_simulation_custody_effective_catalog_binding(
            resolved_bindings,
            context=current_context,
            catalog_packs=resolved_catalog_packs,
        )
        evaluated_packs: list[dict[str, Any]] = []
        for item in resolved_catalog_packs:
            current_item = dict(item)
            current_item['catalog_compliance_summary'] = self._baseline_promotion_simulation_custody_catalog_pack_compliance(
                current_item,
                context=current_context,
                bindings=resolved_bindings,
                effective_binding=effective_binding,
                node_data=node_data,
            )
            evaluated_packs.append(current_item)
        compliance_summary = self._baseline_promotion_simulation_custody_catalog_compliance_summary(
            evaluated_packs,
            context=current_context,
            bindings=resolved_bindings,
            effective_binding=effective_binding,
            node_data=node_data,
        )
        target_entry_id = str(payload.get('catalog_entry_id') or payload.get('registry_entry_id') or '')
        target_version = int(payload.get('catalog_version') or 0)
        pack_compliance = next((dict(item.get('catalog_compliance_summary') or {}) for item in evaluated_packs if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id and int(item.get('catalog_version') or 0) == target_version), self._baseline_promotion_simulation_custody_catalog_pack_compliance(payload, context=current_context, bindings=resolved_bindings, effective_binding=effective_binding, node_data=node_data))
        lineage = self._baseline_promotion_simulation_custody_catalog_pack_lineage(payload, catalog_packs=resolved_catalog_packs)
        policy_summary = self._baseline_promotion_simulation_custody_catalog_pack_policy_delta_summary(payload)
        last_used_pack = self._baseline_promotion_simulation_custody_catalog_last_used_pack(node_data)
        report_id = str(self.openclaw_recovery_scheduler_service._stable_digest({'catalog_entry_id': target_entry_id, 'catalog_version': target_version, 'generated_at': generated_at, 'actor': str(actor or 'system'), 'kind': 'catalog_compliance_report'})[:24])
        scope = {
            'tenant_id': str(tenant_id or ''),
            'workspace_id': str(workspace_id or payload.get('workspace_id') or ''),
            'environment': str(environment or payload.get('environment') or ''),
            'promotion_id': str(current_context.get('promotion_id') or ''),
            'catalog_entry_id': target_entry_id,
            'catalog_scope': str(payload.get('catalog_scope') or payload.get('registry_scope') or ''),
            'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
        }
        report = {
            'report_id': report_id,
            'report_type': 'openmiura_routing_policy_pack_catalog_compliance_report_v1',
            'generated_at': generated_at,
            'generated_by': str(actor or 'system'),
            'scope': scope,
            'evaluated_context': current_context,
            'policy_pack': self._compact_baseline_promotion_simulation_routing_policy_pack(payload),
            'effective_binding': self._compact_baseline_promotion_simulation_catalog_binding(effective_binding),
            'actual_usage': last_used_pack,
            'compliance': pack_compliance,
            'compliance_summary': compliance_summary,
            'divergence_explainability': {
                'drift_reasons': [str(reason) for reason in list(pack_compliance.get('drift_reasons') or []) if str(reason)][:12],
                'expected_catalog_entry_id': str((effective_binding or {}).get('catalog_entry_id') or ''),
                'expected_catalog_version': int((effective_binding or {}).get('catalog_version') or 0),
                'actual_catalog_entry_id': str(last_used_pack.get('catalog_entry_id') or last_used_pack.get('registry_entry_id') or ''),
                'actual_catalog_version': int(last_used_pack.get('catalog_version') or 0),
                'matches_effective_binding': bool(pack_compliance.get('last_used_matches')) and bool(pack_compliance.get('is_effective_for_current_scope')),
            },
            'policy_delta_summary': policy_summary,
            'lineage': lineage,
        }
        report['integrity_manifest'] = {
            'manifest_type': 'openmiura_routing_policy_pack_catalog_compliance_manifest_v1',
            'generated_at': generated_at,
            'section_digests': {
                'policy_pack': self.openclaw_recovery_scheduler_service._stable_digest(report.get('policy_pack') or {}),
                'effective_binding': self.openclaw_recovery_scheduler_service._stable_digest(report.get('effective_binding') or {}),
                'actual_usage': self.openclaw_recovery_scheduler_service._stable_digest(report.get('actual_usage') or {}),
                'compliance': self.openclaw_recovery_scheduler_service._stable_digest(report.get('compliance') or {}),
                'compliance_summary': self.openclaw_recovery_scheduler_service._stable_digest(report.get('compliance_summary') or {}),
                'policy_delta_summary': self.openclaw_recovery_scheduler_service._stable_digest(report.get('policy_delta_summary') or {}),
                'lineage': self.openclaw_recovery_scheduler_service._stable_digest(report.get('lineage') or {}),
            },
        }
        integrity = self.openclaw_recovery_scheduler_service._portfolio_evidence_integrity(
            report_type=str(report.get('report_type') or ''),
            scope=scope,
            payload=report,
            actor=str(actor or 'system'),
            export_policy={'require_signature': True, 'signer_key_id': str(payload.get('catalog_version_key') or payload.get('pack_id') or 'routing-policy-pack-compliance')},
            signing_policy={'enabled': True, 'provider': 'local-ed25519', 'key_id': str(payload.get('catalog_version_key') or payload.get('pack_id') or 'routing-policy-pack-compliance')},
        )
        return {'ok': True, 'report': report, 'integrity': integrity, 'compliance_summary': compliance_summary}

    def _baseline_promotion_simulation_custody_catalog_context(
        self,
        *,
        promotion_detail: dict[str, Any] | None,
        node_data: dict[str, Any] | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> dict[str, str]:
        promotion = dict(((promotion_detail or {}).get('baseline_promotion')) or {})
        node_payload = dict(node_data or {})
        return {
            'promotion_id': str(promotion.get('promotion_id') or (promotion_detail or {}).get('promotion_id') or node_payload.get('promotion_id') or ''),
            'tenant_id': str(tenant_id or ''),
            'workspace_id': str(workspace_id or ''),
            'environment': str(environment or ''),
            'portfolio_family_id': str(node_payload.get('portfolio_family_id') or promotion.get('portfolio_family_id') or ''),
            'runtime_family_id': str(node_payload.get('runtime_family_id') or promotion.get('runtime_family_id') or ''),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_binding_scope_order(scope: str | None) -> int:
        return {
            'global': 1,
            'workspace': 2,
            'environment': 3,
            'portfolio_family': 4,
            'runtime_family': 5,
            'promotion': 6,
        }.get(str(scope or '').strip(), 0)

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_binding_scope_key(scope: str | None, *, context: dict[str, Any] | None) -> str:
        current = dict(context or {})
        normalized_scope = str(scope or '').strip() or 'promotion'
        promotion_id = str(current.get('promotion_id') or '').strip()
        workspace_id = str(current.get('workspace_id') or '').strip()
        environment = str(current.get('environment') or '').strip()
        portfolio_family_id = str(current.get('portfolio_family_id') or '').strip()
        runtime_family_id = str(current.get('runtime_family_id') or '').strip()
        if normalized_scope == 'global':
            return 'global'
        if normalized_scope == 'workspace':
            return workspace_id
        if normalized_scope == 'environment':
            return '|'.join([workspace_id, environment]).strip('|')
        if normalized_scope == 'portfolio_family':
            return '|'.join([workspace_id, environment, portfolio_family_id]).strip('|')
        if normalized_scope == 'runtime_family':
            return '|'.join([workspace_id, environment, runtime_family_id]).strip('|')
        if normalized_scope == 'promotion':
            return promotion_id
        return ''

    @staticmethod
    def _baseline_promotion_simulation_custody_catalog_binding(payload: dict[str, Any] | None) -> dict[str, Any]:
        item = dict(payload or {})
        scope = str(item.get('binding_scope') or item.get('scope') or '').strip() or 'promotion'
        return {
            'binding_id': str(item.get('binding_id') or uuid.uuid4().hex),
            'binding_scope': scope,
            'binding_scope_key': str(item.get('binding_scope_key') or ''),
            'catalog_entry_id': str(item.get('catalog_entry_id') or ''),
            'catalog_version_key': str(item.get('catalog_version_key') or ''),
            'catalog_version': int(item.get('catalog_version') or 0),
            'catalog_pack_id': str(item.get('catalog_pack_id') or item.get('pack_id') or ''),
            'catalog_pack_label': str(item.get('catalog_pack_label') or item.get('pack_label') or ''),
            'promotion_id': str(item.get('promotion_id') or ''),
            'workspace_id': str(item.get('workspace_id') or ''),
            'environment': str(item.get('environment') or ''),
            'portfolio_family_id': str(item.get('portfolio_family_id') or ''),
            'runtime_family_id': str(item.get('runtime_family_id') or ''),
            'bound_at': item.get('bound_at'),
            'bound_by': str(item.get('bound_by') or ''),
            'state': str(item.get('state') or 'active'),
            'note': str(item.get('note') or ''),
            'catalog_owner_canvas_id': str(item.get('catalog_owner_canvas_id') or ''),
            'catalog_owner_node_id': str(item.get('catalog_owner_node_id') or ''),
            'rebound_at': item.get('rebound_at'),
            'rebound_by': str(item.get('rebound_by') or ''),
            'rebound_reason': str(item.get('rebound_reason') or ''),
        }

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

    def _build_baseline_promotion_simulation_custody_catalog_pack_analytics_report_export(
        self,
        *,
        pack: dict[str, Any] | None,
        actor: str,
        promotion_detail: dict[str, Any] | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        node_data: dict[str, Any] | None,
        catalog_packs: list[dict[str, Any]] | None = None,
        bindings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        generated_at = time.time()
        current_context = self._baseline_promotion_simulation_custody_catalog_context(
            promotion_detail=promotion_detail,
            node_data=node_data,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        resolved_catalog_packs = [dict(item or {}) for item in list(catalog_packs or []) if isinstance(item, dict)]
        resolved_bindings = [dict(item or {}) for item in list(bindings or []) if isinstance(item, dict)]
        effective_binding = self._baseline_promotion_simulation_custody_effective_catalog_binding(
            resolved_bindings,
            context=current_context,
            catalog_packs=resolved_catalog_packs,
        )
        evaluated_packs: list[dict[str, Any]] = []
        for item in resolved_catalog_packs:
            current_item = dict(item)
            current_item.update(self._baseline_promotion_simulation_custody_catalog_pack_bindings(current_item, bindings=resolved_bindings, effective_binding=effective_binding))
            current_item['catalog_compliance_summary'] = self._baseline_promotion_simulation_custody_catalog_pack_compliance(
                current_item,
                context=current_context,
                bindings=resolved_bindings,
                effective_binding=effective_binding,
                node_data=node_data,
            )
            current_item['catalog_analytics_summary'] = self._baseline_promotion_simulation_custody_catalog_pack_analytics(
                current_item,
                context=current_context,
                bindings=resolved_bindings,
                effective_binding=effective_binding,
                node_data=node_data,
            )
            evaluated_packs.append(current_item)
        analytics_summary = self._baseline_promotion_simulation_custody_catalog_analytics_summary(
            evaluated_packs,
            context=current_context,
            bindings=resolved_bindings,
            effective_binding=effective_binding,
            node_data=node_data,
        )
        dashboard = self._baseline_promotion_simulation_custody_catalog_operator_dashboard(
            evaluated_packs,
            context=current_context,
            bindings=resolved_bindings,
            effective_binding=effective_binding,
            node_data=node_data,
        )
        target_entry_id = str(payload.get('catalog_entry_id') or payload.get('registry_entry_id') or '')
        target_version = int(payload.get('catalog_version') or 0)
        pack_analytics = next(
            (
                dict(item.get('catalog_analytics_summary') or {})
                for item in evaluated_packs
                if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id and int(item.get('catalog_version') or 0) == target_version
            ),
            self._baseline_promotion_simulation_custody_catalog_pack_analytics(
                payload,
                context=current_context,
                bindings=resolved_bindings,
                effective_binding=effective_binding,
                node_data=node_data,
            ),
        )
        scope = {
            'tenant_id': str(tenant_id or ''),
            'workspace_id': str(workspace_id or payload.get('workspace_id') or ''),
            'environment': str(environment or payload.get('environment') or ''),
            'promotion_id': str(current_context.get('promotion_id') or ''),
            'catalog_entry_id': target_entry_id,
            'catalog_scope': str(payload.get('catalog_scope') or payload.get('registry_scope') or ''),
            'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
        }
        report_id = str(self.openclaw_recovery_scheduler_service._stable_digest({'catalog_entry_id': target_entry_id, 'catalog_version': target_version, 'generated_at': generated_at, 'actor': str(actor or 'system'), 'kind': 'catalog_analytics_report'})[:24])
        report = {
            'report_id': report_id,
            'report_type': 'openmiura_routing_policy_pack_catalog_analytics_report_v1',
            'generated_at': generated_at,
            'generated_by': str(actor or 'system'),
            'scope': scope,
            'evaluated_context': current_context,
            'policy_pack': self._compact_baseline_promotion_simulation_routing_policy_pack(payload),
            'pack_analytics': pack_analytics,
            'catalog_analytics_summary': analytics_summary,
            'operator_dashboard': dashboard,
            'effective_binding': self._compact_baseline_promotion_simulation_catalog_binding(effective_binding),
            'policy_delta_summary': self._baseline_promotion_simulation_custody_catalog_pack_policy_delta_summary(payload),
            'lineage': self._baseline_promotion_simulation_custody_catalog_pack_lineage(payload, catalog_packs=resolved_catalog_packs),
        }
        report['integrity_manifest'] = {
            'manifest_type': 'openmiura_routing_policy_pack_catalog_analytics_manifest_v1',
            'generated_at': generated_at,
            'section_digests': {
                'policy_pack': self.openclaw_recovery_scheduler_service._stable_digest(report.get('policy_pack') or {}),
                'pack_analytics': self.openclaw_recovery_scheduler_service._stable_digest(report.get('pack_analytics') or {}),
                'catalog_analytics_summary': self.openclaw_recovery_scheduler_service._stable_digest(report.get('catalog_analytics_summary') or {}),
                'operator_dashboard': self.openclaw_recovery_scheduler_service._stable_digest(report.get('operator_dashboard') or {}),
                'effective_binding': self.openclaw_recovery_scheduler_service._stable_digest(report.get('effective_binding') or {}),
                'policy_delta_summary': self.openclaw_recovery_scheduler_service._stable_digest(report.get('policy_delta_summary') or {}),
                'lineage': self.openclaw_recovery_scheduler_service._stable_digest(report.get('lineage') or {}),
            },
        }
        integrity = self.openclaw_recovery_scheduler_service._portfolio_evidence_integrity(
            report_type=str(report.get('report_type') or ''),
            scope=scope,
            payload=report,
            actor=str(actor or 'system'),
            export_policy={'require_signature': True, 'signer_key_id': str(payload.get('catalog_version_key') or payload.get('pack_id') or 'routing-policy-pack-analytics')},
            signing_policy={'enabled': True, 'provider': 'local-ed25519', 'key_id': str(payload.get('catalog_version_key') or payload.get('pack_id') or 'routing-policy-pack-analytics')},
        )
        return {'ok': True, 'report': report, 'integrity': integrity, 'analytics_summary': analytics_summary, 'operator_dashboard': dashboard}

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

    def _baseline_promotion_simulation_custody_organizational_publication_manifest(
        self,
        pack: dict[str, Any] | None,
        *,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        service_id = str(payload.get('organizational_service_id') or self._baseline_promotion_simulation_custody_organizational_catalog_service_id(tenant_id=tenant_id))
        visibility = str(payload.get('organizational_visibility') or 'tenant').strip() or 'tenant'
        derived_scope_key = self._baseline_promotion_simulation_custody_organizational_catalog_scope_key(
            visibility,
            tenant_id=tenant_id,
            workspace_id=str(payload.get('workspace_id') or workspace_id or ''),
            environment=str(payload.get('environment') or environment or ''),
        )
        manifest = {
            'manifest_type': 'openmiura_routing_policy_pack_organizational_publication_manifest_v1',
            'catalog_entry_id': str(payload.get('catalog_entry_id') or payload.get('registry_entry_id') or ''),
            'catalog_version_key': str(payload.get('catalog_version_key') or ''),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'pack_id': str(payload.get('pack_id') or ''),
            'pack_label': str(payload.get('pack_label') or ''),
            'organizational_service_id': service_id,
            'organizational_service_entry_id': str(payload.get('organizational_service_entry_id') or ''),
            'organizational_visibility': visibility,
            'organizational_service_scope_key': str(payload.get('organizational_service_scope_key') or derived_scope_key),
            'catalog_lifecycle_state': str(payload.get('catalog_lifecycle_state') or 'draft'),
            'catalog_release_state': str(payload.get('catalog_release_state') or 'draft'),
            'policy_digest': str(self.openclaw_recovery_scheduler_service._stable_digest({
                'comparison_policies': list(payload.get('comparison_policies') or []),
                'category_keys': [str(item) for item in list(payload.get('category_keys') or []) if str(item)],
                'tags': [str(item) for item in list(payload.get('tags') or []) if str(item)],
                'catalog_scope': str(payload.get('catalog_scope') or ''),
                'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
            })),
            'published_at': payload.get('organizational_published_at'),
            'published_by': str(payload.get('organizational_published_by') or ''),
        }
        manifest['manifest_digest'] = str(self.openclaw_recovery_scheduler_service._stable_digest({
            key: value for key, value in manifest.items() if key != 'manifest_digest'
        }))
        return manifest

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

    def _resolve_baseline_promotion_simulation_custody_organizational_catalog_service_pack(
        self,
        gw: AdminGatewayLike,
        *,
        promotion_detail: dict[str, Any] | None,
        node_data: dict[str, Any] | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        pack_id: str | None = None,
        catalog_entry_id: str | None = None,
        organizational_service_entry_id: str | None = None,
    ) -> dict[str, Any]:
        target_pack_id = str(pack_id or '').strip()
        target_entry_id = str(catalog_entry_id or '').strip()
        target_service_entry_id = str(organizational_service_entry_id or '').strip()
        service_packs = self._baseline_promotion_simulation_custody_organizational_catalog_service_packs(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        for item in service_packs:
            if target_service_entry_id and str(item.get('organizational_service_entry_id') or '') == target_service_entry_id:
                return item
            if target_entry_id and str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id:
                return item
            if target_pack_id and str(item.get('pack_id') or '') == target_pack_id:
                return item
        if target_service_entry_id or target_entry_id or target_pack_id:
            return {}
        current_context = self._baseline_promotion_simulation_custody_catalog_context(
            promotion_detail=promotion_detail,
            node_data=node_data,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        all_bindings = self._baseline_promotion_simulation_custody_catalog_policy_bindings(gw, tenant_id=tenant_id)
        effective_binding = self._baseline_promotion_simulation_custody_effective_catalog_binding(
            all_bindings,
            context=current_context,
            catalog_packs=service_packs,
        )
        effective_entry_id = str(effective_binding.get('catalog_entry_id') or '')
        effective_version = int(effective_binding.get('catalog_version') or 0)
        if effective_entry_id and bool(effective_binding.get('binding_ready', False)):
            match = next(
                (
                    item for item in service_packs
                    if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == effective_entry_id and int(item.get('catalog_version') or 0) == effective_version
                ),
                {},
            )
            if match:
                return match
        return next((item for item in service_packs if str(item.get('catalog_release_state') or '') in {'released', 'rolling_out'}), {})

    def _build_baseline_promotion_simulation_custody_organizational_catalog_snapshot_export(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        promotion_detail: dict[str, Any] | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        node_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        current_context = self._baseline_promotion_simulation_custody_catalog_context(
            promotion_detail=promotion_detail,
            node_data=node_data,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        service_packs = self._baseline_promotion_simulation_custody_organizational_catalog_service_packs(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        all_bindings = self._baseline_promotion_simulation_custody_catalog_policy_bindings(gw, tenant_id=tenant_id)
        effective_binding = self._baseline_promotion_simulation_custody_effective_catalog_binding(
            all_bindings,
            context=current_context,
            catalog_packs=service_packs,
        )
        enriched_service_packs: list[dict[str, Any]] = []
        for item in service_packs:
            current_item = dict(item)
            current_item.update(self._baseline_promotion_simulation_custody_catalog_pack_bindings(current_item, bindings=all_bindings, effective_binding=effective_binding))
            current_item['catalog_compliance_summary'] = self._baseline_promotion_simulation_custody_catalog_pack_compliance(
                current_item,
                context=current_context,
                bindings=all_bindings,
                effective_binding=effective_binding,
                node_data=node_data,
            )
            current_item['catalog_analytics_summary'] = self._baseline_promotion_simulation_custody_catalog_pack_analytics(
                current_item,
                context=current_context,
                bindings=all_bindings,
                effective_binding=effective_binding,
                node_data=node_data,
            )
            enriched_service_packs.append(current_item)
        summary = self._baseline_promotion_simulation_custody_organizational_catalog_service_summary(
            enriched_service_packs,
            tenant_id=tenant_id,
            effective_binding=effective_binding,
        )
        catalog_summary = self._baseline_promotion_simulation_custody_catalog_summary(enriched_service_packs)
        analytics_summary = self._baseline_promotion_simulation_custody_catalog_analytics_summary(
            enriched_service_packs,
            context=current_context,
            bindings=all_bindings,
            effective_binding=effective_binding,
            node_data=node_data,
        )
        generated_at = time.time()
        report = {
            'report_id': str(self.openclaw_recovery_scheduler_service._stable_digest({'kind': 'organizational_catalog_snapshot', 'generated_at': generated_at, 'tenant_id': str(tenant_id or '')})[:24]),
            'report_type': 'openmiura_routing_policy_pack_organizational_catalog_snapshot_v1',
            'generated_at': generated_at,
            'generated_by': str(actor or 'system'),
            'scope': {'tenant_id': str(tenant_id or ''), 'workspace_id': str(workspace_id or ''), 'environment': str(environment or '')},
            'service': {'service_id': str(summary.get('service_id') or ''), 'service_label': 'Organizational routing policy pack catalog', 'entry_count': int(summary.get('published_entry_count') or 0)},
            'summary': summary,
            'effective_binding': self._compact_baseline_promotion_simulation_catalog_binding(effective_binding),
            'catalog_summary': catalog_summary,
            'catalog_analytics_summary': analytics_summary,
            'entries': [self._compact_baseline_promotion_simulation_routing_policy_pack(item) for item in enriched_service_packs[:24]],
        }
        report['integrity_manifest'] = {
            'manifest_type': 'openmiura_routing_policy_pack_organizational_catalog_manifest_v1',
            'generated_at': generated_at,
            'section_digests': {
                'service': self.openclaw_recovery_scheduler_service._stable_digest(report.get('service') or {}),
                'summary': self.openclaw_recovery_scheduler_service._stable_digest(report.get('summary') or {}),
                'effective_binding': self.openclaw_recovery_scheduler_service._stable_digest(report.get('effective_binding') or {}),
                'catalog_summary': self.openclaw_recovery_scheduler_service._stable_digest(report.get('catalog_summary') or {}),
                'catalog_analytics_summary': self.openclaw_recovery_scheduler_service._stable_digest(report.get('catalog_analytics_summary') or {}),
                'entries': self.openclaw_recovery_scheduler_service._stable_digest(report.get('entries') or []),
            },
        }
        integrity = self.openclaw_recovery_scheduler_service._portfolio_evidence_integrity(
            report_type=str(report.get('report_type') or ''),
            scope=dict(report.get('scope') or {}),
            payload=report,
            actor=str(actor or 'system'),
            export_policy={'require_signature': True, 'signer_key_id': str(summary.get('service_id') or 'routing-policy-pack-organizational-catalog')},
            signing_policy={'enabled': True, 'provider': 'local-ed25519', 'key_id': str(summary.get('service_id') or 'routing-policy-pack-organizational-catalog')},
        )
        return {'ok': True, 'report': report, 'integrity': integrity, 'summary': summary}

    def _build_baseline_promotion_simulation_custody_organizational_catalog_reconciliation_export(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        promotion_detail: dict[str, Any] | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        node_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        current_context = self._baseline_promotion_simulation_custody_catalog_context(
            promotion_detail=promotion_detail,
            node_data=node_data,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        service_packs = self._baseline_promotion_simulation_custody_organizational_catalog_service_packs(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        all_bindings = self._baseline_promotion_simulation_custody_catalog_policy_bindings(gw, tenant_id=tenant_id)
        effective_binding = self._baseline_promotion_simulation_custody_effective_catalog_binding(
            all_bindings,
            context=current_context,
            catalog_packs=service_packs,
        )
        enriched_service_packs: list[dict[str, Any]] = []
        issue_counts: dict[str, int] = {}
        for item in service_packs:
            current_item = dict(item)
            current_item.update(self._baseline_promotion_simulation_custody_catalog_pack_bindings(current_item, bindings=all_bindings, effective_binding=effective_binding))
            current_item['catalog_compliance_summary'] = self._baseline_promotion_simulation_custody_catalog_pack_compliance(
                current_item,
                context=current_context,
                bindings=all_bindings,
                effective_binding=effective_binding,
                node_data=node_data,
            )
            current_item['catalog_analytics_summary'] = self._baseline_promotion_simulation_custody_catalog_pack_analytics(
                current_item,
                context=current_context,
                bindings=all_bindings,
                effective_binding=effective_binding,
                node_data=node_data,
            )
            current_item['organizational_publication_health'] = self._baseline_promotion_simulation_custody_organizational_publication_health(
                current_item,
                tenant_id=tenant_id,
                workspace_id=current_item.get('workspace_id') or workspace_id,
                environment=current_item.get('environment') or environment,
            )
            for issue_code, count in dict((current_item.get('organizational_publication_health') or {}).get('issue_counts') or {}).items():
                issue_counts[str(issue_code)] = issue_counts.get(str(issue_code), 0) + int(count or 0)
            enriched_service_packs.append(current_item)
        summary = self._baseline_promotion_simulation_custody_organizational_catalog_service_summary(
            enriched_service_packs,
            tenant_id=tenant_id,
            effective_binding=effective_binding,
        )
        generated_at = time.time()
        reconciliation_summary = {
            'overall_status': 'drifted' if int(summary.get('drifted_publication_count') or 0) > 0 else 'healthy',
            'published_entry_count': int(summary.get('published_entry_count') or 0),
            'healthy_publication_count': int(summary.get('healthy_publication_count') or 0),
            'drifted_publication_count': int(summary.get('drifted_publication_count') or 0),
            'issue_counts': issue_counts,
            'latest_publication': dict(summary.get('latest_publication') or {}),
            'effective_entry': dict(summary.get('effective_entry') or {}),
        }
        report = {
            'report_id': str(self.openclaw_recovery_scheduler_service._stable_digest({'kind': 'organizational_catalog_reconciliation', 'generated_at': generated_at, 'tenant_id': str(tenant_id or ''), 'workspace_id': str(workspace_id or ''), 'environment': str(environment or '')})[:24]),
            'report_type': 'openmiura_routing_policy_pack_organizational_catalog_reconciliation_report_v1',
            'generated_at': generated_at,
            'generated_by': str(actor or 'system'),
            'scope': {'tenant_id': str(tenant_id or ''), 'workspace_id': str(workspace_id or ''), 'environment': str(environment or '')},
            'service': {'service_id': str(summary.get('service_id') or ''), 'service_label': 'Organizational routing policy pack catalog', 'entry_count': int(summary.get('published_entry_count') or 0)},
            'summary': summary,
            'reconciliation_summary': reconciliation_summary,
            'effective_binding': self._compact_baseline_promotion_simulation_catalog_binding(effective_binding),
            'entries': [self._compact_baseline_promotion_simulation_routing_policy_pack(item) for item in enriched_service_packs[:24]],
        }
        report['integrity_manifest'] = {
            'manifest_type': 'openmiura_routing_policy_pack_organizational_catalog_reconciliation_manifest_v1',
            'generated_at': generated_at,
            'section_digests': {
                'service': self.openclaw_recovery_scheduler_service._stable_digest(report.get('service') or {}),
                'summary': self.openclaw_recovery_scheduler_service._stable_digest(report.get('summary') or {}),
                'reconciliation_summary': self.openclaw_recovery_scheduler_service._stable_digest(report.get('reconciliation_summary') or {}),
                'effective_binding': self.openclaw_recovery_scheduler_service._stable_digest(report.get('effective_binding') or {}),
                'entries': self.openclaw_recovery_scheduler_service._stable_digest(report.get('entries') or []),
            },
        }
        integrity = self.openclaw_recovery_scheduler_service._portfolio_evidence_integrity(
            report_type=str(report.get('report_type') or ''),
            scope=dict(report.get('scope') or {}),
            payload=report,
            actor=str(actor or 'system'),
            export_policy={'require_signature': True, 'signer_key_id': str(summary.get('service_id') or 'routing-policy-pack-organizational-catalog-reconciliation')},
            signing_policy={'enabled': True, 'provider': 'local-ed25519', 'key_id': str(summary.get('service_id') or 'routing-policy-pack-organizational-catalog-reconciliation')},
        )
        return {'ok': True, 'report': report, 'integrity': integrity, 'reconciliation_summary': reconciliation_summary, 'summary': summary}

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

    def _resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
        self,
        gw: AdminGatewayLike,
        *,
        promotion_detail: dict[str, Any] | None,
        node_data: dict[str, Any] | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        pack_id: str | None = None,
        catalog_entry_id: str | None = None,
    ) -> dict[str, Any]:
        target_pack_id = str(pack_id or '').strip()
        target_entry_id = str(catalog_entry_id or '').strip()
        catalog_packs = self._baseline_promotion_simulation_custody_catalog_policy_packs(
            gw,
            promotion_detail=promotion_detail,
            node_data=node_data,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        for item in catalog_packs:
            if target_entry_id and str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id:
                return item
            if target_pack_id and str(item.get('pack_id') or '') == target_pack_id:
                return item
        if not target_entry_id and not target_pack_id:
            context = self._baseline_promotion_simulation_custody_catalog_context(
                promotion_detail=promotion_detail,
                node_data=node_data,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            effective_binding = self._baseline_promotion_simulation_custody_effective_catalog_binding(
                self._baseline_promotion_simulation_custody_catalog_policy_bindings(gw, tenant_id=tenant_id),
                context=context,
                catalog_packs=catalog_packs,
            )
            effective_entry_id = str(effective_binding.get('catalog_entry_id') or '')
            effective_version = int(effective_binding.get('catalog_version') or 0)
            if effective_entry_id and bool(effective_binding.get('binding_ready', False)):
                match = next((item for item in catalog_packs if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == effective_entry_id and int(item.get('catalog_version') or 0) == effective_version), {})
                if match:
                    match = dict(match)
                    match['catalog_effective_binding'] = effective_binding
                    match['catalog_is_effective_for_current_scope'] = True
                    return match
        return {}

    @staticmethod
    def _baseline_promotion_simulation_state(
        *,
        simulation: dict[str, Any],
        actor: str,
        request: dict[str, Any],
        review: dict[str, Any] | None = None,
        created_promotions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        review_payload = dict(review or simulation.get('review') or {})
        review_state = dict(simulation.get('review_state') or {})
        approval_preview = dict(simulation.get('approval_preview') or {})
        approval_policy = dict(approval_preview.get('approval_policy') or {})
        rollout_plan = dict(simulation.get('rollout_plan') or {})
        rollout_items = []
        for item in list(rollout_plan.get('items') or []):
            wave = dict(item or {})
            rollout_items.append({
                'wave_no': int(wave.get('wave_no') or 0),
                'wave_id': str(wave.get('wave_id') or ''),
                'status': str(wave.get('status') or ''),
                'status_forecast': str(wave.get('status_forecast') or ''),
                'portfolio_count': len(list(wave.get('portfolio_ids') or [])),
                'gate_evaluation': {
                    'status': str((wave.get('gate_evaluation') or {}).get('status') or ''),
                    'reasons': [str(reason) for reason in list((wave.get('gate_evaluation') or {}).get('reasons') or []) if str(reason)],
                },
                'calendar_decision': {
                    'allowed': bool((wave.get('calendar_decision') or {}).get('allowed', False)),
                    'next_allowed_at': (wave.get('calendar_decision') or {}).get('next_allowed_at'),
                },
            })
        analytics = dict(simulation.get('analytics') or {})
        diff = dict(simulation.get('diff') or {})
        return {
            'simulation_id': str(simulation.get('simulation_id') or uuid.uuid4().hex),
            'kind': 'baseline_promotion_dry_run',
            'simulated_at': float(simulation.get('simulated_at') or time.time()),
            'simulated_by': str(actor or 'operator'),
            'mode': str(simulation.get('mode') or 'dry-run'),
            'catalog_id': str(simulation.get('catalog_id') or ''),
            'catalog_name': str(simulation.get('catalog_name') or ''),
            'candidate_catalog_version': str(simulation.get('candidate_catalog_version') or ''),
            'summary': dict(simulation.get('summary') or {}),
            'validation': dict(simulation.get('validation') or {}),
            'approval_preview': {
                'required': bool(approval_preview.get('required', False)),
                'summary': dict(approval_preview.get('summary') or {}),
                'approval_policy': {
                    'enabled': bool(approval_policy.get('enabled', False)),
                    'mode': str(approval_policy.get('mode') or ''),
                    'layers': [
                        {
                            'layer_id': str(layer.get('layer_id') or ''),
                            'label': str(layer.get('label') or ''),
                            'requested_role': str(layer.get('requested_role') or ''),
                            'required': bool(layer.get('required', True)),
                        }
                        for layer in list(approval_policy.get('layers') or [])
                    ],
                },
            },
            'analytics': {
                'timeline_count': int(analytics.get('timeline_count') or 0),
                'approval_count': int(analytics.get('approval_count') or 0),
                'advance_job_count': int(analytics.get('advance_job_count') or 0),
                'rollback_attestation_count': int(analytics.get('rollback_attestation_count') or 0),
                'gate_reason_counts': dict(analytics.get('gate_reason_counts') or {}),
                'rollout_plan_status_counts': dict(analytics.get('rollout_plan_status_counts') or {}),
            },
            'rollout_plan': {
                'wave_count': int(rollout_plan.get('wave_count') or len(rollout_items)),
                'summary': dict(rollout_plan.get('summary') or {}),
                'validation': dict(rollout_plan.get('validation') or {}),
                'items': rollout_items,
            },
            'simulation_source': {
                'kind': str((simulation.get('simulation_source') or {}).get('kind') or ''),
                'promotion_id': str((simulation.get('simulation_source') or {}).get('promotion_id') or ''),
                'release_id': str((simulation.get('simulation_source') or {}).get('release_id') or ''),
                'catalog_id': str((simulation.get('simulation_source') or {}).get('catalog_id') or ''),
            },
            'simulation_policy': LiveCanvasService._compact_baseline_promotion_simulation_policy(simulation.get('simulation_policy') or {}),
            'diff': {
                'summary': dict(diff.get('summary') or {}),
                'items': [
                    {
                        'environment': str(item.get('environment') or ''),
                        'changed': bool(item.get('changed', False)),
                        'change_type': str(item.get('change_type') or ''),
                    }
                    for item in list(diff.get('items') or [])
                ],
            },
            'explainability': {
                'decision': str((simulation.get('explainability') or {}).get('decision') or ''),
                'blocking_reasons': [str(item) for item in list((simulation.get('explainability') or {}).get('blocking_reasons') or []) if str(item)][:5],
                'advisory_reasons': [str(item) for item in list((simulation.get('explainability') or {}).get('advisory_reasons') or []) if str(item)][:5],
                'runtime_status': {
                    'status': str(((simulation.get('explainability') or {}).get('runtime_status') or {}).get('status') or ''),
                    'reason': str(((simulation.get('explainability') or {}).get('runtime_status') or {}).get('reason') or ''),
                },
            },
            'observed_context': {
                'catalog': {
                    'catalog_id': str((((simulation.get('observed_context') or {}).get('catalog')) or {}).get('catalog_id') or ''),
                    'version': str((((simulation.get('observed_context') or {}).get('catalog')) or {}).get('version') or ((((simulation.get('observed_context') or {}).get('catalog')) or {}).get('current_version')) or ''),
                },
                'candidate': {
                    'fingerprint': str((((simulation.get('observed_context') or {}).get('candidate')) or {}).get('fingerprint') or ''),
                    'environment_count': int((((simulation.get('observed_context') or {}).get('candidate')) or {}).get('environment_count') or 0),
                },
                'source': {
                    'promotion_id': str((((simulation.get('observed_context') or {}).get('source')) or {}).get('promotion_id') or ''),
                    'candidate_catalog_version': str((((simulation.get('observed_context') or {}).get('source')) or {}).get('candidate_catalog_version') or ''),
                    'missing': bool(((((simulation.get('observed_context') or {}).get('source')) or {}).get('missing'))),
                },
            },
            'observed_versions': dict(simulation.get('observed_versions') or {}),
            'fingerprints': dict(simulation.get('fingerprints') or {}),
            'simulation_status': str(
                simulation.get('simulation_status')
                or (
                    'stale'
                    if bool(simulation.get('stale'))
                    else 'expired'
                    if bool(simulation.get('expired'))
                    else 'blocked'
                    if bool(simulation.get('blocked'))
                    else 'reviewed'
                    if bool(review_payload.get('approved'))
                    else 'ready'
                )
            ),
            'stale': bool(simulation.get('stale', False)),
            'stale_reasons': [str(item) for item in list(simulation.get('stale_reasons') or []) if str(item)],
            'expired': bool(simulation.get('expired', False)),
            'expires_at': simulation.get('expires_at'),
            'blocked': bool(simulation.get('blocked', False)),
            'blocked_reasons': [str(item) for item in list(simulation.get('blocked_reasons') or []) if str(item)],
            'why_blocked': str(simulation.get('why_blocked') or ''),
            'request': {
                'promotion_id': str((request or {}).get('promotion_id') or ''),
                'catalog_id': str((request or {}).get('catalog_id') or ''),
                'candidate_catalog_version': str((request or {}).get('candidate_catalog_version') or ''),
                'candidate_baselines': dict((request or {}).get('candidate_baselines') or {}),
                'version': (request or {}).get('version'),
                'rollout_policy': dict((request or {}).get('rollout_policy') or {}),
                'gate_policy': dict((request or {}).get('gate_policy') or {}),
                'rollback_policy': dict((request or {}).get('rollback_policy') or {}),
                'reason': str((request or {}).get('reason') or ''),
                'auto_approve': bool((request or {}).get('auto_approve', False)),
            },
            'review': ({
                'approved': bool(review_payload.get('approved', False)),
                'rejected': bool(review_payload.get('rejected', False)),
                'reviewed_by': str(review_payload.get('reviewed_by') or ''),
                'approved_at': review_payload.get('approved_at'),
                'rejected_at': review_payload.get('rejected_at'),
                'reason': str(review_payload.get('reason') or ''),
            } if any([
                bool(review_payload.get('approved', False)),
                bool(review_payload.get('rejected', False)),
                str(review_payload.get('reviewed_by') or '').strip(),
                review_payload.get('approved_at') is not None,
                review_payload.get('rejected_at') is not None,
                str(review_payload.get('reason') or '').strip(),
                bool(list(review_state.get('items') or [])),
                str(review_state.get('overall_status') or '').strip() not in {'', 'not_requested', 'not_required'},
            ]) else {}),
            'review_state': {
                **review_state,
                'items': [
                    {
                        'review_id': str(item.get('review_id') or ''),
                        'layer_id': str(item.get('layer_id') or ''),
                        'label': str(item.get('label') or ''),
                        'requested_role': str(item.get('requested_role') or ''),
                        'decision': str(item.get('decision') or ''),
                        'actor': str(item.get('actor') or item.get('reviewed_by') or ''),
                        'reviewed_by': str(item.get('reviewed_by') or item.get('actor') or ''),
                        'reason': str(item.get('reason') or ''),
                        'created_at': item.get('created_at'),
                        'decided_at': item.get('decided_at') or item.get('reviewed_at'),
                        'reviewed_at': item.get('reviewed_at') or item.get('decided_at'),
                    }
                    for item in list(review_state.get('items') or [])[-5:]
                ],
                'layers': [
                    {
                        'layer_id': str(item.get('layer_id') or ''),
                        'label': str(item.get('label') or ''),
                        'requested_role': str(item.get('requested_role') or ''),
                        'required': bool(item.get('required', True)),
                        'status': str(item.get('status') or ''),
                    }
                    for item in list(review_state.get('layers') or [])
                ],
                'next_layer': {
                    'layer_id': str((review_state.get('next_layer') or {}).get('layer_id') or ''),
                    'label': str((review_state.get('next_layer') or {}).get('label') or ''),
                    'requested_role': str((review_state.get('next_layer') or {}).get('requested_role') or ''),
                    'required': bool((review_state.get('next_layer') or {}).get('required', True)),
                    'status': str((review_state.get('next_layer') or {}).get('status') or ''),
                },
                'latest_review': dict(review_state.get('latest_review') or {}),
                'pending_layers': [str(item) for item in list(review_state.get('pending_layers') or []) if str(item)],
            },
            'reviewed_at': review_payload.get('approved_at') or review_payload.get('rejected_at') or review_payload.get('reviewed_at') or simulation.get('reviewed_at'),
            'export_state': {
                'attestation_count': int(((simulation.get('export_state') or {}).get('attestation_count') or 0)),
                'review_audit_count': int(((simulation.get('export_state') or {}).get('review_audit_count') or 0)),
                'evidence_package_count': int(((simulation.get('export_state') or {}).get('evidence_package_count') or 0)),
                'latest_attestation': LiveCanvasService._compact_baseline_promotion_simulation_export_report(((simulation.get('export_state') or {}).get('latest_attestation') or {})),
                'latest_review_audit': LiveCanvasService._compact_baseline_promotion_simulation_export_report(((simulation.get('export_state') or {}).get('latest_review_audit') or {})),
                'latest_evidence_package': LiveCanvasService._compact_baseline_promotion_simulation_export_report(((simulation.get('export_state') or {}).get('latest_evidence_package') or {})),
                'registry_summary': LiveCanvasService._compact_baseline_promotion_simulation_registry_summary(((simulation.get('export_state') or {}).get('registry_summary') or {})),
                'verification_count': int(((simulation.get('export_state') or {}).get('verification_count') or 0)),
                'latest_verification': {
                    'package_id': str((((simulation.get('export_state') or {}).get('latest_verification') or {}).get('package_id')) or ''),
                    'verified_at': (((simulation.get('export_state') or {}).get('latest_verification') or {}).get('verified_at')),
                    'verified_by': str((((simulation.get('export_state') or {}).get('latest_verification') or {}).get('verified_by')) or ''),
                    'status': str((((simulation.get('export_state') or {}).get('latest_verification') or {}).get('status')) or ''),
                    'valid': bool((((simulation.get('export_state') or {}).get('latest_verification') or {}).get('valid'))),
                    'failures': [str(item) for item in list((((simulation.get('export_state') or {}).get('latest_verification') or {}).get('failures')) or []) if str(item)],
                    'artifact_sha256': str((((simulation.get('export_state') or {}).get('latest_verification') or {}).get('artifact_sha256')) or ''),
                    'artifact_source': str((((simulation.get('export_state') or {}).get('latest_verification') or {}).get('artifact_source')) or ''),
                    'escrow_status': str((((simulation.get('export_state') or {}).get('latest_verification') or {}).get('escrow_status')) or ''),
                    'registry_entry': {
                        'entry_id': str((((((simulation.get('export_state') or {}).get('latest_verification') or {}).get('registry_entry')) or {}).get('entry_id')) or ''),
                        'sequence': int((((((simulation.get('export_state') or {}).get('latest_verification') or {}).get('registry_entry')) or {}).get('sequence')) or 0),
                    },
                },
                'reconciliation_count': int(((simulation.get('export_state') or {}).get('reconciliation_count') or 0)),
                'latest_reconciliation': {
                    'reconciliation_id': str((((simulation.get('export_state') or {}).get('latest_reconciliation') or {}).get('reconciliation_id')) or ''),
                    'package_id': str((((simulation.get('export_state') or {}).get('latest_reconciliation') or {}).get('package_id')) or ''),
                    'reconciled_at': (((simulation.get('export_state') or {}).get('latest_reconciliation') or {}).get('reconciled_at')),
                    'reconciled_by': str((((simulation.get('export_state') or {}).get('latest_reconciliation') or {}).get('reconciled_by')) or ''),
                    'overall_status': str((((simulation.get('export_state') or {}).get('latest_reconciliation') or {}).get('overall_status')) or ''),
                    'drifted_count': int((((simulation.get('export_state') or {}).get('latest_reconciliation') or {}).get('drifted_count')) or 0),
                    'missing_archive_count': int((((simulation.get('export_state') or {}).get('latest_reconciliation') or {}).get('missing_archive_count')) or 0),
                    'lock_drift_count': int((((simulation.get('export_state') or {}).get('latest_reconciliation') or {}).get('lock_drift_count')) or 0),
                    'registry_drift_count': int((((simulation.get('export_state') or {}).get('latest_reconciliation') or {}).get('registry_drift_count')) or 0),
                    'latest_package_id': str((((simulation.get('export_state') or {}).get('latest_reconciliation') or {}).get('latest_package_id')) or ''),
                    'latest_archive_path': str((((simulation.get('export_state') or {}).get('latest_reconciliation') or {}).get('latest_archive_path')) or ''),
                },
                'restore_count': int(((simulation.get('export_state') or {}).get('restore_count') or 0)),
                'latest_restore': {
                    'restore_id': str((((simulation.get('export_state') or {}).get('latest_restore') or {}).get('restore_id')) or ''),
                    'package_id': str((((simulation.get('export_state') or {}).get('latest_restore') or {}).get('package_id')) or ''),
                    'restored_at': (((simulation.get('export_state') or {}).get('latest_restore') or {}).get('restored_at')),
                    'restored_by': str((((simulation.get('export_state') or {}).get('latest_restore') or {}).get('restored_by')) or ''),
                    'simulation_status': str((((simulation.get('export_state') or {}).get('latest_restore') or {}).get('simulation_status')) or ''),
                    'stale': bool((((simulation.get('export_state') or {}).get('latest_restore') or {}).get('stale'))),
                    'expired': bool((((simulation.get('export_state') or {}).get('latest_restore') or {}).get('expired'))),
                    'blocked': bool((((simulation.get('export_state') or {}).get('latest_restore') or {}).get('blocked'))),
                    'why_blocked': str((((simulation.get('export_state') or {}).get('latest_restore') or {}).get('why_blocked')) or ''),
                },
                'custody_guard': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_custody_guard(((simulation.get('export_state') or {}).get('custody_guard') or {}))),
                'custody_alerts_summary': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_custody_alerts_summary(((simulation.get('export_state') or {}).get('custody_alerts_summary') or {}))),
                'custody_active_alert': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_custody_active_alert(((simulation.get('export_state') or {}).get('custody_active_alert') or {}))),
                'last_alert_action': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_last_alert_action(((simulation.get('export_state') or {}).get('last_alert_action') or {}))),
                'latest_routing_replay': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_replay(((simulation.get('export_state') or {}).get('latest_routing_replay') or {}))),
                'routing_policy_what_if_presets': [LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(item)) for item in list(((simulation.get('export_state') or {}).get('routing_policy_what_if_presets') or []))[:6]],
                'saved_routing_policy_packs': [LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(item)) for item in list(((simulation.get('export_state') or {}).get('saved_routing_policy_packs') or []))[:6]],
                'routing_policy_pack_registry': [LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(item)) for item in list(((simulation.get('export_state') or {}).get('routing_policy_pack_registry') or []))[:6]],
                'routing_policy_pack_catalog': [LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(item)) for item in list(((simulation.get('export_state') or {}).get('routing_policy_pack_catalog') or []))[:6]],
                'routing_policy_pack_catalog_summary': dict(((simulation.get('export_state') or {}).get('routing_policy_pack_catalog_summary') or {})),
                'shared_routing_policy_packs': [LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(item)) for item in list(((simulation.get('export_state') or {}).get('shared_routing_policy_packs') or []))[:6]],
                'last_saved_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_saved_routing_policy_pack') or {}))),
                'last_promoted_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_promoted_routing_policy_pack') or {}))),
                'last_catalog_promoted_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_catalog_promoted_routing_policy_pack') or {}))),
                'last_catalog_lifecycle_transition_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_catalog_lifecycle_transition_routing_policy_pack') or {}))),
                'last_catalog_approval_transition_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_catalog_approval_transition_routing_policy_pack') or {}))),
                'last_catalog_release_transition_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_catalog_release_transition_routing_policy_pack') or {}))),
                'last_catalog_attestation_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_catalog_attestation_routing_policy_pack') or {}))),
                'last_catalog_review_transition_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_catalog_review_transition_routing_policy_pack') or {}))),
                'last_catalog_evidence_package_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_catalog_evidence_package_routing_policy_pack') or {}))),
                'last_catalog_signed_release_bundle_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_catalog_signed_release_bundle_routing_policy_pack') or {}))),
                'last_catalog_compliance_report_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_catalog_compliance_report_routing_policy_pack') or {}))),
                'last_catalog_rollout_transition_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_catalog_rollout_transition_routing_policy_pack') or {}))),
                'last_shared_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_shared_routing_policy_pack') or {}))),
                'last_shared_catalog_routing_policy_pack': LiveCanvasService._prune_canvas_payload(LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(((simulation.get('export_state') or {}).get('last_shared_catalog_routing_policy_pack') or {}))),
            },
            'created_promotions': [dict(item) for item in list(created_promotions or simulation.get('created_promotions') or [])],
        }


    def list_documents(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items = gw.audit.list_canvas_documents(limit=limit, status=status, **scope)
        return {'ok': True, 'items': items, 'scope': scope}

    def create_document(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        title: str,
        description: str = '',
        status: str = 'active',
        metadata: dict[str, Any] | None = None,
        share_token: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        if not str(title or '').strip():
            raise ValueError('canvas title is required')
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        self._enforce_scope_limits(gw, scope=scope)
        self._enforce_canvas_payload(payload=dict(metadata or {}))
        document = gw.audit.create_canvas_document(
            title=str(title).strip(),
            description=str(description or ''),
            status=str(status or 'active').strip() or 'active',
            created_by=str(actor or 'admin'),
            metadata=dict(metadata or {}),
            **scope,
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', document['canvas_id'], {
            'action': 'canvas_document_created',
            'title': document['title'],
            **scope,
        }, **scope)
        return {'ok': True, 'document': document, 'scope': scope}

    def get_document(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            return {'ok': False, 'reason': 'not_found', 'canvas_id': canvas_id, 'scope': scope}
        return {
            'ok': True,
            'document': document,
            'nodes': gw.audit.list_canvas_nodes(canvas_id=canvas_id, **scope),
            'edges': gw.audit.list_canvas_edges(canvas_id=canvas_id, **scope),
            'views': gw.audit.list_canvas_views(canvas_id=canvas_id, **scope),
            'presence': gw.audit.list_canvas_presence(canvas_id=canvas_id, **scope),
            'events': gw.audit.list_canvas_events(canvas_id=canvas_id, limit=50, **scope),
            'comments': self.list_comments(gw, canvas_id=canvas_id, **scope).get('items', []),
            'snapshots': self.list_snapshots(gw, canvas_id=canvas_id, **scope).get('items', []),
            'presence_events': self.list_presence_events(gw, canvas_id=canvas_id, **scope).get('items', []),
            'overlay_states': self.list_overlay_states(gw, canvas_id=canvas_id, **scope).get('items', []),
            'scope': scope,
        }

    def upsert_node(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        node_id: str | None = None,
        node_type: str,
        label: str,
        position_x: float = 0.0,
        position_y: float = 0.0,
        width: float = 240.0,
        height: float = 120.0,
        data: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        self._enforce_canvas_payload(payload={'label': label, 'data': data})
        if not node_id:
            self._enforce_canvas_counts(gw, canvas_id=canvas_id, kind='node', tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        node = gw.audit.upsert_canvas_node(
            canvas_id=canvas_id,
            node_id=node_id,
            node_type=str(node_type or 'note').strip() or 'note',
            label=str(label or '').strip(),
            position_x=float(position_x or 0.0),
            position_y=float(position_y or 0.0),
            width=float(width or 240.0),
            height=float(height or 120.0),
            data=dict(data or {}),
            created_by=str(actor or 'admin'),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_node_upserted',
            'node_id': node['node_id'],
            'node_type': node['node_type'],
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'node': node, 'scope': scope}

    def upsert_edge(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        edge_id: str | None = None,
        source_node_id: str,
        target_node_id: str,
        label: str = '',
        edge_type: str = 'default',
        data: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        self._enforce_canvas_payload(payload={'label': label, 'data': data, 'source_node_id': source_node_id, 'target_node_id': target_node_id})
        if not edge_id:
            self._enforce_canvas_counts(gw, canvas_id=canvas_id, kind='edge', tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        edge = gw.audit.upsert_canvas_edge(
            canvas_id=canvas_id,
            edge_id=edge_id,
            source_node_id=str(source_node_id or ''),
            target_node_id=str(target_node_id or ''),
            label=str(label or ''),
            edge_type=str(edge_type or 'default'),
            data=dict(data or {}),
            created_by=str(actor or 'admin'),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_edge_upserted',
            'edge_id': edge['edge_id'],
            'source_node_id': edge['source_node_id'],
            'target_node_id': edge['target_node_id'],
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'edge': edge, 'scope': scope}

    def save_view(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        name: str,
        view_id: str | None = None,
        layout: dict[str, Any] | None = None,
        filters: dict[str, Any] | None = None,
        is_default: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        self._enforce_canvas_payload(payload={'name': name, 'layout': layout, 'filters': filters})
        if not view_id:
            self._enforce_canvas_counts(gw, canvas_id=canvas_id, kind='view', tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        view = gw.audit.save_canvas_view(
            canvas_id=canvas_id,
            view_id=view_id,
            name=str(name or 'Default').strip() or 'Default',
            layout=dict(layout or {}),
            filters=dict(filters or {}),
            is_default=bool(is_default),
            created_by=str(actor or 'admin'),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_view_saved',
            'view_id': view['view_id'],
            'name': view['name'],
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'view': view, 'scope': scope}

    def update_presence(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        user_key: str,
        cursor_x: float = 0.0,
        cursor_y: float = 0.0,
        selected_node_id: str | None = None,
        status: str = 'active',
        metadata: dict[str, Any] | None = None,
        share_token: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        presence = gw.audit.upsert_canvas_presence(
            canvas_id=canvas_id,
            user_key=str(user_key or actor or 'operator'),
            cursor_x=float(cursor_x or 0.0),
            cursor_y=float(cursor_y or 0.0),
            selected_node_id=selected_node_id,
            status=str(status or 'active'),
            metadata=dict(metadata or {}),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        self._safe_call(
            gw.audit,
            'record_canvas_presence_event',
            None,
            canvas_id=canvas_id,
            user_key=str(user_key or actor or 'operator'),
            event_type='presence_updated',
            payload={
                'cursor_x': float(cursor_x or 0.0),
                'cursor_y': float(cursor_y or 0.0),
                'selected_node_id': selected_node_id,
                'status': str(status or 'active'),
                'metadata': dict(metadata or {}),
            },
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or user_key or 'operator', canvas_id, {
            'action': 'canvas_presence_updated',
            'user_key': user_key,
            'selected_node_id': selected_node_id,
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'presence': presence, 'scope': scope}

    def list_events(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': gw.audit.list_canvas_events(canvas_id=canvas_id, limit=limit, **scope),
            'scope': scope,
        }

    def add_comment(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        body: str,
        node_id: str | None = None,
        status: str = 'active',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        if not str(body or '').strip():
            raise ValueError('comment body is required')
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        comment = self._safe_call(
            gw.audit,
            'create_canvas_comment',
            None,
            canvas_id=canvas_id,
            body=str(body or '').strip(),
            author=str(actor or 'admin'),
            node_id=node_id,
            status=str(status or 'active'),
            metadata=dict(metadata or {}),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_comment_created',
            'comment_id': (comment or {}).get('comment_id'),
            'node_id': node_id,
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'comment': comment, 'scope': scope}

    def list_comments(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': self._safe_call(gw.audit, 'list_canvas_comments', [], canvas_id=canvas_id, limit=limit, status=status, **scope),
            'scope': scope,
        }

    def create_snapshot(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        label: str = '',
        snapshot_kind: str = 'manual',
        view_id: str | None = None,
        selected_node_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        share_token: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        detail = self.get_document(gw, canvas_id=canvas_id, **scope)
        if not detail.get('ok'):
            raise KeyError(canvas_id)
        document = dict(detail.get('document') or {})
        snapshot_payload = {
            'document': document,
            'nodes': list(detail.get('nodes') or []),
            'edges': list(detail.get('edges') or []),
            'views': list(detail.get('views') or []),
            'presence': list(detail.get('presence') or []),
            'comments': list(detail.get('comments') or []),
            'overlay_states': list(detail.get('overlay_states') or []),
            'selected_node_id': selected_node_id,
            'metadata': dict(metadata or {}),
            'summary': {
                'node_count': len(list(detail.get('nodes') or [])),
                'edge_count': len(list(detail.get('edges') or [])),
                'view_count': len(list(detail.get('views') or [])),
                'comment_count': len(list(detail.get('comments') or [])),
                'presence_count': len(list(detail.get('presence') or [])),
            },
        }
        if self._payload_size(snapshot_payload) > self.MAX_SNAPSHOT_BYTES:
            raise ValueError('canvas snapshot exceeds max size')
        snapshot = self._safe_call(
            gw.audit,
            'create_canvas_snapshot',
            None,
            canvas_id=canvas_id,
            snapshot_kind=str(snapshot_kind or 'manual').strip() or 'manual',
            label=str(label or document.get('title') or 'Snapshot').strip() or 'Snapshot',
            snapshot=snapshot_payload,
            metadata=dict(metadata or {}),
            created_by=str(actor or 'admin'),
            view_id=view_id,
            share_token=share_token,
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_snapshot_created',
            'snapshot_id': (snapshot or {}).get('snapshot_id'),
            'snapshot_kind': (snapshot or {}).get('snapshot_kind'),
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'snapshot': snapshot, 'scope': scope}

    def list_snapshots(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        snapshot_kind: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': self._safe_call(gw.audit, 'list_canvas_snapshots', [], canvas_id=canvas_id, limit=limit, snapshot_kind=snapshot_kind, **scope),
            'scope': scope,
        }

    def share_view(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        view_id: str | None = None,
        label: str = '',
        selected_node_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        share_token = uuid.uuid4().hex[:16]
        payload = dict(metadata or {})
        payload['shared'] = True
        payload['share_token'] = share_token
        created = self.create_snapshot(
            gw,
            canvas_id=canvas_id,
            actor=actor,
            label=label or 'Shared view',
            snapshot_kind='shared_view',
            view_id=view_id,
            selected_node_id=selected_node_id,
            metadata=payload,
            share_token=share_token,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        snapshot = dict(created.get('snapshot') or {})
        snapshot['share_token'] = snapshot.get('share_token') or share_token
        return {'ok': True, 'snapshot': snapshot, 'share_token': snapshot['share_token'], 'scope': scope}

    def compare_snapshots(
        self,
        gw: AdminGatewayLike,
        *,
        snapshot_a_id: str,
        snapshot_b_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        snapshot_a = self._safe_call(gw.audit, 'get_canvas_snapshot', None, snapshot_a_id, **scope)
        snapshot_b = self._safe_call(gw.audit, 'get_canvas_snapshot', None, snapshot_b_id, **scope)
        if snapshot_a is None or snapshot_b is None:
            return {'ok': False, 'reason': 'not_found', 'snapshot_a_id': snapshot_a_id, 'snapshot_b_id': snapshot_b_id, 'scope': scope}
        data_a = dict(snapshot_a.get('snapshot') or {})
        data_b = dict(snapshot_b.get('snapshot') or {})
        nodes_a = {str(item.get('node_id') or '') for item in list(data_a.get('nodes') or [])}
        nodes_b = {str(item.get('node_id') or '') for item in list(data_b.get('nodes') or [])}
        edges_a = {str(item.get('edge_id') or '') for item in list(data_a.get('edges') or [])}
        edges_b = {str(item.get('edge_id') or '') for item in list(data_b.get('edges') or [])}
        summary = {
            'node_count_delta': len(nodes_b) - len(nodes_a),
            'edge_count_delta': len(edges_b) - len(edges_a),
            'comment_count_delta': len(list(data_b.get('comments') or [])) - len(list(data_a.get('comments') or [])),
            'presence_count_delta': len(list(data_b.get('presence') or [])) - len(list(data_a.get('presence') or [])),
        }
        diff = {
            'added_node_ids': sorted(nodes_b - nodes_a),
            'removed_node_ids': sorted(nodes_a - nodes_b),
            'added_edge_ids': sorted(edges_b - edges_a),
            'removed_edge_ids': sorted(edges_a - edges_b),
        }
        return {'ok': True, 'snapshot_a': snapshot_a, 'snapshot_b': snapshot_b, 'summary': summary, 'diff': diff, 'scope': scope}

    def list_presence_events(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': self._safe_call(gw.audit, 'list_canvas_presence_events', [], canvas_id=canvas_id, limit=limit, **scope),
            'scope': scope,
        }

    def save_overlay_state(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        state_key: str = 'default',
        toggles: dict[str, Any] | None = None,
        inspector: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        state = gw.audit.upsert_canvas_overlay_state(
            canvas_id=canvas_id,
            state_key=str(state_key or 'default').strip() or 'default',
            toggles=self._normalize_toggles(toggles),
            inspector=dict(inspector or {}),
            created_by=str(actor or 'admin'),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_overlay_state_saved',
            'state_key': state.get('state_key'),
            'toggles': state.get('toggles'),
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'state': state, 'scope': scope}

    def list_overlay_states(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': self._safe_call(gw.audit, 'list_canvas_overlay_states', [], canvas_id=canvas_id, **scope),
            'scope': scope,
        }

    def get_operational_overlays(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        selected_node_id: str | None = None,
        toggles: dict[str, Any] | None = None,
        state_key: str = 'default',
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
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
        normalized_toggles = self._normalize_toggles(toggles)
        nodes = list(detail.get('nodes') or [])
        refs = self._collect_refs(nodes, selected_node_id=selected_node_id)
        fetch_limit = max(int(limit or 50), 1)

        traces_all = self._safe_call(gw.audit, 'list_decision_traces', [], limit=max(fetch_limit * 4, 100), **scope)
        approvals_all = self._safe_call(gw.audit, 'list_approvals', [], limit=max(fetch_limit * 4, 100), **scope)
        events_all = self._safe_call(gw.audit, 'list_events_filtered', [], limit=max(fetch_limit * 6, 150), **scope)
        operator_overview = self.operator_console_service.overview(gw, limit=max(fetch_limit * 2, 50), **scope)
        secret_usage = self.secret_governance_service.usage(gw, limit=max(fetch_limit * 2, 50), **scope)
        secret_catalog = self.secret_governance_service.catalog(gw, limit=max(fetch_limit * 2, 50), **scope)
        cost_summary = self.cost_governance_service.summary(gw, group_by='workflow', limit=max(fetch_limit * 2, 50), **scope)
        cost_budgets = self.cost_governance_service.budgets(gw, limit=max(fetch_limit * 2, 50), **scope)

        traces = [item for item in list(traces_all or []) if self._trace_matches(item, refs)][:fetch_limit]
        approvals = [self._compact_approval(item) for item in list(approvals_all or []) if self._approval_matches(item, refs)][:fetch_limit]
        failures = [item for item in list((operator_overview.get('recent_failures') or [])) if self._failure_matches(item, refs)][:fetch_limit]
        secret_items = [self._sanitize_secret_usage(item) for item in list(secret_usage.get('items') or []) if self._secret_usage_matches(item, refs)][:fetch_limit]
        secret_catalog_items = [self._sanitize_secret_catalog(item) for item in list(secret_catalog.get('items') or []) if self._secret_catalog_matches(item, refs)][:fetch_limit]
        cost_items = [self._compact_cost_item(item) for item in list(cost_summary.get('items') or []) if self._cost_matches(item, refs)][:fetch_limit]
        budget_items = [self._compact_budget_item(item) for item in list(cost_budgets.get('items') or []) if self._budget_matches(item, refs)][:fetch_limit]
        policy_items = self._policy_overlay_items(gw, refs=refs, traces=traces, approvals=approvals, events=list(events_all or []), scope=scope, limit=fetch_limit)

        overlays = {
            'policy': {
                'enabled': normalized_toggles.get('policy', True),
                'items': policy_items if normalized_toggles.get('policy', True) else [],
                'summary': {
                    'policy_hits': len(policy_items),
                    'policy_signature': self._safe_call(getattr(gw, 'policy', None), 'signature', None) if getattr(gw, 'policy', None) is not None else None,
                },
            },
            'cost': {
                'enabled': normalized_toggles.get('cost', True),
                'items': cost_items if normalized_toggles.get('cost', True) else [],
                'budgets': budget_items if normalized_toggles.get('cost', True) else [],
                'summary': {
                    'workflow_groups': len(cost_items),
                    'total_spend': round(
                        sum(float(item.get('total_spend') or 0.0) for item in cost_items)
                        if cost_items
                        else float(((cost_summary.get('summary') or {}).get('total_spend') or 0.0)),
                        6,
                    ),
                    'budget_alerts': sum(1 for item in budget_items if str(item.get('status') or '') in {'warning', 'critical'}),
                },
            },
            'traces': {
                'enabled': normalized_toggles.get('traces', True),
                'items': [self._compact_trace(item) for item in traces] if normalized_toggles.get('traces', True) else [],
                'summary': {
                    'trace_count': len(traces),
                    'average_latency_ms': round((sum(float(item.get('latency_ms') or 0.0) for item in traces) / len(traces)) if traces else 0.0, 3),
                    'estimated_cost': round(sum(float(item.get('estimated_cost') or 0.0) for item in traces), 6),
                },
            },
            'failures': {
                'enabled': normalized_toggles.get('failures', True),
                'items': failures if normalized_toggles.get('failures', True) else [],
                'summary': {
                    'failure_count': len(failures),
                    'by_kind': dict(Counter(str(item.get('kind') or 'unknown') for item in failures)),
                },
            },
            'approvals': {
                'enabled': normalized_toggles.get('approvals', True),
                'items': approvals if normalized_toggles.get('approvals', True) else [],
                'summary': {
                    'approval_count': len(approvals),
                    'pending': sum(1 for item in approvals if str(item.get('status') or '') == 'pending'),
                },
            },
            'secrets': {
                'enabled': normalized_toggles.get('secrets', True),
                'items': secret_items if normalized_toggles.get('secrets', True) else [],
                'catalog': secret_catalog_items if normalized_toggles.get('secrets', True) else [],
                'summary': {
                    'usage_groups': len(secret_items),
                    'catalog_refs': len(secret_catalog_items),
                },
            },
        }
        states = self.list_overlay_states(gw, canvas_id=canvas_id, **scope).get('items', [])
        active_state = next((item for item in states if str(item.get('state_key') or '') == str(state_key or 'default')), None)
        selected_node = next((node for node in nodes if str(node.get('node_id') or '') == str(selected_node_id or '')), None)
        inspector = {
            'selected_node_id': selected_node_id,
            'selected_node': selected_node,
            'references': refs,
            'overlay_state': active_state,
            'node_count': len(nodes),
            'edge_count': len(list(detail.get('edges') or [])),
            'event_count': len(list(detail.get('events') or [])),
        }
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'document': detail.get('document'),
            'selected_node_id': selected_node_id,
            'toggles': normalized_toggles,
            'states': states,
            'state_key': str(state_key or 'default').strip() or 'default',
            'overlays': overlays,
            'inspector': inspector,
            'scope': scope,
        }

    def _runtime_board_entry(
        self,
        gw: AdminGatewayLike,
        *,
        node: dict[str, Any],
        scope: dict[str, Any],
        limit: int = 10,
    ) -> dict[str, Any]:
        data = dict(node.get('data') or {})
        runtime_id = str(data.get('runtime_id') or '').strip()
        runtime_detail = self.openclaw_adapter_service.get_runtime(
            gw,
            runtime_id=runtime_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': False, 'error': 'runtime_not_found'}
        runtime = dict(runtime_detail.get('runtime') or {})
        runtime_summary = dict(runtime_detail.get('runtime_summary') or {})
        health = dict(runtime_detail.get('health') or {})
        dispatches_payload = self.openclaw_adapter_service.list_dispatches(
            gw,
            runtime_id=runtime_id or None,
            limit=max(1, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'canonical_state_counts': {}}}
        dispatches = list(dispatches_payload.get('items') or [])
        canonical_state_counts = dict((dispatches_payload.get('summary') or {}).get('canonical_state_counts') or {})
        active_runs = [
            item for item in dispatches
            if str(item.get('canonical_status') or '').strip().lower() in {'requested', 'accepted', 'queued', 'running'}
        ]
        terminal_runs = [
            item for item in dispatches
            if bool(item.get('terminal')) or str(item.get('canonical_status') or '').strip().lower() in {'completed', 'failed', 'cancelled', 'timed_out'}
        ]
        latest_run = dispatches[0] if dispatches else None
        warnings: list[str] = []
        heartbeat_policy = dict(runtime_summary.get('heartbeat_policy') or {})
        stale_active_runs = [
            item for item in active_runs
            if (time.time() - float(self.openclaw_adapter_service._dispatch_signal_ts(item) or 0.0)) >= float(heartbeat_policy.get('active_run_stale_after_s') or 0.0)
        ] if active_runs else []
        health_status = str(health.get('status') or runtime.get('last_health_status') or 'unknown').strip().lower() or 'unknown'
        if health_status in {'degraded', 'unhealthy'}:
            warnings.append(f'runtime_health:{health_status}')
        if bool(health.get('stale')):
            warnings.append('runtime_health:stale')
        recovery_jobs_payload = self.openclaw_recovery_scheduler_service.list_recovery_jobs(
            gw,
            limit=5,
            enabled=None,
            runtime_id=runtime_id or None,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0, 'due': 0}}
        recovery_jobs = list(recovery_jobs_payload.get('items') or [])
        concurrency_payload = self.openclaw_recovery_scheduler_service.get_runtime_concurrency(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'leases': [], 'idempotency_records': [], 'summary': {}}
        concurrency_summary = dict(concurrency_payload.get('summary') or {})
        alerts_payload = self.openclaw_recovery_scheduler_service.evaluate_runtime_alerts(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {}}
        alerts_summary = dict(alerts_payload.get('summary') or {})
        alert_approvals_payload = self.openclaw_recovery_scheduler_service.list_alert_escalation_approvals(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0, 'status_counts': {}}}
        alert_approvals_summary = dict(alert_approvals_payload.get('summary') or {})
        notification_targets_payload = self.openclaw_recovery_scheduler_service.list_runtime_notification_targets(
            gw,
            runtime_id=runtime_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0}}
        alert_dispatches_payload = self.openclaw_recovery_scheduler_service.list_runtime_alert_notification_dispatches(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0, 'status_counts': {}, 'type_counts': {}}}
        alert_dispatches_summary = dict(alert_dispatches_payload.get('summary') or {})
        routing_payload = self.openclaw_recovery_scheduler_service.get_runtime_alert_routing(
            gw,
            runtime_id=runtime_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'routing_policy': {}, 'summary': {'rule_count': 0, 'escalation_chain_count': 0}}
        governance_payload = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance(
            gw,
            runtime_id=runtime_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            limit=max(10, int(limit)),
        ) if runtime_id else {'ok': True, 'policy': {}, 'current': {}, 'summary': {'suppressed_alert_count': 0, 'scheduled_alert_count': 0, 'active_override_count': 0}}
        governance_versions_payload = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_versions(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'current_version': None, 'summary': {'count': 0, 'current_version_id': None, 'current_version_no': None}}
        governance_promotion_approvals_payload = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_promotion_approvals(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0, 'pending_count': 0, 'approved_count': 0, 'rejected_count': 0}}
        governance_bundles_payload = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_bundles(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0}}
        governance_portfolios_payload = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_portfolios(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0}}
        alert_delivery_jobs_payload = self.openclaw_recovery_scheduler_service.list_alert_delivery_jobs(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0, 'due': 0}}
        alert_delivery_jobs_summary = dict(alert_delivery_jobs_payload.get('summary') or {})
        governance_summary = dict(governance_payload.get('summary') or {})
        governance_current = dict(governance_payload.get('current') or {})
        governance_versions_summary = dict(governance_versions_payload.get('summary') or {})
        governance_promotion_approvals_summary = dict(governance_promotion_approvals_payload.get('summary') or {})
        governance_bundles_summary = dict(governance_bundles_payload.get('summary') or {})
        governance_bundle_items = list(governance_bundles_payload.get('items') or [])
        governance_portfolios_summary = dict(governance_portfolios_payload.get('summary') or {})
        governance_portfolio_items = list(governance_portfolios_payload.get('items') or [])
        governance_bundle_rollout_status_counts: dict[str, int] = {}
        governance_portfolio_rollout_status_counts: dict[str, int] = {}
        governance_bundle_max_exposure_ratio = 0.0
        governance_portfolio_calendar_due_count = 0
        governance_portfolio_pending_approval_count = 0
        governance_portfolio_blocked_count = 0
        governance_portfolio_deferred_count = 0
        governance_portfolio_attested_count = 0
        governance_portfolio_evidence_package_count = 0
        governance_portfolio_notarized_evidence_count = 0
        governance_portfolio_escrowed_evidence_count = 0
        governance_portfolio_crypto_signed_evidence_count = 0
        governance_portfolio_object_lock_evidence_count = 0
        governance_portfolio_external_signing_evidence_count = 0
        governance_portfolio_custody_anchor_count = 0
        governance_portfolio_custody_reconciled_count = 0
        governance_portfolio_custody_reconciliation_conflict_count = 0
        governance_portfolio_custody_quorum_satisfied_count = 0
        governance_portfolio_provider_validation_count = 0
        governance_portfolio_chain_of_custody_count = 0
        governance_portfolio_drifted_count = 0
        governance_portfolio_blocking_drift_count = 0
        governance_portfolio_read_blocked_count = 0
        governance_portfolio_policy_conformance_status_counts: dict[str, int] = {}
        governance_portfolio_policy_conformance_fail_count = 0
        governance_portfolio_policy_conformance_warning_count = 0
        governance_portfolio_policy_baseline_drift_status_counts: dict[str, int] = {}
        governance_portfolio_policy_deviation_exception_count = 0
        governance_portfolio_operational_tier_counts: dict[str, int] = {}
        governance_portfolio_evidence_classification_counts: dict[str, int] = {}
        for _bundle_item in governance_bundle_items:
            _status = str(((_bundle_item.get('summary') or {}).get('rollout_status')) or 'unknown')
            governance_bundle_rollout_status_counts[_status] = governance_bundle_rollout_status_counts.get(_status, 0) + 1
            _analytics = dict(_bundle_item.get('analytics') or {})
            try:
                governance_bundle_max_exposure_ratio = max(governance_bundle_max_exposure_ratio, float(_analytics.get('current_exposure_ratio') or 0.0))
            except Exception:
                pass
        for _portfolio_item in governance_portfolio_items:
            if bool(_portfolio_item.get('read_blocked')):
                governance_portfolio_read_blocked_count += 1
                continue
            _status = str(((_portfolio_item.get('summary') or {}).get('rollout_status')) or 'unknown')
            governance_portfolio_rollout_status_counts[_status] = governance_portfolio_rollout_status_counts.get(_status, 0) + 1
            try:
                governance_portfolio_calendar_due_count += int(((_portfolio_item.get('analytics') or {}).get('calendar_due_count')) or 0)
            except Exception:
                pass
            try:
                governance_portfolio_pending_approval_count += int(((_portfolio_item.get('approval_summary') or {}).get('pending_count')) or 0)
            except Exception:
                pass
            try:
                governance_portfolio_blocked_count += int((((_portfolio_item.get('simulation') or {}).get('summary') or {}).get('blocked_count')) or 0)
            except Exception:
                pass
            try:
                governance_portfolio_deferred_count += int((((_portfolio_item.get('simulation') or {}).get('summary') or {}).get('deferred_count')) or 0)
            except Exception:
                pass
            try:
                governance_portfolio_attested_count += 1 if bool(((_portfolio_item.get('attestation_summary') or {}).get('attested'))) else 0
            except Exception:
                pass
            try:
                governance_portfolio_evidence_package_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_notarized_evidence_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('notarized_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_escrowed_evidence_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('escrowed_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_crypto_signed_evidence_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('crypto_signed_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_object_lock_evidence_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('object_lock_archive_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_external_signing_evidence_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('external_signing_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_custody_anchor_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('custody_anchor_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_custody_reconciled_count += 1 if bool(((_portfolio_item.get('custody_anchor_summary') or {}).get('reconciled'))) else 0
            except Exception:
                pass
            try:
                governance_portfolio_custody_reconciliation_conflict_count += int((((_portfolio_item.get('custody_anchor_summary') or {}).get('reconciliation_conflict_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_custody_quorum_satisfied_count += 1 if bool(((_portfolio_item.get('custody_anchor_summary') or {}).get('quorum_satisfied'))) else 0
            except Exception:
                pass
            try:
                governance_portfolio_provider_validation_count += 1 if bool(((_portfolio_item.get('summary') or {}).get('provider_validation_valid'))) else 0
            except Exception:
                pass
            try:
                _tier = str(((_portfolio_item.get('summary') or {}).get('operational_tier')) or '').strip()
                if _tier:
                    governance_portfolio_operational_tier_counts[_tier] = governance_portfolio_operational_tier_counts.get(_tier, 0) + 1
                _classification = str(((_portfolio_item.get('summary') or {}).get('evidence_classification')) or '').strip()
                if _classification:
                    governance_portfolio_evidence_classification_counts[_classification] = governance_portfolio_evidence_classification_counts.get(_classification, 0) + 1
                _conformance_status = str(((_portfolio_item.get('policy_conformance_summary') or {}).get('overall_status')) or ((_portfolio_item.get('summary') or {}).get('policy_conformance_status')) or '').strip()
                if _conformance_status:
                    governance_portfolio_policy_conformance_status_counts[_conformance_status] = governance_portfolio_policy_conformance_status_counts.get(_conformance_status, 0) + 1
                governance_portfolio_policy_conformance_fail_count += int(((_portfolio_item.get('policy_conformance_summary') or {}).get('fail_count')) or 0)
                governance_portfolio_policy_conformance_warning_count += int(((_portfolio_item.get('policy_conformance_summary') or {}).get('warning_count')) or 0)
                _baseline_drift_status = str(((_portfolio_item.get('policy_baseline_drift_summary') or {}).get('overall_status')) or ((_portfolio_item.get('summary') or {}).get('policy_baseline_drift_status')) or '').strip()
                if _baseline_drift_status:
                    governance_portfolio_policy_baseline_drift_status_counts[_baseline_drift_status] = governance_portfolio_policy_baseline_drift_status_counts.get(_baseline_drift_status, 0) + 1
                governance_portfolio_policy_deviation_exception_count += int(((_portfolio_item.get('deviation_exception_summary') or {}).get('count')) or 0)
            except Exception:
                pass
            try:
                governance_portfolio_chain_of_custody_count += int((((_portfolio_item.get('analytics') or {}).get('chain_of_custody_count')) or 0))
            except Exception:
                pass
            try:
                if str(_portfolio_item.get('drift_status') or '') in {'drift_detected', 'blocking_drift', 'no_attestation'}:
                    governance_portfolio_drifted_count += 1
            except Exception:
                pass
            try:
                governance_portfolio_blocking_drift_count += int((((_portfolio_item.get('drift_summary') or {}).get('blocking_count')) or 0))
            except Exception:
                pass
        event_bridge = dict(runtime_summary.get('event_bridge') or {})
        session_bridge = dict(runtime_summary.get('session_bridge') or {})
        if runtime_summary.get('dispatch_policy', {}).get('dispatch_mode') == 'async' and not bool(event_bridge.get('enabled')):
            warnings.append('event_bridge:disabled_for_async')
        if session_bridge.get('enabled') and not session_bridge.get('workspace_connection'):
            warnings.append('session_bridge:missing_workspace_connection')
        if active_runs and bool(health.get('stale')):
            warnings.append('active_runs:stale_runtime_health')
        if stale_active_runs:
            warnings.append('active_runs:stale_detected')
        if bool(concurrency_summary.get('runtime_lock_active')):
            warnings.append('scheduler:runtime_lock_active')
        if (concurrency_summary.get('workspace_slot_pressure_ratio') or 0) >= 1.0:
            warnings.append('scheduler:workspace_slot_saturated')
        if (concurrency_summary.get('runtime_run_pressure_ratio') or 0) >= 1.0:
            warnings.append('dispatch:runtime_backpressure')
        if (concurrency_summary.get('workspace_run_pressure_ratio') or 0) >= 1.0:
            warnings.append('dispatch:workspace_backpressure')
        if int(concurrency_summary.get('in_progress_idempotency_count') or 0) > 0:
            warnings.append('scheduler:idempotency_in_progress')
        if bool(governance_current.get('quiet_hours_active')):
            warnings.append('alert_governance:quiet_hours')
        if bool(governance_current.get('maintenance_active')):
            warnings.append('alert_governance:maintenance_window')
        if bool(governance_current.get('storm_active')):
            warnings.append('alert_governance:alert_storm')
        return {
            'node_id': node.get('node_id'),
            'label': node.get('label'),
            'node_type': node.get('node_type'),
            'runtime_id': runtime_id,
            'runtime': runtime,
            'runtime_summary': runtime_summary,
            'health': health,
            'latest_run': latest_run,
            'recent_runs': dispatches,
            'active_runs': active_runs,
            'recovery_jobs': recovery_jobs,
            'concurrency': concurrency_payload,
            'alerts': alerts_payload,
            'alert_approvals': alert_approvals_payload,
            'notification_targets': notification_targets_payload,
            'alert_dispatches': alert_dispatches_payload,
            'alert_routing': routing_payload,
            'alert_governance': governance_payload,
            'alert_governance_versions': governance_versions_payload,
            'alert_governance_promotion_approvals': governance_promotion_approvals_payload,
            'alert_governance_bundles': governance_bundles_payload,
            'alert_governance_portfolios': governance_portfolios_payload,
            'alert_governance_bundle_rollout_status_counts': governance_bundle_rollout_status_counts,
            'alert_governance_portfolio_rollout_status_counts': governance_portfolio_rollout_status_counts,
            'alert_delivery_jobs': alert_delivery_jobs_payload,
            'summary': {
                'count': len(dispatches),
                'active_count': len(active_runs),
                'terminal_count': len(terminal_runs),
                'stale_active_count': len(stale_active_runs),
                'canonical_state_counts': canonical_state_counts,
                'warnings': warnings,
                'recovery_jobs_count': int((recovery_jobs_payload.get('summary') or {}).get('count') or 0),
                'recovery_due_count': int((recovery_jobs_payload.get('summary') or {}).get('due') or 0),
                'active_leases': int(concurrency_summary.get('active_leases') or 0),
                'in_progress_idempotency_count': int(concurrency_summary.get('in_progress_idempotency_count') or 0),
                'workspace_slot_pressure_ratio': concurrency_summary.get('workspace_slot_pressure_ratio'),
                'runtime_run_pressure_ratio': concurrency_summary.get('runtime_run_pressure_ratio'),
                'workspace_run_pressure_ratio': concurrency_summary.get('workspace_run_pressure_ratio'),
                'alert_count': int(alerts_summary.get('count') or 0),
                'critical_alert_count': int(alerts_summary.get('critical_count') or 0),
                'warn_alert_count': int(alerts_summary.get('warn_count') or 0),
                'highest_alert_severity': alerts_summary.get('highest_severity'),
                'alert_code_counts': dict(alerts_summary.get('code_counts') or {}),
                'alert_workflow_status_counts': dict(alerts_summary.get('workflow_status_counts') or {}),
                'silenced_alert_count': int(alerts_summary.get('silenced_count') or 0),
                'suppressed_alert_count': int(alerts_summary.get('suppressed_count') or 0),
                'escalated_alert_count': int(alerts_summary.get('escalated_count') or 0),
                'acked_alert_count': int(alerts_summary.get('acked_count') or 0),
                'pending_alert_approval_count': int(alert_approvals_summary.get('pending_count') or 0),
                'approved_alert_approval_count': int(alert_approvals_summary.get('approved_count') or 0),
                'rejected_alert_approval_count': int(alert_approvals_summary.get('rejected_count') or 0),
                'notification_target_count': int((notification_targets_payload.get('summary') or {}).get('count') or 0),
                'alert_dispatch_count': int(alert_dispatches_summary.get('count') or 0),
                'alert_dispatch_status_counts': dict(alert_dispatches_summary.get('status_counts') or {}),
                'alert_dispatch_type_counts': dict(alert_dispatches_summary.get('type_counts') or {}),
                'rate_limited_dispatch_count': int(dict(alert_dispatches_summary.get('status_counts') or {}).get('rate_limited') or 0),
                'routing_rule_count': int((routing_payload.get('summary') or {}).get('rule_count') or 0),
                'escalation_chain_count': int((routing_payload.get('summary') or {}).get('escalation_chain_count') or 0),
                'quiet_hours_active': bool(governance_current.get('quiet_hours_active')),
                'maintenance_active': bool(governance_current.get('maintenance_active')),
                'storm_active': bool(governance_current.get('storm_active')),
                'governance_suppressed_alert_count': int(governance_summary.get('suppressed_alert_count') or 0),
                'governance_scheduled_alert_count': int(governance_summary.get('scheduled_alert_count') or 0),
                'active_override_count': int(governance_summary.get('active_override_count') or 0),
                'governance_version_count': int(governance_versions_summary.get('count') or 0),
                'pending_governance_promotion_approval_count': int(governance_promotion_approvals_summary.get('pending_count') or 0),
                'governance_bundle_count': int(governance_bundles_summary.get('count') or 0),
                'governance_bundle_rollout_status_counts': governance_bundle_rollout_status_counts,
                'governance_bundle_max_exposure_ratio': round(governance_bundle_max_exposure_ratio, 4),
                'governance_portfolio_count': int(governance_portfolios_summary.get('count') or 0),
                'governance_portfolio_rollout_status_counts': governance_portfolio_rollout_status_counts,
                'governance_portfolio_calendar_due_count': governance_portfolio_calendar_due_count,
                'pending_governance_portfolio_approval_count': governance_portfolio_pending_approval_count,
                'governance_portfolio_blocked_count': governance_portfolio_blocked_count,
                'governance_portfolio_deferred_count': governance_portfolio_deferred_count,
                'governance_portfolio_attested_count': governance_portfolio_attested_count,
                'governance_portfolio_evidence_package_count': governance_portfolio_evidence_package_count,
                'governance_portfolio_notarized_evidence_count': governance_portfolio_notarized_evidence_count,
                'governance_portfolio_escrowed_evidence_count': governance_portfolio_escrowed_evidence_count,
                'governance_portfolio_crypto_signed_evidence_count': governance_portfolio_crypto_signed_evidence_count,
                'governance_portfolio_object_lock_evidence_count': governance_portfolio_object_lock_evidence_count,
                'governance_portfolio_external_signing_evidence_count': governance_portfolio_external_signing_evidence_count,
                'governance_portfolio_custody_anchor_count': governance_portfolio_custody_anchor_count,
                'governance_portfolio_custody_reconciled_count': governance_portfolio_custody_reconciled_count,
                'governance_portfolio_custody_reconciliation_conflict_count': governance_portfolio_custody_reconciliation_conflict_count,
                'governance_portfolio_custody_quorum_satisfied_count': governance_portfolio_custody_quorum_satisfied_count,
                'governance_portfolio_provider_validation_count': governance_portfolio_provider_validation_count,
                'governance_portfolio_chain_of_custody_count': governance_portfolio_chain_of_custody_count,
                'governance_portfolio_drifted_count': governance_portfolio_drifted_count,
                'governance_portfolio_blocking_drift_count': governance_portfolio_blocking_drift_count,
                'governance_portfolio_read_blocked_count': governance_portfolio_read_blocked_count,
                'governance_portfolio_policy_conformance_status_counts': governance_portfolio_policy_conformance_status_counts,
                'governance_portfolio_policy_conformance_fail_count': governance_portfolio_policy_conformance_fail_count,
                'governance_portfolio_policy_conformance_warning_count': governance_portfolio_policy_conformance_warning_count,
                'governance_portfolio_policy_baseline_drift_status_counts': governance_portfolio_policy_baseline_drift_status_counts,
                'governance_portfolio_policy_deviation_exception_count': governance_portfolio_policy_deviation_exception_count,
                'governance_portfolio_operational_tier_counts': governance_portfolio_operational_tier_counts,
                'governance_portfolio_evidence_classification_counts': governance_portfolio_evidence_classification_counts,
                'governance_current_version_id': governance_versions_summary.get('current_version_id'),
                'governance_current_version_no': governance_versions_summary.get('current_version_no'),
                'alert_delivery_job_count': int(alert_delivery_jobs_summary.get('count') or 0),
                'alert_delivery_due_count': int(alert_delivery_jobs_summary.get('due') or 0),
                'available_operations': ['cancel_run', 'retry_run', 'manual_close', 'reconcile_run', 'poll_run', 'recover_stale_runs', 'ack_alert', 'silence_alert', 'escalate_alert', 'dispatch_alert_notification', 'approve_alert_escalation', 'reject_alert_escalation', 'simulate_alert_governance', 'activate_alert_governance', 'rollback_alert_governance', 'approve_governance_promotion', 'reject_governance_promotion', 'simulate_portfolio_calendar', 'detect_portfolio_drift', 'report_portfolio_policy_conformance', 'report_portfolio_policy_baseline_drift', 'reconcile_portfolio_custody_anchors', 'validate_portfolio_providers', 'attest_portfolio_custody_anchor', 'request_portfolio_policy_deviation_exception', 'approve_portfolio_policy_deviation_exception', 'reject_portfolio_policy_deviation_exception', 'request_portfolio_approval', 'approve_portfolio_approval', 'reject_portfolio_approval', 'export_portfolio_attestation', 'export_portfolio_postmortem', 'export_portfolio_evidence_package', 'verify_portfolio_evidence_artifact', 'restore_portfolio_evidence_artifact', 'prune_portfolio_evidence_packages'],
            },
        }

    def get_runtime_board(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 10,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
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
        runtime_nodes = [
            node for node in list(detail.get('nodes') or [])
            if str(node.get('node_type') or '').strip().lower() in {'runtime', 'openclaw_runtime'}
        ]
        items = [
            self._runtime_board_entry(gw, node=node, scope=scope, limit=limit)
            for node in runtime_nodes
        ]
        async_runtime_count = 0
        stale_runtime_count = 0
        unhealthy_runtime_count = 0
        total_active_runs = 0
        total_terminal_runs = 0
        active_leases = 0
        in_progress_idempotency = 0
        saturated_runtime_count = 0
        saturated_workspace_count = 0
        runtime_locked_count = 0
        alert_count = 0
        critical_alert_count = 0
        warn_alert_count = 0
        silenced_alert_count = 0
        suppressed_alert_count = 0
        escalated_alert_count = 0
        acked_alert_count = 0
        alert_code_counts: dict[str, int] = {}
        alert_workflow_status_counts: dict[str, int] = {}
        canonical_state_counts: dict[str, int] = {}
        alert_dispatch_count = 0
        alert_dispatch_status_counts: dict[str, int] = {}
        alert_dispatch_type_counts: dict[str, int] = {}
        notification_target_count = 0
        pending_alert_approval_count = 0
        alert_delivery_job_count = 0
        alert_delivery_due_count = 0
        routing_rule_count = 0
        escalation_chain_count = 0
        quiet_hours_active_count = 0
        maintenance_active_count = 0
        storm_active_count = 0
        governance_suppressed_alert_count = 0
        governance_scheduled_alert_count = 0
        active_override_count = 0
        for item in items:
            dispatch_policy = dict((item.get('runtime_summary') or {}).get('dispatch_policy') or {})
            if str(dispatch_policy.get('dispatch_mode') or '').strip().lower() == 'async':
                async_runtime_count += 1
            health = dict(item.get('health') or {})
            if bool(health.get('stale')):
                stale_runtime_count += 1
            if str(health.get('status') or '').strip().lower() in {'degraded', 'unhealthy'}:
                unhealthy_runtime_count += 1
            summary = dict(item.get('summary') or {})
            total_active_runs += int(summary.get('active_count') or 0)
            total_terminal_runs += int(summary.get('terminal_count') or 0)
            active_leases += int(summary.get('active_leases') or 0)
            in_progress_idempotency += int(summary.get('in_progress_idempotency_count') or 0)
            if (summary.get('runtime_run_pressure_ratio') or 0) >= 1.0:
                saturated_runtime_count += 1
            if (summary.get('workspace_slot_pressure_ratio') or 0) >= 1.0 or (summary.get('workspace_run_pressure_ratio') or 0) >= 1.0:
                saturated_workspace_count += 1
            if 'scheduler:runtime_lock_active' in list(summary.get('warnings') or []):
                runtime_locked_count += 1
            alert_count += int(summary.get('alert_count') or 0)
            critical_alert_count += int(summary.get('critical_alert_count') or 0)
            warn_alert_count += int(summary.get('warn_alert_count') or 0)
            silenced_alert_count += int(summary.get('silenced_alert_count') or 0)
            suppressed_alert_count += int(summary.get('suppressed_alert_count') or 0)
            escalated_alert_count += int(summary.get('escalated_alert_count') or 0)
            acked_alert_count += int(summary.get('acked_alert_count') or 0)
            for key, value in dict(summary.get('alert_code_counts') or {}).items():
                alert_code_counts[str(key)] = alert_code_counts.get(str(key), 0) + int(value or 0)
            for key, value in dict(summary.get('alert_workflow_status_counts') or {}).items():
                alert_workflow_status_counts[str(key)] = alert_workflow_status_counts.get(str(key), 0) + int(value or 0)
            notification_target_count += int(summary.get('notification_target_count') or 0)
            pending_alert_approval_count += int(summary.get('pending_alert_approval_count') or 0)
            alert_delivery_job_count += int(summary.get('alert_delivery_job_count') or 0)
            alert_delivery_due_count += int(summary.get('alert_delivery_due_count') or 0)
            routing_rule_count += int(summary.get('routing_rule_count') or 0)
            escalation_chain_count += int(summary.get('escalation_chain_count') or 0)
            quiet_hours_active_count += 1 if bool(summary.get('quiet_hours_active')) else 0
            maintenance_active_count += 1 if bool(summary.get('maintenance_active')) else 0
            storm_active_count += 1 if bool(summary.get('storm_active')) else 0
            governance_suppressed_alert_count += int(summary.get('governance_suppressed_alert_count') or 0)
            governance_scheduled_alert_count += int(summary.get('governance_scheduled_alert_count') or 0)
            active_override_count += int(summary.get('active_override_count') or 0)
            alert_dispatch_count += int(summary.get('alert_dispatch_count') or 0)
            for key, value in dict(summary.get('alert_dispatch_status_counts') or {}).items():
                alert_dispatch_status_counts[str(key)] = alert_dispatch_status_counts.get(str(key), 0) + int(value or 0)
            for key, value in dict(summary.get('alert_dispatch_type_counts') or {}).items():
                alert_dispatch_type_counts[str(key)] = alert_dispatch_type_counts.get(str(key), 0) + int(value or 0)
            for key, value in dict(summary.get('canonical_state_counts') or {}).items():
                canonical_state_counts[str(key)] = canonical_state_counts.get(str(key), 0) + int(value or 0)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': items,
            'summary': {
                'runtime_count': len(items),
                'async_runtime_count': async_runtime_count,
                'stale_runtime_count': stale_runtime_count,
                'unhealthy_runtime_count': unhealthy_runtime_count,
                'total_active_runs': total_active_runs,
                'total_terminal_runs': total_terminal_runs,
                'stale_active_runs': sum(int((item.get('summary') or {}).get('stale_active_count') or 0) for item in items),
                'active_leases': active_leases,
                'in_progress_idempotency_count': in_progress_idempotency,
                'runtime_locked_count': runtime_locked_count,
                'saturated_runtime_count': saturated_runtime_count,
                'saturated_workspace_count': saturated_workspace_count,
                'alert_count': alert_count,
                'critical_alert_count': critical_alert_count,
                'warn_alert_count': warn_alert_count,
                'silenced_alert_count': silenced_alert_count,
                'suppressed_alert_count': suppressed_alert_count,
                'escalated_alert_count': escalated_alert_count,
                'acked_alert_count': acked_alert_count,
                'notification_target_count': notification_target_count,
                'routing_rule_count': routing_rule_count,
                'escalation_chain_count': escalation_chain_count,
                'quiet_hours_active_count': quiet_hours_active_count,
                'maintenance_active_count': maintenance_active_count,
                'storm_active_count': storm_active_count,
                'governance_suppressed_alert_count': governance_suppressed_alert_count,
                'governance_scheduled_alert_count': governance_scheduled_alert_count,
                'active_override_count': active_override_count,
                'alert_delivery_job_count': alert_delivery_job_count,
                'alert_delivery_due_count': alert_delivery_due_count,
                'alert_dispatch_count': alert_dispatch_count,
                'alert_dispatch_status_counts': alert_dispatch_status_counts,
                'alert_dispatch_type_counts': alert_dispatch_type_counts,
                'alert_code_counts': alert_code_counts,
                'alert_workflow_status_counts': alert_workflow_status_counts,
                'canonical_state_counts': canonical_state_counts,
            },
            'scope': scope,
        }

    def _baseline_promotion_board_entry(
        self,
        gw: AdminGatewayLike,
        *,
        node: dict[str, Any],
        scope: dict[str, Any],
        limit: int = 10,
    ) -> dict[str, Any]:
        data = dict(node.get('data') or {})
        promotion_id = str(data.get('promotion_id') or node.get('label') or '').strip()
        detail = {'ok': False, 'error': 'baseline_promotion_not_found', 'promotion_id': promotion_id}
        if promotion_id:
            detail = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_baseline_promotion(
                gw,
                promotion_id=promotion_id,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        if not detail.get('ok'):
            return {
                'node_id': node.get('node_id'),
                'node_label': node.get('label'),
                'promotion_id': promotion_id,
                'status': 'unknown',
                'error': detail.get('error') or 'baseline_promotion_not_found',
                'summary': {'wave_count': 0, 'completed_wave_count': 0, 'due_advance_job_count': 0, 'rollback_attestation_count': 0},
            }
        release = dict(detail.get('release') or {})
        promotion = dict(detail.get('baseline_promotion') or {})
        analytics = dict(detail.get('analytics') or {})
        advance_jobs = dict(detail.get('advance_jobs') or {})
        rollback_attestations = dict(detail.get('rollback_attestations') or {})
        custody_alerts_summary = dict((((detail.get('simulation_custody_monitoring') or {}).get('alerts')) or {}).get('summary') or {})
        return {
            'node_id': node.get('node_id'),
            'node_label': node.get('label'),
            'promotion_id': promotion_id,
            'status': str(release.get('status') or ''),
            'catalog_id': str(promotion.get('catalog_id') or ''),
            'catalog_name': str(promotion.get('catalog_name') or ''),
            'candidate_catalog_version': str(promotion.get('candidate_catalog_version') or release.get('version') or ''),
            'previous_catalog_version': str(promotion.get('previous_catalog_version') or ''),
            'summary': {
                'wave_count': int(analytics.get('wave_count') or 0),
                'completed_wave_count': int(analytics.get('completed_wave_count') or 0),
                'pending_portfolio_count': int(analytics.get('pending_portfolio_count') or 0),
                'due_advance_job_count': int((advance_jobs.get('summary') or {}).get('due') or 0),
                'scheduled_advance_job_count': int((advance_jobs.get('summary') or {}).get('count') or 0),
                'rollback_attestation_count': int((rollback_attestations.get('summary') or {}).get('count') or 0),
                'gate_failed': bool(analytics.get('gate_failed')),
                'paused': bool((promotion.get('pause_state') or {}).get('paused')),
                'custody_guard_blocked': bool((((detail.get('simulation_custody_monitoring') or {}).get('guard')) or {}).get('blocked')),
                'custody_drifted_count': int(((((detail.get('simulation_evidence_reconciliation') or {}).get('current') or {}).get('summary')) or {}).get('drifted_count') or 0),
                'custody_active_alert_count': int(custody_alerts_summary.get('active_count') or 0),
                'custody_acknowledged_alert_count': int(custody_alerts_summary.get('acknowledged_count') or 0),
                'custody_muted_alert_count': int(custody_alerts_summary.get('muted_count') or 0),
                'custody_escalated_alert_count': int(custody_alerts_summary.get('active_escalated_count') or custody_alerts_summary.get('escalated_count') or 0),
                'custody_suppressed_alert_count': int(custody_alerts_summary.get('active_suppressed_count') or custody_alerts_summary.get('suppressed_count') or 0),
                'custody_owned_alert_count': int(custody_alerts_summary.get('active_owned_count') or custody_alerts_summary.get('owned_count') or 0),
                'custody_claimed_alert_count': int(custody_alerts_summary.get('active_claimed_count') or custody_alerts_summary.get('claimed_count') or 0),
                'custody_unowned_alert_count': int(custody_alerts_summary.get('active_unowned_count') or custody_alerts_summary.get('unassigned_count') or 0),
                'custody_routed_alert_count': int(custody_alerts_summary.get('routed_count') or 0),
                'custody_handoff_pending_alert_count': int(custody_alerts_summary.get('active_handoff_pending_count') or custody_alerts_summary.get('pending_handoff_count') or 0),
                'custody_sla_breached_alert_count': int(custody_alerts_summary.get('active_sla_breached_count') or custody_alerts_summary.get('sla_breached_count') or 0),
                'custody_sla_rerouted_alert_count': int(custody_alerts_summary.get('active_sla_rerouted_count') or custody_alerts_summary.get('sla_rerouted_count') or 0),
                'custody_team_queue_alert_count': int(custody_alerts_summary.get('active_team_queue_alert_count') or custody_alerts_summary.get('team_queue_alert_count') or 0),
                'custody_queue_at_capacity_alert_count': int(custody_alerts_summary.get('active_queue_at_capacity_count') or custody_alerts_summary.get('queue_at_capacity_count') or 0),
                'custody_load_aware_routed_alert_count': int(custody_alerts_summary.get('active_load_aware_routed_count') or custody_alerts_summary.get('load_aware_routed_count') or 0),
                'custody_reservation_protected_alert_count': int(custody_alerts_summary.get('active_reservation_protected_alert_count') or custody_alerts_summary.get('reservation_protected_alert_count') or 0),
                'custody_lease_protected_alert_count': int(custody_alerts_summary.get('active_lease_protected_alert_count') or custody_alerts_summary.get('lease_protected_alert_count') or 0),
                'custody_temporary_hold_protected_alert_count': int(custody_alerts_summary.get('active_temporary_hold_protected_alert_count') or custody_alerts_summary.get('temporary_hold_protected_alert_count') or 0),
                'custody_anti_thrashing_kept_alert_count': int(custody_alerts_summary.get('active_anti_thrashing_kept_alert_count') or custody_alerts_summary.get('anti_thrashing_kept_alert_count') or 0),
                'custody_queue_family_alert_count': int(custody_alerts_summary.get('active_queue_family_alert_count') or custody_alerts_summary.get('queue_family_alert_count') or 0),
                'custody_family_hysteresis_kept_alert_count': int(custody_alerts_summary.get('active_family_hysteresis_kept_alert_count') or custody_alerts_summary.get('family_hysteresis_kept_alert_count') or 0),
                'custody_aging_alert_count': int(custody_alerts_summary.get('active_aging_alert_count') or custody_alerts_summary.get('aging_alert_count') or 0),
                'custody_starving_alert_count': int(custody_alerts_summary.get('active_starving_alert_count') or custody_alerts_summary.get('starving_alert_count') or 0),
                'custody_starvation_prevented_alert_count': int(custody_alerts_summary.get('active_starvation_prevented_alert_count') or custody_alerts_summary.get('starvation_prevented_alert_count') or 0),
                'custody_alerts_at_risk_count': int(custody_alerts_summary.get('active_alerts_at_risk_count') or custody_alerts_summary.get('alerts_at_risk_count') or 0),
                'custody_predicted_sla_breach_count': int(custody_alerts_summary.get('active_predicted_sla_breach_count') or custody_alerts_summary.get('predicted_sla_breach_count') or 0),
                'custody_expedite_routed_alert_count': int(custody_alerts_summary.get('active_expedite_routed_alert_count') or custody_alerts_summary.get('expedite_routed_alert_count') or 0),
                'custody_proactive_routed_alert_count': int(custody_alerts_summary.get('active_proactive_routed_alert_count') or custody_alerts_summary.get('proactive_routed_alert_count') or 0),
                'custody_forecasted_surge_alert_count': int(custody_alerts_summary.get('active_forecasted_surge_alert_count') or custody_alerts_summary.get('forecasted_surge_alert_count') or 0),
                'custody_overload_governed_alert_count': int(custody_alerts_summary.get('active_overload_governed_alert_count') or custody_alerts_summary.get('overload_governed_alert_count') or 0),
                'custody_overload_blocked_alert_count': int(custody_alerts_summary.get('active_overload_blocked_alert_count') or custody_alerts_summary.get('overload_blocked_alert_count') or 0),
                'custody_admission_deferred_alert_count': int(custody_alerts_summary.get('active_admission_deferred_alert_count') or custody_alerts_summary.get('admission_deferred_alert_count') or 0),
                'custody_manual_gate_alert_count': int(custody_alerts_summary.get('active_manual_gate_alert_count') or custody_alerts_summary.get('manual_gate_alert_count') or 0),
            },
            'latest_health': analytics.get('latest_health'),
            'rollback_attestations': rollback_attestations,
            'advance_jobs': advance_jobs,
            'baseline_promotion': detail,
        }

    def get_baseline_promotion_board(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 10,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
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
        promotion_nodes = [
            node for node in list(detail.get('nodes') or [])
            if str(node.get('node_type') or '').strip().lower() in {'baseline_promotion', 'policy_baseline_promotion'}
        ]
        items = [
            self._baseline_promotion_board_entry(gw, node=node, scope=scope, limit=limit)
            for node in promotion_nodes
        ]
        status_counts: dict[str, int] = {}
        due_advance_job_count = 0
        rollback_attestation_count = 0
        paused_count = 0
        gate_failed_count = 0
        awaiting_advance_count = 0
        custody_guard_blocked_count = 0
        custody_active_alert_count = 0
        custody_acknowledged_alert_count = 0
        custody_muted_alert_count = 0
        custody_escalated_alert_count = 0
        custody_suppressed_alert_count = 0
        custody_owned_alert_count = 0
        custody_claimed_alert_count = 0
        custody_unowned_alert_count = 0
        custody_routed_alert_count = 0
        custody_handoff_pending_alert_count = 0
        custody_sla_breached_alert_count = 0
        custody_sla_rerouted_alert_count = 0
        custody_team_queue_alert_count = 0
        custody_queue_at_capacity_alert_count = 0
        custody_load_aware_routed_alert_count = 0
        custody_reservation_protected_alert_count = 0
        custody_lease_protected_alert_count = 0
        custody_temporary_hold_protected_alert_count = 0
        custody_anti_thrashing_kept_alert_count = 0
        custody_queue_family_alert_count = 0
        custody_family_hysteresis_kept_alert_count = 0
        custody_aging_alert_count = 0
        custody_starving_alert_count = 0
        custody_starvation_prevented_alert_count = 0
        custody_alerts_at_risk_count = 0
        custody_predicted_sla_breach_count = 0
        custody_expedite_routed_alert_count = 0
        custody_proactive_routed_alert_count = 0
        custody_forecasted_surge_alert_count = 0
        custody_overload_governed_alert_count = 0
        custody_overload_blocked_alert_count = 0
        custody_admission_deferred_alert_count = 0
        custody_manual_gate_alert_count = 0
        for item in items:
            status = str(item.get('status') or 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
            summary = dict(item.get('summary') or {})
            due_advance_job_count += int(summary.get('due_advance_job_count') or 0)
            rollback_attestation_count += int(summary.get('rollback_attestation_count') or 0)
            paused_count += 1 if bool(summary.get('paused')) else 0
            gate_failed_count += 1 if bool(summary.get('gate_failed')) else 0
            awaiting_advance_count += 1 if status in {'awaiting_advance', 'awaiting_advance_window', 'awaiting_dependencies'} else 0
            custody_guard_blocked_count += 1 if bool(summary.get('custody_guard_blocked')) else 0
            custody_active_alert_count += int(summary.get('custody_active_alert_count') or 0)
            custody_acknowledged_alert_count += int(summary.get('custody_acknowledged_alert_count') or 0)
            custody_muted_alert_count += int(summary.get('custody_muted_alert_count') or 0)
            custody_escalated_alert_count += int(summary.get('custody_escalated_alert_count') or 0)
            custody_suppressed_alert_count += int(summary.get('custody_suppressed_alert_count') or 0)
            custody_owned_alert_count += int(summary.get('custody_owned_alert_count') or 0)
            custody_claimed_alert_count += int(summary.get('custody_claimed_alert_count') or 0)
            custody_unowned_alert_count += int(summary.get('custody_unowned_alert_count') or 0)
            custody_routed_alert_count += int(summary.get('custody_routed_alert_count') or 0)
            custody_handoff_pending_alert_count += int(summary.get('custody_handoff_pending_alert_count') or 0)
            custody_sla_breached_alert_count += int(summary.get('custody_sla_breached_alert_count') or 0)
            custody_sla_rerouted_alert_count += int(summary.get('custody_sla_rerouted_alert_count') or 0)
            custody_team_queue_alert_count += int(summary.get('custody_team_queue_alert_count') or 0)
            custody_queue_at_capacity_alert_count += int(summary.get('custody_queue_at_capacity_alert_count') or 0)
            custody_load_aware_routed_alert_count += int(summary.get('custody_load_aware_routed_alert_count') or 0)
            custody_reservation_protected_alert_count += int(summary.get('custody_reservation_protected_alert_count') or 0)
            custody_lease_protected_alert_count += int(summary.get('custody_lease_protected_alert_count') or 0)
            custody_temporary_hold_protected_alert_count += int(summary.get('custody_temporary_hold_protected_alert_count') or 0)
            custody_anti_thrashing_kept_alert_count += int(summary.get('custody_anti_thrashing_kept_alert_count') or 0)
            custody_queue_family_alert_count += int(summary.get('custody_queue_family_alert_count') or 0)
            custody_family_hysteresis_kept_alert_count += int(summary.get('custody_family_hysteresis_kept_alert_count') or 0)
            custody_aging_alert_count += int(summary.get('custody_aging_alert_count') or 0)
            custody_starving_alert_count += int(summary.get('custody_starving_alert_count') or 0)
            custody_starvation_prevented_alert_count += int(summary.get('custody_starvation_prevented_alert_count') or 0)
            custody_alerts_at_risk_count += int(summary.get('custody_alerts_at_risk_count') or 0)
            custody_predicted_sla_breach_count += int(summary.get('custody_predicted_sla_breach_count') or 0)
            custody_expedite_routed_alert_count += int(summary.get('custody_expedite_routed_alert_count') or 0)
            custody_proactive_routed_alert_count += int(summary.get('custody_proactive_routed_alert_count') or 0)
            custody_forecasted_surge_alert_count += int(summary.get('custody_forecasted_surge_alert_count') or 0)
            custody_overload_governed_alert_count += int(summary.get('custody_overload_governed_alert_count') or 0)
            custody_overload_blocked_alert_count += int(summary.get('custody_overload_blocked_alert_count') or 0)
            custody_admission_deferred_alert_count += int(summary.get('custody_admission_deferred_alert_count') or 0)
            custody_manual_gate_alert_count += int(summary.get('custody_manual_gate_alert_count') or 0)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': items,
            'summary': {
                'promotion_count': len(items),
                'status_counts': status_counts,
                'due_advance_job_count': due_advance_job_count,
                'rollback_attestation_count': rollback_attestation_count,
                'paused_count': paused_count,
                'gate_failed_count': gate_failed_count,
                'awaiting_advance_count': awaiting_advance_count,
                'custody_guard_blocked_count': custody_guard_blocked_count,
                'custody_active_alert_count': custody_active_alert_count,
                'custody_acknowledged_alert_count': custody_acknowledged_alert_count,
                'custody_muted_alert_count': custody_muted_alert_count,
                'custody_escalated_alert_count': custody_escalated_alert_count,
                'custody_suppressed_alert_count': custody_suppressed_alert_count,
                'custody_owned_alert_count': custody_owned_alert_count,
                'custody_claimed_alert_count': custody_claimed_alert_count,
                'custody_unowned_alert_count': custody_unowned_alert_count,
                'custody_routed_alert_count': custody_routed_alert_count,
                'custody_handoff_pending_alert_count': custody_handoff_pending_alert_count,
                'custody_sla_breached_alert_count': custody_sla_breached_alert_count,
                'custody_sla_rerouted_alert_count': custody_sla_rerouted_alert_count,
                'custody_team_queue_alert_count': custody_team_queue_alert_count,
                'custody_queue_at_capacity_alert_count': custody_queue_at_capacity_alert_count,
                'custody_load_aware_routed_alert_count': custody_load_aware_routed_alert_count,
                'custody_reservation_protected_alert_count': custody_reservation_protected_alert_count,
                'custody_lease_protected_alert_count': custody_lease_protected_alert_count,
                'custody_temporary_hold_protected_alert_count': custody_temporary_hold_protected_alert_count,
                'custody_anti_thrashing_kept_alert_count': custody_anti_thrashing_kept_alert_count,
                'custody_queue_family_alert_count': custody_queue_family_alert_count,
                'custody_family_hysteresis_kept_alert_count': custody_family_hysteresis_kept_alert_count,
                'custody_aging_alert_count': custody_aging_alert_count,
                'custody_starving_alert_count': custody_starving_alert_count,
                'custody_starvation_prevented_alert_count': custody_starvation_prevented_alert_count,
                'custody_alerts_at_risk_count': custody_alerts_at_risk_count,
                'custody_predicted_sla_breach_count': custody_predicted_sla_breach_count,
                'custody_expedite_routed_alert_count': custody_expedite_routed_alert_count,
                'custody_proactive_routed_alert_count': custody_proactive_routed_alert_count,
                'custody_forecasted_surge_alert_count': custody_forecasted_surge_alert_count,
                'custody_overload_governed_alert_count': custody_overload_governed_alert_count,
                'custody_overload_blocked_alert_count': custody_overload_blocked_alert_count,
                'custody_admission_deferred_alert_count': custody_admission_deferred_alert_count,
                'custody_manual_gate_alert_count': custody_manual_gate_alert_count,
            },
            'scope': scope,
        }

    def list_operational_views(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
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
        saved_views = list(detail.get('views') or [])
        by_kind = Counter(str(node.get('node_type') or 'note').strip().lower() or 'note' for node in nodes)
        runtime_board = self.get_runtime_board(
            gw,
            canvas_id=canvas_id,
            limit=5,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if by_kind.get('runtime') or by_kind.get('openclaw_runtime') else {'ok': True, 'items': [], 'summary': {}}
        runtime_summary = dict(runtime_board.get('summary') or {})
        baseline_promotion_board = self.get_baseline_promotion_board(
            gw,
            canvas_id=canvas_id,
            limit=5,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if by_kind.get('baseline_promotion') or by_kind.get('policy_baseline_promotion') else {'ok': True, 'items': [], 'summary': {}}
        baseline_promotion_summary = dict(baseline_promotion_board.get('summary') or {})
        suggestions: list[dict[str, Any]] = [
            {
                'view_key': 'overview',
                'name': 'Overview',
                'kind': 'overview',
                'description': 'Vista operacional general del canvas.',
                'filters': {'node_types': sorted(k for k, v in by_kind.items() if v)},
                'toggles': dict(self._DEFAULT_TOGGLES),
                'layout': {'fit': 'all', 'focus': 'document'},
            }
        ]
        if by_kind.get('workflow') or by_kind.get('approval'):
            suggestions.append({
                'view_key': 'workflow-control',
                'name': 'Workflow control',
                'kind': 'workflow',
                'description': 'Foco en workflows, aprobaciones y fallos.',
                'filters': {'node_types': [item for item in ('workflow', 'approval') if by_kind.get(item)]},
                'toggles': {'policy': True, 'cost': False, 'traces': True, 'failures': True, 'approvals': True, 'secrets': False},
                'layout': {'fit': 'filtered', 'focus': 'workflow'},
            })
        if by_kind.get('runtime') or by_kind.get('openclaw_runtime'):
            suggestions.append({
                'view_key': 'runtime-ops',
                'name': 'Runtime ops',
                'kind': 'runtime',
                'description': 'MonitorizaciÃ³n y acciones sobre runtimes externos.',
                'filters': {'node_types': [item for item in ('runtime', 'openclaw_runtime') if by_kind.get(item)]},
                'toggles': {'policy': False, 'cost': False, 'traces': True, 'failures': True, 'approvals': False, 'secrets': True},
                'layout': {'fit': 'filtered', 'focus': 'runtime'},
                'summary': runtime_summary,
            })
            if int(runtime_summary.get('async_runtime_count') or 0) > 0 or int(runtime_summary.get('total_active_runs') or 0) > 0:
                suggestions.append({
                    'view_key': 'async-governed-runs',
                    'name': 'Async governed runs',
                    'kind': 'runtime_async',
                    'description': 'Seguimiento de runs asÃ­ncronos, estados canÃ³nicos y alertas por runtime.',
                    'filters': {'node_types': [item for item in ('runtime', 'openclaw_runtime') if by_kind.get(item)]},
                    'toggles': {'policy': False, 'cost': False, 'traces': True, 'failures': True, 'approvals': False, 'secrets': False},
                    'layout': {'fit': 'filtered', 'focus': 'runtime_async'},
                    'summary': runtime_summary,
                })
        if by_kind.get('baseline_promotion') or by_kind.get('policy_baseline_promotion'):
            suggestions.append({
                'view_key': 'baseline-rollouts',
                'name': 'Baseline rollouts',
                'kind': 'baseline_promotion',
                'description': 'Seguimiento de promociones de baseline, waves, gates y rollbacks.',
                'filters': {'node_types': [item for item in ('baseline_promotion', 'policy_baseline_promotion') if by_kind.get(item)]},
                'toggles': {'policy': True, 'cost': False, 'traces': True, 'failures': True, 'approvals': True, 'secrets': False},
                'layout': {'fit': 'filtered', 'focus': 'baseline_promotion'},
                'summary': baseline_promotion_summary,
            })
        if by_kind.get('tool') or by_kind.get('policy'):
            suggestions.append({
                'view_key': 'risk-hotspots',
                'name': 'Risk hotspots',
                'kind': 'risk',
                'description': 'Herramientas, polÃ­ticas y secretos mÃ¡s sensibles.',
                'filters': {'node_types': [item for item in ('tool', 'policy') if by_kind.get(item)]},
                'toggles': {'policy': True, 'cost': False, 'traces': True, 'failures': True, 'approvals': False, 'secrets': True},
                'layout': {'fit': 'filtered', 'focus': 'risk'},
            })
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'saved_views': saved_views,
            'suggested_views': suggestions,
            'summary': {
                'saved_count': len(saved_views),
                'suggested_count': len(suggestions),
                'node_types': dict(by_kind),
                'runtime_board': runtime_summary,
                'baseline_promotion_board': baseline_promotion_summary,
            },
            'scope': scope,
        }

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

    def execute_node_action(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node_id: str,
        action: str,
        actor: str,
        reason: str = '',
        payload: dict[str, Any] | None = None,
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'canvas',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        inspected = self.get_node_inspector(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            actor=actor,
        )
        if not inspected.get('ok'):
            return inspected
        scope = dict(inspected.get('scope') or {})
        node = dict(inspected.get('node') or {})
        inspected_node = dict(node)
        raw_node = next((item for item in gw.audit.list_canvas_nodes(canvas_id=canvas_id, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) if str(item.get('node_id') or '') == str(node_id or '')), {})
        if raw_node:
            node = dict(raw_node)
            inspected_data = dict((inspected_node.get('data') or {}))
            if inspected_data:
                merged_data = dict(node.get('data') or {})
                merged_data.update(inspected_data)
                node['data'] = merged_data
        node_type = str(node.get('node_type') or '').strip().lower()
        data = dict(node.get('data') or {})
        normalized_action = str(action or '').strip().lower()
        raw_payload = dict(payload or {})
        precheck = self._node_action_precheck(node=node, related=dict(inspected.get('related') or {}), action=normalized_action, actor=actor, payload=raw_payload)
        if not precheck.get('allowed'):
            self._safe_call(
                gw.audit, 'log_event', None, 'admin', 'canvas', str(actor or 'operator'), canvas_id,
                {'action': 'canvas_node_action_blocked', 'node_id': node_id, 'node_type': node_type, 'operator_action': normalized_action, 'reason': precheck.get('reason') or reason},
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
            return {'ok': False, 'canvas_id': canvas_id, 'node_id': node_id, 'action': normalized_action, 'error': 'action_blocked', 'precheck': precheck, 'scope': scope}
        if precheck.get('requires_confirmation') and not bool(raw_payload.get('confirmed', False)):
            self._safe_call(
                gw.audit, 'log_event', None, 'admin', 'canvas', str(actor or 'operator'), canvas_id,
                {'action': 'canvas_node_action_confirmation_required', 'node_id': node_id, 'node_type': node_type, 'operator_action': normalized_action, 'reason': reason},
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
            return {'ok': False, 'canvas_id': canvas_id, 'node_id': node_id, 'action': normalized_action, 'error': 'confirmation_required', 'precheck': precheck, 'scope': scope}
        result: dict[str, Any]
        if node_type == 'workflow':
            workflow_id = str(data.get('workflow_id') or (inspected.get('references') or {}).get('workflow_ids', [''])[0] or '').strip()
            if not workflow_id:
                raise ValueError('workflow node missing workflow_id')
            result = self.operator_console_service.workflow_action(
                gw, workflow_id=workflow_id, action=normalized_action, actor=actor, reason=reason,
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif node_type == 'approval':
            approval_id = str(data.get('approval_id') or (inspected.get('references') or {}).get('approval_ids', [''])[0] or '').strip()
            if not approval_id:
                raise ValueError('approval node missing approval_id')
            result = self.operator_console_service.approval_action(
                gw, approval_id=approval_id, action=normalized_action, actor=actor, reason=reason,
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif node_type in {'runtime', 'openclaw_runtime'}:
            runtime_id = str(data.get('runtime_id') or '').strip()
            if not runtime_id:
                raise ValueError('runtime node missing runtime_id')
            selected_dispatch_id = str(
                raw_payload.get('dispatch_id')
                or (((inspected.get('related') or {}).get('runtime_runboard') or {}).get('latest_run') or {}).get('dispatch_id')
                or ''
            ).strip()
            if normalized_action == 'health_check':
                result = self.openclaw_adapter_service.check_runtime_health(
                    gw, runtime_id=runtime_id, actor=actor, probe=str(raw_payload.get('probe') or 'ready'),
                    user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                    session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            elif normalized_action == 'cancel_run':
                if not selected_dispatch_id:
                    raise ValueError('runtime action requires dispatch_id or latest_run')
                result = self.openclaw_adapter_service.cancel_dispatch(
                    gw, dispatch_id=selected_dispatch_id, actor=actor, reason=reason,
                    user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                    session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            elif normalized_action == 'retry_run':
                if not selected_dispatch_id:
                    raise ValueError('runtime action requires dispatch_id or latest_run')
                result = self.openclaw_adapter_service.retry_dispatch(
                    gw, dispatch_id=selected_dispatch_id, actor=actor, reason=reason,
                    payload_override=dict(raw_payload.get('payload_override') or {}),
                    action_override=str(raw_payload.get('action_override') or ''),
                    agent_id_override=str(raw_payload.get('agent_id_override') or ''),
                    user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                    session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            elif normalized_action in {'manual_close', 'reconcile_run'}:
                if not selected_dispatch_id:
                    raise ValueError('runtime action requires dispatch_id or latest_run')
                target_status = str(raw_payload.get('target_status') or raw_payload.get('manual_status') or ('cancelled' if normalized_action == 'manual_close' else '')).strip().lower()
                result = self.openclaw_adapter_service.reconcile_dispatch(
                    gw, dispatch_id=selected_dispatch_id, actor=actor, target_status=target_status, reason=reason,
                    user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                    session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            elif normalized_action == 'poll_run':
                if not selected_dispatch_id:
                    raise ValueError('runtime action requires dispatch_id or latest_run')
                result = self.openclaw_adapter_service.poll_dispatch(
                    gw, dispatch_id=selected_dispatch_id, actor=actor, reason=reason,
                    user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                    session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            elif normalized_action == 'recover_stale_runs':
                result = self.openclaw_adapter_service.recover_stale_dispatches(
                    gw, runtime_id=runtime_id, actor=actor, reason=reason,
                    limit=int(raw_payload.get('limit') or 25),
                    user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                    session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            elif normalized_action in {'simulate_portfolio_calendar', 'detect_portfolio_drift', 'report_portfolio_policy_conformance', 'report_portfolio_policy_baseline_drift', 'reconcile_portfolio_custody_anchors', 'validate_portfolio_providers', 'attest_portfolio_custody_anchor', 'request_portfolio_policy_deviation_exception', 'approve_portfolio_policy_deviation_exception', 'reject_portfolio_policy_deviation_exception', 'request_portfolio_approval', 'approve_portfolio_approval', 'reject_portfolio_approval', 'export_portfolio_attestation', 'export_portfolio_postmortem', 'export_portfolio_evidence_package', 'verify_portfolio_evidence_artifact', 'restore_portfolio_evidence_artifact', 'prune_portfolio_evidence_packages'}:
                portfolios = dict((inspected.get('related') or {}).get('runtime_alert_governance_portfolios') or {})
                selected_portfolio_id = str(raw_payload.get('portfolio_id') or (((portfolios.get('items') or [{}])[0]).get('portfolio_id')) or '').strip()
                if not selected_portfolio_id:
                    raise ValueError('portfolio action requires portfolio_id or an available portfolio')
                if normalized_action == 'simulate_portfolio_calendar':
                    result = self.openclaw_recovery_scheduler_service.simulate_runtime_alert_governance_portfolio(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        now_ts=float(raw_payload.get('now_ts')) if raw_payload.get('now_ts') is not None else None,
                        dry_run=bool(raw_payload.get('dry_run', True)),
                        auto_reschedule=bool(raw_payload.get('auto_reschedule')) if raw_payload.get('auto_reschedule') is not None else None,
                        persist_schedule=bool(raw_payload.get('persist_schedule', False)),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'detect_portfolio_drift':
                    result = self.openclaw_recovery_scheduler_service.detect_runtime_alert_governance_portfolio_drift(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        persist_metadata=bool(raw_payload.get('persist_metadata', True)),
                    )
                elif normalized_action == 'report_portfolio_policy_conformance':
                    result = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_portfolio_policy_conformance(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        persist_metadata=bool(raw_payload.get('persist_metadata', True)),
                    )
                elif normalized_action == 'report_portfolio_policy_baseline_drift':
                    result = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_portfolio_policy_baseline_drift(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        persist_metadata=bool(raw_payload.get('persist_metadata', True)),
                    )
                elif normalized_action == 'reconcile_portfolio_custody_anchors':
                    result = self.openclaw_recovery_scheduler_service.reconcile_runtime_alert_governance_portfolio_custody_anchors(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'validate_portfolio_providers':
                    result = self.openclaw_recovery_scheduler_service.validate_runtime_alert_governance_portfolio_provider_integrations(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'attest_portfolio_custody_anchor':
                    result = self.openclaw_recovery_scheduler_service.attest_runtime_alert_governance_portfolio_custody_anchor(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        package_id=raw_payload.get('package_id'),
                        control_plane_id=raw_payload.get('control_plane_id'),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'request_portfolio_policy_deviation_exception':
                    result = self.openclaw_recovery_scheduler_service.request_runtime_alert_governance_portfolio_policy_deviation_exception(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        deviation_id=str(raw_payload.get('deviation_id') or ''),
                        actor=actor,
                        reason=reason,
                        ttl_s=int(raw_payload.get('ttl_s')) if raw_payload.get('ttl_s') is not None else None,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action in {'approve_portfolio_policy_deviation_exception', 'reject_portfolio_policy_deviation_exception'}:
                    approval_id = str(raw_payload.get('approval_id') or '').strip()
                    if not approval_id:
                        approvals = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_portfolio_policy_deviation_exceptions(
                            gw,
                            portfolio_id=selected_portfolio_id,
                            tenant_id=scope.get('tenant_id'),
                            workspace_id=scope.get('workspace_id'),
                            environment=scope.get('environment'),
                        )
                        items = list(((approvals.get('deviation_exceptions') or {}).get('items') or []))
                        for item in items:
                            if str(item.get('status') or '') == 'pending_approval' and str(item.get('approval_id') or '').strip():
                                approval_id = str(item.get('approval_id') or '').strip()
                                break
                    if not approval_id:
                        raise ValueError('portfolio policy deviation action requires approval_id or a pending exception')
                    result = self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_portfolio_policy_deviation_exception(
                        gw,
                        approval_id=approval_id,
                        actor=actor,
                        decision='approve' if normalized_action == 'approve_portfolio_policy_deviation_exception' else 'reject',
                        reason=reason,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'request_portfolio_approval':
                    result = self.openclaw_recovery_scheduler_service.approve_runtime_alert_governance_portfolio(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        reason=str(reason or raw_payload.get('reason') or ''),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'export_portfolio_attestation':
                    result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_portfolio_attestation(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        attestation_id=raw_payload.get('attestation_id'),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'export_portfolio_postmortem':
                    result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_portfolio_postmortem(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        attestation_id=raw_payload.get('attestation_id'),
                        timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'export_portfolio_evidence_package':
                    result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_portfolio_evidence_package(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        attestation_id=raw_payload.get('attestation_id'),
                        timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'verify_portfolio_evidence_artifact':
                    result = self.openclaw_recovery_scheduler_service.verify_runtime_alert_governance_portfolio_evidence_artifact(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        package_id=raw_payload.get('package_id'),
                        artifact=raw_payload.get('artifact'),
                        artifact_b64=raw_payload.get('artifact_b64'),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'restore_portfolio_evidence_artifact':
                    result = self.openclaw_recovery_scheduler_service.restore_runtime_alert_governance_portfolio_evidence_artifact(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        package_id=raw_payload.get('package_id'),
                        artifact=raw_payload.get('artifact'),
                        artifact_b64=raw_payload.get('artifact_b64'),
                        persist_restore_session=bool(raw_payload.get('persist_restore_session', False)),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'prune_portfolio_evidence_packages':
                    result = self.openclaw_recovery_scheduler_service.prune_runtime_alert_governance_portfolio_evidence_packages(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        actor=actor,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                else:
                    portfolio_detail = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_portfolio(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                    approval_items = list(((portfolio_detail.get('approvals') or {}).get('items') or []))
                    approval_id = str(raw_payload.get('approval_id') or (((approval_items or [{}])[0]).get('approval_id')) or '').strip()
                    if not approval_id:
                        raise ValueError('portfolio approval action requires approval_id or a pending portfolio approval')
                    result = self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_portfolio_approval(
                        gw,
                        approval_id=approval_id,
                        actor=actor,
                        decision='approve' if normalized_action == 'approve_portfolio_approval' else 'reject',
                        reason=str(reason or raw_payload.get('reason') or ''),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
            elif normalized_action in {'ack_alert', 'silence_alert', 'escalate_alert', 'dispatch_alert_notification', 'approve_alert_escalation', 'reject_alert_escalation', 'simulate_alert_governance', 'activate_alert_governance', 'rollback_alert_governance', 'approve_governance_promotion', 'reject_governance_promotion'}:
                runtime_alerts = dict((inspected.get('related') or {}).get('runtime_alerts') or {})
                selected_alert_code = str(raw_payload.get('alert_code') or (((runtime_alerts.get('items') or [{}])[0]).get('code')) or '').strip()
                if not selected_alert_code:
                    raise ValueError('runtime alert action requires alert_code or an active alert')
                if normalized_action == 'ack_alert':
                    result = self.openclaw_recovery_scheduler_service.ack_runtime_alert(
                        gw, runtime_id=runtime_id, alert_code=selected_alert_code, actor=actor,
                        note=str(raw_payload.get('note') or reason or ''),
                        tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                    )
                elif normalized_action == 'silence_alert':
                    result = self.openclaw_recovery_scheduler_service.silence_runtime_alert(
                        gw, runtime_id=runtime_id, alert_code=selected_alert_code, actor=actor,
                        silence_for_s=int(raw_payload.get('silence_for_s') or raw_payload.get('duration_s') or 0) or None,
                        reason=str(reason or raw_payload.get('reason') or ''),
                        tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                    )
                elif normalized_action == 'escalate_alert':
                    result = self.openclaw_recovery_scheduler_service.escalate_runtime_alert(
                        gw, runtime_id=runtime_id, alert_code=selected_alert_code, actor=actor,
                        target=str(raw_payload.get('target') or ''),
                        reason=str(reason or raw_payload.get('reason') or ''),
                        level=int(raw_payload.get('level')) if raw_payload.get('level') is not None else None,
                        tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                    )
                elif normalized_action in {'approve_alert_escalation', 'reject_alert_escalation'}:
                    approvals = dict((inspected.get('related') or {}).get('runtime_alert_approvals') or {})
                    approval_id = str(raw_payload.get('approval_id') or (((approvals.get('items') or [{}])[0]).get('approval_id')) or '').strip()
                    if not approval_id:
                        raise ValueError('alert escalation approval action requires approval_id or a pending approval')
                    result = self.openclaw_recovery_scheduler_service.decide_alert_escalation_approval(
                        gw, approval_id=approval_id, actor=actor,
                        decision='approve' if normalized_action == 'approve_alert_escalation' else 'reject',
                        reason=str(reason or raw_payload.get('reason') or ''),
                        tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                    )
                elif normalized_action in {'approve_governance_promotion', 'reject_governance_promotion'}:
                    approvals = dict((inspected.get('related') or {}).get('runtime_alert_governance_promotion_approvals') or {})
                    approval_id = str(raw_payload.get('approval_id') or (((approvals.get('items') or [{}])[0]).get('approval_id')) or '').strip()
                    if not approval_id:
                        raise ValueError('governance promotion approval action requires approval_id or a pending approval')
                    result = self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_promotion_approval(
                        gw, approval_id=approval_id, actor=actor,
                        decision='approve' if normalized_action == 'approve_governance_promotion' else 'reject',
                        reason=str(reason or raw_payload.get('reason') or ''),
                        tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                    )
                elif normalized_action == 'simulate_alert_governance':
                    result = self.openclaw_recovery_scheduler_service.simulate_runtime_alert_governance(
                        gw,
                        runtime_id=runtime_id,
                        candidate_policy=dict(raw_payload.get('candidate_policy') or raw_payload.get('policy') or {}),
                        merge_with_current=bool(raw_payload.get('merge_with_current', True)),
                        alert_code=selected_alert_code,
                        include_unchanged=bool(raw_payload.get('include_unchanged', True)),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        limit=int(raw_payload.get('limit') or 200),
                        now_ts=float(raw_payload.get('now_ts')) if raw_payload.get('now_ts') is not None else None,
                    )
                elif normalized_action == 'activate_alert_governance':
                    result = self.openclaw_recovery_scheduler_service.activate_runtime_alert_governance(
                        gw,
                        runtime_id=runtime_id,
                        actor=actor,
                        candidate_policy=dict(raw_payload.get('candidate_policy') or raw_payload.get('policy') or {}),
                        merge_with_current=bool(raw_payload.get('merge_with_current', True)),
                        reason=str(reason or raw_payload.get('reason') or ''),
                        alert_code=(str(raw_payload.get('alert_code') or selected_alert_code).strip() or None),
                        include_unchanged=bool(raw_payload.get('include_unchanged', True)),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        limit=int(raw_payload.get('limit') or 200),
                        now_ts=float(raw_payload.get('now_ts')) if raw_payload.get('now_ts') is not None else None,
                    )
                elif normalized_action == 'rollback_alert_governance':
                    versions = dict((inspected.get('related') or {}).get('runtime_alert_governance_versions') or {})
                    version_id = str(raw_payload.get('version_id') or (((versions.get('current_version') or {}).get('version_id')) or (((versions.get('items') or [{}])[0]).get('version_id')) or '')).strip()
                    if not version_id:
                        raise ValueError('alert governance rollback requires version_id or an available version')
                    result = self.openclaw_recovery_scheduler_service.rollback_runtime_alert_governance_version(
                        gw,
                        runtime_id=runtime_id,
                        version_id=version_id,
                        actor=actor,
                        reason=str(reason or raw_payload.get('reason') or ''),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                else:
                    result = self.openclaw_recovery_scheduler_service.dispatch_runtime_alert_notifications(
                        gw, runtime_id=runtime_id, alert_code=selected_alert_code, actor=actor,
                        workflow_action=str(raw_payload.get('workflow_action') or 'escalate'),
                        target_id=str(raw_payload.get('target_id') or raw_payload.get('target') or ''),
                        reason=str(reason or raw_payload.get('reason') or ''),
                        escalation_level=int(raw_payload.get('level')) if raw_payload.get('level') is not None else None,
                        tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                    )
            else:
                dispatch_payload = dict(raw_payload.get('payload') or raw_payload)
                dispatch_action = normalized_action
                effective_dispatch_action = dispatch_action
                dry_run = bool(raw_payload.get('dry_run', False))
                if normalized_action in {'dry_run', 'preview'}:
                    dry_run = True
                    dispatch_action = str(raw_payload.get('dispatch_action') or 'health_check')
                    effective_dispatch_action = dispatch_action
                    runtime_detail = gw.audit.get_openclaw_runtime(
                        runtime_id,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                    if runtime_detail is not None:
                        allowed_actions = self.openclaw_adapter_service._allowed_actions(runtime_detail)
                        if allowed_actions and dispatch_action not in allowed_actions and 'dispatch' in allowed_actions:
                            effective_dispatch_action = 'dispatch'
                            dispatch_payload = dict(dispatch_payload or {})
                            dispatch_payload.setdefault('dispatch_action', dispatch_action)
                result = self.openclaw_adapter_service.dispatch(
                    gw, runtime_id=runtime_id, actor=actor, action=effective_dispatch_action, payload=dispatch_payload,
                    agent_id=str(raw_payload.get('agent_id') or data.get('agent_id') or ''),
                    user_role=str(user_role or 'operator'),
                    user_key=str(user_key or actor or ''),
                    session_id=str(session_id or f'canvas:{canvas_id}'),
                    tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                    dry_run=dry_run,
                )
        elif node_type in {'baseline_promotion', 'policy_baseline_promotion'}:
            promotion_id = str(data.get('promotion_id') or node.get('label') or '').strip()
            if not promotion_id:
                raise ValueError('baseline promotion node missing promotion_id')
            latest_simulation = dict(data.get('latest_simulation') or {})
            if normalized_action in {'simulate', 'simulate_baseline_promotion'}:
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
            elif normalized_action in {'approve_simulation', 'reject_simulation'}:
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
            elif normalized_action in {'export_simulation_attestation', 'export_simulation_review_audit', 'export_simulation_evidence_package', 'verify_simulation_evidence_package', 'restore_simulation_evidence_package', 'reconcile_simulation_evidence_custody'}:
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
            elif normalized_action == 'save_simulation_custody_routing_policy_pack':
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
            elif normalized_action == 'promote_simulation_custody_routing_policy_pack_to_registry':
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
            elif normalized_action == 'promote_simulation_custody_routing_policy_pack_to_catalog':
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
            
            elif normalized_action == 'share_registered_simulation_custody_routing_policy_pack':
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
            elif normalized_action == 'share_cataloged_simulation_custody_routing_policy_pack':
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
            elif normalized_action in {'request_cataloged_simulation_custody_routing_policy_pack_review', 'claim_cataloged_simulation_custody_routing_policy_pack_review', 'add_cataloged_simulation_custody_routing_policy_pack_review_note', 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision'}:
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
            elif normalized_action in {'request_cataloged_simulation_custody_routing_policy_pack_approval', 'reject_cataloged_simulation_custody_routing_policy_pack_approval', 'curate_cataloged_simulation_custody_routing_policy_pack', 'approve_cataloged_simulation_custody_routing_policy_pack', 'deprecate_cataloged_simulation_custody_routing_policy_pack', 'stage_cataloged_simulation_custody_routing_policy_pack_release', 'release_cataloged_simulation_custody_routing_policy_pack', 'advance_cataloged_simulation_custody_routing_policy_pack_rollout', 'pause_cataloged_simulation_custody_routing_policy_pack_rollout', 'resume_cataloged_simulation_custody_routing_policy_pack_rollout', 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_release', 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release', 'withdraw_cataloged_simulation_custody_routing_policy_pack_release'}:
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
            elif normalized_action in {'export_cataloged_simulation_custody_routing_policy_pack_evidence_package', 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle', 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report', 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report'}:
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
            elif normalized_action in {'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service', 'withdraw_cataloged_simulation_custody_routing_policy_pack_from_organizational_catalog_service', 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot', 'reconcile_organizational_simulation_custody_routing_policy_pack_catalog_service', 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_reconciliation_report'}:
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
            elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_attestation':
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

            elif normalized_action in {'bind_cataloged_simulation_custody_routing_policy_pack_effective_policy', 'unbind_cataloged_simulation_custody_routing_policy_pack_effective_policy'}:
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

            elif normalized_action in {'simulate_simulation_custody_routing', 'replay_simulation_custody_routing', 'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'}:
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
            elif normalized_action in {'acknowledge_simulation_custody_alert', 'mute_simulation_custody_alert', 'unmute_simulation_custody_alert', 'resolve_simulation_custody_alert', 'claim_simulation_custody_alert', 'assign_simulation_custody_alert', 'release_simulation_custody_alert', 'reroute_simulation_custody_alert', 'handoff_simulation_custody_alert'}:
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
            elif normalized_action in {'create_rollout', 'create_and_approve_rollout'}:
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
            elif normalized_action == 'export_attestation':
                result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_attestation(
                    gw,
                    promotion_id=promotion_id,
                    actor=actor,
                    timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'export_postmortem':
                result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_postmortem(
                    gw,
                    promotion_id=promotion_id,
                    actor=actor,
                    timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            else:
                result = self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_baseline_promotion(
                    gw,
                    promotion_id=promotion_id,
                    actor=actor,
                    decision=normalized_action,
                    reason=reason,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
        else:
            raise ValueError('Unsupported node action')
        refreshed = self.get_node_inspector(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            actor=actor,
        )
        self._safe_call(
            gw.audit, 'log_event', None, 'admin', 'canvas', str(actor or 'operator'), canvas_id,
            {'action': 'canvas_node_action_executed', 'node_id': node_id, 'node_type': node_type, 'operator_action': normalized_action, 'reason': reason, 'reconciled': bool(refreshed.get('ok'))},
            tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
        )
        result_ok = True
        result_error = ''
        if isinstance(result, dict):
            result_ok = bool(result.get('ok', True))
            result_error = str(result.get('error') or '').strip()
        return {
            'ok': result_ok,
            'canvas_id': canvas_id,
            'node_id': node_id,
            'action': normalized_action,
            'error': result_error,
            'precheck': precheck,
            'result': result,
            'reconciled': bool(refreshed.get('ok')),
            'refresh': refreshed if refreshed.get('ok') else {},
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

    def get_node_timeline(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_document(gw, canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        scope = dict(detail.get('scope') or {})
        nodes = list(detail.get('nodes') or [])
        node = next((item for item in nodes if str(item.get('node_id') or '') == str(node_id or '')), None)
        if node is None:
            return {'ok': False, 'reason': 'node_not_found', 'canvas_id': canvas_id, 'node_id': node_id, 'scope': scope}
        refs = self._collect_refs(nodes, selected_node_id=node_id)
        node_type = str(node.get('node_type') or '').strip().lower()
        items: list[dict[str, Any]] = []
        if node_type == 'workflow':
            workflow_id = str(((node.get('data') or {}).get('workflow_id')) or (refs.get('workflow_ids') or [''])[0] or '').strip()
            timeline = self.operator_console_service.workflow_service.unified_timeline(
                gw, workflow_id=workflow_id or None, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            for event in list(timeline.get('items') or []):
                payload = dict(event.get('payload') or {})
                items.append({'kind': 'event', 'ts': float(event.get('ts') or 0.0), 'label': str(payload.get('event') or payload.get('action') or 'workflow_event'), 'status': str(payload.get('status') or ''), 'event': event})
        elif node_type == 'approval':
            approval_id = str(((node.get('data') or {}).get('approval_id')) or (refs.get('approval_ids') or [''])[0] or '').strip()
            timeline = self.operator_console_service.workflow_service.unified_timeline(
                gw, approval_id=approval_id or None, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            for event in list(timeline.get('items') or []):
                payload = dict(event.get('payload') or {})
                items.append({'kind': 'event', 'ts': float(event.get('ts') or 0.0), 'label': str(payload.get('event') or payload.get('action') or 'approval_event'), 'status': str(payload.get('status') or ''), 'event': event})
        elif node_type in {'runtime', 'openclaw_runtime'}:
            runtime_id = str(((node.get('data') or {}).get('runtime_id')) or '').strip()
            events = self._safe_call(gw.audit, 'list_events_filtered', [], limit=max(limit * 5, 100), channels=['broker'], tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            for event in list(events or []):
                payload = dict(event.get('payload') or {})
                if str(payload.get('runtime_id') or '') != runtime_id:
                    continue
                items.append({'kind': 'event', 'ts': float(event.get('ts') or 0.0), 'label': str(payload.get('action') or payload.get('event') or 'runtime_event'), 'status': str(payload.get('status') or payload.get('health_status') or ''), 'event': event})
            dispatches = self._safe_call(gw.audit, 'list_openclaw_dispatches', [], runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            concurrency = self.openclaw_recovery_scheduler_service.get_runtime_concurrency(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            alerts = self.openclaw_recovery_scheduler_service.evaluate_runtime_alerts(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            alert_states = self.openclaw_recovery_scheduler_service.list_runtime_alert_states(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            alert_approvals = self.openclaw_recovery_scheduler_service.list_alert_escalation_approvals(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            for lease in list((concurrency.get('leases') or [])):
                items.append({'kind': 'lease', 'ts': float(lease.get('updated_at') or lease.get('created_at') or 0.0), 'label': str(lease.get('lease_type') or 'lease'), 'status': 'active' if bool(lease.get('active')) else 'expired', 'lease': lease})
            for record in list((concurrency.get('idempotency_records') or [])):
                items.append({'kind': 'idempotency', 'ts': float(record.get('updated_at') or record.get('created_at') or 0.0), 'label': 'due_slot', 'status': str(record.get('status') or ''), 'idempotency_record': record})
            for alert in list((alerts.get('items') or [])):
                items.append({'kind': 'alert', 'ts': float(alert.get('observed_at') or 0.0), 'label': str(alert.get('title') or alert.get('code') or 'alert'), 'status': str(alert.get('severity') or ''), 'alert': alert})
            governance = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            if bool((governance.get('current') or {}).get('quiet_hours_active')) or bool((governance.get('current') or {}).get('maintenance_active')) or bool((governance.get('current') or {}).get('storm_active')):
                items.append({'kind': 'alert_governance', 'ts': time.time(), 'label': 'alert_governance', 'status': 'active', 'alert_governance': governance})
            versions = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_versions(
                gw, runtime_id=runtime_id, limit=max(5, min(limit, 20)), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
            if int((versions.get('summary') or {}).get('count') or 0) > 0:
                items.append({'kind': 'alert_governance_version', 'ts': time.time(), 'label': 'alert_governance_version', 'status': 'active' if (versions.get('current_version') or {}).get('version_id') else 'history', 'versions': versions})
            alert_dispatches = self.openclaw_recovery_scheduler_service.list_runtime_alert_notification_dispatches(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            alert_delivery_jobs = self.openclaw_recovery_scheduler_service.list_alert_delivery_jobs(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            for alert_state in list((alert_states.get('items') or [])):
                items.append({'kind': 'alert_workflow', 'ts': float(alert_state.get('updated_at') or alert_state.get('observed_at') or 0.0), 'label': str(alert_state.get('alert_code') or 'alert_workflow'), 'status': str(alert_state.get('workflow_status') or ''), 'alert_state': alert_state})
            for approval in list((alert_approvals.get('items') or [])):
                items.append({'kind': 'alert_approval', 'ts': float(approval.get('updated_at') or approval.get('created_at') or 0.0), 'label': str(approval.get('alert_code') or 'alert_approval'), 'status': str(approval.get('status') or ''), 'alert_approval': approval})
            for alert_dispatch in list((alert_dispatches.get('items') or [])):
                items.append({'kind': 'alert_dispatch', 'ts': float(alert_dispatch.get('updated_at') or alert_dispatch.get('created_at') or 0.0), 'label': str(alert_dispatch.get('target_id') or 'alert_dispatch'), 'status': str(alert_dispatch.get('delivery_status') or ''), 'alert_dispatch': alert_dispatch})
            for alert_job in list((alert_delivery_jobs.get('items') or [])):
                items.append({'kind': 'alert_delivery_job', 'ts': float(alert_job.get('next_run_at') or alert_job.get('created_at') or 0.0), 'label': str(((alert_job.get('target') or {}).get('target_id')) or 'alert_delivery_job'), 'status': 'due' if bool(alert_job.get('is_due')) else 'scheduled', 'alert_delivery_job': alert_job})
            for dispatch in list(dispatches or []):
                enriched_dispatch = self.openclaw_adapter_service._canonical_dispatch_view(dispatch) or dict(dispatch)
                items.append({
                    'kind': 'dispatch',
                    'ts': float(dispatch.get('created_at') or 0.0),
                    'label': str(dispatch.get('action') or 'dispatch'),
                    'status': str(dispatch.get('status') or ''),
                    'canonical_status': str(enriched_dispatch.get('canonical_status') or ''),
                    'terminal': bool(enriched_dispatch.get('terminal')),
                    'dispatch': enriched_dispatch,
                })
        elif node_type in {'baseline_promotion', 'policy_baseline_promotion'}:
            promotion_id = str(((node.get('data') or {}).get('promotion_id')) or node.get('label') or '').strip()
            if promotion_id:
                timeline = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_baseline_promotion_timeline(
                    gw,
                    promotion_id=promotion_id,
                    limit=limit,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                for event in list(timeline.get('timeline') or []):
                    items.append({
                        'kind': str(event.get('kind') or 'baseline_promotion_event'),
                        'ts': float(event.get('ts') or 0.0),
                        'label': str(event.get('label') or 'baseline_promotion_event'),
                        'status': str(event.get('status') or event.get('trigger') or ''),
                        'baseline_promotion_event': event,
                    })
                canvas_events = self._safe_call(
                    gw.audit,
                    'list_events_filtered',
                    [],
                    limit=max(limit * 5, 50),
                    channels=['canvas'],
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                for event in list(canvas_events or []):
                    payload = dict(event.get('payload') or {})
                    if str(payload.get('node_id') or '') != str(node_id or ''):
                        continue
                    if str(payload.get('action') or '') not in {'canvas_node_action_executed', 'canvas_node_action_confirmation_required'}:
                        continue
                    operator_action = str(payload.get('operator_action') or '').strip()
                    if not operator_action:
                        continue
                    items.append({
                        'kind': 'canvas_action',
                        'ts': float(event.get('ts') or 0.0),
                        'label': f'canvas_{operator_action}',
                        'status': str(payload.get('reason') or ''),
                        'canvas_event': event,
                    })
        items.sort(key=lambda item: float(item.get('ts') or 0.0))
        return {'ok': True, 'canvas_id': canvas_id, 'node_id': node_id, 'items': items[-limit:], 'scope': scope}

    def _node_action_precheck(self, *, node: dict[str, Any], related: dict[str, Any] | None, action: str, actor: str = '', payload: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_action = str(action or '').strip().lower()
        node_type = str(node.get('node_type') or '').strip().lower()
        available = set(self._node_available_actions(node, related=related))
        if normalized_action not in available:
            return {'allowed': False, 'reason': 'action_not_available', 'requires_confirmation': False, 'warnings': []}
        warnings: list[str] = []
        if node_type == 'workflow':
            workflow = dict((related or {}).get('workflow', {}).get('workflow') or {})
            status = str(workflow.get('status') or '').strip().lower()
            if normalized_action == 'run' and status in {'running', 'waiting_approval'}:
                return {'allowed': False, 'reason': 'workflow_already_active', 'requires_confirmation': False, 'warnings': []}
            if normalized_action == 'cancel' and status not in {'created', 'pending', 'running', 'waiting_approval'}:
                return {'allowed': False, 'reason': 'workflow_not_cancellable', 'requires_confirmation': False, 'warnings': []}
        elif node_type == 'approval':
            approval = dict((related or {}).get('approval') or {})
            status = str(approval.get('status') or '').strip().lower()
            assigned_to = str(approval.get('assigned_to') or '').strip()
            actor_key = str(actor or '').strip()
            if status != 'pending':
                return {'allowed': False, 'reason': 'approval_not_pending', 'requires_confirmation': False, 'warnings': []}
            if assigned_to and actor_key and assigned_to != actor_key:
                return {'allowed': False, 'reason': 'approval_claimed_by_other', 'requires_confirmation': False, 'warnings': []}
        elif node_type in {'runtime', 'openclaw_runtime'}:
            runtime = dict((related or {}).get('runtime', {}).get('runtime') or {})
            health = dict((related or {}).get('runtime', {}).get('health') or {})
            if str(health.get('status') or '') in {'unhealthy', 'degraded'}:
                warnings.append(f"runtime_health:{health.get('status')}")
            if bool(health.get('stale')):
                warnings.append('runtime_health:stale')
            if not runtime:
                return {'allowed': False, 'reason': 'runtime_not_found', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'ack_alert', 'silence_alert', 'escalate_alert', 'dispatch_alert_notification', 'approve_alert_escalation', 'reject_alert_escalation'}:
                alerts = dict((related or {}).get('runtime_alerts') or {})
                if not list(alerts.get('items') or []):
                    return {'allowed': False, 'reason': 'no_runtime_alerts', 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action in {'approve_alert_escalation', 'reject_alert_escalation'}:
                    warnings.append('approval_action:alert_escalation')
                    approvals = dict((related or {}).get('runtime_alert_approvals') or {})
                    if not list(approvals.get('items') or []):
                        return {'allowed': False, 'reason': 'no_alert_escalation_approvals', 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action == 'dispatch_alert_notification':
                    targets = dict((related or {}).get('runtime_notification_targets') or {})
                    if not list(targets.get('items') or []):
                        warnings.append('alert_notification_targets:missing')
            if normalized_action in {'approve_governance_promotion', 'reject_governance_promotion'}:
                warnings.append('approval_action:governance_promotion')
                approvals = dict((related or {}).get('runtime_alert_governance_promotion_approvals') or {})
                if not list(approvals.get('items') or []):
                    return {'allowed': False, 'reason': 'no_governance_promotion_approvals', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'simulate_portfolio_calendar', 'detect_portfolio_drift', 'report_portfolio_policy_conformance', 'report_portfolio_policy_baseline_drift', 'reconcile_portfolio_custody_anchors', 'validate_portfolio_providers', 'attest_portfolio_custody_anchor', 'request_portfolio_policy_deviation_exception', 'approve_portfolio_policy_deviation_exception', 'reject_portfolio_policy_deviation_exception', 'request_portfolio_approval', 'approve_portfolio_approval', 'reject_portfolio_approval', 'export_portfolio_attestation', 'export_portfolio_postmortem', 'export_portfolio_evidence_package', 'verify_portfolio_evidence_artifact', 'restore_portfolio_evidence_artifact', 'prune_portfolio_evidence_packages'}:
                portfolios = dict((related or {}).get('runtime_alert_governance_portfolios') or {})
                portfolio_items = list(portfolios.get('items') or [])
                if not portfolio_items:
                    return {'allowed': False, 'reason': 'no_governance_portfolios', 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action in {'approve_portfolio_approval', 'reject_portfolio_approval'}:
                    warnings.append('approval_action:governance_portfolio')
                    pending_found = any(int((item.get('approval_summary') or {}).get('pending_count') or 0) > 0 for item in portfolio_items)
                    if not pending_found:
                        return {'allowed': False, 'reason': 'no_portfolio_approvals', 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action in {'approve_portfolio_policy_deviation_exception', 'reject_portfolio_policy_deviation_exception'}:
                    warnings.append('approval_action:governance_portfolio_deviation')
        elif node_type in {'baseline_promotion', 'policy_baseline_promotion'}:
            promotion_detail = dict((related or {}).get('baseline_promotion') or {})
            if not promotion_detail.get('ok'):
                return {'allowed': False, 'reason': 'baseline_promotion_not_found', 'requires_confirmation': False, 'warnings': warnings}
            release = dict(promotion_detail.get('release') or {})
            promotion = dict(promotion_detail.get('baseline_promotion') or {})
            latest_simulation = dict((node.get('data') or {}).get('latest_simulation') or {})
            status = str(release.get('status') or '').strip().lower()
            paused = bool((promotion.get('pause_state') or {}).get('paused')) or status == 'paused'
            terminal = status in {'completed', 'rolled_back', 'rejected'}
            if normalized_action == 'simulate' and not str(promotion.get('catalog_id') or '').strip():
                return {'allowed': False, 'reason': 'baseline_promotion_not_simulatable', 'requires_confirmation': False, 'warnings': warnings}
            stored_simulation_packages = list(((promotion_detail.get('simulation_evidence_packages') or {}).get('items') or []))
            if normalized_action in {'export_simulation_attestation', 'export_simulation_review_audit', 'export_simulation_evidence_package'}:
                if not latest_simulation:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'verify_simulation_evidence_package', 'restore_simulation_evidence_package', 'reconcile_simulation_evidence_custody'}:
                if not stored_simulation_packages and not str((((latest_simulation.get('export_state') or {}).get('latest_evidence_package') or {}).get('package_id')) or '').strip():
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_evidence_package_missing', 'requires_confirmation': False, 'warnings': warnings}
            custody_guard = dict((((promotion_detail.get('simulation_custody_monitoring') or {}).get('guard')) or {}))
            custody_alert_items = [dict(item) for item in list((((promotion_detail.get('simulation_custody_monitoring') or {}).get('alerts')) or {}).get('items') or [])]
            active_custody_alert = next((item for item in custody_alert_items if bool(item.get('active'))), {})
            muted_custody_alert = next((item for item in custody_alert_items if str(item.get('status') or '') == 'muted'), {})
            if bool(custody_guard.get('blocked')):
                warnings.append('baseline_promotion_simulation_custody:blocked')
            if normalized_action in {'save_simulation_custody_routing_policy_pack', 'promote_simulation_custody_routing_policy_pack_to_registry', 'promote_simulation_custody_routing_policy_pack_to_catalog', 'share_registered_simulation_custody_routing_policy_pack', 'share_cataloged_simulation_custody_routing_policy_pack'} and not latest_simulation:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_missing', 'requires_confirmation': False, 'warnings': warnings}
            catalog_registry = [
                dict(item or {})
                for item in list(((node.get('data') or {}).get('routing_policy_pack_catalog') or []) if isinstance((node.get('data') or {}).get('routing_policy_pack_catalog'), list) else [])
                if isinstance(item, dict)
            ]
            if not catalog_registry:
                catalog_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(
                    list(((node.get('data') or {}).get('routing_policy_pack_registry') or []))
                )
            organizational_service = dict((related or {}).get('routing_policy_pack_organizational_catalog_service') or {})
            organizational_entries = [dict(item or {}) for item in list(organizational_service.get('entries') or []) if isinstance(item, dict)]
            if normalized_action in {'request_cataloged_simulation_custody_routing_policy_pack_review', 'claim_cataloged_simulation_custody_routing_policy_pack_review', 'add_cataloged_simulation_custody_routing_policy_pack_review_note', 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision', 'request_cataloged_simulation_custody_routing_policy_pack_approval', 'reject_cataloged_simulation_custody_routing_policy_pack_approval', 'curate_cataloged_simulation_custody_routing_policy_pack', 'approve_cataloged_simulation_custody_routing_policy_pack', 'deprecate_cataloged_simulation_custody_routing_policy_pack', 'export_cataloged_simulation_custody_routing_policy_pack_attestation', 'export_cataloged_simulation_custody_routing_policy_pack_evidence_package', 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle', 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report', 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report', 'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service', 'withdraw_cataloged_simulation_custody_routing_policy_pack_from_organizational_catalog_service', 'bind_cataloged_simulation_custody_routing_policy_pack_effective_policy', 'unbind_cataloged_simulation_custody_routing_policy_pack_effective_policy', 'stage_cataloged_simulation_custody_routing_policy_pack_release', 'release_cataloged_simulation_custody_routing_policy_pack', 'advance_cataloged_simulation_custody_routing_policy_pack_rollout', 'pause_cataloged_simulation_custody_routing_policy_pack_rollout', 'resume_cataloged_simulation_custody_routing_policy_pack_rollout', 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_release', 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release', 'withdraw_cataloged_simulation_custody_routing_policy_pack_release', 'replay_cataloged_simulation_custody_routing_policy_pack'} and not catalog_registry:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot' and not organizational_entries:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_organizational_policy_pack_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'replay_organizational_simulation_custody_routing_policy_pack' and not organizational_entries:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_organizational_policy_pack_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'add_cataloged_simulation_custody_routing_policy_pack_review_note', 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision'}:
                active_review_found = any(self._baseline_promotion_simulation_custody_catalog_pack_review_state(item) != 'not_requested' for item in catalog_registry)
                if not active_review_found:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_review_not_requested', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'unbind_cataloged_simulation_custody_routing_policy_pack_effective_policy' and not any(isinstance(item, dict) for item in list((node.get('data') or {}).get('routing_policy_pack_bindings') or [])):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_binding_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle':
                releasable_pack_found = any(str(item.get('catalog_release_state') or 'draft') != 'draft' for item in catalog_registry)
                if not releasable_pack_found:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_release_bundle_not_ready', 'requires_confirmation': False, 'warnings': warnings}
            rollout_summaries = [self._baseline_promotion_simulation_custody_catalog_rollout_summary(item) for item in catalog_registry]
            if normalized_action == 'advance_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(bool(item.get('enabled')) for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'pause_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(str(item.get('state') or '') == 'rolling_out' for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_active', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'resume_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(bool(item.get('paused')) for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_paused', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(bool(item.get('enabled')) for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(bool(item.get('frozen')) for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_frozen', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(bool(item.get('enabled')) for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release' and not any(str(item.get('catalog_release_state') or 'draft') in {'staged', 'rolling_out', 'released'} for item in catalog_registry):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_release_not_active', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_release' and not any(self._baseline_promotion_simulation_custody_catalog_previous_restore_candidate(item, catalog_packs=catalog_registry) for item in catalog_registry):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_release_rollback_target_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'simulate_simulation_custody_routing', 'replay_simulation_custody_routing', 'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'} and not (active_custody_alert or muted_custody_alert):
                replay_actions = {'replay_simulation_custody_routing', 'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'}
                if normalized_action not in replay_actions:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'acknowledge_simulation_custody_alert', 'mute_simulation_custody_alert', 'resolve_simulation_custody_alert', 'claim_simulation_custody_alert', 'assign_simulation_custody_alert', 'release_simulation_custody_alert', 'reroute_simulation_custody_alert', 'handoff_simulation_custody_alert'} and not active_custody_alert:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'unmute_simulation_custody_alert' and not muted_custody_alert:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_not_muted', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'resolve_simulation_custody_alert':
                current_reconciliation = dict((promotion_detail.get('simulation_evidence_reconciliation') or {}).get('current') or {})
                if str((current_reconciliation.get('summary') or {}).get('overall_status') or '') == 'drifted':
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_still_drifted', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'claim_simulation_custody_alert':
                current_owner_id = str(((active_custody_alert.get('ownership') or {}).get('owner_id')) or '')
                if current_owner_id and current_owner_id != actor:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_already_owned', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'release_simulation_custody_alert' and not str(((active_custody_alert.get('ownership') or {}).get('owner_id')) or '').strip():
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_not_owned', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'approve_simulation', 'reject_simulation'}:
                if not latest_simulation:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_missing', 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('expired')):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_expired', 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('stale')):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_stale', 'requires_confirmation': False, 'warnings': warnings}
                if str((latest_simulation.get('validation') or {}).get('status') or '').strip().lower() != 'passed':
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_invalid', 'requires_confirmation': False, 'warnings': warnings}
                if not bool((latest_simulation.get('summary') or {}).get('approvable', False)):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_not_approvable', 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('blocked')) and str(latest_simulation.get('why_blocked') or '') not in {'baseline_promotion_simulation_review_rejected'}:
                    return {'allowed': False, 'reason': str(latest_simulation.get('why_blocked') or 'baseline_promotion_simulation_blocked'), 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action == 'approve_simulation':
                    if bool((latest_simulation.get('review') or {}).get('approved')):
                        return {'allowed': False, 'reason': 'baseline_promotion_simulation_already_approved', 'requires_confirmation': False, 'warnings': warnings}
                    if bool(((latest_simulation.get('review_state') or {}).get('rejected'))):
                        return {'allowed': False, 'reason': 'baseline_promotion_simulation_review_rejected', 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action == 'reject_simulation' and bool(((latest_simulation.get('review_state') or {}).get('rejected'))):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_already_rejected', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'create_rollout', 'create_and_approve_rollout'}:
                if not latest_simulation:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_missing', 'requires_confirmation': False, 'warnings': warnings}
                if bool(custody_guard.get('blocked')):
                    return {'allowed': False, 'reason': str(custody_guard.get('reason') or 'baseline_promotion_simulation_custody_drift_detected'), 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('expired')):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_expired', 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('stale')):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_stale', 'requires_confirmation': False, 'warnings': warnings}
                if bool(((latest_simulation.get('review_state') or {}).get('rejected'))):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_review_rejected', 'requires_confirmation': False, 'warnings': warnings}
                if not bool((latest_simulation.get('review') or {}).get('approved')):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_not_approved', 'requires_confirmation': False, 'warnings': warnings}
                if str((latest_simulation.get('validation') or {}).get('status') or '').strip().lower() != 'passed':
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_invalid', 'requires_confirmation': False, 'warnings': warnings}
                if not bool((latest_simulation.get('summary') or {}).get('approvable', False)):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_not_approvable', 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('blocked')):
                    return {'allowed': False, 'reason': str(latest_simulation.get('why_blocked') or 'baseline_promotion_simulation_blocked'), 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'approve', 'advance', 'resume'} and bool(custody_guard.get('blocked')):
                return {'allowed': False, 'reason': str(custody_guard.get('reason') or 'baseline_promotion_simulation_custody_drift_detected'), 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'approve' and status not in {'pending_approval'}:
                return {'allowed': False, 'reason': 'baseline_promotion_not_approvable', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'reject' and status not in {'pending_approval', 'approved', 'awaiting_advance', 'awaiting_advance_window', 'awaiting_dependencies'}:
                return {'allowed': False, 'reason': 'baseline_promotion_not_rejectable', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'advance':
                if terminal:
                    return {'allowed': False, 'reason': 'baseline_promotion_not_advanceable', 'requires_confirmation': False, 'warnings': warnings}
                if paused:
                    return {'allowed': False, 'reason': 'baseline_promotion_paused', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'pause' and (terminal or paused):
                return {'allowed': False, 'reason': 'baseline_promotion_not_pausable', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'resume' and not paused:
                return {'allowed': False, 'reason': 'baseline_promotion_not_paused', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'rollback' and terminal:
                return {'allowed': False, 'reason': 'baseline_promotion_not_rollbackable', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action.startswith('export_') and int((promotion_detail.get('analytics') or {}).get('timeline_count') or 0) == 0:
                warnings.append('baseline_promotion_timeline:empty')
        return {'allowed': True, 'reason': '', 'requires_confirmation': normalized_action in {'cancel', 'reject', 'cancel_run', 'manual_close', 'reconcile_run', 'escalate_alert', 'reject_alert_escalation', 'reject_governance_promotion', 'reject_portfolio_policy_deviation_exception', 'reject_portfolio_approval', 'prune_portfolio_evidence_packages', 'rollback'}, 'warnings': warnings}

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

    @staticmethod
    def _trace_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        trace_id = str(item.get('trace_id') or '')
        session_id = str(item.get('session_id') or '')
        tools_used = {str(tool.get('tool_name') or tool.get('name') or tool or '').strip() for tool in list(item.get('tools_used') or []) if str(tool)}
        policy_names = {str(pol.get('name') or '').strip() for pol in list(item.get('policies') or []) if isinstance(pol, dict)}
        if refs.get('trace_ids') and trace_id in set(refs.get('trace_ids') or []):
            return True
        workflow_sessions = {f"workflow:{workflow_id}" for workflow_id in list(refs.get('workflow_ids') or [])}
        if refs.get('session_ids') and session_id in set(refs.get('session_ids') or []):
            return True
        if workflow_sessions and session_id in workflow_sessions:
            return True
        if refs.get('tool_names') and tools_used.intersection(set(refs.get('tool_names') or [])):
            return True
        if refs.get('policy_names') and policy_names.intersection(set(refs.get('policy_names') or [])):
            return True
        if any(list(refs.get(key) or []) for key in ('trace_ids', 'workflow_ids', 'session_ids', 'tool_names', 'policy_names')):
            return False
        return True

    @staticmethod
    def _approval_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        approval_id = str(item.get('approval_id') or '')
        workflow_id = str(item.get('workflow_id') or '')
        if refs.get('approval_ids') and approval_id in set(refs.get('approval_ids') or []):
            return True
        if refs.get('workflow_ids') and workflow_id in set(refs.get('workflow_ids') or []):
            return True
        if any(list(refs.get(key) or []) for key in ('approval_ids', 'workflow_ids')):
            return False
        return True

    @staticmethod
    def _failure_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        kind = str(item.get('kind') or '')
        item_id = str(item.get('id') or '')
        label = str(item.get('label') or '')
        if kind == 'workflow' and refs.get('workflow_ids'):
            return item_id in set(refs.get('workflow_ids') or []) or label in set(refs.get('workflow_ids') or [])
        if kind == 'trace' and refs.get('trace_ids'):
            return item_id in set(refs.get('trace_ids') or [])
        if kind == 'tool_call' and refs.get('tool_names'):
            return label in set(refs.get('tool_names') or [])
        if any(list(refs.get(key) or []) for key in ('workflow_ids', 'trace_ids', 'tool_names')):
            return False
        return True

    @staticmethod
    def _secret_usage_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        ref = str(item.get('ref') or '')
        tools = {str(tool).strip() for tool in list(item.get('tools') or [])}
        if refs.get('secret_refs') and ref in set(refs.get('secret_refs') or []):
            return True
        if refs.get('tool_names') and tools.intersection(set(refs.get('tool_names') or [])):
            return True
        if any(list(refs.get(key) or []) for key in ('secret_refs', 'tool_names')):
            return False
        return True

    @staticmethod
    def _secret_catalog_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        ref = str(item.get('ref') or '')
        if refs.get('secret_refs') and ref in set(refs.get('secret_refs') or []):
            return True
        if any(list(refs.get(key) or []) for key in ('secret_refs',)):
            return False
        return True

    @staticmethod
    def _cost_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        workflows = {str(value).strip() for value in list(item.get('workflows') or [])}
        group = str(item.get('group') or '').strip()
        if refs.get('workflow_ids') and (workflows.intersection(set(refs.get('workflow_ids') or [])) or group in set(refs.get('workflow_ids') or [])):
            return True
        if any(list(refs.get(key) or []) for key in ('workflow_ids',)):
            return False
        return True

    @staticmethod
    def _budget_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        workflow_name = str(item.get('workflow_name') or '').strip()
        if refs.get('workflow_ids') and workflow_name in set(refs.get('workflow_ids') or []):
            return True
        if any(list(refs.get(key) or []) for key in ('workflow_ids',)):
            return False
        return True

    @staticmethod
    def _compact_trace(item: dict[str, Any]) -> dict[str, Any]:
        return {
            'trace_id': item.get('trace_id'),
            'session_id': item.get('session_id'),
            'agent_id': item.get('agent_id'),
            'status': item.get('status'),
            'provider': item.get('provider'),
            'model': item.get('model'),
            'latency_ms': float(item.get('latency_ms') or 0.0),
            'estimated_cost': float(item.get('estimated_cost') or 0.0),
            'tools_used': item.get('tools_used') or [],
            'policies': item.get('policies') or [],
            'ts': float(item.get('ts') or 0.0),
        }

    @staticmethod
    def _compact_approval(item: dict[str, Any]) -> dict[str, Any]:
        return {
            'approval_id': item.get('approval_id'),
            'workflow_id': item.get('workflow_id'),
            'step_id': item.get('step_id'),
            'requested_role': item.get('requested_role'),
            'requested_by': item.get('requested_by'),
            'status': item.get('status'),
            'reason': item.get('reason') or '',
            'updated_at': float(item.get('updated_at') or item.get('created_at') or 0.0),
        }

    @staticmethod
    def _sanitize_secret_usage(item: dict[str, Any]) -> dict[str, Any]:
        return {
            'ref': item.get('ref'),
            'count': int(item.get('count') or 0),
            'last_used_at': item.get('last_used_at'),
            'last_used_tool': item.get('last_used_tool'),
            'last_used_domain': item.get('last_used_domain'),
            'tools': list(item.get('tools') or []),
            'domains': list(item.get('domains') or []),
            'tenants': list(item.get('tenants') or []),
            'workspaces': list(item.get('workspaces') or []),
            'environments': list(item.get('environments') or []),
        }

    def _sanitize_secret_catalog(self, item: dict[str, Any]) -> dict[str, Any]:
        return self._redact_sensitive({
            'ref': item.get('ref'),
            'configured': bool(item.get('configured')),
            'usage_count': int(item.get('usage_count') or 0),
            'last_used_at': item.get('last_used_at'),
            'last_used_tool': item.get('last_used_tool'),
            'rotation': item.get('rotation') or {},
            'visibility': item.get('visibility') or {},
            'allowed_tenants': item.get('allowed_tenants') or [],
            'allowed_workspaces': item.get('allowed_workspaces') or [],
            'allowed_environments': item.get('allowed_environments') or [],
            'metadata': item.get('metadata') or {},
        })

    @staticmethod
    def _compact_cost_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            'group': item.get('group'),
            'run_count': int(item.get('run_count') or 0),
            'total_spend': float(item.get('total_spend') or 0.0),
            'average_spend_per_run': float(item.get('average_spend_per_run') or 0.0),
            'total_cases': int(item.get('total_cases') or 0),
            'latest_run_id': item.get('latest_run_id'),
            'latest_started_at': item.get('latest_started_at'),
            'workflows': list(item.get('workflows') or []),
            'agents': list(item.get('agents') or []),
        }

    @staticmethod
    def _compact_budget_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            'budget_name': item.get('budget_name'),
            'status': item.get('status'),
            'workflow_name': item.get('workflow_name'),
            'current_spend': float(item.get('current_spend') or 0.0),
            'budget_amount': float(item.get('budget_amount') or 0.0),
            'utilization': float(item.get('utilization') or 0.0),
            'window_hours': int(item.get('window_hours') or 0),
        }

    def _policy_overlay_items(
        self,
        gw: AdminGatewayLike,
        *,
        refs: dict[str, list[str]],
        traces: list[dict[str, Any]],
        approvals: list[dict[str, Any]],
        events: list[dict[str, Any]],
        scope: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        policy_engine = getattr(gw, 'policy', None)
        for trace in traces:
            for raw in list(trace.get('policies') or []):
                if not isinstance(raw, dict):
                    continue
                key = f"trace:{trace.get('trace_id')}:{raw.get('name')}:{raw.get('effect')}"
                if key in seen:
                    continue
                seen.add(key)
                items.append({
                    'source': 'trace',
                    'trace_id': trace.get('trace_id'),
                    'name': raw.get('name') or 'policy',
                    'effect': raw.get('effect') or 'unknown',
                    'reason': raw.get('reason') or '',
                })
        for tool_name in list(refs.get('tool_names') or []):
            if policy_engine is None or not hasattr(policy_engine, 'explain_request'):
                continue
            key = f'tool:{tool_name}'
            if key in seen:
                continue
            seen.add(key)
            try:
                explanation = policy_engine.explain_request(
                    scope='tool',
                    resource_name=tool_name,
                    agent_name='default',
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            except Exception:
                continue
            items.append({
                'source': 'explain_request',
                'resource': tool_name,
                'decision': (explanation.get('decision') or {}),
            })
        for approval in approvals:
            key = f"approval:{approval.get('approval_id')}"
            if key in seen:
                continue
            seen.add(key)
            items.append({
                'source': 'approval',
                'approval_id': approval.get('approval_id'),
                'workflow_id': approval.get('workflow_id'),
                'status': approval.get('status'),
                'requested_role': approval.get('requested_role'),
            })
        for event in list(events or []):
            payload = dict(event.get('payload') or {})
            action = str(payload.get('action') or '').strip()
            if action not in {'policy_blocked', 'policy_allowed', 'approval_required'}:
                continue
            items.append({
                'source': 'event',
                'action': action,
                'ts': event.get('ts'),
                'payload': payload,
            })
            if len(items) >= limit:
                break
        return items[:max(1, int(limit))]


