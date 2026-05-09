"""``LiveCanvasService`` aggregates a set of mixins, one per bounded
sub-domain of the canvas service.

The original implementation was a single 11,519-line class file.
After the split:

- ``__init__.py`` (this file) keeps the class signature, the class
  constants and the constructor.
- Each ``_<domain>_mixin.py`` module owns the methods of one
  sub-domain.

External callers are unaffected: ``LiveCanvasService`` exposes the
same method surface, instantiated the same way, with the same
constructor parameters.

One file in this package — ``_node_actions_mixin.py`` — exceeds
the 1,500-line ceiling because the ``execute_node_action`` method
alone is ~2,957 lines. Splitting that single method requires an
internal refactor (action dispatch extraction) which is tracked as
follow-up work in a dedicated branch; mechanical file split is
done here.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from typing import Any

from openmiura.application.canvas.helpers import (
    enforce_canvas_counts as canvas_enforce_counts,
    enforce_canvas_payload as canvas_enforce_payload,
    enforce_scope_limits as canvas_enforce_scope_limits,
    normalize_toggles as canvas_normalize_toggles,
    payload_size as canvas_payload_size,
    redact_sensitive as canvas_redact_sensitive,
    safe_call as canvas_safe_call,
    sanitize_scope as canvas_sanitize_scope,
)
from openmiura.application.costs import CostGovernanceService
from openmiura.application.operator import OperatorConsoleService
from openmiura.application.packaging import PackagingHardeningService
from openmiura.application.runtime_adapters.external import (
    OpenClawAdapterService,
    OpenClawRecoverySchedulerService,
)
from openmiura.application.secrets import SecretGovernanceService
from openmiura.core.contracts import AdminGatewayLike

from ._baseline_promotion_catalog_a_mixin import _LiveCanvasBaselinePromotionCatalogAMixin
from ._baseline_promotion_catalog_b_mixin import _LiveCanvasBaselinePromotionCatalogBMixin
from ._baseline_promotion_compactors_mixin import _LiveCanvasBaselinePromotionCompactorsMixin
from ._baseline_promotion_exports_mixin import _LiveCanvasBaselinePromotionExportsMixin
from ._baseline_promotion_other_mixin import _LiveCanvasBaselinePromotionOtherMixin
from ._baseline_promotion_state_mixin import _LiveCanvasBaselinePromotionStateMixin
from ._board_mixin import _LiveCanvasBoardMixin
from ._data_mixin import _LiveCanvasDataMixin
from ._helpers_mixin import _LiveCanvasHelpersMixin
from ._node_actions_mixin import _LiveCanvasNodeActionsMixin
from ._node_data_mixin import _LiveCanvasNodeDataMixin
from ._node_inspector_mixin import _LiveCanvasNodeInspectorMixin
from ._timeline_mixin import _LiveCanvasTimelineMixin


class LiveCanvasService(
    _LiveCanvasBaselinePromotionCatalogAMixin,
    _LiveCanvasBaselinePromotionCatalogBMixin,
    _LiveCanvasBaselinePromotionCompactorsMixin,
    _LiveCanvasBaselinePromotionExportsMixin,
    _LiveCanvasBaselinePromotionOtherMixin,
    _LiveCanvasBaselinePromotionStateMixin,
    _LiveCanvasBoardMixin,
    _LiveCanvasDataMixin,
    _LiveCanvasHelpersMixin,
    _LiveCanvasNodeActionsMixin,
    _LiveCanvasNodeDataMixin,
    _LiveCanvasNodeInspectorMixin,
    _LiveCanvasTimelineMixin
):
    _CANVAS_LIMITS = PackagingHardeningService.DEFAULT_HARDENING['canvas']

    MAX_DOCUMENTS_PER_SCOPE = int(_CANVAS_LIMITS['max_documents_per_scope'])

    MAX_NODES_PER_CANVAS = int(_CANVAS_LIMITS['max_nodes_per_canvas'])

    MAX_EDGES_PER_CANVAS = int(_CANVAS_LIMITS['max_edges_per_canvas'])

    MAX_VIEWS_PER_CANVAS = int(_CANVAS_LIMITS['max_views_per_canvas'])

    MAX_PAYLOAD_CHARS = int(_CANVAS_LIMITS['max_payload_chars'])

    MAX_COMMENT_CHARS = int(_CANVAS_LIMITS['max_comment_chars'])

    MAX_SNAPSHOT_BYTES = int(_CANVAS_LIMITS['max_snapshot_bytes'])

    _DEFAULT_TOGGLES = {
        'policy': True,
        'cost': True,
        'traces': True,
        'failures': True,
        'approvals': True,
        'secrets': True,
    }

    def __init__(
        self,
        *,
        cost_governance_service: CostGovernanceService | None = None,
        operator_console_service: OperatorConsoleService | None = None,
        secret_governance_service: SecretGovernanceService | None = None,
        openclaw_adapter_service: OpenClawAdapterService | None = None,
        openclaw_recovery_scheduler_service: OpenClawRecoverySchedulerService | None = None,
    ) -> None:
        self.cost_governance_service = cost_governance_service or CostGovernanceService()
        self.operator_console_service = operator_console_service or OperatorConsoleService()
        self.secret_governance_service = secret_governance_service or SecretGovernanceService()
        self.openclaw_adapter_service = openclaw_adapter_service or OpenClawAdapterService()
        self.openclaw_recovery_scheduler_service = openclaw_recovery_scheduler_service or OpenClawRecoverySchedulerService(openclaw_adapter_service=self.openclaw_adapter_service)


# Late-bind the class name into each mixin module so the
# `@staticmethod`s that internally call `LiveCanvasService.foo(...)`
# (162 such call sites at the time of the split) can resolve the
# reference at call time without circular imports.
from openmiura.application.canvas.service import (  # noqa: E402
    _baseline_promotion_catalog_a_mixin as _m_bp_cat_a,
    _baseline_promotion_catalog_b_mixin as _m_bp_cat_b,
    _baseline_promotion_compactors_mixin as _m_bp_compactors,
    _baseline_promotion_exports_mixin as _m_bp_exports,
    _baseline_promotion_other_mixin as _m_bp_other,
    _baseline_promotion_state_mixin as _m_bp_state,
    _board_mixin as _m_board,
    _data_mixin as _m_data,
    _helpers_mixin as _m_helpers,
    _node_actions_mixin as _m_node_actions,
    _node_data_mixin as _m_node_data,
    _node_inspector_mixin as _m_node_inspector,
    _timeline_mixin as _m_timeline,
)
for _mod in (
    _m_bp_cat_a, _m_bp_cat_b, _m_bp_compactors, _m_bp_exports,
    _m_bp_other, _m_bp_state, _m_board, _m_data, _m_helpers,
    _m_node_actions, _m_node_data, _m_node_inspector, _m_timeline,
):
    _mod.LiveCanvasService = LiveCanvasService
del _mod

