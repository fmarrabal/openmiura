"""Public extension surface for openMiura.

This package formalizes the extensibility contracts introduced in roadmap
phase 1. The goal is to let tools, skills, providers and adapters evolve
against a stable SDK instead of importing private internals.
"""

__all__ = ["ExtensionLoader", "LoadedExtension"]


def __getattr__(name: str):
    if name in {"ExtensionLoader", "LoadedExtension"}:
        from .loader import ExtensionLoader, LoadedExtension
        return {"ExtensionLoader": ExtensionLoader, "LoadedExtension": LoadedExtension}[name]
    raise AttributeError(name)
