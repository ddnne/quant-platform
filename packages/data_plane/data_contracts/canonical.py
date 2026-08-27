"""Canonical dataset meta-index.

This registry owns stable dataset identity, membership, source, governance tier,
and routing links. It is deliberately *not* the source of truth for history
bounds, coverage grain/frequency, natural keys, availability, or research
eligibility:

* CollectionCoverageContract owns history bounds and coverage shape.
* SourceCapabilityContract owns official availability and eligibility where a
  V3 row exists.

The JSON retains legacy projection fields for inventory compatibility. Python
accessors derive those values from the owning contracts, and
``validate_derived_metadata`` rejects projection drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

CANONICAL_REGISTRY_PATH = Path(__file__).with_name("canonical_datasets.json")

_REQUIRED = frozenset({
    "dataset_id",
    "display_name",
    "source",
    "governance_tier",
    "contracts",
})

_DERIVED_FIELDS = frozenset(
    {
        "available_at",
        "collection_window",
        "coverage_segment_granularity",
        "expected_frequency",
        "historical_start",
        "natural_key_fields",
        "research_eligible",
    }
)


@dataclass(frozen=True)
class CanonicalDatasetContract:
    """Stable identity entry with values derived from owning contracts."""

    dataset_id: str
    display_name: str
    source: str
    governance_tier: str
    contracts: Mapping[str, str]

    @property
    def natural_key_fields(self) -> tuple[str, ...]:
        """Derive row identity from the primary PIT/ingestion contract."""
        if self.source == "jquants_premium_core":
            from .loader import contract_for

            return contract_for(self.dataset_id).natural_key_fields
        if self.source == "jsda_governed":
            from .jsda import jsda_contract_for

            return jsda_contract_for(self.dataset_id).natural_key_fields
        raise ValueError(
            f"{self.dataset_id} has no governed primary natural-key contract"
        )

    @property
    def historical_start(self) -> str:
        """Derive the coverage start from CollectionCoverageContract."""
        coverage = _coverage_contract_or_none(self.dataset_id)
        if coverage is not None:
            return coverage.history_target_start
        raise ValueError(
            f"{self.dataset_id} has no governed CollectionCoverageContract"
        )

    @property
    def coverage_segment_granularity(self) -> str:
        """Derive coverage grain from CollectionCoverageContract."""
        coverage = _coverage_contract_or_none(self.dataset_id)
        if coverage is not None:
            return coverage.segment_granularity
        raise ValueError(
            f"{self.dataset_id} has no governed CollectionCoverageContract"
        )

    @property
    def expected_frequency(self) -> str:
        """Derive expected frequency from CollectionCoverageContract."""
        coverage = _coverage_contract_or_none(self.dataset_id)
        if coverage is not None:
            return coverage.expected_frequency
        raise ValueError(
            f"{self.dataset_id} has no governed CollectionCoverageContract"
        )

    @property
    def research_eligible(self) -> bool:
        """Derive official eligibility from SourceCapability V3 when available."""
        from .source_capability import source_capability_contract_or_none

        capability = source_capability_contract_or_none(self.dataset_id)
        if capability is not None:
            return capability.historical_research_eligible
        return False

    @property
    def available_at(self):
        """Derive point-in-time availability semantics from SourceCapability."""
        from .source_capability import source_capability_contract_or_none

        capability = source_capability_contract_or_none(self.dataset_id)
        return capability.available_at if capability is not None else None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CanonicalDatasetContract":
        missing = _REQUIRED - raw.keys()
        if missing:
            raise ValueError(f"canonical dataset contract missing fields: {sorted(missing)}")

        dataset_id = _text(raw["dataset_id"], "dataset_id")
        display_name = _text(raw["display_name"], "display_name")
        source = _text(raw["source"], f"{dataset_id}.source")
        tier = _text(raw["governance_tier"], f"{dataset_id}.governance_tier")

        if tier not in {"governed", "experimental"}:
            raise ValueError(f"{dataset_id}.governance_tier must be 'governed' or 'experimental'")

        contracts_raw = raw["contracts"]
        if not isinstance(contracts_raw, dict) or not contracts_raw:
            raise ValueError(f"{dataset_id}.contracts must be a non-empty object")

        contracts = MappingProxyType({
            _text(k, f"{dataset_id}.contracts key"): _text(v, f"{dataset_id}.contracts.{k}")
            for k, v in contracts_raw.items()
        })

        if "primary" not in contracts:
            raise ValueError(f"{dataset_id}.contracts must include 'primary'")

        return cls(
            dataset_id=dataset_id,
            display_name=display_name,
            source=source,
            governance_tier=tier,
            contracts=contracts,
        )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _coverage_contract_or_none(dataset_id: str):
    from .coverage import coverage_contract_for

    try:
        return coverage_contract_for(dataset_id)
    except KeyError:
        return None


def _load() -> tuple[str, Mapping[str, CanonicalDatasetContract]]:
    """Load and validate the canonical dataset registry."""
    import json

    document = json.loads(CANONICAL_REGISTRY_PATH.read_text(encoding="utf-8"))

    if document.get("schema_version") != 1:
        raise ValueError("canonical dataset registry schema_version must be 1")

    registry_version = _text(document.get("registry_version"), "registry_version")

    raw_datasets = document.get("datasets")
    if not isinstance(raw_datasets, list) or not raw_datasets:
        raise ValueError("canonical registry datasets must be a non-empty array")

    contracts: dict[str, CanonicalDatasetContract] = {}
    dataset_ids: set[str] = set()

    for raw in raw_datasets:
        if not isinstance(raw, dict):
            raise ValueError("each canonical dataset contract must be an object")

        contract = CanonicalDatasetContract.from_dict(raw)

        if contract.dataset_id in dataset_ids:
            raise ValueError(f"duplicate dataset_id in canonical registry: {contract.dataset_id}")

        dataset_ids.add(contract.dataset_id)
        contracts[contract.dataset_id] = contract

    # Governed membership is fixed at 26 (JQ Premium 23 + JSDA 3). Experimental
    # add-ons may grow without changing that invariant.
    governed_count = sum(1 for c in contracts.values() if c.governance_tier == "governed")
    if governed_count != 26:
        raise ValueError(
            f"canonical registry must have exactly 26 governed datasets, found {governed_count}"
        )
    if len(contracts) < 26:
        raise ValueError("canonical registry must include at least the 26 governed datasets")

    return registry_version, MappingProxyType(contracts)


REGISTRY_VERSION, _DATASETS = _load()


def all_canonical_datasets() -> tuple[CanonicalDatasetContract, ...]:
    """Return all canonical dataset contracts."""
    return tuple(_DATASETS.values())


def canonical_dataset_for(dataset_id: str) -> CanonicalDatasetContract:
    """Get canonical contract for a specific dataset."""
    try:
        return _DATASETS[dataset_id]
    except KeyError as exc:
        known = sorted(_DATASETS.keys())
        raise KeyError(
            f"unknown dataset_id: {dataset_id!r}. "
            f"Known datasets: {', '.join(known)}"
        ) from exc


def governed_datasets() -> tuple[CanonicalDatasetContract, ...]:
    """Return all governed datasets (tier=governed)."""
    return tuple(
        c for c in _DATASETS.values()
        if c.governance_tier == "governed"
    )


def experimental_datasets() -> tuple[CanonicalDatasetContract, ...]:
    """Return all experimental datasets (tier=experimental)."""
    return tuple(
        c for c in _DATASETS.values()
        if c.governance_tier == "experimental"
    )


def datasets_by_source(source: str) -> tuple[CanonicalDatasetContract, ...]:
    """Return all datasets from a specific source (e.g., 'jquants_premium_core', 'jsda_governed')."""
    return tuple(
        c for c in _DATASETS.values()
        if c.source == source
    )


def validate_derived_metadata() -> None:
    """Reject derived authority fields if they reappear in the meta-index."""
    import json

    document = json.loads(CANONICAL_REGISTRY_PATH.read_text(encoding="utf-8"))
    violations: list[str] = []
    for row in document.get("datasets", []):
        if not isinstance(row, Mapping):
            continue
        dataset_id = str(row.get("dataset_id") or "<unknown>")
        for field_name in sorted(_DERIVED_FIELDS.intersection(row)):
            violations.append(f"{dataset_id}.{field_name}")
    if violations:
        raise ValueError(
            "canonical meta-index contains derived authority fields: "
            + ", ".join(violations)
        )


def validate_downstream_consistency() -> None:
    """Validate that all downstream registries are consistent with canonical registry.

    This checks that:
    - Coverage contracts are a subset of canonical registry
    - JSDA contracts are a subset of canonical registry
    - No dataset IDs conflict between systems

    Raises:
        ValueError: if any inconsistency is detected
    """
    from .coverage import all_coverage_contracts
    from .jsda import all_jsda_contracts

    canonical_ids = set(_DATASETS.keys())
    coverage_ids = {c.dataset_id for c in all_coverage_contracts()}
    jsda_ids = {c.dataset_id for c in all_jsda_contracts()}

    # Coverage should be subset of canonical
    coverage_extra = coverage_ids - canonical_ids
    if coverage_extra:
        raise ValueError(
            f"coverage contracts contain datasets not in canonical registry: {sorted(coverage_extra)}"
        )

    # JSDA should be subset of canonical
    jsda_extra = jsda_ids - canonical_ids
    if jsda_extra:
        raise ValueError(
            f"JSDA contracts contain datasets not in canonical registry: {sorted(jsda_extra)}"
        )

    # Canonical should contain all coverage and JSDA datasets
    canonical_missing = (coverage_ids | jsda_ids) - canonical_ids
    if canonical_missing:
        raise ValueError(
            f"canonical registry missing datasets from downstream contracts: {sorted(canonical_missing)}"
        )

    validate_derived_metadata()


# Fail closed at import time if duplicate authority metadata is reintroduced.
validate_derived_metadata()


__all__ = [
    "REGISTRY_VERSION",
    "CanonicalDatasetContract",
    "all_canonical_datasets",
    "canonical_dataset_for",
    "experimental_datasets",
    "governed_datasets",
    "datasets_by_source",
    "validate_derived_metadata",
    "validate_downstream_consistency",
]
