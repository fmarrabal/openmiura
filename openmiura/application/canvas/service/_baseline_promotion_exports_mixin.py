"""openmiura.application.canvas.service._baseline_promotion_exports_mixin

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


class _LiveCanvasBaselinePromotionExportsMixin:
    """Mixin: baseline promotion exports methods on LiveCanvasService."""

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

