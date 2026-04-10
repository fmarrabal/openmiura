from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re

SDK_CONTRACT_VERSION = "1.0"
SUPPORTED_MANIFEST_VERSIONS = {"1", "1.0"}


@dataclass(slots=True)
class CompatibilityReport:
    compatible: bool
    runtime_version: str
    runtime_contract_version: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "runtime_version": self.runtime_version,
            "runtime_contract_version": self.runtime_contract_version,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "details": dict(self.details),
        }


def _semver_parts(version: str | None) -> tuple[int, int, int]:
    text = str(version or "0.0.0").strip()
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", text)
    if not match:
        return (0, 0, 0)
    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    return (major, minor, patch)


def semver_key(version: str | None) -> tuple[int, int, int]:
    return _semver_parts(version)


def compare_versions(left: str | None, right: str | None) -> int:
    left_key = semver_key(left)
    right_key = semver_key(right)
    if left_key < right_key:
        return -1
    if left_key > right_key:
        return 1
    return 0


def detect_version_bump(previous: str | None, current: str | None) -> str:
    if previous is None:
        return "initial"
    prev_key = semver_key(previous)
    curr_key = semver_key(current)
    if curr_key < prev_key:
        return "downgrade"
    if curr_key == prev_key:
        return "same"
    if curr_key[0] > prev_key[0]:
        return "major"
    if curr_key[1] > prev_key[1]:
        return "minor"
    return "patch"


def is_contract_compatible(extension_contract: str | None, runtime_contract: str | None = None) -> bool:
    ext = semver_key(extension_contract or SDK_CONTRACT_VERSION)
    run = semver_key(runtime_contract or SDK_CONTRACT_VERSION)
    return ext[0] == run[0] and ext <= run


def evaluate_extension_compatibility(
    *,
    extension_contract: str | None,
    runtime_contract: str | None = None,
    runtime_version: str = "1.0.0",
    compatibility: dict[str, Any] | None = None,
) -> CompatibilityReport:
    runtime_contract_version = str(runtime_contract or SDK_CONTRACT_VERSION)
    compat = dict(compatibility or {})
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {
        "extension_contract_version": str(extension_contract or SDK_CONTRACT_VERSION),
        "minimum_openmiura_version": compat.get("min_openmiura_version"),
        "maximum_openmiura_version": compat.get("max_openmiura_version"),
        "tested_contract_versions": list(compat.get("tested_contract_versions") or []),
        "backward_compatible_from": compat.get("backward_compatible_from"),
    }

    if not is_contract_compatible(extension_contract, runtime_contract_version):
        errors.append(
            f"extension_contract_incompatible: extension={extension_contract or SDK_CONTRACT_VERSION}, runtime={runtime_contract_version}"
        )

    min_version = compat.get("min_openmiura_version")
    max_version = compat.get("max_openmiura_version")
    if min_version and compare_versions(runtime_version, str(min_version)) < 0:
        errors.append(f"openmiura_too_old: runtime={runtime_version}, required>={min_version}")
    if max_version and compare_versions(runtime_version, str(max_version)) > 0:
        errors.append(f"openmiura_too_new: runtime={runtime_version}, allowed<={max_version}")

    tested_contract_versions = [str(value) for value in (compat.get("tested_contract_versions") or []) if str(value).strip()]
    if tested_contract_versions and runtime_contract_version not in tested_contract_versions:
        warnings.append(
            f"runtime_contract_not_in_tested_matrix: runtime={runtime_contract_version}, tested={tested_contract_versions}"
        )

    return CompatibilityReport(
        compatible=not errors,
        runtime_version=runtime_version,
        runtime_contract_version=runtime_contract_version,
        errors=errors,
        warnings=warnings,
        details=details,
    )
