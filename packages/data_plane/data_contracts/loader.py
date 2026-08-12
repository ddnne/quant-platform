"""Strict loader for the canonical J-Quants Premium-core contract.

The checked-in JSON is consumed by both Python and the Cloudflare Worker.
This loader validates it eagerly so a malformed policy cannot silently fall
back to an unsafe timestamp rule.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

CONTRACT_PATH = Path(__file__).with_name("jquants_premium_core.json")

AVAILABLE_AT_POLICIES = frozenset(
    {
        "session_close",
        "explicit_timestamp_field",
        "explicit_disclosure_date",
        "known_publication_lag",
        "calendar_prepublished",
        "ingest_time_conservative",
    }
)
EVENT_TIME_POLICIES = frozenset(
    {"session_close", "explicit_timestamp_field", "observation_date"}
)
_REQUIRED_FIELDS = frozenset(
    {
        "dataset_id",
        "path",
        "group",
        "date_mode",
        "natural_key_fields",
        "event_time_policy",
        "available_at_policy",
        "availability_field",
        "known_publication_lag",
        "fallback_policy",
        "observation_grain",
    }
)


@dataclass(frozen=True)
class DatasetContract:
    dataset_id: str
    path: str
    group: str
    date_mode: str
    natural_key_fields: tuple[str, ...]
    event_time_policy: str
    event_time_fields: tuple[str, ...]
    available_at_policy: str
    availability_field: str | None
    known_publication_lag: str | None
    fallback_policy: str
    observation_grain: str
    bulk: str
    params: tuple[str, ...]
    code_param: bool
    day_param: str | None
    session: str | None
    field_aliases: Mapping[str, tuple[str, ...]]
    assumption: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DatasetContract":
        missing = _REQUIRED_FIELDS - raw.keys()
        if missing:
            raise ValueError(
                f"dataset contract missing fields {sorted(missing)}: {raw.get('dataset_id')!r}"
            )
        dataset_id = _nonempty(raw["dataset_id"], "dataset_id")
        path = _nonempty(raw["path"], f"{dataset_id}.path")
        if not path.startswith("/v2/"):
            raise ValueError(f"{dataset_id}.path must start with /v2/: {path!r}")
        policy = _nonempty(
            raw["available_at_policy"], f"{dataset_id}.available_at_policy"
        )
        if policy not in AVAILABLE_AT_POLICIES:
            raise ValueError(f"{dataset_id}: unknown available_at policy {policy!r}")
        event_policy = _nonempty(
            raw["event_time_policy"], f"{dataset_id}.event_time_policy"
        )
        if event_policy not in EVENT_TIME_POLICIES:
            raise ValueError(f"{dataset_id}: unknown event_time policy {event_policy!r}")
        if raw["fallback_policy"] != "ingest_time_conservative":
            raise ValueError(
                f"{dataset_id}: fallback_policy must be ingest_time_conservative"
            )
        aliases_raw = raw.get("field_aliases", {})
        if not isinstance(aliases_raw, dict):
            raise ValueError(f"{dataset_id}.field_aliases must be an object")
        aliases = MappingProxyType(
            {str(k): _string_tuple(v, f"{dataset_id}.field_aliases.{k}") for k, v in aliases_raw.items()}
        )
        availability_field = raw["availability_field"]
        if availability_field is not None and not isinstance(availability_field, str):
            raise ValueError(f"{dataset_id}.availability_field must be string or null")
        lag = raw["known_publication_lag"]
        if lag is not None and not isinstance(lag, str):
            raise ValueError(f"{dataset_id}.known_publication_lag must be string or null")
        return cls(
            dataset_id=dataset_id,
            path=path,
            group=_nonempty(raw["group"], f"{dataset_id}.group"),
            date_mode=_nonempty(raw["date_mode"], f"{dataset_id}.date_mode"),
            natural_key_fields=_string_tuple(
                raw["natural_key_fields"], f"{dataset_id}.natural_key_fields"
            ),
            event_time_policy=event_policy,
            event_time_fields=_string_tuple(
                raw.get("event_time_fields", []), f"{dataset_id}.event_time_fields"
            ),
            available_at_policy=policy,
            availability_field=availability_field,
            known_publication_lag=lag,
            fallback_policy=str(raw["fallback_policy"]),
            observation_grain=_nonempty(
                raw["observation_grain"], f"{dataset_id}.observation_grain"
            ),
            bulk=_nonempty(raw.get("bulk", "api"), f"{dataset_id}.bulk"),
            params=_string_tuple(raw.get("params", []), f"{dataset_id}.params"),
            code_param=bool(raw.get("code_param", False)),
            day_param=str(raw["day_param"]) if raw.get("day_param") else None,
            session=str(raw["session"]) if raw.get("session") else None,
            field_aliases=aliases,
            assumption=_nonempty(raw.get("assumption", ""), f"{dataset_id}.assumption"),
        )

    def aliases_for(self, field: str) -> tuple[str, ...]:
        """Canonical field followed by contract-declared source aliases."""
        return (field, *self.field_aliases.get(field, ()))

    def as_catalog_entry(self) -> dict[str, Any]:
        """Compatibility shape used by the existing ingestion client."""
        entry: dict[str, Any] = {
            "path": self.path,
            "group": self.group,
            "bulk": self.bulk,
            "params": list(self.params),
            "key": list(self.natural_key_fields),
            "date_mode": self.date_mode,
            "code_param": self.code_param,
            "contract": self,
        }
        if self.day_param:
            entry["day_param"] = self.day_param
        return entry


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ValueError(f"{label} must be an array of non-empty strings")
    return tuple(value)


def _load() -> tuple[int, Mapping[str, DatasetContract]]:
    document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if document.get("schema_version") != 2:
        raise ValueError("J-Quants contract schema_version must be 2")
    rows = document.get("datasets")
    if not isinstance(rows, list):
        raise ValueError("J-Quants contract datasets must be an array")
    contracts: dict[str, DatasetContract] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("each dataset contract must be an object")
        contract = DatasetContract.from_dict(raw)
        if contract.dataset_id in contracts:
            raise ValueError(f"duplicate dataset contract: {contract.dataset_id}")
        contracts[contract.dataset_id] = contract
    if len(contracts) != 23:
        raise ValueError(f"expected 23 Premium-core contracts, found {len(contracts)}")
    return 2, MappingProxyType(contracts)


SCHEMA_VERSION, _CONTRACTS = _load()


def all_contracts() -> tuple[DatasetContract, ...]:
    return tuple(_CONTRACTS.values())


def contract_for(dataset_id: str) -> DatasetContract:
    try:
        return _CONTRACTS[dataset_id]
    except KeyError as exc:
        raise KeyError(f"unknown Premium-core dataset contract: {dataset_id!r}") from exc


__all__ = [
    "AVAILABLE_AT_POLICIES",
    "CONTRACT_PATH",
    "DatasetContract",
    "EVENT_TIME_POLICIES",
    "SCHEMA_VERSION",
    "all_contracts",
    "contract_for",
]
