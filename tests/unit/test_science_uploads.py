"""Tests for the /science/uploads HTTP surface.

End-to-end coverage: POST a file, GET the list, GET the bytes,
hit the size cap and the rate limit. Uses an isolated temp
directory for the upload store and an in-memory SQLite audit db
so the tests never touch production state.

The auth shape mirrors the admin surface: every endpoint
requires the admin token. We stamp ``admin.enabled = true`` and
a fixed token in the test app config.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from openmiura.interfaces.http.app import create_app


TOKEN = "test-admin-token-xxxxxxxxxxxxxxxx"


def _build_app(upload_dir: Path, *, max_bytes: int = 1024 * 1024, rate_limit: int = 0):
    """Spin up a fresh openMiura app with an isolated upload
    directory and in-memory audit db.

    rate_limit=0 disables the per-IP cap so we don't trip it on
    happy-path tests; the rate-limit case sets it explicitly.

    Returns the (app, cfg_path) tuple so the caller can wrap a
    ``with TestClient(app) as client:`` and clean up.
    """
    cfg = {
        "server":  {"host": "127.0.0.1", "port": 8081},
        "storage": {"backend": "sqlite", "db_path": ":memory:"},
        "admin":   {"enabled": True, "token": TOKEN},
        "auth":    {"enabled": False},
        "science": {
            "enabled": True,
            "upload_dir": str(upload_dir),
            "max_upload_bytes": int(max_bytes),
            "rate_limit_per_minute": int(rate_limit),
        },
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.safe_dump(cfg, f)
        cfg_path = f.name
    app = create_app(config_path=cfg_path)
    return app, cfg_path


def _headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_upload_returns_metadata_and_persists_bytes(tmp_path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        payload = b"hello-world\n"
        files = {"file": ("hello.txt", io.BytesIO(payload), "text/plain")}
        data  = {"user_id": "curro", "description": "demo upload"}
        r = client.post("/science/uploads", headers=_headers(), files=files, data=data)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "hello.txt"
        assert body["size"] == len(payload)
        assert body["mime"] == "text/plain"
        assert body["user_id"] == "curro"
        assert body["description"] == "demo upload"
        assert len(body["upload_id"]) == 24, "upload_id should be 24 hex chars"
        import hashlib
        assert body["sha256"] == hashlib.sha256(payload).hexdigest()
        sha = body["sha256"]
        expected_path = tmp_path / sha[:2] / sha
        assert expected_path.exists()
        assert expected_path.read_bytes() == payload
        index = tmp_path / "index.jsonl"
        assert index.exists()
        lines = index.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1


def test_upload_requires_user_id(tmp_path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        files = {"file": ("x.bin", io.BytesIO(b"abc"), "application/octet-stream")}
        r = client.post("/science/uploads", headers=_headers(), files=files, data={"user_id": ""})
        assert r.status_code == 422


def test_upload_rejects_empty_file(tmp_path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        files = {"file": ("empty.bin", io.BytesIO(b""), "application/octet-stream")}
        r = client.post("/science/uploads", headers=_headers(), files=files, data={"user_id": "curro"})
        assert r.status_code == 422
        assert "empty" in r.text.lower()


def test_upload_enforces_size_cap(tmp_path):
    app, _ = _build_app(tmp_path, max_bytes=64)
    with TestClient(app) as client:
        payload = b"A" * 100
        files = {"file": ("big.bin", io.BytesIO(payload), "application/octet-stream")}
        r = client.post("/science/uploads", headers=_headers(), files=files, data={"user_id": "curro"})
        assert r.status_code == 413, r.text


def test_upload_dedups_by_sha(tmp_path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        payload = b"content-addressed dedup\n"
        files1 = {"file": ("first.txt",  io.BytesIO(payload), "text/plain")}
        files2 = {"file": ("second.txt", io.BytesIO(payload), "text/plain")}
        r1 = client.post("/science/uploads", headers=_headers(), files=files1, data={"user_id": "curro"})
        r2 = client.post("/science/uploads", headers=_headers(), files=files2, data={"user_id": "curro"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        b1, b2 = r1.json(), r2.json()
        assert b1["upload_id"] != b2["upload_id"]
        assert b1["sha256"] == b2["sha256"]
        sha = b1["sha256"]
        stored = tmp_path / sha[:2] / sha
        assert stored.exists()
        assert stored.stat().st_size == len(payload)


def test_list_and_fetch_round_trip(tmp_path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        payload = b"round-trip"
        files = {"file": ("rt.bin", io.BytesIO(payload), "application/octet-stream")}
        r = client.post("/science/uploads", headers=_headers(), files=files, data={"user_id": "curro"})
        assert r.status_code == 200
        upload_id = r.json()["upload_id"]
        rl = client.get("/science/uploads", headers=_headers())
        assert rl.status_code == 200
        items = rl.json()["items"]
        assert any(it["upload_id"] == upload_id for it in items)
        rl2 = client.get("/science/uploads?user_id=nobody", headers=_headers())
        assert rl2.status_code == 200
        assert rl2.json()["items"] == []
        rf = client.get(f"/science/uploads/{upload_id}", headers=_headers())
        assert rf.status_code == 200
        assert rf.content == payload


def test_fetch_unknown_id_returns_404(tmp_path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        r = client.get("/science/uploads/" + ("0" * 24), headers=_headers())
        assert r.status_code == 404


def test_fetch_returns_410_when_bytes_disappear(tmp_path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        payload = b"will-vanish"
        files = {"file": ("v.bin", io.BytesIO(payload), "application/octet-stream")}
        r = client.post("/science/uploads", headers=_headers(), files=files, data={"user_id": "curro"})
        assert r.status_code == 200
        sha = r.json()["sha256"]
        upload_id = r.json()["upload_id"]
        (tmp_path / sha[:2] / sha).unlink()
        r2 = client.get(f"/science/uploads/{upload_id}", headers=_headers())
        assert r2.status_code == 410


def test_unauthenticated_request_rejected(tmp_path):
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        files = {"file": ("x.bin", io.BytesIO(b"abc"), "application/octet-stream")}
        r = client.post("/science/uploads", files=files, data={"user_id": "curro"})
        assert r.status_code == 401


def test_rate_limit_trips(tmp_path):
    app, _ = _build_app(tmp_path, rate_limit=2)
    with TestClient(app) as client:
        files = lambda: {"file": ("x.bin", io.BytesIO(b"abc"), "application/octet-stream")}
        r1 = client.post("/science/uploads", headers=_headers(), files=files(), data={"user_id": "curro"})
        r2 = client.post("/science/uploads", headers=_headers(), files=files(), data={"user_id": "curro"})
        r3 = client.post("/science/uploads", headers=_headers(), files=files(), data={"user_id": "curro"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 429
