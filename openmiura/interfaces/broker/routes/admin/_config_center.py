"""admin/_config_center.py - broker admin sub-routes for the config_center domain."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from openmiura.application.admin import AdminService
from openmiura.application.auth.service import AuthService
from openmiura.application.tenancy.service import TenancyService
from openmiura.interfaces.broker.common import (
    audit_sensitive,
    metrics_summary,
    require_csrf,
    require_permission,
)




def register_routes(router, tenancy_service) -> None:
    """Attach the config_center broker admin endpoints to *router*."""
    @router.get("/admin/config-center")
    def broker_admin_config_center(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().config_center_snapshot(gw)
        audit_sensitive(gw, action="admin_config_center_read", auth_ctx=auth_ctx, status="ok", details={"sections": [item.get("name") for item in response.get("sections", [])]})
        return response

    @router.post("/admin/config-center/validate")
    async def broker_admin_config_center_validate(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        try:
            response = AdminService().validate_config_content(
                gw,
                section=str(payload.get("section") or ""),
                content=str(payload.get("content") or ""),
                form_payload=payload.get("form_payload") if isinstance(payload.get("form_payload"), dict) else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_config_center_validate", auth_ctx=auth_ctx, status="ok", details={"section": payload.get("section")})
        return response

    @router.post("/admin/config-center/save")
    async def broker_admin_config_center_save(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().save_config_content(
                gw,
                section=str(payload.get("section") or ""),
                content=str(payload.get("content") or ""),
                reload_after_save=bool(payload.get("reload_after_save", False)),
                actor=str(payload.get("actor") or auth_ctx.get("username") or auth_ctx.get("user_key") or "broker-admin"),
                form_payload=payload.get("form_payload") if isinstance(payload.get("form_payload"), dict) else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_config_center_save", auth_ctx=auth_ctx, status="ok", details={"section": payload.get("section"), "reload_applied": response.get("reload_applied"), "restart_required": response.get("restart_required")})
        return response

    @router.get("/admin/config-center/reload-assistant")
    def broker_admin_config_center_reload_assistant(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().reload_assistant_snapshot(gw)
        audit_sensitive(gw, action="admin_config_center_reload_assistant_read", auth_ctx=auth_ctx, status="ok", details={"sections": [item.get("name") for item in response.get("sections", [])], "hook_configured": (response.get("restart_hook") or {}).get("configured")})
        return response

    @router.post("/admin/config-center/reload-assistant/apply")
    async def broker_admin_config_center_reload_assistant_apply(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().apply_reload_assistant(
                gw,
                sections=list(payload.get("sections") or []),
                apply_live_reload=bool(payload.get("apply_live_reload", False)),
                request_restart=bool(payload.get("request_restart", False)),
                execute_restart_hook=bool(payload.get("execute_restart_hook", False)),
                actor=str(payload.get("actor") or auth_ctx.get("username") or auth_ctx.get("user_key") or "broker-admin"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_config_center_reload_assistant_apply", auth_ctx=auth_ctx, status="ok", details={"sections": payload.get("sections") or [], "live_reload_applied": response.get("live_reload_applied"), "restart_status": ((response.get("restart_request") or {}).get("status"))})
        return response

    @router.get("/admin/config-center/channels-wizard")
    def broker_admin_config_center_channels_wizard(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().channel_setup_wizard_snapshot(gw)
        audit_sensitive(gw, action="admin_config_center_channels_wizard_read", auth_ctx=auth_ctx, status="ok", details={"channels": [item.get("name") for item in response.get("channels", [])]})
        return response

    @router.post("/admin/config-center/channels-wizard/validate")
    async def broker_admin_config_center_channels_wizard_validate(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        try:
            response = AdminService().validate_channel_setup(
                gw,
                channel=str(payload.get("channel") or ""),
                content=str(payload.get("content") or ""),
                wizard_payload=payload.get("wizard_payload") if isinstance(payload.get("wizard_payload"), dict) else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_config_center_channels_wizard_validate", auth_ctx=auth_ctx, status="ok", details={"channel": response.get("channel")})
        return response

    @router.post("/admin/config-center/channels-wizard/save")
    async def broker_admin_config_center_channels_wizard_save(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().save_channel_setup(
                gw,
                channel=str(payload.get("channel") or ""),
                content=str(payload.get("content") or ""),
                wizard_payload=payload.get("wizard_payload") if isinstance(payload.get("wizard_payload"), dict) else None,
                reload_after_save=bool(payload.get("reload_after_save", False)),
                actor=str(payload.get("actor") or auth_ctx.get("username") or auth_ctx.get("user_key") or "broker-admin"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_config_center_channels_wizard_save", auth_ctx=auth_ctx, status="ok", details={"channel": response.get("channel"), "restart_required": response.get("restart_required")})
        return response

    @router.get("/admin/config-center/secrets-wizard")
    def broker_admin_config_center_secrets_wizard(request: Request, env_prefix: str | None = Query(default='OPENMIURA')):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().secret_env_reference_wizard_snapshot(gw, env_prefix=env_prefix or 'OPENMIURA')
        audit_sensitive(gw, action="admin_config_center_secrets_wizard_read", auth_ctx=auth_ctx, status="ok", details={"profiles": [item.get("name") for item in response.get("profiles", [])], "env_prefix": response.get("env_prefix")})
        return response

    @router.post("/admin/config-center/secrets-wizard/validate")
    async def broker_admin_config_center_secrets_wizard_validate(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        try:
            response = AdminService().validate_secret_env_references(
                gw,
                profile=str(payload.get("profile") or ""),
                content=str(payload.get("content") or ""),
                wizard_payload=payload.get("wizard_payload") if isinstance(payload.get("wizard_payload"), dict) else None,
                env_prefix=str(payload.get("env_prefix") or 'OPENMIURA'),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_config_center_secrets_wizard_validate", auth_ctx=auth_ctx, status="ok", details={"profile": response.get("profile")})
        return response

    @router.post("/admin/config-center/secrets-wizard/save")
    async def broker_admin_config_center_secrets_wizard_save(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().save_secret_env_references(
                gw,
                profile=str(payload.get("profile") or ""),
                content=str(payload.get("content") or ""),
                wizard_payload=payload.get("wizard_payload") if isinstance(payload.get("wizard_payload"), dict) else None,
                env_prefix=str(payload.get("env_prefix") or 'OPENMIURA'),
                reload_after_save=bool(payload.get("reload_after_save", False)),
                actor=str(payload.get("actor") or auth_ctx.get("username") or auth_ctx.get("user_key") or "broker-admin"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_config_center_secrets_wizard_save", auth_ctx=auth_ctx, status="ok", details={"profile": response.get("profile"), "restart_required": response.get("restart_required")})
        return response

