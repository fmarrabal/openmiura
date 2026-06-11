"""scheduler._portfolio_a_mixin

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


class _OpenClawRecoverySchedulerServicePortfolioAMixin:
    """Sub-mixin: portfolio a."""

    @classmethod
    def _is_alert_governance_portfolio_release(cls, release: dict[str, Any] | None) -> bool:
        payload = dict(release or {})
        if str(payload.get('kind') or '').strip() != 'policy_portfolio':
            return False
        metadata = dict(payload.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        return str(portfolio.get('kind') or '').strip() == 'openclaw_alert_governance_portfolio'

    @staticmethod
    def _portfolio_event_id(portfolio_id: str, bundle_id: str, wave_no: int, order_no: int) -> str:
        seed = f'{portfolio_id}:{bundle_id}:{wave_no}:{order_no}'
        return hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]

    @staticmethod
    def _portfolio_approval_workflow_id(portfolio_id: str) -> str:
        return f'openclaw-governance-portfolio:{str(portfolio_id or "").strip()}'

    @staticmethod
    def _portfolio_deviation_approval_workflow_id(portfolio_id: str) -> str:
        return f'openclaw-governance-portfolio-deviation:{str(portfolio_id or "").strip()}'

    def _load_portfolio_private_signing_key(
        self,
        *,
        key_id: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> tuple[ed25519.Ed25519PrivateKey, dict[str, Any]]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        provider = str(policy.get('provider') or 'local-ed25519').strip() or 'local-ed25519'
        # Type hint left as a PEP 484 comment to avoid a secret-scanner
        # false positive on `private_key: <KeyType> | None = None`.
        private_key = None  # type: ed25519.Ed25519PrivateKey | None
        origin = 'derived_seed'
        dev_default_seed = False
        provider_metadata: dict[str, Any] = {'provider': provider}

        def _load_from_sources(env_b64: str, env_path: str, *, error_prefix: str) -> ed25519.Ed25519PrivateKey | None:
            if env_b64:
                return self._load_ed25519_private_key_from_pem(base64.b64decode(env_b64.encode('ascii')), error_prefix=error_prefix)
            if env_path:
                return self._load_ed25519_private_key_from_pem(Path(env_path).read_bytes(), error_prefix=error_prefix)
            return None

        if provider in {'kms-ed25519-simulated', 'kms-ed25519-file'}:
            private_key = _load_from_sources(
                str(policy.get('kms_private_key_pem_b64') or os.getenv('OPENMIURA_EVIDENCE_KMS_PRIVATE_KEY_PEM_B64') or '').strip(),
                str(policy.get('kms_private_key_pem_path') or '').strip(),
                error_prefix='KMS signing key',
            )
            if private_key is not None:
                origin = 'kms_file' if provider == 'kms-ed25519-file' else 'kms_simulated'
                provider_metadata['kms_key_ref'] = str(policy.get('kms_key_ref') or key_id or '').strip() or None
        elif provider in {'hsm-ed25519-simulated', 'hsm-ed25519-file'}:
            private_key = _load_from_sources(
                str(policy.get('hsm_private_key_pem_b64') or os.getenv('OPENMIURA_EVIDENCE_HSM_PRIVATE_KEY_PEM_B64') or '').strip(),
                str(policy.get('hsm_private_key_pem_path') or '').strip(),
                error_prefix='HSM signing key',
            )
            if private_key is not None:
                origin = 'hsm_file' if provider == 'hsm-ed25519-file' else 'hsm_simulated'
                provider_metadata['hsm_slot_id'] = str(policy.get('hsm_slot_id') or key_id or '').strip() or None
        if private_key is None and provider in {'kms-ed25519-simulated', 'hsm-ed25519-simulated', 'kms-ed25519-file', 'hsm-ed25519-file'} and not bool(policy.get('allow_local_fallback', False)):
            raise RuntimeError(f'external_signing_provider_unavailable:{provider}')
        if private_key is None:
            env_b64 = str(os.getenv('OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_B64') or '').strip()
            env_path = str(os.getenv('OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_PATH') or '').strip()
            if env_b64:
                private_key = self._load_ed25519_private_key_from_pem(base64.b64decode(env_b64.encode('ascii')), error_prefix='OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_B64')
                origin = 'configured_pem_b64'
            elif env_path:
                private_key = self._load_ed25519_private_key_from_pem(Path(env_path).read_bytes(), error_prefix='OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_PATH')
                origin = 'configured_pem_path'
            else:
                configured_seed = str(os.getenv('OPENMIURA_EVIDENCE_SIGNING_SEED') or '').strip()
                # No real key, PEM, KMS/HSM provider, or custom seed
                # configured → we fall back to the built-in PUBLIC dev
                # seed. Flag it so the signature can be marked
                # non-authoritative below.
                dev_default_seed = not configured_seed
                seed_material = (configured_seed or 'openmiura-portfolio-signing-v2-dev-seed').encode('utf-8')
                derived = hashlib.sha256(seed_material + b':' + str(key_id or 'openmiura-local').encode('utf-8')).digest()
                private_key = ed25519.Ed25519PrivateKey.from_private_bytes(derived)
                origin = 'derived_seed'
                provider = 'local-ed25519'
                provider_metadata['provider'] = provider
        public_key = private_key.public_key()
        info: dict[str, Any] = {
            'algorithm': 'ed25519',
            'origin': origin,
            'provider': provider,
            'provider_metadata': provider_metadata,
            'public_key_pem': self._ed25519_public_key_pem(public_key),
            'public_key_fingerprint': self._ed25519_public_key_fingerprint(public_key),
        }
        # Security/honesty: the built-in fallback seed is a PUBLIC
        # literal — anyone with the source can reproduce this private
        # key and forge a "signature". When it is in use (no real key,
        # PEM, KMS/HSM provider, or custom OPENMIURA_EVIDENCE_SIGNING_SEED)
        # and the operator has NOT explicitly opted in via
        # OPENMIURA_ALLOW_DEV_SIGNING_KEY, mark the signature as
        # non-authoritative so an auditor reading the evidence pack is
        # never misled into trusting a dev-seed signature. This is
        # additive metadata: the signature itself is unchanged.
        _dev_opt_in = str(os.getenv('OPENMIURA_ALLOW_DEV_SIGNING_KEY') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
        if dev_default_seed and not _dev_opt_in:
            info['dev_signing_key'] = True
            info['signing_warning'] = (
                'Signed with the built-in development seed, a public, '
                'source-reproducible key. This signature is NOT '
                'authoritative and must not be relied upon. Configure a '
                'real signing key (OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_'
                'PEM_B64 / _PEM_PATH, a KMS/HSM provider, or '
                'OPENMIURA_EVIDENCE_SIGNING_SEED) for production evidence.'
            )
        return private_key, info

    def _run_portfolio_external_signing_command(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        command = [str(item).strip() for item in list(policy.get('sign_command') or []) if str(item).strip()]
        if not command:
            raise RuntimeError(f'external_signing_command_missing:{provider}')
        message = self._json_canonical_bytes(signing_input)
        request_payload = {
            'operation': 'sign',
            'provider': provider,
            'key_id': str(signer_key_id or '').strip(),
            'signing_input': signing_input,
            'message_b64': base64.b64encode(message).decode('ascii'),
            'message_sha256': hashlib.sha256(message).hexdigest(),
        }
        env = os.environ.copy()
        env.update({str(key): str(value) for key, value in dict(policy.get('command_env') or {}).items()})
        proc = subprocess.run(
            command,
            input=self._json_canonical_bytes(request_payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=float(policy.get('command_timeout_s') or 10.0),
            env=env,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode('utf-8', errors='replace').strip()
            raise RuntimeError(f'external_signing_command_failed:{provider}:{stderr or proc.returncode}')
        try:
            response = json.loads(proc.stdout.decode('utf-8'))
        except Exception as exc:
            raise RuntimeError(f'external_signing_command_invalid_json:{provider}') from exc
        signature_b64 = str(response.get('signature') or '').strip()
        public_key_pem = str(response.get('public_key_pem') or '').strip()
        if not public_key_pem and str(response.get('public_key_pem_b64') or '').strip():
            public_key_pem = base64.b64decode(str(response.get('public_key_pem_b64')).encode('ascii')).decode('utf-8')
        if not signature_b64 or not public_key_pem:
            raise RuntimeError(f'external_signing_command_incomplete:{provider}')
        loaded_public = load_pem_public_key(public_key_pem.encode('utf-8'))
        if not isinstance(loaded_public, ed25519.Ed25519PublicKey):
            raise TypeError('unsupported_public_key_type')
        loaded_public.verify(base64.b64decode(signature_b64.encode('ascii')), message)
        return {
            'signature': signature_b64,
            'signature_scheme': 'ed25519',
            'signature_input': dict(signing_input),
            'signature_input_hash': hashlib.sha256(message).hexdigest(),
            'public_key': {
                'algorithm': 'ed25519',
                'origin': 'external_command',
                'provider': provider,
                'provider_metadata': {
                    'provider': provider,
                    'command': command,
                    **dict(response.get('provider_metadata') or {}),
                },
                'public_key_pem': public_key_pem,
                'public_key_fingerprint': self._ed25519_public_key_fingerprint(loaded_public),
            },
            'signer_provider': provider,
            'key_origin': 'external_command',
        }

    def _load_portfolio_public_key_from_sources(
        self,
        *,
        pem_b64: str = '',
        pem_path: str = '',
        error_prefix: str = 'public key',
    ) -> Any | None:
        raw_pem = b''
        if str(pem_b64 or '').strip():
            raw_pem = base64.b64decode(str(pem_b64).encode('ascii'))
        elif str(pem_path or '').strip():
            raw_pem = Path(str(pem_path)).read_bytes()
        if not raw_pem:
            return None
        loaded = load_pem_public_key(raw_pem)
        return loaded

    def _sign_portfolio_payload_crypto_v2(
        self,
        *,
        report_type: str,
        scope: dict[str, Any],
        payload: dict[str, Any],
        signer_key_id: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        provider = str(normalized_policy.get('provider') or 'local-ed25519').strip() or 'local-ed25519'
        payload_hash = self._stable_digest(payload)
        signing_input = {
            'report_type': str(report_type or '').strip(),
            'scope': dict(scope or {}),
            'payload_hash': payload_hash,
            'signer_key_id': str(signer_key_id or '').strip(),
        }
        native_providers = {'aws-kms-ecdsa-p256', 'gcp-kms-ecdsa-p256', 'azure-kv-ecdsa-p256', 'pkcs11-ed25519', 'pkcs11-ecdsa-p256'}
        if provider in native_providers:
            try:
                return self._sign_with_native_external_provider(
                    provider=provider,
                    signer_key_id=signer_key_id,
                    signing_input=signing_input,
                    payload_hash=payload_hash,
                    signing_policy=normalized_policy,
                )
            except Exception:
                if not bool(normalized_policy.get('allow_local_fallback', False)):
                    raise
        if provider in {'kms-ed25519-command', 'hsm-ed25519-command'}:
            crypto = self._run_portfolio_external_signing_command(
                provider=provider,
                signer_key_id=signer_key_id,
                signing_input=signing_input,
                signing_policy=normalized_policy,
            )
            crypto['payload_hash'] = payload_hash
            return crypto
        private_key, key_info = self._load_portfolio_private_signing_key(key_id=signer_key_id, signing_policy=normalized_policy)
        message = self._json_canonical_bytes(signing_input)
        signature_bytes = private_key.sign(message)
        return {
            'payload_hash': payload_hash,
            'signature': base64.b64encode(signature_bytes).decode('ascii'),
            'signature_scheme': 'ed25519',
            'signature_input': signing_input,
            'signature_input_hash': hashlib.sha256(message).hexdigest(),
            'public_key': key_info,
            'signer_provider': key_info.get('provider'),
            'key_origin': key_info.get('origin'),
        }

    def _verify_portfolio_crypto_signature(
        self,
        *,
        report_type: str,
        scope: dict[str, Any],
        payload: dict[str, Any],
        integrity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved = dict(integrity or {})
        payload_hash = self._stable_digest(payload)
        public_key_payload = dict(resolved.get('public_key') or {})
        public_key_pem = str(public_key_payload.get('public_key_pem') or '').strip()
        signature_b64 = str(resolved.get('signature') or '').strip()
        signer_key_id = str(resolved.get('signer_key_id') or '').strip()
        signed = bool(resolved.get('signed'))
        scheme = str(resolved.get('signature_scheme') or '').strip().lower()
        signing_input = dict(resolved.get('signature_input') or {})
        expected_input = {
            'report_type': str(report_type or '').strip(),
            'scope': dict(scope or {}),
            'payload_hash': payload_hash,
            'signer_key_id': signer_key_id,
        }
        payload_hash_valid = str(resolved.get('payload_hash') or '').strip() == payload_hash
        input_valid = signing_input == expected_input
        message = self._json_canonical_bytes(expected_input)
        signature_valid = False
        public_key_valid = False
        public_key_fingerprint = None
        error = None
        if not signed:
            signature_valid = not signature_b64
        elif not public_key_pem or not signature_b64:
            error = 'missing_crypto_material'
        else:
            try:
                loaded_public = load_pem_public_key(public_key_pem.encode('utf-8'))
                signature_bytes = base64.b64decode(signature_b64.encode('ascii'))
                if scheme == 'ed25519':
                    if not isinstance(loaded_public, ed25519.Ed25519PublicKey):
                        raise TypeError('unsupported_public_key_type')
                    public_key_valid = True
                    public_key_fingerprint = self._public_key_fingerprint(loaded_public)
                    loaded_public.verify(signature_bytes, message)
                    signature_valid = True
                elif scheme in {'ecdsa-sha256', 'ecdsa-p256-sha256', 'es256'}:
                    if not isinstance(loaded_public, ec.EllipticCurvePublicKey):
                        raise TypeError('unsupported_public_key_type')
                    public_key_valid = True
                    public_key_fingerprint = self._public_key_fingerprint(loaded_public)
                    loaded_public.verify(signature_bytes, message, ec.ECDSA(hashes.SHA256()))
                    signature_valid = True
                else:
                    error = f'unsupported_signature_scheme:{scheme or "unknown"}'
            except (ValueError, TypeError, InvalidSignature) as exc:
                error = str(exc) or exc.__class__.__name__
                signature_valid = False
        return {
            'report_type': str(report_type or '').strip(),
            'signed': signed,
            'signer_key_id': signer_key_id or None,
            'scheme': scheme or None,
            'signer_provider': public_key_payload.get('provider') or resolved.get('signer_provider'),
            'key_origin': public_key_payload.get('origin') or resolved.get('key_origin'),
            'payload_hash_valid': payload_hash_valid,
            'signature_valid': signature_valid,
            'public_key_valid': public_key_valid,
            'public_key_fingerprint': public_key_fingerprint,
            'signature_input_valid': input_valid,
            'expected_payload_hash': payload_hash,
            'error': error,
            'valid': payload_hash_valid and input_valid and signature_valid,
        }

    def _validate_portfolio_signing_provider_live(
        self,
        *,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        provider = str(policy.get('provider') or 'local-ed25519').strip() or 'local-ed25519'
        base: dict[str, Any] = {
            'provider': provider,
            'key_id': str(policy.get('key_id') or '').strip() or None,
            'validated_at': time.time(),
            'live': provider in {'aws-kms-ecdsa-p256', 'gcp-kms-ecdsa-p256', 'azure-kv-ecdsa-p256', 'pkcs11-ed25519', 'pkcs11-ecdsa-p256'},
        }
        try:
            if provider == 'aws-kms-ecdsa-p256':
                boto3 = importlib.import_module('boto3')
                session_kwargs = {}
                if policy.get('aws_profile'):
                    session_kwargs['profile_name'] = str(policy.get('aws_profile'))
                session = boto3.Session(**session_kwargs)
                client_kwargs = {}
                if policy.get('aws_region'):
                    client_kwargs['region_name'] = str(policy.get('aws_region'))
                if policy.get('aws_endpoint_url'):
                    client_kwargs['endpoint_url'] = str(policy.get('aws_endpoint_url'))
                client = session.client('kms', **client_kwargs)
                key_id = str(policy.get('aws_kms_key_id') or policy.get('kms_key_ref') or policy.get('key_id') or '').strip()
                if not key_id:
                    raise RuntimeError('aws_kms_key_id_missing')
                describe = client.describe_key(KeyId=key_id)
                public_key = client.get_public_key(KeyId=key_id)
                signing_algorithms = list(public_key.get('SigningAlgorithms') or [])
                return {
                    **base,
                    'valid': True,
                    'provider_live': True,
                    'key_origin': 'aws_kms_native',
                    'key_spec': ((describe.get('KeyMetadata') or {}).get('CustomerMasterKeySpec')) or ((describe.get('KeyMetadata') or {}).get('KeySpec')),
                    'key_state': ((describe.get('KeyMetadata') or {}).get('KeyState')),
                    'signing_algorithms': signing_algorithms,
                    'public_key_pem_available': bool(public_key.get('PublicKey')),
                }
            if provider == 'gcp-kms-ecdsa-p256':
                kms_v1 = importlib.import_module('google.cloud.kms_v1')
                credentials_path = str(policy.get('gcp_credentials_path') or '').strip()
                if credentials_path and not os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
                    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
                client = kms_v1.KeyManagementServiceClient()
                key_name = str(policy.get('gcp_kms_key_name') or policy.get('key_id') or '').strip()
                if not key_name:
                    raise RuntimeError('gcp_kms_key_name_missing')
                public_key = client.get_public_key(request={'name': key_name})
                algorithm = getattr(public_key, 'algorithm', None)
                pem = getattr(public_key, 'pem', '')
                return {
                    **base,
                    'valid': True,
                    'provider_live': True,
                    'key_origin': 'gcp_kms_native',
                    'key_name': key_name,
                    'algorithm': str(algorithm) if algorithm is not None else None,
                    'public_key_pem_available': bool(pem),
                }
            if provider == 'azure-kv-ecdsa-p256':
                key_client_mod = importlib.import_module('azure.keyvault.keys')
                identity_mod = importlib.import_module('azure.identity')
                vault_url = str(policy.get('azure_vault_url') or '').strip()
                key_id = str(policy.get('azure_key_id') or policy.get('key_id') or '').strip()
                if not vault_url:
                    raise RuntimeError('azure_vault_url_missing')
                if not key_id:
                    raise RuntimeError('azure_key_id_missing')
                credential = identity_mod.DefaultAzureCredential()
                key_client = key_client_mod.KeyClient(vault_url=vault_url, credential=credential)
                key_name = key_id.rstrip('/').split('/')[-1]
                key = key_client.get_key(key_name)
                key_type = getattr(key, 'key_type', None)
                return {
                    **base,
                    'valid': True,
                    'provider_live': True,
                    'key_origin': 'azure_key_vault_native',
                    'key_name': key_name,
                    'key_type': str(key_type) if key_type is not None else None,
                    'public_key_pem_available': bool(policy.get('azure_public_key_pem_b64') or policy.get('azure_public_key_pem_path') or getattr(key, 'key', None)),
                }
            if provider in {'pkcs11-ed25519', 'pkcs11-ecdsa-p256'}:
                pkcs11 = importlib.import_module('pkcs11')
                module_path = str(policy.get('pkcs11_module_path') or '').strip()
                if not module_path:
                    raise RuntimeError('pkcs11_module_path_missing')
                lib = pkcs11.lib(module_path)
                token_label = str(policy.get('pkcs11_token_label') or '').strip() or None
                key_label = str(policy.get('pkcs11_key_label') or policy.get('key_id') or '').strip() or None
                pin = str(policy.get('pkcs11_pin') or '').strip() or None
                pin_env_var = str(policy.get('pkcs11_pin_env_var') or '').strip()
                if pin is None and pin_env_var:
                    pin = str(os.getenv(pin_env_var) or '').strip() or None
                if policy.get('pkcs11_slot_id') is not None:
                    token = lib.get_token(slot=int(policy.get('pkcs11_slot_id')))
                else:
                    token = lib.get_token(token_label=token_label)
                with token.open(user_pin=pin) as session:
                    private_key = session.get_key(label=key_label, object_class=pkcs11.ObjectClass.PRIVATE_KEY)
                return {
                    **base,
                    'valid': private_key is not None,
                    'provider_live': True,
                    'key_origin': 'pkcs11_native',
                    'module_path': module_path,
                    'token_label': token_label,
                    'key_label': key_label,
                }
            return {
                **base,
                'valid': True,
                'provider_live': False,
                'key_origin': 'local_or_non_live_provider',
                'reason': 'live_validation_not_required',
            }
        except Exception as exc:
            return {
                **base,
                'valid': False,
                'provider_live': bool(base.get('live')),
                'error': str(exc) or exc.__class__.__name__,
            }

    def _validate_portfolio_escrow_backend_live(
        self,
        *,
        escrow_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_escrow_policy(dict(escrow_policy or {}))
        provider = str(policy.get('provider') or 'filesystem-governed').strip() or 'filesystem-governed'
        base: dict[str, Any] = {
            'provider': provider,
            'validated_at': time.time(),
            'object_lock_enabled': bool(policy.get('object_lock_enabled')),
        }
        try:
            if provider in {'aws-s3-object-lock', 's3-object-lock'}:
                boto3 = importlib.import_module('boto3')
                bucket = str(policy.get('aws_s3_bucket') or '').strip()
                if not bucket:
                    raise RuntimeError('aws_s3_bucket_missing')
                session_kwargs = {}
                if policy.get('aws_profile'):
                    session_kwargs['profile_name'] = str(policy.get('aws_profile'))
                session = boto3.Session(**session_kwargs)
                client_kwargs = {}
                if policy.get('aws_region'):
                    client_kwargs['region_name'] = str(policy.get('aws_region'))
                if policy.get('aws_endpoint_url'):
                    client_kwargs['endpoint_url'] = str(policy.get('aws_endpoint_url'))
                client = session.client('s3', **client_kwargs)
                client.head_bucket(Bucket=bucket)
                lock = client.get_object_lock_configuration(Bucket=bucket)
                enabled = str((((lock.get('ObjectLockConfiguration') or {}).get('ObjectLockEnabled')) or '')).upper() == 'ENABLED'
                return {
                    **base,
                    'valid': enabled if bool(policy.get('require_object_lock', True)) else True,
                    'provider_live': True,
                    'bucket': bucket,
                    'prefix': str(policy.get('aws_s3_prefix') or '').strip() or None,
                    'object_lock_backend': True,
                    'object_lock_configuration': dict(lock.get('ObjectLockConfiguration') or {}),
                }
            if provider == 'azure-blob-immutable':
                service = self._azure_blob_service_client_for_policy(policy)
                container = str(policy.get('azure_blob_container') or '').strip()
                if not container:
                    raise RuntimeError('azure_blob_container_missing')
                container_client = service.get_container_client(container)
                if hasattr(container_client, 'get_container_properties'):
                    props = container_client.get_container_properties() or {}
                else:
                    props = {}
                return {
                    **base,
                    'valid': True,
                    'provider_live': True,
                    'container': container,
                    'account_url': str(policy.get('azure_blob_account_url') or '').strip() or None,
                    'object_lock_backend': True,
                    'container_properties': dict(props or {}),
                }
            if provider == 'gcs-retention-lock':
                client = self._gcs_client_for_policy(policy)
                bucket_name = str(policy.get('gcs_bucket') or '').strip()
                if not bucket_name:
                    raise RuntimeError('gcs_bucket_missing')
                bucket = client.bucket(bucket_name)
                if hasattr(bucket, 'reload'):
                    bucket.reload()
                retention_period = getattr(bucket, 'retention_period', None)
                return {
                    **base,
                    'valid': retention_period is not None or not bool(policy.get('require_object_lock', True)),
                    'provider_live': True,
                    'bucket': bucket_name,
                    'object_lock_backend': True,
                    'retention_period': retention_period,
                }
            if provider in {'filesystem-object-lock', 'object-lock-filesystem', 'filesystem-governed'}:
                root_dir = Path(str(policy.get('root_dir') or 'data/openclaw_evidence_escrow')).expanduser().resolve()
                root_dir.mkdir(parents=True, exist_ok=True)
                return {
                    **base,
                    'valid': True,
                    'provider_live': False,
                    'root_dir': root_dir.as_posix(),
                    'object_lock_backend': provider in {'filesystem-object-lock', 'object-lock-filesystem'},
                }
            return {
                **base,
                'valid': True,
                'provider_live': False,
                'reason': 'live_validation_not_implemented_for_provider',
            }
        except Exception as exc:
            return {
                **base,
                'valid': False,
                'provider_live': provider in {'aws-s3-object-lock', 's3-object-lock'},
                'error': str(exc) or exc.__class__.__name__,
            }

    def _validate_portfolio_custody_anchor_backend_live(
        self,
        *,
        custody_anchor_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_custody_anchor_policy(dict(custody_anchor_policy or {}))
        provider = str(policy.get('provider') or 'filesystem-ledger').strip() or 'filesystem-ledger'
        try:
            if provider == 'sqlite-immutable-ledger':
                sqlite_path = Path(str(policy.get('sqlite_path') or 'data/openclaw_custody_anchor/custody_anchor_ledger.sqlite3')).expanduser().resolve()
                conn = self._open_portfolio_custody_anchor_sqlite(sqlite_path)
                try:
                    row = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'custody_anchor_receipts'").fetchone()
                finally:
                    conn.close()
                return {
                    'provider': provider,
                    'validated_at': time.time(),
                    'valid': row is not None,
                    'provider_live': True,
                    'sqlite_path': sqlite_path.as_posix(),
                    'immutable_backend': True,
                }
            if provider == 'filesystem-ledger':
                root_dir = Path(str(policy.get('root_dir') or 'data/openclaw_custody_anchor')).expanduser().resolve()
                root_dir.mkdir(parents=True, exist_ok=True)
                return {
                    'provider': provider,
                    'validated_at': time.time(),
                    'valid': True,
                    'provider_live': False,
                    'root_dir': root_dir.as_posix(),
                    'immutable_backend': False,
                }
            return {
                'provider': provider,
                'validated_at': time.time(),
                'valid': False,
                'provider_live': False,
                'error': 'unsupported_custody_anchor_provider',
            }
        except Exception as exc:
            return {
                'provider': provider,
                'validated_at': time.time(),
                'valid': False,
                'provider_live': provider == 'sqlite-immutable-ledger',
                'error': str(exc) or exc.__class__.__name__,
            }

    def _store_portfolio_provider_validation(
        self,
        gw,
        *,
        release: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        history = [dict(item) for item in list(portfolio.get('provider_validation_history') or [])]
        history.append(dict(validation))
        portfolio['provider_validation_history'] = history[-20:]
        portfolio['current_provider_validation'] = dict(validation)
        metadata['portfolio'] = portfolio
        return gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release

    @classmethod
    def _default_portfolio_operational_tier(cls, environment: str | None) -> str:
        env = cls._normalize_portfolio_environment_name(environment)
        if env == 'prod':
            return 'prod'
        if env == 'stage':
            return 'stage'
        if env == 'dev':
            return 'dev'
        return env or 'standard'

    @staticmethod
    def _merge_portfolio_policy_overrides(base_policy: dict[str, Any] | None, override_policy: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(base_policy or {})
        for key, value in dict(override_policy or {}).items():
            if value in (None, '', []):
                continue
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                nested = dict(merged.get(key) or {})
                nested.update({nested_key: nested_value for nested_key, nested_value in value.items() if nested_value not in (None, '', [])})
                merged[key] = nested
            else:
                merged[key] = value
        return merged

    def _resolve_portfolio_train_policy_for_environment(
        self,
        train_policy: dict[str, Any] | None,
        *,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_portfolio_train_policy(dict(train_policy or {}))
        env_key = self._normalize_portfolio_environment_name(environment)
        resolved = dict(normalized)
        resolved['resolved_environment'] = env_key or None
        resolved['operational_tier'] = self._default_portfolio_operational_tier(env_key)
        resolved['evidence_classification'] = self._default_portfolio_evidence_classification(env_key)
        override = dict((normalized.get('environment_tier_policies') or {}).get(env_key) or {}) if env_key else {}
        if override:
            resolved['environment_tier_policy'] = dict(override)
            resolved['operational_tier'] = str(override.get('operational_tier') or resolved.get('operational_tier') or '').strip() or self._default_portfolio_operational_tier(env_key)
            resolved['evidence_classification'] = str(override.get('evidence_classification') or resolved.get('evidence_classification') or '').strip() or self._default_portfolio_evidence_classification(env_key)
            resolved['tier_label'] = str(override.get('tier_label') or resolved.get('operational_tier') or '').strip() or resolved.get('operational_tier')
            resolved['approval_policy'] = self._merge_portfolio_policy_overrides(resolved.get('approval_policy'), override.get('approval_policy'))
            resolved['security_gate_policy'] = self._merge_portfolio_policy_overrides(resolved.get('security_gate_policy'), override.get('security_gate_policy'))
            resolved['escrow_policy'] = self._merge_portfolio_policy_overrides(resolved.get('escrow_policy'), override.get('escrow_policy'))
            resolved['signing_policy'] = self._merge_portfolio_policy_overrides(resolved.get('signing_policy'), override.get('signing_policy'))
            resolved['verification_gate_policy'] = self._merge_portfolio_policy_overrides(resolved.get('verification_gate_policy'), override.get('verification_gate_policy'))
        else:
            resolved['environment_tier_policy'] = {
                'environment': env_key or None,
                'tier_label': resolved.get('operational_tier'),
                'operational_tier': resolved.get('operational_tier'),
                'evidence_classification': resolved.get('evidence_classification'),
                'approval_policy': resolved.get('approval_policy'),
                'security_gate_policy': resolved.get('security_gate_policy'),
            }
        retention_policy = dict(resolved.get('retention_policy') or {})
        if resolved.get('evidence_classification'):
            retention_policy['classification'] = str(resolved.get('evidence_classification'))
        resolved['retention_policy'] = retention_policy
        baselines = dict(normalized.get('environment_policy_baselines') or {})
        baseline_override = dict(baselines.get(env_key) or {}) if env_key else {}
        if baseline_override:
            resolved['environment_policy_baseline'] = dict(baseline_override)
        else:
            resolved['environment_policy_baseline'] = {
                'environment': env_key or None,
                'baseline_label': f'{env_key}-baseline' if env_key else 'default-baseline',
                'operational_tier': self._default_portfolio_operational_tier(env_key),
                'evidence_classification': self._default_portfolio_evidence_classification(env_key),
            }
        return resolved

    def _resolve_portfolio_environment_policy_baseline(
        self,
        train_policy: dict[str, Any] | None,
        *,
        environment: str | None = None,
        gw=None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        release: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_portfolio_train_policy(dict(train_policy or {}))
        env_key = self._normalize_portfolio_environment_name(environment)
        baseline: dict[str, Any] = {}
        catalog_ref = dict(normalized.get('baseline_catalog_ref') or {})
        rollout_state = dict((((release or {}).get('metadata') or {}).get('portfolio') or {}).get('current_baseline_catalog_rollout') or {}) if release is not None else {}
        if gw is not None and catalog_ref and env_key:
            catalog_release = self._get_baseline_catalog_release(
                gw,
                catalog_id=str(catalog_ref.get('catalog_id') or ''),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            if catalog_release is not None:
                baseline = self._resolve_baseline_catalog_environment_baseline(
                    gw,
                    catalog_release=catalog_release,
                    environment=env_key,
                )
                if baseline:
                    baseline['catalog_ref'] = catalog_ref
        if rollout_state and bool(rollout_state.get('active')) and str(rollout_state.get('catalog_id') or '') == str(catalog_ref.get('catalog_id') or ''):
            rollout_candidates = self._normalize_baseline_catalog_environment_entries(dict(rollout_state.get('candidate_baselines') or {}))
            rollout_baseline = dict(rollout_candidates.get(env_key) or rollout_state.get('candidate_baseline') or {})
            if rollout_baseline:
                baseline = self._merge_portfolio_policy_overrides(baseline, rollout_baseline)
                baseline['configured'] = True
                baseline['environment'] = env_key or rollout_baseline.get('environment')
                baseline['baseline_label'] = str(rollout_baseline.get('baseline_label') or baseline.get('baseline_label') or f'{env_key}-baseline').strip() or f'{env_key}-baseline'
                baseline['candidate_rollout'] = {
                    'promotion_id': rollout_state.get('promotion_id'),
                    'wave_no': rollout_state.get('wave_no'),
                    'wave_id': rollout_state.get('wave_id'),
                    'catalog_version': rollout_state.get('catalog_version'),
                    'status': rollout_state.get('status'),
                }
        inline_baselines = dict(normalized.get('environment_policy_baselines') or {})
        inline_baseline = dict(inline_baselines.get(env_key) or {}) if env_key else {}
        catalog_overrides = dict(normalized.get('baseline_catalog_overrides') or {})
        override_baseline = dict(catalog_overrides.get(env_key) or {}) if env_key else {}
        for candidate in (inline_baseline, override_baseline):
            if candidate:
                baseline = self._merge_portfolio_policy_overrides(baseline, candidate)
                baseline['configured'] = True
                baseline['environment'] = env_key or candidate.get('environment')
                baseline['baseline_label'] = str(candidate.get('baseline_label') or baseline.get('baseline_label') or f'{env_key}-baseline').strip() or f'{env_key}-baseline'
                if candidate is override_baseline and catalog_ref:
                    baseline['override_applied'] = True
        if baseline:
            baseline['environment'] = env_key or baseline.get('environment')
            baseline['configured'] = bool(baseline.get('configured', True))
            return baseline
        return {
            'environment': env_key or None,
            'configured': False,
            'baseline_label': f'{env_key}-baseline' if env_key else 'default-baseline',
            'operational_tier': self._default_portfolio_operational_tier(env_key),
            'evidence_classification': self._default_portfolio_evidence_classification(env_key),
            'approval_policy': self._normalize_portfolio_approval_policy({}),
            'security_gate_policy': self._normalize_portfolio_security_gate_policy({}),
            'escrow_policy': self._normalize_portfolio_escrow_policy({}),
            'signing_policy': self._normalize_portfolio_signing_policy({}),
            'verification_gate_policy': self._normalize_portfolio_verification_gate_policy({}),
            'catalog_ref': catalog_ref or None,
        }

    @staticmethod
    def _resolve_portfolio_custody_anchor_policy_for_environment(
        policy: dict[str, Any] | None,
        *,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized = OpenClawRecoverySchedulerService._normalize_portfolio_custody_anchor_policy(dict(policy or {}))
        env_key = str(environment or '').strip().lower()
        if not env_key:
            return normalized
        override = dict((normalized.get('environment_policies') or {}).get(env_key) or {})
        if not override:
            return normalized
        merged = dict(normalized)
        merged.update({k: v for k, v in override.items() if v not in (None, '', [])})
        merged['resolved_environment'] = env_key
        return merged

    def _list_portfolio_approvals(
        self,
        gw,
        *,
        portfolio_id: str,
        limit: int = 100,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        workflow_id = self._portfolio_approval_workflow_id(portfolio_id)
        return gw.audit.list_approvals(
            limit=max(limit, 1),
            status=status,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def _portfolio_approval_state(
        self,
        *,
        portfolio_id: str,
        approval_policy: dict[str, Any],
        approvals: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        layers = [dict(item) for item in list((approval_policy or {}).get('layers') or [])]
        records = [dict(item) for item in list(approvals or [])]
        by_layer: dict[str, dict[str, Any]] = {}
        for layer in layers:
            layer_id = str(layer.get('layer_id') or '').strip()
            matching = [item for item in records if str(((item.get('payload') or {}).get('layer_id')) or '') == layer_id]
            matching.sort(key=lambda item: float(item.get('created_at') or 0.0), reverse=True)
            active = matching[0] if matching else None
            status = str((active or {}).get('status') or ('not_requested' if layer.get('required', True) else 'optional')).strip().lower()
            by_layer[layer_id] = {
                'layer_id': layer_id,
                'label': str(layer.get('label') or layer_id),
                'requested_role': str(layer.get('requested_role') or ''),
                'required': bool(layer.get('required', True)),
                'status': status,
                'approval_id': (active or {}).get('approval_id'),
                'decided_by': (active or {}).get('decided_by'),
                'decided_at': (active or {}).get('decided_at'),
                'created_at': (active or {}).get('created_at'),
                'approval': active,
            }
        pending_count = sum(1 for item in by_layer.values() if str(item.get('status') or '') == 'pending')
        approved_count = sum(1 for item in by_layer.values() if str(item.get('status') or '') == 'approved')
        rejected_count = sum(1 for item in by_layer.values() if str(item.get('status') or '') == 'rejected')
        not_requested_count = sum(1 for item in by_layer.values() if str(item.get('status') or '') in {'not_requested', 'optional'})
        required_layers = [item for item in by_layer.values() if bool(item.get('required', True))]
        satisfied = bool(required_layers) and all(str(item.get('status') or '') == 'approved' for item in required_layers)
        if not required_layers:
            satisfied = True
        overall_status = 'not_required'
        if layers:
            if rejected_count > 0:
                overall_status = 'rejected'
            elif satisfied:
                overall_status = 'approved'
            elif pending_count > 0:
                overall_status = 'pending'
            else:
                overall_status = 'not_requested'
        next_layer = None
        if layers and not satisfied and rejected_count == 0:
            mode = str((approval_policy or {}).get('mode') or 'sequential').strip().lower() or 'sequential'
            for layer in layers:
                layer_state = by_layer.get(str(layer.get('layer_id') or '').strip(), {})
                status = str(layer_state.get('status') or '')
                if status == 'approved':
                    continue
                next_layer = layer_state
                if mode == 'sequential':
                    break
        return {
            'portfolio_id': portfolio_id,
            'mode': str((approval_policy or {}).get('mode') or 'none'),
            'enabled': bool((approval_policy or {}).get('enabled')),
            'layers': [by_layer.get(str(layer.get('layer_id') or '').strip(), {}) for layer in layers],
            'pending_count': pending_count,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'not_requested_count': not_requested_count,
            'overall_status': overall_status,
            'satisfied': satisfied,
            'next_layer': next_layer,
        }

    def _refresh_portfolio_metadata_state(
        self,
        gw,
        *,
        release: dict[str, Any],
        approval_state: dict[str, Any] | None = None,
        simulation: dict[str, Any] | None = None,
        persist_schedule: bool = False,
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        calendar = [dict(item) for item in list(portfolio.get('train_calendar') or [])]
        simulation_payload = dict(simulation or {})
        simulation_items = [dict(item) for item in list(simulation_payload.get('items') or [])]
        if approval_state is not None:
            portfolio['approval_state'] = {
                'mode': approval_state.get('mode'),
                'enabled': approval_state.get('enabled'),
                'pending_count': int(approval_state.get('pending_count') or 0),
                'approved_count': int(approval_state.get('approved_count') or 0),
                'rejected_count': int(approval_state.get('rejected_count') or 0),
                'overall_status': approval_state.get('overall_status'),
                'satisfied': bool(approval_state.get('satisfied')),
                'next_layer': dict(approval_state.get('next_layer') or {}),
                'layers': [
                    {
                        'layer_id': item.get('layer_id'),
                        'label': item.get('label'),
                        'requested_role': item.get('requested_role'),
                        'required': item.get('required'),
                        'status': item.get('status'),
                        'approval_id': item.get('approval_id'),
                        'decided_by': item.get('decided_by'),
                        'decided_at': item.get('decided_at'),
                    }
                    for item in list(approval_state.get('layers') or [])
                ],
            }
        if simulation_payload:
            portfolio['last_simulation'] = {
                'executed_at': simulation_payload.get('executed_at'),
                'executed_by': simulation_payload.get('executed_by'),
                'dry_run': bool(simulation_payload.get('dry_run', True)),
                'persisted_schedule': bool(simulation_payload.get('persisted_schedule', False)),
                'validation_status': simulation_payload.get('validation_status'),
                'approvable': bool(simulation_payload.get('approvable', False)),
                'summary': dict(simulation_payload.get('summary') or {}),
                'open_conflicts': [dict(item) for item in list(simulation_payload.get('open_conflicts') or [])],
                'dependency_blocks': [dict(item) for item in list(simulation_payload.get('dependency_blocks') or [])],
                'freeze_hits': [dict(item) for item in list(simulation_payload.get('freeze_hits') or [])],
            }
            by_event = {str(item.get('event_id') or ''): item for item in simulation_items}
            updated_calendar: list[dict[str, Any]] = []
            for event in calendar:
                sim_item = by_event.get(str(event.get('event_id') or ''))
                updated = dict(event)
                if sim_item is not None:
                    validation = {
                        'simulation_status': sim_item.get('simulation_status'),
                        'original_planned_at': sim_item.get('original_planned_at'),
                        'proposed_at': sim_item.get('proposed_at'),
                        'reprogrammed': bool(sim_item.get('reprogrammed')),
                        'blockers': [dict(item) for item in list(sim_item.get('blockers') or [])],
                        'notices': [dict(item) for item in list(sim_item.get('notices') or [])],
                        'target_runtime_ids': list(sim_item.get('target_runtime_ids') or []),
                    }
                    updated['validation'] = validation
                    if persist_schedule and sim_item.get('proposed_at') is not None and str(updated.get('status') or 'planned') not in {'completed', 'error'}:
                        updated['planned_at'] = sim_item.get('proposed_at')
                updated_calendar.append(updated)
            portfolio['train_calendar'] = updated_calendar
        metadata['portfolio'] = portfolio
        return gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release

    def _portfolio_attestation_schedule_items(self, simulation: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in list((simulation or {}).get('items') or []):
            payload = dict(item or {})
            attested_planned_at = payload.get('proposed_at')
            if attested_planned_at is None:
                attested_planned_at = payload.get('original_planned_at')
            items.append({
                'event_id': str(payload.get('event_id') or ''),
                'bundle_id': str(payload.get('bundle_id') or ''),
                'wave_no': int(payload.get('wave_no') or 1),
                'attested_planned_at': float(attested_planned_at) if attested_planned_at is not None else None,
                'window_s': int(payload.get('window_s') or 0),
                'simulation_status': str(payload.get('simulation_status') or ''),
                'target_runtime_ids': [str(entry).strip() for entry in list(payload.get('target_runtime_ids') or []) if str(entry).strip()],
            })
        items.sort(key=lambda entry: (float(entry.get('attested_planned_at') or 0.0), int(entry.get('wave_no') or 0), str(entry.get('event_id') or '')))
        return items

    def _create_portfolio_execution_attestation(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        reason: str = '',
        simulation: dict[str, Any],
        approval_state: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        now_ts = time.time()
        schedule_items = self._portfolio_attestation_schedule_items(simulation)
        attestation_id = str(uuid.uuid4())
        base_train_policy = self._normalize_portfolio_train_policy(dict(portfolio.get('train_policy') or {}))
        train_policy = self._resolve_portfolio_train_policy_for_environment(base_train_policy, environment=release.get('environment'))
        attestation = {
            'attestation_id': attestation_id,
            'kind': 'portfolio_execution_plan',
            'created_at': now_ts,
            'created_by': str(actor or 'system'),
            'reason': str(reason or '').strip(),
            'portfolio_id': str(release.get('release_id') or ''),
            'portfolio_version': str(release.get('version') or ''),
            'release_status': str(release.get('status') or ''),
            'schedule_items': schedule_items,
            'schedule_hash': self._stable_digest(schedule_items),
            'simulation_hash': self._stable_digest({
                'validation_status': simulation.get('validation_status'),
                'summary': simulation.get('summary'),
                'items': schedule_items,
            }),
            'train_policy_hash': self._stable_digest(train_policy),
            'approval_state_hash': self._stable_digest({
                'overall_status': (approval_state or {}).get('overall_status'),
                'layers': [
                    {
                        'layer_id': item.get('layer_id'),
                        'status': item.get('status'),
                        'approval_id': item.get('approval_id'),
                    }
                    for item in list((approval_state or {}).get('layers') or [])
                ],
            }),
            'summary': {
                'count': len(schedule_items),
                'validation_status': simulation.get('validation_status'),
                'approvable': bool(simulation.get('approvable')),
                'reprogrammed_count': int((simulation.get('summary') or {}).get('reprogrammed_count') or 0),
                'blocked_count': int((simulation.get('summary') or {}).get('blocked_count') or 0),
                'deferred_count': int((simulation.get('summary') or {}).get('deferred_count') or 0),
            },
            'signature': self._stable_digest({
                'portfolio_id': str(release.get('release_id') or ''),
                'attestation_id': attestation_id,
                'schedule_hash': self._stable_digest(schedule_items),
                'actor': str(actor or 'system'),
            }),
            'state': 'current',
        }
        existing = [dict(item) for item in list(portfolio.get('attestations') or [])]
        for item in existing:
            if str(item.get('state') or '') == 'current':
                item['state'] = 'superseded'
        existing.append(attestation)
        portfolio['attestations'] = existing[-20:]
        portfolio['current_attestation'] = attestation
        portfolio['last_attested_at'] = now_ts
        metadata['portfolio'] = portfolio
        updated_release = gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release
        gw.audit.log_event(
            direction='system',
            channel='openclaw',
            user_id=str(actor or 'system'),
            session_id='',
            payload={
                'event': 'openclaw_portfolio_execution_attested',
                'portfolio_id': str(release.get('release_id') or ''),
                'attestation_id': attestation_id,
                'schedule_hash': attestation.get('schedule_hash'),
                'simulation_hash': attestation.get('simulation_hash'),
                'status': updated_release.get('status'),
            },
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        )
        return attestation, updated_release

    def _list_portfolio_attestations(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        items = [dict(item) for item in list(portfolio.get('attestations') or [])]
        items.sort(key=lambda item: float(item.get('created_at') or 0.0), reverse=True)
        return items

    def _list_portfolio_chain_of_custody_entries(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        items = [dict(item) for item in list(portfolio.get('chain_of_custody_ledger') or [])]
        items.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('timestamp') or 0.0), str(item.get('entry_id') or '')))
        return items

    def _build_portfolio_chain_of_custody_entry(
        self,
        *,
        release: dict[str, Any],
        actor: str,
        event_type: str,
        sequence: int,
        previous_entry_hash: str,
        chain_policy: dict[str, Any] | None = None,
        signing_policy: dict[str, Any] | None = None,
        package_id: str | None = None,
        artifact_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        normalized_chain = self._normalize_portfolio_chain_of_custody_policy(dict(chain_policy or {}))
        scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        ts = float(timestamp) if timestamp is not None else time.time()
        canonical = {
            'entry_type': 'openmiura_portfolio_chain_of_custody_entry_v1',
            'entry_id': str(uuid.uuid4()),
            'portfolio_id': str(release.get('release_id') or '').strip(),
            'sequence': int(sequence),
            'timestamp': ts,
            'actor': str(actor or 'system').strip() or 'system',
            'event_type': str(event_type or '').strip() or 'unknown',
            'package_id': str(package_id or '').strip() or None,
            'artifact_sha256': str(artifact_sha256 or '').strip() or None,
            'scope': scope,
            'previous_entry_hash': str(previous_entry_hash or '').strip(),
            'metadata': dict(metadata or {}),
        }
        integrity = self._portfolio_evidence_integrity(
            report_type='openmiura_portfolio_chain_of_custody_entry_v1',
            scope=scope,
            payload=canonical,
            actor=str(actor or 'system'),
            export_policy={'require_signature': bool(normalized_chain.get('sign_entries', True)), 'signer_key_id': str(normalized_chain.get('signer_key_id') or 'openmiura-custody')},
            signing_policy=signing_policy,
        )
        entry_hash = self._stable_digest({
            'canonical': canonical,
            'payload_hash': integrity.get('payload_hash'),
            'previous_entry_hash': canonical.get('previous_entry_hash'),
        })
        return {**canonical, 'entry_hash': entry_hash, 'integrity': integrity}

    def _prepare_portfolio_chain_of_custody_snapshot(
        self,
        *,
        release: dict[str, Any],
        actor: str,
        chain_policy: dict[str, Any] | None = None,
        signing_policy: dict[str, Any] | None = None,
        events: list[dict[str, Any]] | None = None,
        timestamp: float | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        normalized_chain = self._normalize_portfolio_chain_of_custody_policy(dict(chain_policy or {}))
        base_entries = self._list_portfolio_chain_of_custody_entries(release)
        working = [dict(item) for item in base_entries]
        new_entries: list[dict[str, Any]] = []
        if bool(normalized_chain.get('enabled', True)):
            for raw in list(events or []):
                sequence = (int(working[-1].get('sequence') or 0) if working else 0) + 1
                previous_hash = str(working[-1].get('entry_hash') or '') if working else ''
                entry = self._build_portfolio_chain_of_custody_entry(
                    release=release,
                    actor=str(raw.get('actor') or actor or 'system'),
                    event_type=str(raw.get('event_type') or '').strip() or 'unknown',
                    sequence=sequence,
                    previous_entry_hash=previous_hash,
                    chain_policy=normalized_chain,
                    signing_policy=signing_policy,
                    package_id=raw.get('package_id'),
                    artifact_sha256=raw.get('artifact_sha256'),
                    metadata=dict(raw.get('metadata') or {}),
                    timestamp=timestamp,
                )
                working.append(entry)
                new_entries.append(entry)
        snapshot = {
            'ledger_type': 'openmiura_portfolio_chain_of_custody_v1',
            'portfolio_id': str(release.get('release_id') or '').strip(),
            'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
            'entries': working[-max(1, int(normalized_chain.get('max_entries') or 500)):],
        }
        snapshot['summary'] = self._verify_portfolio_chain_of_custody_entries(snapshot['entries'])
        return base_entries, new_entries, snapshot

    def _verify_portfolio_chain_of_custody_entries(self, entries: list[dict[str, Any]] | None) -> dict[str, Any]:
        items = [dict(item) for item in list(entries or [])]
        previous_hash = ''
        chain_valid = True
        signature_valid_count = 0
        invalid_entry_ids: list[str] = []
        for item in items:
            canonical = {
                'entry_type': 'openmiura_portfolio_chain_of_custody_entry_v1',
                'entry_id': item.get('entry_id'),
                'portfolio_id': item.get('portfolio_id'),
                'sequence': int(item.get('sequence') or 0),
                'timestamp': float(item.get('timestamp') or 0.0),
                'actor': item.get('actor'),
                'event_type': item.get('event_type'),
                'package_id': item.get('package_id'),
                'artifact_sha256': item.get('artifact_sha256'),
                'scope': dict(item.get('scope') or {}),
                'previous_entry_hash': item.get('previous_entry_hash'),
                'metadata': dict(item.get('metadata') or {}),
            }
            integrity_verify = self._verify_portfolio_export_integrity(
                report_type='openmiura_portfolio_chain_of_custody_entry_v1',
                scope=dict(item.get('scope') or {}),
                payload=canonical,
                integrity=dict(item.get('integrity') or {}),
            )
            if integrity_verify.get('valid'):
                signature_valid_count += 1
            expected_entry_hash = self._stable_digest({
                'canonical': canonical,
                'payload_hash': ((item.get('integrity') or {}).get('payload_hash')),
                'previous_entry_hash': previous_hash,
            })
            if str(item.get('previous_entry_hash') or '') != previous_hash or str(item.get('entry_hash') or '') != expected_entry_hash or not bool(integrity_verify.get('valid')):
                chain_valid = False
                invalid_entry_ids.append(str(item.get('entry_id') or ''))
            previous_hash = str(item.get('entry_hash') or '')
        return {
            'count': len(items),
            'head_hash': previous_hash or None,
            'chain_valid': chain_valid,
            'signature_valid_count': signature_valid_count,
            'invalid_entry_ids': [item for item in invalid_entry_ids if item],
            'valid': chain_valid and signature_valid_count == len(items),
        }

    def _store_portfolio_chain_of_custody_entries(
        self,
        gw,
        *,
        release: dict[str, Any],
        entries: list[dict[str, Any]] | None,
        chain_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_chain = self._normalize_portfolio_chain_of_custody_policy(dict(chain_policy or {}))
        if not entries:
            return release
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        current = self._list_portfolio_chain_of_custody_entries(release)
        current.extend([dict(item) for item in list(entries or [])])
        current = current[-max(1, int(normalized_chain.get('max_entries') or 500)):]
        portfolio['chain_of_custody_ledger'] = current
        portfolio['current_chain_of_custody_head'] = current[-1].get('entry_hash') if current else None
        metadata['portfolio'] = portfolio
        return gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release

    @staticmethod
    def _open_portfolio_custody_anchor_sqlite(pathlike: str | Path) -> sqlite3.Connection:
        path = Path(pathlike)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path.as_posix(), timeout=30.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute("CREATE TABLE IF NOT EXISTS custody_anchor_receipts (portfolio_id TEXT NOT NULL, sequence INTEGER NOT NULL, anchor_id TEXT NOT NULL, receipt_json TEXT NOT NULL, receipt_hash TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY (portfolio_id, sequence), UNIQUE(anchor_id))")
        conn.execute("CREATE TRIGGER IF NOT EXISTS trg_custody_anchor_receipts_no_update BEFORE UPDATE ON custody_anchor_receipts BEGIN SELECT RAISE(ABORT, 'immutable_custody_anchor_ledger'); END;")
        conn.execute("CREATE TRIGGER IF NOT EXISTS trg_custody_anchor_receipts_no_delete BEFORE DELETE ON custody_anchor_receipts BEGIN SELECT RAISE(ABORT, 'immutable_custody_anchor_ledger'); END;")
        return conn

    def _load_external_portfolio_custody_anchor_receipts(
        self,
        *,
        release: dict[str, Any],
        custody_anchor_policy: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        policy = self._resolve_portfolio_custody_anchor_policy_for_environment(custody_anchor_policy, environment=release.get('environment'))
        provider = str(policy.get('provider') or 'filesystem-ledger')
        scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        portfolio_id = str(release.get('release_id') or '').strip() or 'portfolio'
        items: list[dict[str, Any]] = []
        if provider == 'filesystem-ledger':
            root_dir = Path(str(policy.get('root_dir') or 'data/openclaw_custody_anchor'))
            anchor_dir = root_dir.joinpath(
                str(policy.get('ledger_namespace') or 'portfolio-custody'),
                str(scope.get('tenant_id') or 'global'),
                str(scope.get('workspace_id') or 'default'),
                str(scope.get('environment') or 'default'),
                portfolio_id,
                'anchors',
            )
            if anchor_dir.exists():
                for path in sorted(anchor_dir.glob('*.json')):
                    try:
                        items.append(json.loads(path.read_text(encoding='utf-8')))
                    except Exception:
                        continue
        elif provider == 'sqlite-immutable-ledger':
            sqlite_path = Path(str(policy.get('sqlite_path') or 'data/openclaw_custody_anchor/custody_anchor_ledger.sqlite3'))
            if sqlite_path.exists():
                conn = self._open_portfolio_custody_anchor_sqlite(sqlite_path)
                try:
                    rows = conn.execute('SELECT receipt_json FROM custody_anchor_receipts WHERE portfolio_id = ? ORDER BY sequence ASC', (portfolio_id,)).fetchall()
                finally:
                    conn.close()
                for (receipt_json,) in rows:
                    try:
                        items.append(json.loads(str(receipt_json)))
                    except Exception:
                        continue
        items.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('anchored_at') or 0.0), str(item.get('anchor_id') or '')))
        return items

    def _replace_portfolio_custody_anchor_receipts(
        self,
        gw,
        *,
        release: dict[str, Any],
        receipts: list[dict[str, Any]],
        custody_anchor_policy: dict[str, Any] | None = None,
        reconciliation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_custody_anchor_policy(dict(custody_anchor_policy or {}))
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        trimmed = [dict(item) for item in list(receipts or [])][-max(1, int(policy.get('max_receipts') or 250)):]
        portfolio['custody_anchor_receipts'] = trimmed
        portfolio['current_custody_anchor'] = trimmed[-1] if trimmed else None
        if reconciliation is not None:
            history = [dict(item) for item in list(portfolio.get('custody_reconciliation_history') or [])]
            history.append(dict(reconciliation))
            portfolio['custody_reconciliation_history'] = history[-20:]
            portfolio['current_custody_reconciliation'] = dict(reconciliation)
        metadata['portfolio'] = portfolio
        return gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release

