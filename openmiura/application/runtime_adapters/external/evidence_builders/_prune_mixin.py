"""evidence_builders._prune_mixin"""
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






OpenClawEvidenceBuildersMixin: type | None = None


class _OpenClawEvidenceBuildersMixinPruneMixin:
    """Sub-mixin: prune."""

    def _prune_portfolio_evidence_packages(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        base_train_policy = self._normalize_portfolio_train_policy(dict(portfolio.get('train_policy') or {}))
        train_policy = self._resolve_portfolio_train_policy_for_environment(base_train_policy, environment=release.get('environment'))
        retention_policy = dict(train_policy.get('retention_policy') or {})
        packages = self._list_portfolio_evidence_packages(release, include_content=True)
        resolved_now = float(now_ts) if now_ts is not None else time.time()
        keep: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for item in packages:
            retention = self._portfolio_retention_snapshot(
                created_at=float(item.get('created_at') or resolved_now),
                retention_policy=dict(item.get('retention') or retention_policy),
                now_ts=resolved_now,
            )
            enriched = dict(item)
            enriched['retention'] = retention
            if bool(retention.get('expired')) and bool(retention.get('purge_expired', True)) and not bool(retention.get('legal_hold', False)):
                removed.append(enriched)
            else:
                keep.append(enriched)
        max_packages = max(1, int(retention_policy.get('max_packages') or 25))
        if len(keep) > max_packages:
            overflow = keep[max_packages:]
            keep = keep[:max_packages]
            removed.extend(overflow)
        if len(removed) != 0:
            portfolio['evidence_packages'] = keep
            metadata['portfolio'] = portfolio
            release = gw.audit.update_release_bundle(
                str(release.get('release_id') or ''),
                status=release.get('status'),
                notes=release.get('notes'),
                metadata=metadata,
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            ) or release
            gw.audit.log_event(
                direction='system',
                channel='openclaw',
                user_id=str(actor or 'system'),
                session_id='',
                payload={
                    'event': 'openclaw_portfolio_evidence_pruned',
                    'portfolio_id': str(release.get('release_id') or ''),
                    'removed_package_ids': [item.get('package_id') for item in removed],
                    'remaining_count': len(keep),
                },
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            )
        return {
            'release': release,
            'removed': removed,
            'remaining': keep,
            'summary': {
                'removed_count': len(removed),
                'remaining_count': len(keep),
                'expired_removed_count': sum(1 for item in removed if bool(((item.get('retention') or {}).get('expired')))),
            },
        }

