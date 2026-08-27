"""Behavioral tests for one-observation Ops Projection contract inputs."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest

from data_contracts.coverage import coverage_contract_for, coverage_policy_binding
from ops import projection_contract_snapshot as snapshot_module
from ops.projection_contract_snapshot import ProjectionContractSnapshot


ROOT = Path(__file__).resolve().parents[1]


def _inventory_row(
    snapshot: ProjectionContractSnapshot, dataset_id: str
) -> dict[str, object]:
    return dict(
        next(
            row
            for row in snapshot.source_inventory
            if row["dataset_id"] == dataset_id
        )
    )


def test_contract_snapshot_reads_each_retained_file_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = snapshot_module._read_retained_contract_file
    calls: Counter[str] = Counter()

    def observed(path: Path) -> bytes:
        relative = path.relative_to(ROOT).as_posix()
        calls[relative] += 1
        return original(path)

    monkeypatch.setattr(snapshot_module, "_read_retained_contract_file", observed)
    snapshot = ProjectionContractSnapshot.capture(ROOT)

    assert calls == Counter({path: 1 for path in snapshot.retained_files})
    before = calls.copy()
    assert snapshot.coverage_dataset_ids
    assert snapshot.source_inventory
    assert snapshot.coverage_policy_binding("equities_bars_daily")
    assert snapshot.coverage_policy_set_binding(
        list(snapshot.coverage_dataset_ids)
    )
    assert calls == before


def test_retained_bytes_drive_digest_policy_and_inventory_not_import_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different retained observation must not mix with package caches."""

    original = snapshot_module._read_retained_contract_file
    marker = "retained-observation-only"
    altered_start = "2013-01-02"

    # Force the ordinary package caches to contain the checked-in observation.
    baseline = ProjectionContractSnapshot.capture(ROOT)
    cached_policy = dict(coverage_policy_binding("equities_investor_types"))
    cached_start = coverage_contract_for(
        "equities_investor_types"
    ).history_target_start

    def observed(path: Path) -> bytes:
        raw = original(path)
        if path.name == "canonical_datasets.json":
            document = json.loads(raw)
            row = next(
                item
                for item in document["datasets"]
                if item["dataset_id"] == "equities_investor_types"
            )
            row["display_name"] = marker
            return json.dumps(document, ensure_ascii=False).encode("utf-8")
        if path.name == "collection_coverage.json":
            document = json.loads(raw)
            document["datasets"]["equities_investor_types"][
                "history_target_start"
            ] = altered_start
            return json.dumps(document, ensure_ascii=False).encode("utf-8")
        return raw

    monkeypatch.setattr(snapshot_module, "_read_retained_contract_file", observed)
    snapshot = ProjectionContractSnapshot.capture(ROOT)
    retained_policy = dict(
        snapshot.coverage_policy_binding("equities_investor_types")
    )

    assert cached_start != altered_start
    assert cached_policy != retained_policy
    inventory = _inventory_row(snapshot, "equities_investor_types")
    assert inventory["display_name"] == marker
    assert inventory["historical_start"] == altered_start
    assert snapshot.contract_digest != baseline.contract_digest
    assert snapshot.registry_digest != baseline.registry_digest

    # Re-reading the package cache still returns the original observation.
    assert coverage_contract_for("equities_investor_types").history_target_start == (
        cached_start
    )
    assert dict(coverage_policy_binding("equities_investor_types")) == cached_policy
