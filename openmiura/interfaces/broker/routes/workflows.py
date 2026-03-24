from __future__ import annotations

import queue
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from openmiura.application.approvals import ApprovalService
from openmiura.application.auth.service import AuthService
from openmiura.application.jobs import JobService
from openmiura.application.workflows import PlaybookService, WorkflowBuilderService, WorkflowService
from openmiura.interfaces.broker.common import audit_sensitive, require_csrf, require_permission, session_event
from openmiura.interfaces.broker.schemas import (
    BrokerApprovalDecisionRequest,
    BrokerJobCreateRequest,
    BrokerPlaybookInstantiateRequest,
    BrokerPlaybookPublicationRequest,
    BrokerWorkflowActionRequest,
    BrokerWorkflowBuilderCreateRequest,
    BrokerWorkflowBuilderValidateRequest,
    BrokerWorkflowCreateRequest,
)


workflow_service = WorkflowService()
approval_service = ApprovalService(workflow_service=workflow_service)
job_service = JobService(workflow_service=workflow_service)
playbook_service = PlaybookService()
builder_service = WorkflowBuilderService(workflow_service=workflow_service, playbook_service=playbook_service)


def _scope_filters(auth_ctx: dict[str, Any]) -> dict[str, Any]:
    return AuthService.scope_filters(auth_ctx, include_environment=True)


def _event_matches(
    event: dict[str, Any],
    *,
    event_types: set[str] | None = None,
    topic: str | None = None,
    workflow_id: str | None = None,
    approval_id: str | None = None,
    job_id: str | None = None,
    entity_kind: str | None = None,
    entity_id: str | None = None,
    session_id: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    environment: str | None = None,
) -> bool:
    if event_types and str(event.get('type') or '') not in event_types:
        return False
    if topic and str(event.get('topic') or '') != str(topic):
        return False
    if workflow_id and str(event.get('workflow_id') or '') != str(workflow_id):
        return False
    if approval_id and str(event.get('approval_id') or '') != str(approval_id):
        return False
    if job_id and str(event.get('job_id') or '') != str(job_id):
        return False
    if entity_kind and str(event.get('entity_kind') or '') != str(entity_kind):
        return False
    if entity_id and str(event.get('entity_id') or '') != str(entity_id):
        return False
    if session_id and str(event.get('session_id') or '') != str(session_id):
        return False
    if tenant_id and str(event.get('tenant_id') or '') != str(tenant_id):
        return False
    if workspace_id and str(event.get('workspace_id') or '') != str(workspace_id):
        return False
    if environment and str(event.get('environment') or '') != str(environment):
        return False
    return True


