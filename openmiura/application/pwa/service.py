from __future__ import annotations

import hashlib
import time
from typing import Any

from openmiura.core.contracts import AdminGatewayLike


class PWAFoundationService:
    def _sanitize_scope(self, gw: AdminGatewayLike, *, tenant_id: str | None, workspace_id: str | None, environment: str | None) -> dict[str, Any]:
        tenancy = getattr(gw, 'tenancy', None)
        if tenancy is not None and hasattr(tenancy, 'normalize_scope'):
            try:
                return tenancy.normalize_scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
            except Exception:
                pass
        return {
            'tenant_id': tenant_id,
            'workspace_id': workspace_id,
            'environment': environment,
        }

    def list_installations(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items = gw.audit.list_app_installations(limit=limit, status=status, **scope)
        return {'ok': True, 'items': items, 'scope': scope}

    def register_installation(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        user_key: str,
        platform: str = 'pwa',
        device_label: str = '',
        push_capable: bool = False,
        notification_permission: str = 'default',
        deep_link_base: str = '/ui/',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        installation = gw.audit.register_app_installation(
            user_key=user_key,
            platform=platform,
            device_label=device_label,
            status='active',
            push_capable=push_capable,
            notification_permission=notification_permission,
            deep_link_base=deep_link_base,
            metadata={**(metadata or {}), 'registered_by': actor},
            **scope,
        )
        gw.audit.log_event('admin', 'pwa', actor or user_key or 'operator', installation['installation_id'], {
            'action': 'app_installation_registered',
            'platform': platform,
            'push_capable': push_capable,
            **scope,
        })
        return {'ok': True, 'installation': installation, 'scope': scope}

    def list_notifications(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        installation_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items = gw.audit.list_app_notifications(limit=limit, installation_id=installation_id, **scope)
        return {'ok': True, 'items': items, 'scope': scope}

    def create_notification(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        title: str,
        body: str,
        category: str = 'operator',
        installation_id: str | None = None,
        target_path: str = '/ui/?tab=operator',
        require_interaction: bool = False,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        notification = gw.audit.create_app_notification(
            installation_id=installation_id,
            category=category,
            title=title,
            body=body,
            target_path=target_path,
            status='ready',
            created_by=actor,
            metadata={**(metadata or {}), 'require_interaction': bool(require_interaction)},
            **scope,
        )
        gw.audit.log_event('admin', 'pwa', actor or 'operator', notification['notification_id'], {
            'action': 'app_notification_created',
            'category': category,
            'target_path': target_path,
            **scope,
        })
        return {'ok': True, 'notification': notification, 'scope': scope}

    def list_deep_links(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items = gw.audit.list_app_deep_links(limit=limit, status=status, **scope)
        return {'ok': True, 'items': items, 'scope': scope}

    def create_deep_link(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        view: str,
        target_type: str,
        target_id: str,
        params: dict[str, Any] | None = None,
        expires_in_s: int = 3600,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        expires_in_s = max(60, int(expires_in_s or 3600))
        target_params = dict(params or {})
        target_params.setdefault('tab', view)
        target_params.setdefault('view', view)
        target_params.setdefault('target_type', target_type)
        target_params.setdefault('target_id', target_id)
        target_params.setdefault('tenant_id', scope.get('tenant_id'))
        target_params.setdefault('workspace_id', scope.get('workspace_id'))
        target_params.setdefault('environment', scope.get('environment'))
        fingerprint = hashlib.sha256(f"{view}|{target_type}|{target_id}|{sorted(target_params.items())}".encode('utf-8')).hexdigest()[:16]
        deep_link = gw.audit.create_app_deep_link(
            view=view,
            target_type=target_type,
            target_id=target_id,
            target_params=target_params,
            status='active',
            created_by=actor,
            expires_at=time.time() + expires_in_s,
            metadata={'fingerprint': fingerprint},
            **scope,
        )
        deep_link['url'] = f"/app/deep-links/{deep_link['link_token']}"
        gw.audit.log_event('admin', 'pwa', actor or 'operator', deep_link['link_token'], {
            'action': 'app_deep_link_created',
            'view': view,
            'target_type': target_type,
            'target_id': target_id,
            **scope,
        })
        return {'ok': True, 'deep_link': deep_link, 'scope': scope}

    def resolve_deep_link(self, gw: AdminGatewayLike, *, link_token: str) -> dict[str, Any]:
        deep_link = gw.audit.resolve_app_deep_link(link_token)
        if deep_link is None:
            return {'ok': False, 'reason': 'not_found'}
        if deep_link.get('status') == 'expired':
            return {'ok': False, 'reason': 'expired', 'deep_link': deep_link}
        params = dict(deep_link.get('target_params') or {})
        ordered_items = []
        for key in ('tab', 'view', 'target_type', 'target_id', 'tenant_id', 'workspace_id', 'environment'):
            value = params.pop(key, None)
            if value not in (None, ''):
                ordered_items.append((key, str(value)))
        for key, value in params.items():
            if value not in (None, ''):
                ordered_items.append((key, str(value)))
        query = '&'.join(f"{k}={v}" for k, v in ordered_items)
        ui_path = '/ui/'
        if query:
            ui_path += '?' + query
        return {'ok': True, 'deep_link': deep_link, 'ui_path': ui_path}
