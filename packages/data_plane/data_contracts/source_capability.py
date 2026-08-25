"""SourceCapabilityContract v3 — official-availability source of truth.

This module is the official-availability SoT. Coverage required inventory,
backfill planning, Ops MCP, and READY profiles must derive from this
contract. They must not independently define a history start or coverage
mode that exceeds official provision.

``derive_collection_coverage_v3`` is the collection_coverage.json overlay
for datasets that have a V3 JSON row (policy_version collection-coverage/v3;
equities_master history_target_start 2008-05-07). Missing V3 stays None.

``storage.coverage_ledger.plan_required_segments`` MUST subset official
domain via ``required_domain_subset_official``. That clip does not invent
COMPLETE. The production ingestion Worker persists the effective per-dataset
V2/V3 policy; a new Ops generation must be published before live V3 is current.

JSON documents (optional) live at ``specs/source_capability/*.json``. An
empty or missing directory is valid: the type and fail-closed loader still
export. Missing dataset rows are not invented; they load as ``None``.

Nested evidence maps remain open; dataset-level keys are closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from qp_paths import repo_root

POLICY_VERSION = "source-capability/v3"
COLLECTION_COVERAGE_V3 = "collection-coverage/v3"
SCHEMA_VERSION = 3
SCHEMA_PATH = Path(__file__).with_name("source_capability.schema.json")

HISTORY_MODES = frozenset(
    {
        "bounded_history",
        "recent_snapshot",
        "next_business_day_snapshot",
        "event_stream",
        "official_archive_index",
        "periodic_archive",
    }
)
TIP_SNAPSHOT_MODES = frozenset(
    {"recent_snapshot", "next_business_day_snapshot"}
)
REQUIRED_DOMAIN_BASES = frozenset(
    {
        "calendar_months_from_official_start",
        "publication_windows_from_official_start",
        "issued_same_trading_day_snapshot",
        "issued_collection_cutoff_snapshot",
        "official_archive_publication_days",
        "official_archive_periods",
    }
)
EMPTY_SUCCESS_POLICIES = frozenset(
    {
        "never_complete",
        "trusted_exhausted_receipt_may_complete",
    }
)

_DATASET_FIELDS = (
    "dataset_id",
    "source",
    "upstream_locator",
    "official_evidence_url",
    "history_mode",
    "earliest_official_availability",
    "historical_research_eligible",
    "tip_only_operational",
    "supported_query_parameters",
    "publication_calendar",
    "entitlement_semantics",
    "collection_window",
    "freshness_sla",
    "event_time",
    "available_at",
    "revision_semantics",
    "research_profile_eligibility",
    "required_domain_semantics",
)
_DATASET_ALLOWED = frozenset(_DATASET_FIELDS) | frozenset({"policy_version"})
_BUNDLE_ALLOWED = frozenset({"policy_version", "datasets", "schema_version"})


def specs_dir() -> Path:
    """Directory of optional per-dataset / bundle JSON documents."""
    return repo_root() / "specs" / "source_capability"


def _reject_unknown(raw: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"{label} unknown field(s): {unknown}")


def _open_object(value: Any, label: str) -> dict[str, Any]:
    """Nested evidence maps are open; only the dataset-level key set is closed."""
    return dict(_require_object(value, label))


def _require_object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{label} must be an array of non-empty strings")
    return tuple(item.strip() for item in value)


def _iso_date(value: Any, label: str) -> str:
    text = _nonempty(value, label)
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO date YYYY-MM-DD") from exc
    if len(text) != 10:
        raise ValueError(f"{label} must be ISO date YYYY-MM-DD")
    return text


def _optional_str(raw: Mapping[str, Any], key: str, label: str) -> str | None:
    if key not in raw or raw[key] is None:
        return None
    return _nonempty(raw[key], label)


def _https_url(value: Any, label: str) -> str:
    text = _nonempty(value, label)
    if not text.startswith("https://"):
        raise ValueError(f"{label} must be an https URL")
    return text


@dataclass(frozen=True)
class PublicationCalendar:
    kind: str
    timezone: str
    index_url: str | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], label: str) -> "PublicationCalendar":
        obj = _open_object(raw, label)
        if "kind" not in obj or "timezone" not in obj:
            raise ValueError(f"{label} missing kind/timezone")
        index_url = _optional_str(obj, "index_url", f"{label}.index_url")
        if index_url is not None:
            index_url = _https_url(index_url, f"{label}.index_url")
        return cls(
            kind=_nonempty(obj["kind"], f"{label}.kind"),
            timezone=_nonempty(obj["timezone"], f"{label}.timezone"),
            index_url=index_url,
        )


@dataclass(frozen=True)
class EntitlementSemantics:
    clamp_before_earliest: bool
    subscription_floor: str | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], label: str) -> "EntitlementSemantics":
        obj = _open_object(raw, label)
        clamp = obj.get("clamp_before_earliest")
        if clamp is None:
            clamp = bool(obj.get("subscription_floor_is_not_historical_required_start"))
        floor = _optional_str(obj, "subscription_floor", f"{label}.subscription_floor")
        if floor is not None:
            floor = _iso_date(floor, f"{label}.subscription_floor")
        return cls(
            clamp_before_earliest=_bool(clamp, f"{label}.clamp_before_earliest"),
            subscription_floor=floor,
        )


@dataclass(frozen=True)
class CollectionWindow:
    grain: str
    open: str
    close: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], label: str) -> "CollectionWindow":
        obj = _open_object(raw, label)
        if "grain" not in obj:
            raise ValueError(f"{label} missing grain")
        open_v = obj.get("open") or obj.get("required_domain_start") or obj.get("pit_history_start")
        close_v = obj.get("close") or obj.get("required_domain_end") or ""
        return cls(
            grain=_nonempty(obj["grain"], f"{label}.grain"),
            open=_nonempty(open_v, f"{label}.open"),
            close=str(close_v),
        )


@dataclass(frozen=True)
class FreshnessSla:
    expected_after: str
    usable_by: str
    timezone: str
    rule: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], label: str) -> "FreshnessSla":
        obj = _open_object(raw, label)
        tz = obj.get("timezone") or "UTC"
        rule = obj.get("rule") or obj.get("policy") or "unspecified"
        expected = obj.get("expected_after") or obj.get("next_business_day_after") or ""
        usable = obj.get("usable_by") or expected
        return cls(
            expected_after=str(expected),
            usable_by=str(usable),
            timezone=_nonempty(tz, f"{label}.timezone"),
            rule=_nonempty(rule, f"{label}.rule"),
        )


@dataclass(frozen=True)
class EventTimeSpec:
    policy: str
    fields: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], label: str) -> "EventTimeSpec":
        obj = _open_object(raw, label)
        if "policy" not in obj:
            raise ValueError(f"{label} missing policy")
        fields = obj.get("fields") if isinstance(obj.get("fields"), list) else []
        return cls(
            policy=_nonempty(obj["policy"], f"{label}.policy"),
            fields=_string_tuple(fields, f"{label}.fields") if fields else (),
        )


@dataclass(frozen=True)
class AvailableAtSpec:
    policy: str
    field: str | None
    known_publication_lag: str | None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], label: str) -> "AvailableAtSpec":
        obj = _open_object(raw, label)
        if "policy" not in obj:
            raise ValueError(f"{label} missing policy")
        field = obj.get("field")
        if field is not None and (not isinstance(field, str) or not field.strip()):
            raise ValueError(f"{label}.field must be a non-empty string or null")
        lag = obj.get("known_publication_lag")
        if lag is not None and (not isinstance(lag, str) or not lag.strip()):
            raise ValueError(
                f"{label}.known_publication_lag must be a non-empty string or null"
            )
        return cls(
            policy=_nonempty(obj["policy"], f"{label}.policy"),
            field=field.strip() if isinstance(field, str) else None,
            known_publication_lag=lag.strip() if isinstance(lag, str) else None,
        )


@dataclass(frozen=True)
class RevisionSemantics:
    policy: str
    generation_on_revision: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], label: str) -> "RevisionSemantics":
        obj = _open_object(raw, label)
        policy = obj.get("policy") or obj.get("kind")
        if not policy:
            raise ValueError(f"{label} missing policy")
        gen = obj.get("generation_on_revision")
        if gen is None:
            gen = False
        return cls(
            policy=_nonempty(policy, f"{label}.policy"),
            generation_on_revision=_bool(gen, f"{label}.generation_on_revision"),
        )


@dataclass(frozen=True)
class ResearchProfileEligibility:
    include_in: tuple[str, ...]
    exclude_from: tuple[str, ...]
    exclusion_reason: str

    @classmethod
    def from_dict(
        cls, raw: Mapping[str, Any], label: str
    ) -> "ResearchProfileEligibility":
        obj = _open_object(raw, label)
        include = obj.get("include_in") if isinstance(obj.get("include_in"), list) else []
        exclude = obj.get("exclude_from") if isinstance(obj.get("exclude_from"), list) else []
        reason = obj.get("exclusion_reason")
        if not isinstance(reason, str):
            reason = ""
        return cls(
            include_in=_string_tuple(include, f"{label}.include_in") if include else (),
            exclude_from=_string_tuple(exclude, f"{label}.exclude_from") if exclude else (),
            exclusion_reason=reason,
        )


@dataclass(frozen=True)
class RequiredDomainSemantics:
    basis: str
    empty_success_policy: str

    @classmethod
    def from_dict(
        cls, raw: Mapping[str, Any], label: str
    ) -> "RequiredDomainSemantics":
        obj = _open_object(raw, label)
        if "basis" not in obj or "empty_success_policy" not in obj:
            raise ValueError(f"{label} missing basis/empty_success_policy")
        basis = _nonempty(obj["basis"], f"{label}.basis")
        if basis not in REQUIRED_DOMAIN_BASES:
            raise ValueError(
                f"{label}.basis must be one of {sorted(REQUIRED_DOMAIN_BASES)}"
            )
        empty_policy = _nonempty(
            obj["empty_success_policy"], f"{label}.empty_success_policy"
        )
        if empty_policy not in EMPTY_SUCCESS_POLICIES:
            raise ValueError(
                f"{label}.empty_success_policy must be one of "
                f"{sorted(EMPTY_SUCCESS_POLICIES)}"
            )
        return cls(basis=basis, empty_success_policy=empty_policy)


@dataclass(frozen=True)
class SourceCapabilityContract:
    """Per-dataset official availability. Unknown keys fail closed."""

    dataset_id: str
    source: str
    upstream_locator: str
    official_evidence_url: str
    history_mode: str
    earliest_official_availability: str
    historical_research_eligible: bool
    tip_only_operational: bool
    supported_query_parameters: tuple[str, ...]
    publication_calendar: PublicationCalendar
    entitlement_semantics: EntitlementSemantics
    collection_window: CollectionWindow
    freshness_sla: FreshnessSla
    event_time: EventTimeSpec
    available_at: AvailableAtSpec
    revision_semantics: RevisionSemantics
    research_profile_eligibility: ResearchProfileEligibility
    required_domain_semantics: RequiredDomainSemantics

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SourceCapabilityContract":
        obj = _require_object(raw, "SourceCapabilityContract")
        _reject_unknown(obj, _DATASET_ALLOWED, "SourceCapabilityContract")
        if "dataset_id" not in obj:
            raise ValueError("SourceCapabilityContract missing dataset_id")
        missing = [name for name in _DATASET_FIELDS if name not in obj]
        if missing:
            raise ValueError(
                f"SourceCapabilityContract missing {missing}: {obj.get('dataset_id')!r}"
            )
        if "policy_version" in obj:
            version = _nonempty(obj["policy_version"], "policy_version")
            if version != POLICY_VERSION:
                raise ValueError(
                    f"unsupported SourceCapabilityContract policy_version: {version!r}"
                )
        dataset_id = _nonempty(obj["dataset_id"], "dataset_id")
        history_mode = _nonempty(obj["history_mode"], f"{dataset_id}.history_mode")
        if history_mode not in HISTORY_MODES:
            raise ValueError(
                f"{dataset_id}.history_mode must be one of {sorted(HISTORY_MODES)}: "
                f"{history_mode!r}"
            )
        collection_window = CollectionWindow.from_dict(
            obj["collection_window"], f"{dataset_id}.collection_window"
        )
        domain_semantics = RequiredDomainSemantics.from_dict(
            obj["required_domain_semantics"],
            f"{dataset_id}.required_domain_semantics",
        )
        _validate_required_domain_semantics(
            dataset_id=dataset_id,
            history_mode=history_mode,
            historical_research_eligible=obj["historical_research_eligible"],
            tip_only_operational=obj["tip_only_operational"],
            collection_window=collection_window,
            semantics=domain_semantics,
        )
        return cls(
            dataset_id=dataset_id,
            source=_nonempty(obj["source"], f"{dataset_id}.source"),
            upstream_locator=_nonempty(
                obj["upstream_locator"], f"{dataset_id}.upstream_locator"
            ),
            official_evidence_url=_https_url(
                obj["official_evidence_url"], f"{dataset_id}.official_evidence_url"
            ),
            history_mode=history_mode,
            earliest_official_availability=_iso_date(
                obj["earliest_official_availability"],
                f"{dataset_id}.earliest_official_availability",
            ),
            historical_research_eligible=_bool(
                obj["historical_research_eligible"],
                f"{dataset_id}.historical_research_eligible",
            ),
            tip_only_operational=_bool(
                obj["tip_only_operational"], f"{dataset_id}.tip_only_operational"
            ),
            supported_query_parameters=_string_tuple(
                obj["supported_query_parameters"],
                f"{dataset_id}.supported_query_parameters",
            ),
            publication_calendar=PublicationCalendar.from_dict(
                obj["publication_calendar"], f"{dataset_id}.publication_calendar"
            ),
            entitlement_semantics=EntitlementSemantics.from_dict(
                obj["entitlement_semantics"], f"{dataset_id}.entitlement_semantics"
            ),
            collection_window=collection_window,
            freshness_sla=FreshnessSla.from_dict(
                obj["freshness_sla"], f"{dataset_id}.freshness_sla"
            ),
            event_time=EventTimeSpec.from_dict(
                obj["event_time"], f"{dataset_id}.event_time"
            ),
            available_at=AvailableAtSpec.from_dict(
                obj["available_at"], f"{dataset_id}.available_at"
            ),
            revision_semantics=RevisionSemantics.from_dict(
                obj["revision_semantics"], f"{dataset_id}.revision_semantics"
            ),
            research_profile_eligibility=ResearchProfileEligibility.from_dict(
                obj["research_profile_eligibility"],
                f"{dataset_id}.research_profile_eligibility",
            ),
            required_domain_semantics=domain_semantics,
        )


_BASIS_HISTORY_MODE: Mapping[str, str] = MappingProxyType(
    {
        "calendar_months_from_official_start": "bounded_history",
        "publication_windows_from_official_start": "event_stream",
        "issued_same_trading_day_snapshot": "recent_snapshot",
        "issued_collection_cutoff_snapshot": "next_business_day_snapshot",
        "official_archive_publication_days": "official_archive_index",
        "official_archive_periods": "periodic_archive",
    }
)
_BASIS_GRAIN: Mapping[str, str] = MappingProxyType(
    {
        "calendar_months_from_official_start": "calendar_month",
        "publication_windows_from_official_start": "calendar_month",
        "issued_same_trading_day_snapshot": "same_trading_day_am_snapshot",
        "issued_collection_cutoff_snapshot": "collection_cutoff_snapshot",
        "official_archive_publication_days": "official_archive_index_day",
        "official_archive_periods": "official_archive_year",
    }
)


def _validate_required_domain_semantics(
    *,
    dataset_id: str,
    history_mode: str,
    historical_research_eligible: Any,
    tip_only_operational: Any,
    collection_window: CollectionWindow,
    semantics: RequiredDomainSemantics,
) -> None:
    historical = _bool(
        historical_research_eligible,
        f"{dataset_id}.historical_research_eligible",
    )
    tip_only = _bool(tip_only_operational, f"{dataset_id}.tip_only_operational")
    expected_mode = _BASIS_HISTORY_MODE[semantics.basis]
    expected_grain = _BASIS_GRAIN[semantics.basis]
    if history_mode != expected_mode:
        raise ValueError(
            f"{dataset_id}.required_domain_semantics.basis requires "
            f"history_mode {expected_mode!r}"
        )
    if collection_window.grain != expected_grain:
        raise ValueError(
            f"{dataset_id}.required_domain_semantics.basis requires "
            f"collection_window.grain {expected_grain!r}"
        )
    if tip_only != (history_mode in TIP_SNAPSHOT_MODES):
        raise ValueError(
            f"{dataset_id}.tip_only_operational must match snapshot history_mode"
        )
    if historical == tip_only:
        raise ValueError(
            f"{dataset_id} historical_research_eligible and tip_only_operational "
            "must be opposite"
        )
    if (
        history_mode
        in TIP_SNAPSHOT_MODES | {"official_archive_index", "periodic_archive"}
        and semantics.empty_success_policy != "never_complete"
    ):
        raise ValueError(
            f"{dataset_id} snapshot/archive empty SUCCESS must never COMPLETE"
        )


@dataclass(frozen=True)
class OfficialRequiredDomainSubset:
    """Official availability domain. Required coverage inventory must be a subset.

    Does not invent COMPLETE. ``coverage_ledger.plan_required_segments`` MUST
    subset official domain via ``required_domain_subset_official``.
    """

    dataset_id: str
    policy_version: str
    history_mode: str
    earliest_official_availability: str
    historical_research_eligible: bool
    tip_only_operational: bool
    admit_historical_required_segments: bool
    publication_days_only: bool
    collection_window_grain: str
    supported_query_parameters: tuple[str, ...]
    research_profile_include_in: tuple[str, ...]
    research_profile_exclude_from: tuple[str, ...]
    required_domain_basis: str
    empty_success_policy: str


def required_domain_subset_official(
    contract: SourceCapabilityContract,
) -> OfficialRequiredDomainSubset:
    """Official domain that CoverageRequiredSet / backfill / READY must subset."""
    if not isinstance(contract, SourceCapabilityContract):
        raise TypeError(
            "required_domain_subset_official requires SourceCapabilityContract"
        )
    tip_snapshot = contract.history_mode in TIP_SNAPSHOT_MODES
    admit_historical = (
        contract.historical_research_eligible and not tip_snapshot
    )
    publication_days_only = contract.history_mode == "official_archive_index"
    return OfficialRequiredDomainSubset(
        dataset_id=contract.dataset_id,
        policy_version=POLICY_VERSION,
        history_mode=contract.history_mode,
        earliest_official_availability=contract.earliest_official_availability,
        historical_research_eligible=contract.historical_research_eligible,
        tip_only_operational=contract.tip_only_operational,
        admit_historical_required_segments=admit_historical,
        publication_days_only=publication_days_only,
        collection_window_grain=contract.collection_window.grain,
        supported_query_parameters=contract.supported_query_parameters,
        research_profile_include_in=contract.research_profile_eligibility.include_in,
        research_profile_exclude_from=contract.research_profile_eligibility.exclude_from,
        required_domain_basis=contract.required_domain_semantics.basis,
        empty_success_policy=(
            contract.required_domain_semantics.empty_success_policy
        ),
    )


def derive_collection_coverage_v3(
    contract: SourceCapabilityContract,
) -> dict[str, str]:
    """collection_coverage.json SoT fields for one SourceCapability row.

    Does not invent COMPLETE. Does not rewrite live MCP projection.
    Missing V3 is ``collection_coverage_v3_overrides`` → None.
    """
    if not isinstance(contract, SourceCapabilityContract):
        raise TypeError(
            "derive_collection_coverage_v3 requires SourceCapabilityContract"
        )
    return {
        "policy_version": COLLECTION_COVERAGE_V3,
        "history_target_start": contract.earliest_official_availability,
        "history_mode": contract.history_mode,
        "segment_granularity": contract.collection_window.grain,
        "required_domain_basis": contract.required_domain_semantics.basis,
        "empty_success_policy": (
            contract.required_domain_semantics.empty_success_policy
        ),
    }


def _parse_policy_version(value: Any) -> str:
    version = _nonempty(value, "policy_version")
    if version != POLICY_VERSION:
        raise ValueError(
            f"unsupported SourceCapabilityContract policy_version: {version!r}"
        )
    return version


def parse_source_capability_document(
    raw: Mapping[str, Any], *, origin: str = "<memory>"
) -> tuple[SourceCapabilityContract, ...]:
    """Decode one JSON object: a single dataset or a ``datasets`` bundle."""
    obj = _require_object(raw, origin)
    if "datasets" in obj:
        _reject_unknown(obj, _BUNDLE_ALLOWED, origin)
        if "policy_version" not in obj:
            raise ValueError(f"{origin} missing policy_version")
        _parse_policy_version(obj["policy_version"])
        if "schema_version" in obj and obj["schema_version"] != SCHEMA_VERSION:
            raise ValueError(
                f"{origin} schema_version must be {SCHEMA_VERSION}"
            )
        rows = obj["datasets"]
        if not isinstance(rows, list):
            raise ValueError(f"{origin} datasets must be an array")
        contracts = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise ValueError(f"{origin} datasets[{index}] must be an object")
            contracts.append(SourceCapabilityContract.from_dict(row))
        return tuple(contracts)
    return (SourceCapabilityContract.from_dict(obj),)


def load_source_capability_dir(
    directory: Path | None = None,
) -> Mapping[str, SourceCapabilityContract]:
    """Load and validate ``*.json`` under ``specs/source_capability``.

    Missing or empty directory → empty mapping. Unknown fields fail closed.
    ``schema.json`` is skipped so a schema document can live beside rows.
    """
    root = specs_dir() if directory is None else Path(directory)
    if not root.is_dir():
        return MappingProxyType({})
    contracts: dict[str, SourceCapabilityContract] = {}
    for path in sorted(root.glob("*.json")):
        if path.name == "schema.json":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        origin = str(path)
        if not isinstance(document, Mapping):
            raise ValueError(f"{origin} must be a JSON object")
        for contract in parse_source_capability_document(document, origin=origin):
            if contract.dataset_id in contracts:
                raise ValueError(
                    f"duplicate SourceCapabilityContract dataset_id: "
                    f"{contract.dataset_id!r} ({origin})"
                )
            contracts[contract.dataset_id] = contract
    return MappingProxyType(contracts)


_CONTRACTS: Mapping[str, SourceCapabilityContract] = load_source_capability_dir()


def all_source_capability_contracts() -> tuple[SourceCapabilityContract, ...]:
    return tuple(_CONTRACTS.values())


def source_capability_contract_or_none(
    dataset_id: str,
) -> SourceCapabilityContract | None:
    """Return the V3 contract, or None when no JSON row exists.

    Missing dataset rows are not invented. An empty specs directory is valid.
    """
    return _CONTRACTS.get(dataset_id)


def source_capability_contract_for(dataset_id: str) -> SourceCapabilityContract:
    contract = source_capability_contract_or_none(dataset_id)
    if contract is None:
        raise KeyError(f"unknown SourceCapabilityContract: {dataset_id!r}")
    return contract


def collection_coverage_v3_overrides(dataset_id: str) -> dict[str, str] | None:
    """Derive V3 coverage overlays, or None when no SourceCapability JSON exists."""
    contract = source_capability_contract_or_none(dataset_id)
    if contract is None:
        return None
    return derive_collection_coverage_v3(contract)


def coverage_v3_dataset_ids() -> frozenset[str]:
    """Dataset ids that have a SourceCapability V3 JSON row. Not COMPLETE 23."""
    return frozenset(_CONTRACTS)


def _earliest_official_availability(
    contract: SourceCapabilityContract | Mapping[str, Any],
) -> str:
    if isinstance(contract, SourceCapabilityContract):
        return contract.earliest_official_availability
    return _iso_date(
        contract.get("earliest_official_availability")
        if isinstance(contract, Mapping)
        else None,
        "earliest_official_availability",
    )


def apply_official_query_clamp(
    query_date: str,
    contract: SourceCapabilityContract | Mapping[str, Any],
) -> str:
    """Clamp a snapshot/query date to official provision start.

    Dates before ``earliest_official_availability`` are vendor-misdate
    queries, not missing backfill and not required history. Does not
    rewrite a PIT ``as_of`` used for ``available_at <= as_of``.
    """
    start = _earliest_official_availability(contract)
    day = str(query_date).strip()[:10]
    if len(day) != 10:
        raise ValueError("query_date must be ISO date YYYY-MM-DD")
    if day < start:
        return start
    return str(query_date).strip()


__all__ = [
    "COLLECTION_COVERAGE_V3",
    "HISTORY_MODES",
    "EMPTY_SUCCESS_POLICIES",
    "POLICY_VERSION",
    "SCHEMA_PATH",
    "SCHEMA_VERSION",
    "TIP_SNAPSHOT_MODES",
    "REQUIRED_DOMAIN_BASES",
    "AvailableAtSpec",
    "CollectionWindow",
    "EntitlementSemantics",
    "EventTimeSpec",
    "FreshnessSla",
    "OfficialRequiredDomainSubset",
    "PublicationCalendar",
    "ResearchProfileEligibility",
    "RequiredDomainSemantics",
    "RevisionSemantics",
    "SourceCapabilityContract",
    "all_source_capability_contracts",
    "apply_official_query_clamp",
    "collection_coverage_v3_overrides",
    "coverage_v3_dataset_ids",
    "derive_collection_coverage_v3",
    "load_source_capability_dir",
    "parse_source_capability_document",
    "required_domain_subset_official",
    "source_capability_contract_for",
    "source_capability_contract_or_none",
    "specs_dir",
]
