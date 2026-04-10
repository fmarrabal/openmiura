from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from openmiura.core.config import Settings


@dataclass(frozen=True)
class WorkerSpec:
    name: str
    command: list[str]
    enabled: bool = True


class SubprocessWorker:
    def __init__(self, spec: WorkerSpec, *, env: dict[str, str] | None = None, cwd: str | None = None) -> None:
        self.spec = spec
        self.env = env
        self.cwd = cwd
        self.proc: subprocess.Popen[str] | None = None

    def start(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen(self.spec.command, env=self.env, cwd=self.cwd)

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None


class WorkerManager:
    def __init__(self, workers: Iterable[SubprocessWorker]) -> None:
        self.workers = list(workers)

    def __enter__(self) -> "WorkerManager":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
        return None

    def start(self) -> None:
        for worker in self.workers:
            worker.start()

    def stop(self) -> None:
        for worker in reversed(self.workers):
            worker.stop()

    def running_names(self) -> list[str]:
        return [worker.spec.name for worker in self.workers]


# -------------------------------
# Fase 1/2 compatibility helpers
# -------------------------------
def resolve_worker_mode(*, with_workers: bool, settings: Settings) -> str:
    if with_workers:
        return "inline"
    mode = str(getattr(settings.runtime, "worker_mode", "external") or "external").strip().lower()
    return mode if mode in {"inline", "external"} else "external"


def build_worker_specs(settings: Settings) -> list[WorkerSpec]:
    specs: list[WorkerSpec] = []
    repo_root = Path(__file__).resolve().parents[2]

    telegram_cfg = getattr(settings, "telegram", None)
    if telegram_cfg and getattr(telegram_cfg, "bot_token", None) and str(getattr(telegram_cfg, "mode", "polling")).strip().lower() == "polling":
        specs.append(
            WorkerSpec(
                name="telegram_polling",
                command=[sys.executable, str(repo_root / "scripts" / "telegram_poll_worker.py")],
            )
        )

    discord_cfg = getattr(settings, "discord", None)
    if discord_cfg and getattr(discord_cfg, "bot_token", None):
        specs.append(
            WorkerSpec(
                name="discord_gateway",
                command=[sys.executable, str(repo_root / "scripts" / "discord_worker.py")],
            )
        )

    return specs


def build_worker_manager(*, settings: Settings, config_path: str) -> WorkerManager:
    env = os.environ.copy()
    env["OPENMIURA_CONFIG"] = config_path
    cwd = str(Path(__file__).resolve().parents[2])
    workers = [SubprocessWorker(spec, env=env, cwd=cwd) for spec in build_worker_specs(settings)]
    return WorkerManager(workers)


# -------------------------------
# Current runtime API wrappers
# -------------------------------
@dataclass
class WorkerProcess:
    name: str
    argv: list[str]
    process: subprocess.Popen[str]


@dataclass
class WorkerSupervisor:
    config_path: str
    processes: list[WorkerProcess] = field(default_factory=list)

    @property
    def started(self) -> list[str]:
        return [p.name for p in self.processes]

    def stop(self) -> None:
        for proc in self.processes:
            try:
                proc.process.terminate()
            except Exception:
                pass
        for proc in self.processes:
            try:
                proc.process.wait(timeout=5)
            except Exception:
                try:
                    proc.process.kill()
                except Exception:
                    pass


def build_worker_commands(settings: Settings) -> list[tuple[str, list[str]]]:
    normalized: list[tuple[str, list[str]]] = []
    for spec in build_worker_specs(settings):
        name = spec.name
        if name == "telegram_polling":
            name = "telegram"
        elif name == "discord_gateway":
            name = "discord"
        normalized.append((name, list(spec.command)))
    return normalized


def should_start_inline_workers(settings: Settings, force_with_workers: bool = False) -> bool:
    return resolve_worker_mode(with_workers=force_with_workers, settings=settings) == "inline"


def start_inline_workers(settings: Settings, *, config_path: str) -> WorkerSupervisor:
    env = os.environ.copy()
    env["OPENMIURA_CONFIG"] = config_path
    supervisor = WorkerSupervisor(config_path=config_path)
    for name, argv in build_worker_commands(settings):
        process = subprocess.Popen(argv, env=env)
        supervisor.processes.append(WorkerProcess(name=name, argv=argv, process=process))
    return supervisor
