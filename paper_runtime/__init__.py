"""Trusted runtime helpers for reproducible paper experiments.

This package is intentionally outside :mod:`strategies`: it may inspect the
local SQLite control plane, while strategy code remains isolated from storage.
"""

from .snapshot import DATA_SNAPSHOT_FORMAT, data_snapshot_id
from .code_fingerprints import (
    feature_definition_hashes,
    git_commit,
    strategy_definition_hash,
)

__all__ = [
    "DATA_SNAPSHOT_FORMAT",
    "data_snapshot_id",
    "feature_definition_hashes",
    "git_commit",
    "strategy_definition_hash",
]
