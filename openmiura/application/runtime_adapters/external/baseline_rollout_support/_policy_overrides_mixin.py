"""baseline_rollout_support._policy_overrides_mixin

Sub-mixin extracted from
``openmiura.application.runtime_adapters.external.baseline_rollout_support``
so that no individual file in the package exceeds 1,500 lines. The
public class ``OpenClawBaselineRolloutSupportMixin`` continues to
inherit from this sub-mixin.

The module-level ``OpenClawBaselineRolloutSupportMixin = None`` sentinel
is rebound by ``baseline_rollout_support/__init__.py`` so that the few
``@staticmethod`` call sites that reference the class by name resolve
correctly at call time.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OpenClawBaselineRolloutSupportMixin: type | None = None  # late-bound by __init__.py


class _OpenClawBaselineRolloutSupportPolicyOverridesMixin:
    """Sub-mixin: policy overrides methods on OpenClawBaselineRolloutSupportMixin."""

    @staticmethod
    def _baseline_promotion_simulation_custody_merge_policy_overrides(
        base: dict[str, Any] | None,
        overrides: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged = dict(base or {})
        for key, value in dict(overrides or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = OpenClawBaselineRolloutSupportMixin._baseline_promotion_simulation_custody_merge_policy_overrides(
                    dict(merged.get(key) or {}),
                    value,
                )
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _baseline_promotion_simulation_custody_policy_delta_keys(
        overrides: dict[str, Any] | None,
        *,
        prefix: str = '',
    ) -> list[str]:
        keys: list[str] = []
        for key, value in dict(overrides or {}).items():
            dotted = f'{prefix}.{key}' if prefix else str(key)
            if isinstance(value, dict):
                nested = OpenClawBaselineRolloutSupportMixin._baseline_promotion_simulation_custody_policy_delta_keys(value, prefix=dotted)
                if nested:
                    keys.extend(nested)
                else:
                    keys.append(dotted)
            else:
                keys.append(dotted)
        return keys

    @staticmethod
    def _normalize_baseline_promotion_simulation_custody_policy_what_if_pack(
        raw_pack: dict[str, Any] | None,
        *,
        actor: str = '',
        index: int = 1,
        source: str = 'saved',
    ) -> dict[str, Any]:
        payload = dict(raw_pack or {})
        pack_id = str(payload.get('pack_id') or payload.get('policy_pack_id') or payload.get('scenario_pack_id') or f'routing_policy_pack_{index}').strip() or f'routing_policy_pack_{index}'
        pack_label = str(payload.get('pack_label') or payload.get('label') or payload.get('scenario_pack_label') or pack_id.replace('_', ' ').title()).strip() or pack_id
        comparison_policies: list[dict[str, Any]] = []
        for scenario_index, raw_item in enumerate(list(payload.get('comparison_policies') or payload.get('scenarios') or []), start=1):
            item = dict(raw_item or {})
            overrides = dict(item.get('policy_overrides') or item.get('overrides') or {})
            if not overrides:
                overrides = {
                    key: value
                    for key, value in item.items()
                    if key not in {'scenario_id', 'scenario_label', 'label', 'policy_overrides', 'overrides'}
                }
            scenario_id = str(item.get('scenario_id') or f'{pack_id}_scenario_{scenario_index}').strip() or f'{pack_id}_scenario_{scenario_index}'
            scenario_label = str(item.get('scenario_label') or item.get('label') or scenario_id.replace('_', ' ').title()).strip() or scenario_id
            comparison_policies.append({
                'scenario_id': scenario_id,
                'scenario_label': scenario_label,
                'policy_overrides': overrides,
                'policy_delta_keys': OpenClawBaselineRolloutSupportMixin._baseline_promotion_simulation_custody_policy_delta_keys(overrides),
            })
        return {
            'pack_id': pack_id,
            'pack_label': pack_label,
            'description': str(payload.get('description') or payload.get('summary') or ''),
            'source': str(payload.get('source') or source or 'saved'),
            'category_keys': [str(item).strip() for item in list(payload.get('category_keys') or payload.get('categories') or payload.get('domains') or []) if str(item).strip()],
            'tags': [str(item).strip() for item in list(payload.get('tags') or []) if str(item).strip()],
            'comparison_policies': comparison_policies,
            'scenario_count': len(comparison_policies),
            'created_at': payload.get('created_at') or time.time(),
            'created_by': str(payload.get('created_by') or actor or ''),
            'last_used_at': payload.get('last_used_at'),
            'use_count': int(payload.get('use_count') or 0),
            'registry_entry_id': str(payload.get('registry_entry_id') or payload.get('registry_id') or ''),
            'registry_scope': str(payload.get('registry_scope') or payload.get('share_scope') or '').strip(),
            'promoted_at': payload.get('promoted_at'),
            'promoted_by': str(payload.get('promoted_by') or ''),
            'promoted_from_pack_id': str(payload.get('promoted_from_pack_id') or ''),
            'promoted_from_source': str(payload.get('promoted_from_source') or ''),
            'shared_from_pack_id': str(payload.get('shared_from_pack_id') or ''),
            'shared_from_source': str(payload.get('shared_from_source') or ''),
            'last_shared_at': payload.get('last_shared_at'),
            'last_shared_by': str(payload.get('last_shared_by') or ''),
            'share_count': int(payload.get('share_count') or 0),
            'share_targets': [str(item).strip() for item in list(payload.get('share_targets') or []) if str(item).strip()][:8],
            'catalog_entry_id': str(payload.get('catalog_entry_id') or payload.get('catalog_id') or payload.get('registry_entry_id') or ''),
            'catalog_scope': str(payload.get('catalog_scope') or payload.get('registry_scope') or '').strip(),
            'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
            'promotion_id': str(payload.get('promotion_id') or ''),
            'workspace_id': str(payload.get('workspace_id') or ''),
            'environment': str(payload.get('environment') or ''),
            'portfolio_family_id': str(payload.get('portfolio_family_id') or ''),
            'runtime_family_id': str(payload.get('runtime_family_id') or ''),
            'catalog_promoted_at': payload.get('catalog_promoted_at') or payload.get('promoted_at'),
            'catalog_promoted_by': str(payload.get('catalog_promoted_by') or payload.get('promoted_by') or ''),
            'catalog_share_count': int(payload.get('catalog_share_count') or payload.get('share_count') or 0),
            'catalog_last_shared_at': payload.get('catalog_last_shared_at') or payload.get('last_shared_at'),
            'catalog_last_shared_by': str(payload.get('catalog_last_shared_by') or payload.get('last_shared_by') or ''),
            'catalog_version_key': str(payload.get('catalog_version_key') or payload.get('version_key') or ''),
            'catalog_version': int(payload.get('catalog_version') or payload.get('version') or 0),
            'catalog_lifecycle_state': str(payload.get('catalog_lifecycle_state') or payload.get('catalog_status') or 'draft').strip() or 'draft',
            'catalog_curated_at': payload.get('catalog_curated_at'),
            'catalog_curated_by': str(payload.get('catalog_curated_by') or ''),
            'catalog_approved_at': payload.get('catalog_approved_at'),
            'catalog_approved_by': str(payload.get('catalog_approved_by') or ''),
            'catalog_deprecated_at': payload.get('catalog_deprecated_at'),
            'catalog_deprecated_by': str(payload.get('catalog_deprecated_by') or ''),
            'catalog_replaced_by_version': int(payload.get('catalog_replaced_by_version') or 0),
            'catalog_is_latest': bool(payload.get('catalog_is_latest', False)),
            'catalog_approval_required': bool(payload.get('catalog_approval_required', False)),
            'catalog_required_approvals': max(0, int(payload.get('catalog_required_approvals') or 0)),
            'catalog_approval_count': int(payload.get('catalog_approval_count') or 0),
            'catalog_approval_state': str(payload.get('catalog_approval_state') or ''),
            'catalog_approval_requested_at': payload.get('catalog_approval_requested_at'),
            'catalog_approval_requested_by': str(payload.get('catalog_approval_requested_by') or ''),
            'catalog_approval_rejected_at': payload.get('catalog_approval_rejected_at'),
            'catalog_approval_rejected_by': str(payload.get('catalog_approval_rejected_by') or ''),
            'catalog_approvals': [
                {
                    'approval_id': str(item.get('approval_id') or item.get('id') or ''),
                    'decision': str(item.get('decision') or ''),
                    'actor': str(item.get('actor') or item.get('approved_by') or item.get('requested_by') or ''),
                    'role': str(item.get('role') or item.get('requested_role') or ''),
                    'at': item.get('at') or item.get('approved_at') or item.get('requested_at'),
                    'note': str(item.get('note') or item.get('reason') or ''),
                }
                for item in list(payload.get('catalog_approvals') or [])[:12]
                if isinstance(item, dict)
            ],
            'catalog_review_state': str(payload.get('catalog_review_state') or '').strip(),
            'catalog_review_requested_at': payload.get('catalog_review_requested_at'),
            'catalog_review_requested_by': str(payload.get('catalog_review_requested_by') or ''),
            'catalog_review_assigned_reviewer': str(payload.get('catalog_review_assigned_reviewer') or ''),
            'catalog_review_assigned_role': str(payload.get('catalog_review_assigned_role') or ''),
            'catalog_review_claimed_by': str(payload.get('catalog_review_claimed_by') or ''),
            'catalog_review_claimed_at': payload.get('catalog_review_claimed_at'),
            'catalog_review_last_transition_at': payload.get('catalog_review_last_transition_at'),
            'catalog_review_last_transition_by': str(payload.get('catalog_review_last_transition_by') or ''),
            'catalog_review_last_transition_action': str(payload.get('catalog_review_last_transition_action') or ''),
            'catalog_review_decision_at': payload.get('catalog_review_decision_at'),
            'catalog_review_decision_by': str(payload.get('catalog_review_decision_by') or ''),
            'catalog_review_decision': str(payload.get('catalog_review_decision') or ''),
            'catalog_review_note_count': int(payload.get('catalog_review_note_count') or len(list(payload.get('catalog_review_events') or payload.get('catalog_review_timeline') or [])) or 0),
            'catalog_review_events': [
                {
                    'event_id': str(item.get('event_id') or item.get('review_event_id') or ''),
                    'event_type': str(item.get('event_type') or ''),
                    'state': str(item.get('state') or ''),
                    'actor': str(item.get('actor') or ''),
                    'role': str(item.get('role') or ''),
                    'at': item.get('at'),
                    'note': str(item.get('note') or ''),
                    'decision': str(item.get('decision') or ''),
                }
                for item in list(payload.get('catalog_review_events') or payload.get('catalog_review_timeline') or [])[:12]
                if isinstance(item, dict)
            ],
            'catalog_dependency_refs': [
                {
                    'dependency_id': str(item.get('dependency_id') or f'dependency-{index}').strip() or f'dependency-{index}',
                    'catalog_entry_id': str(item.get('catalog_entry_id') or item.get('entry_id') or '').strip(),
                    'catalog_version_key': str(item.get('catalog_version_key') or item.get('version_key') or '').strip(),
                    'min_catalog_version': max(0, int(item.get('min_catalog_version') or item.get('min_version') or 0)),
                    'required_lifecycle_state': str(item.get('required_lifecycle_state') or item.get('required_state') or 'approved').strip() or 'approved',
                    'required_release_state': str(item.get('required_release_state') or 'released').strip() or 'released',
                    'reason': str(item.get('reason') or item.get('note') or '').strip(),
                }
                for index, item in enumerate(list(payload.get('catalog_dependency_refs') or [])[:12], start=1)
                if isinstance(item, dict) and (str(item.get('catalog_entry_id') or item.get('entry_id') or '').strip() or str(item.get('catalog_version_key') or item.get('version_key') or '').strip())
            ],
            'catalog_conflict_rules': {
                'conflict_entry_ids': [str(item).strip() for item in list((payload.get('catalog_conflict_rules') or {}).get('conflict_entry_ids') or (payload.get('catalog_conflict_rules') or {}).get('entry_ids') or []) if str(item).strip()][:16],
                'conflict_version_keys': [str(item).strip() for item in list((payload.get('catalog_conflict_rules') or {}).get('conflict_version_keys') or (payload.get('catalog_conflict_rules') or {}).get('version_keys') or []) if str(item).strip()][:16],
                'conflict_category_keys': [str(item).strip() for item in list((payload.get('catalog_conflict_rules') or {}).get('conflict_category_keys') or (payload.get('catalog_conflict_rules') or {}).get('category_keys') or []) if str(item).strip()][:16],
                'conflict_tags': [str(item).strip() for item in list((payload.get('catalog_conflict_rules') or {}).get('conflict_tags') or (payload.get('catalog_conflict_rules') or {}).get('tags') or []) if str(item).strip()][:16],
                'enforce_same_scope': bool((payload.get('catalog_conflict_rules') or {}).get('enforce_same_scope', True)),
            },
            'catalog_freeze_windows': [
                {
                    'window_id': str(item.get('window_id') or f'catalog-freeze-{index}').strip() or f'catalog-freeze-{index}',
                    'label': str(item.get('label') or item.get('name') or f'catalog-freeze-{index}').strip() or f'catalog-freeze-{index}',
                    'start_at': float(item.get('start_at')) if item.get('start_at') is not None else None,
                    'end_at': float(item.get('end_at')) if item.get('end_at') is not None else None,
                    'reason': str(item.get('reason') or '').strip(),
                    'block_stage': bool(item.get('block_stage', True)),
                    'block_release': bool(item.get('block_release', True)),
                    'block_advance': bool(item.get('block_advance', True)),
                }
                for index, item in enumerate(list(payload.get('catalog_freeze_windows') or [])[:12], start=1)
                if isinstance(item, dict)
            ],
            'catalog_release_state': str(payload.get('catalog_release_state') or 'draft').strip() or 'draft',
            'catalog_release_notes': str(payload.get('catalog_release_notes') or ''),
            'catalog_release_train_id': str(payload.get('catalog_release_train_id') or ''),
            'catalog_release_staged_at': payload.get('catalog_release_staged_at'),
            'catalog_release_staged_by': str(payload.get('catalog_release_staged_by') or ''),
            'catalog_released_at': payload.get('catalog_released_at'),
            'catalog_released_by': str(payload.get('catalog_released_by') or ''),
            'catalog_withdrawn_at': payload.get('catalog_withdrawn_at'),
            'catalog_withdrawn_by': str(payload.get('catalog_withdrawn_by') or ''),
            'catalog_withdrawn_reason': str(payload.get('catalog_withdrawn_reason') or ''),
            'catalog_supersedence_state': str(payload.get('catalog_supersedence_state') or ''),
            'catalog_superseded_at': payload.get('catalog_superseded_at'),
            'catalog_superseded_by': str(payload.get('catalog_superseded_by') or ''),
            'catalog_superseded_reason': str(payload.get('catalog_superseded_reason') or ''),
            'catalog_superseded_by_entry_id': str(payload.get('catalog_superseded_by_entry_id') or ''),
            'catalog_superseded_by_version': int(payload.get('catalog_superseded_by_version') or 0),
            'catalog_superseded_by_bundle_id': str(payload.get('catalog_superseded_by_bundle_id') or ''),
            'catalog_supersedes_entry_id': str(payload.get('catalog_supersedes_entry_id') or ''),
            'catalog_supersedes_version': int(payload.get('catalog_supersedes_version') or 0),
            'catalog_restored_from_entry_id': str(payload.get('catalog_restored_from_entry_id') or ''),
            'catalog_restored_from_version': int(payload.get('catalog_restored_from_version') or 0),
            'catalog_restored_at': payload.get('catalog_restored_at'),
            'catalog_restored_by': str(payload.get('catalog_restored_by') or ''),
            'catalog_restored_reason': str(payload.get('catalog_restored_reason') or ''),
            'catalog_rollback_release_state': str(payload.get('catalog_rollback_release_state') or ''),
            'catalog_rollback_release_at': payload.get('catalog_rollback_release_at'),
            'catalog_rollback_release_by': str(payload.get('catalog_rollback_release_by') or ''),
            'catalog_rollback_release_reason': str(payload.get('catalog_rollback_release_reason') or ''),
            'catalog_rollback_target_entry_id': str(payload.get('catalog_rollback_target_entry_id') or ''),
            'catalog_rollback_target_version': int(payload.get('catalog_rollback_target_version') or 0),
            'catalog_emergency_withdrawal_active': bool(payload.get('catalog_emergency_withdrawal_active', False)),
            'catalog_emergency_withdrawal_at': payload.get('catalog_emergency_withdrawal_at'),
            'catalog_emergency_withdrawal_by': str(payload.get('catalog_emergency_withdrawal_by') or ''),
            'catalog_emergency_withdrawal_reason': str(payload.get('catalog_emergency_withdrawal_reason') or ''),
            'catalog_emergency_withdrawal_incident_id': str(payload.get('catalog_emergency_withdrawal_incident_id') or ''),
            'catalog_emergency_withdrawal_severity': str(payload.get('catalog_emergency_withdrawal_severity') or ''),
            'catalog_rollout_enabled': bool(payload.get('catalog_rollout_enabled', False)),
            'catalog_rollout_policy': {
                'enabled': bool((payload.get('catalog_rollout_policy') or {}).get('enabled', False)),
                'wave_size': max(1, int(((payload.get('catalog_rollout_policy') or {}).get('wave_size') or 1))),
                'require_manual_advance': bool((payload.get('catalog_rollout_policy') or {}).get('require_manual_advance', True)),
                'require_evidence_package': bool((payload.get('catalog_rollout_policy') or {}).get('require_evidence_package', False)),
                'require_signed_bundle': bool((payload.get('catalog_rollout_policy') or {}).get('require_signed_bundle', False)),
            },
            'catalog_rollout_train_id': str(payload.get('catalog_rollout_train_id') or ''),
            'catalog_rollout_state': str(payload.get('catalog_rollout_state') or ''),
            'catalog_rollout_current_wave_index': int(payload.get('catalog_rollout_current_wave_index') or 0),
            'catalog_rollout_completed_wave_count': int(payload.get('catalog_rollout_completed_wave_count') or 0),
            'catalog_rollout_paused': bool(payload.get('catalog_rollout_paused', False)),
            'catalog_rollout_frozen': bool(payload.get('catalog_rollout_frozen', False)),
            'catalog_rollout_started_at': payload.get('catalog_rollout_started_at'),
            'catalog_rollout_started_by': str(payload.get('catalog_rollout_started_by') or ''),
            'catalog_rollout_completed_at': payload.get('catalog_rollout_completed_at'),
            'catalog_rollout_completed_by': str(payload.get('catalog_rollout_completed_by') or ''),
            'catalog_rollout_rolled_back_at': payload.get('catalog_rollout_rolled_back_at'),
            'catalog_rollout_rolled_back_by': str(payload.get('catalog_rollout_rolled_back_by') or ''),
            'catalog_rollout_rolled_back_reason': str(payload.get('catalog_rollout_rolled_back_reason') or ''),
            'catalog_rollout_last_transition_at': payload.get('catalog_rollout_last_transition_at'),
            'catalog_rollout_last_transition_by': str(payload.get('catalog_rollout_last_transition_by') or ''),
            'catalog_rollout_last_transition_action': str(payload.get('catalog_rollout_last_transition_action') or ''),
            'catalog_rollout_latest_gate': dict(payload.get('catalog_rollout_latest_gate') or {}),
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
                for item in list(payload.get('catalog_rollout_targets') or [])[:24]
                if isinstance(item, dict)
            ],
            'catalog_rollout_waves': [
                {
                    'wave_index': int(item.get('wave_index') or 0),
                    'status': str(item.get('status') or ''),
                    'target_keys': [str(key) for key in list(item.get('target_keys') or []) if str(key)][:24],
                    'released_at': item.get('released_at'),
                    'released_by': str(item.get('released_by') or ''),
                    'gate_evaluation': dict(item.get('gate_evaluation') or {}),
                }
                for item in list(payload.get('catalog_rollout_waves') or [])[:12]
                if isinstance(item, dict)
            ],
            'catalog_attestation_count': int(payload.get('catalog_attestation_count') or 0),
            'catalog_latest_attestation': dict(payload.get('catalog_latest_attestation') or {}),
            'catalog_evidence_package_count': int(payload.get('catalog_evidence_package_count') or 0),
            'catalog_latest_evidence_package': dict(payload.get('catalog_latest_evidence_package') or {}),
            'catalog_release_bundle_count': int(payload.get('catalog_release_bundle_count') or 0),
            'catalog_latest_release_bundle': dict(payload.get('catalog_latest_release_bundle') or {}),
            'catalog_compliance_summary': dict(payload.get('catalog_compliance_summary') or {}),
            'catalog_compliance_report_count': int(payload.get('catalog_compliance_report_count') or 0),
            'catalog_latest_compliance_report': dict(payload.get('catalog_latest_compliance_report') or {}),
            'catalog_replay_count': int(payload.get('catalog_replay_count') or 0),
            'catalog_last_replayed_at': payload.get('catalog_last_replayed_at'),
            'catalog_last_replayed_by': str(payload.get('catalog_last_replayed_by') or ''),
            'catalog_last_replay_source': str(payload.get('catalog_last_replay_source') or ''),
            'catalog_binding_count': int(payload.get('catalog_binding_count') or 0),
            'catalog_last_bound_at': payload.get('catalog_last_bound_at'),
            'catalog_last_bound_by': str(payload.get('catalog_last_bound_by') or ''),
            'catalog_analytics_summary': dict(payload.get('catalog_analytics_summary') or {}),
            'catalog_analytics_report_count': int(payload.get('catalog_analytics_report_count') or 0),
            'catalog_latest_analytics_report': dict(payload.get('catalog_latest_analytics_report') or {}),
            'organizational_service_id': str(payload.get('organizational_service_id') or payload.get('organizational_catalog_service_id') or ''),
            'organizational_service_entry_id': str(payload.get('organizational_service_entry_id') or payload.get('organizational_catalog_service_entry_id') or ''),
            'organizational_publish_state': str(payload.get('organizational_publish_state') or payload.get('organizational_state') or ''),
            'organizational_visibility': str(payload.get('organizational_visibility') or 'tenant').strip() or 'tenant',
            'organizational_service_scope_key': str(payload.get('organizational_service_scope_key') or ''),
            'organizational_published_at': payload.get('organizational_published_at'),
            'organizational_published_by': str(payload.get('organizational_published_by') or ''),
            'organizational_withdrawn_at': payload.get('organizational_withdrawn_at'),
            'organizational_withdrawn_by': str(payload.get('organizational_withdrawn_by') or ''),
            'organizational_withdrawn_reason': str(payload.get('organizational_withdrawn_reason') or ''),
            'organizational_publication_manifest': dict(payload.get('organizational_publication_manifest') or {}),
            'organizational_publication_health': dict(payload.get('organizational_publication_health') or {}),
            'organizational_reconciliation_report_count': int(payload.get('organizational_reconciliation_report_count') or 0),
            'organizational_latest_reconciliation_report': dict(payload.get('organizational_latest_reconciliation_report') or {}),
        }

    def _baseline_promotion_simulation_custody_builtin_policy_what_if_packs(
        self,
        policy: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(policy or {}))
        queue_policy = dict(normalized_policy.get('queue_capacity_policy') or {})
        expedite_threshold = int(queue_policy.get('expedite_threshold_s') or 300)
        overload_load_threshold = float(queue_policy.get('overload_projected_load_ratio_threshold') or 1.0)
        overload_wait_threshold = int(queue_policy.get('overload_projected_wait_time_threshold_s') or 900)
        builtins = [
            {
                'pack_id': 'family_hysteresis_presets',
                'pack_label': 'Families + hysteresis presets',
                'description': 'Compare queue families and family hysteresis behaviour under equivalent routing options.',
                'source': 'builtin',
                'category_keys': ['families', 'hysteresis'],
                'tags': ['queue-families', 'hysteresis'],
                'comparison_policies': [
                    {'scenario_id': 'disable_family_hysteresis', 'scenario_label': 'Disable family hysteresis', 'policy_overrides': {'queue_capacity_policy': {'multi_hop_hysteresis_enabled': False}}},
                    {'scenario_id': 'disable_queue_families', 'scenario_label': 'Disable queue families', 'policy_overrides': {'queue_capacity_policy': {'queue_families_enabled': False}}},
                    {'scenario_id': 'relax_family_hysteresis', 'scenario_label': 'Relax family hysteresis thresholds', 'policy_overrides': {'queue_capacity_policy': {'multi_hop_hysteresis_enabled': True, 'family_min_active_delta': max(0, int(queue_policy.get('family_min_active_delta') or 1) - 1), 'family_min_load_delta': max(0.0, float(queue_policy.get('family_min_load_delta') or 0.2) / 2.0), 'family_min_projected_wait_delta_s': max(30, int(queue_policy.get('family_min_projected_wait_delta_s') or 120) // 2)}}},
                ],
            },
            {
                'pack_id': 'sla_expedite_presets',
                'pack_label': 'SLA + expedite presets',
                'description': 'Compare deadline protection, breach prediction and expedite sensitivity.',
                'source': 'builtin',
                'category_keys': ['sla', 'expedite'],
                'tags': ['sla', 'expedite'],
                'comparison_policies': [
                    {'scenario_id': 'disable_expedite', 'scenario_label': 'Disable expedite', 'policy_overrides': {'queue_capacity_policy': {'expedite_enabled': False}}},
                    {'scenario_id': 'aggressive_expedite', 'scenario_label': 'Aggressive expedite thresholds', 'policy_overrides': {'queue_capacity_policy': {'breach_prediction_enabled': True, 'expedite_enabled': True, 'expedite_threshold_s': max(expedite_threshold, 600)}}},
                    {'scenario_id': 'disable_breach_prediction', 'scenario_label': 'Disable breach prediction', 'policy_overrides': {'queue_capacity_policy': {'breach_prediction_enabled': False}}},
                ],
            },
            {
                'pack_id': 'admission_overload_presets',
                'pack_label': 'Admission + overload presets',
                'description': 'Compare admission control and overload governance under stricter or more lenient thresholds.',
                'source': 'builtin',
                'category_keys': ['admission', 'overload'],
                'tags': ['admission', 'overload'],
                'comparison_policies': [
                    {'scenario_id': 'disable_admission_control', 'scenario_label': 'Disable admission control', 'policy_overrides': {'queue_capacity_policy': {'admission_control_enabled': False}}},
                    {'scenario_id': 'disable_overload_governance', 'scenario_label': 'Disable overload governance', 'policy_overrides': {'queue_capacity_policy': {'overload_governance_enabled': False}}},
                    {'scenario_id': 'lenient_overload_thresholds', 'scenario_label': 'Lenient overload thresholds', 'policy_overrides': {'queue_capacity_policy': {'overload_governance_enabled': True, 'overload_projected_load_ratio_threshold': max(overload_load_threshold, 1.25), 'overload_projected_wait_time_threshold_s': max(overload_wait_threshold, 1200)}}},
                ],
            },
        ]
        return [self._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor='system', index=index, source='builtin') for index, item in enumerate(builtins, start=1)]

