"""Canonical dataset meta-index.

This registry owns stable dataset identity, membership, source, governance tier,
contract links, and natural keys. It is deliberately *not* the source of truth
for history bounds, coverage grain/frequency, or research eligibility:

* CollectionCoverageContract owns history bounds and coverage shape.
* SourceCapabilityContract owns official availability and eligibility where a
  V3 row exists.

The JSON retains legacy projection fields for inventory compatibility. Python
accessors derive those values from the owning contracts, and
``validate_derived_metadata`` rejects projection drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
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
    "natural_key_fields",
})


@dataclass(frozen=True)
class CanonicalDatasetContract:
    """Stable identity entry with derived compatibility projections."""

    dataset_id: str
    display_name: str
    source: str
    governance_tier: str
    contracts: Mapping[str, str]
    natural_key_fields: tuple[str, ...]
    _declared_historical_start: str | None = field(repr=False)
    _declared_coverage_segment_granularity: str | None = field(repr=False)
    _declared_expected_frequency: str | None = field(repr=False)
    _declared_research_eligible: bool | None = field(repr=False)

    @property
    def historical_start(self) -> str:
        """Derive the coverage start; fall back only for non-coverage metadata."""
        coverage = _coverage_contract_or_none(self.dataset_id)
        if coverage is not None:
            return coverage.history_target_start
        if self._declared_historical_start is None:
            raise ValueError(
                f"{self.dataset_id} has neither CollectionCoverageContract nor "
                "legacy historical_start projection"
            )
        return self._declared_historical_start

    @property
    def coverage_segment_granularity(self) -> str:
        """Derive coverage grain from CollectionCoverageContract."""
        coverage = _coverage_contract_or_none(self.dataset_id)
        if coverage is not None:
            return coverage.segment_granularity
        if self._declared_coverage_segment_granularity is None:
            raise ValueError(
                f"{self.dataset_id} has neither CollectionCoverageContract nor "
                "legacy coverage_segment_granularity projection"
            )
        return self._declared_coverage_segment_granularity

    @property
    def expected_frequency(self) -> str:
        """Derive expected frequency from CollectionCoverageContract."""
        coverage = _coverage_contract_or_none(self.dataset_id)
        if coverage is not None:
            return coverage.expected_frequency
        if self._declared_expected_frequency is None:
            raise ValueError(
                f"{self.dataset_id} has neither CollectionCoverageContract nor "
                "legacy expected_frequency projection"
            )
        return self._declared_expected_frequency

    @property
    def research_eligible(self) -> bool:
        """Derive official eligibility from SourceCapability V3 when available."""
        from .source_capability import source_capability_contract_or_none

        capability = source_capability_contract_or_none(self.dataset_id)
        if capability is not None:
            return capability.historical_research_eligible
        if self._declared_research_eligible is None:
            return False
        return self._declared_research_eligible

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

        natural_key_fields = _strings(raw["natural_key_fields"], f"{dataset_id}.natural_key_fields")
        historical_start = _optional_text(
            raw, "historical_start", f"{dataset_id}.historical_start"
        )
        if historical_start is not None:
            try:
                date.fromisoformat(historical_start)
            except ValueError as exc:
                raise ValueError(
                    f"{dataset_id}.historical_start must be ISO date format"
                ) from exc

        segment_granularity = _optional_text(
            raw,
            "coverage_segment_granularity",
            f"{dataset_id}.coverage_segment_granularity",
        )
        expected_frequency = _optional_text(
            raw, "expected_frequency", f"{dataset_id}.expected_frequency"
        )
        declared_research_eligible = raw.get("research_eligible")
        if declared_research_eligible is not None and not isinstance(
            declared_research_eligible, bool
        ):
            raise ValueError(f"{dataset_id}.research_eligible must be boolean")

        return cls(
            dataset_id=dataset_id,
            display_name=display_name,
            source=source,
            governance_tier=tier,
            contracts=contracts,
            natural_key_fields=natural_key_fields,
            _declared_historical_start=historical_start,
            _declared_coverage_segment_granularity=segment_granularity,
            _declared_expected_frequency=expected_frequency,
            _declared_research_eligible=declared_research_eligible,
        )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_text(raw: Mapping[str, Any], key: str, label: str) -> str | None:
    if key not in raw or raw[key] is None:
        return None
    return _text(raw[key], label)


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty string array")
    return tuple(_text(item, label) for item in value)


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
    """Reject drift in legacy JSON projections against their owning contracts.

    The projections are compatibility annotations only. A missing projection is
    valid; a present projection must equal the value derived from Coverage or
    SourceCapability V3.
    """
    from .source_capability import source_capability_contract_or_none

    mismatches: list[str] = []
    for contract in _DATASETS.values():
        coverage = _coverage_contract_or_none(contract.dataset_id)
        if coverage is not None:
            comparisons = (
                (
                    "historical_start",
                    contract._declared_historical_start,
                    coverage.history_target_start,
                ),
                (
                    "coverage_segment_granularity",
                    contract._declared_coverage_segment_granularity,
                    coverage.segment_granularity,
                ),
                (
                    "expected_frequency",
                    contract._declared_expected_frequency,
                    coverage.expected_frequency,
                ),
            )
            for name, declared, derived in comparisons:
                if declared is not None and declared != derived:
                    mismatches.append(
                        f"{contract.dataset_id}.{name}: declared={declared!r}, "
                        f"derived={derived!r}"
                    )

        capability = source_capability_contract_or_none(contract.dataset_id)
        if (
            capability is not None
            and contract._declared_research_eligible is not None
            and contract._declared_research_eligible
            != capability.historical_research_eligible
        ):
            mismatches.append(
                f"{contract.dataset_id}.research_eligible: "
                f"declared={contract._declared_research_eligible!r}, "
                f"derived={capability.historical_research_eligible!r}"
            )

    if mismatches:
        raise ValueError(
            "canonical meta-index projection drift: " + "; ".join(mismatches)
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


# Fail closed at import time if a compatibility projection drifts from its
# owning Coverage or SourceCapability contract.
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
