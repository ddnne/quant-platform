"""Stable repo-root resolution for quant-platform.

Physical packages live under ``packages/*``; never assume a fixed
``Path(__file__).parents[N]`` depth from a library module.
"""

from __future__ import annotations

import os
from pathlib import Path

_CACHED: Path | None = None
_REPO_ROOT_ENV = "QP_REPO_ROOT"


def repo_root() -> Path:
    """Return the quant-platform repository root.

    ``QP_REPO_ROOT``, when set, is fail-closed: the resolved path must contain
    ``pyproject.toml`` and runtime layout (``packages/``). ``tests/`` is not
    required. An invalid explicit value is never ignored.

    When the environment variable is unset, walk from this file and then CWD
    for a checkout that has ``pyproject.toml`` and ``tests/``.
    """
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    if _REPO_ROOT_ENV in os.environ:
        _CACHED = _explicit_repo_root(os.environ[_REPO_ROOT_ENV])
        return _CACHED
    discovered = _discover_checkout_root()
    if discovered is None:
        raise RuntimeError(
            "quant-platform repo root not found (no pyproject.toml + tests/)"
        )
    _CACHED = discovered
    return _CACHED


def _explicit_repo_root(raw: str) -> Path:
    stripped = raw.strip()
    if not stripped:
        raise RuntimeError(f"{_REPO_ROOT_ENV} is set but empty")
    root = Path(stripped).expanduser().resolve()
    missing = _runtime_root_errors(root)
    if missing:
        raise RuntimeError(
            f"{_REPO_ROOT_ENV} is not a quant-platform runtime root ({root}): "
            + "; ".join(missing)
        )
    return root


def _runtime_root_errors(root: Path) -> list[str]:
    errors: list[str] = []
    if not root.is_dir():
        errors.append("path is not a directory")
        return errors
    if not (root / "pyproject.toml").is_file():
        errors.append("missing pyproject.toml")
    if not (root / "packages").is_dir():
        errors.append("missing packages/")
    return errors


def _discover_checkout_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if _is_checkout_root(parent):
            return parent
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if _is_checkout_root(parent):
            return parent
    return None


def _is_checkout_root(parent: Path) -> bool:
    return (parent / "pyproject.toml").is_file() and (parent / "tests").is_dir()


def package_dir(import_name: str) -> Path:
    """Resolve on-disk directory for a top-level import name via importlib."""
    import importlib.util

    spec = importlib.util.find_spec(import_name)
    if spec is None or not spec.origin:
        raise ModuleNotFoundError(import_name)
    origin = Path(spec.origin)
    # package: .../pkg/__init__.py  → parent; module: .../mod.py → parent (dir holding mod)
    if origin.name == "__init__.py":
        return origin.parent
    return origin.parent
