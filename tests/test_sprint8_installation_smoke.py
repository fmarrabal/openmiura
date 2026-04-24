from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx

from openmiura.application.packaging.service import PackagingHardeningService
from openmiura.core.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"Command failed ({completed.returncode}): {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


def _venv_paths(venv_dir: Path) -> tuple[Path, Path]:
    if os.name == 'nt':
        scripts = venv_dir / 'Scripts'
        return scripts / 'python.exe', scripts / 'openmiura.exe'
    scripts = venv_dir / 'bin'
    return scripts / 'python', scripts / 'openmiura'


def _create_venv(venv_dir: Path) -> tuple[Path, Path]:
    _run([sys.executable, '-m', 'venv', str(venv_dir)], cwd=ROOT)
    python_bin, openmiura_bin = _venv_paths(venv_dir)
    _run([str(python_bin), '-m', 'pip', 'install', '--upgrade', 'pip'], cwd=ROOT)
    return python_bin, openmiura_bin


def _invoke_openmiura(
    python_bin: Path,
    openmiura_bin: Path,
    *args: str,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 300,
):
    if openmiura_bin.exists():
        return _run([str(openmiura_bin), *args], cwd=cwd, env=env, timeout=timeout)
    return _run([str(python_bin), '-m', 'openmiura.cli', *args], cwd=cwd, env=env, timeout=timeout)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def _write_minimal_config(path: Path, *, port: int) -> None:
    db_path = path.parent / 'audit.db'
    sandbox_dir = path.parent / 'sandbox'
    path.write_text(
        f"""server:\n  host: 127.0.0.1\n  port: {port}\nstorage:\n  backend: sqlite\n  db_path: {db_path.as_posix()}\n  auto_migrate: true\nllm:\n  provider: ollama\n  base_url: http://127.0.0.1:11434\n  model: qwen2.5:7b-instruct\n  timeout_s: 5\nruntime: {{}}\nagents:\n  default:\n    system_prompt: hello\nmemory:\n  enabled: false\ntools:\n  sandbox_dir: {sandbox_dir.as_posix()}\n  web_fetch: {{}}\n  terminal: {{}}\nadmin:\n  enabled: false\nmcp:\n  enabled: false\nbroker:\n  enabled: false\nauth:\n  enabled: false\n""",
        encoding='utf-8',
    )


