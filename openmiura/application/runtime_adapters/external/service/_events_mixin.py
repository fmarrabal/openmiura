"""service._events_mixin"""
from __future__ import annotations

import copy
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from openmiura.core.secrets import SecretAccessDenied, SecretBrokerError



OpenClawAdapterService: type | None = None  # late-bound


class _OpenClawAdapterServiceEventsMixin:
    """Sub-mixin: events."""

    @classmethod
    def _event_bridge(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('event_bridge') or {})
        session_bridge = cls._session_bridge(runtime)
        accepted_sources = [str(item).strip() for item in list(raw.get('accepted_sources') or metadata.get('accepted_event_sources') or ['openclaw']) if str(item).strip()]
        accepted_event_types = [str(item).strip().lower() for item in list(raw.get('accepted_event_types') or metadata.get('accepted_event_types') or []) if str(item).strip()]
        return {
            'enabled': bool(session_bridge.get('event_bridge_enabled')),
            'token_configured': bool(str(raw.get('token') or metadata.get('event_bridge_token') or '').strip()),
            'accepted_sources': accepted_sources,
            'accepted_event_types': accepted_event_types,
            'source_label': str(raw.get('source_label') or metadata.get('event_bridge_source_label') or 'openclaw').strip() or 'openclaw',
        }

    @classmethod
    def _event_bridge_token(cls, runtime: dict[str, Any]) -> str:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('event_bridge') or {})
        return str(raw.get('token') or metadata.get('event_bridge_token') or '').strip()

