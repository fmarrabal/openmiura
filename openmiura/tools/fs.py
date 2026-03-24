from __future__ import annotations

from pathlib import Path

from .runtime import Tool, ToolError


_MAX_WRITE_CHARS = 1_000_000


def _resolve_in_sandbox(sandbox: Path, rel: str) -> Path:
    rel = (rel or "").strip().lstrip("/\\")
    if not rel:
        raise ToolError("Missing path")
    p = (sandbox / rel).resolve()
    sandbox = sandbox.resolve()
    if sandbox not in p.parents and p != sandbox:
        raise ToolError("Path traversal blocked")
    return p


def _filesystem_policy(ctx) -> dict:
    decision = getattr(ctx, "sandbox_decision", None)
    if decision is None:
        return {"read_only": False, "max_write_chars": _MAX_WRITE_CHARS}
    raw = dict(decision.filesystem_overrides() or {})
    raw.setdefault("read_only", False)
    raw.setdefault("max_write_chars", _MAX_WRITE_CHARS)
    return raw


class FsReadTool(Tool):
    name = "fs_read"
    description = "Read a UTF-8 text file from sandbox."
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path inside the sandbox."},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def run(self, ctx, **kwargs) -> str:
        decision = getattr(ctx, "sandbox_decision", None)
        if decision is not None and not decision.allows_tool(self.name):
            raise ToolError(f"Sandbox profile '{decision.profile_name}' denies filesystem reads")
        path = _resolve_in_sandbox(ctx.sandbox_dir, kwargs.get("path", ""))
        if not path.exists():
            raise ToolError(f"File not found: {path.name}")
        data = path.read_text(encoding="utf-8", errors="replace")
        return data


class FsWriteTool(Tool):
    name = "fs_write"
    description = "Write a UTF-8 text file to sandbox."
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path inside the sandbox."},
            "content": {"type": "string", "description": "UTF-8 text content to write."},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def run(self, ctx, **kwargs) -> str:
        decision = getattr(ctx, "sandbox_decision", None)
        policy = _filesystem_policy(ctx)
        if decision is not None and not decision.allows_tool(self.name):
            raise ToolError(f"Sandbox profile '{decision.profile_name}' denies filesystem writes")
        if bool(policy.get("read_only", False)):
            raise ToolError("Sandbox filesystem is read-only for this execution")
        path = _resolve_in_sandbox(ctx.sandbox_dir, kwargs.get("path", ""))
        content = str(kwargs.get("content", ""))
        max_write_chars = int(policy.get("max_write_chars", _MAX_WRITE_CHARS) or _MAX_WRITE_CHARS)
        if len(content) > max_write_chars:
            raise ToolError(f"Content too large for sandbox profile (>{max_write_chars} chars)")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"OK written: {path.name} ({len(content)} chars)"
