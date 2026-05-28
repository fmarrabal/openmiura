from __future__ import annotations

import base64
import hashlib
from typing import Any

from pydantic import BaseModel, Field


class InboundMessage(BaseModel):
    channel: str = "http"
    user_id: str
    text: str
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # H3.3c — multi-modal attachments. Each entry mirrors the
    # ``Attachment`` dataclass shape from ``openmiura.core.llm.types``:
    #   {kind: "image", media_type: "image/png",
    #    data_b64: "<base64>", sha256?: "<hex>"}
    # We accept dicts (not the dataclass) so the JSON wire payload
    # round-trips cleanly through Pydantic and so the HTTP layer
    # does not have to import the LLM-types module.
    # Non-image entries and malformed entries are filtered later
    # (provider translators + audit hashing both run defensively).
    attachments: list[dict[str, Any]] = Field(default_factory=list)

    def attachments_audit_meta(self) -> list[dict[str, Any]]:
        """Return a *byte-free* summary of every attachment,
        safe to dump into the audit ``events`` table.

        We never persist the raw ``data_b64`` (a 1 MiB image
        would balloon every audit row). Instead we record:

          - ``sha256``     — hex digest of the decoded bytes
                              (the caller's pre-computed digest
                              is trusted if present and well-
                              formed; otherwise recomputed).
          - ``size_bytes`` — decoded payload size.
          - ``media_type`` — original MIME.
          - ``kind``       — discriminator (today only 'image').

        Malformed entries (non-dict, missing fields, undecodable
        base64) are skipped silently — the audit layer should
        never raise on bad input.
        """
        out: list[dict[str, Any]] = []
        for a in self.attachments or []:
            if not isinstance(a, dict):
                continue
            kind = str(a.get("kind") or "").strip().lower()
            media = str(a.get("media_type") or "").strip()
            data = a.get("data_b64")
            if not (kind and media and isinstance(data, str) and data):
                continue
            try:
                raw = base64.b64decode(data, validate=False)
            except Exception:
                continue
            sha_in = str(a.get("sha256") or "").strip().lower()
            sha = sha_in if (len(sha_in) == 64 and all(c in "0123456789abcdef" for c in sha_in)) \
                  else hashlib.sha256(raw).hexdigest()
            out.append({
                "kind":       kind,
                "media_type": media,
                "size_bytes": len(raw),
                "sha256":     sha,
            })
        return out

    def model_dump_for_audit(self) -> dict[str, Any]:
        """Convenience: ``model_dump`` but with ``attachments``
        replaced by their byte-free meta. Used by the pipeline
        + streaming layers to log the inbound turn without
        spilling image bytes into the audit DB.
        """
        out = self.model_dump(exclude={"attachments"})
        meta = self.attachments_audit_meta()
        if meta:
            out["attachments_meta"] = meta
        return out


class OutboundMessage(BaseModel):
    channel: str = "http"
    user_id: str
    session_id: str
    agent_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
