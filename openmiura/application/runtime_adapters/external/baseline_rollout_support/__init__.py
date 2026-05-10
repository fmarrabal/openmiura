"""``OpenClawBaselineRolloutSupportMixin`` aggregates a set of
sub-mixins, one per bounded sub-domain.

The original implementation was a single 7,961-line module.
After this split, ``__init__.py`` keeps the public class as a
thin shell that inherits from every sub-mixin and re-exports the
class name unchanged.

External callers (currently
``openmiura.application.runtime_adapters.external.scheduler``)
continue to ``from .baseline_rollout_support import
OpenClawBaselineRolloutSupportMixin``.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from ._alerts_a_mixin import _OpenClawBaselineRolloutSupportAlertsAMixin
from ._alerts_b_mixin import _OpenClawBaselineRolloutSupportAlertsBMixin
from ._core_mixin import _OpenClawBaselineRolloutSupportCoreMixin
from ._custody_mixin import _OpenClawBaselineRolloutSupportCustodyMixin
from ._evidence_mixin import _OpenClawBaselineRolloutSupportEvidenceMixin
from ._monitoring_a_mixin import _OpenClawBaselineRolloutSupportMonitoringAMixin
from ._monitoring_b_mixin import _OpenClawBaselineRolloutSupportMonitoringBMixin
from ._policy_overrides_mixin import _OpenClawBaselineRolloutSupportPolicyOverridesMixin
from ._rollout_plan_mixin import _OpenClawBaselineRolloutSupportRolloutPlanMixin


class OpenClawBaselineRolloutSupportMixin(
    _OpenClawBaselineRolloutSupportAlertsAMixin,
    _OpenClawBaselineRolloutSupportAlertsBMixin,
    _OpenClawBaselineRolloutSupportCoreMixin,
    _OpenClawBaselineRolloutSupportCustodyMixin,
    _OpenClawBaselineRolloutSupportEvidenceMixin,
    _OpenClawBaselineRolloutSupportMonitoringAMixin,
    _OpenClawBaselineRolloutSupportMonitoringBMixin,
    _OpenClawBaselineRolloutSupportPolicyOverridesMixin,
    _OpenClawBaselineRolloutSupportRolloutPlanMixin
):
    """Aggregating mixin re-exposing the original class surface."""

    pass


from openmiura.application.runtime_adapters.external.baseline_rollout_support import _alerts_a_mixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _alerts_b_mixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _core_mixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _custody_mixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _evidence_mixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _monitoring_a_mixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _monitoring_b_mixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _policy_overrides_mixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _rollout_plan_mixin

# Late-bind OpenClawBaselineRolloutSupportMixin into each sub-mixin
# module so the few ``@staticmethod``s that reference the class
# name resolve at call time.
for _mod in (
    _alerts_a_mixin,
    _alerts_b_mixin,
    _core_mixin,
    _custody_mixin,
    _evidence_mixin,
    _monitoring_a_mixin,
    _monitoring_b_mixin,
    _policy_overrides_mixin,
    _rollout_plan_mixin
):
    _mod.OpenClawBaselineRolloutSupportMixin = OpenClawBaselineRolloutSupportMixin
del _mod
