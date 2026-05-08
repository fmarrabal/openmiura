"""Internal helper for the Phase 1 audit.py refactor.

Extracts a list of methods from openmiura.core.audit.AuditStore into a
new repository class under openmiura/persistence/. Replaces the
extracted methods in audit.py with one-line delegators that call into
the new repository instance.

Use:
    py -3.9 scripts/_extract_repo.py \\
        --domain voice \\
        --class-name VoiceRepo \\
        --attr _voice \\
        --methods <one-method-name-per-line-file>

The script is deterministic: re-running on a clean tree should produce
identical output.

This file is removed at the end of the Phase 1 PR.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "openmiura" / "core" / "audit.py"
PERSISTENCE_DIR = ROOT / "openmiura" / "persistence"

REPO_HEADER_TEMPLATE = '''"""{domain_title}Repo: persistence for the {domain} domain of openMiura.

Owns the persistence logic for the {domain}-related tables. The class
is instantiated by ``AuditStore`` so existing public callers remain
unaffected; ``AuditStore`` keeps thin one-line delegators on its API.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from openmiura.core.db import DBConnection, CompatRow
from openmiura.core.tenancy.scope import assert_scope_match, normalize_scope
from openmiura.persistence.base import (
    infer_scope_from_session,
    row_scope,
    scope_payload,
    scope_where,
)


