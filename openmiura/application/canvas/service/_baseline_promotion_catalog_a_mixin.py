"""openmiura.application.canvas.service._baseline_promotion_catalog_a_mixin

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

class _LiveCanvasBaselinePromotionCatalogAMixin:
    """Mixin: baseline promotion catalog a methods on LiveCanvasService."""

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

