from openmiura.interfaces.http.app import create_app as _create_app
from openmiura.pipeline import process_message


def create_app(config_path: str | None = None, gateway_factory=None):
    def _message_handler(gw, msg):
        return process_message(gw, msg)

    return _create_app(
        config_path=config_path,
        gateway_factory=gateway_factory,
        message_handler=_message_handler,
    )


app = create_app()

__all__ = ["app", "create_app", "process_message"]
