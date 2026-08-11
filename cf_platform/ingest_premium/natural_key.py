"""Python compatibility surface for Worker identity normalization.

Dataset-specific key and event policies are selected from ``data_contracts``;
there is intentionally no global ``KEY_FIELDS`` authority.
"""

from __future__ import annotations

from typing import Any

from data_contracts.identity import event_time_for, natural_key as _natural_key
from data_contracts.loader import all_contracts


def _field_union(attribute: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for contract in all_contracts():
        for field in getattr(contract, attribute):
            seen.setdefault(field, None)
    return tuple(seen)


# Backward-compatible introspection unions. They are not consulted by either
# normalizer; dataset contracts remain the sole key/event authority.
KEY_FIELDS = _field_union("natural_key_fields")
EVENT_TIME_FIELDS = _field_union("event_time_fields")


def natural_key(row: dict[str, Any], dataset_id: str) -> str:
    return _natural_key(row, dataset_id)


def pick_event_time(row: dict[str, Any], dataset_id: str) -> str | None:
    return event_time_for(row, dataset_id)


__all__ = ["EVENT_TIME_FIELDS", "KEY_FIELDS", "natural_key", "pick_event_time"]
