"""baseline_rollout_management._simulation_b_mixin"""
from __future__ import annotations

import time
import uuid
from typing import Any




OpenClawBaselineRolloutManagementMixin: type | None = None  # late-bound by __init__.py


class _OpenClawBaselineRolloutManagementMixinSimulationBMixin:
    """Sub-mixin: simulation_b."""

    def restore_runtime_alert_governance_baseline_promotion_simulation_evidence_artifact(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        package_id: str | None = None,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
        persist_restore_session: bool = True,
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
        if not verification.get('ok'):
            return verification
        if not bool((verification.get('verification') or {}).get('valid')):
            return {
                'ok': False,
                'error': 'baseline_promotion_simulation_evidence_artifact_verification_failed',
                'promotion_id': promotion_id,
                'package_id': package_id or verification.get('package_id'),
                'verification': verification,
            }
        restored_simulation = self._restore_baseline_promotion_simulation_from_evidence_verification(
            verification=verification,
        )
        replayed_simulation = self.evaluate_baseline_promotion_simulation_state(
            gw,
            simulation=restored_simulation,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        restore_id = f'sim-restore-{str(promotion_id)[:8]}-{str(verification.get("package_id") or "")[:8]}-{uuid.uuid4().hex[:8]}'
        restore_session = {
            'restore_id': restore_id,
            'restored_at': time.time(),
            'restored_by': str(actor or 'system'),
            'package_id': str(verification.get('package_id') or ''),
            'simulation_id': str(restored_simulation.get('simulation_id') or ''),
            'artifact_sha256': str(((verification.get('artifact') or {}).get('sha256')) or ''),
            'registry_entry': {
                'entry_id': str(((verification.get('registry_entry') or {}).get('entry_id')) or ''),
                'sequence': int(((verification.get('registry_entry') or {}).get('sequence')) or 0),
                'entry_hash': str(((verification.get('registry_entry') or {}).get('entry_hash')) or ''),
            },
            'verification': {
                'status': str(((verification.get('verification') or {}).get('status')) or ''),
                'valid': bool(((verification.get('verification') or {}).get('valid'))),
                'failures': [str(item) for item in list(((verification.get('verification') or {}).get('failures')) or []) if str(item)],
            },
            'replay': {
                'simulation_status': str(replayed_simulation.get('simulation_status') or restored_simulation.get('simulation_status') or ''),
                'stale': bool(replayed_simulation.get('stale')),
                'expired': bool(replayed_simulation.get('expired')),
                'blocked': bool(replayed_simulation.get('blocked')),
                'why_blocked': str(replayed_simulation.get('why_blocked') or ''),
                'review_status': str(((replayed_simulation.get('review_state') or {}).get('overall_status')) or ''),
            },
        }
        updated_release = release
        if persist_restore_session:
            updated_release = self._store_baseline_promotion_simulation_restore_session(
                gw,
                release=release,
                session_record=restore_session,
                restore_history_limit=20,
            )
        return {
            'ok': True,
            'promotion_id': str(updated_release.get('release_id') or promotion_id),
            'package_id': str(verification.get('package_id') or ''),
            'verification': dict(verification.get('verification') or {}),
            'artifact': dict(verification.get('artifact') or {}),
            'registry_entry': dict(verification.get('registry_entry') or {}),
            'restored_simulation': restored_simulation,
            'replayed_simulation': replayed_simulation,
            'restore_session': restore_session,
            'release': dict(updated_release),
            'simulation_restore_sessions': {
                'items': self._list_baseline_promotion_simulation_restore_sessions(updated_release),
                'summary': {
                    'count': len(self._list_baseline_promotion_simulation_restore_sessions(updated_release)),
                    'latest_restore_id': (self._list_baseline_promotion_simulation_restore_sessions(updated_release)[0].get('restore_id') if self._list_baseline_promotion_simulation_restore_sessions(updated_release) else None),
                },
            },
        }

    def reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        package_id: str | None = None,
        persist_reconciliation_session: bool = True,
        history_limit: int = 20,
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
        packages = self._list_baseline_promotion_simulation_evidence_packages(release, include_content=True)
        target_package_id = str(package_id or '').strip()
        if target_package_id:
            packages = [item for item in packages if str(item.get('package_id') or '') == target_package_id]
        if not packages:
            return {
                'ok': False,
                'error': 'baseline_promotion_simulation_evidence_package_not_found',
                'promotion_id': promotion_id,
                'package_id': package_id,
            }
        now_ts = time.time()
        registry_entries = self._baseline_promotion_simulation_export_registry_entries(release)
        items = [
            self._baseline_promotion_simulation_evidence_reconciliation_item(
                stored_package=dict(package),
                registry_entries=registry_entries,
                now_ts=now_ts,
            )
            for package in packages
        ]
        items.sort(key=lambda item: (float(item.get('created_at') or 0.0), str(item.get('package_id') or '')), reverse=True)
        summary = self._baseline_promotion_simulation_evidence_reconciliation_summary(items)
        reconciliation_id = f'sim-reconcile-{str(promotion_id)[:8]}-{uuid.uuid4().hex[:10]}'
        session_record = {
            'reconciliation_id': reconciliation_id,
            'reconciled_at': now_ts,
            'reconciled_by': str(actor or 'system'),
            'promotion_id': str(release.get('release_id') or promotion_id),
            'package_id': target_package_id or None,
            'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
            'summary': summary,
            'items': items,
        }
        updated_release = release
        monitoring = {}
        if persist_reconciliation_session:
            updated_release = self._store_baseline_promotion_simulation_evidence_reconciliation_session(
                gw,
                release=release,
                session_record=session_record,
                history_limit=history_limit,
            )
            monitoring = self._apply_baseline_promotion_simulation_custody_monitoring(
                gw,
                release=updated_release,
                reconciliation=session_record,
                actor=actor,
            )
            updated_release = dict(monitoring.get('release') or updated_release)
        return {
            'ok': True,
            'promotion_id': str(updated_release.get('release_id') or promotion_id),
            'package_id': target_package_id or None,
            'reconciliation': session_record,
            'release': dict(updated_release),
            'custody_monitoring': {
                'guard': dict((monitoring.get('guard') or {})),
                'alerts': [dict(item) for item in list(monitoring.get('alerts') or [])],
                'policy': dict((monitoring.get('policy') or {})),
            },
            'simulation_evidence_reconciliation': {
                'current': dict((((updated_release.get('metadata') or {}).get('baseline_promotion') or {}).get('current_simulation_evidence_reconciliation') or {}) or session_record),
                'history': {
                    'items': self._list_baseline_promotion_simulation_evidence_reconciliation_sessions(updated_release),
                    'summary': {
                        'count': len(self._list_baseline_promotion_simulation_evidence_reconciliation_sessions(updated_release)),
                        'latest_reconciliation_id': (self._list_baseline_promotion_simulation_evidence_reconciliation_sessions(updated_release)[0].get('reconciliation_id') if self._list_baseline_promotion_simulation_evidence_reconciliation_sessions(updated_release) else None),
                        'latest_overall_status': (((self._list_baseline_promotion_simulation_evidence_reconciliation_sessions(updated_release)[0].get('summary') or {}).get('overall_status')) if self._list_baseline_promotion_simulation_evidence_reconciliation_sessions(updated_release) else None),
                    },
                },
            },
        }

    def update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        action: str,
        alert_id: str | None = None,
        reason: str = '',
        mute_for_s: int | None = None,
        owner_id: str | None = None,
        owner_role: str | None = None,
        queue_id: str | None = None,
        queue_label: str | None = None,
        route_id: str | None = None,
        route_label: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        release = self._resolve_baseline_promotion_release(
            gw,
            promotion_id=str(promotion_id or '').strip(),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if release is None or not self._is_baseline_promotion_release(release):
            return {'ok': False, 'error': 'baseline_promotion_not_found', 'promotion_id': promotion_id}
        updated = self._update_baseline_promotion_simulation_custody_alert_lifecycle(
            gw,
            release=release,
            actor=actor,
            action=action,
            alert_id=alert_id,
            reason=reason,
            mute_for_s=mute_for_s,
            owner_id=owner_id,
            owner_role=owner_role,
            queue_id=queue_id,
            queue_label=queue_label,
            route_id=route_id,
            route_label=route_label,
        )
        if not updated.get('ok'):
            payload = {
                'ok': False,
                'error': str(updated.get('error') or 'baseline_promotion_simulation_custody_alert_update_failed'),
                'promotion_id': promotion_id,
                'action': str(action or '').strip().lower(),
                'alert_id': str(alert_id or ''),
                'scope': self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            }
            if updated.get('reconciliation'):
                payload['reconciliation'] = dict(updated.get('reconciliation') or {})
            return payload
        current_release = dict(updated.get('release') or release)
        return {
            'ok': True,
            'promotion_id': promotion_id,
            'action': str(updated.get('action') or '').strip().lower(),
            'alert': dict(updated.get('alert') or {}),
            'simulation_custody_monitoring': {
                'policy': self._baseline_promotion_simulation_custody_monitoring_policy_for_release(current_release),
                'guard': self._baseline_promotion_simulation_custody_guard(current_release),
                'alerts': {
                    'items': [dict(item) for item in list(updated.get('alerts') or [])],
                    'summary': dict(updated.get('alerts_summary') or {}),
                },
            },
            'scope': self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
        }

    def create_runtime_alert_governance_baseline_promotion_from_simulation(
        self,
        gw,
        *,
        simulation: dict[str, Any],
        actor: str,
        reason: str = '',
        auto_approve: bool = False,
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
        request = dict(state.get('request') or {})
        validation = dict(state.get('validation') or {})
        summary = dict(state.get('summary') or {})
        if str(state.get('mode') or '').strip().lower() != 'dry-run':
            return {'ok': False, 'error': 'baseline_promotion_simulation_invalid', 'simulation': state}
        if str(validation.get('status') or '').strip().lower() != 'passed':
            return {'ok': False, 'error': 'baseline_promotion_simulation_not_valid', 'simulation': state}
        if bool(state.get('stale')):
            return {'ok': False, 'error': 'baseline_promotion_simulation_stale', 'simulation': state, 'guard': {'status': 'blocked', 'reasons': list(state.get('blocked_reasons') or []), 'why_blocked': state.get('why_blocked')}}
        if bool(state.get('expired')):
            return {'ok': False, 'error': 'baseline_promotion_simulation_expired', 'simulation': state, 'guard': {'status': 'blocked', 'reasons': list(state.get('blocked_reasons') or []), 'why_blocked': state.get('why_blocked')}}
        if bool(state.get('blocked')):
            return {'ok': False, 'error': str(state.get('why_blocked') or 'baseline_promotion_simulation_blocked'), 'simulation': state, 'guard': {'status': 'blocked', 'reasons': list(state.get('blocked_reasons') or []), 'why_blocked': state.get('why_blocked')}}
        if not bool((state.get('review') or {}).get('approved')):
            return {'ok': False, 'error': 'baseline_promotion_simulation_not_approved', 'simulation': state, 'guard': {'status': 'blocked', 'reasons': ['baseline_promotion_simulation_not_approved'], 'why_blocked': 'baseline_promotion_simulation_not_approved'}}
        if not bool(summary.get('approvable', False)):
            return {'ok': False, 'error': 'baseline_promotion_simulation_not_approvable', 'simulation': state}
        catalog_id = str(request.get('catalog_id') or state.get('catalog_id') or '').strip()
        if not catalog_id:
            return {'ok': False, 'error': 'baseline_catalog_not_found', 'simulation': state}
        source_release = self._resolve_baseline_promotion_release_for_simulation(
            gw,
            simulation=state,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        custody_guard = self._baseline_promotion_simulation_custody_guard(source_release)
        if bool(custody_guard.get('blocked')):
            return {
                'ok': False,
                'error': 'baseline_promotion_simulation_custody_guard_blocked',
                'simulation': state,
                'guard': custody_guard,
            }
        created = self.create_runtime_alert_governance_baseline_promotion(
            gw,
            catalog_id=catalog_id,
            actor=actor,
            candidate_baselines=dict(request.get('candidate_baselines') or state.get('candidate_baselines') or {}),
            version=(str(request.get('version')).strip() if request.get('version') is not None else None),
            rollout_policy=(dict(request.get('rollout_policy') or {}) if 'rollout_policy' in request else None),
            gate_policy=(dict(request.get('gate_policy') or {}) if 'gate_policy' in request else None),
            rollback_policy=(dict(request.get('rollback_policy') or {}) if 'rollback_policy' in request else None),
            reason=str(reason or request.get('reason') or ''),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not created.get('ok'):
            return created
        created_release = dict(created.get('release') or {})
        created_promotion = dict(created.get('baseline_promotion') or {})
        comparison = {
            'simulation_request_fingerprint': str((state.get('fingerprints') or {}).get('request_hash') or ''),
            'created_request_fingerprint': self._stable_digest({
                'catalog_id': catalog_id,
                'candidate_baselines': dict(created_promotion.get('candidate_baselines') or {}),
                'version': str(created_release.get('version') or ''),
                'rollout_policy': dict((created_promotion.get('promotion_policy') or {}).get('rollout_policy') or {}),
                'gate_policy': dict((created_promotion.get('promotion_policy') or {}).get('gate_policy') or {}),
                'rollback_policy': dict((created_promotion.get('promotion_policy') or {}).get('rollback_policy') or {}),
            }),
            'items': [],
        }
        compare_pairs = [
            ('candidate_baselines', dict(request.get('candidate_baselines') or state.get('candidate_baselines') or {}), dict(created_promotion.get('candidate_baselines') or {})),
            ('rollout_policy', dict(request.get('rollout_policy') or {}), dict((created_promotion.get('promotion_policy') or {}).get('rollout_policy') or {})),
            ('gate_policy', dict(request.get('gate_policy') or {}), dict((created_promotion.get('promotion_policy') or {}).get('gate_policy') or {})),
            ('rollback_policy', dict(request.get('rollback_policy') or {}), dict((created_promotion.get('promotion_policy') or {}).get('rollback_policy') or {})),
            ('candidate_catalog_version', str(state.get('candidate_catalog_version') or ''), str(created_promotion.get('candidate_catalog_version') or created_release.get('version') or '')),
        ]
        for field_name, simulation_value, created_value in compare_pairs:
            if simulation_value == created_value:
                continue
            comparison['items'].append({
                'field': field_name,
                'simulation_value': simulation_value,
                'created_value': created_value,
                'simulation_hash': self._stable_digest(simulation_value),
                'created_hash': self._stable_digest(created_value),
            })
        comparison['diverged'] = bool(comparison['items']) or comparison['simulation_request_fingerprint'] != comparison['created_request_fingerprint']
        simulation_attestation = self._build_baseline_promotion_simulation_attestation_export_payload(
            simulation=state,
            actor=actor,
        )
        review_audit = self._build_baseline_promotion_simulation_review_audit_export_payload(
            simulation=state,
            actor=actor,
        )
        attestation_report = dict(simulation_attestation.get('report') or {})
        review_audit_report = dict(review_audit.get('report') or {})
        created_from_simulation = {
            'simulation_id': str(state.get('simulation_id') or ''),
            'catalog_id': catalog_id,
            'candidate_catalog_version': str(state.get('candidate_catalog_version') or ''),
            'simulation_source': dict(state.get('simulation_source') or {}),
            'comparison': comparison,
            'attestation': {
                'report_id': str(attestation_report.get('report_id') or ''),
                'report_type': str(attestation_report.get('report_type') or ''),
                'generated_at': attestation_report.get('generated_at'),
                'generated_by': attestation_report.get('generated_by'),
                'scope': dict(simulation_attestation.get('scope') or {}),
                'summary': {
                    'simulation_status': str(((attestation_report.get('simulation') or {}).get('simulation_status') or '')),
                    'review_status': str(((attestation_report.get('review_state') or {}).get('overall_status') or '')),
                    'review_count': int(((attestation_report.get('review_state') or {}).get('review_count') or 0)),
                    'created_promotion_count': len(list(attestation_report.get('created_promotions') or [])),
                },
                'fingerprint': self._stable_digest(attestation_report),
                'integrity': dict(simulation_attestation.get('integrity') or {}),
            },
            'review_audit': {
                'report_id': str(review_audit_report.get('report_id') or ''),
                'report_type': str(review_audit_report.get('report_type') or ''),
                'generated_at': review_audit_report.get('generated_at'),
                'generated_by': review_audit_report.get('generated_by'),
                'summary': {
                    'overall_status': str(((review_audit_report.get('review_sequence') or {}).get('overall_status') or '')),
                    'mode': str(((review_audit_report.get('review_sequence') or {}).get('mode') or '')),
                    'review_count': int(((review_audit_report.get('review_sequence') or {}).get('review_count') or 0)),
                    'reviewers': list(((review_audit_report.get('separation_of_duties') or {}).get('reviewers') or [])),
                    'policy_fingerprint': str(((review_audit_report.get('effective_policy') or {}).get('policy_fingerprint') or '')),
                },
                'fingerprint': self._stable_digest(review_audit_report),
                'integrity': dict(review_audit.get('integrity') or {}),
            },
            'evidence_package': dict((((state.get('export_state') or {}).get('latest_evidence_package')) or {})),
        }
        created['created_from_simulation'] = created_from_simulation
        created_release = dict(created.get('release') or {})
        if created_release:
            created_meta = dict(created_release.get('metadata') or {})
            created_bp = dict(created_meta.get('baseline_promotion') or {})
            created_bp['created_from_simulation'] = created_from_simulation
            created_bp = self._append_baseline_promotion_timeline_event(
                created_bp,
                kind='simulation',
                label='baseline_promotion_created_from_simulation',
                actor=str(actor or 'admin'),
                simulation_id=str(state.get('simulation_id') or ''),
                source_promotion_id=str((state.get('simulation_source') or {}).get('promotion_id') or ''),
                diverged=bool(comparison.get('diverged')),
                divergence_count=len(list(comparison.get('items') or [])),
                simulation_attestation_id=str(((created_from_simulation.get('attestation') or {}).get('report_id') or '')),
                simulation_review_audit_id=str(((created_from_simulation.get('review_audit') or {}).get('report_id') or '')),
            )
            created_meta['baseline_promotion'] = created_bp
            refreshed_release = gw.audit.update_release_bundle(
                str(created_release.get('release_id') or ''),
                metadata=created_meta,
                tenant_id=created_release.get('tenant_id'),
                workspace_id=created_release.get('workspace_id'),
                environment=created_release.get('environment'),
            ) or created_release
            created = self._baseline_promotion_detail_view(gw, release=refreshed_release)
            created['created_from_simulation'] = created_from_simulation
        if auto_approve and str(((created.get('release') or {}).get('status') or '')).strip().lower() == 'pending_approval':
            approved = self.decide_runtime_alert_governance_baseline_promotion(
                gw,
                promotion_id=str((created.get('release') or {}).get('release_id') or created.get('promotion_id') or ''),
                actor=actor,
                decision='approve',
                reason=str(reason or 'approve rollout from canvas simulation'),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            if not approved.get('ok'):
                return {
                    'ok': False,
                    'error': 'baseline_promotion_auto_approve_failed',
                    'created': created,
                    'approval_error': approved,
                }
            approved['created_from_simulation'] = dict(created.get('created_from_simulation') or {})
            return approved
        return created

