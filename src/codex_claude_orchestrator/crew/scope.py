"""Unified write-scope normalization and matching.

All write-scope checks in the codebase MUST use these functions.
Do NOT implement scope matching elsewhere.
"""

from __future__ import annotations

from fnmatch import fnmatch


def normalize_path(path: str) -> str:
    """Normalize a path for scope comparison.

    - Forward slashes only
    - Strip leading ./ and /
    - Strip whitespace
    """
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    while normalized.startswith("/"):
        normalized = normalized[1:]
    return normalized


def scope_covers(write_scope: list[str], target_path: str) -> bool:
    """Check if write_scope covers target_path.

    A scope covers a target if:
    - target == scope (exact match)
    - target is a subdirectory of scope (prefix match with /)

    Returns False if write_scope is empty.
    Returns True if target_path is empty (nothing to constrain).
    """
    target = normalize_path(target_path)
    if not target:
        return True
    for scope in write_scope:
        s = normalize_path(scope)
        if not s:
            continue
        # Directory prefix matching
        if not s.endswith("/"):
            s += "/"
        target_with_slash = target if target.endswith("/") else target + "/"
        if target_with_slash.startswith(s) or target == normalize_path(scope):
            return True
    return False


def scope_covers_all(write_scope: list[str], target_paths: list[str]) -> bool:
    """Check if write_scope covers ALL target paths."""
    return all(scope_covers(write_scope, p) for p in target_paths if p)


def is_protected(path: str, protected_patterns: list[str]) -> bool:
    """Check if a path matches any protected pattern."""
    normalized = normalize_path(path)
    for pattern in protected_patterns:
        p = normalize_path(pattern)
        if p.endswith("/"):
            if normalized.startswith(p):
                return True
        elif fnmatch(normalized, p):
            return True
    return False
