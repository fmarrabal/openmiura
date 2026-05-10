"""``OpenClawRecoverySchedulerService`` aggregates the original 20 external mixins plus a new layer of sub-mixins extracted from the original 7,263-line file.
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



from ._alerts_mixin import _OpenClawRecoverySchedulerServiceAlertsMixin
from ._core_mixin import _OpenClawRecoverySchedulerServiceCoreMixin
from ._policy_mixin import _OpenClawRecoverySchedulerServicePolicyMixin
from ._portfolio_a_mixin import _OpenClawRecoverySchedulerServicePortfolioAMixin
from ._portfolio_b_mixin import _OpenClawRecoverySchedulerServicePortfolioBMixin
from ._portfolio_c_mixin import _OpenClawRecoverySchedulerServicePortfolioCMixin
from ._portfolio_d_mixin import _OpenClawRecoverySchedulerServicePortfolioDMixin
from ._recovery_jobs_mixin import _OpenClawRecoverySchedulerServiceRecoveryJobsMixin


class OpenClawRecoverySchedulerService(
    _OpenClawRecoverySchedulerServiceAlertsMixin,
    _OpenClawRecoverySchedulerServiceCoreMixin,
    _OpenClawRecoverySchedulerServicePolicyMixin,
    _OpenClawRecoverySchedulerServicePortfolioAMixin,
    _OpenClawRecoverySchedulerServicePortfolioBMixin,
    _OpenClawRecoverySchedulerServicePortfolioCMixin,
    _OpenClawRecoverySchedulerServicePortfolioDMixin,
    _OpenClawRecoverySchedulerServiceRecoveryJobsMixin,
    OpenClawRuntimeContextMixin,
    OpenClawApprovalCommonMixin,
    OpenClawGovernanceExplainabilityMixin,
    OpenClawJobFamilyCommonMixin,
    OpenClawTemporalWindowsMixin,
    OpenClawRuntimeAlertCommonMixin,
    OpenClawRuntimeAlertEscalationsMixin,
    OpenClawRuntimeAlertNotificationsMixin,
    OpenClawRuntimeAlertExecutionMixin,
    OpenClawPolicyNormalizationMixin,
    OpenClawEvidenceBuildersMixin,
    OpenClawRuntimeRolloutSummariesMixin,
    OpenClawBaselineRolloutManagementMixin,
    OpenClawBaselineRolloutSupportMixin,
    OpenClawBaselineRolloutStateMixin,
    OpenClawBaselineRolloutJobsMixin,
    OpenClawBaselineRolloutGatesMixin,
    OpenClawAlertGovernanceBundleManagementMixin,
    OpenClawAlertGovernanceBundleJobsMixin,
    OpenClawAlertGovernanceBundleGatesMixin,
):
    """Periodic scheduler/worker for stale-run reconciliation on OpenClaw runtimes."""

    JOB_KIND = 'openclaw_runtime_recovery'

    ALERT_DELIVERY_JOB_KIND = 'openclaw_alert_delivery'

    GOVERNANCE_WAVE_ADVANCE_JOB_KIND = 'openclaw_alert_governance_wave_advance'

    GOVERNANCE_RELEASE_TRAIN_JOB_KIND = 'openclaw_alert_governance_release_train'

    BASELINE_WAVE_ADVANCE_JOB_KIND = 'openclaw_alert_governance_baseline_wave_advance'

    BASELINE_SIMULATION_CUSTODY_JOB_KIND = 'openclaw_alert_governance_baseline_simulation_custody_reconciliation'

    def __init__(
        self,
        *,
        openclaw_adapter_service: OpenClawAdapterService | None = None,
        job_service: JobService | None = None,
    ) -> None:
        self.openclaw_adapter_service = openclaw_adapter_service or OpenClawAdapterService()
        self.job_service = job_service or JobService()



from openmiura.application.runtime_adapters.external.scheduler import _alerts_mixin
from openmiura.application.runtime_adapters.external.scheduler import _core_mixin
from openmiura.application.runtime_adapters.external.scheduler import _policy_mixin
from openmiura.application.runtime_adapters.external.scheduler import _portfolio_a_mixin
from openmiura.application.runtime_adapters.external.scheduler import _portfolio_b_mixin
from openmiura.application.runtime_adapters.external.scheduler import _portfolio_c_mixin
from openmiura.application.runtime_adapters.external.scheduler import _portfolio_d_mixin
from openmiura.application.runtime_adapters.external.scheduler import _recovery_jobs_mixin
for _mod in (
    _alerts_mixin,
    _core_mixin,
    _policy_mixin,
    _portfolio_a_mixin,
    _portfolio_b_mixin,
    _portfolio_c_mixin,
    _portfolio_d_mixin,
    _recovery_jobs_mixin,
):
    _mod.OpenClawRecoverySchedulerService = OpenClawRecoverySchedulerService
del _mod
