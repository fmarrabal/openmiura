"""AuthRepo: persistence for the auth domain of openMiura.

Owns the persistence logic for the auth-related tables. The class
is instantiated by ``AuditStore`` so existing public callers remain
unaffected; ``AuditStore`` keeps thin one-line delegators on its API.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from openmiura.core.db import DBConnection, CompatRow
from openmiura.core.tenancy.scope import assert_scope_match, normalize_scope
from openmiura.persistence.base import (
    infer_scope_from_session,
    row_scope,
    scope_payload,
    scope_where,
)


class AuthRepo:
    def __init__(self, conn: DBConnection) -> None:
        self._conn = conn

    @staticmethod
    def _scope_payload(*, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return scope_payload(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    @staticmethod
    def _row_scope(row: Any) -> dict[str, Any]:
        return row_scope(row)

    def _scope_where(self, clauses: list[str], params: list[Any], *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, prefix: str = "") -> tuple[list[str], list[Any]]:
        return scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, prefix=prefix)

    def _infer_scope_from_session(self, session_id: str) -> dict[str, Any]:
        return infer_scope_from_session(self._conn, session_id)

    def count_api_tokens(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = ["revoked_at IS NULL"]
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT COUNT(*) FROM api_tokens WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_auth_users(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id)
        sql = "SELECT COUNT(*) FROM auth_users"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_auth_sessions(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = ["revoked_at IS NULL"]
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT COUNT(*) FROM auth_sessions WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def create_api_token(
        self,
        *,
        user_key: str,
        label: str,
        scopes: list[str] | None = None,
        ttl_s: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        raw_token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + int(ttl_s) if ttl_s else None
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token_prefix = raw_token[:10]
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO api_tokens(user_key, label, token_hash, token_prefix, scopes_json, created_at, expires_at, last_used_at, revoked_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_key, label.strip() or "token", token_hash, token_prefix, json.dumps(list(scopes or ["broker"]), ensure_ascii=False), now, expires_at, None, None, tenant_id, workspace_id, environment),
        )
        token_id = int(cur.lastrowid)
        self._conn.commit()
        return {"id": token_id, "user_key": user_key, "label": label.strip() or "token", "token": raw_token, "token_prefix": token_prefix, "scopes": list(scopes or ["broker"]), "created_at": float(now), "expires_at": float(expires_at) if expires_at is not None else None, "tenant_id": tenant_id, "workspace_id": workspace_id, "environment": environment}

    def list_api_tokens(self, *, user_key: str | None = None, include_revoked: bool = False, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if user_key is not None:
            clauses.append("user_key=?")
            params.append(user_key)
        if not include_revoked:
            clauses.append("revoked_at IS NULL")
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT id, user_key, label, token_prefix, scopes_json, created_at, expires_at, last_used_at, revoked_at, tenant_id, workspace_id, environment FROM api_tokens"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        rows = cur.execute(sql, tuple(params)).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                scopes = json.loads(r["scopes_json"]) if r["scopes_json"] else []
            except Exception:
                scopes = []
            out.append({"id": int(r["id"]), "user_key": r["user_key"], "label": r["label"], "token_prefix": r["token_prefix"], "scopes": scopes, "created_at": float(r["created_at"]), "expires_at": float(r["expires_at"]) if r["expires_at"] is not None else None, "last_used_at": float(r["last_used_at"]) if r["last_used_at"] is not None else None, "revoked_at": float(r["revoked_at"]) if r["revoked_at"] is not None else None, "tenant_id": r["tenant_id"], "workspace_id": r["workspace_id"], "environment": r["environment"]})
        return out

    def get_api_token(self, raw_token: str, *, idle_ttl_s: int | None = None) -> dict[str, Any] | None:
        if not raw_token:
            return None
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        cur = self._conn.cursor()
        row = cur.execute("SELECT id, user_key, label, token_prefix, scopes_json, created_at, expires_at, last_used_at, revoked_at, tenant_id, workspace_id, environment FROM api_tokens WHERE token_hash=?", (token_hash,)).fetchone()
        if row is None or row["revoked_at"] is not None:
            return None
        now_ts = time.time()
        if row["expires_at"] is not None and float(row["expires_at"]) <= now_ts:
            return None
        if idle_ttl_s is not None and int(idle_ttl_s or 0) > 0:
            last_seen = float(row["last_used_at"]) if row["last_used_at"] is not None else float(row["created_at"])
            if last_seen + int(idle_ttl_s) <= now_ts:
                return None
        try:
            scopes = json.loads(row["scopes_json"]) if row["scopes_json"] else []
        except Exception:
            scopes = []
        return {"id": int(row["id"]), "user_key": row["user_key"], "label": row["label"], "token_prefix": row["token_prefix"], "scopes": scopes, "created_at": float(row["created_at"]), "expires_at": float(row["expires_at"]) if row["expires_at"] is not None else None, "last_used_at": float(row["last_used_at"]) if row["last_used_at"] is not None else None, "tenant_id": row["tenant_id"], "workspace_id": row["workspace_id"], "environment": row["environment"]}

    def touch_api_token(self, raw_token: str) -> int:
        if not raw_token:
            return 0
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        cur = self._conn.cursor()
        cur.execute("UPDATE api_tokens SET last_used_at=? WHERE token_hash=?", (time.time(), token_hash))
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def revoke_api_token(self, *, token_id: int | None = None, raw_token: str | None = None) -> int:
        if token_id is None and not raw_token:
            return 0
        cur = self._conn.cursor()
        if token_id is not None:
            cur.execute("UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), int(token_id)))
        else:
            token_hash = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
            cur.execute("UPDATE api_tokens SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (time.time(), token_hash))
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def rotate_api_token(self, *, token_id: int, ttl_s: int | None = None, user_key: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT id, user_key, label, scopes_json, tenant_id, workspace_id, environment FROM api_tokens WHERE id=? AND revoked_at IS NULL",
            (int(token_id),),
        ).fetchone()
        if row is None:
            return None
        token_user_key = str(row["user_key"])
        if user_key is not None and token_user_key != str(user_key):
            return None
        try:
            scopes = json.loads(row["scopes_json"]) if row["scopes_json"] else []
        except Exception:
            scopes = []
        rotated = self.create_api_token(
            user_key=token_user_key,
            label=str(row["label"]),
            scopes=list(scopes),
            ttl_s=ttl_s,
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            environment=row["environment"],
        )
        cur.execute("UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), int(token_id)))
        self._conn.commit()
        return rotated

    def cleanup_api_tokens(self, *, idle_ttl_s: int | None = None) -> dict[str, int]:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute("UPDATE api_tokens SET revoked_at=? WHERE revoked_at IS NULL AND expires_at IS NOT NULL AND expires_at<=?", (now, now))
        expired = int(cur.rowcount)
        idle_revoked = 0
        if idle_ttl_s is not None and int(idle_ttl_s or 0) > 0:
            threshold = now - int(idle_ttl_s)
            cur.execute(
                "UPDATE api_tokens SET revoked_at=? WHERE revoked_at IS NULL AND COALESCE(last_used_at, created_at)<=?",
                (now, threshold),
            )
            idle_revoked = int(cur.rowcount)
        self._conn.commit()
        return {"expired": expired, "idle_revoked": idle_revoked}

    def _hash_password(self, password: str, salt_hex: str | None = None, iterations: int = 200000) -> tuple[str, str]:
        import hashlib
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, int(iterations))
        return salt.hex(), digest.hex()

    def has_auth_users(self) -> bool:
        cur = self._conn.cursor()
        return bool(cur.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0])

    def ensure_auth_user(
        self,
        *,
        username: str,
        password: str,
        user_key: str | None = None,
        role: str = "user",
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        username = str(username).strip()
        if not username:
            raise ValueError("username is required")
        user_key = str(user_key or f"user:{username}").strip()
        salt_hex, hash_hex = self._hash_password(password)
        now = time.time()
        cur = self._conn.cursor()
        existing = cur.execute("SELECT id FROM auth_users WHERE username=?", (username,)).fetchone()
        if existing is None:
            cur.execute(
                "INSERT INTO auth_users(username, user_key, password_salt, password_hash, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (username, user_key, salt_hex, hash_hex, str(role or 'user'), 1, now, now, None, tenant_id, workspace_id),
            )
            user_id = int(cur.lastrowid)
        else:
            user_id = int(existing[0])
            cur.execute(
                "UPDATE auth_users SET user_key=?, password_salt=?, password_hash=?, role=?, is_active=1, updated_at=?, tenant_id=COALESCE(tenant_id, ?), workspace_id=COALESCE(workspace_id, ?) WHERE id=?",
                (user_key, salt_hex, hash_hex, str(role or 'user'), now, tenant_id, workspace_id, user_id),
            )
        self._conn.commit()
        return self.get_auth_user(user_id=user_id) or {"id": user_id, "username": username, "user_key": user_key, "role": role, "tenant_id": tenant_id, "workspace_id": workspace_id}

    def get_auth_user(self, *, user_id: int | None = None, username: str | None = None, user_key: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        if user_id is not None:
            row = cur.execute("SELECT id, username, user_key, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id FROM auth_users WHERE id=?", (int(user_id),)).fetchone()
        elif username is not None:
            row = cur.execute("SELECT id, username, user_key, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id FROM auth_users WHERE username=?", (str(username),)).fetchone()
        elif user_key is not None:
            row = cur.execute("SELECT id, username, user_key, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id FROM auth_users WHERE user_key=?", (str(user_key),)).fetchone()
        else:
            return None
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "username": row["username"],
            "user_key": row["user_key"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "last_login_at": float(row["last_login_at"]) if row["last_login_at"] is not None else None,
            "tenant_id": row["tenant_id"],
            "workspace_id": row["workspace_id"],
        }

    def list_auth_users(self, *, tenant_id: str | None = None, workspace_id: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id)
        sql = "SELECT id, username, user_key, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id FROM auth_users"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC"
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [
            {
                "id": int(r["id"]),
                "username": r["username"],
                "user_key": r["user_key"],
                "role": r["role"],
                "is_active": bool(r["is_active"]),
                "created_at": float(r["created_at"]),
                "updated_at": float(r["updated_at"]),
                "last_login_at": float(r["last_login_at"]) if r["last_login_at"] is not None else None,
                "tenant_id": r["tenant_id"],
                "workspace_id": r["workspace_id"],
            }
            for r in rows
        ]

    def verify_auth_user(self, *, username: str, password: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT id, username, user_key, password_salt, password_hash, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id FROM auth_users WHERE username=?",
            (str(username).strip(),),
        ).fetchone()
        if row is None or not bool(row["is_active"]):
            return None
        _, digest_hex = self._hash_password(password, salt_hex=row["password_salt"])
        if not secrets.compare_digest(digest_hex, row["password_hash"]):
            return None
        now = time.time()
        cur.execute("UPDATE auth_users SET last_login_at=?, updated_at=? WHERE id=?", (now, now, int(row["id"])))
        self._conn.commit()
        return self.get_auth_user(user_id=int(row["id"]))

    # --- TOTP second factor (signature-grade approvals) --------------------
    # The secret itself is encrypted by the application layer (TotpService)
    # before it reaches here; this repo only persists the opaque ciphertext
    # plus the enabled/confirmed flags. Keyed by user_key (the identity used
    # on approvals).
    def set_user_otp_secret(self, *, user_key: str, otp_secret_enc: str) -> int:
        """Store a freshly enrolled (encrypted) TOTP secret, leaving 2FA
        DISABLED until a code is confirmed."""
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE auth_users SET otp_secret_enc=?, otp_enabled=0, otp_confirmed_at=NULL, updated_at=? WHERE user_key=?",
            (otp_secret_enc, now, str(user_key)),
        )
        self._conn.commit()
        return int(getattr(cur, "rowcount", 0) or 0)

    def mark_user_otp_confirmed(self, *, user_key: str, confirmed_at: float | None = None) -> int:
        """Enable 2FA for the user once enrolment has been confirmed."""
        now = time.time()
        ts = float(confirmed_at) if confirmed_at is not None else now
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE auth_users SET otp_enabled=1, otp_confirmed_at=?, updated_at=? WHERE user_key=?",
            (ts, now, str(user_key)),
        )
        self._conn.commit()
        return int(getattr(cur, "rowcount", 0) or 0)

    def disable_user_otp(self, *, user_key: str) -> int:
        """Turn 2FA off and forget the secret (e.g. on reset)."""
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE auth_users SET otp_enabled=0, otp_secret_enc=NULL, otp_confirmed_at=NULL, updated_at=? WHERE user_key=?",
            (now, str(user_key)),
        )
        self._conn.commit()
        return int(getattr(cur, "rowcount", 0) or 0)

    def get_user_otp(self, *, user_key: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT otp_secret_enc, otp_enabled, otp_confirmed_at FROM auth_users WHERE user_key=?",
            (str(user_key),),
        ).fetchone()
        if row is None:
            return None
        return {
            "otp_secret_enc": row["otp_secret_enc"],
            "otp_enabled": bool(row["otp_enabled"]),
            "otp_confirmed_at": float(row["otp_confirmed_at"]) if row["otp_confirmed_at"] is not None else None,
        }

    def create_auth_session(
        self,
        *,
        user_id: int,
        label: str = "ui",
        ttl_s: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        raw_token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + int(ttl_s) if ttl_s else None
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token_prefix = raw_token[:10]
        user = self.get_auth_user(user_id=int(user_id)) or {}
        cur = self._conn.cursor()
        effective_tenant = tenant_id if tenant_id is not None else user.get("tenant_id")
        effective_workspace = workspace_id if workspace_id is not None else user.get("workspace_id")
        effective_environment = environment
        cur.execute(
            "INSERT INTO auth_sessions(user_id, label, token_hash, token_prefix, created_at, expires_at, last_used_at, revoked_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (int(user_id), str(label or 'ui'), token_hash, token_prefix, now, expires_at, None, None, effective_tenant, effective_workspace, effective_environment),
        )
        session_id = int(cur.lastrowid)
        self._conn.commit()
        return {
            "id": session_id,
            "token": raw_token,
            "token_prefix": token_prefix,
            "label": str(label or 'ui'),
            "created_at": float(now),
            "expires_at": float(expires_at) if expires_at is not None else None,
            "tenant_id": effective_tenant,
            "workspace_id": effective_workspace,
            "environment": effective_environment,
            "user": user,
        }

    def list_auth_sessions(self, *, user_id: int | None = None, include_revoked: bool = False, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("s.user_id=?")
            params.append(int(user_id))
        if not include_revoked:
            clauses.append("s.revoked_at IS NULL")
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, prefix="s")
        sql = (
            "SELECT s.id, s.user_id, s.label, s.token_prefix, s.created_at, s.expires_at, s.last_used_at, s.revoked_at, s.tenant_id, s.workspace_id, s.environment, "
            "u.username, u.user_key, u.role, u.is_active "
            "FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY s.created_at DESC"
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [
            {
                "id": int(r["id"]),
                "user_id": int(r["user_id"]),
                "label": r["label"],
                "token_prefix": r["token_prefix"],
                "created_at": float(r["created_at"]),
                "expires_at": float(r["expires_at"]) if r["expires_at"] is not None else None,
                "last_used_at": float(r["last_used_at"]) if r["last_used_at"] is not None else None,
                "revoked_at": float(r["revoked_at"]) if r["revoked_at"] is not None else None,
                "username": r["username"],
                "user_key": r["user_key"],
                "role": r["role"],
                "is_active": bool(r["is_active"]),
                "tenant_id": r["tenant_id"],
                "workspace_id": r["workspace_id"],
                "environment": r["environment"],
            }
            for r in rows
        ]

    def get_auth_session(self, raw_token: str, *, idle_ttl_s: int | None = None) -> dict[str, Any] | None:
        if not raw_token:
            return None
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT s.id, s.user_id, s.label, s.token_prefix, s.created_at, s.expires_at, s.last_used_at, s.revoked_at, s.tenant_id, s.workspace_id, s.environment, u.username, u.user_key, u.role, u.is_active FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id WHERE s.token_hash=?",
            (token_hash,),
        ).fetchone()
        if row is None or row["revoked_at"] is not None or not bool(row["is_active"]):
            return None
        now_ts = time.time()
        if row["expires_at"] is not None and float(row["expires_at"]) <= now_ts:
            return None
        if idle_ttl_s is not None and int(idle_ttl_s or 0) > 0:
            last_seen = float(row["last_used_at"]) if row["last_used_at"] is not None else float(row["created_at"])
            if last_seen + int(idle_ttl_s) <= now_ts:
                return None
        return {
            "id": int(row["id"]),
            "user_id": int(row["user_id"]),
            "label": row["label"],
            "token_prefix": row["token_prefix"],
            "created_at": float(row["created_at"]),
            "expires_at": float(row["expires_at"]) if row["expires_at"] is not None else None,
            "last_used_at": float(row["last_used_at"]) if row["last_used_at"] is not None else None,
            "username": row["username"],
            "user_key": row["user_key"],
            "role": row["role"],
            "tenant_id": row["tenant_id"],
            "workspace_id": row["workspace_id"],
            "environment": row["environment"],
        }

    def touch_auth_session(self, raw_token: str) -> int:
        if not raw_token:
            return 0
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        cur = self._conn.cursor()
        cur.execute("UPDATE auth_sessions SET last_used_at=? WHERE token_hash=?", (time.time(), token_hash))
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def revoke_auth_session(self, *, raw_token: str | None = None, session_id: int | None = None) -> int:
        if not raw_token and session_id is None:
            return 0
        cur = self._conn.cursor()
        if raw_token:
            token_hash = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
            cur.execute("UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (time.time(), token_hash))
        else:
            cur.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), int(session_id)))
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def revoke_auth_sessions_for_user(self, *, user_id: int, keep_session_id: int | None = None) -> int:
        cur = self._conn.cursor()
        if keep_session_id is None:
            cur.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (time.time(), int(user_id)))
        else:
            cur.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND id<>?",
                (time.time(), int(user_id), int(keep_session_id)),
            )
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def rotate_auth_session(self, *, raw_token: str | None = None, session_id: int | None = None, ttl_s: int | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = None
        if raw_token:
            token_hash = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
            row = cur.execute("SELECT id, user_id, label, tenant_id, workspace_id, environment FROM auth_sessions WHERE token_hash=? AND revoked_at IS NULL", (token_hash,)).fetchone()
        elif session_id is not None:
            row = cur.execute("SELECT id, user_id, label, tenant_id, workspace_id, environment FROM auth_sessions WHERE id=? AND revoked_at IS NULL", (int(session_id),)).fetchone()
        if row is None:
            return None
        rotated = self.create_auth_session(
            user_id=int(row["user_id"]),
            label=str(row["label"] or "ui"),
            ttl_s=ttl_s,
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            environment=row["environment"],
        )
        cur.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), int(row["id"])))
        self._conn.commit()
        return rotated

    def cleanup_auth_sessions(self, *, idle_ttl_s: int | None = None) -> dict[str, int]:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute("UPDATE auth_sessions SET revoked_at=? WHERE revoked_at IS NULL AND expires_at IS NOT NULL AND expires_at<=?", (now, now))
        expired = int(cur.rowcount)
        idle_revoked = 0
        if idle_ttl_s is not None and int(idle_ttl_s or 0) > 0:
            threshold = now - int(idle_ttl_s)
            cur.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE revoked_at IS NULL AND COALESCE(last_used_at, created_at)<=?",
                (now, threshold),
            )
            idle_revoked = int(cur.rowcount)
        self._conn.commit()
        return {"expired": expired, "idle_revoked": idle_revoked}
