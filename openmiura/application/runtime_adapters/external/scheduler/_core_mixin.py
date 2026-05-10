"""scheduler._core_mixin

Sub-mixin extracted from OpenClawRecoverySchedulerService; original imports replicated.
"""
from __future__ import annotations

import base64
import hashlib
import json
import importlib
import os
import socket
import sqlite3
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key

from openmiura.application.jobs import JobService
from openmiura.application.runtime_adapters.external.service import OpenClawAdapterService
from openmiura.application.runtime_adapters.external.baseline_rollout_management import OpenClawBaselineRolloutManagementMixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import OpenClawBaselineRolloutSupportMixin
from openmiura.application.runtime_adapters.external.baseline_rollout_state import OpenClawBaselineRolloutStateMixin
from openmiura.application.runtime_adapters.external.baseline_rollout_jobs import OpenClawBaselineRolloutJobsMixin
from openmiura.application.runtime_adapters.external.baseline_rollout_gates import OpenClawBaselineRolloutGatesMixin
from openmiura.application.runtime_adapters.external.alert_governance_bundle_management import OpenClawAlertGovernanceBundleManagementMixin
from openmiura.application.runtime_adapters.external.alert_governance_bundle_jobs import OpenClawAlertGovernanceBundleJobsMixin
from openmiura.application.runtime_adapters.external.alert_governance_bundle_gates import OpenClawAlertGovernanceBundleGatesMixin
from openmiura.application.runtime_adapters.external.policy_normalization import OpenClawPolicyNormalizationMixin
from openmiura.application.runtime_adapters.external.evidence_builders import OpenClawEvidenceBuildersMixin
from openmiura.application.runtime_adapters.external.runtime_rollout_summaries import OpenClawRuntimeRolloutSummariesMixin
from openmiura.application.runtime_adapters.external.runtime_alert_common import OpenClawRuntimeAlertCommonMixin
from openmiura.application.runtime_adapters.external.runtime_alert_execution import OpenClawRuntimeAlertExecutionMixin
from openmiura.application.runtime_adapters.external.runtime_alert_notifications import OpenClawRuntimeAlertNotificationsMixin
from openmiura.application.runtime_adapters.external.runtime_alert_escalations import OpenClawRuntimeAlertEscalationsMixin
from openmiura.application.runtime_adapters.external.temporal_windows import OpenClawTemporalWindowsMixin
from openmiura.application.runtime_adapters.external.job_family_common import OpenClawJobFamilyCommonMixin
from openmiura.application.runtime_adapters.external.runtime_context import OpenClawRuntimeContextMixin
from openmiura.application.runtime_adapters.external.approval_common import OpenClawApprovalCommonMixin
from openmiura.application.runtime_adapters.external.governance_explainability import OpenClawGovernanceExplainabilityMixin
from openmiura.application.runtime_adapters.external.scheduler_primitives import (
    alert_delivery_job_definition,
    baseline_simulation_custody_job_definition,
    baseline_simulation_custody_job_id,
    baseline_wave_advance_job_definition,
    baseline_wave_job_id,
    decorate_idempotency_record,
    decorate_worker_lease,
    due_slot,
    governance_wave_advance_job_definition,
    governance_wave_job_id,
    holder_id,
    is_workflow_job,
    job_idempotency_key,
    job_lease_key,
    lease_type,
    recovery_job_definition,
    runtime_lease_key,
    scheduler_policy,
    scope as scheduler_scope,
    workspace_lease_keys,
    workspace_lease_prefix,
)



OpenClawRecoverySchedulerService: type | None = None  # late-bound by __init__.py


