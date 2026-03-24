from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .fs import _resolve_in_sandbox
from .runtime import Tool, ToolError


def _role_policy(terminal_cfg: Any, role: str | None) -> dict[str, Any]:
    role_key = str(role or "user").strip().lower() or "user"
    role_policies = dict(getattr(terminal_cfg, "role_policies", {}) or {})
    override = dict(role_policies.get(role_key) or {})
    return {
        "timeout_s": int(override.get("timeout_s", getattr(terminal_cfg, "timeout_s", 30) or 30)),
        "max_timeout_s": int(override.get("max_timeout_s", getattr(terminal_cfg, "max_timeout_s", 120) or 120)),
        "max_output_chars": int(override.get("max_output_chars", getattr(terminal_cfg, "max_output_chars", 12000) or 12000)),
        "shell_executable": str(override.get("shell_executable", getattr(terminal_cfg, "shell_executable", "") or "")).strip() or None,
        "allow_shell": bool(override.get("allow_shell", getattr(terminal_cfg, "allow_shell", True))),
        "allow_shell_metacharacters": bool(override.get("allow_shell_metacharacters", getattr(terminal_cfg, "allow_shell_metacharacters", True))),
        "allow_multiline": bool(override.get("allow_multiline", getattr(terminal_cfg, "allow_multiline", False))),
        "require_explicit_allowlist": bool(override.get("require_explicit_allowlist", getattr(terminal_cfg, "require_explicit_allowlist", False))),
        "allowed_commands": {str(x).strip().lower() for x in (override.get("allowed_commands") or getattr(terminal_cfg, "allowed_commands", []) or []) if str(x).strip()},
        "blocked_commands": {str(x).strip().lower() for x in (override.get("blocked_commands") or getattr(terminal_cfg, "blocked_commands", []) or []) if str(x).strip()},
        "blocked_patterns": [str(x) for x in (override.get("blocked_patterns") or getattr(terminal_cfg, "blocked_patterns", []) or []) if str(x).strip()],
    }


def _merge_sandbox_overrides(policy: dict[str, Any], sandbox_decision: Any | None) -> dict[str, Any]:
    merged = dict(policy)
    if sandbox_decision is None:
        return merged
    overrides = dict(sandbox_decision.terminal_overrides() or {})
    if not overrides:
        return merged
    scalar_keys = {
        "timeout_s",
        "max_timeout_s",
        "max_output_chars",
        "shell_executable",
        "allow_shell",
        "allow_shell_metacharacters",
        "allow_multiline",
        "require_explicit_allowlist",
    }
    for key in scalar_keys:
        if key in overrides:
            merged[key] = overrides.get(key)
    if "allowed_commands" in overrides:
        merged["allowed_commands"] = {str(x).strip().lower() for x in (overrides.get("allowed_commands") or []) if str(x).strip()}
    if "blocked_commands" in overrides:
        merged["blocked_commands"] = {str(x).strip().lower() for x in (overrides.get("blocked_commands") or []) if str(x).strip()}
    if "blocked_patterns" in overrides:
        merged["blocked_patterns"] = [str(x) for x in (overrides.get("blocked_patterns") or []) if str(x).strip()]
    return merged


_WINDOWS_CMD_BUILTINS = {
    "assoc", "break", "call", "cd", "chdir", "cls", "color", "copy", "date", "del", "dir",
    "echo", "endlocal", "erase", "for", "ftype", "md", "mkdir", "mklink", "move", "path",
    "pause", "popd", "prompt", "pushd", "rd", "rem", "ren", "rename", "rmdir", "set",
    "setlocal", "shift", "start", "time", "title", "type", "ver", "verify", "vol",
}


def _windows_builtin_invocation(command: str, executable: str, allow_shell: bool) -> tuple[object, bool, str | None]:
    if allow_shell or os.name != "nt" or executable not in _WINDOWS_CMD_BUILTINS:
        return command, allow_shell, None
    comspec = os.environ.get("ComSpec") or os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "cmd.exe")
    return [comspec, "/d", "/c", command], False, None


_DEFENSIVE_BLOCKLIST = {
    "shutdown", "reboot", "halt", "poweroff", "mkfs", "fdisk", "diskpart", "format", "passwd",
}


def terminal_policy_for_role(terminal_cfg: Any, role: str | None, sandbox_decision: Any | None = None) -> dict[str, Any]:
    policy = _role_policy(terminal_cfg, role)
    policy = _merge_sandbox_overrides(policy, sandbox_decision)
    policy["blocked_commands"] = set(policy.get("blocked_commands") or set()) | set(_DEFENSIVE_BLOCKLIST)
    return policy


