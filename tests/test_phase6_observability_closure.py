from __future__ import annotations

from pathlib import Path

import yaml

from scripts.fire_test_alerts import load_payload

ROOT = Path(__file__).resolve().parents[1]


def test_alert_rules_include_runbooks() -> None:
    rules = yaml.safe_load((ROOT / "ops/prometheus/rules/openmiura_alerts.yml").read_text(encoding="utf-8"))
    group = rules["groups"][0]
    assert group["rules"]
    for rule in group["rules"]:
        assert "runbook_url" in rule.get("annotations", {})


def test_fire_test_alert_payload_is_valid() -> None:
    payload = load_payload(ROOT / "ops/alertmanager/testdata/sample_alerts.json")
    assert len(payload) >= 2
    assert payload[0]["labels"]["severity"] == "critical"
    assert payload[1]["labels"]["severity"] == "warning"


def test_dashboard_files_present() -> None:
    dashboards = {
        p.name for p in (ROOT / "ops/grafana/dashboards").glob("*.json")
    }
    assert "openmiura-operations-overview.json" in dashboards
    assert "openmiura-channel-tool-ops.json" in dashboards
    assert "openmiura-latency-capacity.json" in dashboards
    assert "openmiura-security-broker.json" in dashboards


def test_alertmanager_renderer_mentions_real_receivers() -> None:
    script = (ROOT / "ops/alertmanager/render_alertmanager_config.sh").read_text(encoding="utf-8")
    assert "slack-primary" in script
    assert "email-primary" in script
    assert "webhook-primary" in script


def test_runbooks_cover_primary_alerts() -> None:
    content = (ROOT / "docs/runbooks/alerts.md").read_text(encoding="utf-8").lower()
    for anchor in [
        "openmiuratargetdown",
        "openmiurahigherrorrate",
        "openmiurahighlatencyp95",
        "openmiuratoolerrorsburst",
        "openmiurabrokerauthfailures",
    ]:
        assert anchor in content
