"""scheduler._policy_mixin

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


class _OpenClawRecoverySchedulerServicePolicyMixin:
    """Sub-mixin: policy."""

    @staticmethod
    def _scheduler_policy(item: dict[str, Any] | None) -> dict[str, Any]:
        return scheduler_policy(item)

    @staticmethod
    def _policy_diff_view(baseline: dict[str, Any] | None, candidate: dict[str, Any] | None) -> dict[str, Any]:
        before = dict(baseline or {})
        after = dict(candidate or {})
        keys = sorted(set(before.keys()) | set(after.keys()))
        changed_keys = [key for key in keys if before.get(key) != after.get(key)]
        return {
            'changed': bool(changed_keys),
            'changed_keys': changed_keys,
            'baseline_signature': json.dumps(before, sort_keys=True, ensure_ascii=False),
            'candidate_signature': json.dumps(after, sort_keys=True, ensure_ascii=False),
        }

    @staticmethod
    def _azure_blob_service_client_for_policy(escrow_policy: dict[str, Any] | None = None):
        policy = dict(escrow_policy or {})
        blob_mod = importlib.import_module('azure.storage.blob')
        connection_string = str(policy.get('azure_blob_connection_string') or '').strip()
        if connection_string and hasattr(blob_mod.BlobServiceClient, 'from_connection_string'):
            return blob_mod.BlobServiceClient.from_connection_string(connection_string)
        account_url = str(policy.get('azure_blob_account_url') or '').strip()
        if not account_url:
            raise RuntimeError('azure_blob_account_url_missing')
        credential = policy.get('azure_blob_credential')
        return blob_mod.BlobServiceClient(account_url=account_url, credential=credential)

    @staticmethod
    def _gcs_client_for_policy(escrow_policy: dict[str, Any] | None = None):
        policy = dict(escrow_policy or {})
        storage_mod = importlib.import_module('google.cloud.storage')
        credentials_path = str(policy.get('gcs_credentials_path') or '').strip()
        project = str(policy.get('gcs_project') or '').strip() or None
        if credentials_path and hasattr(storage_mod.Client, 'from_service_account_json'):
            return storage_mod.Client.from_service_account_json(credentials_path, project=project)
        return storage_mod.Client(project=project)

    @staticmethod
    def _aws_s3_client_for_policy(escrow_policy: dict[str, Any] | None = None):
        policy = dict(escrow_policy or {})
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
        return session.client('s3', **client_kwargs)

