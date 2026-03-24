from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PendingToolConfirmation:
    session_id: str
    channel: str | None
    channel_user_id: str | None
    user_key: str
    agent_id: str
    tool_name: str
    args: dict[str, Any]
    created_at: float
    expires_at: float

    def is_expired(self, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        return current >= float(self.expires_at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "channel": self.channel,
            "channel_user_id": self.channel_user_id,
            "user_key": self.user_key,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "args": dict(self.args or {}),
            "created_at": float(self.created_at),
            "expires_at": float(self.expires_at),
        }


class PendingToolConfirmationStore:
    """In-memory pending confirmation store keyed by session_id.

    A session can have at most one pending tool confirmation at a time, which keeps
    the UX aligned with the existing `/confirm` and `/cancel` commands.
    """

    def __init__(self, default_ttl_s: int = 900, ttl_s: int | None = None) -> None:
        effective = default_ttl_s if ttl_s is None else ttl_s
        self.default_ttl_s = max(1, int(effective))
        self._items: dict[str, PendingToolConfirmation] = {}
        self._lock = threading.RLock()

    def _purge_if_expired_locked(self, session_id: str, *, now: float | None = None) -> PendingToolConfirmation | None:
        item = self._items.get(session_id)
        if item is None:
            return None
        current = time.time() if now is None else float(now)
        if item.is_expired(current):
            self._items.pop(session_id, None)
            return None
        return item

    def set(
        self,
        session_id: str,
        *,
        channel: str | None = None,
        channel_user_id: str | None = None,
        user_key: str | None = None,
        agent_id: str,
        tool_name: str | None = None,
        args: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        ttl_s: int | None = None,
    ) -> dict[str, Any]:
        data = dict(payload or {})
        if user_key is None:
            user_key = data.get("user_key") or data.get("channel_user_id") or data.get("channel") or "anonymous"
        if tool_name is None:
            tool_name = data.get("tool_name") or "unknown_tool"
        if args is None:
            args = data.get("args") or {}
        if channel is None:
            channel = data.get("channel")
        if channel_user_id is None:
            channel_user_id = data.get("channel_user_id")

        ttl = self.default_ttl_s if ttl_s is None else max(1, int(ttl_s))
        now = time.time()
        item = PendingToolConfirmation(
            session_id=session_id,
            channel=channel,
            channel_user_id=channel_user_id,
            user_key=str(user_key),
            agent_id=str(agent_id),
            tool_name=str(tool_name),
            args=dict(args or {}),
            created_at=now,
            expires_at=now + ttl,
        )
        with self._lock:
            self._items[session_id] = item
        return item.to_payload()

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._purge_if_expired_locked(session_id)
            return None if item is None else item.to_payload()

    def pop(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._purge_if_expired_locked(session_id)
            if item is None:
                return None
            self._items.pop(session_id, None)
            return item.to_payload()

    def consume(self, session_id: str, *, user_key: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            item = self._purge_if_expired_locked(session_id)
            if item is None:
                return None
            if user_key is not None and item.user_key != user_key:
                return None
            self._items.pop(session_id, None)
            return item.to_payload()

    def clear(self, session_id: str) -> bool:
        with self._lock:
            return self._items.pop(session_id, None) is not None

    def cancel(self, session_id: str, *, user_key: str | None = None) -> bool:
        with self._lock:
            item = self._purge_if_expired_locked(session_id)
            if item is None:
                return False
            if user_key is not None and item.user_key != user_key:
                return False
            self._items.pop(session_id, None)
            return True

    def reset_session(self, session_id: str) -> bool:
        return self.clear(session_id)

    def invalidate_agent(self, session_id: str, agent_id: str | None) -> int:
        if not agent_id:
            return 0
        with self._lock:
            item = self._purge_if_expired_locked(session_id)
            if item is None or item.agent_id != agent_id:
                return 0
            self._items.pop(session_id, None)
            return 1

    def invalidate_if_agent_changes(self, session_id: str, next_agent_id: str | None) -> bool:
        if not next_agent_id:
            return False
        with self._lock:
            item = self._purge_if_expired_locked(session_id)
            if item is None:
                return False
            if str(item.agent_id).strip() == str(next_agent_id).strip():
                return False
            self._items.pop(session_id, None)
            return True

    def cleanup_expired(self) -> int:
        now = time.time()
        with self._lock:
            expired_sessions = [sid for sid, item in self._items.items() if item.is_expired(now)]
            for sid in expired_sessions:
                self._items.pop(sid, None)
            return len(expired_sessions)

    def list_items(self, *, user_key: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self.cleanup_expired()
            items = [item.to_payload() for item in self._items.values()]
        if user_key is not None:
            items = [item for item in items if item.get("user_key") == user_key]
        items.sort(key=lambda item: float(item.get("created_at") or 0.0), reverse=True)
        return items

    def count(self) -> int:
        with self._lock:
            self.cleanup_expired()
            return len(self._items)

    def __len__(self) -> int:
        return self.count()


class PendingToolConfirmationCleanupService:
    def __init__(self, store: PendingToolConfirmationStore, interval_s: int = 60) -> None:
        self.store = store
        self.interval_s = max(1, int(interval_s))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="openmiura-confirmation-cleaner", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.store.cleanup_expired()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


# Backward-compatible aliases used by current gateway/app code.
PendingConfirmationStore = PendingToolConfirmationStore
PendingConfirmation = PendingToolConfirmation
PendingConfirmationCleanupService = PendingToolConfirmationCleanupService
