"""``OpenClawEvidenceBuildersMixin`` aggregator."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any






from ._archive_mixin import _OpenClawEvidenceBuildersMixinArchiveMixin
from ._build_mixin import _OpenClawEvidenceBuildersMixinBuildMixin
from ._core_mixin import _OpenClawEvidenceBuildersMixinCoreMixin
from ._prune_mixin import _OpenClawEvidenceBuildersMixinPruneMixin
from ._verify_mixin import _OpenClawEvidenceBuildersMixinVerifyMixin


class OpenClawEvidenceBuildersMixin(
    _OpenClawEvidenceBuildersMixinArchiveMixin,
    _OpenClawEvidenceBuildersMixinBuildMixin,
    _OpenClawEvidenceBuildersMixinCoreMixin,
    _OpenClawEvidenceBuildersMixinPruneMixin,
    _OpenClawEvidenceBuildersMixinVerifyMixin,
):
    pass


from openmiura.application.runtime_adapters.external.evidence_builders import _archive_mixin
from openmiura.application.runtime_adapters.external.evidence_builders import _build_mixin
from openmiura.application.runtime_adapters.external.evidence_builders import _core_mixin
from openmiura.application.runtime_adapters.external.evidence_builders import _prune_mixin
from openmiura.application.runtime_adapters.external.evidence_builders import _verify_mixin
for _mod in (
    _archive_mixin,
    _build_mixin,
    _core_mixin,
    _prune_mixin,
    _verify_mixin,
):
    _mod.OpenClawEvidenceBuildersMixin = OpenClawEvidenceBuildersMixin
del _mod
