from __future__ import annotations

import inspect
import json
from typing import Any

from openmiura.core.schema import InboundMessage


def _require_fastmcp():
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency/runtime feature
        raise RuntimeError(
            "MCP support requires the 'mcp' package. Install it with `pip install mcp`."
        ) from exc
    return FastMCP


def _python_type_from_json(raw: str | None):
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    return mapping.get(str(raw or "string"), str)


def _signature_from_schema(schema: dict[str, Any]) -> inspect.Signature:
    properties = dict(schema.get("properties") or {})
    required = set(schema.get("required") or [])
    parameters: list[inspect.Parameter] = []
    for name, spec in properties.items():
        annotation = _python_type_from_json((spec or {}).get("type"))
        default = inspect._empty if name in required else None
        parameters.append(
            inspect.Parameter(
                name=name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )
    return inspect.Signature(parameters=parameters, return_annotation=str)


def build_mcp_server(gw):
    FastMCP = _require_fastmcp()
    mcp = FastMCP(
        name="openMiura",
        instructions="Access openMiura tools and semantic memory through MCP.",
    )

    tools_runtime = getattr(gw, "tools", None)
    registry = getattr(tools_runtime, "registry", None)
    if registry is not None:
        for tool_name in registry.names():
            tool = registry.get(tool_name)

            async def _runner(__tool_name: str = tool.name, **kwargs) -> str:
                return tools_runtime.run_tool(
                    agent_id="default",
                    session_id="mcp-session",
                    user_key="mcp:local",
                    tool_name=__tool_name,
                    args=kwargs,
                    confirmed=True,
                )

            _runner.__name__ = tool.name.replace("-", "_")
            _runner.__doc__ = tool.description or f"Run openMiura tool {tool.name}."
            _runner.__signature__ = _signature_from_schema(tool.parameters_schema)
            mcp.tool()(_runner)

    @mcp.resource("memory://search/{query}")
    def memory_search(query: str) -> str:
        memory = getattr(gw, "memory", None)
        if memory is None:
            return json.dumps({"items": [], "disabled": True}, ensure_ascii=False)
        hits = memory.recall(user_key="mcp:local", query=query, top_k=10)
        return json.dumps({"items": hits}, ensure_ascii=False)

    @mcp.tool()
    def chat(message: str) -> str:
        inbound = InboundMessage(channel="mcp", user_id="mcp:local", text=message)
        from openmiura.pipeline import process_message

        return process_message(gw, inbound).text

    return mcp


def build_sse_app(gw, mount_path: str | None = None):
    server = build_mcp_server(gw)
    if mount_path:
        return server.sse_app(mount_path)
    return server.sse_app()


def run_stdio(config_path: str | None = None) -> int:
    from openmiura.gateway import Gateway

    gw = Gateway.from_config(config_path)
    server = build_mcp_server(gw)
    server.run(transport="stdio")
    return 0


def run_sse(config_path: str | None = None) -> int:
    from openmiura.gateway import Gateway

    gw = Gateway.from_config(config_path)
    server = build_mcp_server(gw)
    mcp_cfg = getattr(gw.settings, "mcp", None)
    mount_path = getattr(mcp_cfg, "sse_path", "/mcp")
    host = getattr(mcp_cfg, "host", "127.0.0.1")
    port = getattr(mcp_cfg, "port", 8091)
    server.run(transport="sse", host=host, port=port, mount_path=mount_path)
    return 0
