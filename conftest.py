from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def _set_project_root() -> None:
    os.chdir(PROJECT_ROOT)


def pytest_sessionstart(session) -> None:
    _set_project_root()


def pytest_runtest_setup(item) -> None:
    _set_project_root()


def pytest_runtest_call(item) -> None:
    _set_project_root()