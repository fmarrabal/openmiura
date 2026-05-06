from __future__ import annotations

import os
import shlex
import socket
from pathlib import Path
from typing import Any




class OpenClawPolicyNormalizationMixin:
    @staticmethod
    def _normalize_weekdays(values: list[Any] | tuple[Any, ...] | None) -> list[int]:
        mapping = {
            'mon': 0,
            'monday': 0,
            'tue': 1,
            'tues': 1,
            'tuesday': 1,
            'wed': 2,
            'wednesday': 2,
            'thu': 3,
            'thur': 3,
            'thurs': 3,
            'thursday': 3,
            'fri': 4,
            'friday': 4,
            'sat': 5,
            'saturday': 5,
            'sun': 6,
            'sunday': 6,
        }
        out: list[int] = []
        for item in list(values or []):
            if isinstance(item, int):
                if 0 <= int(item) <= 6:
                    out.append(int(item))
                continue
            raw = str(item or '').strip().lower()
            if not raw:
                continue
            if raw.isdigit() and 0 <= int(raw) <= 6:
                out.append(int(raw))
                continue
            if raw in mapping:
                out.append(mapping[raw])
        return sorted(set(out))


    @staticmethod
    def _normalize_portfolio_freeze_windows(raw_windows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for idx, entry in enumerate(list(raw_windows or []), start=1):
            start_at = entry.get('start_at')
            end_at = entry.get('end_at')
            try:
                normalized_start = float(start_at) if start_at is not None else None
            except Exception:
                normalized_start = None
            try:
                normalized_end = float(end_at) if end_at is not None else None
            except Exception:
                normalized_end = None
            if normalized_start is None and normalized_end is None:
                continue
            if normalized_start is not None and normalized_end is not None and normalized_end < normalized_start:
                normalized_start, normalized_end = normalized_end, normalized_start
            bundle_ids = [str(item).strip() for item in list(entry.get('bundle_ids') or []) if str(item).strip()]
            items.append({
                'window_id': str(entry.get('window_id') or f'freeze-{idx}').strip() or f'freeze-{idx}',
                'label': str(entry.get('label') or entry.get('name') or f'freeze-{idx}').strip() or f'freeze-{idx}',
                'start_at': normalized_start,
                'end_at': normalized_end,
                'reason': str(entry.get('reason') or '').strip(),
                'bundle_ids': bundle_ids,
                'workspace_ids': [str(item).strip() for item in list(entry.get('workspace_ids') or []) if str(item).strip()],
                'environment': str(entry.get('environment') or '').strip(),
            })
        items.sort(key=lambda item: (float(item.get('start_at') or 0.0), float(item.get('end_at') or 0.0), str(item.get('window_id') or '')))
        return items


    @staticmethod
    def _normalize_portfolio_dependency_graph(raw_dependency_graph: Any) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        if isinstance(raw_dependency_graph, dict):
            iterable = raw_dependency_graph.items()
        else:
            iterable = []
            for entry in list(raw_dependency_graph or []):
                if not isinstance(entry, dict):
                    continue
                iterable.append((entry.get('bundle_id'), entry.get('depends_on')))
        for bundle_id, depends_on in iterable:
            normalized_bundle_id = str(bundle_id or '').strip()
            if not normalized_bundle_id:
                continue
            deps = []
            for item in list(depends_on or []):
                dep_id = str(item or '').strip()
                if dep_id and dep_id != normalized_bundle_id and dep_id not in deps:
                    deps.append(dep_id)
            graph[normalized_bundle_id] = deps
        return graph


    @staticmethod
    def _normalize_portfolio_approval_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        layers: list[dict[str, Any]] = []
        raw_layers = list(payload.get('layers') or [])
        if not raw_layers and payload.get('requested_role'):
            raw_layers = [{
                'layer_id': 'portfolio-approval',
                'label': 'Portfolio approval',
                'requested_role': payload.get('requested_role'),
            }]
        for idx, entry in enumerate(raw_layers, start=1):
            requested_role = str(entry.get('requested_role') or '').strip()
            if not requested_role:
                continue
            layer_id = str(entry.get('layer_id') or entry.get('level_id') or entry.get('name') or f'layer-{idx}').strip() or f'layer-{idx}'
            layers.append({
                'layer_id': layer_id,
                'label': str(entry.get('label') or entry.get('name') or layer_id).strip() or layer_id,
                'requested_role': requested_role,
                'required': bool(entry.get('required', True)),
                'description': str(entry.get('description') or '').strip(),
            })
        mode = str(payload.get('mode') or ('sequential' if layers else 'none')).strip().lower() or 'none'
        if mode not in {'none', 'sequential', 'parallel'}:
            mode = 'sequential' if layers else 'none'
        return {
            'mode': mode,
            'layers': layers,
            'enabled': bool(layers),
            'simulate_before_request': bool(payload.get('simulate_before_request', True)),
            'block_on_rejection': bool(payload.get('block_on_rejection', True)),
        }


    @staticmethod
    def _normalize_portfolio_drift_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        try:
            schedule_tolerance_s = float(payload.get('schedule_tolerance_s') or 0.0)
        except Exception:
            schedule_tolerance_s = 0.0
        return {
            'enabled': bool(payload.get('enabled', True)),
            'block_on_missing_attestation': bool(payload.get('block_on_missing_attestation', True)),
            'block_on_schedule_change': bool(payload.get('block_on_schedule_change', True)),
            'block_on_target_change': bool(payload.get('block_on_target_change', True)),
            'block_on_status_downgrade': bool(payload.get('block_on_status_downgrade', True)),
            'schedule_tolerance_s': max(0.0, schedule_tolerance_s),
            'persist_detections': bool(payload.get('persist_detections', True)),
        }


    @staticmethod
    def _normalize_portfolio_export_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        try:
            timeline_limit = int(payload.get('timeline_limit') or 250)
        except Exception:
            timeline_limit = 250
        try:
            evidence_limit = int(payload.get('evidence_limit') or max(100, timeline_limit))
        except Exception:
            evidence_limit = max(100, timeline_limit)
        return {
            'enabled': bool(payload.get('enabled', True)),
            'require_signature': bool(payload.get('require_signature', True)),
            'signer_key_id': str(payload.get('signer_key_id') or 'openmiura-local').strip() or 'openmiura-local',
            'timeline_limit': max(25, timeline_limit),
            'evidence_limit': max(25, evidence_limit),
            'include_audit_events': bool(payload.get('include_audit_events', True)),
            'include_jobs': bool(payload.get('include_jobs', True)),
            'include_replay_timeline': bool(payload.get('include_replay_timeline', True)),
            'embed_artifact_content': bool(payload.get('embed_artifact_content', True)),
            'artifact_format': str(payload.get('artifact_format') or 'zip').strip().lower() or 'zip',
            'restore_history_limit': max(1, int(payload.get('restore_history_limit') or 20)),
        }


    @staticmethod
    def _normalize_portfolio_notarization_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        try:
            receipt_ttl_days = int(payload.get('receipt_ttl_days') or 365)
        except Exception:
            receipt_ttl_days = 365
        return {
            'enabled': bool(payload.get('enabled', False)),
            'provider': str(payload.get('provider') or 'simulated-external').strip() or 'simulated-external',
            'require_on_export': bool(payload.get('require_on_export', True)),
            'allow_unsigned_fallback': bool(payload.get('allow_unsigned_fallback', False)),
            'notary_key_id': str(payload.get('notary_key_id') or 'openmiura-notary').strip() or 'openmiura-notary',
            'receipt_ttl_days': max(1, receipt_ttl_days),
            'reference_namespace': str(payload.get('reference_namespace') or 'openmiura-evidence').strip() or 'openmiura-evidence',
            'mode': str(payload.get('mode') or 'simulated_external').strip() or 'simulated_external',
        }


    @staticmethod
    def _normalize_portfolio_escrow_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        try:
            immutable_retention_days = int(payload.get('immutable_retention_days') or payload.get('retention_lock_days') or 365)
        except Exception:
            immutable_retention_days = 365
        provider = str(payload.get('provider') or 'filesystem-governed').strip() or 'filesystem-governed'
        object_lock_enabled = provider in {'filesystem-object-lock', 'object-lock-filesystem', 'aws-s3-object-lock', 's3-object-lock', 'azure-blob-immutable', 'gcs-retention-lock'} or bool(payload.get('object_lock_enabled', False))
        root_dir = str(payload.get('root_dir') or os.getenv('OPENMIURA_EVIDENCE_ESCROW_DIR') or 'data/openclaw_evidence_escrow').strip() or 'data/openclaw_evidence_escrow'
        mode_default = 'filesystem_external'
        if provider in {'aws-s3-object-lock', 's3-object-lock'}:
            mode_default = 's3_object_lock'
        elif provider == 'azure-blob-immutable':
            mode_default = 'azure_blob_immutable'
        elif provider == 'gcs-retention-lock':
            mode_default = 'gcs_retention_lock'
        elif object_lock_enabled:
            mode_default = 'filesystem_object_lock'
        return {
            'enabled': bool(payload.get('enabled', False)),
            'provider': provider,
            'mode': str(payload.get('mode') or mode_default).strip() or mode_default,
            'root_dir': root_dir,
            'archive_namespace': str(payload.get('archive_namespace') or 'portfolio-evidence').strip() or 'portfolio-evidence',
            'require_archive_on_export': bool(payload.get('require_archive_on_export', True)),
            'allow_inline_fallback': bool(payload.get('allow_inline_fallback', True)),
            'write_receipt_sidecar': bool(payload.get('write_receipt_sidecar', True)),
            'immutable_retention_days': max(1, immutable_retention_days),
            'escrow_key_id': str(payload.get('escrow_key_id') or 'openmiura-escrow').strip() or 'openmiura-escrow',
            'object_lock_enabled': object_lock_enabled,
            'retention_mode': str(payload.get('retention_mode') or ('GOVERNANCE' if object_lock_enabled else 'none')).strip().upper() or ('GOVERNANCE' if object_lock_enabled else 'none'),
            'require_object_lock': bool(payload.get('require_object_lock', object_lock_enabled)),
            'lock_sidecar': bool(payload.get('lock_sidecar', object_lock_enabled)),
            'lock_key_id': str(payload.get('lock_key_id') or payload.get('escrow_key_id') or 'openmiura-object-lock').strip() or 'openmiura-object-lock',
            'delete_protection': bool(payload.get('delete_protection', object_lock_enabled)),
            'aws_s3_bucket': str(payload.get('aws_s3_bucket') or os.getenv('OPENMIURA_EVIDENCE_S3_BUCKET') or '').strip(),
            'aws_s3_prefix': str(payload.get('aws_s3_prefix') or os.getenv('OPENMIURA_EVIDENCE_S3_PREFIX') or '').strip(),
            'aws_region': str(payload.get('aws_region') or os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION') or '').strip(),
            'aws_profile': str(payload.get('aws_profile') or os.getenv('AWS_PROFILE') or '').strip(),
            'aws_endpoint_url': str(payload.get('aws_endpoint_url') or os.getenv('OPENMIURA_EVIDENCE_S3_ENDPOINT_URL') or '').strip(),
            'aws_s3_storage_class': str(payload.get('aws_s3_storage_class') or os.getenv('OPENMIURA_EVIDENCE_S3_STORAGE_CLASS') or 'STANDARD').strip() or 'STANDARD',
            'aws_s3_sse': str(payload.get('aws_s3_sse') or os.getenv('OPENMIURA_EVIDENCE_S3_SSE') or '').strip(),
            'aws_s3_kms_key_id': str(payload.get('aws_s3_kms_key_id') or os.getenv('OPENMIURA_EVIDENCE_S3_KMS_KEY_ID') or '').strip(),
            'aws_s3_object_lock_legal_hold': bool(payload.get('aws_s3_object_lock_legal_hold', payload.get('object_lock_legal_hold', False))),
            'aws_s3_metadata_namespace': str(payload.get('aws_s3_metadata_namespace') or 'openmiura').strip() or 'openmiura',
            'azure_blob_account_url': str(payload.get('azure_blob_account_url') or os.getenv('OPENMIURA_EVIDENCE_AZURE_BLOB_ACCOUNT_URL') or '').strip(),
            'azure_blob_connection_string': str(payload.get('azure_blob_connection_string') or os.getenv('OPENMIURA_EVIDENCE_AZURE_BLOB_CONNECTION_STRING') or '').strip(),
            'azure_blob_container': str(payload.get('azure_blob_container') or os.getenv('OPENMIURA_EVIDENCE_AZURE_BLOB_CONTAINER') or '').strip(),
            'azure_blob_prefix': str(payload.get('azure_blob_prefix') or os.getenv('OPENMIURA_EVIDENCE_AZURE_BLOB_PREFIX') or '').strip(),
            'azure_blob_immutable_policy_mode': str(payload.get('azure_blob_immutable_policy_mode') or 'Unlocked').strip() or 'Unlocked',
            'azure_blob_legal_hold': bool(payload.get('azure_blob_legal_hold', payload.get('object_lock_legal_hold', False))),
            'gcs_bucket': str(payload.get('gcs_bucket') or os.getenv('OPENMIURA_EVIDENCE_GCS_BUCKET') or '').strip(),
            'gcs_prefix': str(payload.get('gcs_prefix') or os.getenv('OPENMIURA_EVIDENCE_GCS_PREFIX') or '').strip(),
            'gcs_project': str(payload.get('gcs_project') or os.getenv('GOOGLE_CLOUD_PROJECT') or '').strip(),
            'gcs_credentials_path': str(payload.get('gcs_credentials_path') or os.getenv('GOOGLE_APPLICATION_CREDENTIALS') or '').strip(),
            'gcs_temporary_hold': bool(payload.get('gcs_temporary_hold', True)),
            'gcs_event_based_hold': bool(payload.get('gcs_event_based_hold', False)),
        }


    @staticmethod
    def _normalize_portfolio_signing_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        provider = str(payload.get('provider') or os.getenv('OPENMIURA_EVIDENCE_SIGNING_PROVIDER') or 'local-ed25519').strip() or 'local-ed25519'
        external_providers = {
            'kms-ed25519-simulated',
            'hsm-ed25519-simulated',
            'kms-ed25519-file',
            'hsm-ed25519-file',
            'kms-ed25519-command',
            'hsm-ed25519-command',
            'aws-kms-ecdsa-p256',
            'gcp-kms-ecdsa-p256',
            'azure-kv-ecdsa-p256',
            'pkcs11-ed25519',
            'pkcs11-ecdsa-p256',
        }
        require_external = bool(payload.get('require_external_provider', provider in external_providers))
        allow_local_fallback = bool(payload.get('allow_local_fallback', not require_external))
        raw_command = payload.get('sign_command')
        if raw_command is None:
            raw_command = os.getenv('OPENMIURA_EVIDENCE_SIGN_COMMAND') or ''
        if isinstance(raw_command, (list, tuple)):
            sign_command = [str(item).strip() for item in raw_command if str(item).strip()]
        else:
            sign_command = [str(item).strip() for item in shlex.split(str(raw_command or '')) if str(item).strip()]
        command_env = {
            str(key).strip(): str(value)
            for key, value in dict(payload.get('command_env') or {}).items()
            if str(key).strip()
        }
        try:
            command_timeout_s = float(payload.get('command_timeout_s') or os.getenv('OPENMIURA_EVIDENCE_SIGN_COMMAND_TIMEOUT_S') or 10.0)
        except Exception:
            command_timeout_s = 10.0
        return {
            'enabled': bool(payload.get('enabled', True)),
            'provider': provider,
            'key_id': str(payload.get('key_id') or os.getenv('OPENMIURA_EVIDENCE_SIGNING_KEY_ID') or 'openmiura-signing').strip() or 'openmiura-signing',
            'require_external_provider': require_external,
            'allow_local_fallback': allow_local_fallback,
            'kms_private_key_pem_b64': str(payload.get('kms_private_key_pem_b64') or '').strip(),
            'kms_private_key_pem_path': str(payload.get('kms_private_key_pem_path') or os.getenv('OPENMIURA_EVIDENCE_KMS_PRIVATE_KEY_PEM_PATH') or '').strip(),
            'kms_public_key_pem_b64': str(payload.get('kms_public_key_pem_b64') or '').strip(),
            'kms_public_key_pem_path': str(payload.get('kms_public_key_pem_path') or os.getenv('OPENMIURA_EVIDENCE_KMS_PUBLIC_KEY_PEM_PATH') or '').strip(),
            'kms_key_ref': str(payload.get('kms_key_ref') or os.getenv('OPENMIURA_EVIDENCE_KMS_KEY_REF') or '').strip(),
            'hsm_private_key_pem_b64': str(payload.get('hsm_private_key_pem_b64') or '').strip(),
            'hsm_private_key_pem_path': str(payload.get('hsm_private_key_pem_path') or os.getenv('OPENMIURA_EVIDENCE_HSM_PRIVATE_KEY_PEM_PATH') or '').strip(),
            'hsm_public_key_pem_b64': str(payload.get('hsm_public_key_pem_b64') or '').strip(),
            'hsm_public_key_pem_path': str(payload.get('hsm_public_key_pem_path') or os.getenv('OPENMIURA_EVIDENCE_HSM_PUBLIC_KEY_PEM_PATH') or '').strip(),
            'hsm_slot_id': str(payload.get('hsm_slot_id') or os.getenv('OPENMIURA_EVIDENCE_HSM_SLOT_ID') or '').strip(),
            'sign_command': sign_command,
            'command_env': command_env,
            'command_timeout_s': max(1.0, command_timeout_s),
            'aws_kms_key_id': str(payload.get('aws_kms_key_id') or os.getenv('OPENMIURA_EVIDENCE_AWS_KMS_KEY_ID') or '').strip(),
            'aws_region': str(payload.get('aws_region') or os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION') or '').strip(),
            'aws_profile': str(payload.get('aws_profile') or os.getenv('AWS_PROFILE') or '').strip(),
            'aws_endpoint_url': str(payload.get('aws_endpoint_url') or os.getenv('OPENMIURA_EVIDENCE_AWS_KMS_ENDPOINT_URL') or '').strip(),
            'aws_signing_algorithm': str(payload.get('aws_signing_algorithm') or os.getenv('OPENMIURA_EVIDENCE_AWS_SIGNING_ALGORITHM') or 'ECDSA_SHA_256').strip() or 'ECDSA_SHA_256',
            'aws_public_key_pem_b64': str(payload.get('aws_public_key_pem_b64') or '').strip(),
            'aws_public_key_pem_path': str(payload.get('aws_public_key_pem_path') or '').strip(),
            'gcp_kms_key_name': str(payload.get('gcp_kms_key_name') or os.getenv('OPENMIURA_EVIDENCE_GCP_KMS_KEY_NAME') or '').strip(),
            'gcp_credentials_path': str(payload.get('gcp_credentials_path') or os.getenv('GOOGLE_APPLICATION_CREDENTIALS') or '').strip(),
            'gcp_public_key_pem_b64': str(payload.get('gcp_public_key_pem_b64') or '').strip(),
            'gcp_public_key_pem_path': str(payload.get('gcp_public_key_pem_path') or '').strip(),
            'azure_key_id': str(payload.get('azure_key_id') or os.getenv('OPENMIURA_EVIDENCE_AZURE_KEY_ID') or '').strip(),
            'azure_vault_url': str(payload.get('azure_vault_url') or os.getenv('OPENMIURA_EVIDENCE_AZURE_VAULT_URL') or '').strip(),
            'azure_public_key_pem_b64': str(payload.get('azure_public_key_pem_b64') or '').strip(),
            'azure_public_key_pem_path': str(payload.get('azure_public_key_pem_path') or '').strip(),
            'azure_signature_algorithm_enum': str(payload.get('azure_signature_algorithm_enum') or 'es256').strip() or 'es256',
            'pkcs11_module_path': str(payload.get('pkcs11_module_path') or os.getenv('OPENMIURA_EVIDENCE_PKCS11_MODULE_PATH') or '').strip(),
            'pkcs11_slot_id': payload.get('pkcs11_slot_id') if payload.get('pkcs11_slot_id') is not None else (int(os.getenv('OPENMIURA_EVIDENCE_PKCS11_SLOT_ID')) if os.getenv('OPENMIURA_EVIDENCE_PKCS11_SLOT_ID') else None),
            'pkcs11_token_label': str(payload.get('pkcs11_token_label') or os.getenv('OPENMIURA_EVIDENCE_PKCS11_TOKEN_LABEL') or '').strip(),
            'pkcs11_key_label': str(payload.get('pkcs11_key_label') or os.getenv('OPENMIURA_EVIDENCE_PKCS11_KEY_LABEL') or '').strip(),
            'pkcs11_pin': str(payload.get('pkcs11_pin') or '').strip(),
            'pkcs11_pin_env_var': str(payload.get('pkcs11_pin_env_var') or os.getenv('OPENMIURA_EVIDENCE_PKCS11_PIN_ENV_VAR') or 'OPENMIURA_EVIDENCE_PKCS11_PIN').strip(),
            'pkcs11_mechanism': str(payload.get('pkcs11_mechanism') or ('ECDSA' if provider == 'pkcs11-ecdsa-p256' else 'EDDSA')).strip().upper() or ('ECDSA' if provider == 'pkcs11-ecdsa-p256' else 'EDDSA'),
            'pkcs11_public_key_pem_b64': str(payload.get('pkcs11_public_key_pem_b64') or '').strip(),
            'pkcs11_public_key_pem_path': str(payload.get('pkcs11_public_key_pem_path') or '').strip(),
        }


    @staticmethod
    def _normalize_portfolio_chain_of_custody_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        try:
            max_entries = int(payload.get('max_entries') or 500)
        except Exception:
            max_entries = 500
        return {
            'enabled': bool(payload.get('enabled', True)),
            'include_in_artifact': bool(payload.get('include_in_artifact', True)),
            'sign_entries': bool(payload.get('sign_entries', True)),
            'signer_key_id': str(payload.get('signer_key_id') or 'openmiura-custody').strip() or 'openmiura-custody',
            'max_entries': max(10, max_entries),
        }


    @staticmethod
    def _normalize_portfolio_custody_anchor_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        try:
            max_receipts = int(payload.get('max_receipts') or 250)
        except Exception:
            max_receipts = 250
        root_dir = str(payload.get('root_dir') or os.getenv('OPENMIURA_CUSTODY_ANCHOR_DIR') or 'data/openclaw_custody_anchor').strip() or 'data/openclaw_custody_anchor'
        provider = str(payload.get('provider') or 'filesystem-ledger').strip() or 'filesystem-ledger'
        sqlite_path = str(payload.get('sqlite_path') or os.getenv('OPENMIURA_CUSTODY_ANCHOR_SQLITE_PATH') or '').strip()
        if not sqlite_path:
            sqlite_path = str(Path(root_dir).joinpath('custody_anchor_ledger.sqlite3'))
        environment_policies = {}
        for env_name, env_payload in dict(payload.get('environment_policies') or payload.get('quorum_witness_policies') or {}).items():
            env_key = str(env_name or '').strip().lower()
            if not env_key:
                continue
            env_policy = dict(env_payload or {})
            environment_policies[env_key] = {
                'append_authority': str(env_policy.get('append_authority') or payload.get('append_authority') or 'any').strip().lower() or 'any',
                'leader_control_plane_id': str(env_policy.get('leader_control_plane_id') or '').strip(),
                'quorum_enabled': bool(env_policy.get('quorum_enabled', payload.get('quorum_enabled', False))),
                'quorum_size': max(1, int(env_policy.get('quorum_size') or payload.get('quorum_size') or 1)),
                'require_quorum_for_reconciliation': bool(env_policy.get('require_quorum_for_reconciliation', payload.get('require_quorum_for_reconciliation', False))),
                'allow_witness_attestations': bool(env_policy.get('allow_witness_attestations', payload.get('allow_witness_attestations', True))),
                'authority_hint': str(env_policy.get('authority_hint') or payload.get('authority_hint') or '').strip().lower() or None,
                'required_witness_count': max(0, int(env_policy.get('required_witness_count') or 0)),
                'required_witness_control_planes': [str(item).strip() for item in list(env_policy.get('required_witness_control_planes') or []) if str(item).strip()],
            }
        return {
            'enabled': bool(payload.get('enabled', False)),
            'provider': provider,
            'root_dir': root_dir,
            'sqlite_path': sqlite_path,
            'ledger_namespace': str(payload.get('ledger_namespace') or 'portfolio-custody').strip() or 'portfolio-custody',
            'require_anchor_on_export': bool(payload.get('require_anchor_on_export', False)),
            'anchor_on_export': bool(payload.get('anchor_on_export', True)),
            'include_in_artifact': bool(payload.get('include_in_artifact', True)),
            'verify_against_external': bool(payload.get('verify_against_external', True)),
            'signer_key_id': str(payload.get('signer_key_id') or 'openmiura-custody-anchor').strip() or 'openmiura-custody-anchor',
            'max_receipts': max(10, max_receipts),
            'require_immutable_backend': bool(payload.get('require_immutable_backend', provider == 'sqlite-immutable-ledger')),
            'control_plane_id': str(payload.get('control_plane_id') or os.getenv('OPENMIURA_CONTROL_PLANE_ID') or socket.gethostname()).strip() or 'control-plane',
            'reconcile_on_read': bool(payload.get('reconcile_on_read', False)),
            'append_authority': str(payload.get('append_authority') or 'any').strip().lower() or 'any',
            'leader_control_plane_id': str(payload.get('leader_control_plane_id') or os.getenv('OPENMIURA_CUSTODY_LEADER_CONTROL_PLANE_ID') or '').strip(),
            'quorum_enabled': bool(payload.get('quorum_enabled', False)),
            'quorum_size': max(1, int(payload.get('quorum_size') or 1)),
            'require_quorum_for_reconciliation': bool(payload.get('require_quorum_for_reconciliation', False)),
            'allow_witness_attestations': bool(payload.get('allow_witness_attestations', True)),
            'authority_hint': str(payload.get('authority_hint') or '').strip().lower() or None,
            'required_witness_count': max(0, int(payload.get('required_witness_count') or 0)),
            'required_witness_control_planes': [str(item).strip() for item in list(payload.get('required_witness_control_planes') or []) if str(item).strip()],
            'environment_policies': environment_policies,
        }


    @staticmethod
    def _normalize_portfolio_security_gate_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        required_approval_roles: list[str] = []
        for item in list(payload.get('required_approval_roles') or []):
            role = str(item or '').strip()
            if role and role not in required_approval_roles:
                required_approval_roles.append(role)
        return {
            'enabled': bool(payload.get('enabled', False)),
            'envelope_label': str(payload.get('envelope_label') or payload.get('label') or '').strip() or None,
            'require_provider_validation': bool(payload.get('require_provider_validation', False)),
            'require_valid_provider_validation': bool(payload.get('require_valid_provider_validation', True)),
            'require_crypto_signed_evidence': bool(payload.get('require_crypto_signed_evidence', False)),
            'require_immutable_escrow': bool(payload.get('require_immutable_escrow', False)),
            'require_external_signing': bool(payload.get('require_external_signing', False)),
            'require_chain_of_custody': bool(payload.get('require_chain_of_custody', False)),
            'require_valid_chain_of_custody': bool(payload.get('require_valid_chain_of_custody', True)),
            'require_custody_anchor': bool(payload.get('require_custody_anchor', False)),
            'require_custody_anchor_reconciled': bool(payload.get('require_custody_anchor_reconciled', False)),
            'require_custody_anchor_quorum': bool(payload.get('require_custody_anchor_quorum', False)),
            'require_read_verification_valid': bool(payload.get('require_read_verification_valid', False)),
            'min_approval_layers': max(0, int(payload.get('min_approval_layers') or 0)),
            'required_approval_roles': required_approval_roles,
            'block_on_nonconformance': bool(payload.get('block_on_nonconformance', True)),
            'enforce_before_sensitive_export': bool(payload.get('enforce_before_sensitive_export', False)),
            'enforce_before_sensitive_restore': bool(payload.get('enforce_before_sensitive_restore', False)),
            'enforce_before_approval_finalize': bool(payload.get('enforce_before_approval_finalize', False)),
        }


    @staticmethod
    def _normalize_portfolio_verification_gate_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        default_read_paths = [
            'detail',
            'list_item',
            'calendar',
            'approvals',
            'attestations',
            'evidence_packages',
            'chain_of_custody',
            'custody_anchors',
            'policy_conformance',
            'policy_baseline_drift',
            'deviation_exceptions',
        ]
        critical_read_paths: list[str] = []
        raw_paths = payload.get('critical_read_paths')
        if raw_paths is None:
            raw_paths = payload.get('verify_on_read_paths')
        if raw_paths is None:
            critical_read_paths = list(default_read_paths)
        else:
            for item in list(raw_paths or []):
                text = str(item or '').strip().lower()
                if not text or text in critical_read_paths:
                    continue
                critical_read_paths.append(text)
            if not critical_read_paths:
                critical_read_paths = list(default_read_paths)
        return {
            'enabled': bool(payload.get('enabled', False)),
            'require_before_sensitive_export': bool(payload.get('require_before_sensitive_export', False)),
            'require_before_sensitive_restore': bool(payload.get('require_before_sensitive_restore', True)),
            'require_chain_reconciliation': bool(payload.get('require_chain_reconciliation', True)),
            'require_external_anchor_validation': bool(payload.get('require_external_anchor_validation', True)),
            'require_verified_artifact_for_restore': bool(payload.get('require_verified_artifact_for_restore', True)),
            'block_on_reconciliation_conflict': bool(payload.get('block_on_reconciliation_conflict', True)),
            'require_live_provider_validation': bool(payload.get('require_live_provider_validation', False)),
            'require_quorum_or_authority': bool(payload.get('require_quorum_or_authority', False)),
            'require_verify_on_read': bool(payload.get('require_verify_on_read', False)),
            'block_on_failed_verify_on_read': bool(payload.get('block_on_failed_verify_on_read', True)),
            'verify_on_read_latest_only': bool(payload.get('verify_on_read_latest_only', True)),
            'persist_verify_on_read': bool(payload.get('persist_verify_on_read', True)),
            'critical_read_paths': critical_read_paths,
        }


    @staticmethod
    def _normalize_portfolio_environment_name(environment: str | None) -> str:
        env = str(environment or '').strip().lower()
        aliases = {
            'development': 'dev',
            'devel': 'dev',
            'test': 'dev',
            'testing': 'dev',
            'staging': 'stage',
            'preprod': 'stage',
            'pre-prod': 'stage',
            'uat': 'stage',
            'production': 'prod',
        }
        return aliases.get(env, env)


    @classmethod
    def _default_portfolio_evidence_classification(cls, environment: str | None) -> str:
        env = cls._normalize_portfolio_environment_name(environment)
        if env == 'prod':
            return 'regulated-evidence'
        if env == 'stage':
            return 'controlled-preprod-evidence'
        if env == 'dev':
            return 'internal-dev-evidence'
        return 'internal-sensitive'


    def _normalize_portfolio_environment_tier_policies(self, raw_policies: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policies or {})
        normalized: dict[str, Any] = {}
        for env_name, env_payload in payload.items():
            env_key = self._normalize_portfolio_environment_name(env_name)
            if not env_key:
                continue
            entry = dict(env_payload or {})
            operational_tier = str(entry.get('operational_tier') or self._default_portfolio_operational_tier(env_key)).strip() or self._default_portfolio_operational_tier(env_key)
            evidence_classification = str(entry.get('evidence_classification') or entry.get('classification') or self._default_portfolio_evidence_classification(env_key)).strip() or self._default_portfolio_evidence_classification(env_key)
            normalized[env_key] = {
                'environment': env_key,
                'tier_label': str(entry.get('tier_label') or operational_tier).strip() or operational_tier,
                'operational_tier': operational_tier,
                'evidence_classification': evidence_classification,
                'approval_policy': self._normalize_portfolio_approval_policy(dict(entry.get('approval_policy') or {})),
                'security_gate_policy': self._normalize_portfolio_security_gate_policy(dict(entry.get('security_gate_policy') or entry.get('security_envelope') or {})),
                'escrow_policy': self._normalize_portfolio_escrow_policy(dict(entry.get('escrow_policy') or {})),
                'signing_policy': self._normalize_portfolio_signing_policy(dict(entry.get('signing_policy') or {})),
                'verification_gate_policy': self._normalize_portfolio_verification_gate_policy(dict(entry.get('verification_gate_policy') or {})),
            }
        return normalized


    def _normalize_portfolio_environment_policy_baselines(self, raw_policies: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policies or {})
        normalized: dict[str, Any] = {}
        for env_name, env_payload in payload.items():
            env_key = self._normalize_portfolio_environment_name(env_name)
            if not env_key:
                continue
            entry = dict(env_payload or {})
            operational_tier = str(entry.get('operational_tier') or self._default_portfolio_operational_tier(env_key)).strip() or self._default_portfolio_operational_tier(env_key)
            evidence_classification = str(entry.get('evidence_classification') or entry.get('classification') or self._default_portfolio_evidence_classification(env_key)).strip() or self._default_portfolio_evidence_classification(env_key)
            normalized[env_key] = {
                'environment': env_key,
                'baseline_label': str(entry.get('baseline_label') or entry.get('label') or f'{env_key}-baseline').strip() or f'{env_key}-baseline',
                'operational_tier': operational_tier,
                'evidence_classification': evidence_classification,
                'approval_policy': self._normalize_portfolio_approval_policy(dict(entry.get('approval_policy') or {})),
                'security_gate_policy': self._normalize_portfolio_security_gate_policy(dict(entry.get('security_gate_policy') or entry.get('security_envelope') or {})),
                'escrow_policy': self._normalize_portfolio_escrow_policy(dict(entry.get('escrow_policy') or {})),
                'signing_policy': self._normalize_portfolio_signing_policy(dict(entry.get('signing_policy') or {})),
                'verification_gate_policy': self._normalize_portfolio_verification_gate_policy(dict(entry.get('verification_gate_policy') or {})),
            }
        return normalized


    @staticmethod
    def _normalize_portfolio_deviation_management_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        try:
            default_ttl_s = int(payload.get('default_ttl_s') if payload.get('default_ttl_s') is not None else payload.get('ttl_s') or 7 * 24 * 3600)
        except Exception:
            default_ttl_s = 7 * 24 * 3600
        try:
            max_ttl_s = int(payload.get('max_ttl_s') if payload.get('max_ttl_s') is not None else payload.get('max_exception_ttl_s') or default_ttl_s)
        except Exception:
            max_ttl_s = default_ttl_s
        try:
            max_active = int(payload.get('max_active_exceptions') or 25)
        except Exception:
            max_active = 25
        return {
            'enabled': bool(payload.get('enabled', True)),
            'require_approval': bool(payload.get('require_approval', True)),
            'requested_role': str(payload.get('requested_role') or payload.get('approval_role') or 'security-governance').strip() or 'security-governance',
            'default_ttl_s': max(60, default_ttl_s),
            'max_ttl_s': max(max(60, default_ttl_s), max_ttl_s),
            'auto_expire': bool(payload.get('auto_expire', True)),
            'block_on_unapproved': bool(payload.get('block_on_unapproved', True)),
            'block_on_expired': bool(payload.get('block_on_expired', True)),
            'block_on_missing_baseline': bool(payload.get('block_on_missing_baseline', False)),
            'persist_drift': bool(payload.get('persist_drift', True)),
            'max_active_exceptions': max(1, max_active),
        }


    @staticmethod
    def _normalize_portfolio_retention_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        try:
            retention_days = int(payload.get('retention_days') if payload.get('retention_days') is not None else 180)
        except Exception:
            retention_days = 180
        try:
            max_packages = int(payload.get('max_packages') or 25)
        except Exception:
            max_packages = 25
        return {
            'enabled': bool(payload.get('enabled', True)),
            'classification': str(payload.get('classification') or 'internal-sensitive').strip() or 'internal-sensitive',
            'retention_days': max(0, retention_days),
            'max_packages': max(1, max_packages),
            'legal_hold': bool(payload.get('legal_hold', False)),
            'prune_on_export': bool(payload.get('prune_on_export', True)),
            'purge_expired': bool(payload.get('purge_expired', True)),
        }


    def _normalize_portfolio_train_policy(self, train_policy: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(train_policy or {})
        spacing_s = max(0, int(payload.get('spacing_s') or 0))
        default_event_window_s = max(1, int(payload.get('default_event_window_s') or payload.get('window_s') or spacing_s or 60))
        reschedule_buffer_s = max(1, int(payload.get('reschedule_buffer_s') or spacing_s or 60))
        freeze_windows = self._normalize_portfolio_freeze_windows(list(payload.get('freeze_windows') or []))
        freeze_windows.extend(self._normalize_portfolio_freeze_windows(list(payload.get('blackout_windows') or [])))
        return {
            'base_release_at': float(payload.get('base_release_at')) if payload.get('base_release_at') is not None else None,
            'spacing_s': spacing_s,
            'default_event_window_s': default_event_window_s,
            'auto_reschedule': bool(payload.get('auto_reschedule', False)),
            'reschedule_buffer_s': reschedule_buffer_s,
            'strict_conflict_check': bool(payload.get('strict_conflict_check', False)),
            'default_timezone': str(payload.get('default_timezone') or 'UTC').strip() or 'UTC',
            'rollout_timezone': str(payload.get('rollout_timezone') or payload.get('timezone') or '').strip() or None,
            'freeze_windows': freeze_windows,
            'dependency_graph': self._normalize_portfolio_dependency_graph(payload.get('dependency_graph') or payload.get('dependencies')),
            'approval_policy': self._normalize_portfolio_approval_policy(dict(payload.get('approval_policy') or {})),
            'security_gate_policy': self._normalize_portfolio_security_gate_policy(dict(payload.get('security_gate_policy') or payload.get('security_envelope_policy') or {})),
            'drift_policy': self._normalize_portfolio_drift_policy(dict(payload.get('drift_policy') or {})),
            'export_policy': self._normalize_portfolio_export_policy(dict(payload.get('export_policy') or {})),
            'notarization_policy': self._normalize_portfolio_notarization_policy(dict(payload.get('notarization_policy') or {})),
            'retention_policy': self._normalize_portfolio_retention_policy(dict(payload.get('retention_policy') or {})),
            'escrow_policy': self._normalize_portfolio_escrow_policy(dict(payload.get('escrow_policy') or {})),
            'signing_policy': self._normalize_portfolio_signing_policy(dict(payload.get('signing_policy') or {})),
            'chain_of_custody_policy': self._normalize_portfolio_chain_of_custody_policy(dict(payload.get('chain_of_custody_policy') or {})),
            'custody_anchor_policy': self._normalize_portfolio_custody_anchor_policy(dict(payload.get('custody_anchor_policy') or {})),
            'verification_gate_policy': self._normalize_portfolio_verification_gate_policy(dict(payload.get('verification_gate_policy') or {})),
            'environment_tier_policies': self._normalize_portfolio_environment_tier_policies(dict(payload.get('environment_tier_policies') or payload.get('environment_envelopes') or payload.get('environment_security_envelopes') or payload.get('environment_evidence_policies') or payload.get('tier_policies') or {})),
            'environment_policy_baselines': self._normalize_portfolio_environment_policy_baselines(dict(payload.get('environment_policy_baselines') or payload.get('policy_baselines') or payload.get('environment_baselines') or {})),
            'baseline_catalog_ref': self._normalize_portfolio_baseline_catalog_ref(dict(payload.get('baseline_catalog_ref') or payload.get('baseline_catalog_reference') or payload.get('baseline_catalog') or {})),
            'baseline_catalog_overrides': self._normalize_portfolio_environment_policy_baselines(dict(payload.get('baseline_catalog_overrides') or payload.get('baseline_overrides') or {})),
            'deviation_management_policy': self._normalize_portfolio_deviation_management_policy(dict(payload.get('deviation_management_policy') or payload.get('deviation_policy') or {})),
        }


    def _normalize_release_train_calendar(
        self,
        *,
        portfolio_id: str,
        bundle_ids: list[str],
        train_calendar: list[dict[str, Any]] | None = None,
        base_release_at: float | None = None,
        spacing_s: int | None = None,
        default_window_s: int | None = None,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        raw_events = list(train_calendar or [])
        default_window = max(0, int(default_window_s or 0))
        if not raw_events:
            next_at = float(base_release_at) if base_release_at is not None else None
            step = int(spacing_s or 0)
            order_no = 1
            for bundle_id in bundle_ids:
                events.append({
                    'event_id': self._portfolio_event_id(portfolio_id, bundle_id, 1, order_no),
                    'order_no': order_no,
                    'bundle_id': str(bundle_id or '').strip(),
                    'wave_no': 1,
                    'label': f'Bundle {order_no}',
                    'planned_at': next_at,
                    'window_s': default_window,
                    'status': 'planned',
                    'train': {},
                })
                if next_at is not None and step > 0:
                    next_at += step
                order_no += 1
            return events
        seen: set[str] = set()
        order_no = 1
        for item in raw_events:
            bundle_id = str(item.get('bundle_id') or '').strip()
            if not bundle_id or bundle_id not in bundle_ids:
                continue
            wave_no = max(1, int(item.get('wave_no') or 1))
            event_id = str(item.get('event_id') or self._portfolio_event_id(portfolio_id, bundle_id, wave_no, order_no)).strip()
            if event_id in seen:
                continue
            seen.add(event_id)
            planned_at = item.get('planned_at')
            try:
                normalized_planned_at = float(planned_at) if planned_at is not None else None
            except Exception:
                normalized_planned_at = None
            events.append({
                'event_id': event_id,
                'order_no': int(item.get('order_no') or order_no),
                'bundle_id': bundle_id,
                'wave_no': wave_no,
                'label': str(item.get('label') or f'{bundle_id} wave {wave_no}'),
                'planned_at': normalized_planned_at,
                'window_s': max(0, int(item.get('window_s') or default_window)),
                'status': str(item.get('status') or 'planned'),
                'train': dict(item.get('train') or {}),
                'validation': dict(item.get('validation') or {}),
            })
            order_no += 1
        events.sort(key=lambda x: (int(x.get('order_no') or 0), float(x.get('planned_at') or 0.0), str(x.get('event_id') or '')))
        return events
