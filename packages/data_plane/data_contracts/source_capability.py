"""SourceCapabilityContract v3 — official-availability source of truth.

Coverage required inventory, backfill planning, Ops MCP, and READY profiles
must derive from this contract. They must not independently define a history
start or coverage mode that exceeds official provision.

JSON documents (optional) live at ``specs/source_capability/*.json``. An
empty or missing directory is valid: the type and fail-closed loader still
export. Dataset rows are not invented here.

This module does not rewrite ``plan_required_segments``. Other lanes call
``required_domain_subset_official``.
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
)
_DATASET_ALLOWED = frozenset(_DATASET_FIELDS) | frozenset({"policy_version"})
_BUNDLE_ALLOWED = frozenset({"policy_version", "datasets", "schema_version"})
_PUBLICATION_CALENDAR_ALLOWED = frozenset({"kind", "timezone", "index_url"})
_ENTITLEMENT_ALLOWED = frozenset({"clamp_before_earliest", "subscription_floor"})
_COLLECTION_WINDOW_ALLOWED = frozenset({"grain", "open", "close"})
_FRESHNESS_SLA_ALLOWED = frozenset(
    {"expected_after", "usable_by", "timezone", "rule"}
)
_EVENT_TIME_ALLOWED = frozenset({"policy", "fields"})
_AVAILABLE_AT_ALLOWED = frozenset(
    {"policy", "field", "known_publication_lag"}
)
_REVISION_ALLOWED = frozenset({"policy", "generation_on_revision"})
_PROFILE_ELIGIBILITY_ALLOWED = frozenset(
    {"include_in", "exclude_from", "exclusion_reason"}
)


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
        obj = _require_object(raw, label)
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
        obj = _require_object(raw, label)
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
        obj = _require_object(raw, label)
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
        obj = _require_object(raw, label)
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
        obj = _require_object(raw, label)
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
        obj = _require_object(raw, label)
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
        obj = _require_object(raw, label)
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
        obj = _require_object(raw, label)
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
            collection_window=CollectionWindow.from_dict(
                obj["collection_window"], f"{dataset_id}.collection_window"
            ),
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
        )


@dataclass(frozen=True)
class OfficialRequiredDomainSubset:
    """Official availability domain. Required coverage inventory must be a subset.

    Does not invent COMPLETE and does not plan segments. Later lanes clip
    ``plan_required_segments`` to this domain.
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
    )


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


def source_capability_contract_for(dataset_id: str) -> SourceCapabilityContract:
    try:
        return _CONTRACTS[dataset_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown SourceCapabilityContract: {dataset_id!r}"
        ) from exc


__all__ = [
    "HISTORY_MODES",
    "POLICY_VERSION",
    "SCHEMA_PATH",
    "SCHEMA_VERSION",
    "TIP_SNAPSHOT_MODES",
    "AvailableAtSpec",
    "CollectionWindow",
    "EntitlementSemantics",
    "EventTimeSpec",
    "FreshnessSla",
    "OfficialRequiredDomainSubset",
    "PublicationCalendar",
    "ResearchProfileEligibility",
    "RevisionSemantics",
    "SourceCapabilityContract",
    "all_source_capability_contracts",
    "load_source_capability_dir",
    "parse_source_capability_document",
    "required_domain_subset_official",
    "source_capability_contract_for",
    "specs_dir",
]
