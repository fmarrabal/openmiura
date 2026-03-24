from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

from .runtime import Tool, ToolError

_MAX_REDIRECTS = 5
_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {80, 443, None}
_TEXTUAL_CONTENT_TYPES = ("text", "json", "xml", "html")


def _resolve_ips(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    ips: list[str] = []
    seen: set[str] = set()
    for info in infos:
        ip = info[4][0]
        if ip not in seen:
            seen.add(ip)
            ips.append(ip)
    return ips


def _is_private_ip(ip: str) -> bool:
    ip_obj = ipaddress.ip_address(ip)
    return (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def _validate_url_candidate(
    url: str,
    *,
    allow_all: bool,
    allowed_domains: set[str],
    block_private: bool,
) -> tuple[str, str]:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ToolError("Only http/https URLs are supported")

    if parsed.username or parsed.password:
        raise ToolError("Userinfo in URL is not allowed")

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ToolError("Invalid URL (no host)")

    port = parsed.port
    if port not in _ALLOWED_PORTS:
        raise ToolError(f"Port not allowed: {port}")

    if not allow_all:
        ok = any(host == d or host.endswith("." + d) for d in allowed_domains)
        if not ok:
            raise ToolError(f"Domain not allowed: {host}")

    if block_private:
        try:
            ips = _resolve_ips(host)
        except Exception as e:
            raise ToolError(f"Could not resolve host safely: {host}") from e
        if not ips:
            raise ToolError(f"Could not resolve host safely: {host}")
        for ip in ips:
            if _is_private_ip(ip):
                raise ToolError("Blocked: private/loopback host")

    return url, host


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "Fetch a URL via HTTP GET (text only) with allowlist controls."
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute http/https URL to fetch."},
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def run(self, ctx, **kwargs) -> str:
        url = (kwargs.get("url") or "").strip()
        if not url:
            raise ToolError("Missing url")

        if not re.match(r"^https?://", url, re.I):
            raise ToolError("Only http/https URLs are supported")

        decision = getattr(ctx, "sandbox_decision", None)
        if decision is not None:
            if not decision.network_enabled() or not decision.allows_tool(self.name):
                raise ToolError(f"Sandbox profile '{decision.profile_name}' denies outbound network access")

        wf = (
            ctx.settings.tools.web_fetch
            if (ctx.settings.tools and ctx.settings.tools.web_fetch)
            else None
        )
        timeout_s = wf.timeout_s if wf else 20
        max_bytes = wf.max_bytes if wf else 250000
        allow_all = wf.allow_all_domains if wf else True
        allowed_domains = set((wf.allowed_domains if wf else []) or [])
        allowed_domains = {
            d.strip().lower() for d in allowed_domains if str(d).strip()
        }
        block_private = wf.block_private_ips if wf else True

        sandbox_overrides = dict(decision.web_fetch_overrides() or {}) if decision is not None else {}
        if sandbox_overrides:
            timeout_s = int(sandbox_overrides.get("timeout_s", timeout_s) or timeout_s)
            max_bytes = int(sandbox_overrides.get("max_bytes", max_bytes) or max_bytes)
            if "allow_all_domains" in sandbox_overrides:
                allow_all = bool(sandbox_overrides.get("allow_all_domains"))
            if sandbox_overrides.get("allowed_domains"):
                allowed_domains = {
                    str(d).strip().lower()
                    for d in list(sandbox_overrides.get("allowed_domains") or [])
                    if str(d).strip()
                }
            if "block_private_ips" in sandbox_overrides:
                block_private = bool(sandbox_overrides.get("block_private_ips"))
            if sandbox_overrides.get("enabled") is False:
                raise ToolError(f"Sandbox profile '{decision.profile_name}' disables web_fetch")

        headers = {"User-Agent": "openMiura/0.1 (local-first)"}
        current_url, _ = _validate_url_candidate(
            url,
            allow_all=allow_all,
            allowed_domains=allowed_domains,
            block_private=block_private,
        )

        with httpx.Client(
            timeout=timeout_s,
            headers=headers,
            follow_redirects=False,
        ) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                r = client.get(current_url)

                if r.is_redirect:
                    location = r.headers.get("location") or ""
                    if not location:
                        raise ToolError(
                            "Redirect response without Location header"
                        )
                    current_url = urljoin(str(r.request.url), location)
                    current_url, _ = _validate_url_candidate(
                        current_url,
                        allow_all=allow_all,
                        allowed_domains=allowed_domains,
                        block_private=block_private,
                    )
                    continue

                r.raise_for_status()
                content_type = (r.headers.get("content-type") or "").lower()
                data = r.content
                break
            else:
                raise ToolError(f"Too many redirects (>{_MAX_REDIRECTS})")

        if len(data) > max_bytes:
            data = data[:max_bytes]

        if not any(token in content_type for token in _TEXTUAL_CONTENT_TYPES):
            raise ToolError(f"Unsupported content-type for MVP: {content_type}")

        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = data.decode(errors="replace")

        return (
            f"URL: {current_url}\n"
            f"Content-Type: {content_type}\n\n"
            f"{text}"
        )
