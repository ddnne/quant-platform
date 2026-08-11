"""Trusted runtime helpers for reproducible paper experiments.

This package is intentionally outside :mod:`strategies`: it may inspect the
local SQLite control plane, while strategy code remains isolated from storage.
"""

from .snapshot import (
    DATA_SNAPSHOT_FORMAT,
    LOCAL_SNAPSHOT_MANIFEST_FORMAT,
    begin_snapshot_sync,
    commit_snapshot_manifest,
    data_snapshot_id,
    fail_snapshot_sync,
)
from .code_fingerprints import (
    feature_definition_hashes,
    git_commit,
    strategy_definition_hash,
)
from .experiment_index import ExperimentIndex

__all__ = [
    "DATA_SNAPSHOT_FORMAT",
    "LOCAL_SNAPSHOT_MANIFEST_FORMAT",
    "begin_snapshot_sync",
    "commit_snapshot_manifest",
    "data_snapshot_id",
    "fail_snapshot_sync",
    "ExperimentIndex",
    "feature_definition_hashes",
    "git_commit",
    "strategy_definition_hash",
]