def validate_terminal_command_policy(command: str, terminal_cfg: Any, role: str | None = None, sandbox_decision: Any | None = None) -> tuple[list[str], str, dict[str, Any]]:
    cmd = str(command or "").strip()
    if not cmd:
        raise ToolError("Missing command")
    if sandbox_decision is not None and not sandbox_decision.allows_tool("terminal_exec"):
        raise ToolError(f"Sandbox profile '{sandbox_decision.profile_name}' denies terminal execution")
    policy = terminal_policy_for_role(terminal_cfg, role, sandbox_decision=sandbox_decision)
    parts = shlex.split(cmd, posix=True)
    if not parts:
        raise ToolError("Missing command")
    executable = Path(parts[0]).name.lower()
    if not policy["allow_multiline"] and ("\n" in cmd or "\r" in cmd):
        raise ToolError("Multiline commands are not allowed by policy")
    if policy["require_explicit_allowlist"] and not policy["allowed_commands"]:
        raise ToolError("Terminal policy requires an explicit allowlist for this role")
    if policy["blocked_commands"] and executable in policy["blocked_commands"]:
        raise ToolError(f"Command blocked by policy: {executable}")
    if policy["allowed_commands"] and executable not in policy["allowed_commands"]:
        raise ToolError(f"Command not allowlisted for role '{str(role or 'user').lower()}': {executable}")
    for pattern in list(policy.get("blocked_patterns") or []):
        try:
            if re.search(pattern, cmd, flags=re.IGNORECASE):
                raise ToolError(f"Command matches blocked pattern: {pattern}")
        except re.error:
            continue
    if not policy["allow_shell_metacharacters"] and re.search(r"[|&><`$()]", cmd):
        raise ToolError("Shell metacharacters are not allowed by policy")
    return parts, executable, policy


class TerminalExecTool(Tool):
    name = 'terminal_exec'
    description = 'Execute a terminal command inside the sandbox when policy allows it.'
    parameters_schema = {
        'type': 'object',
        'properties': {
            'command': {'type': 'string', 'description': 'Shell command to execute.'},
            'cwd': {'type': 'string', 'description': 'Optional relative working directory inside the sandbox.'},
            'timeout_s': {'type': 'integer', 'description': 'Optional timeout override in seconds.'},
        },
        'required': ['command'],
        'additionalProperties': False,
    }

    def run(self, ctx, **kwargs) -> str:
        command = str(kwargs.get('command') or '').strip()
        if not command:
            raise ToolError('Missing command')

        terminal_cfg = getattr(ctx.settings.tools, 'terminal', None) if ctx.settings.tools else None
        try:
            parts, executable, policy = validate_terminal_command_policy(
                command,
                terminal_cfg,
                getattr(ctx, 'user_role', 'user'),
                sandbox_decision=getattr(ctx, 'sandbox_decision', None),
            )
        except ToolError:
            try:
                ctx.audit.log_event(
                    'security',
                    'terminal',
                    getattr(ctx, 'user_key', ''),
                    '',
                    {
                        'event': 'terminal_exec_denied',
                        'role': getattr(ctx, 'user_role', 'user'),
                        'command': command,
                        'sandbox_profile': getattr(getattr(ctx, 'sandbox_decision', None), 'profile_name', ''),
                    },
                )
            except Exception:
                pass
            raise

        timeout_s = int(kwargs.get('timeout_s') or policy.get('timeout_s', 30) or 30)
        timeout_s = min(timeout_s, int(policy.get('max_timeout_s', 120) or 120))
        max_output_chars = int(policy.get('max_output_chars', 12000) or 12000)
        shell_executable = policy.get('shell_executable')
        allow_shell = bool(policy.get('allow_shell', True))

        rel_cwd = str(kwargs.get('cwd') or '').strip()
        workdir: Path = ctx.sandbox_dir
        if rel_cwd:
            workdir = _resolve_in_sandbox(ctx.sandbox_dir, rel_cwd)
            if not workdir.exists() or not workdir.is_dir():
                raise ToolError(f'Working directory not found: {rel_cwd}')

        run_args, run_shell, run_executable = _windows_builtin_invocation(command, executable, allow_shell)
        if not allow_shell and run_args is not command:
            shell_executable = None
        elif not allow_shell:
            run_args = parts
            run_shell = False
            run_executable = None
        else:
            run_executable = shell_executable

        try:
            completed = subprocess.run(
                run_args,
                shell=run_shell,
                cwd=str(workdir),
                executable=run_executable,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            try:
                ctx.audit.log_event(
                    'security',
                    'terminal',
                    getattr(ctx, 'user_key', ''),
                    '',
                    {
                        'event': 'terminal_exec_timeout',
                        'role': getattr(ctx, 'user_role', 'user'),
                        'command': command,
                        'cwd': str(workdir),
                        'timeout_s': timeout_s,
                        'sandbox_profile': getattr(getattr(ctx, 'sandbox_decision', None), 'profile_name', ''),
                    },
                )
            except Exception:
                pass
            raise ToolError(f'Command timed out after {timeout_s}s') from exc
        stdout = completed.stdout or ''
        stderr = completed.stderr or ''
        if len(stdout) > max_output_chars:
            stdout = stdout[:max_output_chars] + '\n...[truncated]'
        if len(stderr) > max_output_chars:
            stderr = stderr[:max_output_chars] + '\n...[truncated]'

        try:
            ctx.audit.log_event(
                'security',
                'terminal',
                getattr(ctx, 'user_key', ''),
                '',
                {
                    'event': 'terminal_exec_completed',
                    'role': getattr(ctx, 'user_role', 'user'),
                    'command': command,
                    'cwd': str(workdir),
                    'exit_code': int(completed.returncode),
                    'executable': executable,
                    'sandbox_profile': getattr(getattr(ctx, 'sandbox_decision', None), 'profile_name', ''),
                },
            )
        except Exception:
            pass

        return json.dumps(
            {
                'command': command,
                'cwd': str(workdir),
                'exit_code': int(completed.returncode),
                'stdout': stdout,
                'stderr': stderr,
                'sandbox_profile': getattr(getattr(ctx, 'sandbox_decision', None), 'profile_name', ''),
            },
            ensure_ascii=False,
            indent=2,
        )
