"""Python compatibility surface for Worker availability normalization.

Rules come from the shared Premium-core JSON contract; this module deliberately
contains no dataset list or field-priority table of its own.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from data_contracts.identity import available_at_for, session_close_jst
from data_contracts.loader import AVAILABLE_AT_POLICIES, all_contracts, contract_for

POLICIES = tuple(sorted(AVAILABLE_AT_POLICIES))
DATASET_POLICY = {c.dataset_id: c.available_at_policy for c in all_contracts()}
SESSION_CLOSE_DATASETS = tuple(sorted(
    c.dataset_id for c in all_contracts() if c.available_at_policy == "session_close"
))
DEFAULT_POLICY = "ingest_time_conservative"
AvailabilityPolicy = str


def _ordered_contract_fields() -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for contract in all_contracts():
        for field in contract.event_time_fields:
            seen.setdefault(field, None)
        if contract.availability_field:
            for field in contract.availability_field.split("+"):
                seen.setdefault(field, None)
    return tuple(seen)


# Import compatibility only. Runtime selection is always per contract; this
# union is not a priority list and must not be used as normalization authority.
EVENT_FIELD_CANDIDATES = _ordered_contract_fields()


def next_business_open_jst(date_yyyy_mm_dd: str) -> str:
    """Deprecated compatibility helper; runtime policies never call this."""
    day = datetime.strptime(date_yyyy_mm_dd, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.strftime("%Y-%m-%dT09:00:00+09:00")


def policy_for_dataset(dataset_id: str) -> str:
    try:
        return contract_for(dataset_id).available_at_policy
    except KeyError:
        return DEFAULT_POLICY


def pick_available_at(
    row: Mapping[str, Any], dataset_id: str, ingested_at: str
) -> str:
    try:
        return available_at_for(row, dataset_id, ingested_at)
    except KeyError:
        return ingested_at


__all__ = [
    "AvailabilityPolicy",
    "DATASET_POLICY",
    "DEFAULT_POLICY",
    "EVENT_FIELD_CANDIDATES",
    "POLICIES",
    "SESSION_CLOSE_DATASETS",
    "next_business_open_jst",
    "pick_available_at",
    "policy_for_dataset",
    "session_close_jst",
]
