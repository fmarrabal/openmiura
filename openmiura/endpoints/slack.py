"""Legacy compatibility shim for Slack HTTP routes.

Canonical implementation now lives under ``openmiura.interfaces.channels.slack``.
"""

from openmiura.interfaces.channels.slack.routes import router, slack_events
from openmiura.interfaces.channels.slack.translator import normalize_slack_text, slack_chunks
from openmiura.pipeline import process_message

__all__ = ["router", "slack_events", "normalize_slack_text", "slack_chunks", "process_message"]
