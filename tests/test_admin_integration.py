from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module


class _FakeAudit:
    def __init__(self) -> None:
        self.logged: list[dict] = []
        self._items = [
            {
                "id": 1,
                "user_key": "u1",
                "kind": "fact",
                "text": "Curro trabaja en UAL",
            },
            {
                "id": 2,
                "user_key": "u1",
                "kind": "preference",
                "text": "Prefiere español neutro",
            },
            {
                "id": 3,
                "user_key": "u2",
                "kind": "fact",
                "text": "Otro usuario",
            },
        ]

    def table_counts(self) -> dict[str, int]:
        return {
            "sessions": 2,
            "messages": 5,
            "events": len(self.logged),
            "memory_items": len(self._items),
            "telegram_state": 0,
            "identity_map": 1,
            "tool_calls": 2,
            "slack_event_dedupe": 1,
        }

    def count_memory_items(self, user_key: str | None = None, kind: str | None = None) -> int:
        return len(
            [
                item
                for item in self._items
                if (user_key is None or item["user_key"] == user_key)
                and (kind is None or item["kind"] == kind)
            ]
        )

    def search_memory_items(
        self,
        *,
        user_key: str | None = None,
        kind: str | None = None,
        text_contains: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        rows = list(self._items)
        if user_key is not None:
            rows = [r for r in rows if r["user_key"] == user_key]
        if kind is not None:
            rows = [r for r in rows if r["kind"] == kind]
        if text_contains:
            needle = text_contains.lower()
            rows = [r for r in rows if needle in r["text"].lower()]
        return rows[:limit]

    def delete_memory_items(self, *, user_key: str, kind: str | None = None) -> int:
        before = len(self._items)
        self._items = [
            item
            for item in self._items
            if not (item["user_key"] == user_key and (kind is None or item["kind"] == kind))
        ]
        return before - len(self._items)

    def log_event(self, **kwargs) -> None:
        self.logged.append(kwargs)


class _FakeGateway:
    def __init__(self, *, admin_enabled: bool = True, token: str = "admin-secret") -> None:
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(
                provider="ollama",
                model="qwen2.5:7b-instruct",
                base_url="http://127.0.0.1:11434",
            ),
            memory=SimpleNamespace(enabled=True, embed_model="nomic-embed-text"),
            storage=SimpleNamespace(db_path="data/test.db"),
            admin=SimpleNamespace(enabled=admin_enabled, token=token, max_search_results=5),
        )
        self.telegram = None
        self.slack = None
        self.audit = _FakeAudit()
        self.tools = SimpleNamespace(
            registry=SimpleNamespace(_tools={"time_now": object(), "web_fetch": object()})
        )


def _client_for_gateway(fake_gw: _FakeGateway) -> TestClient:
    app = app_module.create_app(gateway_factory=lambda _config: fake_gw)
    return TestClient(app)


def test_admin_status_requires_token() -> None:
    fake_gw = _FakeGateway(admin_enabled=True, token="secret")
    with _client_for_gateway(fake_gw) as client:
        response = client.get("/admin/status")

    assert response.status_code == 401
    assert response.json() == {"error": "Invalid admin token"}


def test_admin_status_returns_service_snapshot() -> None:
    fake_gw = _FakeGateway(admin_enabled=True, token="secret")
    with _client_for_gateway(fake_gw) as client:
        response = client.get(
            "/admin/status",
            headers={"Authorization": "Bearer secret"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["service"] == "openMiura"
    assert data["llm"]["model"] == "qwen2.5:7b-instruct"
    assert data["memory"]["total_items"] == 3
    assert data["tools"]["registered"] == ["time_now", "web_fetch"]
    assert data["db"]["counts"]["memory_items"] == 3


def test_admin_memory_search_applies_filters_and_limit() -> None:
    fake_gw = _FakeGateway(admin_enabled=True, token="secret")
    with _client_for_gateway(fake_gw) as client:
        response = client.post(
            "/admin/memory/search",
            headers={"X-Admin-Token": "secret"},
            json={
                "user_key": "u1",
                "text_contains": "prefiere",
                "limit": 99,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["returned"] == 1
    assert data["items"][0]["kind"] == "preference"
    assert data["filters"]["limit"] == 99


def test_admin_memory_delete_dry_run_does_not_delete() -> None:
    fake_gw = _FakeGateway(admin_enabled=True, token="secret")
    with _client_for_gateway(fake_gw) as client:
        response = client.post(
            "/admin/memory/delete",
            headers={"Authorization": "Bearer secret"},
            json={"user_key": "u1", "dry_run": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["would_delete"] == 2
    assert fake_gw.audit.count_memory_items(user_key="u1") == 2


def test_admin_memory_delete_removes_items_and_logs_event() -> None:
    fake_gw = _FakeGateway(admin_enabled=True, token="secret")
    with _client_for_gateway(fake_gw) as client:
        response = client.post(
            "/admin/memory/delete",
            headers={"Authorization": "Bearer secret"},
            json={"user_key": "u1", "kind": "preference", "dry_run": False},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] == 1
    assert fake_gw.audit.count_memory_items(user_key="u1") == 1
    assert any(
        item["payload"]["action"] == "memory_delete"
        and item["payload"]["deleted"] == 1
        for item in fake_gw.audit.logged
    )


def test_admin_endpoints_return_503_when_disabled() -> None:
    fake_gw = _FakeGateway(admin_enabled=False, token="secret")
    with _client_for_gateway(fake_gw) as client:
        response = client.get(
            "/admin/status",
            headers={"Authorization": "Bearer secret"},
        )

    assert response.status_code == 503
    assert response.json() == {"error": "Admin API not enabled"}
