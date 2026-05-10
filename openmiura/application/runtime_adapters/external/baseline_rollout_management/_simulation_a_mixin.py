"""baseline_rollout_management._simulation_a_mixin"""
from __future__ import annotations

import time
import uuid
from typing import Any




OpenClawBaselineRolloutManagementMixin: type | None = None  # late-bound by __init__.py


class _OpenClawBaselineRolloutManagementMixinSimulationAMixin:
    """Sub-mixin: simulation_a."""

    def get_runtime_alert_governance_baseline_simulation_custody_dashboard(
        self,
        gw,
        *,
        limit: int = 100,
        only_active: bool = False,
        only_blocked: bool = False,
        only_escalated: bool = False,
        only_suppressed: bool = False,
        only_unowned: bool = False,
        only_claimed: bool = False,
        only_sla_breached: bool = False,
        only_handoff_pending: bool = False,
        only_sla_rerouted: bool = False,
        queue_id: str | None = None,
        team_queue_id: str | None = None,
        owner_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        releases = gw.audit.list_release_bundles(
            limit=max(limit * 5, limit),
            kind='policy_baseline_promotion',
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        normalized_queue_id = str(queue_id or '').strip()
        normalized_team_queue_id = str(team_queue_id or '').strip()
        normalized_owner_id = str(owner_id or '').strip()
        queue_state = self._baseline_promotion_simulation_custody_queue_capacity_state(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        queue_state_items = dict(queue_state.get('queues') or {})
        items: list[dict[str, Any]] = []
        for release in releases:
            if not self._is_baseline_promotion_release(release):
                continue
            metadata = dict(release.get('metadata') or {})
            promotion = dict(metadata.get('baseline_promotion') or {})
            alerts = self._baseline_promotion_simulation_custody_alerts(release)
            alerts_summary = self._baseline_promotion_simulation_custody_alerts_summary(alerts)
            guard = self._baseline_promotion_simulation_custody_guard(release)
            policy = self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release)
            current_reconciliation = dict(promotion.get('current_simulation_evidence_reconciliation') or {})
            reconciliation_summary = dict(current_reconciliation.get('summary') or {})
            active_alert = next((item for item in alerts if bool(item.get('active'))), {})
            active_ownership = dict(active_alert.get('ownership') or {})
            active_routing = dict(active_alert.get('routing') or {})
            active_handoff = dict(active_alert.get('handoff') or {})
            active_sla = dict(active_alert.get('sla') or active_alert.get('sla_state') or {})
            if only_active and not bool(alerts_summary.get('active_count')):
                continue
            if only_blocked and not bool(guard.get('blocked')):
                continue
            if only_escalated and not bool(alerts_summary.get('active_escalated_count') or alerts_summary.get('escalated_count')):
                continue
            if only_suppressed and not bool(alerts_summary.get('active_suppressed_count') or alerts_summary.get('suppressed_count')):
                continue
            if only_unowned and not bool(alerts_summary.get('active_unowned_count') or alerts_summary.get('unassigned_count')):
                continue
            if only_claimed and not bool(alerts_summary.get('active_claimed_count') or alerts_summary.get('claimed_count')):
                continue
            if only_sla_breached and not bool(alerts_summary.get('active_sla_breached_count') or alerts_summary.get('sla_breached_count')):
                continue
            if only_handoff_pending and not bool(alerts_summary.get('active_handoff_pending_count') or alerts_summary.get('pending_handoff_count')):
                continue
            if only_sla_rerouted and not bool(alerts_summary.get('active_sla_rerouted_count') or alerts_summary.get('sla_rerouted_count')):
                continue
            if normalized_queue_id and str(active_ownership.get('queue_id') or active_routing.get('queue_id') or '') != normalized_queue_id:
                continue
            if normalized_team_queue_id and str((active_alert.get('sla_routing_state') or {}).get('last_queue_id') or active_routing.get('queue_id') or '') != normalized_team_queue_id:
                continue
            if normalized_owner_id and str(active_ownership.get('owner_id') or '') != normalized_owner_id:
                continue
            queue_live = dict(queue_state_items.get(str(active_ownership.get('queue_id') or active_routing.get('queue_id') or '')) or {})
            items.append({
                'promotion_id': str(release.get('release_id') or ''),
                'status': str(release.get('status') or ''),
                'environment': str(release.get('environment') or ''),
                'catalog_id': str(promotion.get('catalog_id') or ''),
                'catalog_name': str(promotion.get('catalog_name') or ''),
                'candidate_catalog_version': str(promotion.get('candidate_catalog_version') or release.get('version') or ''),
                'guard': guard,
                'alerts': {
                    'items': alerts[:5],
                    'summary': alerts_summary,
                },
                'reconciliation': {
                    'reconciliation_id': str(current_reconciliation.get('reconciliation_id') or ''),
                    'summary': reconciliation_summary,
                },
                'jobs': self.list_baseline_promotion_simulation_custody_jobs(
                    gw,
                    limit=10,
                    promotion_id=str(release.get('release_id') or ''),
                    tenant_id=release.get('tenant_id'),
                    workspace_id=release.get('workspace_id'),
                    environment=release.get('environment'),
                ),
                'policy': policy,
                'active_alert': {
                    'alert_id': str(active_alert.get('alert_id') or ''),
                    'status': str(active_alert.get('status') or ''),
                    'severity': str(active_alert.get('severity') or ''),
                    'escalation_level': int(active_alert.get('escalation_level') or 0),
                    'ownership': active_ownership,
                    'routing': active_routing,
                    'queue_live': queue_live,
                    'handoff': active_handoff,
                    'sla': active_sla,
                    'sla_routing': dict(active_alert.get('sla_routing_state') or {}),
                },
                'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
            })
        items.sort(
            key=lambda item: (
                1 if bool((item.get('guard') or {}).get('blocked')) else 0,
                int((((item.get('alerts') or {}).get('summary')) or {}).get('active_count') or 0),
                int((((item.get('alerts') or {}).get('summary')) or {}).get('active_escalated_count') or 0),
                int((((item.get('reconciliation') or {}).get('summary')) or {}).get('drifted_count') or 0),
                str(item.get('promotion_id') or ''),
            ),
            reverse=True,
        )
        items = items[: max(1, int(limit or 100))]
        return {
            'ok': True,
            'items': items,
            'summary': {
                'promotion_count': len(items),
                'blocked_count': sum(1 for item in items if bool((item.get('guard') or {}).get('blocked'))),
                'active_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_count') or 0) for item in items),
                'acknowledged_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('acknowledged_count') or 0) for item in items),
                'muted_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('muted_count') or 0) for item in items),
                'resolved_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('resolved_count') or 0) for item in items),
                'recovered_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('recovered_count') or 0) for item in items),
                'drifted_count': sum(1 for item in items if str((((item.get('reconciliation') or {}).get('summary')) or {}).get('overall_status') or '') == 'drifted'),
                'open_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('open_count') or 0) for item in items),
                'escalated_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('escalated_count') or 0) for item in items),
                'active_escalated_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_escalated_count') or 0) for item in items),
                'suppressed_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('suppressed_count') or 0) for item in items),
                'active_suppressed_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_suppressed_count') or 0) for item in items),
                'critical_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('critical_count') or 0) for item in items),
                'pending_escalation_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('pending_escalation_count') or 0) for item in items),
                'owned_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('owned_count') or 0) for item in items),
                'active_owned_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_owned_count') or 0) for item in items),
                'claimed_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('claimed_count') or 0) for item in items),
                'active_claimed_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_claimed_count') or 0) for item in items),
                'unassigned_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('unassigned_count') or 0) for item in items),
                'active_unowned_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_unowned_count') or 0) for item in items),
                'routed_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('routed_count') or 0) for item in items),
                'handoff_pending_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_handoff_pending_count') or (((item.get('alerts') or {}).get('summary')) or {}).get('pending_handoff_count') or 0) for item in items),
                'sla_breached_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_sla_breached_count') or (((item.get('alerts') or {}).get('summary')) or {}).get('sla_breached_count') or 0) for item in items),
                'sla_warning_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('sla_warning_count') or 0) for item in items),
                'sla_rerouted_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_sla_rerouted_count') or (((item.get('alerts') or {}).get('summary')) or {}).get('sla_rerouted_count') or 0) for item in items),
                'team_queue_alert_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_team_queue_alert_count') or (((item.get('alerts') or {}).get('summary')) or {}).get('team_queue_alert_count') or 0) for item in items),
                'queue_at_capacity_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_queue_at_capacity_count') or (((item.get('alerts') or {}).get('summary')) or {}).get('queue_at_capacity_count') or 0) for item in items),
                'queue_over_capacity_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_queue_over_capacity_count') or (((item.get('alerts') or {}).get('summary')) or {}).get('queue_over_capacity_count') or 0) for item in items),
                'load_aware_routed_count': sum(int((((item.get('alerts') or {}).get('summary')) or {}).get('active_load_aware_routed_count') or (((item.get('alerts') or {}).get('summary')) or {}).get('load_aware_routed_count') or 0) for item in items),
                'queue_capacity': dict(queue_state.get('summary') or {}),
            },
            'queue_capacity': queue_state,
            'scope': self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
        }

    @staticmethod
    def _baseline_promotion_simulation_ttl_s(promotion_policy: dict[str, Any] | None) -> int:
        payload = dict(promotion_policy or {})
        raw_value = payload.get('simulation_ttl_s')
        if raw_value is None:
            raw_value = payload.get('ttl_s')
        if raw_value is None and isinstance(payload.get('simulation_policy'), dict):
            raw_value = dict(payload.get('simulation_policy') or {}).get('ttl_s')
        try:
            ttl_s = int(raw_value or 0)
        except Exception:
            ttl_s = 0
        return max(0, ttl_s)

    def _baseline_promotion_simulation_review_policy(self, simulation_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(simulation_policy or {})
        raw_policy = dict(payload.get('approval_policy') or payload.get('review_policy') or {})
        approval_policy = self._normalize_portfolio_approval_policy(raw_policy)
        return {
            'enabled': bool(approval_policy.get('enabled')),
            'approval_policy': approval_policy,
            'allow_self_review': bool(payload.get('allow_self_review', True)),
            'require_reason': bool(payload.get('require_reason', False)),
            'block_on_rejection': bool(payload.get('block_on_rejection', approval_policy.get('block_on_rejection', True))),
        }

    def _baseline_promotion_simulation_review_state(
        self,
        *,
        review_policy: dict[str, Any] | None,
        review_state: dict[str, Any] | None = None,
        legacy_review: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = dict(review_policy or {})
        approval_policy = self._normalize_portfolio_approval_policy(dict(policy.get('approval_policy') or {}))
        items: list[dict[str, Any]] = []
        for raw_item in list((review_state or {}).get('items') or []):
            item = dict(raw_item or {})
            decision = str(item.get('decision') or '').strip().lower()
            if decision in {'approved', 'approve'}:
                decision = 'approve'
            elif decision in {'rejected', 'reject'}:
                decision = 'reject'
            else:
                continue
            layer_id = str(item.get('layer_id') or '').strip()
            if not layer_id and len(list(approval_policy.get('layers') or [])) == 1:
                layer_id = str(((approval_policy.get('layers') or [])[0].get('layer_id') or '')).strip()
            items.append({
                'review_id': str(item.get('review_id') or self._stable_digest(item)[:24]),
                'layer_id': layer_id,
                'label': str(item.get('label') or layer_id),
                'requested_role': str(item.get('requested_role') or ''),
                'decision': decision,
                'actor': str(item.get('actor') or item.get('reviewed_by') or ''),
                'reason': str(item.get('reason') or ''),
                'created_at': float(item.get('created_at') or item.get('decided_at') or time.time()),
                'decided_at': float(item.get('decided_at') or item.get('created_at') or time.time()),
            })
        synthetic_approvals = [
            {
                'approval_id': item.get('review_id'),
                'status': 'approved' if str(item.get('decision') or '') == 'approve' else 'rejected',
                'created_at': item.get('created_at'),
                'decided_at': item.get('decided_at'),
                'decided_by': item.get('actor'),
                'payload': {'layer_id': item.get('layer_id')},
            }
            for item in items if str(item.get('layer_id') or '').strip()
        ]
        approval_state = self._portfolio_approval_state(
            portfolio_id='baseline-simulation',
            approval_policy=approval_policy,
            approvals=synthetic_approvals,
        )
        required = bool(policy.get('enabled', approval_policy.get('enabled'))) and bool(list(approval_policy.get('layers') or []))
        latest_item = max(items, key=lambda entry: (float(entry.get('decided_at') or 0.0), str(entry.get('review_id') or '')), default=None)
        if required:
            approved = bool(approval_state.get('satisfied'))
            rejected = int(approval_state.get('rejected_count') or 0) > 0
            pending_layers = [
                str(layer.get('layer_id') or '')
                for layer in list(approval_state.get('layers') or [])
                if str(layer.get('status') or '') not in {'approved', 'optional'}
            ]
            layer_states = [dict(item) for item in list(approval_state.get('layers') or [])]
            next_layer = dict(approval_state.get('next_layer') or {})
            if approved:
                overall_status = 'approved'
            elif rejected:
                overall_status = 'rejected'
            elif items:
                overall_status = 'in_review'
            else:
                overall_status = 'not_requested'
        else:
            legacy = dict(legacy_review or {})
            approved = bool(legacy.get('approved'))
            rejected = bool(legacy.get('rejected'))
            overall_status = 'approved' if approved else ('rejected' if rejected else 'not_required')
            pending_layers = []
            layer_states = []
            next_layer = {}
        return {
            'required': required,
            'enabled': required,
            'mode': str(approval_policy.get('mode') or ('none' if not required else 'sequential')),
            'allow_self_review': bool(policy.get('allow_self_review', True)),
            'require_reason': bool(policy.get('require_reason', False)),
            'block_on_rejection': bool(policy.get('block_on_rejection', True)),
            'review_count': len(items),
            'approved': approved,
            'rejected': rejected,
            'overall_status': overall_status,
            'pending_layers': self._baseline_promotion_unique_ids(pending_layers),
            'next_layer': next_layer,
            'layers': layer_states,
            'items': items,
            'latest_review': dict(latest_item or {}),
            'approved_count': int(approval_state.get('approved_count') or (1 if approved else 0)),
            'rejected_count': int(approval_state.get('rejected_count') or (1 if rejected else 0)),
            'pending_count': int(len(pending_layers) if required else 0),
            'satisfied': approved,
        }

    @staticmethod
    def _baseline_promotion_simulation_review_summary(review_state: dict[str, Any] | None, legacy_review: dict[str, Any] | None = None) -> dict[str, Any]:
        state = dict(review_state or {})
        latest = dict(state.get('latest_review') or {})
        if bool(state.get('approved')):
            return {
                'approved': True,
                'approved_at': latest.get('decided_at') or latest.get('created_at') or (legacy_review or {}).get('approved_at'),
                'approved_by': latest.get('actor') or (legacy_review or {}).get('approved_by'),
                'reason': latest.get('reason') or (legacy_review or {}).get('reason') or '',
                'review_count': int(state.get('review_count') or 0),
                'decision': 'approve',
            }
        if bool(state.get('rejected')):
            return {
                'approved': False,
                'rejected': True,
                'rejected_at': latest.get('decided_at') or latest.get('created_at') or (legacy_review or {}).get('rejected_at'),
                'rejected_by': latest.get('actor') or (legacy_review or {}).get('rejected_by'),
                'reason': latest.get('reason') or (legacy_review or {}).get('reason') or '',
                'review_count': int(state.get('review_count') or 0),
                'decision': 'reject',
            }
        legacy = dict(legacy_review or {})
        if bool(legacy):
            return legacy
        if bool(state.get('required')):
            return {
                'approved': False,
                'review_required': True,
                'review_count': int(state.get('review_count') or 0),
                'pending_layers': [str(item) for item in list(state.get('pending_layers') or []) if str(item)],
            }
        return {}

    def _baseline_promotion_simulation_diff(
        self,
        *,
        previous_baselines: dict[str, Any] | None,
        candidate_baselines: dict[str, Any] | None,
    ) -> dict[str, Any]:
        previous = self._normalize_baseline_catalog_environment_entries(previous_baselines)
        candidate = self._normalize_baseline_catalog_environment_entries(candidate_baselines)
        envs = sorted(set(previous) | set(candidate))
        items: list[dict[str, Any]] = []
        changed_environment_count = 0
        changed_field_count = 0
        for env_key in envs:
            baseline_entry = dict(previous.get(env_key) or {})
            candidate_entry = dict(candidate.get(env_key) or {})
            compare = self._portfolio_policy_baseline_compare_view(baseline=baseline_entry, effective=candidate_entry)
            changed = baseline_entry != candidate_entry
            if changed:
                changed_environment_count += 1
                changed_field_count += len(list(compare.get('items') or []))
            items.append({
                'environment': env_key,
                'changed': changed,
                'change_type': ('added' if not baseline_entry and candidate_entry else ('removed' if baseline_entry and not candidate_entry else ('changed' if changed else 'unchanged'))),
                'compare': compare,
                'baseline_fingerprint': self._stable_digest(baseline_entry),
                'candidate_fingerprint': self._stable_digest(candidate_entry),
                'baseline_configured': bool(baseline_entry),
                'candidate_configured': bool(candidate_entry),
            })
        return {
            'items': items,
            'summary': {
                'environment_count': len(envs),
                'changed_environment_count': changed_environment_count,
                'unchanged_environment_count': max(0, len(envs) - changed_environment_count),
                'changed_field_count': changed_field_count,
                'baseline_fingerprint': self._stable_digest(previous),
                'candidate_fingerprint': self._stable_digest(candidate),
            },
        }

    def _baseline_promotion_simulation_explainability(
        self,
        *,
        diff: dict[str, Any],
        validation_errors: list[dict[str, Any]] | None,
        wave_items: list[dict[str, Any]] | None,
        approval_preview: dict[str, Any] | None,
        approvable: bool,
        stale: bool = False,
        expired: bool = False,
        stale_reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        blocking_reasons: list[str] = []
        advisory_reasons: list[str] = []
        if list(validation_errors or []):
            blocking_reasons.append('validation_failed')
        failing_waves = [dict(item) for item in list(wave_items or []) if str(((item.get('gate_evaluation') or {}).get('status') or '')) == 'failed']
        if failing_waves:
            blocking_reasons.append('wave_gate_failed')
        calendar_blocked = [dict(item) for item in list(wave_items or []) if not bool((item.get('calendar_decision') or {}).get('allowed', False))]
        if calendar_blocked:
            advisory_reasons.append('calendar_window_constraints')
        if bool((approval_preview or {}).get('required')):
            advisory_reasons.append('approval_required')
        if stale:
            blocking_reasons.append('simulation_stale')
        if expired:
            blocking_reasons.append('simulation_expired')
        if list(stale_reasons or []):
            advisory_reasons.extend([str(item) for item in list(stale_reasons or []) if str(item)])
        decision = 'approvable' if approvable and not stale and not expired else 'blocked'
        if decision == 'blocked' and not blocking_reasons:
            blocking_reasons.append('simulation_not_approvable')
        changed_envs = [str(item.get('environment') or '') for item in list((diff.get('items') or [])) if bool(item.get('changed'))]
        return {
            'decision': decision,
            'blocking_reasons': self._baseline_promotion_unique_ids(blocking_reasons),
            'advisory_reasons': self._baseline_promotion_unique_ids(advisory_reasons),
            'changed_environments': [item for item in changed_envs if item],
            'changed_environment_count': int((diff.get('summary') or {}).get('changed_environment_count') or 0),
            'changed_field_count': int((diff.get('summary') or {}).get('changed_field_count') or 0),
            'summary': (
                'Simulation is approvable.'
                if decision == 'approvable'
                else 'Simulation is blocked because validation, gating, freshness, or expiry constraints are no longer satisfied.'
            ),
        }

    def _baseline_promotion_simulation_observation(
        self,
        gw,
        *,
        catalog_release: dict[str, Any] | None,
        candidate_baselines: dict[str, Any] | None,
        request: dict[str, Any] | None = None,
        simulation_source: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        catalog_meta = dict(((catalog_release or {}).get('metadata') or {}).get('baseline_catalog') or {})
        current_baselines = self._normalize_baseline_catalog_environment_entries(dict(catalog_meta.get('current_baselines') or {}))
        candidate_entries = self._normalize_baseline_catalog_environment_entries(candidate_baselines)
        request_payload = {
            'catalog_id': str((request or {}).get('catalog_id') or ((catalog_release or {}).get('release_id') or '') or ''),
            'candidate_baselines': candidate_entries,
            'version': (request or {}).get('version'),
            'rollout_policy': dict((request or {}).get('rollout_policy') or {}),
            'gate_policy': dict((request or {}).get('gate_policy') or {}),
            'rollback_policy': dict((request or {}).get('rollback_policy') or {}),
        }
        source_snapshot: dict[str, Any] = {}
        source = dict(simulation_source or {})
        if str(source.get('kind') or '') == 'baseline_promotion' and str(source.get('promotion_id') or '').strip():
            source_release = gw.audit.get_release_bundle(
                str(source.get('promotion_id') or '').strip(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            if source_release is None:
                source_snapshot = {
                    'kind': 'baseline_promotion',
                    'promotion_id': str(source.get('promotion_id') or '').strip(),
                    'missing': True,
                }
            else:
                source_promotion = dict((source_release.get('metadata') or {}).get('baseline_promotion') or {})
                source_snapshot = {
                    'kind': 'baseline_promotion',
                    'promotion_id': str(source_release.get('release_id') or ''),
                    'candidate_catalog_version': str(source_promotion.get('candidate_catalog_version') or source_release.get('version') or ''),
                    'candidate_baselines_fingerprint': self._stable_digest(dict(source_promotion.get('candidate_baselines') or {})),
                    'release_status': str(source_release.get('status') or ''),
                    'missing': False,
                }
        fingerprints = {
            'catalog_context_hash': self._stable_digest({
                'catalog_id': str((catalog_release or {}).get('release_id') or ''),
                'catalog_version': str((catalog_meta.get('current_version') or {}).get('catalog_version') or (catalog_release or {}).get('version') or ''),
                'current_baselines': current_baselines,
            }),
            'catalog_baselines_hash': self._stable_digest(current_baselines),
            'candidate_baseline_hash': self._stable_digest(candidate_entries),
            'request_hash': self._stable_digest(request_payload),
            'source_hash': self._stable_digest(source_snapshot),
        }
        fingerprints['simulation_hash'] = self._stable_digest({
            'catalog': fingerprints['catalog_context_hash'],
            'candidate': fingerprints['candidate_baseline_hash'],
            'request': fingerprints['request_hash'],
            'source': fingerprints['source_hash'],
        })
        observed_versions = {
            'catalog_version': str((catalog_meta.get('current_version') or {}).get('catalog_version') or (catalog_release or {}).get('version') or ''),
            'catalog_release_version': str((catalog_release or {}).get('version') or ''),
            'source_candidate_catalog_version': str(source_snapshot.get('candidate_catalog_version') or ''),
            'requested_candidate_catalog_version': str((request or {}).get('version') or ''),
        }
        return {
            'catalog': {
                'catalog_id': str((catalog_release or {}).get('release_id') or ''),
                'catalog_name': str((catalog_release or {}).get('name') or ''),
                'current_version': observed_versions['catalog_version'],
                'current_baselines_fingerprint': fingerprints['catalog_baselines_hash'],
            },
            'candidate': {
                'fingerprint': fingerprints['candidate_baseline_hash'],
                'environment_count': len(candidate_entries),
            },
            'request': request_payload,
            'source': source_snapshot,
            'observed_versions': observed_versions,
            'fingerprints': fingerprints,
        }

    def evaluate_baseline_promotion_simulation_state(
        self,
        gw,
        *,
        simulation: dict[str, Any] | None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        state = dict(simulation or {})
        if not state:
            return {}
        request = dict(state.get('request') or {})
        simulation_source = dict(state.get('simulation_source') or {})
        catalog_id = str(state.get('catalog_id') or request.get('catalog_id') or simulation_source.get('catalog_id') or '').strip()
        if not catalog_id:
            blocked = ['baseline_catalog_not_found']
            return {**state, 'simulation_status': 'invalid', 'stale': True, 'expired': False, 'blocked': True, 'blocked_reasons': blocked, 'why_blocked': 'baseline_catalog_not_found'}
        catalog_release = self._get_baseline_catalog_release(gw, catalog_id=catalog_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if catalog_release is None:
            blocked = ['baseline_catalog_not_found']
            return {**state, 'simulation_status': 'invalid', 'stale': True, 'expired': False, 'blocked': True, 'blocked_reasons': blocked, 'why_blocked': 'baseline_catalog_not_found'}
        observed_context = self._baseline_promotion_simulation_observation(
            gw,
            catalog_release=catalog_release,
            candidate_baselines=dict(request.get('candidate_baselines') or state.get('candidate_baselines') or {}),
            request=request,
            simulation_source=simulation_source,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        stored_versions = dict(state.get('source_observed_versions') or state.get('observed_versions') or {})
        stored_fingerprints = dict(state.get('source_fingerprints') or state.get('fingerprints') or {})
        blocked_reasons: list[str] = []
        stale_reasons: list[str] = []
        stale = False
        if stored_versions and str(stored_versions.get('catalog_version') or '') != str((observed_context.get('observed_versions') or {}).get('catalog_version') or ''):
            stale = True
            stale_reasons.append('catalog_version_changed')
        if stored_fingerprints and str(stored_fingerprints.get('catalog_baselines_hash') or '') and str(stored_fingerprints.get('catalog_baselines_hash') or '') != str((observed_context.get('fingerprints') or {}).get('catalog_baselines_hash') or ''):
            stale = True
            stale_reasons.append('catalog_baselines_changed')
        if stored_fingerprints and str(stored_fingerprints.get('candidate_baseline_hash') or '') and str(stored_fingerprints.get('candidate_baseline_hash') or '') != str((observed_context.get('fingerprints') or {}).get('candidate_baseline_hash') or ''):
            stale = True
            stale_reasons.append('candidate_baseline_changed')
        if stored_fingerprints and str(stored_fingerprints.get('request_hash') or '') and str(stored_fingerprints.get('request_hash') or '') != str((observed_context.get('fingerprints') or {}).get('request_hash') or ''):
            stale = True
            stale_reasons.append('simulation_request_changed')
        if stored_fingerprints and str(stored_fingerprints.get('source_hash') or '') and str(stored_fingerprints.get('source_hash') or '') != str((observed_context.get('fingerprints') or {}).get('source_hash') or ''):
            stale = True
            stale_reasons.append('simulation_source_changed')
        simulation_policy = dict(state.get('simulation_policy') or {})
        ttl_s = self._baseline_promotion_simulation_ttl_s(simulation_policy)
        review_policy = self._baseline_promotion_simulation_review_policy(simulation_policy)
        legacy_review = dict(state.get('review') or {})
        review_state = self._baseline_promotion_simulation_review_state(
            review_policy=review_policy,
            review_state=dict(state.get('review_state') or {}),
            legacy_review=legacy_review,
        )
        review = self._baseline_promotion_simulation_review_summary(review_state, legacy_review)
        simulated_at = float(state.get('simulated_at') or state.get('created_at') or time.time())
        expires_at = simulated_at + ttl_s if ttl_s > 0 else None
        expired = expires_at is not None and float(time.time()) > float(expires_at)
        if stale:
            blocked_reasons.append('baseline_promotion_simulation_stale')
        if expired:
            blocked_reasons.append('baseline_promotion_simulation_expired')
        if str((state.get('validation') or {}).get('status') or '').strip().lower() != 'passed':
            blocked_reasons.append('baseline_promotion_simulation_invalid')
        if not bool((state.get('summary') or {}).get('approvable', False)):
            blocked_reasons.append('baseline_promotion_simulation_not_approvable')
        if bool(review_state.get('rejected')) and bool(review_state.get('block_on_rejection')):
            blocked_reasons.append('baseline_promotion_simulation_review_rejected')
        summary = dict(state.get('summary') or {})
        summary['review_required'] = bool(review_state.get('required'))
        summary['review_satisfied'] = bool(review_state.get('approved'))
        summary['review_status'] = str(review_state.get('overall_status') or '')
        simulation_status = 'ready'
        if expired:
            simulation_status = 'expired'
        elif stale:
            simulation_status = 'stale'
        elif bool(review_state.get('rejected')):
            simulation_status = 'review_rejected'
        elif bool(review.get('approved')):
            simulation_status = 'reviewed'
        elif int(review_state.get('review_count') or 0) > 0:
            simulation_status = 'in_review'
        elif blocked_reasons:
            simulation_status = 'blocked'
        evaluated = {
            **state,
            'summary': summary,
            'simulation_policy': {
                'ttl_s': ttl_s,
                'approval_policy': dict(review_policy.get('approval_policy') or {}),
                'allow_self_review': bool(review_policy.get('allow_self_review', True)),
                'require_reason': bool(review_policy.get('require_reason', False)),
                'block_on_rejection': bool(review_policy.get('block_on_rejection', True)),
                'custody_monitoring_policy': self._baseline_promotion_simulation_custody_monitoring_policy_for_release(
                    self._resolve_baseline_promotion_release_for_simulation(
                        gw,
                        simulation=state,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        environment=environment,
                    ),
                    simulation=state,
                ),
            },
            'review_state': review_state,
            'review': review,
            'observed_context': observed_context,
            'source_observed_versions': stored_versions,
            'source_fingerprints': stored_fingerprints,
            'current_observed_versions': dict(observed_context.get('observed_versions') or {}),
            'current_fingerprints': dict(observed_context.get('fingerprints') or {}),
            'observed_versions': stored_versions,
            'fingerprints': stored_fingerprints,
            'stale': stale,
            'stale_reasons': self._baseline_promotion_unique_ids(stale_reasons),
            'expired': expired,
            'expires_at': expires_at,
            'blocked': bool(blocked_reasons),
            'blocked_reasons': self._baseline_promotion_unique_ids(blocked_reasons),
            'why_blocked': (self._baseline_promotion_unique_ids(blocked_reasons) or [''])[0] or '',
            'reviewed_at': review.get('approved_at') or review.get('rejected_at') or review.get('reviewed_at'),
            'simulation_status': simulation_status,
        }
        explainability = dict(evaluated.get('explainability') or {})
        explainability['runtime_status'] = {
            'simulation_status': evaluated.get('simulation_status'),
            'stale': stale,
            'expired': expired,
            'review_status': str(review_state.get('overall_status') or ''),
            'review_required': bool(review_state.get('required')),
            'review_satisfied': bool(review_state.get('approved')),
            'blocked_reasons': self._baseline_promotion_unique_ids(blocked_reasons),
            'stale_reasons': self._baseline_promotion_unique_ids(stale_reasons),
            'source_observed_versions': stored_versions,
            'current_observed_versions': dict(observed_context.get('observed_versions') or {}),
        }
        evaluated['explainability'] = explainability
        return evaluated

    def simulate_existing_runtime_alert_governance_baseline_promotion(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        candidate_baselines: dict[str, Any] | None = None,
        version: str | None = None,
        rollout_policy: dict[str, Any] | None = None,
        gate_policy: dict[str, Any] | None = None,
        rollback_policy: dict[str, Any] | None = None,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_baseline_promotion(
            gw,
            promotion_id=promotion_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        promotion = dict(detail.get('baseline_promotion') or {})
        promotion_policy = dict(promotion.get('promotion_policy') or {})
        catalog_id = str(promotion.get('catalog_id') or '')
        if not catalog_id:
            return {
                'ok': False,
                'error': 'baseline_promotion_catalog_not_found',
                'promotion_id': str(promotion_id or '').strip(),
            }
        simulation_source = {
            'kind': 'baseline_promotion',
            'promotion_id': str(promotion_id or '').strip(),
            'catalog_id': catalog_id,
            'candidate_catalog_version': str(promotion.get('candidate_catalog_version') or ''),
        }
        simulation = self.simulate_runtime_alert_governance_baseline_promotion(
            gw,
            catalog_id=catalog_id,
            actor=actor,
            candidate_baselines=(dict(candidate_baselines or {}) if candidate_baselines is not None else dict(promotion.get('candidate_baselines') or {})),
            version=(str(version).strip() if version is not None else None),
            rollout_policy=(dict(rollout_policy or {}) if rollout_policy is not None else dict(promotion_policy.get('rollout_policy') or {})),
            gate_policy=(dict(gate_policy or {}) if gate_policy is not None else dict(promotion_policy.get('gate_policy') or {})),
            rollback_policy=(dict(rollback_policy or {}) if rollback_policy is not None else dict(promotion_policy.get('rollback_policy') or {})),
            reason=reason,
            simulation_source=simulation_source,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        return simulation

    def simulate_runtime_alert_governance_baseline_promotion(
        self,
        gw,
        *,
        catalog_id: str,
        actor: str,
        candidate_baselines: dict[str, Any] | None = None,
        version: str | None = None,
        rollout_policy: dict[str, Any] | None = None,
        gate_policy: dict[str, Any] | None = None,
        rollback_policy: dict[str, Any] | None = None,
        reason: str = '',
        simulation_source: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        catalog_release = self._get_baseline_catalog_release(gw, catalog_id=catalog_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if catalog_release is None:
            return {'ok': False, 'error': 'baseline_catalog_not_found', 'catalog_id': str(catalog_id or '').strip()}
        catalog_meta = dict((catalog_release.get('metadata') or {}).get('baseline_catalog') or {})
        previous_baselines = self._normalize_baseline_catalog_environment_entries(dict(catalog_meta.get('current_baselines') or {}))
        candidate_updates = self._normalize_baseline_catalog_environment_entries(candidate_baselines)
        merged_candidate = {k: dict(v) for k, v in previous_baselines.items()}
        for env_key, entry in candidate_updates.items():
            merged_candidate[env_key] = self._merge_portfolio_policy_overrides(merged_candidate.get(env_key), entry)
        impact = self._baseline_catalog_rollout_impact(gw, catalog_release=catalog_release, previous_baselines=previous_baselines, candidate_baselines=merged_candidate)
        promotion_policy_payload = dict(catalog_meta.get('promotion_policy') or {})
        if rollout_policy is not None:
            promotion_policy_payload['rollout_policy'] = dict(rollout_policy or {})
        if gate_policy is not None:
            promotion_policy_payload['gate_policy'] = dict(gate_policy or {})
        if rollback_policy is not None:
            promotion_policy_payload['rollback_policy'] = dict(rollback_policy or {})
        rollout_validation_errors = self._validate_baseline_rollout_policy(dict(promotion_policy_payload.get('rollout_policy') or {}))
        promotion_policy = self._normalize_baseline_catalog_promotion_policy(promotion_policy_payload)
        promotion_version = str(version or f'{catalog_release.get("version")}-promotion-sim-{int(time.time())}').strip() or f'{catalog_release.get("version")}-promotion-sim-{int(time.time())}'
        rollout_plan = self._build_baseline_promotion_rollout_plan(promotion_id='simulation', impact=impact, rollout_policy=dict(promotion_policy.get('rollout_policy') or {}))
        validation_errors = [dict(item) for item in rollout_validation_errors]
        if str((rollout_plan.get('validation') or {}).get('status') or 'passed') != 'passed':
            validation_errors.extend([dict(item) for item in list((rollout_plan.get('validation') or {}).get('errors') or [])])
        validation_status = 'failed' if validation_errors else 'passed'
        synthetic_release = {
            'release_id': 'simulation',
            'name': f'{catalog_release.get("name")}-baseline-promotion-simulation',
            'version': promotion_version,
            'status': 'simulated',
            'tenant_id': catalog_release.get('tenant_id'),
            'workspace_id': catalog_release.get('workspace_id'),
            'environment': catalog_release.get('environment'),
            'metadata': {
                'baseline_promotion': {
                    'kind': 'openclaw_alert_governance_baseline_promotion',
                    'catalog_id': str(catalog_release.get('release_id') or ''),
                    'catalog_name': str(catalog_release.get('name') or ''),
                    'previous_catalog_version': str((catalog_meta.get('current_version') or {}).get('catalog_version') or catalog_release.get('version') or ''),
                    'candidate_catalog_version': promotion_version,
                    'previous_baselines': previous_baselines,
                    'candidate_baselines': merged_candidate,
                    'rollout_impact': impact,
                    'approval_policy': dict(promotion_policy.get('approval_policy') or {}),
                    'promotion_policy': promotion_policy,
                    'rollout_plan': rollout_plan,
                    'rollback_attestations': [],
                    'status': 'simulated' if validation_status == 'passed' else 'invalid',
                    'created_from': {'actor': str(actor or 'admin'), 'reason': str(reason or '').strip(), 'simulation': True},
                    'timeline': [
                        {
                            'ts': time.time(),
                            'kind': 'simulation',
                            'label': 'baseline_promotion_simulated',
                            'actor': str(actor or 'admin'),
                            'catalog_id': str(catalog_release.get('release_id') or ''),
                            'candidate_catalog_version': promotion_version,
                            'validation_status': validation_status,
                        }
                    ],
                },
            },
        }
        rollout_plan_items = [dict(item) for item in list((rollout_plan.get('items') or []))]
        gate_policy_normalized = dict(promotion_policy.get('gate_policy') or {})
        requested_at = time.time()
        auto_window_s = int(((promotion_policy.get('rollout_policy') or {}).get('auto_advance_window_s') or 0) or 0)
        for idx, wave in enumerate(rollout_plan_items):
            overrides: dict[str, dict[str, Any]] = {}
            for portfolio_id in self._baseline_promotion_unique_ids(list(wave.get('portfolio_ids') or [])):
                portfolio_release = gw.audit.get_release_bundle(
                    str(portfolio_id or ''),
                    tenant_id=catalog_release.get('tenant_id'),
                    workspace_id=catalog_release.get('workspace_id'),
                    environment=None,
                )
                if portfolio_release is None or not self._is_alert_governance_portfolio_release(portfolio_release):
                    continue
                overrides[str(portfolio_id)] = self._simulate_portfolio_baseline_catalog_rollout_state(
                    portfolio_release=portfolio_release,
                    promotion_release=synthetic_release,
                    actor=actor,
                    status='simulated',
                    active=True,
                    wave_no=int(wave.get('wave_no') or 0),
                    wave_id=str(wave.get('wave_id') or ''),
                    reason='baseline_promotion_simulation',
                )
            gate_eval = self._evaluate_baseline_promotion_wave_gate(
                gw,
                promotion_release=synthetic_release,
                wave=wave,
                gate_policy=gate_policy_normalized,
                portfolio_release_overrides=overrides,
            )
            wave['gate_evaluation'] = gate_eval
            wave['status_forecast'] = 'gate_failed' if str(gate_eval.get('status') or '') == 'failed' else 'ready'
            calendar_decision = self._baseline_rollout_wave_calendar_decision(
                gw,
                promotion_release=synthetic_release,
                rollout_policy=dict(promotion_policy.get('rollout_policy') or {}),
                requested_at=requested_at,
                wave=wave,
            )
            wave['calendar_decision'] = calendar_decision
            synthetic_promotion = dict(((synthetic_release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
            synthetic_promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan({**rollout_plan, 'items': rollout_plan_items})
            synthetic_release['metadata'] = {'baseline_promotion': synthetic_promotion}
            next_allowed_at = calendar_decision.get('next_allowed_at')
            if next_allowed_at is not None:
                requested_at = float(next_allowed_at) + (auto_window_s if idx < len(rollout_plan_items) - 1 else 0)
        synthetic_promotion = dict(((synthetic_release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
        synthetic_promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan({**rollout_plan, 'items': rollout_plan_items})
        synthetic_release['metadata'] = {'baseline_promotion': synthetic_promotion}
        analytics = self._baseline_promotion_analytics_view(synthetic_release)
        approval_policy_normalized = self._normalize_portfolio_approval_policy(dict(promotion_policy.get('approval_policy') or {}))
        approval_preview = self._baseline_promotion_approval_state(approval_policy=approval_policy_normalized, approvals=[])
        wave_items = [dict(item) for item in list((synthetic_promotion.get('rollout_plan') or {}).get('items') or [])]
        failing_wave_count = len([item for item in wave_items if str(((item.get('gate_evaluation') or {}).get('status') or '')) == 'failed'])
        calendar_blocked_wave_count = len([item for item in wave_items if not bool((item.get('calendar_decision') or {}).get('allowed', False))])
        approvable = validation_status == 'passed' and failing_wave_count == 0
        simulation_request = {
            'catalog_id': str(catalog_release.get('release_id') or ''),
            'candidate_baselines': merged_candidate,
            'version': version if version is not None else None,
            'rollout_policy': dict(promotion_policy.get('rollout_policy') or {}),
            'gate_policy': dict(promotion_policy.get('gate_policy') or {}),
            'rollback_policy': dict(promotion_policy.get('rollback_policy') or {}),
            'reason': str(reason or '').strip(),
        }
        diff = self._baseline_promotion_simulation_diff(previous_baselines=previous_baselines, candidate_baselines=merged_candidate)
        approval_preview_payload = {
            'required': bool(approval_policy_normalized.get('enabled', True)) and bool(list(approval_policy_normalized.get('layers') or [])),
            'approval_policy': approval_policy_normalized,
            'summary': approval_preview,
        }
        explainability = self._baseline_promotion_simulation_explainability(
            diff=diff,
            validation_errors=validation_errors,
            wave_items=wave_items,
            approval_preview=approval_preview_payload,
            approvable=approvable,
        )
        simulated_at = time.time()
        observed_context = self._baseline_promotion_simulation_observation(
            gw,
            catalog_release=catalog_release,
            candidate_baselines=merged_candidate,
            request=simulation_request,
            simulation_source=simulation_source,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        simulation_payload = {
            'ok': True,
            'simulation_id': str(self._stable_digest({'catalog_id': str(catalog_release.get('release_id') or ''), 'simulated_at': simulated_at, 'actor': str(actor or 'admin'), 'request': simulation_request, 'observed': observed_context})[:24]),
            'simulated_at': simulated_at,
            'mode': 'dry-run',
            'catalog_id': str(catalog_release.get('release_id') or ''),
            'catalog_name': str(catalog_release.get('name') or ''),
            'candidate_catalog_version': promotion_version,
            'previous_baselines': previous_baselines,
            'candidate_baselines': merged_candidate,
            'rollout_impact': impact,
            'rollout_plan': synthetic_promotion.get('rollout_plan'),
            'approval_preview': approval_preview_payload,
            'analytics': analytics,
            'summary': {
                'affected_count': int((impact.get('summary') or {}).get('count') or 0),
                'wave_count': len(wave_items),
                'failing_wave_count': failing_wave_count,
                'passing_wave_count': max(0, len(wave_items) - failing_wave_count),
                'calendar_blocked_wave_count': calendar_blocked_wave_count,
                'validation_status': validation_status,
                'validation_error_count': len(validation_errors),
                'approvable': approvable,
                'approval_required': bool(approval_policy_normalized.get('enabled', True)) and bool(list(approval_policy_normalized.get('layers') or [])),
                'first_allowed_at': next((item.get('calendar_decision', {}).get('next_allowed_at') for item in wave_items if (item.get('calendar_decision') or {}).get('next_allowed_at') is not None), None),
            },
            'validation': {
                'status': validation_status,
                'errors': validation_errors,
            },
            'diff': diff,
            'explainability': explainability,
            'simulation_policy': {
                'ttl_s': self._baseline_promotion_simulation_ttl_s(promotion_policy),
                'approval_policy': dict(((promotion_policy.get('simulation_review_policy') or {}).get('approval_policy') or {})),
                'allow_self_review': bool(((promotion_policy.get('simulation_review_policy') or {}).get('allow_self_review', True))),
                'require_reason': bool(((promotion_policy.get('simulation_review_policy') or {}).get('require_reason', False))),
                'block_on_rejection': bool(((promotion_policy.get('simulation_review_policy') or {}).get('block_on_rejection', True))),
                'custody_monitoring_policy': dict(promotion_policy.get('simulation_custody_monitoring_policy') or {}),
            },
            'simulation_source': dict(simulation_source or {}),
            'request': simulation_request,
            'observed_context': observed_context,
            'observed_versions': dict(observed_context.get('observed_versions') or {}),
            'fingerprints': dict(observed_context.get('fingerprints') or {}),
            'scope': self._scope(tenant_id=catalog_release.get('tenant_id'), workspace_id=catalog_release.get('workspace_id'), environment=catalog_release.get('environment')),
        }
        return self.evaluate_baseline_promotion_simulation_state(
            gw,
            simulation=simulation_payload,
            tenant_id=catalog_release.get('tenant_id'),
            workspace_id=catalog_release.get('workspace_id'),
            environment=catalog_release.get('environment'),
        )

    def review_runtime_alert_governance_baseline_promotion_simulation(
        self,
        gw,
        *,
        simulation: dict[str, Any],
        actor: str,
        decision: str,
        reason: str = '',
        layer_id: str | None = None,
        requested_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        state = self.evaluate_baseline_promotion_simulation_state(
            gw,
            simulation=simulation,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        normalized_decision = str(decision or '').strip().lower()
        if normalized_decision in {'approved', 'approve'}:
            normalized_decision = 'approve'
        elif normalized_decision in {'rejected', 'reject'}:
            normalized_decision = 'reject'
        else:
            return {'ok': False, 'error': 'baseline_promotion_simulation_review_invalid_decision', 'simulation': state}
        if str(state.get('mode') or '').strip().lower() != 'dry-run':
            return {'ok': False, 'error': 'baseline_promotion_simulation_invalid', 'simulation': state}
        if bool(state.get('expired')):
            return {'ok': False, 'error': 'baseline_promotion_simulation_expired', 'simulation': state, 'guard': {'status': 'blocked', 'reasons': list(state.get('blocked_reasons') or []), 'why_blocked': state.get('why_blocked')}}
        if bool(state.get('stale')):
            return {'ok': False, 'error': 'baseline_promotion_simulation_stale', 'simulation': state, 'guard': {'status': 'blocked', 'reasons': list(state.get('blocked_reasons') or []), 'why_blocked': state.get('why_blocked')}}
        if str((state.get('validation') or {}).get('status') or '').strip().lower() != 'passed':
            return {'ok': False, 'error': 'baseline_promotion_simulation_invalid', 'simulation': state}
        if not bool((state.get('summary') or {}).get('approvable', False)):
            return {'ok': False, 'error': 'baseline_promotion_simulation_not_approvable', 'simulation': state}
        review_policy = self._baseline_promotion_simulation_review_policy(dict(state.get('simulation_policy') or {}))
        review_state = self._baseline_promotion_simulation_review_state(
            review_policy=review_policy,
            review_state=dict(state.get('review_state') or {}),
            legacy_review=dict(state.get('review') or {}),
        )
        if bool(review_state.get('rejected')) and bool(review_state.get('block_on_rejection')):
            return {'ok': False, 'error': 'baseline_promotion_simulation_review_rejected', 'simulation': state, 'guard': {'status': 'blocked', 'reasons': list(state.get('blocked_reasons') or []), 'why_blocked': state.get('why_blocked')}}
        if normalized_decision == 'approve' and bool(review_state.get('approved')):
            return {'ok': False, 'error': 'baseline_promotion_simulation_already_approved', 'simulation': state}
        if normalized_decision == 'reject' and bool(review_state.get('rejected')):
            return {'ok': False, 'error': 'baseline_promotion_simulation_already_rejected', 'simulation': state}
        actor_value = str(actor or '').strip() or 'operator'
        if not bool(review_policy.get('allow_self_review', True)) and actor_value == str(state.get('simulated_by') or '').strip():
            return {'ok': False, 'error': 'baseline_promotion_simulation_self_review_blocked', 'simulation': state}
        if bool(review_policy.get('require_reason')) and not str(reason or '').strip():
            return {'ok': False, 'error': 'baseline_promotion_simulation_review_reason_required', 'simulation': state}
        if not bool(review_state.get('required')):
            now_ts = time.time()
            review_summary = {
                'approved': normalized_decision == 'approve',
                'rejected': normalized_decision == 'reject',
                'approved_at': now_ts if normalized_decision == 'approve' else None,
                'approved_by': actor_value if normalized_decision == 'approve' else None,
                'rejected_at': now_ts if normalized_decision == 'reject' else None,
                'rejected_by': actor_value if normalized_decision == 'reject' else None,
                'reason': str(reason or '').strip(),
                'decision': normalized_decision,
                'reviewed_at': now_ts,
            }
            updated = self.evaluate_baseline_promotion_simulation_state(
                gw,
                simulation={**state, 'review': review_summary},
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            return {'ok': True, 'simulation': updated, 'review_action': {'decision': normalized_decision, 'actor': actor_value, 'legacy': True}}
        pending_layers = [dict(item) for item in list(review_state.get('layers') or []) if str(item.get('status') or '') not in {'approved', 'rejected', 'optional'}]
        requested_role_value = str(requested_role or '').strip()
        target_layer = str(layer_id or '').strip()
        if not target_layer and requested_role_value:
            matching = [item for item in pending_layers if str(item.get('requested_role') or '').strip() == requested_role_value]
            if matching:
                target_layer = str(matching[0].get('layer_id') or '').strip()
        if not target_layer:
            next_layer = dict(review_state.get('next_layer') or {})
            target_layer = str(next_layer.get('layer_id') or '').strip()
        if not target_layer and pending_layers:
            target_layer = str(pending_layers[0].get('layer_id') or '').strip()
        layer_states = {str(item.get('layer_id') or ''): dict(item) for item in list(review_state.get('layers') or []) if str(item.get('layer_id') or '')}
        layer_state = dict(layer_states.get(target_layer) or {})
        if not target_layer or not layer_state:
            return {'ok': False, 'error': 'baseline_promotion_simulation_review_layer_not_found', 'simulation': state}
        if review_state.get('mode') == 'sequential':
            next_layer = dict(review_state.get('next_layer') or {})
            next_layer_id = str(next_layer.get('layer_id') or '').strip()
            if next_layer_id and target_layer != next_layer_id:
                return {'ok': False, 'error': 'baseline_promotion_simulation_review_out_of_order', 'simulation': state, 'expected_layer_id': next_layer_id, 'provided_layer_id': target_layer}
        if str(layer_state.get('status') or '') in {'approved', 'rejected'}:
            return {'ok': False, 'error': 'baseline_promotion_simulation_review_layer_already_decided', 'simulation': state, 'layer_id': target_layer}
        existing_items = [dict(item) for item in list(review_state.get('items') or [])]
        for item in existing_items:
            if str(item.get('actor') or '').strip() == actor_value and str(item.get('layer_id') or '').strip() == target_layer:
                return {'ok': False, 'error': 'baseline_promotion_simulation_reviewer_duplicate', 'simulation': state, 'layer_id': target_layer}
        reviewed_at = time.time()
        review_item = {
            'review_id': self._stable_digest({'simulation_id': str(state.get('simulation_id') or ''), 'layer_id': target_layer, 'actor': actor_value, 'reviewed_at': reviewed_at, 'decision': normalized_decision})[:24],
            'layer_id': target_layer,
            'label': str(layer_state.get('label') or target_layer),
            'requested_role': str(layer_state.get('requested_role') or requested_role_value),
            'decision': normalized_decision,
            'actor': actor_value,
            'reason': str(reason or '').strip(),
            'created_at': reviewed_at,
            'decided_at': reviewed_at,
        }
        updated = self.evaluate_baseline_promotion_simulation_state(
            gw,
            simulation={**state, 'review_state': {'items': [*existing_items, review_item]}},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        return {
            'ok': True,
            'simulation': updated,
            'review_action': {
                'review_id': review_item['review_id'],
                'decision': normalized_decision,
                'actor': actor_value,
                'layer_id': target_layer,
                'requested_role': review_item['requested_role'],
                'reviewed_at': reviewed_at,
            },
        }

    def export_runtime_alert_governance_baseline_promotion_simulation_attestation(
        self,
        gw,
        *,
        simulation: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        state = self.evaluate_baseline_promotion_simulation_state(
            gw,
            simulation=simulation,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not str(state.get('simulation_id') or '').strip():
            return {'ok': False, 'error': 'baseline_promotion_simulation_missing'}
        return self._build_baseline_promotion_simulation_attestation_export_payload(
            simulation=state,
            actor=actor,
            timeline_limit=timeline_limit,
        )

    def export_runtime_alert_governance_baseline_promotion_simulation_review_audit(
        self,
        gw,
        *,
        simulation: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        state = self.evaluate_baseline_promotion_simulation_state(
            gw,
            simulation=simulation,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not str(state.get('simulation_id') or '').strip():
            return {'ok': False, 'error': 'baseline_promotion_simulation_missing'}
        return self._build_baseline_promotion_simulation_review_audit_export_payload(
            simulation=state,
            actor=actor,
            timeline_limit=timeline_limit,
        )

    def _resolve_baseline_promotion_release_for_simulation(
        self,
        gw,
        *,
        simulation: dict[str, Any],
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any] | None:
        promotion_id = str(((simulation.get('simulation_source') or {}).get('promotion_id') or '')).strip()
        if not promotion_id:
            return None
        release = gw.audit.get_release_bundle(promotion_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None or not self._is_baseline_promotion_release(release):
            release = gw.audit.get_release_bundle(promotion_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=None)
        return release if self._is_baseline_promotion_release(release) else None

    def export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
        self,
        gw,
        *,
        simulation: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        state = self.evaluate_baseline_promotion_simulation_state(
            gw,
            simulation=simulation,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not str(state.get('simulation_id') or '').strip():
            return {'ok': False, 'error': 'baseline_promotion_simulation_missing'}
        release = self._resolve_baseline_promotion_release_for_simulation(
            gw,
            simulation=state,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if release is None:
            return {'ok': False, 'error': 'baseline_promotion_simulation_source_missing', 'simulation_id': str(state.get('simulation_id') or '')}
        exported = self._build_baseline_promotion_simulation_evidence_package_export_payload(
            release=release,
            simulation=state,
            actor=actor,
            timeline_limit=timeline_limit,
        )
        if not exported.get('ok'):
            return exported
        updated_release = self._store_baseline_promotion_simulation_evidence_package(
            gw,
            release=release,
            package_record=dict(exported.get('package_record') or {}),
            registry_entry=dict(exported.get('registry_entry') or {}),
        )
        custody_job = self._schedule_baseline_promotion_simulation_custody_job(
            gw,
            promotion_release=updated_release,
            actor=actor,
            reason='simulation evidence package exported',
        )
        package_items = self._list_baseline_promotion_simulation_evidence_packages(updated_release)
        return {
            **exported,
            'promotion_id': str(updated_release.get('release_id') or ''),
            'release': dict(updated_release),
            'custody_job': custody_job,
            'registry_summary': self._baseline_promotion_simulation_export_registry_summary(updated_release),
            'simulation_evidence_packages': {
                'items': package_items,
                'summary': {
                    'count': len(package_items),
                    'latest_package_id': package_items[0].get('package_id') if package_items else None,
                },
            },
        }

    def verify_runtime_alert_governance_baseline_promotion_simulation_evidence_artifact(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        package_id: str | None = None,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_baseline_promotion(
            gw,
            promotion_id=promotion_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        release = dict(detail.get('release') or {})
        artifact_payload = dict(artifact or {})
        stored_package = None
        if not artifact_payload and artifact_b64 is None:
            stored_package = self._find_baseline_promotion_simulation_evidence_package(
                release,
                package_id=package_id,
                include_content=True,
            )
            if stored_package is None:
                return {
                    'ok': False,
                    'error': 'baseline_promotion_simulation_evidence_package_not_found',
                    'promotion_id': promotion_id,
                    'package_id': package_id,
                }
            artifact_payload = dict(stored_package.get('artifact') or {})
        verification = self._verify_baseline_promotion_simulation_evidence_artifact_payload(
            artifact=artifact_payload or artifact,
            artifact_b64=artifact_b64,
            registry_entries=self._baseline_promotion_simulation_export_registry_entries(release),
            stored_package=stored_package,
        )
        if verification.get('ok'):
            metadata = dict(release.get('metadata') or {})
            promotion = dict(metadata.get('baseline_promotion') or {})
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='evidence',
                label='baseline_promotion_simulation_evidence_verified',
                actor=str(actor or 'system'),
                package_id=str(verification.get('package_id') or ''),
                entry_id=str(((verification.get('registry_entry') or {}).get('entry_id')) or ''),
                verification_status=str(((verification.get('verification') or {}).get('status')) or ''),
                artifact_sha256=str(((verification.get('artifact') or {}).get('sha256')) or ''),
            )
            metadata['baseline_promotion'] = promotion
            updated_release = gw.audit.update_release_bundle(
                str(release.get('release_id') or ''),
                metadata=metadata,
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            ) or release
            verification['promotion_id'] = str(updated_release.get('release_id') or '')
            verification['release'] = dict(updated_release)
        return verification

