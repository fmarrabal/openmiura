"""Compatibility export for the canonical audit store path.

The full implementation still lives in ``openmiura.core.audit`` while the
ongoing refactor preserves backwards compatibility. New infrastructure-facing
imports should use this module.
"""

from openmiura.core.audit import AuditStore

__all__ = ["AuditStore"]
