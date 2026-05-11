"""baseline_rollout_support._core_mixin

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


class _OpenClawBaselineRolloutSupportCoreMixinB:
    """Sub-mixin: core methods on OpenClawBaselineRolloutSupportMixin."""

    def _baseline_rollout_wave_calendar_decision(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        rollout_policy: dict[str, Any] | None,
        requested_at: float,
        wave: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_baseline_catalog_rollout_policy(dict(rollout_policy or {}))
        candidate = float(requested_at)
        last_decisions: list[dict[str, Any]] = []
        combined_blockers: list[str] = []
        combined_windows: list[dict[str, Any]] = []
        unique_portfolio_ids = self._baseline_promotion_unique_ids(list((wave or {}).get('portfolio_ids') or []))
        portfolios: list[dict[str, Any] | None] = []
        for portfolio_id in unique_portfolio_ids:
            portfolio_release = gw.audit.get_release_bundle(str(portfolio_id or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=None)
            portfolios.append(portfolio_release if self._is_alert_governance_portfolio_release(portfolio_release) else None)
        if not portfolios:
            portfolios = [None]
        maintenance_state_by_portfolio: dict[str | None, bool] = {}
        for _ in range(0, 20):
            decisions: list[dict[str, Any]] = []
            next_candidates: list[float] = [candidate]
            fatal_reason: str | None = None
            fatal = False
            all_allowed = True
            for portfolio_release in portfolios:
                portfolio_environment = (portfolio_release or {}).get('environment') or promotion_release.get('environment')
                portfolio_id = str((portfolio_release or {}).get('release_id') or '') or None
                decision = self._baseline_rollout_next_allowed_time(
                    rollout_policy=policy,
                    requested_at=float(candidate),
                    tenant_id=promotion_release.get('tenant_id'),
                    workspace_id=promotion_release.get('workspace_id'),
                    environment=portfolio_environment,
                    portfolio_release=portfolio_release,
                    maintenance_already_satisfied=bool(maintenance_state_by_portfolio.get(portfolio_id)),
                )
                maintenance_state_by_portfolio[portfolio_id] = bool(decision.get('maintenance_satisfied', False))
                decision['portfolio_id'] = portfolio_id
                decision['portfolio_name'] = str((portfolio_release or {}).get('name') or '') or None
                decision['environment'] = self._normalize_portfolio_environment_name(portfolio_environment)
                decisions.append(decision)
                combined_blockers.extend(list(decision.get('blockers') or []))
                combined_windows.extend([dict(item) for item in list(decision.get('blocker_windows') or [])])
                next_allowed_at = decision.get('next_allowed_at')
                if next_allowed_at is None:
                    if not bool(decision.get('allowed', False)):
                        fatal = True
                        fatal_reason = str(decision.get('reason') or 'window_blocked')
                    continue
                next_candidates.append(float(next_allowed_at))
                if float(next_allowed_at) > candidate + 1e-6 or not bool(decision.get('allowed', False)):
                    all_allowed = False
            last_decisions = decisions
            if fatal:
                return {
                    'allowed': False,
                    'reason': fatal_reason or 'window_blocked',
                    'requested_at': float(requested_at),
                    'next_allowed_at': None,
                    'blockers': self._baseline_promotion_unique_ids(combined_blockers),
                    'blocker_windows': combined_windows[-50:],
                    'portfolio_decisions': last_decisions,
                }
            next_candidate = max(next_candidates) if next_candidates else candidate
            if all_allowed and next_candidate <= candidate + 1e-6:
                return {
                    'allowed': True,
                    'requested_at': float(requested_at),
                    'next_allowed_at': float(candidate),
                    'blockers': self._baseline_promotion_unique_ids(combined_blockers),
                    'blocker_windows': combined_windows[-50:],
                    'portfolio_decisions': last_decisions,
                }
            if next_candidate <= candidate + 1e-6:
                return {
                    'allowed': False,
                    'reason': 'window_resolution_exceeded',
                    'requested_at': float(requested_at),
                    'next_allowed_at': None,
                    'blockers': self._baseline_promotion_unique_ids(combined_blockers),
                    'blocker_windows': combined_windows[-50:],
                    'portfolio_decisions': last_decisions,
                }
            candidate = float(next_candidate)
        return {
            'allowed': False,
            'reason': 'window_resolution_exceeded',
            'requested_at': float(requested_at),
            'next_allowed_at': None,
            'blockers': self._baseline_promotion_unique_ids(combined_blockers),
            'blocker_windows': combined_windows[-50:],
            'portfolio_decisions': last_decisions,
        }

    def _set_portfolio_baseline_catalog_rollout_state(
        self,
        gw,
        *,
        portfolio_release: dict[str, Any],
        promotion_release: dict[str, Any],
        actor: str,
        status: str,
        active: bool,
        wave_no: int | None = None,
        wave_id: str | None = None,
        reason: str = '',
    ) -> dict[str, Any]:
        promotion = dict(((promotion_release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
        env_key = self._normalize_portfolio_environment_name(portfolio_release.get('environment'))
        candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(promotion.get('candidate_baselines') or {}))
        candidate_entry = dict(candidate_baselines.get(env_key) or {})
        metadata = dict(portfolio_release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        history = [dict(item) for item in list(portfolio.get('baseline_catalog_rollout_history') or [])]
        record = {
            'promotion_id': str(promotion_release.get('release_id') or ''),
            'catalog_id': str(promotion.get('catalog_id') or ''),
            'catalog_version': str(promotion.get('candidate_catalog_version') or promotion_release.get('version') or ''),
            'recorded_at': time.time(),
            'recorded_by': str(actor or 'admin'),
            'status': str(status or '').strip() or 'unknown',
            'active': bool(active),
            'wave_no': int(wave_no or 0) if wave_no is not None else None,
            'wave_id': str(wave_id or '').strip() or None,
            'reason': str(reason or '').strip(),
            'candidate_baselines': {env_key: candidate_entry} if candidate_entry else {},
        }
        history.append(dict(record))
        portfolio['baseline_catalog_rollout_history'] = history[-50:]
        portfolio['current_baseline_catalog_rollout'] = record
        metadata['portfolio'] = portfolio
        return gw.audit.update_release_bundle(
            str(portfolio_release.get('release_id') or ''),
            metadata=metadata,
            tenant_id=portfolio_release.get('tenant_id'),
            workspace_id=portfolio_release.get('workspace_id'),
            environment=portfolio_release.get('environment'),
        ) or portfolio_release

    def _simulate_portfolio_baseline_catalog_rollout_state(
        self,
        *,
        portfolio_release: dict[str, Any],
        promotion_release: dict[str, Any],
        actor: str,
        status: str,
        active: bool,
        wave_no: int | None = None,
        wave_id: str | None = None,
        reason: str = '',
    ) -> dict[str, Any]:
        promotion = dict(((promotion_release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
        env_key = self._normalize_portfolio_environment_name(portfolio_release.get('environment'))
        candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(promotion.get('candidate_baselines') or {}))
        candidate_entry = dict(candidate_baselines.get(env_key) or {})
        cloned_release = dict(portfolio_release or {})
        metadata = dict(cloned_release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        history = [dict(item) for item in list(portfolio.get('baseline_catalog_rollout_history') or [])]
        record = {
            'promotion_id': str(promotion_release.get('release_id') or ''),
            'catalog_id': str(promotion.get('catalog_id') or ''),
            'catalog_version': str(promotion.get('candidate_catalog_version') or promotion_release.get('version') or ''),
            'recorded_at': time.time(),
            'recorded_by': str(actor or 'admin'),
            'status': str(status or '').strip() or 'simulated',
            'active': bool(active),
            'wave_no': int(wave_no or 0) if wave_no is not None else None,
            'wave_id': str(wave_id or '').strip() or None,
            'reason': str(reason or '').strip(),
            'candidate_baselines': {env_key: candidate_entry} if candidate_entry else {},
            'simulated': True,
        }
        history.append(dict(record))
        portfolio['baseline_catalog_rollout_history'] = history[-50:]
        portfolio['current_baseline_catalog_rollout'] = record
        metadata['portfolio'] = portfolio
        cloned_release['metadata'] = metadata
        return cloned_release

    def _baseline_promotion_effective_signing_policy(
        self,
        *,
        promotion_release: dict[str, Any],
        promotion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(promotion or ((promotion_release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
        environment_key = str(promotion_release.get('environment') or 'prod').strip().lower() or 'prod'
        candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(payload.get('candidate_baselines') or {}))
        previous_baselines = self._normalize_baseline_catalog_environment_entries(dict(payload.get('previous_baselines') or {}))
        candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
        previous_entry = dict(previous_baselines.get(environment_key) or previous_baselines.get('default') or {})
        signing_policy = dict(candidate_entry.get('signing_policy') or previous_entry.get('signing_policy') or {})
        return self._normalize_portfolio_signing_policy(signing_policy)

    def _baseline_promotion_export_policy(
        self,
        *,
        promotion_release: dict[str, Any],
        promotion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        signing_policy = self._baseline_promotion_effective_signing_policy(promotion_release=promotion_release, promotion=promotion)
        return {
            'enabled': True,
            'require_signature': True,
            'timeline_limit': 250,
            'signer_key_id': str(signing_policy.get('key_id') or 'openmiura-local').strip() or 'openmiura-local',
        }

    def _baseline_promotion_simulation_effective_signing_policy(
        self,
        *,
        simulation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = dict(simulation or {})
        scope = dict(payload.get('scope') or {})
        environment_key = self._normalize_portfolio_environment_name(
            scope.get('environment')
            or ((payload.get('observed_context') or {}).get('catalog') or {}).get('environment')
            or 'prod'
        )
        candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(payload.get('candidate_baselines') or {}))
        previous_baselines = self._normalize_baseline_catalog_environment_entries(dict(payload.get('previous_baselines') or {}))
        candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
        previous_entry = dict(previous_baselines.get(environment_key) or previous_baselines.get('default') or {})
        if not candidate_entry and candidate_baselines:
            candidate_entry = dict(next(iter(candidate_baselines.values())) or {})
        if not previous_entry and previous_baselines:
            previous_entry = dict(next(iter(previous_baselines.values())) or {})
        signing_policy = dict(candidate_entry.get('signing_policy') or previous_entry.get('signing_policy') or {})
        return self._normalize_portfolio_signing_policy(signing_policy)

    def _baseline_promotion_simulation_export_policy(
        self,
        *,
        simulation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        signing_policy = self._baseline_promotion_simulation_effective_signing_policy(simulation=simulation)
        return {
            'enabled': True,
            'require_signature': True,
            'timeline_limit': 250,
            'signer_key_id': str(signing_policy.get('key_id') or 'openmiura-local').strip() or 'openmiura-local',
        }

    @staticmethod
    def _baseline_promotion_simulation_timeline_view(
        simulation: dict[str, Any] | None,
        *,
        limit: int = 250,
    ) -> dict[str, Any]:
        payload = dict(simulation or {})
        items: list[dict[str, Any]] = []
        simulated_at = payload.get('simulated_at')
        if simulated_at is not None:
            items.append({
                'ts': float(simulated_at),
                'kind': 'simulation',
                'label': 'baseline_promotion_simulated',
                'actor': str(payload.get('simulated_by') or ''),
                'simulation_id': str(payload.get('simulation_id') or ''),
                'simulation_status': str(payload.get('simulation_status') or ''),
            })
        for review in list(((payload.get('review_state') or {}).get('items') or [])):
            review_item = dict(review or {})
            items.append({
                'ts': float(review_item.get('decided_at') or review_item.get('created_at') or 0.0),
                'kind': 'review',
                'label': 'baseline_promotion_simulation_reviewed',
                'review_id': str(review_item.get('review_id') or ''),
                'layer_id': str(review_item.get('layer_id') or ''),
                'requested_role': str(review_item.get('requested_role') or ''),
                'decision': str(review_item.get('decision') or ''),
                'actor': str(review_item.get('actor') or ''),
                'reason': str(review_item.get('reason') or ''),
            })
        for created in list(payload.get('created_promotions') or []):
            created_item = dict(created or {})
            items.append({
                'ts': float(created_item.get('created_at') or 0.0),
                'kind': 'promotion',
                'label': 'baseline_promotion_created_from_simulation',
                'promotion_id': str(created_item.get('promotion_id') or ''),
                'status': str(created_item.get('status') or ''),
                'actor': str(created_item.get('created_by') or ''),
                'auto_approved': bool(created_item.get('auto_approved')),
                'diverged': bool(created_item.get('diverged')),
            })
        items.sort(key=lambda item: (float(item.get('ts') or 0.0), str(item.get('kind') or ''), str(item.get('label') or ''), str(item.get('review_id') or item.get('promotion_id') or '')))
        capped = items[-max(1, int(limit or 250)):]
        return {
            'items': capped,
            'summary': {
                'count': len(capped),
                'review_count': len([item for item in capped if str(item.get('kind') or '') == 'review']),
                'promotion_count': len([item for item in capped if str(item.get('kind') or '') == 'promotion']),
                'latest_label': capped[-1].get('label') if capped else None,
            },
        }

    def _build_baseline_promotion_simulation_attestation_export_payload(
        self,
        *,
        simulation: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        payload = dict(simulation or {})
        simulation_id = str(payload.get('simulation_id') or '').strip()
        scope = dict(payload.get('scope') or {})
        export_policy = self._baseline_promotion_simulation_export_policy(simulation=payload)
        signing_policy = self._baseline_promotion_simulation_effective_signing_policy(simulation=payload)
        timeline = self._baseline_promotion_simulation_timeline_view(payload, limit=max(25, int(timeline_limit or export_policy.get('timeline_limit') or 250)))
        review_state = dict(payload.get('review_state') or {})
        diff = dict(payload.get('diff') or {})
        report_id = str(self._stable_digest({
            'report_type': 'openmiura_baseline_promotion_simulation_attestation_v1',
            'simulation_id': simulation_id,
            'generated_by': str(actor or 'system'),
            'request_hash': str((payload.get('fingerprints') or {}).get('request_hash') or ''),
            'review_fingerprint': self._stable_digest(list(review_state.get('items') or [])),
        })[:24])
        report = {
            'report_id': report_id,
            'report_type': 'openmiura_baseline_promotion_simulation_attestation_v1',
            'generated_at': time.time(),
            'generated_by': str(actor or 'system'),
            'simulation': {
                'simulation_id': simulation_id,
                'mode': str(payload.get('mode') or ''),
                'simulation_status': str(payload.get('simulation_status') or ''),
                'simulated_at': payload.get('simulated_at'),
                'simulated_by': payload.get('simulated_by'),
                'reviewed_at': payload.get('reviewed_at'),
                'stale': bool(payload.get('stale')),
                'expired': bool(payload.get('expired')),
                'blocked': bool(payload.get('blocked')),
                'why_blocked': str(payload.get('why_blocked') or ''),
                'candidate_catalog_version': str(payload.get('candidate_catalog_version') or ''),
                'catalog_id': str(payload.get('catalog_id') or ''),
                'catalog_name': str(payload.get('catalog_name') or ''),
            },
            'scope': scope,
            'source': dict(payload.get('simulation_source') or {}),
            'request': dict(payload.get('request') or {}),
            'summary': dict(payload.get('summary') or {}),
            'validation': dict(payload.get('validation') or {}),
            'approval_preview': dict(payload.get('approval_preview') or {}),
            'simulation_policy': dict(payload.get('simulation_policy') or {}),
            'review': dict(payload.get('review') or {}),
            'review_state': {
                'overall_status': str(review_state.get('overall_status') or ''),
                'required': bool(review_state.get('required')),
                'approved': bool(review_state.get('approved')),
                'rejected': bool(review_state.get('rejected')),
                'review_count': int(review_state.get('review_count') or 0),
                'pending_layers': [str(item) for item in list(review_state.get('pending_layers') or []) if str(item)],
                'next_layer': dict(review_state.get('next_layer') or {}),
                'layers': [dict(item) for item in list(review_state.get('layers') or [])],
                'items': [dict(item) for item in list(review_state.get('items') or [])],
            },
            'observed_context': dict(payload.get('observed_context') or {}),
            'observed_versions': dict(payload.get('observed_versions') or payload.get('source_observed_versions') or {}),
            'fingerprints': dict(payload.get('fingerprints') or payload.get('source_fingerprints') or {}),
            'diff': {
                'summary': dict(diff.get('summary') or {}),
                'items': [
                    {
                        'environment': str(item.get('environment') or ''),
                        'changed': bool(item.get('changed')),
                        'change_type': str(item.get('change_type') or ''),
                        'compare': dict(item.get('compare') or {}),
                        'baseline_fingerprint': str(item.get('baseline_fingerprint') or ''),
                        'candidate_fingerprint': str(item.get('candidate_fingerprint') or ''),
                    }
                    for item in list(diff.get('items') or [])
                ],
            },
            'explainability': dict(payload.get('explainability') or {}),
            'created_promotions': [dict(item) for item in list(payload.get('created_promotions') or [])],
            'timeline': timeline,
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=report['report_type'],
            scope=scope,
            payload=report,
            actor=actor,
            export_policy=export_policy,
            signing_policy=signing_policy,
        )
        return {
            'ok': True,
            'simulation_id': simulation_id,
            'report': report,
            'integrity': integrity,
            'scope': scope,
        }

    def _baseline_promotion_simulation_effective_escrow_policy(
        self,
        *,
        simulation: dict[str, Any] | None,
        release: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        simulation_payload = dict(simulation or {})
        simulation_policy = dict(simulation_payload.get('simulation_policy') or {})
        scope = dict(simulation_payload.get('scope') or {})
        environment_key = self._normalize_portfolio_environment_name(
            scope.get('environment')
            or (release or {}).get('environment')
            or 'default'
        )
        raw_policy = dict(simulation_policy.get('escrow_policy') or {})
        if not raw_policy:
            candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(simulation_payload.get('candidate_baselines') or {}))
            candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
            raw_policy = dict(candidate_entry.get('escrow_policy') or {})
        if not raw_policy and release:
            promotion = dict(((release.get('metadata') or {}).get('baseline_promotion')) or {})
            candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(promotion.get('candidate_baselines') or {}))
            candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
            raw_policy = dict(candidate_entry.get('escrow_policy') or {})
            if not raw_policy:
                raw_policy = dict(((promotion.get('promotion_policy') or {}).get('escrow_policy')) or {})
        normalized = self._normalize_portfolio_escrow_policy(raw_policy)
        if normalized.get('enabled') and not str(normalized.get('archive_namespace') or '').strip():
            normalized['archive_namespace'] = 'baseline-promotion-simulation-evidence'
        elif not str(normalized.get('archive_namespace') or '').strip():
            normalized['archive_namespace'] = 'baseline-promotion-simulation-evidence'
        return normalized

    def _baseline_promotion_simulation_export_registry_entries(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        items = [dict(item) for item in list(promotion.get('simulation_export_registry') or [])]
        items.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('appended_at') or 0.0), str(item.get('entry_id') or '')))
        return items

    def _baseline_promotion_simulation_export_registry_summary(self, release: dict[str, Any] | None) -> dict[str, Any]:
        entries = self._baseline_promotion_simulation_export_registry_entries(release)
        packages = self._list_baseline_promotion_simulation_evidence_packages(release)
        chain_ok = True
        broken_sequences = 0
        previous_hash = ''
        expected_sequence = 1
        immutable_count = 0
        escrowed_count = 0
        immutable_archive_count = 0
        latest_archive_path = None
        latest_receipt_id = None
        for package in packages:
            escrow = dict(package.get('escrow') or {})
            if bool(escrow.get('archived')):
                escrowed_count += 1
                latest_archive_path = latest_archive_path or escrow.get('archive_path')
                latest_receipt_id = latest_receipt_id or escrow.get('receipt_id')
                if escrow.get('immutable_until') is not None:
                    immutable_archive_count += 1
        for entry in entries:
            if int(entry.get('sequence') or 0) != expected_sequence:
                broken_sequences += 1
                chain_ok = False
                expected_sequence = int(entry.get('sequence') or expected_sequence)
            core = dict(entry.get('entry_core') or {})
            actual_hash = self._stable_digest(core)
            if str(entry.get('previous_entry_hash') or '') != previous_hash:
                chain_ok = False
            if str(entry.get('entry_hash') or '') != actual_hash:
                chain_ok = False
            if bool(entry.get('immutable')):
                immutable_count += 1
            previous_hash = str(entry.get('entry_hash') or '')
            expected_sequence += 1
        latest = entries[-1] if entries else {}
        return {
            'count': len(entries),
            'package_count': len(packages),
            'latest_entry_id': str(latest.get('entry_id') or ''),
            'latest_package_id': str(latest.get('package_id') or ''),
            'latest_entry_hash': str(latest.get('entry_hash') or ''),
            'chain_ok': chain_ok,
            'broken_sequence_count': broken_sequences,
            'immutable_count': immutable_count,
            'escrowed_count': escrowed_count,
            'immutable_archive_count': immutable_archive_count,
            'latest_archive_path': latest_archive_path,
            'latest_receipt_id': latest_receipt_id,
        }

    def _list_baseline_promotion_simulation_restore_sessions(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        items = [dict(item) for item in list(promotion.get('simulation_restore_sessions') or [])]
        items.sort(key=lambda item: (float(item.get('restored_at') or 0.0), str(item.get('restore_id') or '')), reverse=True)
        return items

    def _store_baseline_promotion_simulation_restore_session(
        self,
        gw,
        *,
        release: dict[str, Any],
        session_record: dict[str, Any],
        restore_history_limit: int = 20,
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        sessions = [dict(item) for item in list(promotion.get('simulation_restore_sessions') or [])]
        sessions = [item for item in sessions if str(item.get('restore_id') or '') != str(session_record.get('restore_id') or '')]
        sessions.append(dict(session_record))
        sessions.sort(key=lambda item: (float(item.get('restored_at') or 0.0), str(item.get('restore_id') or '')), reverse=True)
        promotion['simulation_restore_sessions'] = sessions[: max(1, int(restore_history_limit or 20))]
        promotion = self._append_baseline_promotion_timeline_event(
            promotion,
            kind='evidence',
            label='baseline_promotion_simulation_evidence_restored',
            actor=str(session_record.get('restored_by') or 'system'),
            restore_id=str(session_record.get('restore_id') or ''),
            package_id=str(session_record.get('package_id') or ''),
            simulation_id=str(session_record.get('simulation_id') or ''),
            replay_status=str(((session_record.get('replay') or {}).get('simulation_status')) or ''),
            artifact_sha256=str(session_record.get('artifact_sha256') or ''),
        )
        metadata['baseline_promotion'] = promotion
        return gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release

    def _build_baseline_promotion_rollback_attestation(
        self,
        *,
        promotion_release: dict[str, Any],
        promotion: dict[str, Any],
        actor: str,
        reason: str = '',
        trigger: str = 'manual',
        wave_no: int | None = None,
        affected_portfolio_ids: list[str] | None = None,
        rollout_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        created_at = time.time()
        resolved_promotion = dict(promotion or {})
        resolved_rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(rollout_plan or resolved_promotion.get('rollout_plan') or {}))
        affected_ids = self._baseline_promotion_unique_ids(list(affected_portfolio_ids or []))
        attestation = {
            'attestation_id': f'baseline-rollback-{str(promotion_release.get("release_id") or "")}-{int(created_at)}',
            'report_type': 'openmiura_baseline_promotion_rollback_attestation_v1',
            'generated_at': created_at,
            'generated_by': str(actor or 'admin'),
            'created_at': created_at,
            'created_by': str(actor or 'admin'),
            'trigger': str(trigger or 'manual'),
            'reason': str(reason or '').strip(),
            'wave_no': int(wave_no or 0) if wave_no is not None else None,
            'promotion_id': str(promotion_release.get('release_id') or ''),
            'promotion_status_before': str(promotion_release.get('status') or ''),
            'catalog_id': str(resolved_promotion.get('catalog_id') or ''),
            'catalog_name': str(resolved_promotion.get('catalog_name') or ''),
            'candidate_catalog_version': str(resolved_promotion.get('candidate_catalog_version') or promotion_release.get('version') or ''),
            'previous_catalog_version': str(resolved_promotion.get('previous_catalog_version') or ''),
            'scope': self._scope(tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')),
            'affected_portfolio_ids': affected_ids,
            'affected_portfolio_count': len(affected_ids),
            'rollout': {
                'wave_count': int(resolved_rollout_plan.get('wave_count') or 0),
                'completed_wave_count': int(resolved_rollout_plan.get('completed_wave_count') or 0),
                'applied_portfolio_ids': list(resolved_rollout_plan.get('applied_portfolio_ids') or []),
                'rolled_back_portfolio_ids': affected_ids,
                'summary': dict(resolved_rollout_plan.get('summary') or {}),
            },
            'rollback_policy': dict(((resolved_promotion.get('promotion_policy') or {}).get('rollback_policy') or {})),
            'timeline_summary': {
                'count': len(list(resolved_promotion.get('timeline') or [])),
                'last_label': ((list(resolved_promotion.get('timeline') or []) or [{}])[-1].get('label')) if list(resolved_promotion.get('timeline') or []) else None,
            },
        }
        attestation['integrity'] = self._portfolio_evidence_integrity(
            report_type=str(attestation.get('report_type') or 'openmiura_baseline_promotion_rollback_attestation_v1'),
            scope=dict(attestation.get('scope') or {}),
            payload=dict(attestation),
            actor=actor,
            export_policy=self._baseline_promotion_export_policy(promotion_release=promotion_release, promotion=resolved_promotion),
            signing_policy=self._baseline_promotion_effective_signing_policy(promotion_release=promotion_release, promotion=resolved_promotion),
        )
        return attestation

    def _build_baseline_promotion_attestation_export_payload(
        self,
        *,
        detail: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        release = dict(detail.get('release') or {})
        promotion = dict(detail.get('baseline_promotion') or {})
        export_policy = self._baseline_promotion_export_policy(promotion_release=release, promotion=promotion)
        signing_policy = self._baseline_promotion_effective_signing_policy(promotion_release=release, promotion=promotion)
        timeline = self._baseline_promotion_timeline_view(release, limit=max(25, int(timeline_limit or export_policy.get('timeline_limit') or 250)))
        report = {
            'report_type': 'openmiura_baseline_promotion_attestation_export_v1',
            'generated_at': time.time(),
            'generated_by': str(actor or 'system'),
            'promotion': {
                'promotion_id': str(detail.get('promotion_id') or release.get('release_id') or ''),
                'name': release.get('name'),
                'version': release.get('version'),
                'status': release.get('status'),
                'catalog_id': promotion.get('catalog_id'),
                'catalog_name': promotion.get('catalog_name'),
                'previous_catalog_version': promotion.get('previous_catalog_version'),
                'candidate_catalog_version': promotion.get('candidate_catalog_version'),
            },
            'scope': dict(detail.get('scope') or {}),
            'approvals': dict(detail.get('approvals') or {}),
            'rollout_plan': dict(promotion.get('rollout_plan') or {}),
            'rollout_impact': dict(promotion.get('rollout_impact') or {}),
            'promotion_policy': dict(promotion.get('promotion_policy') or {}),
            'analytics': dict(detail.get('analytics') or {}),
            'advance_jobs': dict(detail.get('advance_jobs') or {}),
            'rollback_attestations': dict(detail.get('rollback_attestations') or {}),
            'timeline': timeline,
            'catalog': {
                'catalog_id': ((detail.get('catalog') or {}).get('catalog_id')),
                'current_version': (((detail.get('catalog') or {}).get('baseline_catalog') or {}).get('current_version')),
            },
            'created_from_simulation': dict(promotion.get('created_from_simulation') or {}),
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=report['report_type'],
            scope=dict(detail.get('scope') or {}),
            payload=report,
            actor=actor,
            export_policy=export_policy,
            signing_policy=signing_policy,
        )
        return {
            'ok': True,
            'promotion_id': detail.get('promotion_id') or release.get('release_id'),
            'report': report,
            'integrity': integrity,
            'scope': detail.get('scope'),
        }

    def _build_baseline_promotion_postmortem_export_payload(
        self,
        *,
        detail: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        release = dict(detail.get('release') or {})
        promotion = dict(detail.get('baseline_promotion') or {})
        analytics = dict(detail.get('analytics') or {})
        export_policy = self._baseline_promotion_export_policy(promotion_release=release, promotion=promotion)
        signing_policy = self._baseline_promotion_effective_signing_policy(promotion_release=release, promotion=promotion)
        replay_limit = max(25, int(timeline_limit or export_policy.get('timeline_limit') or 250))
        timeline = self._baseline_promotion_timeline_view(release, limit=replay_limit)
        rollback_items = [dict(item) for item in list(((detail.get('rollback_attestations') or {}).get('items') or []))]
        latest_rollback = rollback_items[-1] if rollback_items else None
        report = {
            'report_type': 'openmiura_baseline_promotion_postmortem_v1',
            'generated_at': time.time(),
            'generated_by': str(actor or 'system'),
            'promotion': {
                'promotion_id': str(detail.get('promotion_id') or release.get('release_id') or ''),
                'name': release.get('name'),
                'version': release.get('version'),
                'status': release.get('status'),
                'catalog_id': promotion.get('catalog_id'),
                'catalog_name': promotion.get('catalog_name'),
                'previous_catalog_version': promotion.get('previous_catalog_version'),
                'candidate_catalog_version': promotion.get('candidate_catalog_version'),
            },
            'scope': dict(detail.get('scope') or {}),
            'summary': {
                'final_status': str(release.get('status') or ''),
                'gate_failed': bool(analytics.get('gate_failed')),
                'gate_failed_wave_no': analytics.get('gate_failed_wave_no'),
                'completed_wave_count': int(analytics.get('completed_wave_count') or 0),
                'wave_count': int(analytics.get('wave_count') or 0),
                'rollback_attestation_count': len(rollback_items),
                'dependency_blocked_wave_count': int(analytics.get('dependency_blocked_wave_count') or 0),
                'due_advance_job_count': int(analytics.get('due_advance_job_count') or 0),
            },
            'analytics': analytics,
            'approvals': dict(detail.get('approvals') or {}),
            'advance_jobs': dict(detail.get('advance_jobs') or {}),
            'rollout_plan': dict(promotion.get('rollout_plan') or {}),
            'rollout_impact': dict(promotion.get('rollout_impact') or {}),
            'timeline': timeline,
            'rollback': {
                'rolled_back': str(release.get('status') or '') == 'rolled_back',
                'latest_attestation': latest_rollback,
                'attestation_ids': [item.get('attestation_id') for item in rollback_items],
                'items': rollback_items,
            },
            'latest_health': analytics.get('latest_health'),
            'wave_health_curve': list(analytics.get('wave_health_curve') or []),
            'gate_reason_counts': dict(analytics.get('gate_reason_counts') or {}),
            'catalog': detail.get('catalog'),
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=report['report_type'],
            scope=dict(detail.get('scope') or {}),
            payload=report,
            actor=actor,
            export_policy=export_policy,
            signing_policy=signing_policy,
        )
        return {
            'ok': True,
            'promotion_id': detail.get('promotion_id') or release.get('release_id'),
            'report': report,
            'integrity': integrity,
            'scope': detail.get('scope'),
        }

