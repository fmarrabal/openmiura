"""Legacy compatibility shim for Telegram HTTP routes.

Canonical implementation now lives under ``openmiura.interfaces.channels.telegram``.
"""

from openmiura.interfaces.channels.telegram.routes import router, telegram_webhook
from openmiura.interfaces.channels.telegram.translator import build_telegram_inbound
from openmiura.pipeline import process_message

__all__ = ["router", "telegram_webhook", "build_telegram_inbound", "process_message"]