def build_workflow_router() -> APIRouter:
    router = APIRouter(tags=['broker'])

    @router.get('/workflow-builder/schema')
    def broker_workflow_builder_schema(request: Request):
        gw, auth_ctx = require_permission(request, 'workflows.read')
        payload = builder_service.schema_catalog()
        audit_sensitive(gw, action='workflow_builder_schema', auth_ctx=auth_ctx, status='ok', details={'starter_playbooks': len(payload.get('starter_playbooks') or [])})
        return payload

    @router.get('/workflow-builder/playbooks')
    def broker_workflow_builder_playbooks(request: Request):
        gw, auth_ctx = require_permission(request, 'workflows.read')
        payload = builder_service.schema_catalog()
        items = payload.get('starter_playbooks') or []
        audit_sensitive(gw, action='workflow_builder_playbooks', auth_ctx=auth_ctx, status='ok', details={'count': len(items)})
        return {'ok': True, 'items': items}

    @router.get('/workflow-builder/playbooks/{playbook_id}')
    def broker_workflow_builder_playbook(playbook_id: str, request: Request, version: str | None = Query(default=None)):
        gw, auth_ctx = require_permission(request, 'workflows.read')
        payload = builder_service.playbook_payload(playbook_id, version=version)
        if payload is None:
            raise HTTPException(status_code=404, detail='Unknown playbook')
        audit_sensitive(gw, action='workflow_builder_playbook', auth_ctx=auth_ctx, status='ok', target=playbook_id)
        return payload

    @router.post('/workflow-builder/validate')
    def broker_workflow_builder_validate(payload: BrokerWorkflowBuilderValidateRequest, request: Request):
        gw, auth_ctx = require_permission(request, 'workflows.write')
        result = builder_service.validate_definition(payload.definition)
        audit_sensitive(gw, action='workflow_builder_validate', auth_ctx=auth_ctx, status='ok' if result.get('ok') else 'error', details={'errors': len(result.get('errors') or []), 'warnings': len(result.get('warnings') or [])})
        return result

    @router.post('/workflow-builder/create')
    def broker_workflow_builder_create(payload: BrokerWorkflowBuilderCreateRequest, request: Request):
        gw, auth_ctx = require_permission(request, 'workflows.write')
        require_csrf(request, auth_ctx)
        validation = builder_service.validate_definition(payload.definition)
        if not validation.get('ok'):
            raise HTTPException(status_code=400, detail='; '.join(validation.get('errors') or ['Invalid workflow definition']))
        scope = _scope_filters(auth_ctx)
        item = workflow_service.create_workflow(
            gw,
            name=payload.name,
            definition=validation['definition'],
            created_by=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'),
            input_payload=payload.input,
            playbook_id=payload.playbook_id,
            **scope,
        )
        if payload.autorun:
            try:
                item = workflow_service.run_workflow(gw, item['workflow_id'], actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'), **scope)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action='workflow_builder_create', auth_ctx=auth_ctx, status='ok', target=item['workflow_id'], details={'warnings': len(validation.get('warnings') or [])})
        return {'ok': True, 'workflow': item, 'builder': {'graph': validation.get('graph'), 'warnings': validation.get('warnings') or [], 'stats': validation.get('stats') or {}}}

    @router.get('/workflows')
    def broker_workflows_list(request: Request, limit: int = Query(default=100, ge=1, le=300), status: str | None = Query(default=None)):
        gw, auth_ctx = require_permission(request, 'workflows.read')
        payload = workflow_service.list_workflows(gw, limit=limit, status=status, **_scope_filters(auth_ctx))
        audit_sensitive(gw, action='workflows_list', auth_ctx=auth_ctx, status='ok', details={'count': len(payload['items'])})
        return payload

    @router.post('/workflows')
    def broker_workflows_create(payload: BrokerWorkflowCreateRequest, request: Request):
        gw, auth_ctx = require_permission(request, 'workflows.write')
        require_csrf(request, auth_ctx)
        scope = _scope_filters(auth_ctx)
        item = workflow_service.create_workflow(
            gw,
            name=payload.name,
            definition=payload.definition,
            created_by=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'),
            input_payload=payload.input,
            playbook_id=payload.playbook_id,
            **scope,
        )
        if payload.autorun:
            try:
                item = workflow_service.run_workflow(gw, item['workflow_id'], actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'), **scope)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action='workflow_create', auth_ctx=auth_ctx, status='ok', target=item['workflow_id'])
        return {'ok': True, 'workflow': item}

    @router.get('/workflows/{workflow_id}')
    def broker_workflow_get(workflow_id: str, request: Request):
        gw, auth_ctx = require_permission(request, 'workflows.read')
        item = workflow_service.get_workflow(gw, workflow_id, **_scope_filters(auth_ctx))
        if item is None:
            raise HTTPException(status_code=404, detail='Unknown workflow')
        return {'ok': True, 'workflow': item}

    @router.get('/workflows/{workflow_id}/timeline')
    def broker_workflow_timeline(workflow_id: str, request: Request, limit: int = Query(default=200, ge=1, le=500)):
        gw, auth_ctx = require_permission(request, 'workflows.read')
        payload = workflow_service.timeline(gw, workflow_id, limit=limit, **_scope_filters(auth_ctx))
        return payload

    @router.get('/workflows/{workflow_id}/stream')
    def broker_workflow_stream(
        workflow_id: str,
        request: Request,
        replay_last: int = Query(default=20, ge=0, le=500),
        since_id: int | None = Query(default=None, ge=0),
        once: bool = Query(default=False),
        event_types: list[str] = Query(default=[]),
    ):
        gw, auth_ctx = require_permission(request, 'workflows.read')
        scope = _scope_filters(auth_ctx)
        item = workflow_service.get_workflow(gw, workflow_id, **scope)
        if item is None:
            raise HTTPException(status_code=404, detail='Unknown workflow')
        bus = getattr(gw, 'realtime_bus', None)
        if bus is None:
            raise HTTPException(status_code=503, detail='Realtime bus not configured')
        type_set = {str(entry).strip() for entry in event_types if str(entry).strip()} or None
        q = bus.subscribe(
            replay_last=replay_last,
            event_types=list(type_set or []),
            topic='workflow',
            workflow_id=workflow_id,
            tenant_id=item.get('tenant_id'),
            workspace_id=item.get('workspace_id'),
            environment=item.get('environment'),
            since_id=since_id,
        )

        def _gen():
            yield session_event('connected', workflow_id=workflow_id, replay_last=replay_last, scope=scope)
            try:
                idle_loops = 0
                while True:
                    try:
                        event = q.get(timeout=0.25 if once else 15.0)
                    except queue.Empty:
                        if once:
                            idle_loops += 1
                            if idle_loops >= 1:
                                break
                        else:
                            yield session_event('heartbeat', ts=time.time(), workflow_id=workflow_id)
                        continue
                    idle_loops = 0
                    if _event_matches(
                        event,
                        event_types=type_set,
                        topic='workflow',
                        workflow_id=workflow_id,
                        tenant_id=item.get('tenant_id'),
                        workspace_id=item.get('workspace_id'),
                        environment=item.get('environment'),
                    ):
                        yield session_event(str(event.get('type') or 'message'), **event)
                    if once and q.empty():
                        break
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(_gen(), media_type='text/event-stream')

    @router.post('/workflows/{workflow_id}/run')
    def broker_workflow_run(workflow_id: str, request: Request):
        gw, auth_ctx = require_permission(request, 'workflows.write')
        require_csrf(request, auth_ctx)
        try:
            item = workflow_service.run_workflow(gw, workflow_id, actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'), **_scope_filters(auth_ctx))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action='workflow_run', auth_ctx=auth_ctx, status='ok', target=workflow_id)
        return {'ok': True, 'workflow': item}

    @router.post('/workflows/{workflow_id}/cancel')
    def broker_workflow_cancel(workflow_id: str, payload: BrokerWorkflowActionRequest, request: Request):
        gw, auth_ctx = require_permission(request, 'workflows.write')
        require_csrf(request, auth_ctx)
        item = workflow_service.cancel_workflow(gw, workflow_id, actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'), **_scope_filters(auth_ctx))
        if item is None:
            raise HTTPException(status_code=404, detail='Unknown workflow')
        audit_sensitive(gw, action='workflow_cancel', auth_ctx=auth_ctx, status='ok', target=workflow_id, details={'reason': payload.reason})
        return {'ok': True, 'workflow': item}

    @router.get('/approvals')
    def broker_approvals_list(
        request: Request,
        limit: int = Query(default=100, ge=1, le=300),
        status: str | None = Query(default='pending'),
        workflow_id: str | None = Query(default=None),
        requested_role: str | None = Query(default=None),
        requested_by: str | None = Query(default=None),
        assignee: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, 'approvals.read')
        payload = approval_service.list_approvals(
            gw,
            limit=limit,
            status=status,
            workflow_id=workflow_id,
            requested_role=requested_role,
            requested_by=requested_by,
            assignee=assignee,
            **_scope_filters(auth_ctx),
        )
        audit_sensitive(gw, action='approvals_list', auth_ctx=auth_ctx, status='ok', details={'count': len(payload['items'])})
        return payload

    @router.get('/approvals/{approval_id}')
    def broker_approval_get(approval_id: str, request: Request):
        gw, auth_ctx = require_permission(request, 'approvals.read')
        item = approval_service.get_approval(gw, approval_id, **_scope_filters(auth_ctx))
        if item is None:
            raise HTTPException(status_code=404, detail='Unknown approval')
        return {'ok': True, 'approval': item}

    @router.get('/approvals/{approval_id}/timeline')
    def broker_approval_timeline(approval_id: str, request: Request, limit: int = Query(default=200, ge=1, le=500)):
        gw, auth_ctx = require_permission(request, 'approvals.read')
        return workflow_service.unified_timeline(gw, limit=limit, approval_id=approval_id, **_scope_filters(auth_ctx))

    @router.post('/approvals/{approval_id}/claim')
    def broker_approval_claim(approval_id: str, request: Request):
        gw, auth_ctx = require_permission(request, 'approvals.write')
        require_csrf(request, auth_ctx)
        try:
            item = approval_service.claim(
                gw,
                approval_id,
                actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'),
                **_scope_filters(auth_ctx),
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        audit_sensitive(gw, action='approval_claim', auth_ctx=auth_ctx, status='ok', target=approval_id)
        return {'ok': True, 'approval': item}

    @router.post('/approvals/{approval_id}/decision')
    def broker_approval_decision(approval_id: str, payload: BrokerApprovalDecisionRequest, request: Request):
        gw, auth_ctx = require_permission(request, 'approvals.write')
        require_csrf(request, auth_ctx)
        try:
            item = approval_service.decide(
                gw,
                approval_id,
                actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'),
                decision=payload.decision,
                reason=payload.reason,
                **_scope_filters(auth_ctx),
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            status_code = 409 if 'already claimed' in str(exc).lower() else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        audit_sensitive(gw, action='approval_decision', auth_ctx=auth_ctx, status='ok', target=approval_id, details={'decision': payload.decision})
        return {'ok': True, 'approval': item}

    @router.get('/jobs')
    def broker_jobs_list(request: Request, limit: int = Query(default=100, ge=1, le=300), enabled: bool | None = Query(default=None)):
        gw, auth_ctx = require_permission(request, 'jobs.read')
        payload = job_service.list_jobs(gw, limit=limit, enabled=enabled, **_scope_filters(auth_ctx))
        return payload

    @router.get('/jobs/summary')
    def broker_jobs_summary(request: Request, limit: int = Query(default=200, ge=1, le=500)):
        gw, auth_ctx = require_permission(request, 'jobs.read')
        return job_service.jobs_summary(gw, limit=limit, **_scope_filters(auth_ctx))

    @router.get('/jobs/{job_id}/timeline')
    def broker_job_timeline(job_id: str, request: Request, limit: int = Query(default=200, ge=1, le=500)):
        gw, auth_ctx = require_permission(request, 'jobs.read')
        return workflow_service.unified_timeline(gw, limit=limit, job_id=job_id, **_scope_filters(auth_ctx))

    @router.get('/jobs/{job_id}')
    def broker_job_get(job_id: str, request: Request):
        gw, auth_ctx = require_permission(request, 'jobs.read')
        item = job_service.get_job(gw, job_id, **_scope_filters(auth_ctx))
        if item is None:
            raise HTTPException(status_code=404, detail='Unknown job')
        return {'ok': True, 'job': item}

    @router.post('/jobs')
    def broker_jobs_create(payload: BrokerJobCreateRequest, request: Request):
        gw, auth_ctx = require_permission(request, 'jobs.write')
        require_csrf(request, auth_ctx)
        try:
            item = job_service.create_job(
                gw,
                name=payload.name,
                workflow_definition=payload.workflow_definition,
                created_by=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'),
                input_payload=payload.input,
                interval_s=payload.interval_s,
                next_run_at=payload.next_run_at,
                enabled=payload.enabled,
                playbook_id=payload.playbook_id,
                schedule_kind=payload.schedule_kind,
                schedule_expr=payload.schedule_expr,
                timezone_name=payload.timezone,
                not_before=payload.not_before,
                not_after=payload.not_after,
                max_runs=payload.max_runs,
                **_scope_filters(auth_ctx),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action='job_create', auth_ctx=auth_ctx, status='ok', target=item['job_id'])
        return {'ok': True, 'job': item}

    @router.post('/jobs/{job_id}/pause')
    def broker_job_pause(job_id: str, request: Request):
        gw, auth_ctx = require_permission(request, 'jobs.write')
        require_csrf(request, auth_ctx)
        item = job_service.pause_job(gw, job_id, actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'), **_scope_filters(auth_ctx))
        if item is None:
            raise HTTPException(status_code=404, detail='Unknown job')
        audit_sensitive(gw, action='job_pause', auth_ctx=auth_ctx, status='ok', target=job_id)
        return {'ok': True, 'job': item}

    @router.post('/jobs/{job_id}/resume')
    def broker_job_resume(job_id: str, request: Request):
        gw, auth_ctx = require_permission(request, 'jobs.write')
        require_csrf(request, auth_ctx)
        item = job_service.resume_job(gw, job_id, actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'), **_scope_filters(auth_ctx))
        if item is None:
            raise HTTPException(status_code=404, detail='Unknown job')
        audit_sensitive(gw, action='job_resume', auth_ctx=auth_ctx, status='ok', target=job_id)
        return {'ok': True, 'job': item}

    @router.post('/jobs/{job_id}/run')
    def broker_job_run(job_id: str, request: Request):
        gw, auth_ctx = require_permission(request, 'jobs.run')
        require_csrf(request, auth_ctx)
        try:
            payload = job_service.run_job(gw, job_id, actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'), **_scope_filters(auth_ctx))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action='job_run', auth_ctx=auth_ctx, status='ok', target=job_id)
        return {'ok': True, **payload}

    @router.post('/jobs/run-due')
    def broker_jobs_run_due(request: Request, limit: int = Query(default=20, ge=1, le=100)):
        gw, auth_ctx = require_permission(request, 'jobs.run')
        require_csrf(request, auth_ctx)
        payload = job_service.run_due_jobs(gw, actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'), limit=limit, **_scope_filters(auth_ctx))
        audit_sensitive(gw, action='jobs_run_due', auth_ctx=auth_ctx, status='ok', details={'count': len(payload['items'])})
        return payload

    @router.get('/playbooks')
    def broker_playbooks_list(request: Request, published_only: bool = Query(default=False), include_versions: bool = Query(default=False)):
        gw, auth_ctx = require_permission(request, 'workflows.read')
        items = playbook_service.list_playbooks(published_only=published_only, include_versions=include_versions)
        audit_sensitive(gw, action='playbooks_list', auth_ctx=auth_ctx, status='ok', details={'count': len(items), 'published_only': published_only})
        return {'ok': True, 'items': items}

    @router.get('/playbooks/{playbook_id}')
    def broker_playbook_get(playbook_id: str, request: Request, version: str | None = Query(default=None)):
        gw, auth_ctx = require_permission(request, 'workflows.read')
        item = playbook_service.get_playbook(playbook_id, version=version)
        if item is None:
            raise HTTPException(status_code=404, detail='Unknown playbook')
        audit_sensitive(gw, action='playbook_get', auth_ctx=auth_ctx, status='ok', target=playbook_id)
        return {'ok': True, 'playbook': item}

    @router.get('/playbooks/{playbook_id}/versions')
    def broker_playbook_versions(playbook_id: str, request: Request):
        gw, auth_ctx = require_permission(request, 'workflows.read')
        versions = playbook_service.list_versions(playbook_id)
        if not versions:
            raise HTTPException(status_code=404, detail='Unknown playbook')
        audit_sensitive(gw, action='playbook_versions', auth_ctx=auth_ctx, status='ok', target=playbook_id, details={'count': len(versions)})
        return {'ok': True, 'items': versions}

    @router.post('/playbooks/{playbook_id}/publish')
    def broker_playbook_publish(playbook_id: str, payload: BrokerPlaybookPublicationRequest, request: Request):
        gw, auth_ctx = require_permission(request, 'workflows.write')
        require_csrf(request, auth_ctx)
        try:
            item = playbook_service.publish(playbook_id, actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'), version=payload.version, notes=payload.notes)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        audit_sensitive(gw, action='playbook_publish', auth_ctx=auth_ctx, status='ok', target=playbook_id, details={'version': item.get('version')})
        return {'ok': True, 'playbook': item}

    @router.post('/playbooks/{playbook_id}/deprecate')
    def broker_playbook_deprecate(playbook_id: str, payload: BrokerPlaybookPublicationRequest, request: Request):
        gw, auth_ctx = require_permission(request, 'workflows.write')
        require_csrf(request, auth_ctx)
        try:
            item = playbook_service.deprecate(playbook_id, actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'), version=payload.version, notes=payload.notes)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        audit_sensitive(gw, action='playbook_deprecate', auth_ctx=auth_ctx, status='ok', target=playbook_id, details={'version': item.get('version')})
        return {'ok': True, 'playbook': item}

    @router.post('/playbooks/{playbook_id}/instantiate')
    def broker_playbook_instantiate(playbook_id: str, payload: BrokerPlaybookInstantiateRequest, request: Request, version: str | None = Query(default=None)):
        gw, auth_ctx = require_permission(request, 'workflows.write')
        require_csrf(request, auth_ctx)
        try:
            item = playbook_service.instantiate(
                gw,
                playbook_id,
                actor=str(auth_ctx.get('user_key') or auth_ctx.get('username') or 'system'),
                name=payload.name,
                input_payload=payload.input,
                autorun=payload.autorun,
                workflow_service=workflow_service,
                version=version,
                **_scope_filters(auth_ctx),
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action='playbook_instantiate', auth_ctx=auth_ctx, status='ok', target=playbook_id)
        return {'ok': True, 'workflow': item}

    @router.get('/timeline')
    def broker_timeline(
        request: Request,
        limit: int = Query(default=200, ge=1, le=500),
        workflow_id: str | None = Query(default=None),
        approval_id: str | None = Query(default=None),
        job_id: str | None = Query(default=None),
        entity_kind: str | None = Query(default=None),
        entity_id: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, 'events.read')
        return workflow_service.unified_timeline(gw, limit=limit, workflow_id=workflow_id, approval_id=approval_id, job_id=job_id, entity_kind=entity_kind, entity_id=entity_id, **_scope_filters(auth_ctx))

    @router.get('/timeline/stream')
    def broker_timeline_stream(
        request: Request,
        replay_last: int = Query(default=20, ge=0, le=500),
        workflow_id: str | None = Query(default=None),
        approval_id: str | None = Query(default=None),
        job_id: str | None = Query(default=None),
        entity_kind: str | None = Query(default=None),
        entity_id: str | None = Query(default=None),
        since_id: int | None = Query(default=None, ge=0),
        once: bool = Query(default=False),
        event_types: list[str] = Query(default=[]),
    ):
        gw, auth_ctx = require_permission(request, 'events.read')
        bus = getattr(gw, 'realtime_bus', None)
        if bus is None:
            raise HTTPException(status_code=503, detail='Realtime bus not configured')
        scope = _scope_filters(auth_ctx)
        type_set = {str(entry).strip() for entry in event_types if str(entry).strip()} or None
        q = bus.subscribe(
            replay_last=replay_last,
            event_types=list(type_set or []),
            topic='workflow',
            workflow_id=workflow_id,
            approval_id=approval_id,
            job_id=job_id,
            entity_kind=entity_kind,
            entity_id=entity_id,
            since_id=since_id,
            **scope,
        )

        def _gen():
            yield session_event('connected', topic='workflow', workflow_id=workflow_id, approval_id=approval_id, job_id=job_id, entity_kind=entity_kind, entity_id=entity_id, scope=scope, replay_last=replay_last)
            try:
                idle_loops = 0
                while True:
                    try:
                        event = q.get(timeout=0.25 if once else 15.0)
                    except queue.Empty:
                        if once:
                            idle_loops += 1
                            if idle_loops >= 1:
                                break
                        else:
                            yield session_event('heartbeat', ts=time.time(), topic='workflow')
                        continue
                    idle_loops = 0
                    if _event_matches(event, event_types=type_set, topic='workflow', workflow_id=workflow_id, approval_id=approval_id, job_id=job_id, entity_kind=entity_kind, entity_id=entity_id, **scope):
                        yield session_event(str(event.get('type') or 'message'), **event)
                    if once and q.empty():
                        break
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(_gen(), media_type='text/event-stream')

    @router.get('/realtime/events')
    def broker_realtime_events(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        topic: str | None = Query(default=None),
        workflow_id: str | None = Query(default=None),
        approval_id: str | None = Query(default=None),
        job_id: str | None = Query(default=None),
        entity_kind: str | None = Query(default=None),
        entity_id: str | None = Query(default=None),
        session_id: str | None = Query(default=None),
        since_id: int | None = Query(default=None, ge=0),
        event_types: list[str] = Query(default=[]),
    ):
        gw, auth_ctx = require_permission(request, 'events.read')
        bus = getattr(gw, 'realtime_bus', None)
        if bus is None:
            raise HTTPException(status_code=503, detail='Realtime bus not configured')
        scope = _scope_filters(auth_ctx)
        items = bus.recent(
            limit=limit,
            event_types=event_types,
            topic=topic,
            workflow_id=workflow_id,
            approval_id=approval_id,
            job_id=job_id,
            entity_kind=entity_kind,
            entity_id=entity_id,
            session_id=session_id,
            since_id=since_id,
            **scope,
        )
        audit_sensitive(gw, action='realtime_events', auth_ctx=auth_ctx, status='ok', details={'count': len(items), 'topic': topic or ''})
        return {'ok': True, 'items': items, 'stats': bus.stats()}

    @router.get('/realtime/stream')
    def broker_realtime_stream(
        request: Request,
        replay_last: int = Query(default=20, ge=0, le=500),
        topic: str | None = Query(default=None),
        workflow_id: str | None = Query(default=None),
        approval_id: str | None = Query(default=None),
        job_id: str | None = Query(default=None),
        entity_kind: str | None = Query(default=None),
        entity_id: str | None = Query(default=None),
        session_id: str | None = Query(default=None),
        since_id: int | None = Query(default=None, ge=0),
        once: bool = Query(default=False),
        event_types: list[str] = Query(default=[]),
    ):
        gw, auth_ctx = require_permission(request, 'events.read')
        bus = getattr(gw, 'realtime_bus', None)
        if bus is None:
            raise HTTPException(status_code=503, detail='Realtime bus not configured')
        scope = _scope_filters(auth_ctx)
        type_set = {str(entry).strip() for entry in event_types if str(entry).strip()} or None
        q = bus.subscribe(
            replay_last=replay_last,
            event_types=list(type_set or []),
            topic=topic,
            workflow_id=workflow_id,
            approval_id=approval_id,
            job_id=job_id,
            entity_kind=entity_kind,
            entity_id=entity_id,
            session_id=session_id,
            since_id=since_id,
            **scope,
        )

        def _gen():
            yield session_event('connected', topic=topic or '*', workflow_id=workflow_id, scope=scope, replay_last=replay_last)
            try:
                idle_loops = 0
                while True:
                    try:
                        event = q.get(timeout=0.25 if once else 15.0)
                    except queue.Empty:
                        if once:
                            idle_loops += 1
                            if idle_loops >= 1:
                                break
                        else:
                            yield session_event('heartbeat', ts=time.time(), topic=topic or '*')
                        continue
                    idle_loops = 0
                    if _event_matches(event, event_types=type_set, topic=topic, workflow_id=workflow_id, approval_id=approval_id, job_id=job_id, entity_kind=entity_kind, entity_id=entity_id, session_id=session_id, **scope):
                        yield session_event(str(event.get('type') or 'message'), **event)
                    if once and q.empty():
                        break
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(_gen(), media_type='text/event-stream')

    return router
