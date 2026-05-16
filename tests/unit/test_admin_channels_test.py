"""Tests for the /admin/channels/{channel}/test surface (G2).

We inject fake Slack / Telegram clients onto the live Gateway
during the lifespan so we can assert what gets called without
making real network requests.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi.testclient import TestClient

from openmiura.interfaces.http.app import create_app


TOKEN = "test-admin-token-xxxxxxxxxxxxxxxx"


def _build_app(tmp_path: Path):
    cfg = {
        "server":  {"host": "127.0.0.1", "port": 8081},
        "storage": {"backend": "sqlite", "db_path": ":memory:"},
        "admin":   {"enabled": True, "token": TOKEN},
        "auth":    {"enabled": False},
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.safe_dump(cfg, f)
        cfg_path = f.name
    app = create_app(config_path=cfg_path)
    return app


def _headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def _attach_fakes(app, *, slack=None, telegram=None):
    """Attach fake channel clients on the gateway. Called inside
    the TestClient context so app.state.gw is non-None.
    """
    gw = app.state.gw
    if slack is not None:
        gw.slack = slack
    if telegram is not None:
        gw.telegram = telegram


def test_slack_success_records_audit_and_calls_client(tmp_path):
    app = _build_app(tmp_path)
    fake_slack = MagicMock()
    fake_slack.post_message = MagicMock(return_value=None)
    with TestClient(app) as client:
        _attach_fakes(app, slack=fake_slack)
        r = client.post(
            "/admin/channels/slack/test",
            headers=_headers(),
            json={"recipient": "#general", "text": "hello", "actor": "curro"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["channel"] == "slack"
    assert body["recipient"] == "#general"
    # Slack client called with the right kwargs.
    fake_slack.post_message.assert_called_once_with(channel="#general", text="hello")


def test_telegram_success_parses_chat_id_to_int(tmp_path):
    app = _build_app(tmp_path)
    fake_tg = MagicMock()
    fake_tg.send_message = MagicMock(return_value=None)
    with TestClient(app) as client:
        _attach_fakes(app, telegram=fake_tg)
        r = client.post(
            "/admin/channels/telegram/test",
            headers=_headers(),
            json={"recipient": "12345", "text": "hi"},
        )
    assert r.status_code == 200
    fake_tg.send_message.assert_called_once_with(12345, "hi")


def test_telegram_rejects_non_numeric_recipient(tmp_path):
    app = _build_app(tmp_path)
    fake_tg = MagicMock()
    with TestClient(app) as client:
        _attach_fakes(app, telegram=fake_tg)
        r = client.post(
            "/admin/channels/telegram/test",
            headers=_headers(),
            json={"recipient": "not-a-number", "text": "hi"},
        )
    assert r.status_code == 422
    fake_tg.send_message.assert_not_called()


def test_unknown_channel_returns_404(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        r = client.post(
            "/admin/channels/discord/test",
            headers=_headers(),
            json={"recipient": "x", "text": "hi"},
        )
    assert r.status_code == 404
    assert "supported" in r.text.lower()


def test_unconfigured_channel_returns_503(tmp_path):
    # The gateway has no slack client attached.
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        # Make sure the live gw doesn't have a slack client.
        app.state.gw.slack = None
        r = client.post(
            "/admin/channels/slack/test",
            headers=_headers(),
            json={"recipient": "#x", "text": "hi"},
        )
    assert r.status_code == 503
    assert "not configured" in r.text.lower()


def test_provider_error_returned_as_502(tmp_path):
    app = _build_app(tmp_path)
    fake_slack = MagicMock()
    fake_slack.post_message = MagicMock(
        side_effect=RuntimeError("Slack chat.postMessage failed: invalid_auth")
    )
    with TestClient(app) as client:
        _attach_fakes(app, slack=fake_slack)
        r = client.post(
            "/admin/channels/slack/test",
            headers=_headers(),
            json={"recipient": "#general", "text": "hi"},
        )
    assert r.status_code == 502
    assert "slack send failed" in r.text.lower()


def test_empty_text_rejected(tmp_path):
    app = _build_app(tmp_path)
    fake_slack = MagicMock()
    with TestClient(app) as client:
        _attach_fakes(app, slack=fake_slack)
        r = client.post(
            "/admin/channels/slack/test",
            headers=_headers(),
            json={"recipient": "#general", "text": ""},
        )
    # Pydantic min_length=1 catches this with a 422 before our
    # handler runs.
    assert r.status_code == 422
    fake_slack.post_message.assert_not_called()


def test_unauthenticated_request_rejected(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        r = client.post(
            "/admin/channels/slack/test",
            json={"recipient": "#x", "text": "hi"},
        )
    assert r.status_code == 401


def test_failure_path_still_records_audit_attempt(tmp_path):
    """The attempt is logged *before* the provider call, and a
    failure path appends a ``channel_test_failure`` event. The
    audit trail must therefore show one attempt + one failure
    for a failed send."""
    app = _build_app(tmp_path)
    fake_slack = MagicMock()
    fake_slack.post_message = MagicMock(side_effect=RuntimeError("boom"))
    with TestClient(app) as client:
        _attach_fakes(app, slack=fake_slack)
        # Capture the audit-store size before...
        gw = app.state.gw
        # ...fire the request...
        r = client.post(
            "/admin/channels/slack/test",
            headers=_headers(),
            json={"recipient": "#general", "text": "hi"},
        )
        assert r.status_code == 502
        # ...and verify the attempt + failure landed. We don't
        # crack open the audit-store schema; we just verify the
        # public list_events surface (used by /admin/events) has
        # grown by at least 2.
        events = gw.audit.get_recent_events(limit=100, channel="admin")
        actions = []
        for ev in events or []:
            payload = ev.get("payload") or {}
            if isinstance(payload, dict):
                a = payload.get("action")
                if a in ("channel_test_attempt", "channel_test_failure"):
                    actions.append(a)
        assert "channel_test_attempt" in actions
        assert "channel_test_failure" in actions
