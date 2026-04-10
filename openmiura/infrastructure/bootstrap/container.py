from __future__ import annotations

from collections.abc import Callable

from openmiura.gateway import Gateway

GatewayFactory = Callable[[str | None], Gateway]


def resolve_gateway_factory(gateway_factory: GatewayFactory | None = None) -> GatewayFactory:
    return gateway_factory or Gateway.from_config


def build_gateway(config_path: str | None = None, gateway_factory: GatewayFactory | None = None) -> Gateway:
    factory = resolve_gateway_factory(gateway_factory)
    return factory(config_path)


def probe_gateway(config_path: str | None = None, gateway_factory: GatewayFactory | None = None) -> Gateway | None:
    factory = resolve_gateway_factory(gateway_factory)
    try:
        return factory(config_path)
    except Exception:
        return None
