from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
import openmiura.endpoints.slack as slack_endpoint
from openmiura.core.schema import OutboundMessage


class _FakeSlackClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post_message(self, *, channel: str, text: str, thread_ts: str | None = None) -> None:
        self.calls.append({"channel": channel, "text": text, "thread_ts": thread_ts})


class _FakeAudit:
    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.logged: list[dict] = []

    def mark_slack_event_once(
        self,
        event_id: str,
        team_id: str,
        channel_id: str,
        slack_user: str,
    ) -> bool:
        key = f"{event_id}:{team_id}:{channel_id}:{slack_user}"
        if key in self.seen:
            return False
        self.seen.add(key)
        return True

    def log_event(self, **kwargs) -> None:
        self.logged.append(kwargs)


class _FakeGateway:
    def __init__(self, *, allowed: bool = True, reply_in_thread: bool = True) -> None:
        self.settings = SimpleNamespace(
            slack=SimpleNamespace(
                signing_secret="test-secret",
                reply_in_thread=reply_in_thread,
                bot_user_id="B123",
                allowlist=SimpleNamespace(
                    deny_message="⛔ No autorizado.",
                ),
            ),
        )
        self.slack = _FakeSlackClient()
        self.audit = _FakeAudit()
        self._allowed = allowed

    def effective_user_key(self, channel_user_key: str) -> str:
        return channel_user_key

    def is_slack_allowed(
        self,
        team_id: str,
        channel_id: str,
        channel_type: str | None = None,
    ) -> bool:
        return self._allowed


def _sign_payload(signing_secret: str, body: bytes, timestamp: str | None = None) -> dict[str, str]:
    ts = timestamp or str(int(time.time()))
    base = b"v0:" + ts.encode("utf-8") + b":" + body
    digest = hmac.new(
        signing_secret.encode("utf-8"),
        base,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": f"v0={digest}",
        "Content-Type": "application/json",
    }


def _client_for_gateway(fake_gw: _FakeGateway) -> TestClient:
    app = app_module.create_app(gateway_factory=lambda _config: fake_gw)
    return TestClient(app)


def test_slack_url_verification_returns_challenge() -> None:
    fake_gw = _FakeGateway()
    payload = {"type": "url_verification", "challenge": "abc123"}
    body = json.dumps(payload).encode("utf-8")

    with _client_for_gateway(fake_gw) as client:
        response = client.post(
            "/slack/events",
            content=body,
            headers=_sign_payload("test-secret", body),
        )

    assert response.status_code == 200
    assert response.json() == {"challenge": "abc123"}
    assert fake_gw.slack.calls == []


def test_slack_app_mention_processes_and_replies_in_thread(monkeypatch) -> None:
    fake_gw = _FakeGateway(allowed=True, reply_in_thread=True)

    def fake_process_message(_gw, inbound):
        assert inbound.channel == "slack"
        assert inbound.user_id == "slack:T1:U1"
        assert inbound.text == "hola equipo"
        assert inbound.metadata["event_type"] == "app_mention"
        return OutboundMessage(
            channel="slack",
            user_id=inbound.user_id,
            session_id=inbound.session_id or "slack-C1-slack:T1:U1",
            agent_id="default",
            text="respuesta slack",
        )

    monkeypatch.setattr(slack_endpoint, "process_message", fake_process_message)

    payload = {
        "type": "event_callback",
        "event_id": "Ev1",
        "team_id": "T1",
        "event": {
            "type": "app_mention",
            "user": "U1",
            "channel": "C1",
            "text": "<@B123> hola equipo",
            "ts": "111.222",
        },
    }
    body = json.dumps(payload).encode("utf-8")

    with _client_for_gateway(fake_gw) as client:
        response = client.post(
            "/slack/events",
            content=body,
            headers=_sign_payload("test-secret", body),
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake_gw.slack.calls == [
        {
            "channel": "C1",
            "text": "respuesta slack",
            "thread_ts": "111.222",
        }
    ]


def test_slack_duplicate_event_is_ignored(monkeypatch) -> None:
    fake_gw = _FakeGateway()
    monkeypatch.setattr(
        slack_endpoint,
        "process_message",
        lambda _gw, inbound: OutboundMessage(
            channel="slack",
            user_id=inbound.user_id,
            session_id=inbound.session_id or "x",
            agent_id="default",
            text="ok",
        ),
    )

    payload = {
        "type": "event_callback",
        "event_id": "EvDup",
        "team_id": "T1",
        "event": {
            "type": "message",
            "channel_type": "im",
            "user": "U1",
            "channel": "D1",
            "text": "hola",
            "ts": "333.444",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    headers = _sign_payload("test-secret", body)

    with _client_for_gateway(fake_gw) as client:
        first = client.post("/slack/events", content=body, headers=headers)
        second = client.post("/slack/events", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert fake_gw.slack.calls == [
        {"channel": "D1", "text": "ok", "thread_ts": "333.444"}
    ]


def test_slack_not_allowlisted_posts_deny_message() -> None:
    fake_gw = _FakeGateway(allowed=False)
    payload = {
        "type": "event_callback",
        "event_id": "EvNope",
        "team_id": "T1",
        "event": {
            "type": "message",
            "channel_type": "im",
            "user": "U1",
            "channel": "D1",
            "text": "hola",
            "ts": "555.666",
        },
    }
    body = json.dumps(payload).encode("utf-8")

    with _client_for_gateway(fake_gw) as client:
        response = client.post(
            "/slack/events",
            content=body,
            headers=_sign_payload("test-secret", body),
        )

    assert response.status_code == 200
    assert fake_gw.slack.calls == [
        {
            "channel": "D1",
            "text": "⛔ No autorizado.",
            "thread_ts": "555.666",
        }
    ]
    assert any(item["direction"] == "security" for item in fake_gw.audit.logged)


def test_slack_invalid_signature_returns_401() -> None:
    fake_gw = _FakeGateway()
    payload = {"type": "url_verification", "challenge": "abc123"}
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "X-Slack-Request-Timestamp": str(int(time.time())),
        "X-Slack-Signature": "v0=invalid",
        "Content-Type": "application/json",
    }

    with _client_for_gateway(fake_gw) as client:
        response = client.post("/slack/events", content=body, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"error": "Invalid Slack signature"}
