"""openmiura.application.canvas.service._node_data_mixin

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


class _LiveCanvasNodeDataMixin:
    """Mixin: node data methods on LiveCanvasService."""

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

