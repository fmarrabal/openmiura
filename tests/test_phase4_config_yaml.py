from __future__ import annotations

from pathlib import Path


def test_default_config_keeps_vault_and_mcp_env_flags_well_scoped() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg = (repo_root / 'configs' / 'openmiura.yaml').read_text(encoding='utf-8')
    assert 'enabled: "env:OPENMIURA_VAULT_ENABLED|false"' in cfg
    assert 'enabled: "env:OPENMIURA_MCP_ENABLED|false"' in cfg
    assert 'telegram:' in cfg
    assert 'allowlist:' in cfg
    assert 'enabled: "env:OPENMIURA_VAULT_ENABLED|false"\n    allow_user_ids' not in cfg
