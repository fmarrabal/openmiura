from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .runtime import Tool


class TimeNowTool(Tool):
    name = "time_now"
    description = "Return current local date/time (Europe/Madrid)."
    parameters_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def run(self, ctx, **kwargs) -> str:
        tz = ZoneInfo("Europe/Madrid")
        now = datetime.now(tz)
        return now.isoformat()
