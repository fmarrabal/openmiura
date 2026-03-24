from __future__ import annotations

import asyncio

import httpx

import app as app_module
from openmiura.channels.discord import post_inbound_to_gateway
from openmiura.core.schema import OutboundMessage


def test_post_inbound_to_gateway_hits_http_message(monkeypatch) -> None:
    monkeypatch.setattr(app_module.app.state, "gw", object(), raising=False)

    def fake_process_message(_gw, msg):
        return OutboundMessage(
            channel=msg.channel,
            user_id=msg.user_id,
            session_id="dc-discord:42",
            agent_id="default",
            text=f"echo::{msg.text}",
        )

    monkeypatch.setattr(app_module, "process_message", fake_process_message)

    async def run():
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await post_inbound_to_gateway(
                gateway_url="http://testserver/http/message",
                payload={
                    "channel": "discord",
                    "user_id": "discord:42",
                    "text": "hola",
                    "metadata": {"source": "message"},
                },
                timeout_s=5,
                client=client,
            )

    out = asyncio.run(run())
    assert out["text"] == "echo::hola"
    assert out["channel"] == "discord"
    assert out["user_id"] == "discord:42"


def test_post_inbound_to_gateway_raises_on_http_error(monkeypatch) -> None:
    monkeypatch.setattr(app_module.app.state, "gw", None, raising=False)

    async def run():
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await post_inbound_to_gateway(
                gateway_url="http://testserver/http/message",
                payload={
                    "channel": "discord",
                    "user_id": "discord:99",
                    "text": "hola",
                    "metadata": {},
                },
                timeout_s=5,
                client=client,
            )

    try:
        asyncio.run(run())
        assert False, "Expected HTTPStatusError"
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 503
