"""openmiura.application.canvas.service._baseline_promotion_state_mixin

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

class _LiveCanvasBaselinePromotionStateMixin:
    """Mixin: baseline promotion state methods on LiveCanvasService."""

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

