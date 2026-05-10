"""Migration dataclass — small module so batches do not pull in the full migrations package on import."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openmiura.core.db import DBConnection, _normalize_backend


@dataclass(frozen=True)


class Migration:
    version: int
    name: str
    sqlite_sql: tuple[str, ...]
    postgres_sql: tuple[str, ...]
    sqlite_down_sql: tuple[str, ...] = ()
    postgres_down_sql: tuple[str, ...] = ()

    def sql_for(self, backend: str) -> tuple[str, ...]:
        return self.postgres_sql if _normalize_backend(backend) == "postgresql" else self.sqlite_sql

    def down_sql_for(self, backend: str) -> tuple[str, ...]:
        return self.postgres_down_sql if _normalize_backend(backend) == "postgresql" else self.sqlite_down_sql