def test_load_settings_reads_project_root_dotenv(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / 'sample-root'
    cfg_dir = root / 'configs'
    cfg_dir.mkdir(parents=True)
    (root / '.env').write_text('OPENMIURA_SERVER_PORT=8099\nOPENMIURA_AUTH_ENABLED=false\n', encoding='utf-8')
    (cfg_dir / 'openmiura.yaml').write_text(
        """server:\n  host: 127.0.0.1\n  port: \"env:OPENMIURA_SERVER_PORT|8081\"\nstorage:\n  db_path: data/audit.db\nllm: {}\nruntime: {}\nagents:\n  default:\n    system_prompt: hola\nauth:\n  enabled: \"env:OPENMIURA_AUTH_ENABLED|true\"\n""",
        encoding='utf-8',
    )
    monkeypatch.chdir(root)
    monkeypatch.delenv('OPENMIURA_SERVER_PORT', raising=False)
    settings = load_settings(str(cfg_dir / 'openmiura.yaml'))
    assert settings.server.port == 8099
    assert settings.auth.enabled is False


def test_reproducible_manifest_keeps_files_when_root_path_contains_data(tmp_path: Path) -> None:
    project_root = tmp_path / 'data' / 'project'
    (project_root / 'openmiura').mkdir(parents=True)
    (project_root / 'configs').mkdir(parents=True)
    (project_root / 'openmiura' / '__init__.py').write_text('__version__ = "1.0.0"\n', encoding='utf-8')
    (project_root / 'configs' / 'openmiura.yaml').write_text('server: {}\n', encoding='utf-8')

    service = PackagingHardeningService()
    manifest = service._manifest_for_root(project_root, include=['openmiura', 'configs'])
    paths = {item['path'] for item in manifest['files']}
    assert 'openmiura/__init__.py' in paths
    assert 'configs/openmiura.yaml' in paths


def test_installation_docs_define_bundle_as_official_route() -> None:
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    install = (ROOT / 'docs' / 'installation.md').read_text(encoding='utf-8')
    publication = (ROOT / 'docs' / 'release_publication.md').read_text(encoding='utf-8')

    assert 'stable reproducible bundle' in readme
    assert 'ops/env/local-secure.env' in readme
    assert 'official minimum adoption path' in install
    assert 'reproducible bundle zip' in install
    assert 'wheel' in install and 'sdist' in install
    assert 'first external install (recommended)' in publication


def test_artifact_install_smoke_for_wheel_sdist_and_bundle(tmp_path: Path) -> None:
    dist_dir = tmp_path / 'dist'
    _run(
        [sys.executable, 'scripts/build_release_artifacts.py', '--dist-dir', str(dist_dir), '--tag', 'v1.0.0', '--target', 'desktop', '--strict'],
        cwd=ROOT,
        timeout=600,
    )

    wheel_path = next(dist_dir.glob('openmiura-1.0.0-*.whl'))
    sdist_path = next(dist_dir.glob('openmiura-1.0.0.tar.gz'))
    bundle_path = next(dist_dir.glob('openmiura-desktop-v1.0.0-*.zip'))

    # wheel install smoke
    wheel_venv = tmp_path / 'wheel-venv'
    wheel_python, wheel_openmiura = _create_venv(wheel_venv)
    _run([str(wheel_python), '-m', 'pip', 'install', '--force-reinstall', str(wheel_path)], cwd=ROOT, timeout=600)
    wheel_cfg = tmp_path / 'wheel-config.yaml'
    _write_minimal_config(wheel_cfg, port=_find_free_port())
    _invoke_openmiura(wheel_python, wheel_openmiura, 'version', cwd=ROOT)
    _invoke_openmiura(wheel_python, wheel_openmiura, 'doctor', '--config', str(wheel_cfg), cwd=ROOT)

    # sdist install smoke
    sdist_venv = tmp_path / 'sdist-venv'
    sdist_python, sdist_openmiura = _create_venv(sdist_venv)
    _run([str(sdist_python), '-m', 'pip', 'install', '--force-reinstall', str(sdist_path)], cwd=ROOT, timeout=600)
    sdist_cfg = tmp_path / 'sdist-config.yaml'
    _write_minimal_config(sdist_cfg, port=_find_free_port())
    _invoke_openmiura(sdist_python, sdist_openmiura, 'version', cwd=ROOT)
    _invoke_openmiura(sdist_python, sdist_openmiura, 'doctor', '--config', str(sdist_cfg), cwd=ROOT)

    # bundle install + run + /health smoke
    bundle_root = tmp_path / 'bundle'
    bundle_root.mkdir()
    with zipfile.ZipFile(bundle_path) as zf:
        zf.extractall(bundle_root)
    assert (bundle_root / 'configs' / 'openmiura.yaml').exists()
    assert (bundle_root / 'ops' / 'env' / 'local-secure.env').exists()

    bundle_venv = tmp_path / 'bundle-venv'
    bundle_python, bundle_openmiura = _create_venv(bundle_venv)
    _run([str(bundle_python), '-m', 'pip', 'install', '--force-reinstall', '.'], cwd=bundle_root, timeout=600)
    env = os.environ.copy()
    env['OPENMIURA_CONFIG'] = 'configs/openmiura.yaml'
    # local-secure profile, loaded from .env at bundle root
    (bundle_root / '.env').write_text((bundle_root / 'ops' / 'env' / 'local-secure.env').read_text(encoding='utf-8'), encoding='utf-8')
    port = _find_free_port()
    env['OPENMIURA_SERVER_PORT'] = str(port)
    env['OPENMIURA_DB_PATH'] = str((bundle_root / 'data' / 'audit.db').as_posix())
    env['OPENMIURA_SANDBOX_DIR'] = str((bundle_root / 'data' / 'sandbox').as_posix())
    _invoke_openmiura(bundle_python, bundle_openmiura, 'doctor', '--config', 'configs/openmiura.yaml', cwd=bundle_root, env=env, timeout=600)

    proc = subprocess.Popen(
        [str(bundle_openmiura), 'run', '--config', 'configs/openmiura.yaml', '--host', '127.0.0.1', '--port', str(port)],
        cwd=str(bundle_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 30
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                response = httpx.get(f'http://127.0.0.1:{port}/health', timeout=1.5)
                if response.status_code == 200:
                    payload = response.json()
                    assert payload['ok'] is True
                    assert payload['name'] == 'openMiura'
                    break
            except Exception as exc:  # pragma: no cover - transient startup timing
                last_error = exc
            time.sleep(0.5)
        else:
            stdout = proc.stdout.read() if proc.stdout else ''
            stderr = proc.stderr.read() if proc.stderr else ''
            raise AssertionError(f'/health did not come up. Last error: {last_error!r}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
