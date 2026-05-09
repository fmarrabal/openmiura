"""admin/system.py — sub-router for the system bounded admin domain."""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from openmiura.interfaces.http.routes.admin._helpers import (
    _ADMIN_SERVICE,
    _audit_admin,
    _extract_admin_token,
    _get_gw,
    _rate_limit,
    _require_admin,
)
from openmiura.interfaces.http.routes.admin._models import *  # noqa: F401,F403

router = APIRouter(tags=["admin"])


@router.get("/admin/config-center")
def admin_config_center(request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.config_center_snapshot(gw)
    _audit_admin(gw, "config_center_read", {"sections": [item.get("name") for item in response.get("sections", [])]})
    return response


@router.post("/admin/config-center/validate")
def admin_config_center_validate(payload: ConfigCenterValidateRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.validate_config_content(gw, section=payload.section, content=payload.content, form_payload=payload.form_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "config_center_validate", {"section": payload.section, "valid": response.get("valid", False)})
    return response


@router.post("/admin/config-center/save")
def admin_config_center_save(payload: ConfigCenterSaveRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.save_config_content(
            gw,
            section=payload.section,
            content=payload.content,
            reload_after_save=payload.reload_after_save,
            actor=payload.actor,
            form_payload=payload.form_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "config_center_save", {"section": payload.section, "reload_applied": response.get("reload_applied"), "restart_required": response.get("restart_required")})
    return response


@router.get("/admin/config-center/reload-assistant")
def admin_config_center_reload_assistant(request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.reload_assistant_snapshot(gw)
    _audit_admin(gw, "config_center_reload_assistant_read", {"sections": [item.get("name") for item in response.get("sections", [])], "hook_configured": (response.get("restart_hook") or {}).get("configured")})
    return response


@router.post("/admin/config-center/reload-assistant/apply")
def admin_config_center_reload_assistant_apply(payload: ReloadAssistantApplyRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.apply_reload_assistant(
            gw,
            sections=payload.sections,
            apply_live_reload=payload.apply_live_reload,
            request_restart=payload.request_restart,
            execute_restart_hook=payload.execute_restart_hook,
            actor=payload.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "config_center_reload_assistant_apply", {"sections": payload.sections, "live_reload_applied": response.get("live_reload_applied"), "restart_required": response.get("restart_required"), "restart_status": ((response.get("restart_request") or {}).get("status"))})
    return response


@router.get("/admin/config-center/channels-wizard")
def admin_config_center_channels_wizard(request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.channel_setup_wizard_snapshot(gw)
    _audit_admin(gw, "config_center_channels_wizard_read", {"channels": [item.get("name") for item in response.get("channels", [])]})
    return response


@router.post("/admin/config-center/channels-wizard/validate")
def admin_config_center_channels_wizard_validate(payload: ChannelWizardValidateRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.validate_channel_setup(
            gw,
            channel=payload.channel,
            content=payload.content,
            wizard_payload=payload.wizard_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "config_center_channels_wizard_validate", {"channel": response.get("channel"), "configured": response.get("channel_status", {}).get("configured")})
    return response


@router.post("/admin/config-center/channels-wizard/save")
def admin_config_center_channels_wizard_save(payload: ChannelWizardSaveRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.save_channel_setup(
            gw,
            channel=payload.channel,
            content=payload.content,
            wizard_payload=payload.wizard_payload,
            reload_after_save=payload.reload_after_save,
            actor=payload.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "config_center_channels_wizard_save", {"channel": response.get("channel"), "restart_required": response.get("restart_required")})
    return response


@router.get("/admin/phase8/packaging/summary")
def admin_phase8_packaging_summary(request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = {
        'ok': True,
        'packaging': _ADMIN_SERVICE.phase8_packaging_summary(gw),
        'hardening': _ADMIN_SERVICE.phase8_hardening_summary(gw),
    }
    _audit_admin(gw, "phase8_packaging_summary", {"ok": True})
    return response


@router.get("/admin/phase8/packaging/builds")
def admin_phase8_package_builds(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    target: str | None = Query(default=None),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.list_package_builds(
        gw,
        limit=limit,
        target=target,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "phase8_package_builds", {"count": len(response.get("items", [])), "target": target, "status": status})
    return response


@router.post("/admin/phase8/packaging/builds")
def admin_phase8_package_build_create(payload: PackageBuildRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.create_package_build(
        gw,
        actor=payload.actor,
        target=payload.target,
        label=payload.label,
        version=payload.version,
        artifact_path=payload.artifact_path,
        status=payload.status,
        metadata=payload.metadata,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "phase8_package_build_create", {"build_id": response.get("build", {}).get("build_id"), "target": payload.target, "actor": payload.actor})
    return response


@router.post("/admin/phase9/packaging/reproducible-build")
def admin_phase9_reproducible_build(payload: ReproducibleBuildRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.create_reproducible_package_build(
        gw,
        actor=payload.actor,
        target=payload.target,
        label=payload.label,
        version=payload.version,
        source_root=payload.source_root,
        output_dir=payload.output_dir,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    audit_event_id = _audit_admin(gw, "phase9_reproducible_build", {"target": payload.target, "actor": payload.actor})
    response["audit_event_id"] = audit_event_id
    return response


@router.post("/admin/phase9/packaging/verify-manifest")
def admin_phase9_verify_manifest(payload: VerifyManifestRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.verify_reproducible_package_manifest(manifest_path=payload.manifest_path)
    audit_event_id = _audit_admin(gw, "phase9_verify_manifest", {"manifest_path": payload.manifest_path, "ok": response.get("ok")})
    response["audit_event_id"] = audit_event_id
    return response


