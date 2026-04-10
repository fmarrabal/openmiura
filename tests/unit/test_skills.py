from pathlib import Path
from openmiura.agents.skills import SkillLoader
from openmiura.tools.runtime import Tool, ToolRegistry


class _EchoTool(Tool):
    name = 'echo_skill'
    description = 'echo'

    def run(self, ctx, **kwargs):
        return 'ok'


def test_skill_loader_reads_manifest_prompt_file_and_registers_tools(tmp_path):
    skill_dir = tmp_path / 'skills' / 'researcher'
    tools_dir = skill_dir / 'tools'
    tools_dir.mkdir(parents=True)
    (skill_dir / 'manifest.yaml').write_text(
        'manifest_version: "1"\n'
        'name: researcher\n'
        'version: 1.0.0\n'
        'tools: [web_fetch]\n'
        'tool_modules: [extra.py]\n'
        'prompt_file: prompt.md\n'
        'system_prompt_extension: extra\n'
        'required_permissions: [web_access]\n',
        encoding='utf-8',
    )
    (skill_dir / 'prompt.md').write_text('Prompt from file', encoding='utf-8')
    (tools_dir / 'extra.py').write_text(
        'from openmiura.tools.runtime import Tool\n\n'
        'class EchoTool(Tool):\n'
        '    name = "echo_skill"\n'
        '    description = "echo"\n'
        '    def run(self, ctx, **kwargs):\n'
        '        return "ok"\n\n'
        'TOOLS = [EchoTool()]\n',
        encoding='utf-8',
    )

    loader = SkillLoader(skill_dir.parent, include_builtin=False)
    all_skills = loader.load_all()
    assert 'researcher' in all_skills
    cfg = loader.extend_agent_config({'system_prompt': 'base', 'skills': ['researcher'], 'allowed_tools': ['time_now']})
    assert 'web_fetch' in cfg['allowed_tools']
    assert 'extra' in cfg['system_prompt']
    assert 'Prompt from file' in cfg['system_prompt']
    assert 'web_access' in cfg['required_permissions']

    registry = ToolRegistry()
    loaded = loader.register_skill_tools(registry, ['researcher'])
    assert loaded
    assert 'echo_skill' in registry.names()


def test_skill_loader_ignores_disabled_skill(tmp_path):
    skill_dir = tmp_path / 'skills' / 'disabled_one'
    skill_dir.mkdir(parents=True)
    (skill_dir / 'manifest.yaml').write_text('enabled: false\nname: disabled_one\n', encoding='utf-8')

    loader = SkillLoader(skill_dir.parent, include_builtin=False)
    assert loader.load_all() == {}


def test_skill_loader_reports_invalid_manifest(tmp_path):
    skill_dir = tmp_path / 'skills' / 'broken'
    skill_dir.mkdir(parents=True)
    (skill_dir / 'manifest.yaml').write_text('name: broken\nunknown_field: true\n', encoding='utf-8')

    loader = SkillLoader(skill_dir.parent, include_builtin=False)
    assert loader.load_all() == {}
    assert loader.errors


def test_external_skill_overrides_builtin_by_name():
    loader = SkillLoader(Path(__file__).resolve().parents[2] / 'skills')
    skills = loader.load_all()
    assert 'researcher' in skills
    assert skills['researcher'].source == 'external'