class {class_name}:
    def __init__(self, conn: DBConnection) -> None:
        self._conn = conn

    @staticmethod
    def _scope_payload(*, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return scope_payload(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    @staticmethod
    def _row_scope(row: Any) -> dict[str, Any]:
        return row_scope(row)

    def _scope_where(self, clauses: list[str], params: list[Any], *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, prefix: str = "") -> tuple[list[str], list[Any]]:
        return scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, prefix=prefix)

    def _infer_scope_from_session(self, session_id: str) -> dict[str, Any]:
        return infer_scope_from_session(self._conn, session_id)

'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, help="lowercase short domain name, e.g. voice")
    parser.add_argument("--class-name", required=True, help="repository class name, e.g. VoiceRepo")
    parser.add_argument("--attr", required=True, help="instance attribute on AuditStore, e.g. _voice")
    parser.add_argument("--methods", required=True, help="path to a file with one method name per line")
    return parser.parse_args()


def load_method_names(path: Path) -> list[str]:
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            names.append(s)
    return names


def find_audit_class(tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "AuditStore":
            return node
    raise SystemExit("AuditStore class not found in audit.py")


def method_range(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[int, int]:
    """Return (start, end) line numbers for the method including decorators (1-indexed)."""
    start = (
        min(d.lineno for d in node.decorator_list)
        if node.decorator_list
        else node.lineno
    )
    end = node.end_lineno  # type: ignore[attr-defined]
    assert end is not None
    return start, end


def call_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build a call argument list that mirrors the signature, skipping self.

    Positional/positional-or-keyword args are passed by name=name to be
    safe with keyword-only signatures, since most AuditStore methods use
    a leading ``*`` to force kw-only parameters.
    """
    args = node.args

    # Positional-only
    parts: list[str] = []
    for a in args.posonlyargs:
        if a.arg == "self":
            continue
        parts.append(a.arg)

    # Regular positional-or-keyword
    for a in args.args:
        if a.arg == "self":
            continue
        # Pass by name for keyword-or-positional safety only when there is
        # no positional-only group (uncommon here).
        parts.append(a.arg)

    if args.vararg:
        parts.append("*" + args.vararg.arg)

    for a in args.kwonlyargs:
        parts.append(f"{a.arg}={a.arg}")

    if args.kwarg:
        parts.append("**" + args.kwarg.arg)

    return ", ".join(parts)


def signature_lines(node: ast.FunctionDef | ast.AsyncFunctionDef, src_lines: list[str]) -> tuple[int, str]:
    """Return (signature_line_count, signature_text). Signature ends at the line that closes with ':'."""
    start_idx = (
        min(d.lineno for d in node.decorator_list) - 1
        if node.decorator_list
        else node.lineno - 1
    )
    # Find ':' at depth 0 — signatures can span multiple lines.
    line_idx = node.lineno - 1
    depth = 0
    in_str = False
    str_ch = ""
    end_idx = line_idx
    for i in range(line_idx, len(src_lines)):
        s = src_lines[i]
        for ch in s:
            if in_str:
                if ch == str_ch:
                    in_str = False
            elif ch in "\"'":
                in_str = True
                str_ch = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == ":" and depth == 0:
                end_idx = i
                return end_idx + 1 - start_idx, "".join(src_lines[start_idx:end_idx + 1])
        # If we are mid-signature, continue to next line
    raise SystemExit(f"Could not find end of signature for {node.name}")


def main() -> int:
    args = parse_args()
    methods_file = Path(args.methods)
    if not methods_file.is_absolute():
        methods_file = ROOT / methods_file
    method_names = load_method_names(methods_file)

    src = AUDIT_PATH.read_text(encoding="utf-8")
    src_lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    audit_cls = find_audit_class(tree)

    target_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in audit_cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in method_names:
                target_nodes.append(node)

    found_names = {n.name for n in target_nodes}
    missing = [m for m in method_names if m not in found_names]
    if missing:
        print(f"WARNING: methods not found in AuditStore: {missing}", file=sys.stderr)

    target_nodes.sort(key=lambda n: n.lineno)

    # Build repo file
    repo_header = REPO_HEADER_TEMPLATE.format(
        domain=args.domain,
        domain_title=args.domain[:1].upper() + args.domain[1:],
        class_name=args.class_name,
    )

    repo_method_blocks: list[str] = []
    for node in target_nodes:
        start, end = method_range(node)
        block = "".join(src_lines[start - 1:end])
        repo_method_blocks.append(block)

    repo_body = "\n".join(repo_method_blocks)
    repo_text = repo_header + repo_body
    if not repo_text.endswith("\n"):
        repo_text += "\n"

    repo_path = PERSISTENCE_DIR / f"{args.domain}_repo.py"
    repo_path.write_text(repo_text, encoding="utf-8")

    # Build replacement: each method in audit.py becomes a thin delegator
    replacements: list[tuple[int, int, str]] = []
    for node in target_nodes:
        start, end = method_range(node)
        sig_line_count, sig_text = signature_lines(node, src_lines)
        # Determine indent (the signature already includes leading whitespace)
        # Strip the trailing newline from sig_text for clean appending
        indent = "    "  # all AuditStore methods are at one level of indent
        body_indent = indent + "    "
        call = call_args(node)
        delegator_body = f"{body_indent}return self.{args.attr}.{node.name}({call})\n"
        # Compose replacement: signature lines as-is + 1-line body
        replacement_text = sig_text
        if not replacement_text.endswith("\n"):
            replacement_text += "\n"
        replacement_text += delegator_body
        replacements.append((start, end, replacement_text))

    new_lines = list(src_lines)
    for start, end, repl in sorted(replacements, key=lambda r: -r[0]):
        new_lines[start - 1:end] = [repl]

    # Insert import for the new repo class right after the existing
    # persistence.base imports.
    import_marker = "from openmiura.persistence.base import scope_where as _scope_where_fn"
    insert_idx = None
    for i, ln in enumerate(new_lines):
        if import_marker in ln:
            insert_idx = i + 1
            break
    if insert_idx is None:
        raise SystemExit("import marker not found in audit.py")
    repo_module = f"openmiura.persistence.{args.domain}_repo"
    new_import_line = f"from {repo_module} import {args.class_name}\n"
    if new_import_line not in new_lines:
        # Insert in alphabetical order among the persistence repo imports.
        # Find the run of persistence repo imports (lines that match
        # `from openmiura.persistence.<x>_repo import ...`).
        scan_start = insert_idx
        run_end = scan_start
        while run_end < len(new_lines) and new_lines[run_end].startswith("from openmiura.persistence.") and "_repo import" in new_lines[run_end]:
            run_end += 1
        block = new_lines[scan_start:run_end]
        block.append(new_import_line)
        block.sort()
        new_lines[scan_start:run_end] = block

    # Insert `self._<attr> = ClassName(self._conn)` in __init__ right after
    # the line that creates self._conn. Insert in alphabetical order among
    # similar attribute lines for stability.
    repo_attr_line = f"        self.{args.attr} = {args.class_name}(self._conn)\n"
    if repo_attr_line not in new_lines:
        for i, ln in enumerate(new_lines):
            if "self._conn = DBConnection(" in ln:
                # Walk forward over any existing self._<attr> = XxxRepo(self._conn) lines.
                j = i + 1
                while j < len(new_lines) and new_lines[j].lstrip().startswith("self.") and "Repo(self._conn)" in new_lines[j]:
                    j += 1
                run = new_lines[i + 1:j]
                run.append(repo_attr_line)
                run.sort()
                new_lines[i + 1:j] = run
                break

    AUDIT_PATH.write_text("".join(new_lines), encoding="utf-8")

    extracted = len(target_nodes)
    print(f"OK: extracted {extracted} methods into {repo_path.relative_to(ROOT)} as {args.class_name}")
    if missing:
        print(f"NOTE: {len(missing)} method(s) not found and skipped:")
        for m in missing:
            print(f"  - {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
