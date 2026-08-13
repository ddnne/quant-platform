"""Shared bootstrap for scripts/ CLIs (Track B1-e).

Finds the quant-platform repo root (``qp_paths.py`` + ``pyproject.toml``) and
inserts it on ``sys.path`` so leaf packages work without an editable install.

Usage from any script under ``scripts/`` or ``scripts/ops/``::

    import sys
    from pathlib import Path

    _here = Path(__file__).resolve().parent
    for _d in (_here, _here.parent):
        if (_d / "_bootstrap.py").is_file():
            if str(_d) not in sys.path:
                sys.path.insert(0, str(_d))
            break
    else:
        raise RuntimeError("scripts/_bootstrap.py not found")
    from _bootstrap import ensure_repo_root

    ROOT = ensure_repo_root()

Do **not** launch Mass / READY / Phase7 / ``cf_premium_backfill`` from this module.
"""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_root() -> Path:
    """Return repo root and ensure it is first on ``sys.path``."""
    # Prefer qp_paths once root is importable; otherwise walk from CWD/script tree.
    for start in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        for parent in [start, *start.parents]:
            if (parent / "qp_paths.py").is_file() and (
                parent / "pyproject.toml"
            ).is_file():
                root_s = str(parent)
                if root_s not in sys.path:
                    sys.path.insert(0, root_s)
                return parent
    raise RuntimeError(
        "quant-platform repo root not found (need qp_paths.py + pyproject.toml)"
    )
