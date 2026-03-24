from __future__ import annotations

import inspect
import types
from dataclasses import dataclass
from typing import Any, Callable, get_args, get_origin

import click


@dataclass
class OptionInfo:
    default: Any = None
    param_decls: tuple[str, ...] = ()
    help: str | None = None


def Option(default: Any = None, *param_decls: str, help: str | None = None, **_: Any) -> OptionInfo:
    return OptionInfo(default=default, param_decls=tuple(param_decls), help=help)


Exit = click.exceptions.Exit

echo = click.echo


def _normalize_type(annotation: Any) -> Any:
    if annotation is inspect._empty:
        return None
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    if origin in (types.UnionType, getattr(__import__("typing"), "Union", object)):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        return _normalize_type(args[0]) if args else None
    return None


class Typer:
    def __init__(
        self,
        *,
        help: str | None = None,
        no_args_is_help: bool = False,
        context_settings: dict[str, Any] | None = None,
        add_completion: bool = False,
        name: str | None = None,
        **_: Any,
    ) -> None:
        self._group = click.Group(
            name=name,
            help=help,
            invoke_without_command=not no_args_is_help,
            no_args_is_help=no_args_is_help,
            context_settings=context_settings or {},
        )
        self._add_completion = add_completion

    @property
    def name(self) -> str | None:
        return self._group.name

    @name.setter
    def name(self, value: str | None) -> None:
        self._group.name = value

    def main(self, *args: Any, **kwargs: Any) -> Any:
        return self._group.main(*args, **kwargs)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._group, item)

    def command(self, name: str | None = None) -> Callable[[Callable[..., Any]], click.Command]:
        def decorator(func: Callable[..., Any]) -> click.Command:
            cmd = self._build_command(func, name=name)
            self._group.add_command(cmd)
            return cmd
        return decorator

    def add_typer(self, app: 'Typer', *, name: str) -> None:
        self._group.add_command(app._group, name)

    def __call__(self, *, prog_name: str | None = None, args: list[str] | None = None, standalone_mode: bool = True) -> Any:
        return self._group.main(args=args, prog_name=prog_name, standalone_mode=standalone_mode)

    def _build_command(self, func: Callable[..., Any], *, name: str | None = None) -> click.Command:
        cmd_name = name or func.__name__.replace('_', '-')
        callback = func
        sig = inspect.signature(func)
        for param in reversed(list(sig.parameters.values())):
            default = param.default
            annotation = _normalize_type(param.annotation)
            option_name = f"--{param.name.replace('_', '-')}"
            param_decls: tuple[str, ...]
            help_text: str | None = None
            default_value: Any = None if default is inspect._empty else default
            if isinstance(default, OptionInfo):
                param_decls = default.param_decls or (option_name,)
                help_text = default.help
                default_value = default.default
            else:
                param_decls = (option_name,)
            kwargs: dict[str, Any] = {"help": help_text, "show_default": default_value is not None}
            if annotation is bool or isinstance(default_value, bool):
                kwargs["is_flag"] = True
                kwargs["default"] = bool(default_value)
            else:
                kwargs["default"] = default_value
                if annotation is int:
                    kwargs["type"] = int
                elif annotation is str:
                    kwargs["type"] = str
            callback = click.option(*param_decls, param.name, **kwargs)(callback)
        return click.command(name=cmd_name)(callback)


__all__ = ["Typer", "Option", "OptionInfo", "Exit", "echo"]
