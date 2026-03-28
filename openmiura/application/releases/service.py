from __future__ import annotations

import hashlib
from typing import Any


class ReleaseService:
    VALID_KINDS = {'agent', 'workflow', 'policy_bundle', 'prompt_pack', 'toolset_bundle'}

    def list_releases(
        self,
        gw,
        *,
        limit: int = 50,
        status: str | None = None,
        kind: str | None = None,
        name: str | None = None,
        environment: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
<<<<<<< HEAD
        items = gw.audit.list_release_bundles(
            limit=limit,
            status=status,
            kind=kind,
            name=name,
            environment=environment,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        return {
            'ok': True,
            'items': items,
            'summary': {
                'count': len(items),
                'status': status,
                'kind': kind,
                'environment': environment,
            },
        }
=======
        items = gw.audit.list_release_bundles(limit=limit, status=status, kind=kind, name=name, environment=environment, tenant_id=tenant_id, workspace_id=workspace_id)
        return {'ok': True, 'items': items, 'summary': {'count': len(items), 'status': status, 'kind': kind, 'environment': environment}}
>>>>>>> origin/main

    def get_release(
        self,
        gw,
        *,
        release_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
<<<<<<< HEAD
        release = gw.audit.get_release_bundle(
            release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if release is None:
            return {'ok': False, 'error': 'release_not_found', 'release_id': release_id}

        items = gw.audit.list_release_bundle_items(release_id)
        approvals = self._sort_audit_items_desc(
            gw.audit.list_release_approvals(
                release_id=release_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
        )
        promotions = self._sort_audit_items_desc(
            gw.audit.list_release_promotions(
                release_id=release_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
        )
        rollbacks = self._sort_audit_items_desc(
            gw.audit.list_release_rollbacks(
                release_id=release_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
        )
        snapshots = gw.audit.list_environment_snapshots(
            kind=release.get('kind'),
            name=release.get('name'),
            environment=release.get('environment'),
            tenant_id=tenant_id or release.get('tenant_id'),
            workspace_id=workspace_id or release.get('workspace_id'),
            limit=20,
        )

        active_release = None
        if release.get('environment'):
            peers = gw.audit.list_release_bundles(
                limit=20,
                status='promoted',
                kind=release.get('kind'),
                name=release.get('name'),
                environment=release.get('environment'),
                tenant_id=tenant_id or release.get('tenant_id'),
                workspace_id=workspace_id or release.get('workspace_id'),
            )
            active_release = next(
                (item for item in peers if item.get('release_id') != release_id),
                None,
            )

        effective_tenant = tenant_id or release.get('tenant_id')
        effective_workspace = workspace_id or release.get('workspace_id')

        canary = gw.audit.get_release_canary(
            release_id,
            tenant_id=effective_tenant,
            workspace_id=effective_workspace,
        )
        gate_runs = gw.audit.list_release_gate_runs(
            release_id=release_id,
            tenant_id=effective_tenant,
            workspace_id=effective_workspace,
            environment=environment or release.get('environment'),
            limit=20,
        )
        change_report = gw.audit.get_release_change_report(
            release_id,
            tenant_id=effective_tenant,
            workspace_id=effective_workspace,
        )

        routing_summary = None
        routing_decisions: list[dict[str, Any]] = []
        if hasattr(gw.audit, 'list_release_routing_decisions'):
            routing_decisions = gw.audit.list_release_routing_decisions(
                release_id=release_id,
                tenant_id=effective_tenant,
                workspace_id=effective_workspace,
                target_environment=(canary or {}).get('target_environment') or environment,
                limit=20,
            )
            routing_summary = self._routing_summary_from_items(routing_decisions, canary)

=======
        release = gw.audit.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None:
            return {'ok': False, 'error': 'release_not_found', 'release_id': release_id}
        items = gw.audit.list_release_bundle_items(release_id)
        approvals = gw.audit.list_release_approvals(release_id=release_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        promotions = gw.audit.list_release_promotions(release_id=release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        rollbacks = gw.audit.list_release_rollbacks(release_id=release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        snapshots = gw.audit.list_environment_snapshots(kind=release.get('kind'), name=release.get('name'), environment=release.get('environment'), tenant_id=tenant_id or release.get('tenant_id'), workspace_id=workspace_id or release.get('workspace_id'), limit=20)
        active_release = None
        if release.get('environment'):
            peers = gw.audit.list_release_bundles(limit=20, status='promoted', kind=release.get('kind'), name=release.get('name'), environment=release.get('environment'), tenant_id=tenant_id or release.get('tenant_id'), workspace_id=workspace_id or release.get('workspace_id'))
            active_release = next((item for item in peers if item.get('release_id') != release_id), None)
        effective_tenant = tenant_id or release.get('tenant_id')
        effective_workspace = workspace_id or release.get('workspace_id')
        canary = gw.audit.get_release_canary(release_id, tenant_id=effective_tenant, workspace_id=effective_workspace)
        gate_runs = gw.audit.list_release_gate_runs(release_id=release_id, tenant_id=effective_tenant, workspace_id=effective_workspace, environment=environment or release.get('environment'), limit=20)
        change_report = gw.audit.get_release_change_report(release_id, tenant_id=effective_tenant, workspace_id=effective_workspace)
        routing_summary = None
        routing_decisions: list[dict[str, Any]] = []
        if hasattr(gw.audit, 'list_release_routing_decisions'):
            routing_decisions = gw.audit.list_release_routing_decisions(release_id=release_id, tenant_id=effective_tenant, workspace_id=effective_workspace, target_environment=(canary or {}).get('target_environment') or environment, limit=20)
            routing_summary = self._routing_summary_from_items(routing_decisions, canary)
>>>>>>> origin/main
        return {
            'ok': True,
            'release': release,
            'items': items,
            'approvals': approvals,
            'promotions': promotions,
            'rollbacks': rollbacks,
            'snapshots': snapshots,
            'canary': canary,
            'gate_runs': gate_runs,
            'change_report': change_report,
            'active_release': active_release,
            'routing_summary': routing_summary,
            'routing_decisions': routing_decisions,
            'available_actions': self._available_actions(release, canary),
        }

    def create_release(
        self,
        gw,
        *,
        kind: str,
        name: str,
        version: str,
        created_by: str,
        items: list[dict[str, Any]] | None = None,
        environment: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        notes: str = '',
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_kind = str(kind or '').strip()
        if normalized_kind not in self.VALID_KINDS:
            raise ValueError(f'Unsupported release kind: {normalized_kind}')
        if not str(name or '').strip():
            raise ValueError('release name is required')
        if not str(version or '').strip():
            raise ValueError('release version is required')
<<<<<<< HEAD

        release = gw.audit.create_release_bundle(
            kind=normalized_kind,
            name=str(name).strip(),
            version=str(version).strip(),
            created_by=str(created_by or 'admin'),
            items=list(items or []),
            environment=str(environment).strip() if environment else None,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            notes=notes,
            metadata=dict(metadata or {}),
        )
        return {'ok': True, 'release': release}

    def submit_release(
        self,
        gw,
        *,
        release_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        release = gw.audit.submit_release_bundle(
            release_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        return {'ok': True, 'release': release}

    def approve_release(
        self,
        gw,
        *,
        release_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        release = gw.audit.approve_release_bundle(
            release_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        return {'ok': True, 'release': release}

    def promote_release(
        self,
        gw,
        *,
        release_id: str,
        to_environment: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        release = gw.audit.promote_release_bundle(
            release_id,
            to_environment=to_environment,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
=======
        release = gw.audit.create_release_bundle(kind=normalized_kind, name=str(name).strip(), version=str(version).strip(), created_by=str(created_by or 'admin'), items=list(items or []), environment=str(environment).strip() if environment else None, tenant_id=tenant_id, workspace_id=workspace_id, notes=notes, metadata=dict(metadata or {}))
        return {'ok': True, 'release': release}

    def submit_release(self, gw, *, release_id: str, actor: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
        release = gw.audit.submit_release_bundle(release_id, actor=actor, reason=reason, tenant_id=tenant_id, workspace_id=workspace_id)
        return {'ok': True, 'release': release}

    def approve_release(self, gw, *, release_id: str, actor: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
        release = gw.audit.approve_release_bundle(release_id, actor=actor, reason=reason, tenant_id=tenant_id, workspace_id=workspace_id)
        return {'ok': True, 'release': release}

    def promote_release(self, gw, *, release_id: str, to_environment: str, actor: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
        release = gw.audit.promote_release_bundle(release_id, to_environment=to_environment, actor=actor, reason=reason, tenant_id=tenant_id, workspace_id=workspace_id)
>>>>>>> origin/main
        return {'ok': True, 'release': release, 'target_environment': to_environment}

    def configure_canary(
        self,
        gw,
        *,
        release_id: str,
        target_environment: str,
        actor: str,
        strategy: str = 'percentage',
        traffic_percent: float = 0,
        step_percent: float = 0,
        bake_minutes: int = 0,
        metric_guardrails: dict[str, Any] | None = None,
        analysis_summary: dict[str, Any] | None = None,
        status: str = 'draft',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
<<<<<<< HEAD
        release = gw.audit.get_release_bundle(
            release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
=======
        release = gw.audit.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
>>>>>>> origin/main
        if release is None:
            raise KeyError(release_id)
        if not str(target_environment or '').strip():
            raise ValueError('target environment is required')
<<<<<<< HEAD

=======
>>>>>>> origin/main
        canary = gw.audit.upsert_release_canary(
            release_id,
            target_environment=str(target_environment).strip(),
            strategy=str(strategy or 'percentage').strip() or 'percentage',
            traffic_percent=max(0.0, min(float(traffic_percent or 0), 100.0)),
            step_percent=max(0.0, min(float(step_percent or 0), 100.0)),
            bake_minutes=max(0, int(bake_minutes or 0)),
            metric_guardrails=dict(metric_guardrails or {}),
            analysis_summary=dict(analysis_summary or {}),
            created_by=str(actor or 'admin'),
            status=str(status or 'draft'),
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
        )
        return {'ok': True, 'release_id': release_id, 'canary': canary}

    def activate_canary(
        self,
        gw,
        *,
        release_id: str,
        actor: str,
        baseline_release_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
<<<<<<< HEAD
        release = gw.audit.get_release_bundle(
            release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if release is None:
            raise KeyError(release_id)

        canary = gw.audit.get_release_canary(
            release_id,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
        )
        if canary is None:
            raise ValueError('canary_not_configured')

        blockers = self._latest_gate_blockers(
            gw,
            release_id=release_id,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=canary.get('target_environment'),
        )
        if blockers:
            raise ValueError(f'canary blocked by failed gates: {", ".join(blockers)}')

        resolved_baseline = baseline_release_id or self._resolve_baseline_release_id(
            gw,
            release=release,
            canary=canary,
        )

        analysis_summary = {
            **dict(canary.get('analysis_summary') or {}),
            'baseline_release_id': resolved_baseline,
            'routing_mode': 'stable-hash-percentage',
        }

        canary = gw.audit.upsert_release_canary(
            release_id,
            target_environment=str(
                canary.get('target_environment') or release.get('environment') or ''
            ),
=======
        release = gw.audit.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if release is None:
            raise KeyError(release_id)
        canary = gw.audit.get_release_canary(release_id, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'))
        if canary is None:
            raise ValueError('canary_not_configured')
        blockers = self._latest_gate_blockers(gw, release_id=release_id, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=canary.get('target_environment'))
        if blockers:
            raise ValueError(f'canary blocked by failed gates: {", ".join(blockers)}')
        resolved_baseline = baseline_release_id or self._resolve_baseline_release_id(gw, release=release, canary=canary)
        analysis_summary = {**dict(canary.get('analysis_summary') or {}), 'baseline_release_id': resolved_baseline, 'routing_mode': 'stable-hash-percentage'}
        canary = gw.audit.upsert_release_canary(
            release_id,
            target_environment=str(canary.get('target_environment') or release.get('environment') or ''),
>>>>>>> origin/main
            strategy=str(canary.get('strategy') or 'percentage'),
            traffic_percent=float(canary.get('traffic_percent') or 0),
            step_percent=float(canary.get('step_percent') or 0),
            bake_minutes=int(canary.get('bake_minutes') or 0),
            metric_guardrails=dict(canary.get('metric_guardrails') or {}),
            analysis_summary=analysis_summary,
            created_by=str(actor or 'admin'),
            status='active',
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
        )
<<<<<<< HEAD

        gw.audit.log_event(
            'system',
            'release',
            str(actor or 'admin'),
            release_id,
            {
                'action': 'canary_activated',
                'baseline_release_id': resolved_baseline,
                'traffic_percent': canary.get('traffic_percent'),
            },
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=canary.get('target_environment'),
        )

        return {
            'ok': True,
            'release_id': release_id,
            'canary': canary,
            'baseline_release_id': resolved_baseline,
        }
=======
        gw.audit.log_event('system', 'release', str(actor or 'admin'), release_id, {'action': 'canary_activated', 'baseline_release_id': resolved_baseline, 'traffic_percent': canary.get('traffic_percent')}, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=canary.get('target_environment'))
        return {'ok': True, 'release_id': release_id, 'canary': canary, 'baseline_release_id': resolved_baseline}
>>>>>>> origin/main

    def resolve_canary_route(
        self,
        gw,
        *,
        release_id: str,
        routing_key: str,
        actor: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
<<<<<<< HEAD
        release = gw.audit.get_release_bundle(
            release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if release is None:
            raise KeyError(release_id)

        canary = gw.audit.get_release_canary(
            release_id,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
        )
        if canary is None or str(canary.get('status') or '').lower() != 'active':
            raise ValueError('canary_not_active')

        baseline_release_id = str(
            (canary.get('analysis_summary') or {}).get('baseline_release_id') or ''
        )
        if not baseline_release_id:
            baseline_release_id = self._resolve_baseline_release_id(
                gw,
                release=release,
                canary=canary,
            )

        baseline = None
        if baseline_release_id:
            baseline = gw.audit.get_release_bundle(
                baseline_release_id,
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
            )

        bucket = self._bucket_for_routing_key(
            routing_key,
            seed=str(canary.get('canary_id') or release_id),
        )

        selected = (
            release
            if bucket < float(canary.get('traffic_percent') or 0)
            else (baseline or release)
        )

        route_kind = 'canary' if selected.get('release_id') == release_id else 'baseline'

=======
        release = gw.audit.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if release is None:
            raise KeyError(release_id)
        canary = gw.audit.get_release_canary(release_id, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'))
        if canary is None or str(canary.get('status') or '').lower() != 'active':
            raise ValueError('canary_not_active')
        baseline_release_id = str((canary.get('analysis_summary') or {}).get('baseline_release_id') or '')
        if not baseline_release_id:
            baseline_release_id = self._resolve_baseline_release_id(gw, release=release, canary=canary)
        baseline = gw.audit.get_release_bundle(baseline_release_id, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id')) if baseline_release_id else None
        bucket = self._bucket_for_routing_key(routing_key, seed=str(canary.get('canary_id') or release_id))
        selected = release if bucket < float(canary.get('traffic_percent') or 0) else (baseline or release)
        route_kind = 'canary' if selected.get('release_id') == release_id else 'baseline'
>>>>>>> origin/main
        decision = gw.audit.create_release_routing_decision(
            release_id=release_id,
            canary_id=str(canary.get('canary_id') or ''),
            baseline_release_id=baseline_release_id or '',
            target_environment=str(canary.get('target_environment') or ''),
            routing_key_hash=hashlib.sha256(str(routing_key).encode('utf-8')).hexdigest(),
            bucket=bucket,
            selected_release_id=str(selected.get('release_id') or release_id),
            selected_version=str(selected.get('version') or ''),
            route_kind=route_kind,
            created_by=str(actor or 'system'),
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
        )
<<<<<<< HEAD

        return {
            'ok': True,
            'decision': decision,
            'selected_release': selected,
            'canary': canary,
        }
=======
        return {'ok': True, 'decision': decision, 'selected_release': selected, 'canary': canary}
>>>>>>> origin/main

    def record_canary_observation(
        self,
        gw,
        *,
        decision_id: str,
        actor: str,
        success: bool,
        latency_ms: float | None = None,
        cost_estimate: float | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
<<<<<<< HEAD
        decision = gw.audit.update_release_routing_decision_observation(
            decision_id,
            success=success,
            latency_ms=latency_ms,
            cost_estimate=cost_estimate,
            metadata=dict(metadata or {}),
            actor=actor,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if decision is None:
            raise KeyError(decision_id)

=======
        decision = gw.audit.update_release_routing_decision_observation(decision_id, success=success, latency_ms=latency_ms, cost_estimate=cost_estimate, metadata=dict(metadata or {}), actor=actor, tenant_id=tenant_id, workspace_id=workspace_id)
        if decision is None:
            raise KeyError(decision_id)
>>>>>>> origin/main
        return {'ok': True, 'decision': decision}

    def routing_summary(
        self,
        gw,
        *,
        release_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        target_environment: str | None = None,
    ) -> dict[str, Any]:
<<<<<<< HEAD
        release = gw.audit.get_release_bundle(
            release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if release is None:
            raise KeyError(release_id)

        canary = gw.audit.get_release_canary(
            release_id,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
        )
        items = gw.audit.list_release_routing_decisions(
            release_id=release_id,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            target_environment=target_environment or (canary or {}).get('target_environment'),
            limit=1000,
        )

        return {
            'ok': True,
            'summary': self._routing_summary_from_items(items, canary),
            'items': items[:50],
        }
=======
        release = gw.audit.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if release is None:
            raise KeyError(release_id)
        canary = gw.audit.get_release_canary(release_id, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'))
        items = gw.audit.list_release_routing_decisions(release_id=release_id, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), target_environment=target_environment or (canary or {}).get('target_environment'), limit=1000)
        return {'ok': True, 'summary': self._routing_summary_from_items(items, canary), 'items': items[:50]}
>>>>>>> origin/main

    def record_gate_run(
        self,
        gw,
        *,
        release_id: str,
        gate_name: str,
        status: str,
        actor: str,
        score: float | None = None,
        threshold: float | None = None,
        details: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
<<<<<<< HEAD
        release = gw.audit.get_release_bundle(
            release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
=======
        release = gw.audit.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
>>>>>>> origin/main
        if release is None:
            raise KeyError(release_id)
        if not str(gate_name or '').strip():
            raise ValueError('gate name is required')
<<<<<<< HEAD

        normalized_status = str(status or '').strip().lower()
        if normalized_status not in {'passed', 'failed', 'warning', 'skipped'}:
            raise ValueError('unsupported gate status')

        gate_run = gw.audit.record_release_gate_run(
            release_id,
            gate_name=str(gate_name).strip(),
            status=normalized_status,
            score=score,
            threshold=threshold,
            details=dict(details or {}),
            executed_by=str(actor or 'system'),
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=environment or release.get('environment'),
        )

=======
        normalized_status = str(status or '').strip().lower()
        if normalized_status not in {'passed', 'failed', 'warning', 'skipped'}:
            raise ValueError('unsupported gate status')
        gate_run = gw.audit.record_release_gate_run(release_id, gate_name=str(gate_name).strip(), status=normalized_status, score=score, threshold=threshold, details=dict(details or {}), executed_by=str(actor or 'system'), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=environment or release.get('environment'))
>>>>>>> origin/main
        return {'ok': True, 'release_id': release_id, 'gate_run': gate_run}

    def set_change_report(
        self,
        gw,
        *,
        release_id: str,
        risk_level: str,
        actor: str,
        summary: dict[str, Any] | None = None,
        diff: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
<<<<<<< HEAD
        release = gw.audit.get_release_bundle(
            release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if release is None:
            raise KeyError(release_id)

        report = gw.audit.upsert_release_change_report(
            release_id,
            risk_level=str(risk_level or 'unknown').strip() or 'unknown',
            summary=dict(summary or {}),
            diff=dict(diff or {}),
            created_by=str(actor or 'system'),
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
        )

        return {'ok': True, 'release_id': release_id, 'change_report': report}

    def rollback_release(
        self,
        gw,
        *,
        release_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        result = gw.audit.rollback_release_bundle(
            release_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        return {'ok': True, **result}

    def _resolve_baseline_release_id(
        self,
        gw,
        *,
        release: dict[str, Any],
        canary: dict[str, Any],
    ) -> str:
        peers = gw.audit.list_release_bundles(
            limit=50,
            status='promoted',
            kind=release.get('kind'),
            name=release.get('name'),
            environment=canary.get('target_environment'),
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
        )
=======
        release = gw.audit.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if release is None:
            raise KeyError(release_id)
        report = gw.audit.upsert_release_change_report(release_id, risk_level=str(risk_level or 'unknown').strip() or 'unknown', summary=dict(summary or {}), diff=dict(diff or {}), created_by=str(actor or 'system'), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'))
        return {'ok': True, 'release_id': release_id, 'change_report': report}

    def rollback_release(self, gw, *, release_id: str, actor: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
        result = gw.audit.rollback_release_bundle(release_id, actor=actor, reason=reason, tenant_id=tenant_id, workspace_id=workspace_id)
        return {'ok': True, **result}

    def _resolve_baseline_release_id(self, gw, *, release: dict[str, Any], canary: dict[str, Any]) -> str:
        peers = gw.audit.list_release_bundles(limit=50, status='promoted', kind=release.get('kind'), name=release.get('name'), environment=canary.get('target_environment'), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'))
>>>>>>> origin/main
        for item in peers:
            if item.get('release_id') != release.get('release_id'):
                return str(item.get('release_id') or '')
        return ''

<<<<<<< HEAD
    def _latest_gate_blockers(
        self,
        gw,
        *,
        release_id: str,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> list[str]:
        runs = gw.audit.list_release_gate_runs(
            release_id=release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=100,
        )
        latest: dict[str, dict[str, Any]] = {}
        for item in runs:
            latest.setdefault(str(item.get('gate_name') or ''), item)

        return [
            name
            for name, item in latest.items()
            if str(item.get('status') or '') == 'failed'
        ]
=======
    def _latest_gate_blockers(self, gw, *, release_id: str, tenant_id: str | None, workspace_id: str | None, environment: str | None) -> list[str]:
        runs = gw.audit.list_release_gate_runs(release_id=release_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, limit=100)
        latest: dict[str, dict[str, Any]] = {}
        for item in runs:
            latest.setdefault(str(item.get('gate_name') or ''), item)
        return [name for name, item in latest.items() if str(item.get('status') or '') == 'failed']
>>>>>>> origin/main

    @staticmethod
    def _bucket_for_routing_key(routing_key: str, *, seed: str) -> float:
        digest = hashlib.sha256(f'{seed}:{routing_key}'.encode('utf-8')).hexdigest()
        value = int(digest[:8], 16) / 0xFFFFFFFF
        return value * 100.0

    @staticmethod
<<<<<<< HEAD
    def _routing_summary_from_items(
        items: list[dict[str, Any]],
        canary: dict[str, Any] | None,
    ) -> dict[str, Any]:
        total = len(items)
        canary_count = sum(1 for item in items if item.get('route_kind') == 'canary')
        baseline_count = sum(1 for item in items if item.get('route_kind') == 'baseline')

        observed = [item for item in items if item.get('completed_at') is not None]
        successes = sum(1 for item in observed if item.get('success') is True)
        latencies = [
            float(item.get('latency_ms'))
            for item in observed
            if item.get('latency_ms') is not None
        ]
        costs = [
            float(item.get('cost_estimate'))
            for item in observed
            if item.get('cost_estimate') is not None
        ]

=======
    def _routing_summary_from_items(items: list[dict[str, Any]], canary: dict[str, Any] | None) -> dict[str, Any]:
        total = len(items)
        canary_count = sum(1 for item in items if item.get('route_kind') == 'canary')
        baseline_count = sum(1 for item in items if item.get('route_kind') == 'baseline')
        observed = [item for item in items if item.get('completed_at') is not None]
        successes = sum(1 for item in observed if item.get('success') is True)
        latencies = [float(item.get('latency_ms')) for item in observed if item.get('latency_ms') is not None]
        costs = [float(item.get('cost_estimate')) for item in observed if item.get('cost_estimate') is not None]
>>>>>>> origin/main
        return {
            'total_decisions': total,
            'canary_count': canary_count,
            'baseline_count': baseline_count,
            'canary_ratio': (canary_count / total) if total else 0.0,
            'target_traffic_percent': float((canary or {}).get('traffic_percent') or 0.0),
            'observed_success_rate': (successes / len(observed)) if observed else None,
            'avg_latency_ms': (sum(latencies) / len(latencies)) if latencies else None,
            'avg_cost_estimate': (sum(costs) / len(costs)) if costs else None,
        }

    @staticmethod
<<<<<<< HEAD
    def _available_actions(
        release: dict[str, Any],
        canary: dict[str, Any] | None = None,
    ) -> list[str]:
        status = str(release.get('status') or '')
        actions: list[str] = []

=======
    def _available_actions(release: dict[str, Any], canary: dict[str, Any] | None = None) -> list[str]:
        status = str(release.get('status') or '')
        actions: list[str] = []
>>>>>>> origin/main
        if status == 'draft':
            actions.append('submit')
        if status == 'candidate':
            actions.append('approve')
        if status == 'approved':
            actions.extend(['promote', 'activate_canary'])
        if status == 'promoted':
            actions.append('rollback')
        if canary is not None and str(canary.get('status') or '').lower() == 'active':
            actions.append('route')
<<<<<<< HEAD

        return actions
    @staticmethod
    def _sort_audit_items_desc(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def _key(item: dict[str, Any]) -> tuple[str, str]:
            ts = str(
                item.get('created_at')
                or item.get('updated_at')
                or item.get('approved_at')
                or item.get('promoted_at')
                or item.get('rolled_back_at')
                or ''
            )
            ident = str(
                item.get('approval_id')
                or item.get('promotion_id')
                or item.get('rollback_id')
                or item.get('release_id')
                or ''
            )
            return (ts, ident)

        return sorted(list(items or []), key=_key, reverse=True)
=======
        return actions
>>>>>>> origin/main
