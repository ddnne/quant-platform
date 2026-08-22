"""Trusted runtime helpers for reproducible paper experiments.

This package is intentionally outside :mod:`strategies`: it may inspect the
local SQLite control plane, while strategy code remains isolated from storage.
"""

from .snapshot import (
    DATA_SNAPSHOT_FORMAT,
    LOCAL_SNAPSHOT_MANIFEST_FORMAT,
    QUALITY_POLICY_VERSION,
    RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
    SNAPSHOT_STATES,
    ReadySnapshot,
    SnapshotRejected,
    begin_snapshot_sync,
    commit_snapshot_manifest,
    data_snapshot_id,
    describe_snapshot,
    fail_snapshot_sync,
    latest_ready_snapshot,
    list_ready_snapshots,
    open_ready_snapshot,
    publish_ready_snapshot,
)
from .code_fingerprints import (
    feature_definition_hashes,
    git_commit,
    strategy_definition_hash,
)
from .experiment_index import ExperimentIndex
from .coherence import (
    CoherenceGateResult,
    check_ready_coherence,
)

__all__ = [
    "DATA_SNAPSHOT_FORMAT",
    "LOCAL_SNAPSHOT_MANIFEST_FORMAT",
    "QUALITY_POLICY_VERSION",
    "RESEARCH_SNAPSHOT_MANIFEST_FORMAT",
    "SNAPSHOT_STATES",
    "ReadySnapshot",
    "SnapshotRejected",
    "begin_snapshot_sync",
    "commit_snapshot_manifest",
    "data_snapshot_id",
    "describe_snapshot",
    "fail_snapshot_sync",
    "latest_ready_snapshot",
    "list_ready_snapshots",
    "open_ready_snapshot",
    "publish_ready_snapshot",
    "ExperimentIndex",
    "feature_definition_hashes",
    "git_commit",
    "strategy_definition_hash",
    "CoherenceGateResult",
    "check_ready_coherence",
]
