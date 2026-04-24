from __future__ import annotations

import json
from pathlib import Path

from openmiura.demo.canonical_case import build_self_contained_demo_report, write_demo_report


def test_canonical_demo_report_proves_governed_runtime_flow(tmp_path: Path) -> None:
    report = build_self_contained_demo_report()

    assert report['success'] is True
    assert report['validation']['approval_required'] is True
    assert report['validation']['blocked_before_approval'] is True
    assert report['validation']['pending_approval_visible'] is True
    assert report['validation']['canvas_operator_action_visible'] is True
    assert report['validation']['executed_after_approval'] is True
    assert report['validation']['signed_release_present'] is True
    assert report['validation']['runtime_timeline_available'] is True
    assert report['validation']['admin_events_available'] is True
    assert report['validation']['current_version_matches'] is True

    activation = report['steps']['governance_activation_requested']
    assert activation['approval_required'] is True
    assert activation['version']['status'] == 'pending_approval'
    assert activation['approval']['status'] == 'pending'
    assert activation['runtime_summary']['alert_governance_policy']['quiet_hours']['enabled'] is False

    inspector = report['steps']['canvas_inspector']
    assert 'approve_governance_promotion' in inspector['available_actions']

    approval_result = report['steps']['canvas_approval_result']['result']
    assert approval_result['approval']['status'] == 'approved'
    assert approval_result['version']['status'] == 'active'
    assert approval_result['version']['release']['signed'] is True

    versions = report['steps']['versions_after_approval']
    assert versions['current_version']['version_id'] == report['demo']['version_id']
    assert versions['current_version']['release']['signed'] is True


def test_canonical_demo_report_can_be_written_to_json(tmp_path: Path) -> None:
    report = build_self_contained_demo_report()
    target = write_demo_report(tmp_path / 'canonical-demo-report.json', report)
    payload = json.loads(target.read_text(encoding='utf-8'))
    assert payload['demo']['name'] == 'Governed runtime alert policy activation'
    assert payload['success'] is True
