"""Storage layer — SQLite schema + writer for structured ingestion rows.

Every structured row carries the PIT columns:
``event_time`` / ``available_at`` / ``source`` / ``ingested_at``.
``available_at`` is mandatory (enforced in :mod:`storage.sqlite_store`).
"""

from .coverage_ledger import (
    coverage_gaps,
    coverage_summary,
    read_dataset_coverage,
    refresh_coverage_ledger,
)

__all__ = [
    "__version__",
    "coverage_gaps",
    "coverage_summary",
    "read_dataset_coverage",
    "refresh_coverage_ledger",
]
__version__ = "0.1.0"
