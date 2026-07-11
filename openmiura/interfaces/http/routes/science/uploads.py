"""science/uploads.py — content-addressed file upload surface.

Closes the *real file upload endpoint* gap documented since
UI v2 PR-C2 (#54). The C2 view stages files client-side and
embeds metadata in the chat turn; the science user has no
way to actually persist the bytes server-side.

Storage layout:

    <upload_dir>/
        <sha256[:2]>/<sha256>           ← raw bytes, content-addressed
        index.jsonl                     ← append-only metadata index

Each line of ``index.jsonl`` is a JSON object with the public
upload metadata (``upload_id``, ``sha256``, ``name``, ``size``,
``mime``, ``user_id``, ``session_id``, ``stored_at``,
``description``). The ``upload_id`` is a fresh random hex so
two users uploading the same content get distinct ids; the
bytes are deduplicated on disk via the sha256 prefix path.

Endpoints
---------

  POST   /science/uploads
         multipart/form-data with ``file`` plus form fields.
         Returns the metadata record. **Confirmed write** (the
         action records an audit event under
         ``channel='science', action='upload'``).

  GET    /science/uploads
         List recent uploads, optionally filtered by user_id.
         Returns ``{ "items": [<metadata>] }``.

  GET    /science/uploads/{upload_id}
         Returns the binary bytes (``application/octet-stream``
         or the stored ``mime`` if known). 404 if unknown.

Caps (configurable via ``science:`` section of the config):

  max_upload_bytes      hard size cap (default 50 MiB)
  rate_limit_per_minute per-IP+token rate limit (default 30)

Auth: every endpoint requires the admin token via
``_require_science_auth``. See ``_helpers.py`` for the
rationale.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from openmiura.interfaces.http.routes.science._helpers import (
    _audit_science,
    _require_science_auth,
)

router = APIRouter(tags=["science"])

# We stream the upload from the request in fixed-size blocks to
# bound memory (a single 50 MiB file held entirely in memory is
# acceptable; the cap protects us from a stuck client trying to
# leak megabytes-per-minute). The 1 MiB block size matches what
# Starlette uses internally for SpooledTemporaryFile.
_BLOCK = 1024 * 1024


def _upload_dir(gw) -> Path:
    cfg = getattr(gw.settings, "science", None)
    raw = (getattr(cfg, "upload_dir", "data/science_uploads") if cfg else "data/science_uploads")
    p = Path(raw).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _max_bytes(gw) -> int:
    cfg = getattr(gw.settings, "science", None)
    return int(getattr(cfg, "max_upload_bytes", 50 * 1024 * 1024) if cfg else 50 * 1024 * 1024)


def _index_path(gw) -> Path:
    return _upload_dir(gw) / "index.jsonl"


def _stored_path(gw, sha256_hex: str) -> Path:
    base = _upload_dir(gw)
    return base / sha256_hex[:2] / sha256_hex


def _index_append(gw, record: dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with open(_index_path(gw), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _index_read_all(gw) -> list[dict[str, Any]]:
    path = _index_path(gw)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # A corrupt line shouldn't kill the listing —
                # log nothing (no logger here) and skip.
                continue
    return out


def _index_find(gw, upload_id: str) -> Optional[dict[str, Any]]:
    if not upload_id:
        return None
    for rec in _index_read_all(gw):
        if rec.get("upload_id") == upload_id:
            return rec
    return None


@router.post("/science/uploads")
async def science_upload(
    request: Request,
    file: UploadFile = File(..., description="The file to stage on the server."),
    user_id: str = Form(..., description="Principal id the upload is attributed to."),
    session_id: str = Form("", description="Optional chat session this upload relates to."),
    description: str = Form("", description="Optional one-line note for the audit trail."),
):
    """Persist a file, content-addressed by SHA-256, and record
    the metadata in the audit trail.

    Returns the metadata record. The bytes are written exactly
    once even if the same content is uploaded again — the
    ``upload_id`` is fresh on every call so distinct uploads
    of the same content are still distinguishable in the
    audit log.
    """
    gw = _require_science_auth(request)

    cap = _max_bytes(gw)
    if cap <= 0:
        raise HTTPException(status_code=503, detail="Uploads disabled by configuration")

    uid = (user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=422, detail="user_id is required")

    name = (file.filename or "").strip() or "upload.bin"
    mime = (file.content_type or "application/octet-stream").strip()

    # Stream the file in blocks so we can enforce the size cap
    # without ever materialising the full payload twice. We
    # accumulate the bytes (we need the full content for the
    # SHA + the disk write); if the limit is exceeded we abort
    # mid-stream and return 413.
    hasher = hashlib.sha256()
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(_BLOCK)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {cap}-byte upload cap",
            )
        hasher.update(chunk)
        chunks.append(chunk)
    await file.close()

    if total == 0:
        raise HTTPException(status_code=422, detail="Empty file")

    sha = hasher.hexdigest()
    target = _stored_path(gw, sha)

    def _persist_content() -> None:
        # Blocking disk I/O — run in the threadpool, not on the event loop.
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write to a sibling .tmp first so a crashing process
        # cannot leave a half-written content-addressed file
        # under its canonical name.
        tmp = target.with_suffix(target.suffix + ".tmp")
        with open(tmp, "wb") as fh:
            for c in chunks:
                fh.write(c)
        tmp.replace(target)

    await run_in_threadpool(_persist_content)

    upload_id = secrets.token_hex(12)  # 24 chars, ~96 bits of entropy
    stored_at = int(time.time())

    record = {
        "upload_id":   upload_id,
        "sha256":      sha,
        "name":        name,
        "size":        total,
        "mime":        mime,
        "user_id":     uid,
        "session_id":  (session_id or "").strip() or None,
        "description": (description or "").strip() or None,
        "stored_at":   stored_at,
    }
    await run_in_threadpool(_index_append, gw, record)

    audit_id = await run_in_threadpool(_audit_science, gw, "upload", {
        "upload_id":  upload_id,
        "sha256":     sha,
        "size":       total,
        "mime":       mime,
        "name":       name,
        "user_id":    uid,
        "session_id": record["session_id"],
    })
    if audit_id is not None:
        record["audit_event_id"] = audit_id

    return JSONResponse(record)


@router.get("/science/uploads")
def science_uploads_list(
    request: Request,
    user_id: Optional[str] = Query(default=None, description="Filter by user_id."),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Return the most recent uploads, newest first.

    Filters by ``user_id`` if supplied. The result is bounded by
    ``limit`` (default 100, hard cap 500). The metadata index is
    read in full each call — for the kind of volume a science
    operator generates (tens to hundreds of files per scope) this
    is cheaper than maintaining a secondary database table.
    """
    gw = _require_science_auth(request)
    items = _index_read_all(gw)
    if user_id:
        uid = user_id.strip()
        items = [r for r in items if r.get("user_id") == uid]
    items.sort(key=lambda r: r.get("stored_at", 0), reverse=True)
    return {"items": items[:limit], "total": len(items)}


@router.get("/science/uploads/{upload_id}")
def science_upload_fetch(upload_id: str, request: Request):
    """Stream the binary bytes for the given upload id.

    Returns 404 if either the metadata or the on-disk file are
    missing. The ``Content-Type`` header reflects the stored
    mime when known; otherwise ``application/octet-stream``.
    """
    gw = _require_science_auth(request)
    rec = _index_find(gw, upload_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    sha = str(rec.get("sha256") or "")
    if not sha:
        raise HTTPException(status_code=410, detail="Upload metadata is missing the sha256")
    path = _stored_path(gw, sha)
    if not path.exists():
        # Metadata exists but the bytes are gone — surface a
        # distinct status so a caller can tell "never existed"
        # apart from "deleted on disk".
        raise HTTPException(status_code=410, detail="Upload bytes no longer available on disk")
    media_type = str(rec.get("mime") or "application/octet-stream")
    filename = str(rec.get("name") or sha)
    return FileResponse(str(path), media_type=media_type, filename=filename)
