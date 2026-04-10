from __future__ import annotations

import copy
from typing import Any

from openmiura.application.workflows.playbooks import PlaybookService
from openmiura.application.workflows.service import WorkflowService


class WorkflowBuilderService:
    """Helpers for the phase-7 visual builder surface.

    The service is intentionally backend-light: it reuses the existing workflow
    engine contracts and exposes a graph-oriented representation that the UI can
    render without introducing a second workflow DSL.
    """

    def __init__(
        self,
        *,
        workflow_service: WorkflowService | None = None,
        playbook_service: PlaybookService | None = None,
    ) -> None:
        self.workflow_service = workflow_service or WorkflowService()
        self.playbook_service = playbook_service or PlaybookService()

    def schema_catalog(self) -> dict[str, Any]:
        playbooks: list[dict[str, Any]] = []
        for item in self.playbook_service.list_playbooks(published_only=False, include_versions=False):
            playbooks.append(
                {
                    "playbook_id": item.get("playbook_id"),
                    "name": item.get("name") or item.get("playbook_id"),
                    "description": item.get("description") or "",
                    "category": item.get("category") or "general",
                    "tags": list(item.get("tags") or []),
                    "input_schema": copy.deepcopy(item.get("input_schema") or {"type": "object", "properties": {}}),
                    "defaults": copy.deepcopy(item.get("defaults") or {}),
                    "current_version": item.get("current_version") or item.get("version"),
                }
            )
        return {
            "ok": True,
            "kinds": ["note", "tool", "approval", "branch"],
            "branch_operators": ["truthy", "exists", "falsy", "eq", "ne", "gt", "gte", "lt", "lte", "contains"],
            "supported_refs": ["$input.*", "$context.*", "$step.<step_id>.*", "$last_result"],
            "starter_playbooks": playbooks,
            "ui_hints": {
                "supports_branching": True,
                "supports_approvals": True,
                "supports_retries": True,
                "supports_timeouts": True,
            },
        }

    def validate_definition(self, definition: dict[str, Any]) -> dict[str, Any]:
        raw_steps = list(dict(definition or {}).get("steps") or [])
        errors: list[str] = []
        warnings: list[str] = []
        seen: set[str] = set()
        duplicates: set[str] = set()
        for idx, raw in enumerate(raw_steps):
            step_id = str((raw or {}).get("id") or f"step-{idx + 1}").strip()
            if step_id in seen:
                duplicates.add(step_id)
            seen.add(step_id)
        if duplicates:
            errors.append(f"Duplicate step ids: {', '.join(sorted(duplicates))}")
        try:
            normalized = self.workflow_service._normalize_definition(definition)
        except Exception as exc:
            return {"ok": False, "errors": [str(exc)], "warnings": warnings, "definition": copy.deepcopy(dict(definition or {})), "graph": {"nodes": [], "edges": []}}

        steps = list(normalized.get("steps") or [])
        index_by_id = {str(step.get("id") or ""): idx for idx, step in enumerate(steps)}
        for step in steps:
            if str(step.get("kind") or "") == "branch":
                true_target = str(step.get("if_true_step_id") or "").strip()
                false_target = str(step.get("if_false_step_id") or "").strip()
                if true_target and true_target not in index_by_id:
                    errors.append(f"Branch step '{step['id']}' references missing true target '{true_target}'")
                if false_target and false_target not in index_by_id:
                    errors.append(f"Branch step '{step['id']}' references missing false target '{false_target}'")
                if not true_target and not false_target:
                    warnings.append(f"Branch step '{step['id']}' has no explicit target steps")

        graph = self.build_graph(normalized)
        node_ids = {str(node.get("id") or "") for node in graph["nodes"]}
        visited: set[str] = set()
        pending: list[str] = [graph["nodes"][0]["id"]] if graph["nodes"] else []
        adjacency: dict[str, list[str]] = {}
        for edge in graph["edges"]:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source and target:
                adjacency.setdefault(source, []).append(target)
        while pending:
            current = pending.pop(0)
            if current in visited or current not in node_ids:
                continue
            visited.add(current)
            for nxt in adjacency.get(current, []):
                if nxt not in visited:
                    pending.append(nxt)
        unreachable = sorted(x for x in node_ids if x and x not in visited)
        if unreachable:
            warnings.append(f"Unreachable steps: {', '.join(unreachable)}")

        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "definition": normalized,
            "graph": graph,
            "stats": {
                "step_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"]),
                "unreachable_steps": unreachable,
                "approval_steps": len([node for node in graph["nodes"] if node.get("kind") == "approval"]),
                "branch_steps": len([node for node in graph["nodes"] if node.get("kind") == "branch"]),
            },
        }

    def build_graph(self, definition: dict[str, Any]) -> dict[str, Any]:
        normalized = self.workflow_service._normalize_definition(definition)
        steps = list(normalized.get("steps") or [])
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        x_by_id: dict[str, int] = {}
        step_ids = [str(step.get("id") or "") for step in steps]
        for idx, step in enumerate(steps):
            step_id = str(step.get("id") or f"step-{idx + 1}")
            kind = str(step.get("kind") or "note")
            lane = 0
            if kind == "branch":
                lane = 1
            elif kind == "approval":
                lane = -1
            x_by_id.setdefault(step_id, lane)
            label = str(step.get("name") or step_id)
            subtitle = ""
            if kind == "tool":
                subtitle = str(step.get("tool_name") or "")
            elif kind == "approval":
                subtitle = f"role: {step.get('requested_role') or 'operator'}"
            elif kind == "branch":
                cond = dict(step.get("condition") or {})
                subtitle = f"{cond.get('left') or ''} {cond.get('op') or 'eq'} {cond.get('right') or ''}".strip()
            elif kind == "note":
                subtitle = str(step.get("note") or "")
            nodes.append(
                {
                    "id": step_id,
                    "kind": kind,
                    "label": label,
                    "subtitle": subtitle,
                    "position": {"x": lane, "y": idx},
                    "meta": {
                        "retry_limit": int(step.get("retry_limit") or 0),
                        "backoff_s": float(step.get("backoff_s") or 0.0),
                        "timeout_s": step.get("timeout_s"),
                    },
                }
            )
            if kind == "branch":
                true_target = str(step.get("if_true_step_id") or "").strip()
                false_target = str(step.get("if_false_step_id") or "").strip()
                if true_target:
                    x_by_id[true_target] = 1
                    edges.append({"source": step_id, "target": true_target, "label": "true", "kind": "branch"})
                if false_target:
                    x_by_id[false_target] = -1
                    edges.append({"source": step_id, "target": false_target, "label": "false", "kind": "branch"})
            elif idx + 1 < len(steps):
                next_step_id = step_ids[idx + 1]
                edges.append({"source": step_id, "target": next_step_id, "label": "next", "kind": "sequential"})

        # align known targets after branch discovery
        for node in nodes:
            step_id = str(node.get("id") or "")
            if step_id in x_by_id:
                node["position"]["x"] = x_by_id[step_id]
        return {"nodes": nodes, "edges": edges}

    def playbook_payload(self, playbook_id: str, *, version: str | None = None) -> dict[str, Any] | None:
        item = self.playbook_service.get_playbook(playbook_id, version=version)
        if item is None:
            return None
        validation = self.validate_definition(dict(item.get("definition") or {}))
        return {
            "ok": validation.get("ok", False),
            "playbook": item,
            "builder": {
                "graph": validation.get("graph") or {"nodes": [], "edges": []},
                "warnings": list(validation.get("warnings") or []),
                "errors": list(validation.get("errors") or []),
                "stats": validation.get("stats") or {},
            },
        }
