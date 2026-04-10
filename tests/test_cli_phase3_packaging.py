from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import openmiura.cli as cli
from openmiura import __version__
from openmiura.core.audit import AuditStore

runner = CliRunner()


def test_resolve_config_path_accepts_directory(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    assert cli._resolve_config_path(str(cfg_dir)) == str(cfg_dir / "openmiura.yaml")


def test_click_version_command() -> None:
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_click_db_check_json(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.db"
    store = AuditStore(str(db_path))
    store.init_db()

    result = runner.invoke(cli.app, ["db", "check", "--db", str(db_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["db"] == str(db_path)
    assert payload["tables"]["sessions"] == 0
