from __future__ import annotations

import json
from pathlib import Path

import yaml


def test_observability_assets_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "ops" / "prometheus" / "prometheus.yml").exists()
    assert (root / "ops" / "prometheus" / "rules" / "openmiura_alerts.yml").exists()
    assert (root / "ops" / "alertmanager" / "alertmanager.yml").exists()
    assert (root / "ops" / "grafana" / "provisioning" / "datasources" / "prometheus.yml").exists()
    assert (root / "ops" / "grafana" / "provisioning" / "dashboards" / "dashboards.yml").exists()
    assert (root / "ops" / "grafana" / "dashboards" / "openmiura-operations-overview.json").exists()
    assert (root / "ops" / "grafana" / "dashboards" / "openmiura-channel-tool-ops.json").exists()


def test_prometheus_alert_rules_and_grafana_dashboards_are_parseable() -> None:
    root = Path(__file__).resolve().parents[1]
    prom = yaml.safe_load((root / "ops" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((root / "ops" / "prometheus" / "rules" / "openmiura_alerts.yml").read_text(encoding="utf-8"))
    ds = yaml.safe_load((root / "ops" / "grafana" / "provisioning" / "datasources" / "prometheus.yml").read_text(encoding="utf-8"))
    dashprov = yaml.safe_load((root / "ops" / "grafana" / "provisioning" / "dashboards" / "dashboards.yml").read_text(encoding="utf-8"))
    dash1 = json.loads((root / "ops" / "grafana" / "dashboards" / "openmiura-operations-overview.json").read_text(encoding="utf-8"))
    dash2 = json.loads((root / "ops" / "grafana" / "dashboards" / "openmiura-channel-tool-ops.json").read_text(encoding="utf-8"))

    assert prom["scrape_configs"][0]["job_name"] == "openmiura"
    alert_names = {rule["alert"] for group in rules["groups"] for rule in group["rules"]}
    assert "OpenMiuraTargetDown" in alert_names
    assert "OpenMiuraHighErrorRate" in alert_names
    assert ds["datasources"][0]["url"] == "http://prometheus:9090"
    assert dashprov["providers"][0]["options"]["path"] == "/var/lib/grafana/dashboards"
    assert dash1["title"] == "openMiura Operations Overview"
    assert dash2["title"] == "openMiura Channel & Tool Operations"


def test_docker_compose_includes_observability_services() -> None:
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "prometheus:" in compose
    assert "grafana:" in compose
    assert "alertmanager:" in compose
    assert 'profiles: ["observability"]' in compose
