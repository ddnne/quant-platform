"""Trusted runtime helpers for reproducible paper experiments.

This package is intentionally outside :mod:`strategies`: it may inspect the
local SQLite control plane, while strategy code remains isolated from storage.
"""

from __future__ import annotations

from importlib import import_module


_EXPORT_MODULES = {
    "DATA_SNAPSHOT_FORMAT": ".snapshot_identity",
    "data_snapshot_id": ".snapshot_identity",
    "RESEARCH_SNAPSHOT_MANIFEST_FORMAT": ".snapshot_identity",
    "LOCAL_SNAPSHOT_MANIFEST_FORMAT": ".snapshot",
    "QUALITY_POLICY_VERSION": ".snapshot",
    "READY_MANIFEST_SCHEMA": ".snapshot",
    "SNAPSHOT_STATES": ".snapshot",
    "ReadySnapshot": ".snapshot",
    "SnapshotRejected": ".snapshot",
    "begin_snapshot_sync": ".snapshot",
    "describe_snapshot": ".snapshot",
    "fail_snapshot_sync": ".snapshot",
    "latest_ready_snapshot": ".snapshot",
    "list_ready_snapshots": ".snapshot",
    "feature_definition_hashes": ".code_fingerprints",
    "git_commit": ".code_fingerprints",
    "strategy_definition_hash": ".code_fingerprints",
    "ExperimentIndex": ".experiment_index",
    "CoherenceGateResult": ".coherence",
    "check_ready_coherence": ".coherence",
}


def __getattr__(name: str):
    """Resolve the legacy public surface without eager READY imports."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

__all__ = [
    "DATA_SNAPSHOT_FORMAT",
    "LOCAL_SNAPSHOT_MANIFEST_FORMAT",
    "QUALITY_POLICY_VERSION",
    "READY_MANIFEST_SCHEMA",
    "RESEARCH_SNAPSHOT_MANIFEST_FORMAT",
    "SNAPSHOT_STATES",
    "ReadySnapshot",
    "SnapshotRejected",
    "begin_snapshot_sync",
    "data_snapshot_id",
    "describe_snapshot",
    "fail_snapshot_sync",
    "latest_ready_snapshot",
    "list_ready_snapshots",
    "ExperimentIndex",
    "feature_definition_hashes",
    "git_commit",
    "strategy_definition_hash",
    "CoherenceGateResult",
    "check_ready_coherence",
]
