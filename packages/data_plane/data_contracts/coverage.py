"""Collection coverage policy paired with the canonical dataset contract.

The policy deliberately distinguishes calendar/periodic series from irregular
event feeds.  Event feeds are reconciled against the source collection window;
they never acquire invented daily row-count expectations.

Event-driven + default ``calendar_month`` still *plans* one required segment
per month (see ``storage.coverage_ledger.plan_required_segments``).
``evaluate_segment`` will COMPLETE an event window with a trusted receipt
even when ``observed_items==0``; it will PARTIAL a month with *no* receipt
(``missing collection receipt``). That is why ``equities_earnings_calendar``
shows 1/200 COMPLETE while the vendor API is next-business-day / recent-only
(https://jpx-jquants.com/en/spec/eq-earnings-cal). Do not fabricate monthly
COMPLETE shells. A later contract grain (snapshot / source_event_window)
needs a product ADR — not a ``history_target_start`` bump to invent COMPLETE.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .loader import all_contracts
from .jsda import jsda_contract_for

COVERAGE_CONTRACT_PATH = Path(__file__).with_name("collection_coverage.json")
COVERAGE_STATUSES = frozenset(
    {"COMPLETE", "PARTIAL", "STALE", "UNKNOWN", "FAILED"}
)
GOVERNANCE_TIERS = frozenset({"governed", "experimental"})
SEGMENT_GRANULARITIES = frozenset({
    "calendar_month", "official_archive_day", "official_archive_year", "source_time_series_file"
})
_REQUIRED = frozenset(
    {
        "collection_scope",
        "history_target_start",
        "history_target_end_rule",
        "coverage_mode",
        "expected_frequency",
        "universe_rule",
        "raw_retention_required",
        "structured_reconciliation_required",
        "segment_granularity",
        "governance_tier",
    }
)


@dataclass(frozen=True)
class CollectionCoverageContract:
    dataset_id: str
    collection_scope: str
    history_target_start: str
    history_target_end_rule: str
    coverage_mode: str
    expected_frequency: str
    universe_rule: str
    raw_retention_required: bool
    structured_reconciliation_required: bool
    segment_granularity: str
    governance_tier: str

    @classmethod
    def from_dict(
        cls, dataset_id: str, raw: Mapping[str, Any]
    ) -> "CollectionCoverageContract":
        missing = _REQUIRED - raw.keys()
        if missing:
            raise ValueError(
                f"coverage contract {dataset_id!r} missing {sorted(missing)}"
            )
        strings = {
            name: raw[name]
            for name in _REQUIRED
            if name not in {
                "raw_retention_required", "structured_reconciliation_required"
            }
        }
        for name, value in strings.items():
            if not isinstance(value, str) or not value:
                raise ValueError(f"{dataset_id}.{name} must be non-empty string")
        # Annotation-only keys (vendor_data_provision_start, vendor_history_policy,
        # citations) are ignored here; they must not move history_target_start.
        tier = str(raw["governance_tier"])
        if tier not in GOVERNANCE_TIERS:
            raise ValueError(
                f"{dataset_id}.governance_tier must be governed or experimental"
            )
        granularity = str(raw["segment_granularity"])
        if granularity not in SEGMENT_GRANULARITIES:
            raise ValueError(
                f"{dataset_id}.segment_granularity is not supported"
            )
        for name in ("raw_retention_required", "structured_reconciliation_required"):
            if not isinstance(raw[name], bool):
                raise ValueError(f"{dataset_id}.{name} must be boolean")
        return cls(dataset_id=dataset_id, **{name: raw[name] for name in _REQUIRED})


def _load() -> tuple[str, Mapping[str, CollectionCoverageContract]]:
    document = json.loads(COVERAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    if document.get("schema_version") != 2:
        raise ValueError("collection coverage schema_version must be 2")
    policy_version = document.get("policy_version")
    if not isinstance(policy_version, str) or not policy_version:
        raise ValueError("collection coverage policy_version must be non-empty")
    defaults = document.get("defaults")
    rows = document.get("datasets")
    if not isinstance(defaults, dict) or not isinstance(rows, dict):
        raise ValueError("coverage defaults and datasets must be objects")
    # JSDA datasets enter the exact READY coverage catalog only after their
    # governed ingestion lane exists. All three governed JSDA datasets are now
    # included in the unified coverage catalog.
    governed_jsda = (
        jsda_contract_for("jsda_otc_bond_reference_prices"),
        jsda_contract_for("jsda_tokyo_repo_rates"),
        jsda_contract_for("jsda_corporate_bond_transactions"),
    )
    expected = {
        *(contract.dataset_id for contract in all_contracts()),
        *(contract.dataset_id for contract in governed_jsda),
    }
    actual = set(rows)
    if actual != expected:
        raise ValueError(
            "coverage datasets must exactly match canonical contract: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    contracts = {
        dataset_id: CollectionCoverageContract.from_dict(
            dataset_id, {**defaults, **overrides}
        )
        for dataset_id, overrides in rows.items()
    }
    return policy_version, MappingProxyType(contracts)


POLICY_VERSION, _CONTRACTS = _load()


def all_coverage_contracts() -> tuple[CollectionCoverageContract, ...]:
    return tuple(_CONTRACTS.values())


def coverage_contract_for(dataset_id: str) -> CollectionCoverageContract:
    try:
        return _CONTRACTS[dataset_id]
    except KeyError as exc:
        raise KeyError(f"unknown coverage contract: {dataset_id!r}") from exc


__all__ = [
    "COVERAGE_CONTRACT_PATH",
    "COVERAGE_STATUSES",
    "GOVERNANCE_TIERS",
    "SEGMENT_GRANULARITIES",
    "POLICY_VERSION",
    "CollectionCoverageContract",
    "all_coverage_contracts",
    "coverage_contract_for",
]
