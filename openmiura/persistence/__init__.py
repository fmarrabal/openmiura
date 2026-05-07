"""Persistence layer for openMiura.

Each module in this package owns the persistence logic of one bounded
domain (voice, evaluations, memory, auth, workflows, canvas, release,
runtime, runtime adapters, tools). The ``AuditStore`` class in
``openmiura.core.audit`` keeps its public API stable and delegates to
these repositories.

The ``base`` module exposes shared primitives (scope filtering helpers)
that every repository uses.
"""
