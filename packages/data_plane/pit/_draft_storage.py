"""Private sqlite bind for paper_runtime DRAFT adapters.

Not a product API. Product/research must not import this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .personal_research_view import PersonalResearchDataView, PersonalResearchViewError


def draft_sqlite_path(view: Any) -> Path:
    if not isinstance(view, PersonalResearchDataView):
        raise PersonalResearchViewError("draft sqlite bind requires a research data view")
    source = getattr(view, "_source", None)
    if not isinstance(source, Path):
        raise PersonalResearchViewError("draft view has no sqlite backend")
    return source


def draft_artifact_root(view: Any) -> Path:
    if not isinstance(view, PersonalResearchDataView):
        raise PersonalResearchViewError("draft artifact bind requires a research data view")
    root = getattr(view, "_artifacts", None)
    if not isinstance(root, Path):
        raise PersonalResearchViewError("draft view has no artifact sink")
    return root


def activate_prepared_sqlite(view: Any, source: Path) -> None:
    if not isinstance(view, PersonalResearchDataView):
        raise PersonalResearchViewError("prepared sqlite bind requires a research data view")
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise PersonalResearchViewError(f"prepared snapshot is missing: {path}")
    object.__setattr__(view, "_source", path)


__all__ = [
    "activate_prepared_sqlite",
    "draft_artifact_root",
    "draft_sqlite_path",
]
