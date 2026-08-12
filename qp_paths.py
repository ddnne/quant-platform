"""Stable repo-root resolution for quant-platform.

Physical packages live under ``packages/*``; never assume a fixed
``Path(__file__).parents[N]`` depth from a library module.
"""

from __future__ import annotations

from pathlib import Path

_CACHED: Path | None = None


def repo_root() -> Path:
    """Return the quant-platform repository root (directory with pyproject.toml + tests/)."""
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "pyproject.toml").is_file() and (parent / "tests").is_dir():
            _CACHED = parent
            return parent
    # Fallback: walk from CWD (scripts/tests sometimes invoked oddly)
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / "pyproject.toml").is_file() and (parent / "tests").is_dir():
            _CACHED = parent
            return parent
    raise RuntimeError("quant-platform repo root not found (no pyproject.toml + tests/)")


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
