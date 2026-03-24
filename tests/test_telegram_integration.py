from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
import openmiura.endpoints.telegram as telegram_endpoint
from openmiura.core.schema import OutboundMessage


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send_message_chunked(
        self,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> None:
        self.calls.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
            }
        )


class _FakeAudit:
    def __init__(self) -> None:
        self.logged: list[dict] = []

    def log_event(self, **kwargs) -> None:
        self.logged.append(kwargs)


class _FakeGateway:
    def __init__(self, *, allowed: bool = True, secret: str = "tg-secret") -> None:
        self.settings = SimpleNamespace(
            telegram=SimpleNamespace(
                webhook_secret=secret,
                allowlist=SimpleNamespace(
                    deny_message="⛔ No autorizado. Pide acceso al administrador.",
                ),
            )
        )
        self.telegram = _FakeTelegramClient()
        self.audit = _FakeAudit()
        self._allowed = allowed

    def is_telegram_allowed(self, chat_id: int | None, from_id: int | None) -> bool:
        return self._allowed

    def telegram_deny_message(self) -> str:
        return self.settings.telegram.allowlist.deny_message

    def effective_user_key(self, channel_user_key: str) -> str:
        return channel_user_key

    def derive_session_id(self, msg, user_key: str) -> str:
        chat_id = (msg.metadata or {}).get("chat_id", "unknown")
        return f"tg-{chat_id}-{user_key}"


def _client_for_gateway(fake_gw: _FakeGateway) -> TestClient:
    app = app_module.create_app(gateway_factory=lambda _config: fake_gw)
    return TestClient(app)


def test_telegram_invalid_secret_returns_401() -> None:
    fake_gw = _FakeGateway(secret="expected-secret")
    payload = {
        "message": {
            "message_id": 10,
            "text": "hola",
            "chat": {"id": 123},
            "from": {"id": 456},
        }
    }

    with _client_for_gateway(fake_gw) as client:
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
            json=payload,
        )

    assert response.status_code == 401
    assert response.json() == {"error": "Invalid Telegram secret token"}
    assert fake_gw.telegram.calls == []


def test_telegram_non_text_update_is_ignored() -> None:
    fake_gw = _FakeGateway()
    payload = {
        "message": {
            "message_id": 10,
            "chat": {"id": 123},
            "from": {"id": 456},
            "photo": [{"file_id": "abc"}],
        }
    }

    with _client_for_gateway(fake_gw) as client:
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"},
            json=payload,
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake_gw.telegram.calls == []


def test_telegram_webhook_processes_message_and_replies(monkeypatch) -> None:
    fake_gw = _FakeGateway(allowed=True)

    def fake_process_message(_gw, inbound):
        assert inbound.channel == "telegram"
        assert inbound.user_id == "tg:456"
        assert inbound.text == "hola equipo"
        assert inbound.metadata == {
            "chat_id": 123,
            "from_id": 456,
            "message_id": 10,
        }
        return OutboundMessage(
            channel="telegram",
            user_id=inbound.user_id,
            session_id="tg-123-tg:456",
            agent_id="default",
            text="respuesta telegram",
        )

    monkeypatch.setattr(telegram_endpoint, "process_message", fake_process_message)

    payload = {
        "message": {
            "message_id": 10,
            "text": "hola equipo",
            "chat": {"id": 123},
            "from": {"id": 456},
        }
    }

    with _client_for_gateway(fake_gw) as client:
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"},
            json=payload,
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake_gw.telegram.calls == [
        {
            "chat_id": 123,
            "text": "respuesta telegram",
            "reply_to_message_id": 10,
        }
    ]


def test_telegram_not_allowlisted_posts_deny_message_and_logs_security() -> None:
    fake_gw = _FakeGateway(allowed=False)
    payload = {
        "message": {
            "message_id": 10,
            "text": "hola",
            "chat": {"id": 123},
            "from": {"id": 456},
        }
    }

    with _client_for_gateway(fake_gw) as client:
        response = client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"},
            json=payload,
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake_gw.telegram.calls == [
        {
            "chat_id": 123,
            "text": "⛔ No autorizado. Pide acceso al administrador.",
            "reply_to_message_id": 10,
        }
    ]
    assert any(item["direction"] == "security" for item in fake_gw.audit.logged)


def test_telegram_missing_config_returns_503() -> None:
    app = app_module.create_app(gateway_factory=lambda _config: SimpleNamespace(telegram=None))
    with TestClient(app) as client:
        response = client.post("/telegram/webhook", json={})

    assert response.status_code == 503
    assert response.json() == {"error": "Telegram not configured"}
