from __future__ import annotations

import time
import uuid
from typing import Any



class OpenClawBaselineRolloutManagementMixin:
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

    def _baseline_catalog_rollout_impact(
        self,
        gw,
        *,
        catalog_release: dict[str, Any],
        previous_baselines: dict[str, Any],
        candidate_baselines: dict[str, Any],
    ) -> dict[str, Any]:
        catalog_id = str(catalog_release.get('release_id') or '')
        releases = gw.audit.list_release_bundles(limit=500, kind='policy_portfolio', tenant_id=catalog_release.get('tenant_id'), workspace_id=catalog_release.get('workspace_id'))
        items: list[dict[str, Any]] = []
        env_counts: dict[str, int] = {}
        for release in releases:
            if not self._is_alert_governance_portfolio_release(release) or not self._portfolio_references_baseline_catalog(release, catalog_id=catalog_id):
                continue
            env_key = self._normalize_portfolio_environment_name(release.get('environment'))
            before = dict(previous_baselines.get(env_key) or {})
            after = dict(candidate_baselines.get(env_key) or {})
            diff = self._portfolio_policy_baseline_compare_view(baseline=before, effective=after)
            if not bool(diff.get('items')):
                continue
            item = {
                'portfolio_id': str(release.get('release_id') or ''),
                'name': str(release.get('name') or ''),
                'environment': env_key,
                'change_count': len(list(diff.get('items') or [])),
                'changes': list(diff.get('items') or []),
            }
            items.append(item)
            env_counts[env_key] = env_counts.get(env_key, 0) + 1
        return {
            'items': items,
            'summary': {
                'count': len(items),
                'environment_counts': env_counts,
                'portfolio_ids': [item.get('portfolio_id') for item in items],
            },
        }

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

    def _create_baseline_promotion_layer_approval_request(self, gw, *, release: dict[str, Any], layer: dict[str, Any], actor: str) -> dict[str, Any]:
        promotion_id = str(release.get('release_id') or '')
        return self._ensure_step_approval_request(
            gw,
            workflow_id=self._baseline_promotion_approval_workflow_id(promotion_id),
            step_id=f'baseline-promotion-layer:{str(layer.get("layer_id") or "")}',
            requested_role=str(layer.get('requested_role') or 'approver'),
            requested_by=str(actor or 'system'),
            payload={
                'promotion_id': promotion_id,
                'catalog_id': str(((release.get('metadata') or {}).get('baseline_promotion') or {}).get('catalog_id') or ''),
                'layer_id': str(layer.get('layer_id') or ''),
                'layer_label': str(layer.get('label') or layer.get('layer_id') or ''),
            },
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        )

    def _baseline_promotion_approval_state(self, *, approval_policy: dict[str, Any], approvals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return self._portfolio_approval_state(portfolio_id='baseline-promotion', approval_policy=approval_policy, approvals=approvals)

    def _ensure_baseline_promotion_approvals(self, gw, *, release: dict[str, Any], actor: str, approval_policy: dict[str, Any]) -> dict[str, Any]:
        promotion_id = str(release.get('release_id') or '')
        approvals = self._list_workflow_approvals(gw, limit=max(20, len(list((approval_policy or {}).get('layers') or [])) * 3 + 5), workflow_id=self._baseline_promotion_approval_workflow_id(promotion_id), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        state = self._baseline_promotion_approval_state(approval_policy=approval_policy, approvals=approvals)
        for layer in list((approval_policy or {}).get('layers') or []):
            layer_id = str(layer.get('layer_id') or '')
            layer_state = dict((state.get('by_layer') or {}).get(layer_id) or {})
            if bool(layer.get('required', True)) and str(layer_state.get('status') or '') == 'not_requested':
                self._create_baseline_promotion_layer_approval_request(gw, release=release, layer=layer, actor=actor)
        approvals = self._list_workflow_approvals(gw, limit=max(20, len(list((approval_policy or {}).get('layers') or [])) * 3 + 5), workflow_id=self._baseline_promotion_approval_workflow_id(promotion_id), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        return self._baseline_promotion_approval_state(approval_policy=approval_policy, approvals=approvals)

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

    def _run_baseline_promotion_wave(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        actor: str,
        reason: str = '',
        wave_no: int | None = None,
    ) -> dict[str, Any]:
        metadata = dict(promotion_release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        promotion_policy = self._normalize_baseline_catalog_promotion_policy(dict(promotion.get('promotion_policy') or {}))
        rollout_policy = self._normalize_baseline_catalog_rollout_policy(dict(promotion_policy.get('rollout_policy') or {}))
        gate_policy = self._normalize_baseline_catalog_gate_policy(dict(promotion_policy.get('gate_policy') or {}))
        rollback_policy = self._normalize_baseline_catalog_rollback_policy(dict(promotion_policy.get('rollback_policy') or {}))
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        self._disable_baseline_promotion_wave_advance_jobs(gw, promotion_id=str(promotion_release.get('release_id') or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment'), reason='wave_execution_started')
        waves = [dict(item) for item in list(rollout_plan.get('items') or [])]
        target_wave = None
        if wave_no is None:
            for wave in waves:
                if str(wave.get('status') or 'planned') == 'planned':
                    target_wave = wave
                    break
        else:
            for wave in waves:
                if int(wave.get('wave_no') or 0) == int(wave_no):
                    target_wave = wave
                    break
        if target_wave is None:
            return {'ok': False, 'error': 'baseline_promotion_wave_not_found', 'promotion_id': str(promotion_release.get('release_id') or ''), 'wave_no': wave_no}
        if str(target_wave.get('status') or 'planned') != 'planned':
            return {'ok': False, 'error': 'baseline_promotion_wave_not_planned', 'promotion_id': str(promotion_release.get('release_id') or ''), 'wave_no': int(target_wave.get('wave_no') or 0), 'status': target_wave.get('status')}
        dependency_summary = dict(target_wave.get('dependency_summary') or {})
        required_wave_nos = [int(item) for item in list(dependency_summary.get('depends_on_wave_nos') or []) if int(item)]
        incomplete_dependencies = []
        for dep_wave_no in required_wave_nos:
            dep_wave = next((dict(item) for item in waves if int(item.get('wave_no') or 0) == dep_wave_no), None)
            if dep_wave is None or str(dep_wave.get('status') or '') != 'completed':
                incomplete_dependencies.append(dep_wave_no)
        if incomplete_dependencies:
            promotion = self._append_baseline_promotion_timeline_event(promotion, kind='wave', label='baseline_promotion_wave_dependency_blocked', actor=str(actor or 'admin'), wave_no=int(target_wave.get('wave_no') or 0), depends_on_wave_nos=incomplete_dependencies)
            promotion['status'] = 'awaiting_dependencies'
            metadata['baseline_promotion'] = promotion
            promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status='awaiting_dependencies', metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
            return self._baseline_promotion_detail_view(gw, release=promotion_release)
        exclusive_groups = [str(item).strip() for item in list(dependency_summary.get('exclusive_with_groups') or []) if str(item).strip()]
        if exclusive_groups:
            exclusive_blocked_wave_nos: list[int] = []
            for wave in waves:
                other_wave_no = int(wave.get('wave_no') or 0)
                if other_wave_no == int(target_wave.get('wave_no') or 0):
                    continue
                if not set(exclusive_groups).intersection({str(item).strip() for item in list(wave.get('group_ids') or []) if str(item).strip()}):
                    continue
                if str(wave.get('status') or 'planned') not in {'completed', 'rolled_back'}:
                    exclusive_blocked_wave_nos.append(other_wave_no)
            if exclusive_blocked_wave_nos:
                promotion = self._append_baseline_promotion_timeline_event(promotion, kind='wave', label='baseline_promotion_wave_exclusivity_blocked', actor=str(actor or 'admin'), wave_no=int(target_wave.get('wave_no') or 0), blocked_by_wave_nos=sorted(set(exclusive_blocked_wave_nos)), exclusive_with_groups=exclusive_groups)
                promotion['status'] = 'awaiting_dependencies'
                target_wave['status'] = 'dependency_blocked'
                target_wave['dependency_summary'] = {**dependency_summary, 'exclusive_blocked_by_wave_nos': sorted(set(exclusive_blocked_wave_nos))}
                rollout_plan['items'] = waves
                promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan(rollout_plan)
                metadata['baseline_promotion'] = promotion
                promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status='awaiting_dependencies', metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
                return self._baseline_promotion_detail_view(gw, release=promotion_release)
        for portfolio_id in self._baseline_promotion_unique_ids(list(target_wave.get('portfolio_ids') or [])):
            portfolio_release = gw.audit.get_release_bundle(str(portfolio_id or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=None)
            if portfolio_release is None or not self._is_alert_governance_portfolio_release(portfolio_release):
                continue
            self._set_portfolio_baseline_catalog_rollout_state(gw, portfolio_release=portfolio_release, promotion_release=promotion_release, actor=actor, status='candidate_active', active=True, wave_no=int(target_wave.get('wave_no') or 0), wave_id=str(target_wave.get('wave_id') or ''), reason=reason)
        target_wave['status'] = 'applied'
        target_wave['applied_at'] = time.time()
        target_wave['applied_by'] = str(actor or 'admin')
        existing_rollout_plan = dict(promotion.get('rollout_plan') or {})
        existing_rollout_plan['items'] = waves
        promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan(existing_rollout_plan)
        promotion['status'] = 'in_progress'
        promotion = self._append_baseline_promotion_timeline_event(promotion, kind='wave', label='baseline_promotion_wave_applied', actor=str(actor or 'admin'), wave_no=int(target_wave.get('wave_no') or 0), wave_id=str(target_wave.get('wave_id') or ''), portfolio_count=len(list(target_wave.get('portfolio_ids') or [])))
        metadata['baseline_promotion'] = promotion
        promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status='in_progress', metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
        gate_evaluation = self._evaluate_baseline_promotion_wave_gate(gw, promotion_release=promotion_release, wave=target_wave, gate_policy=gate_policy)
        metadata = dict(promotion_release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        waves = [dict(item) for item in list(rollout_plan.get('items') or [])]
        for idx, wave in enumerate(waves):
            if int(wave.get('wave_no') or 0) == int(target_wave.get('wave_no') or 0):
                waves[idx]['gate_evaluation'] = gate_evaluation
                if bool(gate_evaluation.get('passed')):
                    waves[idx]['status'] = 'completed'
                    waves[idx]['completed_at'] = time.time()
                    waves[idx]['completed_by'] = str(actor or 'admin')
                else:
                    waves[idx]['status'] = 'gate_failed'
                    waves[idx]['gate_failed_at'] = time.time()
                    waves[idx]['gate_failed_by'] = str(actor or 'admin')
                target_wave = waves[idx]
                break
        existing_rollout_plan = dict(promotion.get('rollout_plan') or {})
        existing_rollout_plan['items'] = waves
        promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan(existing_rollout_plan)
        if bool(gate_evaluation.get('passed')):
            promotion = self._append_baseline_promotion_timeline_event(promotion, kind='gate', label='baseline_promotion_wave_gate_passed', actor=str(actor or 'admin'), wave_no=int(target_wave.get('wave_no') or 0), portfolio_count=len(list(target_wave.get('portfolio_ids') or [])))
            metadata['baseline_promotion'] = promotion
            promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status='in_progress', metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
            has_remaining = any(str(item.get('status') or 'planned') == 'planned' for item in list((promotion.get('rollout_plan') or {}).get('items') or []))
            if not has_remaining:
                return self._complete_baseline_promotion(gw, promotion_release=promotion_release, actor=actor, reason=reason)
            promotion = dict((promotion_release.get('metadata') or {}).get('baseline_promotion') or {})
            auto_advance_enabled = bool(rollout_policy.get('auto_advance', False))
            if auto_advance_enabled:
                next_status = 'awaiting_advance_window'
            else:
                next_status = 'awaiting_advance' if bool(rollout_policy.get('require_manual_advance', True)) else 'in_progress'
            promotion['status'] = next_status
            metadata = dict(promotion_release.get('metadata') or {})
            metadata['baseline_promotion'] = promotion
            promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status=next_status, metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
            scheduled_job = None
            if auto_advance_enabled:
                scheduled_job = self._schedule_baseline_promotion_wave_advance_job(gw, promotion_release=promotion_release, source_wave=target_wave, actor=actor, reason=reason or 'baseline wave passed and awaiting advance window')
                promotion_release = gw.audit.get_release_bundle(str(promotion_release.get('release_id') or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
                detail = self._baseline_promotion_detail_view(gw, release=promotion_release)
                detail['scheduled_advance_job'] = scheduled_job
                return detail
            if not bool(rollout_policy.get('require_manual_advance', True)):
                return self._run_baseline_promotion_wave(gw, promotion_release=promotion_release, actor=actor, reason='auto-advance', wave_no=None)
            return self._baseline_promotion_detail_view(gw, release=promotion_release)
        promotion['status'] = 'gate_failed'
        promotion = self._append_baseline_promotion_timeline_event(promotion, kind='gate', label='baseline_promotion_wave_gate_failed', actor=str(actor or 'admin'), wave_no=int(target_wave.get('wave_no') or 0), reasons=list(gate_evaluation.get('reasons') or []), summary=dict(gate_evaluation.get('summary') or {}))
        metadata['baseline_promotion'] = promotion
        promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status='gate_failed', metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
        self._disable_baseline_promotion_wave_advance_jobs(gw, promotion_id=str(promotion_release.get('release_id') or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment'), reason='gate_failed')
        if bool(rollback_policy.get('enabled', True)) and bool(rollback_policy.get('rollback_on_gate_failure', True)):
            return self._rollback_baseline_promotion(gw, promotion_release=promotion_release, actor=actor, reason=reason or 'gate failure rollback', trigger='gate_failure', wave_no=int(target_wave.get('wave_no') or 0))
        return self._baseline_promotion_detail_view(gw, release=promotion_release)

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