class _OpenClawRecoverySchedulerServiceCoreMixin:
    """Sub-mixin: core."""

    @staticmethod
    def _scope(*, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return scheduler_scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    @staticmethod
    def _job_definition(
        *,
        runtime_id: str,
        actor: str,
        limit: int,
        reason: str,
        scheduler_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return recovery_job_definition(
            runtime_id=runtime_id,
            actor=actor,
            limit=limit,
            reason=reason,
            scheduler_policy=scheduler_policy,
            kind=OpenClawRecoverySchedulerService.JOB_KIND,
        )

    @classmethod
    def _is_alert_delivery_job(cls, item: dict[str, Any] | None, *, runtime_id: str | None = None) -> bool:
        return is_workflow_job(item, kind=cls.ALERT_DELIVERY_JOB_KIND, field_name='runtime_id' if runtime_id is not None else None, field_value=runtime_id)

    @staticmethod
    def _alert_delivery_job_definition(
        *,
        runtime_id: str,
        alert_code: str,
        workflow_action: str,
        actor: str,
        target: dict[str, Any],
        reason: str,
        escalation_level: int,
        attempt_no: int = 0,
        notification_dispatch_id: str = '',
        route: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return alert_delivery_job_definition(
            runtime_id=runtime_id,
            alert_code=alert_code,
            workflow_action=workflow_action,
            actor=actor,
            target=target,
            reason=reason,
            escalation_level=escalation_level,
            attempt_no=attempt_no,
            notification_dispatch_id=notification_dispatch_id,
            route=route,
            kind=OpenClawRecoverySchedulerService.ALERT_DELIVERY_JOB_KIND,
        )

    @classmethod
    def _is_governance_wave_advance_job(cls, item: dict[str, Any] | None, *, bundle_id: str | None = None) -> bool:
        return is_workflow_job(item, kind=cls.GOVERNANCE_WAVE_ADVANCE_JOB_KIND, field_name='bundle_id' if bundle_id is not None else None, field_value=bundle_id)

    @staticmethod
    def _governance_wave_advance_job_definition(
        *,
        bundle_id: str,
        source_wave_no: int,
        next_wave_no: int | None,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        return governance_wave_advance_job_definition(
            bundle_id=bundle_id,
            source_wave_no=source_wave_no,
            next_wave_no=next_wave_no,
            actor=actor,
            reason=reason,
            kind=OpenClawRecoverySchedulerService.GOVERNANCE_WAVE_ADVANCE_JOB_KIND,
        )

    @staticmethod
    def _governance_wave_job_id(bundle_id: str, source_wave_no: int) -> str:
        return governance_wave_job_id(bundle_id, source_wave_no)

    @classmethod
    def _is_baseline_wave_advance_job(cls, item: dict[str, Any] | None, *, promotion_id: str | None = None) -> bool:
        return is_workflow_job(item, kind=cls.BASELINE_WAVE_ADVANCE_JOB_KIND, field_name='promotion_id' if promotion_id is not None else None, field_value=promotion_id)

    @staticmethod
    def _baseline_wave_advance_job_definition(
        *,
        promotion_id: str,
        source_wave_no: int,
        next_wave_no: int | None,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        return baseline_wave_advance_job_definition(
            promotion_id=promotion_id,
            source_wave_no=source_wave_no,
            next_wave_no=next_wave_no,
            actor=actor,
            reason=reason,
            kind=OpenClawRecoverySchedulerService.BASELINE_WAVE_ADVANCE_JOB_KIND,
        )

    @staticmethod
    def _baseline_wave_job_id(promotion_id: str, source_wave_no: int) -> str:
        return baseline_wave_job_id(promotion_id, source_wave_no)

    @classmethod
    def _is_baseline_simulation_custody_job(cls, item: dict[str, Any] | None, *, promotion_id: str | None = None) -> bool:
        return is_workflow_job(item, kind=cls.BASELINE_SIMULATION_CUSTODY_JOB_KIND, field_name='promotion_id' if promotion_id is not None else None, field_value=promotion_id)

    @staticmethod
    def _baseline_simulation_custody_job_definition(
        *,
        promotion_id: str,
        actor: str,
        interval_s: int,
        reason: str,
    ) -> dict[str, Any]:
        return baseline_simulation_custody_job_definition(
            promotion_id=promotion_id,
            actor=actor,
            interval_s=interval_s,
            reason=reason,
            kind=OpenClawRecoverySchedulerService.BASELINE_SIMULATION_CUSTODY_JOB_KIND,
        )

    @staticmethod
    def _baseline_simulation_custody_job_id(promotion_id: str) -> str:
        return baseline_simulation_custody_job_id(promotion_id)

    @staticmethod
    def _holder_id(actor: str) -> str:
        return holder_id(actor)

    @staticmethod
    def _due_slot(item: dict[str, Any] | None, *, now: float | None = None) -> int:
        return due_slot(item, now=now)

    @staticmethod
    def _job_lease_key(job_id: str) -> str:
        return job_lease_key(job_id)

    @staticmethod
    def _runtime_lease_key(runtime_id: str) -> str:
        return runtime_lease_key(runtime_id)

    @classmethod
    def _workspace_lease_prefix(cls, scope: dict[str, Any]) -> str:
        return workspace_lease_prefix(scope)

    @classmethod
    def _workspace_lease_keys(cls, scope: dict[str, Any], *, limit: int) -> list[str]:
        return workspace_lease_keys(scope, limit=limit)

    @staticmethod
    def _job_idempotency_key(job_id: str, due_slot: int) -> str:
        return job_idempotency_key(job_id, due_slot)

    @staticmethod
    def _lease_type(lease_key: str) -> str:
        return lease_type(lease_key)

    @staticmethod
    def _decorate_worker_lease(item: dict[str, Any] | None, *, now: float | None = None) -> dict[str, Any]:
        return decorate_worker_lease(item, now=now)

    @staticmethod
    def _decorate_idempotency_record(item: dict[str, Any] | None, *, now: float | None = None) -> dict[str, Any]:
        return decorate_idempotency_record(item, now=now)

    @staticmethod
    def _alert_key(runtime_id: str, alert_code: str) -> str:
        return f'openclaw-alert:{str(runtime_id or "").strip()}:{str(alert_code or "").strip()}'

    @staticmethod
    def _scope_matches(match: dict[str, Any] | None, scope: dict[str, Any] | None) -> bool:
        criteria = dict(match or {})
        current = dict(scope or {})
        for key in ('tenant_id', 'workspace_id', 'environment', 'runtime_class'):
            expected = criteria.get(key)
            if expected in (None, '', []):
                continue
            if str(current.get(key) or '').strip() != str(expected).strip():
                return False
        return True

    @classmethod
    def _quiet_hours_decision(cls, *, policy: dict[str, Any], alert: dict[str, Any], now_ts: float) -> dict[str, Any]:
        quiet = dict(policy.get('quiet_hours') or {})
        if not bool(quiet.get('enabled')):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'window': {}}
        severity = str(alert.get('severity') or '').strip().lower()
        code = str(alert.get('code') or '').strip()
        if severity and severity in set(quiet.get('allow_severities') or []):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'window': {'bypass': 'severity'}}
        if code and code in set(quiet.get('allow_alert_codes') or []):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'window': {'bypass': 'alert_code'}}
        state = cls._recurring_window_state(weekdays=list(quiet.get('weekdays') or []), start_time=str(quiet.get('start_time') or '22:00'), end_time=str(quiet.get('end_time') or '06:00'), timezone_name=str(quiet.get('timezone') or policy.get('default_timezone') or 'UTC'), now_ts=now_ts)
        if not bool(state.get('active')):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'window': state}
        action = str(quiet.get('action') or 'schedule').strip().lower() or 'schedule'
        next_allowed_at = state.get('active_until') if action == 'schedule' else float(now_ts) + float(quiet.get('suppress_for_s') or 900)
        return {'active': True, 'suppressed': action == 'suppress', 'scheduled': action == 'schedule', 'reasons': ['quiet_hours'], 'next_allowed_at': next_allowed_at, 'window': state, 'action': action}

    @classmethod
    def _maintenance_decision(cls, *, policy: dict[str, Any], alert: dict[str, Any], now_ts: float) -> dict[str, Any]:
        severity = str(alert.get('severity') or '').strip().lower()
        code = str(alert.get('code') or '').strip()
        active_windows: list[dict[str, Any]] = []
        suppressed = False
        scheduled = False
        next_allowed_at = None
        for window in list(policy.get('maintenance_windows') or []):
            if not bool(window.get('enabled', True)):
                continue
            allowed_severities = [str(item).strip().lower() for item in list(window.get('allow_severities') or []) if str(item).strip()]
            allowed_codes = [str(item).strip() for item in list(window.get('allow_alert_codes') or []) if str(item).strip()]
            if severity and severity in set(allowed_severities):
                continue
            if code and code in set(allowed_codes):
                continue
            if window.get('starts_at') is not None and window.get('ends_at') is not None:
                state = cls._absolute_window_state(starts_at=window.get('starts_at'), ends_at=window.get('ends_at'), now_ts=now_ts)
            else:
                state = cls._recurring_window_state(weekdays=list(window.get('weekdays') or window.get('days') or []), start_time=str(window.get('start_time') or '00:00'), end_time=str(window.get('end_time') or '23:59'), timezone_name=str(window.get('timezone') or policy.get('default_timezone') or 'UTC'), now_ts=now_ts)
            if not bool(state.get('active')):
                continue
            action = str(window.get('action') or 'suppress').strip().lower() or 'suppress'
            window_view = {**dict(window), 'state': state, 'action': action}
            active_windows.append(window_view)
            if action == 'suppress':
                suppressed = True
                next_allowed_at = max(float(next_allowed_at or 0.0), float(state.get('active_until') or 0.0)) if state.get('active_until') else next_allowed_at
            elif action == 'schedule' and not suppressed:
                scheduled = True
                next_allowed_at = max(float(next_allowed_at or 0.0), float(state.get('active_until') or 0.0)) if state.get('active_until') else next_allowed_at
        return {'active': bool(active_windows), 'suppressed': suppressed, 'scheduled': scheduled and not suppressed, 'reasons': ['maintenance_window'] if active_windows else [], 'next_allowed_at': next_allowed_at, 'windows': active_windows}

    @classmethod
    def _storm_decision(cls, *, policy: dict[str, Any], alert: dict[str, Any], alerts: list[dict[str, Any]], now_ts: float) -> dict[str, Any]:
        storm = dict(policy.get('storm_policy') or {})
        if not bool(storm.get('enabled')):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'summary': {}}
        code = str(alert.get('code') or '').strip()
        if code and code in set(storm.get('allow_alert_codes') or []):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'summary': {'bypass': 'alert_code'}}
        severity = str(alert.get('severity') or '').strip().lower()
        suppressible = severity in set(storm.get('suppress_severities') or [])
        active_alert_threshold = int(storm.get('active_alert_threshold') or 0)
        severity_counts: dict[str, int] = {}
        code_counts: dict[str, int] = {}
        for item in list(alerts or []):
            sev_key = str(item.get('severity') or '').strip().lower() or 'warn'
            severity_counts[sev_key] = severity_counts.get(sev_key, 0) + 1
            code_key = str(item.get('code') or '').strip() or 'runtime_alert'
            code_counts[code_key] = code_counts.get(code_key, 0) + 1
        active = False
        if active_alert_threshold and len(list(alerts or [])) >= active_alert_threshold:
            active = True
        per_severity = dict(storm.get('per_severity_thresholds') or {})
        if severity and int(per_severity.get(severity) or 0) > 0 and severity_counts.get(severity, 0) >= int(per_severity.get(severity) or 0):
            active = True
        if not active or not suppressible:
            return {'active': active, 'suppressed': False, 'scheduled': False, 'reasons': ['alert_storm'] if active else [], 'next_allowed_at': None, 'summary': {'severity_counts': severity_counts, 'code_counts': code_counts, 'alert_count': len(list(alerts or []))}}
        action = str(storm.get('action') or 'suppress').strip().lower() or 'suppress'
        next_allowed_at = float(now_ts) + float(storm.get('suppress_for_s') or 600)
        return {'active': True, 'suppressed': action == 'suppress', 'scheduled': action == 'schedule', 'reasons': ['alert_storm'], 'next_allowed_at': next_allowed_at, 'summary': {'severity_counts': severity_counts, 'code_counts': code_counts, 'alert_count': len(list(alerts or []))}, 'action': action}

    @classmethod
    def _governance_promotion_requires_approval(cls, *, release_policy: dict[str, Any], simulation: dict[str, Any]) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if bool(release_policy.get('approval_required')):
            reasons.append('approval_required')
        summary = dict(simulation.get('summary') or {})
        affected_count = int(summary.get('affected_count') or 0)
        threshold = int(release_policy.get('approval_on_affected_count_ge') or 0)
        if threshold > 0 and affected_count >= threshold:
            reasons.append(f'affected_count>={threshold}')
        changed_keys = set(dict(simulation.get('policy_diff') or {}).get('changed_keys') or [])
        critical_keys = set(release_policy.get('critical_changed_keys') or [])
        matched_keys = sorted(changed_keys & critical_keys)
        if bool(release_policy.get('approval_on_critical_change')) and matched_keys:
            reasons.append('critical_keys:' + ','.join(matched_keys))
        return (bool(reasons), reasons)

    @staticmethod
    def _governance_release_signature(*, runtime_id: str, version_id: str, version_no: int, policy_kind: str, policy: dict[str, Any], diff: dict[str, Any], signer_key_id: str) -> str:
        payload = {
            'runtime_id': str(runtime_id or '').strip(),
            'version_id': str(version_id or '').strip(),
            'version_no': int(version_no or 0),
            'policy_kind': str(policy_kind or 'alert_governance').strip(),
            'policy': dict(policy or {}),
            'diff': dict(diff or {}),
            'signer_key_id': str(signer_key_id or 'openmiura-local').strip(),
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
        return hashlib.sha256(encoded).hexdigest()

    def _signed_governance_release(self, *, runtime_id: str, version_id: str, version_no: int, policy_kind: str, policy: dict[str, Any], diff: dict[str, Any], actor: str, release_policy: dict[str, Any], activated_at: float) -> dict[str, Any]:
        require_signature = bool(release_policy.get('require_signature', True))
        signer_key_id = str(release_policy.get('signer_key_id') or 'openmiura-local').strip() or 'openmiura-local'
        signature = self._governance_release_signature(
            runtime_id=runtime_id,
            version_id=version_id,
            version_no=version_no,
            policy_kind=policy_kind,
            policy=policy,
            diff=diff,
            signer_key_id=signer_key_id,
        ) if require_signature else ''
        return {
            'release_id': f'govrel-{runtime_id}-{version_no}',
            'policy_kind': str(policy_kind or 'alert_governance').strip() or 'alert_governance',
            'version_id': str(version_id or '').strip(),
            'version_no': int(version_no or 0),
            'status': 'active',
            'signed': bool(signature),
            'signature': signature or None,
            'signer_key_id': signer_key_id,
            'signed_by': str(actor or 'system').strip() or 'system',
            'signed_at': float(activated_at),
        }

    @classmethod
    def _is_baseline_catalog_release(cls, release: dict[str, Any] | None) -> bool:
        payload = dict(release or {})
        if str(payload.get('kind') or '').strip() != 'policy_baseline_catalog':
            return False
        metadata = dict(payload.get('metadata') or {})
        catalog = dict(metadata.get('baseline_catalog') or {})
        return str(catalog.get('kind') or '').strip() == 'openclaw_alert_governance_baseline_catalog'

    @classmethod
    def _is_baseline_promotion_release(cls, release: dict[str, Any] | None) -> bool:
        payload = dict(release or {})
        if str(payload.get('kind') or '').strip() != 'policy_baseline_promotion':
            return False
        metadata = dict(payload.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        return str(promotion.get('kind') or '').strip() == 'openclaw_alert_governance_baseline_promotion'

    @staticmethod
    def _baseline_promotion_approval_workflow_id(promotion_id: str) -> str:
        return f'openclaw-governance-baseline-promotion:{str(promotion_id or "").strip()}'

    @classmethod
    def _is_release_train_job(cls, item: dict[str, Any] | None, *, portfolio_id: str | None = None) -> bool:
        definition = dict((item or {}).get('workflow_definition') or {})
        if str(definition.get('kind') or '').strip().lower() != cls.GOVERNANCE_RELEASE_TRAIN_JOB_KIND:
            return False
        if portfolio_id is None:
            return True
        return str(definition.get('portfolio_id') or '').strip() == str(portfolio_id or '').strip()

    @staticmethod
    def _release_train_job_definition(*, portfolio_id: str, event_id: str, bundle_id: str, wave_no: int, actor: str, reason: str) -> dict[str, Any]:
        return {
            'kind': OpenClawRecoverySchedulerService.GOVERNANCE_RELEASE_TRAIN_JOB_KIND,
            'portfolio_id': str(portfolio_id or '').strip(),
            'event_id': str(event_id or '').strip(),
            'bundle_id': str(bundle_id or '').strip(),
            'wave_no': int(wave_no or 0),
            'created_by': str(actor or 'system'),
            'reason': str(reason or '').strip(),
        }

    @staticmethod
    def _stable_digest(payload: Any) -> str:
        normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    @staticmethod
    def _json_canonical_bytes(payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

    @staticmethod
    def _ed25519_public_key_pem(public_key: ed25519.Ed25519PublicKey) -> str:
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode('utf-8')

    @staticmethod
    def _ed25519_public_key_fingerprint(public_key: ed25519.Ed25519PublicKey) -> str:
        return hashlib.sha256(
            public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).hexdigest()

    @staticmethod
    def _public_key_pem(public_key: Any) -> str:
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode('utf-8')

    @staticmethod
    def _public_key_fingerprint(public_key: Any) -> str:
        return hashlib.sha256(
            public_key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).hexdigest()

    def _crypto_signature_result(
        self,
        *,
        signature_bytes: bytes,
        signature_scheme: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        public_key: Any,
        provider: str,
        key_origin: str,
        provider_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        public_key_pem = self._public_key_pem(public_key)
        return {
            'payload_hash': payload_hash,
            'signature': base64.b64encode(signature_bytes).decode('ascii'),
            'signature_scheme': str(signature_scheme or 'ed25519'),
            'signature_input': dict(signing_input or {}),
            'signature_input_hash': hashlib.sha256(self._json_canonical_bytes(signing_input)).hexdigest(),
            'public_key': {
                'algorithm': str(signature_scheme or 'ed25519'),
                'origin': key_origin,
                'provider': provider,
                'provider_metadata': dict(provider_metadata or {}),
                'public_key_pem': public_key_pem,
                'public_key_fingerprint': self._public_key_fingerprint(public_key),
            },
            'signer_provider': provider,
            'key_origin': key_origin,
        }

    @staticmethod
    def _load_ed25519_private_key_from_pem(pem: bytes, *, error_prefix: str) -> ed25519.Ed25519PrivateKey:
        loaded = load_pem_private_key(pem, password=None)
        if not isinstance(loaded, ed25519.Ed25519PrivateKey):
            raise TypeError(f'{error_prefix} must contain an Ed25519 private key')
        return loaded

    def _sign_with_aws_kms_native(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        boto3 = importlib.import_module('boto3')
        session_cls = getattr(getattr(boto3, 'session', boto3), 'Session', None)
        if session_cls is None:
            raise RuntimeError('aws_kms_session_unavailable')
        profile = str(policy.get('aws_profile') or '').strip() or None
        region = str(policy.get('aws_region') or '').strip() or None
        endpoint_url = str(policy.get('aws_endpoint_url') or '').strip() or None
        key_ref = str(policy.get('aws_kms_key_id') or policy.get('kms_key_ref') or signer_key_id or '').strip()
        if not key_ref:
            raise RuntimeError('aws_kms_key_id_missing')
        session = session_cls(profile_name=profile) if profile else session_cls()
        client = session.client('kms', region_name=region, endpoint_url=endpoint_url)
        message = self._json_canonical_bytes(signing_input)
        algorithm = str(policy.get('aws_signing_algorithm') or 'ECDSA_SHA_256').strip() or 'ECDSA_SHA_256'
        response = client.sign(KeyId=key_ref, Message=message, MessageType='RAW', SigningAlgorithm=algorithm)
        signature_bytes = response.get('Signature') or b''
        public_key_obj = None
        try:
            pub_response = client.get_public_key(KeyId=key_ref)
            public_key_obj = serialization.load_der_public_key(pub_response.get('PublicKey'))
        except Exception:
            public_key_obj = self._load_portfolio_public_key_from_sources(
                pem_b64=str(policy.get('aws_public_key_pem_b64') or '').strip(),
                pem_path=str(policy.get('aws_public_key_pem_path') or '').strip(),
                error_prefix='AWS KMS public key',
            )
        if public_key_obj is None:
            raise RuntimeError('aws_kms_public_key_unavailable')
        scheme = 'ecdsa-sha256'
        if isinstance(public_key_obj, ed25519.Ed25519PublicKey):
            scheme = 'ed25519'
        return self._crypto_signature_result(
            signature_bytes=signature_bytes,
            signature_scheme=scheme,
            signing_input=signing_input,
            payload_hash=payload_hash,
            public_key=public_key_obj,
            provider=provider,
            key_origin='aws_kms_native',
            provider_metadata={'provider': provider, 'aws_region': region, 'aws_key_id': key_ref, 'algorithm': algorithm},
        )

    def _sign_with_gcp_kms_native(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        kms_v1 = importlib.import_module('google.cloud.kms_v1')
        credentials = None
        creds_path = str(policy.get('gcp_credentials_path') or '').strip()
        if creds_path:
            service_account = importlib.import_module('google.oauth2.service_account')
            credentials = service_account.Credentials.from_service_account_file(creds_path)
        client = kms_v1.KeyManagementServiceClient(credentials=credentials) if credentials is not None else kms_v1.KeyManagementServiceClient()
        key_name = str(policy.get('gcp_kms_key_name') or signer_key_id or '').strip()
        if not key_name:
            raise RuntimeError('gcp_kms_key_name_missing')
        message = self._json_canonical_bytes(signing_input)
        digest_bytes = hashlib.sha256(message).digest()
        digest = kms_v1.Digest(sha256=digest_bytes)
        response = client.asymmetric_sign(request={'name': key_name, 'digest': digest})
        signature_bytes = response.signature
        public_key_obj = None
        try:
            pub_response = client.get_public_key(request={'name': key_name})
            public_key_obj = load_pem_public_key(pub_response.pem.encode('utf-8'))
        except Exception:
            public_key_obj = self._load_portfolio_public_key_from_sources(
                pem_b64=str(policy.get('gcp_public_key_pem_b64') or '').strip(),
                pem_path=str(policy.get('gcp_public_key_pem_path') or '').strip(),
                error_prefix='GCP KMS public key',
            )
        if public_key_obj is None:
            raise RuntimeError('gcp_kms_public_key_unavailable')
        scheme = 'ecdsa-sha256'
        if isinstance(public_key_obj, ed25519.Ed25519PublicKey):
            scheme = 'ed25519'
        return self._crypto_signature_result(
            signature_bytes=signature_bytes,
            signature_scheme=scheme,
            signing_input=signing_input,
            payload_hash=payload_hash,
            public_key=public_key_obj,
            provider=provider,
            key_origin='gcp_kms_native',
            provider_metadata={'provider': provider, 'gcp_key_name': key_name},
        )

    def _sign_with_azure_key_vault_native(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        identity_mod = importlib.import_module('azure.identity')
        crypto_mod = importlib.import_module('azure.keyvault.keys.crypto')
        credential = getattr(identity_mod, 'DefaultAzureCredential')()
        key_id = str(policy.get('azure_key_id') or signer_key_id or '').strip()
        if not key_id:
            raise RuntimeError('azure_key_id_missing')
        message = self._json_canonical_bytes(signing_input)
        digest_bytes = hashlib.sha256(message).digest()
        crypto_client = crypto_mod.CryptographyClient(key_id, credential)
        algorithm = getattr(getattr(crypto_mod, 'SignatureAlgorithm'), str(policy.get('azure_signature_algorithm_enum') or 'es256'), None)
        if algorithm is None:
            algorithm = getattr(crypto_mod.SignatureAlgorithm, 'es256')
        sign_result = crypto_client.sign(algorithm, digest_bytes)
        signature_bytes = sign_result.signature
        public_key_obj = self._load_portfolio_public_key_from_sources(
            pem_b64=str(policy.get('azure_public_key_pem_b64') or '').strip(),
            pem_path=str(policy.get('azure_public_key_pem_path') or '').strip(),
            error_prefix='Azure Key Vault public key',
        )
        if public_key_obj is None:
            raise RuntimeError('azure_public_key_unavailable')
        scheme = 'ecdsa-sha256'
        if isinstance(public_key_obj, ed25519.Ed25519PublicKey):
            scheme = 'ed25519'
        return self._crypto_signature_result(
            signature_bytes=signature_bytes,
            signature_scheme=scheme,
            signing_input=signing_input,
            payload_hash=payload_hash,
            public_key=public_key_obj,
            provider=provider,
            key_origin='azure_key_vault_native',
            provider_metadata={'provider': provider, 'azure_key_id': key_id, 'algorithm': str(algorithm)},
        )

    def _sign_with_pkcs11_native(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        pkcs11 = importlib.import_module('pkcs11')
        module_path = str(policy.get('pkcs11_module_path') or '').strip()
        if not module_path:
            raise RuntimeError('pkcs11_module_path_missing')
        lib = pkcs11.lib(module_path)
        token_label = str(policy.get('pkcs11_token_label') or '').strip() or None
        pin = str(policy.get('pkcs11_pin') or '').strip() or None
        pin_env_var = str(policy.get('pkcs11_pin_env_var') or '').strip()
        if pin is None and pin_env_var:
            pin = str(os.getenv(pin_env_var) or '').strip() or None
        key_label = str(policy.get('pkcs11_key_label') or signer_key_id or '').strip() or None
        if token_label:
            token = lib.get_token(token_label=token_label)
        else:
            slot_id = policy.get('pkcs11_slot_id')
            token = lib.get_token(slot=int(slot_id)) if slot_id is not None else lib.get_token()
        message = self._json_canonical_bytes(signing_input)
        mechanism_name = str(policy.get('pkcs11_mechanism') or 'EDDSA').strip().upper() or 'EDDSA'
        mechanism = getattr(pkcs11.Mechanism, mechanism_name, None)
        if mechanism is None:
            raise RuntimeError(f'pkcs11_mechanism_unsupported:{mechanism_name}')
        with token.open(user_pin=pin) as session:
            private_key = session.get_key(label=key_label, object_class=pkcs11.ObjectClass.PRIVATE_KEY)
            if mechanism_name == 'ECDSA':
                signature_bytes = bytes(private_key.sign(hashlib.sha256(message).digest(), mechanism=mechanism))
                scheme = 'ecdsa-sha256'
            else:
                signature_bytes = bytes(private_key.sign(message, mechanism=mechanism))
                scheme = 'ed25519'
        public_key_obj = self._load_portfolio_public_key_from_sources(
            pem_b64=str(policy.get('pkcs11_public_key_pem_b64') or '').strip(),
            pem_path=str(policy.get('pkcs11_public_key_pem_path') or '').strip(),
            error_prefix='PKCS#11 public key',
        )
        if public_key_obj is None:
            raise RuntimeError('pkcs11_public_key_unavailable')
        if isinstance(public_key_obj, ec.EllipticCurvePublicKey):
            scheme = 'ecdsa-sha256'
        return self._crypto_signature_result(
            signature_bytes=signature_bytes,
            signature_scheme=scheme,
            signing_input=signing_input,
            payload_hash=payload_hash,
            public_key=public_key_obj,
            provider=provider,
            key_origin='pkcs11_native',
            provider_metadata={'provider': provider, 'pkcs11_module_path': module_path, 'pkcs11_token_label': token_label, 'pkcs11_key_label': key_label, 'mechanism': mechanism_name},
        )

    def _sign_with_native_external_provider(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if provider == 'aws-kms-ecdsa-p256':
            return self._sign_with_aws_kms_native(provider=provider, signer_key_id=signer_key_id, signing_input=signing_input, payload_hash=payload_hash, signing_policy=signing_policy)
        if provider == 'gcp-kms-ecdsa-p256':
            return self._sign_with_gcp_kms_native(provider=provider, signer_key_id=signer_key_id, signing_input=signing_input, payload_hash=payload_hash, signing_policy=signing_policy)
        if provider == 'azure-kv-ecdsa-p256':
            return self._sign_with_azure_key_vault_native(provider=provider, signer_key_id=signer_key_id, signing_input=signing_input, payload_hash=payload_hash, signing_policy=signing_policy)
        if provider in {'pkcs11-ed25519', 'pkcs11-ecdsa-p256'}:
            return self._sign_with_pkcs11_native(provider=provider, signer_key_id=signer_key_id, signing_input=signing_input, payload_hash=payload_hash, signing_policy=signing_policy)
        raise RuntimeError(f'unsupported_native_signing_provider:{provider}')

    @staticmethod
    def _ensure_parent_dir(pathlike: str | Path) -> Path:
        path = Path(pathlike)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _filesystem_path(pathlike: str | Path) -> str:
        path = Path(pathlike)
        raw = str(path)

        if os.name != 'nt':
            return raw

        try:
            normalized = str(path.resolve(strict=False))
        except Exception:
            normalized = os.path.abspath(raw)

        if normalized.startswith('\\\\?\\'):
            return normalized

        # Solo activamos prefijo extendido cuando hace falta de verdad.
        if len(normalized) < 240:
            return normalized

        if normalized.startswith('\\\\'):
            return '\\\\?\\UNC\\' + normalized.lstrip('\\')

        return '\\\\?\\' + normalized

    @classmethod
    def _path_exists(cls, pathlike: str | Path) -> bool:
        return os.path.exists(cls._filesystem_path(pathlike))

    @classmethod
    def _path_is_file(cls, pathlike: str | Path) -> bool:
        return os.path.isfile(cls._filesystem_path(pathlike))

    @classmethod
    def _read_file_bytes(cls, pathlike: str | Path) -> bytes:
        with open(cls._filesystem_path(pathlike), 'rb') as handle:
            return handle.read()

    @classmethod
    def _read_file_text(cls, pathlike: str | Path, *, encoding: str = 'utf-8') -> str:
        with open(cls._filesystem_path(pathlike), 'r', encoding=encoding) as handle:
            return handle.read()

    @classmethod
    def _write_file_if_absent(cls, pathlike: str | Path, data: bytes) -> Path:
        path = Path(pathlike)
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        target = cls._filesystem_path(path)

        fd = os.open(target, flags, 0o644)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
        except Exception:
            try:
                os.unlink(target)
            except OSError:
                pass
            raise
        return path

    @staticmethod
    def _redact_large_blob(mapping: dict[str, Any] | None, *keys: str) -> dict[str, Any]:
        result = dict(mapping or {})
        for key in keys:
            if key in result:
                result.pop(key, None)
        return result

    @staticmethod
    def _custody_anchor_receipt_hash(receipt: dict[str, Any] | None) -> str:
        item = dict(receipt or {})
        return OpenClawRecoverySchedulerService._stable_digest({
            'anchor_id': item.get('anchor_id'),
            'sequence': int(item.get('sequence') or 0),
            'chain_head_hash': item.get('chain_head_hash'),
            'manifest_hash': item.get('manifest_hash'),
            'control_plane_id': item.get('control_plane_id'),
            'anchor_role': item.get('anchor_role'),
            'quorum_group_key': item.get('quorum_group_key'),
            'payload_hash': ((item.get('integrity') or {}).get('payload_hash')),
            'previous_anchor_hash': item.get('previous_anchor_hash') or '',
        })

    @staticmethod
    def _canonical_json_bytes(payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')

    @staticmethod
    def _s3_uri(bucket: str, key: str) -> str:
        return f's3://{str(bucket or "").strip()}/{str(key or "").lstrip("/")}'

    @staticmethod
    def _parse_s3_uri(uri: str) -> tuple[str, str] | None:
        text = str(uri or '').strip()
        if not text.startswith('s3://'):
            return None
        without_scheme = text[5:]
        if '/' not in without_scheme:
            return without_scheme, ''
        bucket, key = without_scheme.split('/', 1)
        return bucket, key

    @staticmethod
    def _azblob_uri(container: str, blob_name: str) -> str:
        return f'azblob://{str(container or "").strip()}/{str(blob_name or "").lstrip("/")}'

    @staticmethod
    def _parse_azblob_uri(uri: str) -> tuple[str, str] | None:
        text = str(uri or '').strip()
        if not text.startswith('azblob://'):
            return None
        without_scheme = text[9:]
        if '/' not in without_scheme:
            return without_scheme, ''
        container, blob_name = without_scheme.split('/', 1)
        return container, blob_name

    @staticmethod
    def _gs_uri(bucket: str, key: str) -> str:
        return f'gs://{str(bucket or "").strip()}/{str(key or "").lstrip("/")}'

    @staticmethod
    def _parse_gs_uri(uri: str) -> tuple[str, str] | None:
        text = str(uri or '').strip()
        if not text.startswith('gs://'):
            return None
        without_scheme = text[5:]
        if '/' not in without_scheme:
            return without_scheme, ''
        bucket, key = without_scheme.split('/', 1)
        return bucket, key

    @staticmethod
    def _azure_blob_name_for_artifact(*, policy: dict[str, Any], scope: dict[str, Any], portfolio_id: str, package_id: str, filename: str) -> str:
        parts = [
            str(policy.get('azure_blob_prefix') or '').strip().strip('/'),
            str(policy.get('archive_namespace') or 'portfolio-evidence').strip().strip('/'),
            str(scope.get('tenant_id') or 'global').strip(),
            str(scope.get('workspace_id') or 'default').strip(),
            str(scope.get('environment') or 'default').strip(),
            str(portfolio_id or 'portfolio').strip(),
            str(package_id or 'package').strip(),
            str(filename or f'{package_id}.zip').strip(),
        ]
        return '/'.join([part for part in parts if part])

    @staticmethod
    def _gcs_key_for_artifact(*, policy: dict[str, Any], scope: dict[str, Any], portfolio_id: str, package_id: str, filename: str) -> str:
        parts = [
            str(policy.get('gcs_prefix') or '').strip().strip('/'),
            str(policy.get('archive_namespace') or 'portfolio-evidence').strip().strip('/'),
            str(scope.get('tenant_id') or 'global').strip(),
            str(scope.get('workspace_id') or 'default').strip(),
            str(scope.get('environment') or 'default').strip(),
            str(portfolio_id or 'portfolio').strip(),
            str(package_id or 'package').strip(),
            str(filename or f'{package_id}.zip').strip(),
        ]
        return '/'.join([part for part in parts if part])

    @staticmethod
    def _aws_s3_key_for_artifact(*, policy: dict[str, Any], scope: dict[str, Any], portfolio_id: str, package_id: str, filename: str) -> str:
        parts = [
            str(policy.get('aws_s3_prefix') or '').strip().strip('/'),
            str(policy.get('archive_namespace') or 'portfolio-evidence').strip().strip('/'),
            str(scope.get('tenant_id') or 'global').strip(),
            str(scope.get('workspace_id') or 'default').strip(),
            str(scope.get('environment') or 'default').strip(),
            str(portfolio_id or 'portfolio').strip(),
            str(package_id or 'package').strip(),
            str(filename or f'{package_id}.zip').strip(),
        ]
        return '/'.join([part for part in parts if part])

    def _read_s3_object_bytes(self, *, bucket: str, key: str, escrow_policy: dict[str, Any] | None = None) -> bytes:
        client = self._aws_s3_client_for_policy(escrow_policy)
        response = client.get_object(Bucket=bucket, Key=key)
        body = response.get('Body')
        if hasattr(body, 'read'):
            return body.read()
        if isinstance(body, (bytes, bytearray)):
            return bytes(body)
        raise RuntimeError('s3_body_unreadable')

    def list_release_train_jobs(self, gw, *, limit: int = 100, portfolio_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        payload = self._list_jobs_by_family(
            gw,
            matcher=lambda item: self._is_release_train_job(item, portfolio_id=portfolio_id),
            limit=limit,
            enabled=None,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(limit, 50),
        )
        return {'ok': True, 'items': payload['items'], 'summary': {**payload['summary'], 'portfolio_id': portfolio_id}}

    def _run_single_release_train_job(self, gw, *, item: dict[str, Any], actor: str) -> dict[str, Any]:
        definition = dict((item or {}).get('workflow_definition') or {})
        portfolio_id = str(definition.get('portfolio_id') or '')
        event_id = str(definition.get('event_id') or '')
        bundle_id = str(definition.get('bundle_id') or '')
        wave_no = int(definition.get('wave_no') or 1)
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'), read_kind='action_context')
        if not detail.get('ok'):
            gw.audit.update_job_schedule(str(item.get('job_id') or ''), enabled=False, last_error=str(detail.get('error') or 'portfolio_not_found'), run_count=int(item.get('run_count') or 0) + 1, last_run_at=time.time(), tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
            return {'ok': False, 'job_id': item.get('job_id'), 'portfolio_id': portfolio_id, 'error': detail.get('error')}
        sim_items = {str(event.get('event_id') or ''): dict(event) for event in list((detail.get('simulation') or {}).get('items') or [])}
        sim_event = sim_items.get(event_id)
        drift_payload = self.detect_runtime_alert_governance_portfolio_drift(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            tenant_id=item.get('tenant_id'),
            workspace_id=item.get('workspace_id'),
            environment=item.get('environment'),
            persist_metadata=True,
        )
        drift_report = dict(drift_payload.get('drift') or {})
        drift_items = {str(entry.get('event_id') or ''): dict(entry) for entry in list(drift_report.get('items') or [])}
        event_drift = drift_items.get(event_id)
        if str(drift_report.get('overall_status') or '') == 'no_attestation' and bool(drift_report.get('block_execution')):
            self._complete_job_execution(gw, item=item, last_error='portfolio_execution_attestation_missing', next_run_at_override=None, enabled=False)
            return {'ok': False, 'job_id': item.get('job_id'), 'portfolio_id': portfolio_id, 'event_id': event_id, 'bundle_id': bundle_id, 'wave_no': wave_no, 'error': 'portfolio_execution_attestation_missing', 'drift': drift_report}
        if event_drift is not None and int(event_drift.get('blocking_count') or 0) > 0:
            release = dict(detail.get('release') or {})
            metadata = dict(release.get('metadata') or {})
            portfolio = dict(metadata.get('portfolio') or {})
            events = [dict(ev) for ev in list(portfolio.get('train_calendar') or [])]
            for idx, event in enumerate(events):
                if str(event.get('event_id') or '') != event_id:
                    continue
                updated = dict(event)
                updated['status'] = 'drift_blocked'
                updated['last_run_at'] = time.time()
                updated['run_count'] = int(updated.get('run_count') or 0) + 1
                updated['result'] = {'ok': False, 'error': 'portfolio_execution_drift_detected', 'drift': event_drift}
                events[idx] = updated
                break
            portfolio['train_calendar'] = events
            metadata['portfolio'] = portfolio
            gw.audit.update_release_bundle(portfolio_id, metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
            self._complete_job_execution(gw, item=item, last_error='portfolio_execution_drift_detected', next_run_at_override=None, enabled=False)
            return {'ok': False, 'job_id': item.get('job_id'), 'portfolio_id': portfolio_id, 'event_id': event_id, 'bundle_id': bundle_id, 'wave_no': wave_no, 'error': 'portfolio_execution_drift_detected', 'drift': drift_report, 'event_drift': event_drift}
        if sim_event is not None and str(sim_event.get('simulation_status') or '') == 'blocked':
            self._complete_job_execution(gw, item=item, last_error='event_blocked_by_simulation', next_run_at_override=None, enabled=False)
            return {'ok': False, 'job_id': item.get('job_id'), 'portfolio_id': portfolio_id, 'event_id': event_id, 'bundle_id': bundle_id, 'wave_no': wave_no, 'error': 'event_blocked_by_simulation', 'simulation_event': sim_event}
        result = self.run_runtime_alert_governance_bundle_wave(gw, bundle_id=bundle_id, wave_no=wave_no, actor=actor, reason=str(definition.get('reason') or ''), tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        release = dict(detail.get('release') or {})
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        events = [dict(ev) for ev in list(portfolio.get('train_calendar') or [])]
        for idx, event in enumerate(events):
            if str(event.get('event_id') or '') == event_id:
                updated = dict(event)
                updated['last_run_at'] = time.time()
                updated['run_count'] = int(updated.get('run_count') or 0) + 1
                updated['result'] = {'ok': bool(result.get('ok')), 'rollout_status': ((result.get('summary') or {}).get('rollout_status')), 'errors': ((result.get('wave_execution') or {}).get('errors'))}
                updated['status'] = 'completed' if result.get('ok') else 'error'
                events[idx] = updated
                break
        portfolio['train_calendar'] = events
        metadata['portfolio'] = portfolio
        gw.audit.update_release_bundle(portfolio_id, metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        self._complete_job_execution(gw, item=item, last_error='' if result.get('ok') else str(result.get('error') or 'bundle_wave_failed'), next_run_at_override=None, enabled=False)
        return {'ok': bool(result.get('ok')), 'job_id': item.get('job_id'), 'portfolio_id': portfolio_id, 'event_id': event_id, 'bundle_id': bundle_id, 'wave_no': wave_no, 'result': result}

    def run_due_release_train_jobs(self, gw, *, actor: str, limit: int = 20, portfolio_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        payload = self._run_due_jobs_by_family(
            gw,
            matcher=lambda item: self._is_release_train_job(item, portfolio_id=portfolio_id),
            runner=self._run_single_release_train_job,
            actor=actor,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(limit, 50),
        )
        return {'ok': True, 'items': payload['items'], 'summary': {**payload['summary'], 'portfolio_id': portfolio_id}}

