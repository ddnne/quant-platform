"""Collection coverage policy paired with the canonical dataset contract.

The policy distinguishes calendar/periodic series from irregular event feeds
and SourceCapabilityContract V3 snapshot grains. Event feeds never acquire
invented daily row-count expectations.

V3 official-domain datasets are those with a SourceCapability JSON row.
Their collection_coverage.json rows must match ``derive_collection_coverage_v3``
(policy_version collection-coverage/v3; master history_target_start
``2008-05-07``). Missing V3 stays None. Tip/snapshot grains plan a current
collection window, not hundreds of empty monthly COMPLETE shells. Official
``2008-05-07`` for equities_master is domain correction, not Dataset COMPLETE.
The production ingestion Worker consumes the same mixed-version document and
persists each dataset row's effective policy version. Publishing a V3 Ops
generation is still a separate operational step and never relabels old V2
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
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
SNAPSHOT_SEGMENT_GRANULARITIES = frozenset({
    "collection_cutoff_snapshot",
    "same_trading_day_am_snapshot",
})
SEGMENT_GRANULARITIES = frozenset({
    "calendar_month",
    "official_archive_day",
    "official_archive_index_day",
    "official_archive_year",
    "source_time_series_file",
}) | SNAPSHOT_SEGMENT_GRANULARITIES
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
# Optional metadata only. Never copied into history_target_start.
VENDOR_ANNOTATION_FIELDS = (
    "not_historical_required_start",
    "earliest_official_availability",
    "official_mode",
    "vendor_data_provision_start",
    "vendor_history_policy",
    "vendor_data_provision_citation",
    "vendor_history_policy_citation",
)
_OPTIONAL_STRINGS = (
    "policy_version",
    "history_mode",
    "required_domain_basis",
    "empty_success_policy",
) + VENDOR_ANNOTATION_FIELDS


@dataclass(frozen=True)
class CollectionCoverageContract:
    """One dataset's collection policy.

    Vendor annotation fields are optional documented metadata. They are
    retained when present and omitted as ``None`` when absent.
    ``history_target_start`` is always the JSON field as written — never
    replaced by an entitlement floor or official-availability annotation.
    """

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
    policy_version: str | None = None
    history_mode: str | None = None
    required_domain_basis: str | None = None
    empty_success_policy: str | None = None
    not_historical_required_start: str | None = None
    earliest_official_availability: str | None = None
    official_mode: str | None = None
    vendor_data_provision_start: str | None = None
    vendor_history_policy: str | None = None
    vendor_data_provision_citation: str | None = None
    vendor_history_policy_citation: str | None = None

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
        # Vendor annotations stay on the object. Do not copy them into
        # history_target_start; V2 floors and V3 official starts remain
        # distinct JSON values.
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
        optional: dict[str, Any] = {}
        for name in _OPTIONAL_STRINGS:
            if name not in raw or raw[name] is None:
                continue
            value = raw[name]
            if not isinstance(value, str) or not value:
                raise ValueError(f"{dataset_id}.{name} must be non-empty string")
            optional[name] = value
        if optional.get("policy_version") == "collection-coverage/v3":
            from .source_capability import (
                EMPTY_SUCCESS_POLICIES,
                REQUIRED_DOMAIN_BASES,
            )

            missing_v3 = {
                "history_mode",
                "required_domain_basis",
                "empty_success_policy",
            } - optional.keys()
            if missing_v3:
                raise ValueError(
                    f"{dataset_id} collection-coverage/v3 missing "
                    f"{sorted(missing_v3)}"
                )
            if optional["required_domain_basis"] not in REQUIRED_DOMAIN_BASES:
                raise ValueError(
                    f"{dataset_id}.required_domain_basis is not supported"
                )
            if optional["empty_success_policy"] not in EMPTY_SUCCESS_POLICIES:
                raise ValueError(
                    f"{dataset_id}.empty_success_policy is not supported"
                )
        return cls(
            dataset_id=dataset_id,
            **{name: raw[name] for name in _REQUIRED},
            **optional,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"dataset_id": self.dataset_id}
        for name in _REQUIRED:
            payload[name] = getattr(self, name)
        for name in _OPTIONAL_STRINGS:
            payload[name] = getattr(self, name)
        return payload


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
            dataset_id,
            {**defaults, "policy_version": policy_version, **overrides},
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


def coverage_policy_digest(dataset_id: str) -> str:
    """Canonical digest for one dataset's effective governed policy row.

    The collection-coverage document root may contain a deliberate mixture of
    V2 and V3 rows.  READY therefore binds this per-dataset digest instead of
    treating the document-root version as the effective policy for every row.
    """

    payload = coverage_contract_for(dataset_id).to_dict()
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def coverage_policy_binding(dataset_id: str) -> Mapping[str, str]:
    """Closed identity/version/digest tuple for one governed policy row."""

    contract = coverage_contract_for(dataset_id)
    if not contract.policy_version:
        raise ValueError(f"coverage policy version missing for {dataset_id!r}")
    return MappingProxyType(
        {
            "policy_id": dataset_id,
            "policy_version": contract.policy_version,
            "policy_digest": coverage_policy_digest(dataset_id),
        }
    )


def coverage_policy_set_binding(dataset_ids: tuple[str, ...] | list[str]) -> Mapping[str, Any]:
    """Canonical mixed-version policy-set binding for exact dataset membership."""

    normalized = tuple(sorted(str(item) for item in dataset_ids))
    if not normalized or len(normalized) != len(set(normalized)):
        raise ValueError("coverage policy set requires unique dataset ids")
    rows = [dict(coverage_policy_binding(dataset_id)) for dataset_id in normalized]
    raw = json.dumps(
        rows,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    versions = sorted({row["policy_version"] for row in rows})
    effective_version = versions[0] if len(versions) == 1 else "mixed:" + digest
    return MappingProxyType(
        {
            "policy_version": effective_version,
            "policy_digest": digest,
            "datasets": tuple(MappingProxyType(row) for row in rows),
        }
    )


__all__ = [
    "COVERAGE_CONTRACT_PATH",
    "COVERAGE_STATUSES",
    "GOVERNANCE_TIERS",
    "SEGMENT_GRANULARITIES",
    "SNAPSHOT_SEGMENT_GRANULARITIES",
    "VENDOR_ANNOTATION_FIELDS",
    "POLICY_VERSION",
    "CollectionCoverageContract",
    "all_coverage_contracts",
    "coverage_contract_for",
    "coverage_policy_binding",
    "coverage_policy_digest",
    "coverage_policy_set_binding",
]
