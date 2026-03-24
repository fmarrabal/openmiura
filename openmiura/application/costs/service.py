from __future__ import annotations

import time
from typing import Any


class CostGovernanceService:
    _ALLOWED_GROUPS = {
        "tenant",
        "workspace",
        "agent",
        "workflow",
        "provider",
        "model",
        "tenant_workspace",
        "agent_provider_model",
    }

    def _settings(self, gw: Any):
        return getattr(getattr(gw, "settings", None), "cost_governance", None)

    def _default_window_hours(self, gw: Any) -> int:
        settings = self._settings(gw)
        return int(getattr(settings, "default_window_hours", 24 * 30) or (24 * 30))

    def _default_scan_limit(self, gw: Any) -> int:
        settings = self._settings(gw)
        return int(getattr(settings, "default_scan_limit", 2000) or 2000)

    def _normalize_group_by(self, group_by: str | None) -> str:
        value = str(group_by or "tenant").strip().lower()
        return value if value in self._ALLOWED_GROUPS else "tenant"

    def _workflow_name(self, run: dict[str, Any]) -> str:
        return str(run.get("workflow_name") or run.get("suite_name") or "unassigned-workflow")

    def _group_value(self, run: dict[str, Any], group_by: str) -> str:
        tenant_id = str(run.get("tenant_id") or "default")
        workspace_id = str(run.get("workspace_id") or "main")
        agent_name = str(run.get("agent_name") or "unassigned-agent")
        provider = str(run.get("provider") or "unknown-provider")
        model = str(run.get("model") or "unknown-model")
        workflow_name = self._workflow_name(run)
        if group_by == "tenant":
            return tenant_id
        if group_by == "workspace":
            return workspace_id
        if group_by == "agent":
            return agent_name
        if group_by == "workflow":
            return workflow_name
        if group_by == "provider":
            return provider
        if group_by == "model":
            return model
        if group_by == "tenant_workspace":
            return f"{tenant_id} / {workspace_id}"
        return f"{agent_name} / {provider} / {model}"

    def _fetch_runs(
        self,
        gw: Any,
        *,
        limit: int,
        suite_name: str | None = None,
        workflow_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        window_hours: int | None = None,
    ) -> list[dict[str, Any]]:
        query_suite_name = suite_name or workflow_name
        runs = list(
            getattr(gw.audit, "list_evaluation_runs", lambda **_: [])(
                limit=max(1, int(limit)),
                suite_name=query_suite_name,
                agent_name=agent_name,
                provider=provider,
                model=model,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            or []
        )
        effective_window_hours = int(window_hours or self._default_window_hours(gw))
        cutoff = time.time() - (effective_window_hours * 3600)
        filtered: list[dict[str, Any]] = []
        workflow_name_norm = str(workflow_name or "").strip().lower()
        for raw in runs:
            item = dict(raw or {})
            event_time = float(item.get("completed_at") or item.get("started_at") or 0.0)
            if event_time and event_time < cutoff:
                continue
            if workflow_name_norm and self._workflow_name(item).strip().lower() != workflow_name_norm:
                continue
            filtered.append(item)
        return filtered

    def summary(
        self,
        gw: Any,
        *,
        group_by: str = "tenant",
        limit: int = 20,
        window_hours: int | None = None,
        suite_name: str | None = None,
        workflow_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized_group_by = self._normalize_group_by(group_by)
        effective_window_hours = int(window_hours or self._default_window_hours(gw))
        scan_limit = max(self._default_scan_limit(gw), int(limit) * 10)
        runs = self._fetch_runs(
            gw,
            limit=scan_limit,
            suite_name=suite_name,
            workflow_name=workflow_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            window_hours=effective_window_hours,
        )
        buckets: dict[str, dict[str, Any]] = {}
        total_spend = 0.0
        total_cases = 0
        for run in runs:
            group = self._group_value(run, normalized_group_by)
            bucket = buckets.setdefault(
                group,
                {
                    "group": group,
                    "run_count": 0,
                    "total_spend": 0.0,
                    "total_cases": 0,
                    "latest_run_id": "",
                    "latest_started_at": 0.0,
                    "tenant_ids": set(),
                    "workspace_ids": set(),
                    "environments": set(),
                    "agents": set(),
                    "workflows": set(),
                    "providers": set(),
                    "models": set(),
                },
            )
            started_at = float(run.get("started_at") or 0.0)
            spend = float(run.get("total_cost") or 0.0)
            cases = int(run.get("total_cases") or 0)
            bucket["run_count"] += 1
            bucket["total_spend"] += spend
            bucket["total_cases"] += cases
            bucket["tenant_ids"].add(str(run.get("tenant_id") or "default"))
            bucket["workspace_ids"].add(str(run.get("workspace_id") or "main"))
            bucket["environments"].add(str(run.get("environment") or ""))
            bucket["agents"].add(str(run.get("agent_name") or ""))
            bucket["workflows"].add(self._workflow_name(run))
            bucket["providers"].add(str(run.get("provider") or ""))
            bucket["models"].add(str(run.get("model") or ""))
            if started_at >= float(bucket["latest_started_at"]):
                bucket["latest_started_at"] = started_at
                bucket["latest_run_id"] = str(run.get("run_id") or "")
            total_spend += spend
            total_cases += cases

        items: list[dict[str, Any]] = []
        for bucket in buckets.values():
            run_count = int(bucket["run_count"])
            items.append(
                {
                    "group": bucket["group"],
                    "run_count": run_count,
                    "total_spend": round(float(bucket["total_spend"]), 6),
                    "average_spend_per_run": round((float(bucket["total_spend"]) / run_count) if run_count else 0.0, 6),
                    "total_cases": int(bucket["total_cases"]),
                    "average_cases_per_run": round((int(bucket["total_cases"]) / run_count) if run_count else 0.0, 3),
                    "latest_run_id": bucket["latest_run_id"],
                    "latest_started_at": bucket["latest_started_at"],
                    "tenant_ids": sorted(x for x in bucket["tenant_ids"] if x),
                    "workspace_ids": sorted(x for x in bucket["workspace_ids"] if x),
                    "environments": sorted(x for x in bucket["environments"] if x),
                    "agents": sorted(x for x in bucket["agents"] if x),
                    "workflows": sorted(x for x in bucket["workflows"] if x),
                    "providers": sorted(x for x in bucket["providers"] if x),
                    "models": sorted(x for x in bucket["models"] if x),
                }
            )
        items.sort(key=lambda item: (float(item.get("total_spend") or 0.0), int(item.get("run_count") or 0)), reverse=True)
        return {
            "ok": True,
            "group_by": normalized_group_by,
            "window_hours": effective_window_hours,
            "summary": {
                "run_count": len(runs),
                "total_spend": round(total_spend, 6),
                "total_cases": total_cases,
                "group_count": len(items),
            },
            "items": items[: int(limit)],
        }

    def budgets(
        self,
        gw: Any,
        *,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        settings = self._settings(gw)
        budget_defs = list(getattr(settings, "budgets", []) or [])
        items: list[dict[str, Any]] = []
        for budget in budget_defs:
            if not bool(getattr(budget, "enabled", True)):
                continue
            budget_tenant = str(getattr(budget, "tenant_id", "") or "")
            budget_workspace = str(getattr(budget, "workspace_id", "") or "")
            budget_environment = str(getattr(budget, "environment", "") or "")
            if tenant_id and budget_tenant and budget_tenant != tenant_id:
                continue
            if workspace_id and budget_workspace and budget_workspace != workspace_id:
                continue
            if environment and budget_environment and budget_environment != environment:
                continue
            window_hours = int(getattr(budget, "window_hours", self._default_window_hours(gw)) or self._default_window_hours(gw))
            runs = self._fetch_runs(
                gw,
                limit=self._default_scan_limit(gw),
                workflow_name=str(getattr(budget, "workflow_name", "") or "") or None,
                agent_name=str(getattr(budget, "agent_name", "") or "") or None,
                provider=str(getattr(budget, "provider", "") or "") or None,
                model=str(getattr(budget, "model", "") or "") or None,
                tenant_id=budget_tenant or tenant_id,
                workspace_id=budget_workspace or workspace_id,
                environment=budget_environment or environment,
                window_hours=window_hours,
            )
            current_spend = round(sum(float(run.get("total_cost") or 0.0) for run in runs), 6)
            budget_amount = float(getattr(budget, "budget_amount", 0.0) or 0.0)
            warning_threshold = float(getattr(budget, "warning_threshold", 0.8) or 0.8)
            critical_threshold = float(getattr(budget, "critical_threshold", 1.0) or 1.0)
            utilization = round((current_spend / budget_amount) if budget_amount > 0 else 0.0, 4)
            status = "ok"
            if budget_amount > 0 and utilization >= critical_threshold:
                status = "critical"
            elif budget_amount > 0 and utilization >= warning_threshold:
                status = "warning"
            items.append(
                {
                    "name": str(getattr(budget, "name", "") or "").strip() or f"budget-{len(items)+1}",
                    "group_by": self._normalize_group_by(str(getattr(budget, "group_by", "tenant") or "tenant")),
                    "window_hours": window_hours,
                    "budget_amount": round(budget_amount, 6),
                    "current_spend": current_spend,
                    "remaining_budget": round(max(budget_amount - current_spend, 0.0), 6),
                    "utilization": utilization,
                    "warning_threshold": round(warning_threshold, 4),
                    "critical_threshold": round(critical_threshold, 4),
                    "status": status,
                    "run_count": len(runs),
                    "filters": {
                        "tenant_id": budget_tenant or None,
                        "workspace_id": budget_workspace or None,
                        "environment": budget_environment or None,
                        "agent_name": str(getattr(budget, "agent_name", "") or "") or None,
                        "workflow_name": str(getattr(budget, "workflow_name", "") or "") or None,
                        "provider": str(getattr(budget, "provider", "") or "") or None,
                        "model": str(getattr(budget, "model", "") or "") or None,
                    },
                }
            )
        items.sort(key=lambda item: (float(item.get("utilization") or 0.0), float(item.get("current_spend") or 0.0)), reverse=True)
        return {"ok": True, "items": items[: int(limit)]}

    def alerts(
        self,
        gw: Any,
        *,
        severity: str = "all",
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized_severity = str(severity or "all").strip().lower()
        if normalized_severity not in {"all", "warning", "critical"}:
            normalized_severity = "all"
        budgets = self.budgets(
            gw,
            limit=max(int(limit) * 2, 50),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        alerts: list[dict[str, Any]] = []
        for item in list(budgets.get("items") or []):
            status = str(item.get("status") or "ok")
            if status == "ok":
                continue
            if normalized_severity != "all" and status != normalized_severity:
                continue
            alerts.append(
                {
                    "severity": status,
                    "budget_name": item.get("name"),
                    "message": f"Budget {item.get('name')} is at {round(float(item.get('utilization') or 0.0) * 100.0, 2)}% utilization.",
                    "current_spend": item.get("current_spend"),
                    "budget_amount": item.get("budget_amount"),
                    "remaining_budget": item.get("remaining_budget"),
                    "filters": dict(item.get("filters") or {}),
                    "window_hours": item.get("window_hours"),
                    "run_count": item.get("run_count"),
                }
            )
        alerts.sort(key=lambda item: (1 if item.get("severity") == "critical" else 0, float(item.get("current_spend") or 0.0)), reverse=True)
        return {"ok": True, "severity": normalized_severity, "items": alerts[: int(limit)]}
