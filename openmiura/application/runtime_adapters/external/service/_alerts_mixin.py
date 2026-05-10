"""service._alerts_mixin"""
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


class _OpenClawAdapterServiceAlertsMixin:
    """Sub-mixin: alerts."""

    @classmethod
    def _alert_notification_targets(cls, runtime: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = cls._runtime_metadata(runtime)
        items = list(metadata.get('alert_notification_targets') or metadata.get('notification_targets') or [])
        out: list[dict[str, Any]] = []
        for idx, raw_item in enumerate(items):
            if not isinstance(raw_item, dict):
                continue
            target_type = str(raw_item.get('type') or raw_item.get('target_type') or '').strip().lower()
            if target_type not in {'slack', 'webhook', 'app', 'queue', 'email'}:
                continue
            target_id = str(raw_item.get('target_id') or raw_item.get('id') or f'{target_type}-{idx + 1}').strip()
            item = {
                'target_id': target_id,
                'type': target_type,
                'enabled': bool(raw_item.get('enabled', True)),
                'channel': str(raw_item.get('channel') or '').strip(),
                'thread_ts': str(raw_item.get('thread_ts') or '').strip(),
                'url': str(raw_item.get('url') or raw_item.get('webhook_url') or '').strip(),
                'headers': cls._safe_json(raw_item.get('headers') or {}),
                'installation_id': str(raw_item.get('installation_id') or '').strip(),
                'target_path': str(raw_item.get('target_path') or '').strip(),
                'queue_name': str(raw_item.get('queue_name') or raw_item.get('queue') or '').strip(),
                'email_to': str(raw_item.get('email_to') or raw_item.get('to') or '').strip(),
                'subject_prefix': str(raw_item.get('subject_prefix') or '').strip(),
                'min_escalation_level': int(raw_item.get('min_escalation_level') or 1),
                'severities': [str(item).strip().lower() for item in list(raw_item.get('severities') or []) if str(item).strip()],
                'alert_codes': [str(item).strip() for item in list(raw_item.get('alert_codes') or []) if str(item).strip()],
                'workflow_actions': [str(item).strip().lower() for item in list(raw_item.get('workflow_actions') or ['escalate']) if str(item).strip()],
                'auth_secret_ref': str(raw_item.get('auth_secret_ref') or '').strip(),
                'metadata': cls._safe_json(raw_item.get('metadata') or {}),
            }
            out.append(item)
        return out

