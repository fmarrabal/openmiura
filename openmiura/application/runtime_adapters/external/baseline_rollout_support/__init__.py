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

from ._alerts_a_mixin import _OpenClawBaselineRolloutSupportAlertsAMixin
from ._alerts_b_mixin import _OpenClawBaselineRolloutSupportAlertsBMixin
from ._core_mixin_a import _OpenClawBaselineRolloutSupportCoreMixinA
from ._core_mixin_b import _OpenClawBaselineRolloutSupportCoreMixinB
from ._custody_mixin import _OpenClawBaselineRolloutSupportCustodyMixin
from ._evidence_mixin_a import _OpenClawBaselineRolloutSupportEvidenceMixinA
from ._evidence_mixin_b import _OpenClawBaselineRolloutSupportEvidenceMixinB
from ._monitoring_a_mixin import _OpenClawBaselineRolloutSupportMonitoringAMixin
from ._monitoring_b_mixin import _OpenClawBaselineRolloutSupportMonitoringBMixin
from ._policy_overrides_mixin import _OpenClawBaselineRolloutSupportPolicyOverridesMixin
from ._rollout_plan_mixin import _OpenClawBaselineRolloutSupportRolloutPlanMixin


class OpenClawBaselineRolloutSupportMixin(
    _OpenClawBaselineRolloutSupportAlertsAMixin,
    _OpenClawBaselineRolloutSupportAlertsBMixin,
    _OpenClawBaselineRolloutSupportCoreMixinA,
    _OpenClawBaselineRolloutSupportCoreMixinB,
    _OpenClawBaselineRolloutSupportCustodyMixin,
    _OpenClawBaselineRolloutSupportEvidenceMixinA,
    _OpenClawBaselineRolloutSupportEvidenceMixinB,
    _OpenClawBaselineRolloutSupportMonitoringAMixin,
    _OpenClawBaselineRolloutSupportMonitoringBMixin,
    _OpenClawBaselineRolloutSupportPolicyOverridesMixin,
    _OpenClawBaselineRolloutSupportRolloutPlanMixin
):
    """Aggregating mixin re-exposing the original class surface."""

    pass


from openmiura.application.runtime_adapters.external.baseline_rollout_support import _alerts_a_mixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _alerts_b_mixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _core_mixin_a
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _core_mixin_b
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _custody_mixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _evidence_mixin_a
from openmiura.application.runtime_adapters.external.baseline_rollout_support import _evidence_mixin_b
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
    _core_mixin_a,
    _core_mixin_b,
    _custody_mixin,
    _evidence_mixin_a,
    _evidence_mixin_b,
    _monitoring_a_mixin,
    _monitoring_b_mixin,
    _policy_overrides_mixin,
    _rollout_plan_mixin
):
    _mod.OpenClawBaselineRolloutSupportMixin = OpenClawBaselineRolloutSupportMixin
del _mod
