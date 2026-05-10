"""baseline_rollout_management._core_mixin"""
from __future__ import annotations

import time
import uuid
from typing import Any




OpenClawBaselineRolloutManagementMixin: type | None = None  # late-bound by __init__.py


class _OpenClawBaselineRolloutManagementMixinCoreMixin:
    """Sub-mixin: core."""

    def _get_baseline_catalog_release(
        self,
        gw,
        *,
        catalog_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any] | None:
        if not str(catalog_id or '').strip():
            return None
        release = gw.audit.get_release_bundle(str(catalog_id or '').strip(), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is not None and self._is_baseline_catalog_release(release):
            return release
        release = gw.audit.get_release_bundle(str(catalog_id or '').strip(), tenant_id=tenant_id, workspace_id=workspace_id, environment=None)
        if release is not None and self._is_baseline_catalog_release(release):
            return release
        candidates = gw.audit.list_release_bundles(limit=200, kind='policy_baseline_catalog', tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        for item in candidates:
            if str(item.get('release_id') or '') == str(catalog_id or '').strip() and self._is_baseline_catalog_release(item):
                return item
        if environment is not None:
            candidates = gw.audit.list_release_bundles(limit=200, kind='policy_baseline_catalog', tenant_id=tenant_id, workspace_id=workspace_id, environment=None)
            for item in candidates:
                if str(item.get('release_id') or '') == str(catalog_id or '').strip() and self._is_baseline_catalog_release(item):
                    return item
        return None

    def _resolve_baseline_catalog_environment_baseline(
        self,
        gw,
        *,
        catalog_release: dict[str, Any],
        environment: str,
        visited: set[str] | None = None,
    ) -> dict[str, Any]:
        env_key = self._normalize_portfolio_environment_name(environment)
        visit_key = f'{str(catalog_release.get("release_id") or "")}:{env_key}'
        visited = set(visited or set())
        if visit_key in visited:
            return {
                'environment': env_key,
                'configured': False,
                'baseline_label': f'{env_key}-baseline',
                'inheritance_error': 'catalog_inheritance_cycle',
            }
        visited.add(visit_key)
        metadata = dict(catalog_release.get('metadata') or {})
        catalog = dict(metadata.get('baseline_catalog') or {})
        baselines = self._normalize_baseline_catalog_environment_entries(dict(catalog.get('current_baselines') or catalog.get('environment_policy_baselines') or {}))
        entry = dict(baselines.get(env_key) or {})
        base: dict[str, Any] = {}
        parent_ref = dict(catalog.get('parent_catalog_ref') or {})
        if parent_ref:
            parent_release = self._get_baseline_catalog_release(
                gw,
                catalog_id=str(parent_ref.get('catalog_id') or ''),
                tenant_id=catalog_release.get('tenant_id'),
                workspace_id=catalog_release.get('workspace_id'),
                environment=catalog_release.get('environment'),
            )
            if parent_release is not None:
                base = self._resolve_baseline_catalog_environment_baseline(gw, catalog_release=parent_release, environment=env_key, visited=visited)
        inherits_from = self._normalize_portfolio_environment_name(entry.get('inherits_from'))
        if inherits_from and inherits_from != env_key:
            inherited = self._resolve_baseline_catalog_environment_baseline(gw, catalog_release=catalog_release, environment=inherits_from, visited=visited)
            base = self._merge_portfolio_policy_overrides(base, inherited)
        if entry:
            overlay = {k: v for k, v in entry.items() if k not in {'inherits_from', 'override_mode'}}
            base = self._merge_portfolio_policy_overrides(base, overlay)
        if base:
            base['environment'] = env_key
            base['configured'] = True
            base['source'] = 'baseline_catalog'
            base['catalog_id'] = str(catalog_release.get('release_id') or '')
            base['catalog_name'] = str(catalog_release.get('name') or '')
            base['catalog_version'] = str((catalog.get('current_version') or {}).get('catalog_version') or catalog_release.get('version') or '')
            base['baseline_label'] = str(base.get('baseline_label') or f'{env_key}-baseline').strip() or f'{env_key}-baseline'
            base.setdefault('operational_tier', self._default_portfolio_operational_tier(env_key))
            base.setdefault('evidence_classification', self._default_portfolio_evidence_classification(env_key))
            if 'approval_policy' not in base:
                base['approval_policy'] = self._normalize_portfolio_approval_policy({})
            if 'security_gate_policy' not in base:
                base['security_gate_policy'] = self._normalize_portfolio_security_gate_policy({})
            if 'escrow_policy' not in base:
                base['escrow_policy'] = self._normalize_portfolio_escrow_policy({})
            if 'signing_policy' not in base:
                base['signing_policy'] = self._normalize_portfolio_signing_policy({})
            if 'verification_gate_policy' not in base:
                base['verification_gate_policy'] = self._normalize_portfolio_verification_gate_policy({})
            if parent_ref:
                base['parent_catalog_ref'] = parent_ref
            if inherits_from:
                base['inherits_from'] = inherits_from
            return base
        return {
            'environment': env_key,
            'configured': False,
            'baseline_label': f'{env_key}-baseline',
        }

    def _portfolio_references_baseline_catalog(self, release: dict[str, Any] | None, *, catalog_id: str) -> bool:
        metadata = dict((release or {}).get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        train_policy = self._normalize_portfolio_train_policy(dict(portfolio.get('train_policy') or {}))
        ref = dict(train_policy.get('baseline_catalog_ref') or {})
        return str(ref.get('catalog_id') or '') == str(catalog_id or '').strip()

    def _baseline_catalog_detail_view(self, gw, *, release: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        catalog = dict(metadata.get('baseline_catalog') or {})
        current_baselines = self._normalize_baseline_catalog_environment_entries(dict(catalog.get('current_baselines') or {}))
        versions = [dict(item) for item in list(catalog.get('versions') or [])]
        promotion_history = [dict(item) for item in list(catalog.get('promotion_history') or [])]
        return {
            'ok': True,
            'catalog_id': str(release.get('release_id') or ''),
            'release': dict(release),
            'baseline_catalog': {
                **catalog,
                'current_baselines': current_baselines,
                'versions': versions,
                'promotion_history': promotion_history,
            },
            'summary': {
                'environment_count': len(current_baselines),
                'version_count': len(versions),
                'promotion_count': len(promotion_history),
                'current_version': ((catalog.get('current_version') or {}).get('catalog_version')),
                'parent_catalog_id': ((catalog.get('parent_catalog_ref') or {}).get('catalog_id')),
            },
            'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
        }

    def create_runtime_alert_governance_baseline_catalog(
        self,
        gw,
        *,
        name: str,
        version: str,
        actor: str,
        environment_policy_baselines: dict[str, Any] | None = None,
        promotion_policy: dict[str, Any] | None = None,
        parent_catalog_id: str | None = None,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        parent_ref = {}
        if str(parent_catalog_id or '').strip():
            parent_release = self._get_baseline_catalog_release(gw, catalog_id=str(parent_catalog_id or '').strip(), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
            if parent_release is None:
                return {'ok': False, 'error': 'baseline_catalog_parent_not_found', 'parent_catalog_id': str(parent_catalog_id or '').strip()}
            parent_ref = {
                'catalog_id': str(parent_release.get('release_id') or ''),
                'catalog_version': str((((parent_release.get('metadata') or {}).get('baseline_catalog') or {}).get('current_version') or {}).get('catalog_version') or parent_release.get('version') or ''),
            }
        baselines = self._normalize_baseline_catalog_environment_entries(environment_policy_baselines)
        release = gw.audit.create_release_bundle(
            kind='policy_baseline_catalog',
            name=str(name or 'openclaw-governance-baseline-catalog').strip() or 'openclaw-governance-baseline-catalog',
            version=str(version or f'catalog-{int(time.time())}').strip() or f'catalog-{int(time.time())}',
            created_by=str(actor or 'admin'),
            items=[],
            environment=environment,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            notes=str(reason or '').strip(),
            metadata={
                'baseline_catalog': {
                    'kind': 'openclaw_alert_governance_baseline_catalog',
                    'current_version': {'catalog_version': str(version or f'catalog-{int(time.time())}').strip() or f'catalog-{int(time.time())}'},
                    'current_baselines': baselines,
                    'versions': [{
                        'catalog_version': str(version or f'catalog-{int(time.time())}').strip() or f'catalog-{int(time.time())}',
                        'promoted_at': time.time(),
                        'promoted_by': str(actor or 'admin'),
                        'promotion_id': None,
                        'baselines': baselines,
                    }],
                    'promotion_policy': self._normalize_baseline_catalog_promotion_policy(promotion_policy),
                    'parent_catalog_ref': parent_ref,
                    'promotion_history': [],
                    'created_from': {'actor': str(actor or 'admin'), 'reason': str(reason or '').strip()},
                },
            },
            status='approved',
        )
        metadata = dict(release.get('metadata') or {})
        catalog = dict(metadata.get('baseline_catalog') or {})
        catalog['current_version'] = dict(catalog.get('current_version') or {})
        catalog['current_version']['catalog_version'] = str(version or release.get('version') or '').strip() or str(release.get('version') or '')
        metadata['baseline_catalog'] = catalog
        gw.audit.update_release_bundle(str(release.get('release_id') or ''), metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        release = gw.audit.get_release_bundle(str(release.get('release_id') or ''), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or release
        return self._baseline_catalog_detail_view(gw, release=release)

    def list_runtime_alert_governance_baseline_catalogs(self, gw, *, limit: int = 50, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        releases = gw.audit.list_release_bundles(limit=max(limit * 5, limit), kind='policy_baseline_catalog', tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items = []
        for release in releases:
            if not self._is_baseline_catalog_release(release):
                continue
            detail = self._baseline_catalog_detail_view(gw, release=release)
            items.append({
                'catalog_id': detail.get('catalog_id'),
                'name': (detail.get('release') or {}).get('name'),
                'version': (detail.get('release') or {}).get('version'),
                'summary': detail.get('summary'),
                'scope': detail.get('scope'),
            })
            if len(items) >= limit:
                break
        return {'ok': True, 'items': items, 'summary': {'count': len(items)}}

    def get_runtime_alert_governance_baseline_catalog(self, gw, *, catalog_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        release = self._get_baseline_catalog_release(gw, catalog_id=catalog_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None:
            return {'ok': False, 'error': 'baseline_catalog_not_found', 'catalog_id': str(catalog_id or '').strip()}
        return self._baseline_catalog_detail_view(gw, release=release)

    def _baseline_promotion_detail_view(self, gw, *, release: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        approval_policy = self._normalize_portfolio_approval_policy(dict((promotion.get('approval_policy') or {})))
        approvals = self._list_workflow_approvals(gw, limit=50, workflow_id=self._baseline_promotion_approval_workflow_id(str(release.get('release_id') or '')), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        approval_state = self._baseline_promotion_approval_state(approval_policy=approval_policy, approvals=approvals)
        promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        timeline = self._baseline_promotion_timeline_view(release)
        analytics = self._baseline_promotion_analytics_view(release)
        advance_jobs = self.list_baseline_promotion_wave_advance_jobs(gw, limit=20, promotion_id=str(release.get('release_id') or ''), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        analytics = {**analytics, 'scheduled_advance_job_count': int((advance_jobs.get('summary') or {}).get('count') or 0), 'due_advance_job_count': int((advance_jobs.get('summary') or {}).get('due') or 0)}
        rollback_attestations = [dict(item) for item in list(promotion.get('rollback_attestations') or [])]
        simulation_evidence_packages = self._list_baseline_promotion_simulation_evidence_packages(release)
        simulation_export_registry = self._baseline_promotion_simulation_export_registry_entries(release)
        simulation_restore_sessions = self._list_baseline_promotion_simulation_restore_sessions(release)
        simulation_reconciliation_sessions = self._list_baseline_promotion_simulation_evidence_reconciliation_sessions(release)
        current_simulation_reconciliation = dict((((release.get('metadata') or {}).get('baseline_promotion') or {}).get('current_simulation_evidence_reconciliation') or {}) or {})
        custody_alert_items = self._baseline_promotion_simulation_custody_alerts(release)
        custody_queue_state = self._baseline_promotion_simulation_custody_queue_capacity_state(gw, release=release)
        payload = {
            'ok': True,
            'promotion_id': str(release.get('release_id') or ''),
            'release': dict(release),
            'baseline_promotion': promotion,
            'approvals': {'items': approvals, 'summary': approval_state},
            'timeline': timeline,
            'analytics': analytics,
            'advance_jobs': advance_jobs,
            'rollback_attestations': {'items': rollback_attestations, 'summary': {'count': len(rollback_attestations), 'latest_attestation_id': rollback_attestations[-1].get('attestation_id') if rollback_attestations else None}},
            'simulation_evidence_packages': {
                'items': simulation_evidence_packages,
                'summary': {
                    'count': len(simulation_evidence_packages),
                    'latest_package_id': simulation_evidence_packages[0].get('package_id') if simulation_evidence_packages else None,
                    'latest_simulation_id': simulation_evidence_packages[0].get('simulation_id') if simulation_evidence_packages else None,
                    'escrowed_count': sum(1 for item in simulation_evidence_packages if bool((item.get('escrow') or {}).get('archived'))),
                    'immutable_archive_count': sum(1 for item in simulation_evidence_packages if (item.get('escrow') or {}).get('immutable_until') is not None),
                    'latest_archive_path': ((simulation_evidence_packages[0].get('escrow') or {}).get('archive_path')) if simulation_evidence_packages else None,
                },
            },
            'simulation_export_registry': {
                'items': simulation_export_registry,
                'summary': self._baseline_promotion_simulation_export_registry_summary(release),
            },
            'simulation_restore_sessions': {
                'items': simulation_restore_sessions,
                'summary': {
                    'count': len(simulation_restore_sessions),
                    'latest_restore_id': simulation_restore_sessions[0].get('restore_id') if simulation_restore_sessions else None,
                    'latest_package_id': simulation_restore_sessions[0].get('package_id') if simulation_restore_sessions else None,
                },
            },
            'simulation_evidence_reconciliation': {
                'current': current_simulation_reconciliation,
                'history': {
                    'items': simulation_reconciliation_sessions,
                    'summary': {
                        'count': len(simulation_reconciliation_sessions),
                        'latest_reconciliation_id': simulation_reconciliation_sessions[0].get('reconciliation_id') if simulation_reconciliation_sessions else None,
                        'latest_overall_status': ((simulation_reconciliation_sessions[0].get('summary') or {}).get('overall_status')) if simulation_reconciliation_sessions else None,
                    },
                },
            },
            'simulation_custody_monitoring': {
                'policy': self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release),
                'guard': self._baseline_promotion_simulation_custody_guard(release),
                'alerts': {
                    'items': custody_alert_items,
                    'summary': self._baseline_promotion_simulation_custody_alerts_summary(custody_alert_items),
                },
                'queue_capacity': custody_queue_state,
                'jobs': self.list_baseline_promotion_simulation_custody_jobs(
                    gw,
                    limit=20,
                    promotion_id=str(release.get('release_id') or ''),
                    tenant_id=release.get('tenant_id'),
                    workspace_id=release.get('workspace_id'),
                    environment=release.get('environment'),
                ),
            },
            'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
        }
        catalog_id = str(promotion.get('catalog_id') or '')
        if catalog_id:
            catalog_release = self._get_baseline_catalog_release(gw, catalog_id=catalog_id, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
            if catalog_release is not None:
                payload['catalog'] = self._baseline_catalog_detail_view(gw, release=catalog_release)
        return payload

    def _resolve_baseline_promotion_release(
        self,
        gw,
        *,
        promotion_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_promotion_id = str(promotion_id or '').strip()
        if not normalized_promotion_id:
            return None
        candidate_environments: list[str | None] = []
        for candidate in (environment, None, 'prod', 'dev', 'stage', 'test', 'qa'):
            if candidate not in candidate_environments:
                candidate_environments.append(candidate)
        for candidate_environment in candidate_environments:
            release = gw.audit.get_release_bundle(
                normalized_promotion_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=candidate_environment,
            )
            if release is not None and self._is_baseline_promotion_release(release):
                return release
        for release in list(gw.audit.list_release_bundles(limit=500, tenant_id=tenant_id, workspace_id=workspace_id, environment=None) or []):
            current_release = dict(release or {})
            if str(current_release.get('release_id') or '').strip() != normalized_promotion_id:
                continue
            if self._is_baseline_promotion_release(current_release):
                return current_release
        return None

    def get_runtime_alert_governance_baseline_promotion(
        self,
        gw,
        *,
        promotion_id: str,
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
        if release is None:
            return {'ok': False, 'error': 'baseline_promotion_not_found', 'promotion_id': str(promotion_id or '').strip()}
        detail = self._baseline_promotion_detail_view(gw, release=release)
        requested_environment = str(environment or '').strip()
        release_environment = str(release.get('environment') or '').strip()
        if requested_environment and release_environment and requested_environment != release_environment:
            detail['scope_resolution'] = {
                'requested_environment': requested_environment,
                'resolved_environment': release_environment,
                'cross_environment_fallback': True,
            }
        return detail

    def get_runtime_alert_governance_baseline_promotion_timeline(
        self,
        gw,
        *,
        promotion_id: str,
        limit: int = 200,
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
        if release is None:
            return {'ok': False, 'error': 'baseline_promotion_not_found', 'promotion_id': str(promotion_id or '').strip()}
        timeline = self._baseline_promotion_timeline_view(release, limit=limit)
        payload = {
            'ok': True,
            'promotion_id': str(release.get('release_id') or ''),
            'timeline': timeline.get('items') or [],
            'summary': timeline.get('summary') or {},
            'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
        }
        requested_environment = str(environment or '').strip()
        release_environment = str(release.get('environment') or '').strip()
        if requested_environment and release_environment and requested_environment != release_environment:
            payload['scope_resolution'] = {
                'requested_environment': requested_environment,
                'resolved_environment': release_environment,
                'cross_environment_fallback': True,
            }
        return payload

    def create_runtime_alert_governance_baseline_promotion(
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
        if rollout_validation_errors:
            return {'ok': False, 'error': 'baseline_rollout_policy_invalid', 'catalog_id': str(catalog_id or '').strip(), 'validation': {'status': 'failed', 'errors': rollout_validation_errors}}
        promotion_policy = self._normalize_baseline_catalog_promotion_policy(promotion_policy_payload)
        promotion_version = str(version or f'{catalog_release.get("version")}-promotion-{int(time.time())}').strip() or f'{catalog_release.get("version")}-promotion-{int(time.time())}'
        rollout_plan = self._build_baseline_promotion_rollout_plan(promotion_id='', impact=impact, rollout_policy=dict(promotion_policy.get('rollout_policy') or {}))
        if str((rollout_plan.get('validation') or {}).get('status') or 'passed') != 'passed':
            return {'ok': False, 'error': 'baseline_rollout_plan_invalid', 'catalog_id': str(catalog_id or '').strip(), 'rollout_plan': rollout_plan, 'validation': dict(rollout_plan.get('validation') or {})}
        timeline_seed = self._append_baseline_promotion_timeline_event({}, kind='promotion', label='baseline_promotion_created', actor=str(actor or 'admin'), catalog_id=str(catalog_release.get('release_id') or ''), candidate_catalog_version=promotion_version, rollout_enabled=bool((promotion_policy.get('rollout_policy') or {}).get('enabled', False)))
        release = gw.audit.create_release_bundle(
            kind='policy_baseline_promotion',
            name=f'{catalog_release.get("name")}-baseline-promotion',
            version=promotion_version,
            created_by=str(actor or 'admin'),
            items=[],
            environment=catalog_release.get('environment'),
            tenant_id=catalog_release.get('tenant_id'),
            workspace_id=catalog_release.get('workspace_id'),
            notes=str(reason or '').strip(),
            metadata={
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
                    'status': 'pending_approval',
                    'created_from': {'actor': str(actor or 'admin'), 'reason': str(reason or '').strip()},
                    'timeline': list(timeline_seed.get('timeline') or []),
                },
            },
            status='pending_approval',
        )
        promotion_id = str(release.get('release_id') or '')
        metadata = dict(release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        promotion['rollout_plan'] = self._build_baseline_promotion_rollout_plan(promotion_id=promotion_id, impact=impact, rollout_policy=dict(promotion_policy.get('rollout_policy') or {}))
        metadata['baseline_promotion'] = promotion
        release = gw.audit.update_release_bundle(promotion_id, metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')) or release
        approval_policy = self._normalize_portfolio_approval_policy(dict(promotion_policy.get('approval_policy') or {}))
        if bool(approval_policy.get('enabled', True)) and list(approval_policy.get('layers') or []):
            self._ensure_baseline_promotion_approvals(gw, release=release, actor=actor, approval_policy=approval_policy)
        else:
            return self.decide_runtime_alert_governance_baseline_promotion(gw, promotion_id=promotion_id, actor=actor, decision='approve', reason='auto-approve', tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        release = gw.audit.get_release_bundle(promotion_id, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')) or release
        return self._baseline_promotion_detail_view(gw, release=release)

    def _complete_baseline_promotion(self, gw, *, promotion_release: dict[str, Any], actor: str, reason: str = '') -> dict[str, Any]:
        promotion = dict((promotion_release.get('metadata') or {}).get('baseline_promotion') or {})
        catalog_release = self._get_baseline_catalog_release(gw, catalog_id=str(promotion.get('catalog_id') or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment'))
        if catalog_release is None:
            return {'ok': False, 'error': 'baseline_catalog_not_found', 'promotion_id': str(promotion_release.get('release_id') or '')}
        catalog_metadata = dict(catalog_release.get('metadata') or {})
        catalog = dict(catalog_metadata.get('baseline_catalog') or {})
        candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(promotion.get('candidate_baselines') or {}))
        current_version = str(promotion.get('candidate_catalog_version') or promotion_release.get('version') or '')
        versions = [dict(item) for item in list(catalog.get('versions') or [])]
        versions.append({
            'catalog_version': current_version,
            'promoted_at': time.time(),
            'promoted_by': str(actor or 'admin'),
            'promotion_id': str(promotion_release.get('release_id') or ''),
            'baselines': candidate_baselines,
        })
        rollout_impact = dict(promotion.get('rollout_impact') or {})
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        catalog['current_baselines'] = candidate_baselines
        catalog['current_version'] = {
            'catalog_version': current_version,
            'promoted_at': time.time(),
            'promoted_by': str(actor or 'admin'),
            'promotion_id': str(promotion_release.get('release_id') or ''),
        }
        history = [dict(item) for item in list(catalog.get('promotion_history') or [])]
        history.append({
            'promotion_id': str(promotion_release.get('release_id') or ''),
            'catalog_version': current_version,
            'promoted_at': time.time(),
            'promoted_by': str(actor or 'admin'),
            'rollout_impact_summary': (rollout_impact.get('summary') or {}),
            'rollout_plan_summary': (rollout_plan.get('summary') or {}),
            'reason': str(reason or '').strip(),
        })
        catalog['versions'] = versions[-20:]
        catalog['promotion_history'] = history[-50:]
        catalog_metadata['baseline_catalog'] = catalog
        gw.audit.update_release_bundle(str(catalog_release.get('release_id') or ''), metadata=catalog_metadata, tenant_id=catalog_release.get('tenant_id'), workspace_id=catalog_release.get('workspace_id'), environment=catalog_release.get('environment'))
        applied_portfolio_ids = self._baseline_promotion_unique_ids(list((rollout_plan.get('applied_portfolio_ids') or []) or (rollout_impact.get('summary') or {}).get('portfolio_ids') or []))
        for portfolio_id in applied_portfolio_ids:
            portfolio_release = gw.audit.get_release_bundle(str(portfolio_id or ''), tenant_id=catalog_release.get('tenant_id'), workspace_id=catalog_release.get('workspace_id'), environment=None)
            if portfolio_release is None or not self._is_alert_governance_portfolio_release(portfolio_release):
                continue
            self._set_portfolio_baseline_catalog_rollout_state(gw, portfolio_release=portfolio_release, promotion_release=promotion_release, actor=actor, status='completed', active=False, reason=reason)
        prom_meta = dict(promotion_release.get('metadata') or {})
        promotion = dict(prom_meta.get('baseline_promotion') or {})
        final_status = 'completed' if bool(rollout_plan.get('enabled')) and int(rollout_plan.get('wave_count') or 0) > 0 else 'approved'
        promotion['status'] = final_status
        promotion['completed_at'] = time.time()
        promotion['completed_by'] = str(actor or 'admin')
        promotion['rollout_plan'] = rollout_plan
        promotion = self._append_baseline_promotion_timeline_event(promotion, kind='promotion', label='baseline_promotion_completed', actor=str(actor or 'admin'), candidate_catalog_version=current_version)
        prom_meta['baseline_promotion'] = promotion
        updated_promotion = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status=final_status, metadata=prom_meta, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
        self._disable_baseline_promotion_wave_advance_jobs(gw, promotion_id=str(updated_promotion.get('release_id') or ''), tenant_id=updated_promotion.get('tenant_id'), workspace_id=updated_promotion.get('workspace_id'), environment=updated_promotion.get('environment'), reason='promotion_completed')
        detail = self._baseline_promotion_detail_view(gw, release=updated_promotion)
        detail['catalog'] = self._baseline_catalog_detail_view(gw, release=gw.audit.get_release_bundle(str(catalog_release.get('release_id') or ''), tenant_id=catalog_release.get('tenant_id'), workspace_id=catalog_release.get('workspace_id'), environment=catalog_release.get('environment')) or catalog_release)
        return detail

    def _rollback_baseline_promotion(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        actor: str,
        reason: str = '',
        trigger: str = 'manual',
        wave_no: int | None = None,
    ) -> dict[str, Any]:
        metadata = dict(promotion_release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        promotion_policy = self._normalize_baseline_catalog_promotion_policy(dict(promotion.get('promotion_policy') or {}))
        rollback_policy = self._normalize_baseline_catalog_rollback_policy(dict(promotion_policy.get('rollback_policy') or {}))
        if trigger == 'manual' and not bool(rollback_policy.get('rollback_on_manual_trigger', True)):
            return {'ok': False, 'error': 'baseline_promotion_manual_rollback_disabled', 'promotion_id': str(promotion_release.get('release_id') or '')}
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        affected_portfolio_ids: list[str] = []
        for wave in list(rollout_plan.get('items') or []):
            if str(wave.get('status') or '') in {'applied', 'completed', 'gate_failed'}:
                affected_portfolio_ids.extend(list(wave.get('portfolio_ids') or []))
                wave['status'] = 'rolled_back'
                wave['rolled_back_at'] = time.time()
                wave['rolled_back_by'] = str(actor or 'admin')
                wave['rollback_reason'] = str(reason or '').strip()
        affected_portfolio_ids = self._baseline_promotion_unique_ids(affected_portfolio_ids)
        for portfolio_id in affected_portfolio_ids:
            portfolio_release = gw.audit.get_release_bundle(str(portfolio_id or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=None)
            if portfolio_release is None or not self._is_alert_governance_portfolio_release(portfolio_release):
                continue
            self._set_portfolio_baseline_catalog_rollout_state(gw, portfolio_release=portfolio_release, promotion_release=promotion_release, actor=actor, status='rolled_back', active=False, wave_no=wave_no, reason=reason)
        rollback_attestation = self._build_baseline_promotion_rollback_attestation(
            promotion_release=promotion_release,
            promotion=promotion,
            actor=actor,
            reason=reason,
            trigger=trigger,
            wave_no=wave_no,
            affected_portfolio_ids=affected_portfolio_ids,
            rollout_plan=rollout_plan,
        )
        promotion['rollback_attestations'] = [dict(item) for item in list(promotion.get('rollback_attestations') or [])] + [rollback_attestation]
        promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan(rollout_plan)
        promotion['status'] = 'rolled_back'
        promotion['rolled_back_at'] = time.time()
        promotion['rolled_back_by'] = str(actor or 'admin')
        promotion = self._append_baseline_promotion_timeline_event(promotion, kind='rollback', label='baseline_promotion_rolled_back', actor=str(actor or 'admin'), trigger=str(trigger or 'manual'), wave_no=wave_no, affected_count=len(affected_portfolio_ids), reason=str(reason or '').strip())
        metadata['baseline_promotion'] = promotion
        updated_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status='rolled_back', metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
        self._disable_baseline_promotion_wave_advance_jobs(gw, promotion_id=str(updated_release.get('release_id') or ''), tenant_id=updated_release.get('tenant_id'), workspace_id=updated_release.get('workspace_id'), environment=updated_release.get('environment'), reason='promotion_rolled_back')
        detail = self._baseline_promotion_detail_view(gw, release=updated_release)
        catalog_id = str(promotion.get('catalog_id') or '')
        if catalog_id:
            catalog_release = self._get_baseline_catalog_release(gw, catalog_id=catalog_id, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment'))
            if catalog_release is not None:
                detail['catalog'] = self._baseline_catalog_detail_view(gw, release=catalog_release)
        return detail

    def decide_runtime_alert_governance_baseline_promotion(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        decision: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        release = self._resolve_baseline_promotion_release(gw, promotion_id=str(promotion_id or '').strip(), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None or not self._is_baseline_promotion_release(release):
            return {'ok': False, 'error': 'baseline_promotion_not_found', 'promotion_id': str(promotion_id or '').strip()}
        normalized_decision = str(decision or '').strip().lower()
        promotion = dict((release.get('metadata') or {}).get('baseline_promotion') or {})
        promotion_policy = self._normalize_baseline_catalog_promotion_policy(dict(promotion.get('promotion_policy') or {}))
        approval_policy = self._normalize_portfolio_approval_policy(dict(promotion.get('approval_policy') or {}))
        approvals = self._list_workflow_approvals(gw, limit=50, workflow_id=self._baseline_promotion_approval_workflow_id(str(release.get('release_id') or '')), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        pending = [dict(item) for item in approvals if str(item.get('status') or '') == 'pending']
        if normalized_decision in {'approve', 'reject'} and pending:
            target = pending[0]
            updated = gw.audit.decide_approval(str(target.get('approval_id') or ''), decision=normalized_decision, decided_by=str(actor or '').strip(), reason=str(reason or '').strip(), tenant_id=target.get('tenant_id'), workspace_id=target.get('workspace_id'), environment=target.get('environment'))
            if updated is None:
                return {'ok': False, 'error': 'approval_not_pending', 'promotion_id': str(promotion_id or '').strip()}
        approvals = self._list_workflow_approvals(gw, limit=50, workflow_id=self._baseline_promotion_approval_workflow_id(str(release.get('release_id') or '')), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        state = self._baseline_promotion_approval_state(approval_policy=approval_policy, approvals=approvals)
        release_status = str(release.get('status') or '')
        if normalized_decision == 'reject':
            metadata = dict(release.get('metadata') or {})
            promotion = dict(metadata.get('baseline_promotion') or {})
            promotion['status'] = 'rejected'
            promotion['rejected_at'] = time.time()
            promotion['rejected_by'] = str(actor or 'admin')
            promotion = self._append_baseline_promotion_timeline_event(promotion, kind='promotion', label='baseline_promotion_rejected', actor=str(actor or 'admin'), reason=str(reason or '').strip())
            metadata['baseline_promotion'] = promotion
            updated_release = gw.audit.update_release_bundle(str(release.get('release_id') or ''), status='rejected', metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')) or release
            return self._baseline_promotion_detail_view(gw, release=updated_release)
        if normalized_decision == 'pause':
            return self._pause_baseline_promotion(gw, promotion_release=release, actor=actor, reason=reason)
        custody_guard = self._baseline_promotion_simulation_custody_guard(release)
        if normalized_decision in {'approve', 'advance', 'resume'} and bool(custody_guard.get('blocked')):
            return {
                'ok': False,
                'error': 'baseline_promotion_simulation_custody_guard_blocked',
                'promotion_id': str(promotion_id or '').strip(),
                'guard': custody_guard,
            }
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        rollout_validation = dict(rollout_plan.get('validation') or {})
        if normalized_decision in {'approve', 'advance', 'resume'} and str(rollout_validation.get('status') or 'passed') != 'passed':
            return {'ok': False, 'error': 'baseline_rollout_plan_invalid', 'promotion_id': str(promotion_id or '').strip(), 'validation': rollout_validation}
        if normalized_decision == 'resume':
            return self._resume_baseline_promotion(gw, promotion_release=release, actor=actor, reason=reason)
        if normalized_decision == 'rollback':
            if release_status in {'completed', 'rolled_back', 'rejected'}:
                return {'ok': False, 'error': 'baseline_promotion_not_rollbackable', 'promotion_id': str(promotion_id or '').strip(), 'status': release_status}
            return self._rollback_baseline_promotion(gw, promotion_release=release, actor=actor, reason=reason, trigger='manual')
        if normalized_decision == 'advance':
            if release_status in {'completed', 'rolled_back', 'rejected'}:
                return {'ok': False, 'error': 'baseline_promotion_not_advanceable', 'promotion_id': str(promotion_id or '').strip(), 'status': release_status}
            if str(release_status or '') == 'paused' or bool(((promotion.get('pause_state') or {}).get('paused'))):
                return {'ok': False, 'error': 'baseline_promotion_paused', 'promotion_id': str(promotion_id or '').strip(), 'status': release_status}
            rollout_policy = self._normalize_baseline_catalog_rollout_policy(dict((promotion_policy.get('rollout_policy') or {})))
            if not bool(rollout_policy.get('enabled', False)):
                return {'ok': False, 'error': 'baseline_promotion_not_staged', 'promotion_id': str(promotion_id or '').strip()}
            return self._run_baseline_promotion_wave(gw, promotion_release=release, actor=actor, reason=reason, wave_no=None)
        if normalized_decision != 'approve':
            return {'ok': False, 'error': 'unsupported_decision', 'promotion_id': str(promotion_id or '').strip(), 'decision': normalized_decision}
        remaining_pending = [item for item in approvals if str(item.get('status') or '') == 'pending']
        rejected = [item for item in approvals if str(item.get('status') or '') == 'rejected']
        approved_items = [item for item in approvals if str(item.get('status') or '') == 'approved']
        implicit_approval_ok = bool(normalized_decision == 'approve' and not approvals and list((approval_policy or {}).get('layers') or []))
        if list((approval_policy or {}).get('layers') or []):
            if rejected:
                return self._baseline_promotion_detail_view(gw, release=release)
            if not (implicit_approval_ok or bool(state.get('satisfied')) or (not remaining_pending and approved_items)):
                return self._baseline_promotion_detail_view(gw, release=release)
        metadata = dict(release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        if not promotion.get('approved_at'):
            promotion['approved_at'] = time.time()
            promotion['approved_by'] = str(actor or 'admin')
            promotion = self._append_baseline_promotion_timeline_event(promotion, kind='promotion', label='baseline_promotion_approved', actor=str(actor or 'admin'), reason=str(reason or '').strip())
        promotion['status'] = 'approved'
        metadata['baseline_promotion'] = promotion
        release = gw.audit.update_release_bundle(str(release.get('release_id') or ''), status='approved', metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')) or release
        rollout_policy = self._normalize_baseline_catalog_rollout_policy(dict((promotion_policy.get('rollout_policy') or {})))
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict((((release.get('metadata') or {}).get('baseline_promotion') or {}).get('rollout_plan') or {})))
        if bool(rollout_policy.get('enabled', False)) and int(rollout_plan.get('wave_count') or 0) > 0:
            if bool(rollout_policy.get('auto_apply_first_wave', True)):
                return self._run_baseline_promotion_wave(gw, promotion_release=release, actor=actor, reason=reason, wave_no=None)
            metadata = dict(release.get('metadata') or {})
            promotion = dict(metadata.get('baseline_promotion') or {})
            promotion['status'] = 'awaiting_advance'
            metadata['baseline_promotion'] = promotion
            release = gw.audit.update_release_bundle(str(release.get('release_id') or ''), status='awaiting_advance', metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')) or release
            return self._baseline_promotion_detail_view(gw, release=release)
        return self._complete_baseline_promotion(gw, promotion_release=release, actor=actor, reason=reason)

