"""Strict contracts for governed Japan Securities Dealers Association data."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

JSDA_CONTRACT_PATH = Path(__file__).with_name("jsda_governed.json")

_REQUIRED = frozenset({
    "dataset_id",
    "source_product",
    "index_url",
    "history_target_start",
    "history_target_end_rule",
    "coverage_mode",
    "expected_frequency",
    "segment_grain",
    "natural_key_fields",
    "effective_time_policy",
    "publication_label_policy",
    "available_at_policy",
    "correction_policy",
    "canonical_formats",
    "governance_tier",
})


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty string array")
    return tuple(_text(item, label) for item in value)


@dataclass(frozen=True)
class JsdaDatasetContract:
    dataset_id: str
    source_product: str
    index_url: str
    history_target_start: str
    history_target_end_rule: str
    coverage_mode: str
    expected_frequency: str
    segment_grain: str
    natural_key_fields: tuple[str, ...]
    effective_time_policy: str
    publication_label_policy: str
    available_at_policy: str
    correction_policy: str
    canonical_formats: tuple[str, ...]
    governance_tier: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "JsdaDatasetContract":
        missing = _REQUIRED - raw.keys()
        if missing:
            raise ValueError(f"JSDA contract missing fields: {sorted(missing)}")
        dataset_id = _text(raw["dataset_id"], "dataset_id")
        if not dataset_id.startswith("jsda_"):
            raise ValueError(f"JSDA dataset id must start with jsda_: {dataset_id!r}")
        index_url = _text(raw["index_url"], f"{dataset_id}.index_url")
        if not index_url.startswith("https://"):
            raise ValueError(f"{dataset_id}.index_url must be HTTPS")
        tier = _text(raw["governance_tier"], f"{dataset_id}.governance_tier")
        if tier not in {"governed", "experimental"}:
            raise ValueError(f"{dataset_id}.governance_tier is invalid")
        values = {
            name: _text(raw[name], f"{dataset_id}.{name}")
            for name in _REQUIRED
            if name not in {
                "dataset_id", "natural_key_fields", "canonical_formats"
            }
        }
        return cls(
            dataset_id=dataset_id,
            natural_key_fields=_strings(
                raw["natural_key_fields"], f"{dataset_id}.natural_key_fields"
            ),
            canonical_formats=_strings(
                raw["canonical_formats"], f"{dataset_id}.canonical_formats"
            ),
            **values,
        )


def _load() -> tuple[str, Mapping[str, JsdaDatasetContract]]:
    document = json.loads(JSDA_CONTRACT_PATH.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("JSDA contract schema_version must be 1")
    if document.get("source") != "jsda":
        raise ValueError("JSDA contract source must be jsda")
    version = _text(document.get("contract_version"), "contract_version")
    rows = document.get("datasets")
    if not isinstance(rows, list) or not rows:
        raise ValueError("JSDA contract datasets must be a non-empty array")
    contracts: dict[str, JsdaDatasetContract] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("each JSDA dataset contract must be an object")
        contract = JsdaDatasetContract.from_dict(raw)
        if contract.dataset_id in contracts:
            raise ValueError(f"duplicate JSDA dataset: {contract.dataset_id}")
        contracts[contract.dataset_id] = contract
    return version, MappingProxyType(contracts)


JSDA_CONTRACT_VERSION, _CONTRACTS = _load()


def all_jsda_contracts() -> tuple[JsdaDatasetContract, ...]:
    return tuple(_CONTRACTS.values())


def jsda_contract_for(dataset_id: str) -> JsdaDatasetContract:
    try:
        return _CONTRACTS[dataset_id]
    except KeyError as exc:
        raise KeyError(f"unknown governed JSDA dataset: {dataset_id!r}") from exc


__all__ = [
    "JSDA_CONTRACT_PATH",
    "JSDA_CONTRACT_VERSION",
    "JsdaDatasetContract",
    "all_jsda_contracts",
    "jsda_contract_for",
]
