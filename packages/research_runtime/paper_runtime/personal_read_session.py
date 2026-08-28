"""Internal bridge for one personal DRAFT paper read session.

The product execution package intentionally cannot import :mod:`pit`
directly.  This tiny research-runtime bridge exposes only a context boundary,
not the underlying SQLite connection or a new data-access authority.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pit.query import _readonly_connection_scope


@contextmanager
def _personal_paper_read_session(db_path: str | Path) -> Iterator[None]:
    """Reuse PIT's read-only connection only for the enclosed paper run."""

    with _readonly_connection_scope(db_path):
        yield


__all__: list[str] = []
