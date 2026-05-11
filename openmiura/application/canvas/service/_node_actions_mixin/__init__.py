"""``_LiveCanvasNodeActionsMixin`` aggregator over the node-action sub-mixins.

The original single-file ``_node_actions_mixin.py`` (3,931 lines) was
split into a sub-package after refactoring ``execute_node_action`` from
a single 2,957-line method into:

- 4 outer-type handlers (``_execute_workflow_action``,
  ``_execute_approval_action``, ``_execute_runtime_action``,
  ``_execute_baseline_promotion_action``).
- 19 inner ``_baseline_promotion_action_<slug>`` sub-handlers.

The sub-package layout:

- ``_dispatch_mixin.py`` — ``execute_node_action`` + 4 outer handlers
  + ``_node_action_precheck``.
- ``_baseline_promotion_a_mixin.py`` — first chunk of baseline_promotion
  sub-handlers.
- ``_baseline_promotion_b_mixin.py`` — middle chunk.
- ``_baseline_promotion_c_mixin.py`` — last chunk.

The public class ``_LiveCanvasNodeActionsMixin`` keeps the same name and
the same combined method surface; ``canvas/service/__init__.py`` imports
it unchanged.
"""

from __future__ import annotations

from . import _baseline_promotion_a_mixin as _bp_a
from . import _baseline_promotion_b_mixin as _bp_b
from . import _baseline_promotion_c_mixin as _bp_c
from . import _dispatch_mixin as _dispatch
from ._dispatch_mixin import _LiveCanvasNodeActionsMixinDispatch
from ._baseline_promotion_a_mixin import _LiveCanvasNodeActionsMixinBaselinePromotionA
from ._baseline_promotion_b_mixin import _LiveCanvasNodeActionsMixinBaselinePromotionB
from ._baseline_promotion_c_mixin import _LiveCanvasNodeActionsMixinBaselinePromotionC


class _LiveCanvasNodeActionsMixin(
    _LiveCanvasNodeActionsMixinDispatch,
    _LiveCanvasNodeActionsMixinBaselinePromotionA,
    _LiveCanvasNodeActionsMixinBaselinePromotionB,
    _LiveCanvasNodeActionsMixinBaselinePromotionC,
):
    """Aggregating mixin preserving the original surface."""

    pass


# Propagate the late-bound ``LiveCanvasService`` symbol to every
# sub-mixin module. When ``canvas/service/__init__.py`` rebinds
# ``_node_actions_mixin.LiveCanvasService = LiveCanvasService``, this
# package-level descriptor pushes the same value down into the four
# sub-modules so the ``@staticmethod`` call sites that reference the
# class by name resolve correctly at call time.

_SUBMODULES = (_dispatch, _bp_a, _bp_b, _bp_c)


def __getattr__(name: str):
    if name == "LiveCanvasService":
        return _dispatch.LiveCanvasService
    raise AttributeError(name)


_module_setattr = type(_dispatch).__setattr__  # plain object.__setattr__ for ModuleType


def _propagating_setattr(_target_mod, _name, _value):
    object.__setattr__(_target_mod, _name, _value)
    if _name == "LiveCanvasService":
        for _sub in _SUBMODULES:
            _sub.LiveCanvasService = _value


import sys as _sys
_self_module = _sys.modules[__name__]


class _PackageProxy(type(_self_module)):
    def __setattr__(self, name, value):
        _propagating_setattr(self, name, value)


_self_module.__class__ = _PackageProxy
