from __future__ import annotations

import json
import time
import uuid
import os
from pathlib import Path
from typing import Any

import yaml

from openmiura.core.config import resolve_config_related_path


class EvaluationService:
    def _settings(self, gw: Any):
        return getattr(getattr(gw, "settings", None), "evaluations", None)

    def _suites_path(self, gw: Any) -> Path:
        settings = self._settings(gw)
        raw_path = str(getattr(settings, "suites_path", "evaluations.yaml") or "evaluations.yaml")
        config_path = getattr(gw, "config_path", "") or os.environ.get("OPENMIURA_CONFIG", "configs/openmiura.yaml")
        return resolve_config_related_path(config_path, raw_path, default_path="evaluations.yaml")

    def _load_catalog(self, gw: Any) -> dict[str, Any]:
        path = self._suites_path(gw)
        if not path.exists():
            return {"defaults": {}, "suites": {}, "path": str(path)}
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        defaults = dict(raw.get("defaults") or {})
        suites = dict(raw.get("suites") or {})
        return {"defaults": defaults, "suites": suites, "path": str(path)}

    def list_suites(self, gw: Any) -> dict[str, Any]:
        catalog = self._load_catalog(gw)
        suites_out: list[dict[str, Any]] = []
        for suite_name, suite in sorted(dict(catalog.get("suites") or {}).items()):
            suite_cfg = dict(suite or {})
            cases = list(suite_cfg.get("cases") or [])
            suites_out.append(
                {
                    "name": suite_name,
                    "description": str(suite_cfg.get("description", "") or ""),
                    "tags": [str(x).strip() for x in (suite_cfg.get("tags") or []) if str(x).strip()],
                    "use_case": self._suite_use_case(suite_name, suite_cfg),
                    "agent_name": str(suite_cfg.get("agent_name") or catalog.get("defaults", {}).get("agent_name") or ""),
                    "provider": str(suite_cfg.get("provider") or catalog.get("defaults", {}).get("provider") or ""),
                    "model": str(suite_cfg.get("model") or catalog.get("defaults", {}).get("model") or ""),
                    "is_regression_suite": bool(suite_cfg.get("is_regression_suite", True)),
                    "case_count": len(cases),
                    "cases": [
                        {
                            "id": str(case.get("id") or f"case-{idx + 1}"),
                            "name": str(case.get("name") or case.get("id") or f"Case {idx + 1}"),
                            "assertion_count": len(list(case.get("assertions") or [])),
                        }
                        for idx, case in enumerate(cases)
                    ],
                }
            )
        return {
            "ok": True,
            "path": Path(str(catalog.get("path") or self._suites_path(gw))).as_posix(),
            "defaults": dict(catalog.get("defaults") or {}),
            "suites": suites_out,
        }

    def run_suite(
        self,
        gw: Any,
        *,
        suite_name: str,
        observations: list[dict[str, Any]],
        requested_by: str = "admin",
        provider: str | None = None,
        model: str | None = None,
        agent_name: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        catalog = self._load_catalog(gw)
        suites = dict(catalog.get("suites") or {})
        if suite_name not in suites:
            return {"ok": False, "reason": "suite_not_found", "suite_name": suite_name}

        eval_settings = self._settings(gw)
        max_cases = int(getattr(eval_settings, "max_cases_per_run", 200) or 200)
        suite = dict(suites[suite_name] or {})
        cases = list(suite.get("cases") or [])
        if len(cases) > max_cases:
            return {"ok": False, "reason": "suite_too_large", "suite_name": suite_name, "max_cases_per_run": max_cases}

        defaults = dict(catalog.get("defaults") or {})
        llm_settings = getattr(getattr(gw, "settings", None), "llm", None)
        run_id = f"eval-{uuid.uuid4().hex[:12]}"
        started_at = time.time()
        provider_value = str(provider or suite.get("provider") or defaults.get("provider") or getattr(llm_settings, "provider", "") or "")
        model_value = str(model or suite.get("model") or defaults.get("model") or getattr(llm_settings, "model", "") or "")
        agent_value = str(agent_name or suite.get("agent_name") or defaults.get("agent_name") or "")

        observations_by_case: dict[str, dict[str, Any]] = {}
        for item in list(observations or []):
            if not isinstance(item, dict):
                continue
            case_id = str(item.get("case_id") or item.get("id") or "").strip()
            if case_id:
                observations_by_case[case_id] = dict(item)

        if hasattr(gw.audit, "log_evaluation_run") and getattr(eval_settings, "persist_results", True):
            gw.audit.log_evaluation_run(
                run_id=run_id,
                suite_name=suite_name,
                status="running",
                requested_by=requested_by,
                provider=provider_value,
                model=model_value,
                agent_name=agent_value,
                started_at=started_at,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )

        results: list[dict[str, Any]] = []
        assertion_totals: dict[str, dict[str, int]] = {}
        for idx, raw_case in enumerate(cases):
            case = dict(raw_case or {})
            case_id = str(case.get("id") or f"case-{idx + 1}")
            case_name = str(case.get("name") or case_id)
            observed = observations_by_case.get(case_id)
            case_result = self._evaluate_case(
                case,
                observed,
                default_latency_budget_ms=float(getattr(eval_settings, "default_latency_budget_ms", 5000.0) or 5000.0),
            )
            case_result["case_id"] = case_id
            case_result["case_name"] = case_name
            case_result["expected"] = {"assertions": list(case.get("assertions") or [])}
            results.append(case_result)
            for assertion in list(case_result.get("assertions") or []):
                kind = str(assertion.get("type") or "unknown")
                bucket = assertion_totals.setdefault(kind, {"passed": 0, "total": 0})
                bucket["total"] += 1
                if assertion.get("passed"):
                    bucket["passed"] += 1
            if hasattr(gw.audit, "log_evaluation_case_result") and getattr(eval_settings, "persist_results", True):
                gw.audit.log_evaluation_case_result(
                    run_id=run_id,
                    case_id=case_id,
                    case_name=case_name,
                    status=str(case_result.get("status") or "failed"),
                    passed=bool(case_result.get("passed")),
                    score=float(case_result.get("score") or 0.0),
                    latency_ms=float(case_result.get("latency_ms") or 0.0),
                    cost=float(case_result.get("cost") or 0.0),
                    assertions_total=int(case_result.get("assertions_total") or 0),
                    assertions_passed=int(case_result.get("assertions_passed") or 0),
                    details_json=json.dumps({"assertions": case_result.get("assertions") or [], "summary": case_result.get("summary") or ""}, ensure_ascii=False),
                    observed_json=json.dumps(case_result.get("observed") or {}, ensure_ascii=False),
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    environment=environment,
                )

        completed_at = time.time()
        scorecard = self._build_scorecard(results, assertion_totals)
        final_status = "passed" if scorecard["failed_cases"] == 0 else "failed"
        payload = {
            "ok": True,
            "run_id": run_id,
            "suite_name": suite_name,
            "status": final_status,
            "provider": provider_value,
            "model": model_value,
            "agent_name": agent_value,
            "requested_by": requested_by,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": round((completed_at - started_at) * 1000.0, 3),
            "scorecard": scorecard,
            "results": results,
            "scope": {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "environment": environment,
            },
        }
        if hasattr(gw.audit, "log_evaluation_run") and getattr(eval_settings, "persist_results", True):
            gw.audit.log_evaluation_run(
                run_id=run_id,
                suite_name=suite_name,
                status=final_status,
                requested_by=requested_by,
                provider=provider_value,
                model=model_value,
                agent_name=agent_value,
                started_at=started_at,
                completed_at=completed_at,
                total_cases=scorecard["total_cases"],
                passed_cases=scorecard["passed_cases"],
                failed_cases=scorecard["failed_cases"],
                average_latency_ms=scorecard["average_latency_ms"],
                total_cost=scorecard["total_cost"],
                scorecard_json=json.dumps(scorecard, ensure_ascii=False, sort_keys=True),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
        return payload

    def list_runs(
        self,
        gw: Any,
        *,
        limit: int = 20,
        suite_name: str | None = None,
        status: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        items = getattr(gw.audit, "list_evaluation_runs", lambda **_: [])(
            limit=limit,
            suite_name=suite_name,
            status=status,
            agent_name=agent_name,
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        return {"ok": True, "items": list(items or [])}

    def get_run(self, gw: Any, *, run_id: str) -> dict[str, Any]:
        run = getattr(gw.audit, "get_evaluation_run", lambda *_args, **_kwargs: None)(run_id)
        if run is None:
            return {"ok": False, "reason": "run_not_found", "run_id": run_id}
        results = getattr(gw.audit, "list_evaluation_case_results", lambda **_: [])(run_id=run_id)
        return {"ok": True, "run": run, "results": list(results or [])}

    def compare_runs(self, gw: Any, *, run_id: str, baseline_run_id: str | None = None) -> dict[str, Any]:
        current = getattr(gw.audit, "get_evaluation_run", lambda *_args, **_kwargs: None)(run_id)
        if current is None:
            return {"ok": False, "reason": "run_not_found", "run_id": run_id}

        baseline = None
        selection = "explicit"
        if baseline_run_id:
            baseline = getattr(gw.audit, "get_evaluation_run", lambda *_args, **_kwargs: None)(baseline_run_id)
            if baseline is None:
                return {"ok": False, "reason": "baseline_run_not_found", "run_id": run_id, "baseline_run_id": baseline_run_id}
        else:
            baseline = self._find_previous_comparable_run(gw, current)
            selection = "previous_comparable"

        if baseline is None:
            return {
                "ok": True,
                "run": current,
                "baseline_run": None,
                "comparison_mode": selection,
                "summary": {"has_baseline": False},
                "regressions": [],
                "improvements": [],
                "changed_cases": [],
            }

        current_results = list(getattr(gw.audit, "list_evaluation_case_results", lambda **_: [])(run_id=current["run_id"]) or [])
        baseline_results = list(getattr(gw.audit, "list_evaluation_case_results", lambda **_: [])(run_id=baseline["run_id"]) or [])
        current_by_case = {str(item.get("case_id") or ""): dict(item) for item in current_results if item.get("case_id")}
        baseline_by_case = {str(item.get("case_id") or ""): dict(item) for item in baseline_results if item.get("case_id")}

        regressions: list[dict[str, Any]] = []
        improvements: list[dict[str, Any]] = []
        changed_cases: list[dict[str, Any]] = []
        for case_id in sorted(set(current_by_case.keys()) | set(baseline_by_case.keys())):
            cur_case = current_by_case.get(case_id)
            base_case = baseline_by_case.get(case_id)
            cur_passed = bool(cur_case.get("passed")) if cur_case is not None else False
            base_passed = bool(base_case.get("passed")) if base_case is not None else False
            if cur_case is None or base_case is None or cur_passed != base_passed:
                change = {
                    "case_id": case_id,
                    "case_name": str((cur_case or base_case or {}).get("case_name") or case_id),
                    "current_status": cur_case.get("status") if cur_case else "missing",
                    "baseline_status": base_case.get("status") if base_case else "missing",
                    "current_passed": cur_passed if cur_case is not None else None,
                    "baseline_passed": base_passed if base_case is not None else None,
                }
                changed_cases.append(change)
                if base_case is not None and cur_case is not None:
                    if base_passed and not cur_passed:
                        regressions.append(change)
                    elif not base_passed and cur_passed:
                        improvements.append(change)
                elif base_case is None and cur_case is not None and not cur_passed:
                    regressions.append(change)

        current_scorecard = dict(current.get("scorecard") or {})
        baseline_scorecard = dict(baseline.get("scorecard") or {})
        summary = {
            "has_baseline": True,
            "current_run_id": current.get("run_id"),
            "baseline_run_id": baseline.get("run_id"),
            "pass_rate_delta": round(float(current_scorecard.get("pass_rate") or 0.0) - float(baseline_scorecard.get("pass_rate") or 0.0), 4),
            "failed_cases_delta": int(current_scorecard.get("failed_cases") or 0) - int(baseline_scorecard.get("failed_cases") or 0),
            "average_latency_ms_delta": round(float(current_scorecard.get("average_latency_ms") or 0.0) - float(baseline_scorecard.get("average_latency_ms") or 0.0), 3),
            "total_cost_delta": round(float(current_scorecard.get("total_cost") or 0.0) - float(baseline_scorecard.get("total_cost") or 0.0), 6),
            "regression_count": len(regressions),
            "improvement_count": len(improvements),
            "changed_case_count": len(changed_cases),
            "is_regression": bool(regressions or (float(current_scorecard.get("pass_rate") or 0.0) < float(baseline_scorecard.get("pass_rate") or 0.0))),
        }
        return {
            "ok": True,
            "comparison_mode": selection,
            "run": current,
            "baseline_run": baseline,
            "summary": summary,
            "regressions": regressions,
            "improvements": improvements,
            "changed_cases": changed_cases,
        }

    def list_regressions(
        self,
        gw: Any,
        *,
        limit: int = 20,
        suite_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scan_limit = max(int(limit) * 8, 100)
        runs = list(
            getattr(gw.audit, "list_evaluation_runs", lambda **_: [])(
                limit=min(scan_limit, 1000),
                suite_name=suite_name,
                agent_name=agent_name,
                provider=provider,
                model=model,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            or []
        )
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for item in runs:
            key = self._comparison_key(item)
            grouped.setdefault(key, []).append(dict(item))

        regressions: list[dict[str, Any]] = []
        for key, group_runs in grouped.items():
            ordered = sorted(group_runs, key=lambda item: float(item.get("started_at") or 0.0), reverse=True)
            if len(ordered) < 2:
                continue
            latest = ordered[0]
            previous = ordered[1]
            comparison = self.compare_runs(gw, run_id=str(latest.get("run_id") or ""), baseline_run_id=str(previous.get("run_id") or ""))
            summary = dict(comparison.get("summary") or {})
            if not summary.get("has_baseline"):
                continue
            if not summary.get("is_regression"):
                continue
            regressions.append(
                {
                    "group": {
                        "suite_name": key[0],
                        "agent_name": key[1],
                        "provider": key[2],
                        "model": key[3],
                        "tenant_id": key[4],
                        "workspace_id": key[5],
                        "environment": key[6],
                    },
                    "run_id": latest.get("run_id"),
                    "baseline_run_id": previous.get("run_id"),
                    "summary": summary,
                    "regressions": list(comparison.get("regressions") or []),
                    "improvements": list(comparison.get("improvements") or []),
                }
            )

        regressions.sort(
            key=lambda item: (
                int(item.get("summary", {}).get("regression_count") or 0),
                int(item.get("summary", {}).get("failed_cases_delta") or 0),
                abs(float(item.get("summary", {}).get("pass_rate_delta") or 0.0)),
            ),
            reverse=True,
        )
        return {"ok": True, "items": regressions[: int(limit)]}

    def scorecards(
        self,
        gw: Any,
        *,
        group_by: str = "agent_provider_model",
        limit: int = 20,
        suite_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scan_limit = max(int(limit) * 10, 100)
        runs = list(
            getattr(gw.audit, "list_evaluation_runs", lambda **_: [])(
                limit=min(scan_limit, 1000),
                suite_name=suite_name,
                agent_name=agent_name,
                provider=provider,
                model=model,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            or []
        )
        allowed_groupings = {"agent", "provider", "model", "agent_provider_model", "suite"}
        normalized_group_by = str(group_by or "agent_provider_model").strip().lower()
        if normalized_group_by not in allowed_groupings:
            normalized_group_by = "agent_provider_model"

        buckets: dict[str, dict[str, Any]] = {}
        for run in runs:
            group_value = self._group_value(run, normalized_group_by)
            bucket = buckets.setdefault(
                group_value,
                {
                    "group_by": normalized_group_by,
                    "group": group_value,
                    "run_count": 0,
                    "passed_runs": 0,
                    "failed_runs": 0,
                    "total_cases": 0,
                    "passed_cases": 0,
                    "failed_cases": 0,
                    "total_cost": 0.0,
                    "latency_sum_ms": 0.0,
                    "latest_run_id": None,
                    "latest_started_at": None,
                    "suite_names": set(),
                    "agents": set(),
                    "providers": set(),
                    "models": set(),
                },
            )
            bucket["run_count"] += 1
            if str(run.get("status") or "") == "passed":
                bucket["passed_runs"] += 1
            else:
                bucket["failed_runs"] += 1
            bucket["total_cases"] += int(run.get("total_cases") or 0)
            bucket["passed_cases"] += int(run.get("passed_cases") or 0)
            bucket["failed_cases"] += int(run.get("failed_cases") or 0)
            bucket["total_cost"] += float(run.get("total_cost") or 0.0)
            bucket["latency_sum_ms"] += float(run.get("average_latency_ms") or 0.0)
            bucket["suite_names"].add(str(run.get("suite_name") or ""))
            bucket["agents"].add(str(run.get("agent_name") or ""))
            bucket["providers"].add(str(run.get("provider") or ""))
            bucket["models"].add(str(run.get("model") or ""))
            started_at = float(run.get("started_at") or 0.0)
            if bucket["latest_started_at"] is None or started_at > float(bucket["latest_started_at"] or 0.0):
                bucket["latest_started_at"] = started_at
                bucket["latest_run_id"] = run.get("run_id")

        items: list[dict[str, Any]] = []
        for bucket in buckets.values():
            total_cases = int(bucket["total_cases"])
            run_count = int(bucket["run_count"])
            items.append(
                {
                    "group_by": bucket["group_by"],
                    "group": bucket["group"],
                    "run_count": run_count,
                    "passed_runs": int(bucket["passed_runs"]),
                    "failed_runs": int(bucket["failed_runs"]),
                    "run_pass_rate": round((int(bucket["passed_runs"]) / run_count) if run_count else 0.0, 4),
                    "total_cases": total_cases,
                    "passed_cases": int(bucket["passed_cases"]),
                    "failed_cases": int(bucket["failed_cases"]),
                    "case_pass_rate": round((int(bucket["passed_cases"]) / total_cases) if total_cases else 0.0, 4),
                    "average_latency_ms": round((float(bucket["latency_sum_ms"]) / run_count) if run_count else 0.0, 3),
                    "total_cost": round(float(bucket["total_cost"]), 6),
                    "latest_run_id": bucket["latest_run_id"],
                    "latest_started_at": bucket["latest_started_at"],
                    "suite_names": sorted(x for x in bucket["suite_names"] if x),
                    "agents": sorted(x for x in bucket["agents"] if x),
                    "providers": sorted(x for x in bucket["providers"] if x),
                    "models": sorted(x for x in bucket["models"] if x),
                }
            )
        items.sort(key=lambda item: (float(item.get("case_pass_rate") or 0.0), int(item.get("run_count") or 0)), reverse=True)
        return {"ok": True, "group_by": normalized_group_by, "items": items[: int(limit)]}

    def leaderboard(
        self,
        gw: Any,
        *,
        group_by: str = "agent_provider_model",
        rank_by: str = "stability_score",
        limit: int = 20,
        use_case: str | None = None,
        suite_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scan_limit = max(int(limit) * 20, 100)
        runs = self._fetch_annotated_runs(
            gw,
            limit=min(scan_limit, 2000),
            suite_name=suite_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            use_case=use_case,
        )
        normalized_group_by = self._normalize_leaderboard_group_by(group_by)
        normalized_rank_by = self._normalize_leaderboard_rank_by(rank_by)
        items = self._build_leaderboard_items(gw, runs=runs, group_by=normalized_group_by, rank_by=normalized_rank_by)
        return {
            "ok": True,
            "group_by": normalized_group_by,
            "rank_by": normalized_rank_by,
            "summary": {
                "run_count": len(runs),
                "entity_count": len(items),
                "use_case": str(use_case or "").strip() or None,
                "leader": items[0] if items else None,
            },
            "items": items[: int(limit)],
        }

    def comparison(
        self,
        gw: Any,
        *,
        split_by: str = "use_case",
        compare_by: str = "agent_provider_model",
        rank_by: str = "stability_score",
        limit_groups: int = 20,
        limit_per_group: int = 5,
        suite_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized_split_by = self._normalize_comparison_split_by(split_by)
        normalized_compare_by = self._normalize_leaderboard_group_by(compare_by)
        normalized_rank_by = self._normalize_leaderboard_rank_by(rank_by)
        scan_limit = max(int(limit_groups) * int(limit_per_group) * 10, 100)
        runs = self._fetch_annotated_runs(
            gw,
            limit=min(scan_limit, 4000),
            suite_name=suite_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

        split_buckets: dict[str, list[dict[str, Any]]] = {}
        for run in runs:
            split_value = self._comparison_split_value(run, normalized_split_by)
            split_buckets.setdefault(split_value, []).append(run)

        groups: list[dict[str, Any]] = []
        for split_value, group_runs in split_buckets.items():
            leaderboard_items = self._build_leaderboard_items(
                gw,
                runs=group_runs,
                group_by=normalized_compare_by,
                rank_by=normalized_rank_by,
            )
            if not leaderboard_items:
                continue
            groups.append(
                {
                    "split_by": normalized_split_by,
                    "group": split_value,
                    "leader": leaderboard_items[0],
                    "summary": {
                        "run_count": len(group_runs),
                        "entity_count": len(leaderboard_items),
                    },
                    "items": leaderboard_items[: int(limit_per_group)],
                }
            )

        groups.sort(
            key=lambda item: (
                float(item.get("leader", {}).get(normalized_rank_by) or 0.0),
                int(item.get("summary", {}).get("run_count") or 0),
            ),
            reverse=normalized_rank_by not in {"average_latency_ms", "average_cost_per_run", "regression_events", "regression_cases"},
        )
        return {
            "ok": True,
            "split_by": normalized_split_by,
            "compare_by": normalized_compare_by,
            "rank_by": normalized_rank_by,
            "summary": {
                "run_count": len(runs),
                "group_count": len(groups),
                "top_group": groups[0]["group"] if groups else None,
            },
            "groups": groups[: int(limit_groups)],
        }

    def _fetch_annotated_runs(
        self,
        gw: Any,
        *,
        limit: int,
        suite_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        use_case: str | None = None,
    ) -> list[dict[str, Any]]:
        items = list(
            getattr(gw.audit, "list_evaluation_runs", lambda **_: [])(
                limit=max(1, int(limit)),
                suite_name=suite_name,
                agent_name=agent_name,
                provider=provider,
                model=model,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            or []
        )
        catalog = self._suite_catalog_map(gw)
        use_case_norm = str(use_case or "").strip().lower()
        annotated: list[dict[str, Any]] = []
        for raw in items:
            run = dict(raw or {})
            suite_meta = dict(catalog.get(str(run.get("suite_name") or "")) or {})
            run["use_case"] = str(suite_meta.get("use_case") or self._suite_use_case(str(run.get("suite_name") or ""), {}))
            run["suite_tags"] = list(suite_meta.get("tags") or [])
            run["suite_description"] = str(suite_meta.get("description") or "")
            if use_case_norm and str(run.get("use_case") or "").strip().lower() != use_case_norm:
                continue
            annotated.append(run)
        return annotated

    def _build_leaderboard_items(
        self,
        gw: Any,
        *,
        runs: list[dict[str, Any]],
        group_by: str,
        rank_by: str,
    ) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for run in runs:
            group_value = self._leaderboard_group_value(run, group_by)
            bucket = buckets.setdefault(
                group_value,
                {
                    "group_by": group_by,
                    "group": group_value,
                    "run_count": 0,
                    "passed_runs": 0,
                    "failed_runs": 0,
                    "total_cases": 0,
                    "passed_cases": 0,
                    "failed_cases": 0,
                    "latency_sum_ms": 0.0,
                    "total_cost": 0.0,
                    "latest_run_id": None,
                    "latest_started_at": None,
                    "suite_names": set(),
                    "use_cases": set(),
                    "agents": set(),
                    "providers": set(),
                    "models": set(),
                    "runs": [],
                },
            )
            bucket["run_count"] += 1
            if str(run.get("status") or "") == "passed":
                bucket["passed_runs"] += 1
            else:
                bucket["failed_runs"] += 1
            bucket["total_cases"] += int(run.get("total_cases") or 0)
            bucket["passed_cases"] += int(run.get("passed_cases") or 0)
            bucket["failed_cases"] += int(run.get("failed_cases") or 0)
            bucket["latency_sum_ms"] += float(run.get("average_latency_ms") or 0.0)
            bucket["total_cost"] += float(run.get("total_cost") or 0.0)
            bucket["suite_names"].add(str(run.get("suite_name") or ""))
            bucket["use_cases"].add(str(run.get("use_case") or "general"))
            bucket["agents"].add(str(run.get("agent_name") or ""))
            bucket["providers"].add(str(run.get("provider") or ""))
            bucket["models"].add(str(run.get("model") or ""))
            bucket["runs"].append(run)
            started_at = float(run.get("started_at") or 0.0)
            if bucket["latest_started_at"] is None or started_at > float(bucket["latest_started_at"] or 0.0):
                bucket["latest_started_at"] = started_at
                bucket["latest_run_id"] = str(run.get("run_id") or "")

        items: list[dict[str, Any]] = []
        for bucket in buckets.values():
            run_count = int(bucket["run_count"])
            total_cases = int(bucket["total_cases"])
            average_latency_ms = round((float(bucket["latency_sum_ms"]) / run_count) if run_count else 0.0, 3)
            total_cost = round(float(bucket["total_cost"]), 6)
            average_cost_per_run = round((float(bucket["total_cost"]) / run_count) if run_count else 0.0, 6)
            run_pass_rate = round((int(bucket["passed_runs"]) / run_count) if run_count else 0.0, 4)
            case_pass_rate = round((int(bucket["passed_cases"]) / total_cases) if total_cases else 0.0, 4)
            regression_events = 0
            regression_cases = 0
            improvement_cases = 0
            latest_comparison_summary = None
            latest_comparison_started_at = None
            grouped_runs: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
            for run in list(bucket.get("runs") or []):
                grouped_runs.setdefault(self._comparison_key(run), []).append(run)
            for grouped in grouped_runs.values():
                ordered = sorted(grouped, key=lambda item: float(item.get("started_at") or 0.0), reverse=True)
                if len(ordered) < 2:
                    continue
                comparison = self.compare_runs(
                    gw,
                    run_id=str(ordered[0].get("run_id") or ""),
                    baseline_run_id=str(ordered[1].get("run_id") or ""),
                )
                summary = dict(comparison.get("summary") or {})
                regression_events += 1 if summary.get("is_regression") else 0
                regression_cases += int(summary.get("regression_count") or 0)
                improvement_cases += int(summary.get("improvement_count") or 0)
                latest_started_at = float(ordered[0].get("started_at") or 0.0)
                if latest_comparison_started_at is None or latest_started_at > float(latest_comparison_started_at or 0.0):
                    latest_comparison_started_at = latest_started_at
                    latest_comparison_summary = summary
            stability_score = round(((case_pass_rate * 0.7) + (run_pass_rate * 0.2) + ((1.0 / (1 + regression_events)) * 0.1)) * 100.0, 3)
            items.append(
                {
                    "group_by": bucket["group_by"],
                    "group": bucket["group"],
                    "run_count": run_count,
                    "passed_runs": int(bucket["passed_runs"]),
                    "failed_runs": int(bucket["failed_runs"]),
                    "run_pass_rate": run_pass_rate,
                    "total_cases": total_cases,
                    "passed_cases": int(bucket["passed_cases"]),
                    "failed_cases": int(bucket["failed_cases"]),
                    "case_pass_rate": case_pass_rate,
                    "average_latency_ms": average_latency_ms,
                    "total_cost": total_cost,
                    "average_cost_per_run": average_cost_per_run,
                    "regression_events": regression_events,
                    "regression_cases": regression_cases,
                    "improvement_cases": improvement_cases,
                    "latest_regression": bool((latest_comparison_summary or {}).get("is_regression", False)),
                    "latest_comparison": latest_comparison_summary,
                    "stability_score": stability_score,
                    "latest_run_id": bucket["latest_run_id"],
                    "latest_started_at": bucket["latest_started_at"],
                    "suite_names": sorted(x for x in bucket["suite_names"] if x),
                    "use_cases": sorted(x for x in bucket["use_cases"] if x),
                    "agents": sorted(x for x in bucket["agents"] if x),
                    "providers": sorted(x for x in bucket["providers"] if x),
                    "models": sorted(x for x in bucket["models"] if x),
                }
            )
        self._sort_leaderboard_items(items, rank_by=rank_by)
        for idx, item in enumerate(items, start=1):
            item["rank"] = idx
            item["rank_by"] = rank_by
            item["rank_value"] = item.get(rank_by)
        return items

    def _suite_catalog_map(self, gw: Any) -> dict[str, dict[str, Any]]:
        catalog = self._load_catalog(gw)
        suites = dict(catalog.get("suites") or {})
        mapped: dict[str, dict[str, Any]] = {}
        for suite_name, suite in suites.items():
            suite_cfg = dict(suite or {})
            mapped[str(suite_name)] = {
                "use_case": self._suite_use_case(str(suite_name), suite_cfg),
                "tags": [str(x).strip() for x in (suite_cfg.get("tags") or []) if str(x).strip()],
                "description": str(suite_cfg.get("description") or ""),
            }
        return mapped

    def _suite_use_case(self, suite_name: str, suite_cfg: dict[str, Any]) -> str:
        explicit = str((suite_cfg or {}).get("use_case") or "").strip()
        if explicit:
            return explicit
        tags = [str(x).strip() for x in ((suite_cfg or {}).get("tags") or []) if str(x).strip()]
        generic = {"smoke", "ci", "regression", "baseline", "eval", "evaluation", "tests", "qa"}
        for tag in tags:
            if tag.lower() not in generic:
                return tag
        normalized = str(suite_name or "general").strip().replace("_", " ").replace("-", " ")
        return normalized or "general"

    def _normalize_leaderboard_group_by(self, group_by: str) -> str:
        allowed_groupings = {"agent", "provider", "model", "agent_provider_model", "suite", "use_case", "use_case_agent_model"}
        normalized = str(group_by or "agent_provider_model").strip().lower()
        return normalized if normalized in allowed_groupings else "agent_provider_model"

    def _normalize_leaderboard_rank_by(self, rank_by: str) -> str:
        allowed = {
            "stability_score",
            "case_pass_rate",
            "run_pass_rate",
            "run_count",
            "average_latency_ms",
            "average_cost_per_run",
            "regression_events",
            "regression_cases",
            "total_cost",
        }
        normalized = str(rank_by or "stability_score").strip().lower()
        return normalized if normalized in allowed else "stability_score"

    def _normalize_comparison_split_by(self, split_by: str) -> str:
        allowed = {"use_case", "suite", "agent", "model", "provider"}
        normalized = str(split_by or "use_case").strip().lower()
        return normalized if normalized in allowed else "use_case"

    def _comparison_split_value(self, run: dict[str, Any], split_by: str) -> str:
        if split_by == "suite":
            return str(run.get("suite_name") or "unknown-suite")
        if split_by == "agent":
            return str(run.get("agent_name") or "unassigned-agent")
        if split_by == "model":
            return str(run.get("model") or "unknown-model")
        if split_by == "provider":
            return str(run.get("provider") or "unknown-provider")
        return str(run.get("use_case") or "general")

    def _leaderboard_group_value(self, run: dict[str, Any], group_by: str) -> str:
        if group_by == "use_case":
            return str(run.get("use_case") or "general")
        if group_by == "use_case_agent_model":
            return " / ".join(
                [
                    str(run.get("use_case") or "general"),
                    str(run.get("agent_name") or "unassigned-agent"),
                    str(run.get("model") or "unknown-model"),
                ]
            )
        return self._group_value(run, group_by)

    def _sort_leaderboard_items(self, items: list[dict[str, Any]], *, rank_by: str) -> None:
        descending = rank_by not in {"average_latency_ms", "average_cost_per_run", "regression_events", "regression_cases", "total_cost"}
        if descending:
            items.sort(
                key=lambda item: (
                    float(item.get(rank_by) or 0.0),
                    float(item.get("case_pass_rate") or 0.0),
                    float(item.get("run_pass_rate") or 0.0),
                    -float(item.get("average_latency_ms") or 0.0),
                    -float(item.get("average_cost_per_run") or 0.0),
                ),
                reverse=True,
            )
            return
        items.sort(
            key=lambda item: (
                float(item.get(rank_by) or 0.0),
                -float(item.get("case_pass_rate") or 0.0),
                -float(item.get("run_pass_rate") or 0.0),
                int(item.get("run_count") or 0) * -1,
            )
        )

    def _find_previous_comparable_run(self, gw: Any, current: dict[str, Any]) -> dict[str, Any] | None:
        candidates = list(
            getattr(gw.audit, "list_evaluation_runs", lambda **_: [])(
                limit=200,
                suite_name=current.get("suite_name"),
                agent_name=current.get("agent_name"),
                provider=current.get("provider"),
                model=current.get("model"),
                tenant_id=current.get("tenant_id"),
                workspace_id=current.get("workspace_id"),
                environment=current.get("environment"),
            )
            or []
        )
        current_run_id = str(current.get("run_id") or "")
        current_started_at = float(current.get("started_at") or 0.0)
        older = [item for item in candidates if str(item.get("run_id") or "") != current_run_id and float(item.get("started_at") or 0.0) <= current_started_at]
        older.sort(key=lambda item: float(item.get("started_at") or 0.0), reverse=True)
        return dict(older[0]) if older else None

    def _comparison_key(self, run: dict[str, Any]) -> tuple[Any, ...]:
        return (
            str(run.get("suite_name") or ""),
            str(run.get("agent_name") or ""),
            str(run.get("provider") or ""),
            str(run.get("model") or ""),
            str(run.get("tenant_id") or ""),
            str(run.get("workspace_id") or ""),
            str(run.get("environment") or ""),
        )

    def _group_value(self, run: dict[str, Any], group_by: str) -> str:
        if group_by == "agent":
            return str(run.get("agent_name") or "unassigned-agent")
        if group_by == "provider":
            return str(run.get("provider") or "unknown-provider")
        if group_by == "model":
            return str(run.get("model") or "unknown-model")
        if group_by == "suite":
            return str(run.get("suite_name") or "unknown-suite")
        return " / ".join(
            [
                str(run.get("agent_name") or "unassigned-agent"),
                str(run.get("provider") or "unknown-provider"),
                str(run.get("model") or "unknown-model"),
            ]
        )

    def _evaluate_case(self, case: dict[str, Any], observed: dict[str, Any] | None, *, default_latency_budget_ms: float) -> dict[str, Any]:
        observation = dict(observed or {})
        assertions = list(case.get("assertions") or [])
        if observed is None:
            return {
                "status": "missing_observation",
                "passed": False,
                "score": 0.0,
                "assertions_total": len(assertions),
                "assertions_passed": 0,
                "assertions": [
                    {
                        "type": str(item.get("type") or "unknown"),
                        "passed": False,
                        "reason": "missing_observation",
                    }
                    for item in assertions
                ],
                "latency_ms": 0.0,
                "cost": 0.0,
                "observed": {},
                "summary": "No observation supplied for case.",
            }

        if not assertions:
            assertions = [{"type": "contains", "expected": str(case.get("expected_contains", "") or "")}]

        results: list[dict[str, Any]] = []
        passed = 0
        for assertion in assertions:
            result = self._evaluate_assertion(assertion, observation, default_latency_budget_ms=default_latency_budget_ms)
            results.append(result)
            if result["passed"]:
                passed += 1
        total = len(results)
        score = round((passed / total) if total else 0.0, 4)
        return {
            "status": "passed" if passed == total else "failed",
            "passed": passed == total,
            "score": score,
            "assertions_total": total,
            "assertions_passed": passed,
            "assertions": results,
            "latency_ms": float(observation.get("latency_ms") or 0.0),
            "cost": float(observation.get("cost") or 0.0),
            "observed": observation,
            "summary": f"{passed}/{total} assertions passed" if total else "No assertions",
        }

    def _evaluate_assertion(self, assertion: dict[str, Any], observed: dict[str, Any], *, default_latency_budget_ms: float) -> dict[str, Any]:
        assertion_type = str(assertion.get("type") or "unknown").strip().lower()
        response_text = str(observed.get("response_text") or "")
        tools_used = [str(x).strip().lower() for x in (observed.get("tools_used") or []) if str(x).strip()]
        expected = assertion.get("expected")
        passed = False
        reason = ""

        if assertion_type == "exact_match":
            passed = response_text.strip() == str(expected or "").strip()
            reason = f"response_text == {expected!r}"
        elif assertion_type == "contains":
            expected_text = str(expected or "")
            passed = expected_text in response_text
            reason = f"response_text contains {expected_text!r}"
        elif assertion_type == "any_of":
            values = [str(x) for x in (assertion.get("values") or [])]
            passed = response_text.strip() in {item.strip() for item in values}
            reason = "response_text in allowed values"
        elif assertion_type == "tool_used":
            tool_name = str(assertion.get("tool_name") or expected or "").strip().lower()
            passed = tool_name in tools_used
            reason = f"tool {tool_name!r} used"
        elif assertion_type == "tool_not_used":
            tool_name = str(assertion.get("tool_name") or expected or "").strip().lower()
            passed = tool_name not in tools_used
            reason = f"tool {tool_name!r} not used"
        elif assertion_type == "policy_adherence":
            should_be = bool(assertion.get("expected", True))
            passed = bool(observed.get("policy_ok")) is should_be
            reason = f"policy_ok == {should_be}"
        elif assertion_type == "latency_max_ms":
            max_ms = float(assertion.get("max_ms") or assertion.get("expected") or default_latency_budget_ms)
            passed = float(observed.get("latency_ms") or 0.0) <= max_ms
            reason = f"latency_ms <= {max_ms}"
        elif assertion_type == "cost_max":
            max_cost = float(assertion.get("max_cost") or assertion.get("expected") or 0.0)
            passed = float(observed.get("cost") or 0.0) <= max_cost
            reason = f"cost <= {max_cost}"
        elif assertion_type == "rubric_min_score":
            min_score = float(assertion.get("min_score") or assertion.get("expected") or 0.0)
            passed = float(observed.get("rubric_score") or 0.0) >= min_score
            reason = f"rubric_score >= {min_score}"
        else:
            reason = f"unsupported assertion type: {assertion_type}"
            passed = False

        return {
            "type": assertion_type,
            "passed": bool(passed),
            "reason": reason,
        }

    def _build_scorecard(self, results: list[dict[str, Any]], assertion_totals: dict[str, dict[str, int]]) -> dict[str, Any]:
        total_cases = len(results)
        passed_cases = sum(1 for item in results if item.get("passed"))
        failed_cases = total_cases - passed_cases
        total_latency = sum(float(item.get("latency_ms") or 0.0) for item in results)
        total_cost = sum(float(item.get("cost") or 0.0) for item in results)
        return {
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "failed_cases": failed_cases,
            "pass_rate": round((passed_cases / total_cases) if total_cases else 0.0, 4),
            "average_latency_ms": round((total_latency / total_cases) if total_cases else 0.0, 3),
            "total_cost": round(total_cost, 6),
            "assertions": {
                key: {
                    "passed": int(value.get("passed") or 0),
                    "total": int(value.get("total") or 0),
                    "pass_rate": round((int(value.get("passed") or 0) / int(value.get("total") or 1)), 4) if int(value.get("total") or 0) else 0.0,
                }
                for key, value in sorted(assertion_totals.items())
            },
            "failing_cases": [
                {
                    "case_id": item.get("case_id"),
                    "case_name": item.get("case_name"),
                    "status": item.get("status"),
                    "summary": item.get("summary"),
                }
                for item in results
                if not item.get("passed")
            ],
        }
