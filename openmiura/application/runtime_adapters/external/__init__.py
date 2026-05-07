"""External agent runtime adapter (legacy module name: ``openclaw``).

The internal class identifiers ``OpenClawAdapterService`` and
``OpenClawRecoverySchedulerService`` are kept for backwards
compatibility with persisted state and database identifiers and will
be renamed in a future controlled migration.
"""

from .service import OpenClawAdapterService
from .scheduler import OpenClawRecoverySchedulerService

__all__ = ["OpenClawAdapterService", "OpenClawRecoverySchedulerService"]
