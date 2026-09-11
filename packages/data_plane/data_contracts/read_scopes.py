"""Closed dataset read-scope values for versioned feature metadata.

This versioned contract is through the bound decision-visible view. Prior
rows keep the existing daily projection; the decision-day row is the
existing AM allowlist. Decision-day ``volume`` is intentionally absent and
``adjustment_volume`` may be morning-only. Do not fill that absence from
full-day Volume. Split safety uses ``adjustment_close / close`` and optional
corroboration ``adjustment_volume / volume``.

``VisibleObservationCount`` is the latest decision-visible
``(code, event-date)`` rows in existing canonical revision/order, selected
independently of quote validity. Missing raw or adjusted prices do not skip
to older priced rows. Feature None/reject outcomes stay in compute.

Financial ``latest_qualifying_bps_preferred_else_eps`` keeps the existing
payload-then-raw_payload parse, alias priority, BPS preference, and count of
all nonempty parsed payloads. Catalog fields are ``payload`` and
``raw_payload``; neither must be independently non-null.

Pure values only: no SQL, clocks, readers, parameter-name scanning, or
expression evaluation. These declarations do not themselves enforce reader
behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence


READ_SCOPE_CONTRACT = "dataset-read-scope/v1"
THROUGH_BOUND_DECISION_VISIBLE_VIEW = "bound_decision_visible_view"

_COUNT_KINDS = frozenset({"literal", "named_integer_input_plus"})
_INITIAL_STATES = frozenset(
    {
        "all_visible_existence_and_count",
        "latest_qualifying_bps_preferred_else_eps",
        "latest_complete_snapshot_plus_updates",
    }
)
_REQUIRED_FIELDS = frozenset(
    {
        "date",
        "close",
        "adjustment_close",
        "payload",
        "raw_payload",
        "holiday_division",
        "snapshot_date",
        "code",
        "market_code",
        "scale_category",
    }
)
_OPTIONAL_FIELDS = frozenset({"volume", "adjustment_volume"})
_COUNT_LITERAL_KEYS = frozenset({"kind", "value"})
_COUNT_NAMED_KEYS = frozenset({"kind", "input_name", "add"})
_SCOPE_KEYS = frozenset(
    {
        "dataset_id",
        "observation_count",
        "initial_visible_state",
        "split_safety_anchor_interval",
        "fields",
        "optional_fields",
        "unconsumed_membership",
    }
)


def _strict_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return value


def _strict_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a bool")
    return value


def _closed_text(value: Any, allowed: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    text = value.strip()
    if text not in allowed:
        raise ValueError(f"unsupported {label}: {text!r}")
    return text


def _mapping(value: Any, allowed: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be an object")
    extra = sorted(str(key) for key in value if key not in allowed)
    if extra:
        raise ValueError(f"{label} has unsupported fields: {extra}")
    return value


def _unique_fields(value: Any, allowed: frozenset[str], label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be an array of field ids")
    fields = tuple(_closed_text(item, allowed, "canonical field") for item in value)
    if len(fields) != len(set(fields)):
        raise ValueError(f"{label} cannot contain duplicates")
    return tuple(sorted(fields))


@dataclass(frozen=True, slots=True)
class VisibleObservationCount:
    """Visible-row count: a literal, or one named integer input plus addend.

    Counts latest decision-visible ``(code, event-date)`` rows in existing
    canonical revision/order, independent of quote validity.
    """

    kind: str
    value: int | None = None
    input_name: str | None = None
    add: int | None = None

    def __post_init__(self) -> None:
        kind = _closed_text(self.kind, _COUNT_KINDS, "observation count kind")
        object.__setattr__(self, "kind", kind)
        if kind == "literal":
            if self.input_name is not None or self.add is not None:
                raise ValueError("literal observation count cannot name an input")
            object.__setattr__(
                self, "value", _strict_int(self.value, "observation count", minimum=1)
            )
            return
        if self.value is not None:
            raise ValueError("named observation count cannot include a literal value")
        if not isinstance(self.input_name, str) or not self.input_name.strip():
            raise ValueError("named observation count requires input_name")
        object.__setattr__(self, "input_name", self.input_name.strip())
        object.__setattr__(
            self, "add", _strict_int(self.add, "observation count addend", minimum=0)
        )

    @classmethod
    def literal(cls, value: Any) -> "VisibleObservationCount":
        return cls(kind="literal", value=value)

    @classmethod
    def named_integer_input_plus(
        cls, input_name: Any, *, add: Any
    ) -> "VisibleObservationCount":
        return cls(kind="named_integer_input_plus", input_name=input_name, add=add)

    @classmethod
    def from_mapping(cls, raw: Any) -> "VisibleObservationCount":
        mapping = _mapping(raw, _COUNT_LITERAL_KEYS | _COUNT_NAMED_KEYS, "observation count")
        kind = mapping.get("kind")
        if kind == "literal":
            _mapping(mapping, _COUNT_LITERAL_KEYS, "observation count")
            return cls.literal(mapping.get("value"))
        if kind == "named_integer_input_plus":
            _mapping(mapping, _COUNT_NAMED_KEYS, "observation count")
            return cls.named_integer_input_plus(
                mapping.get("input_name"), add=mapping.get("add")
            )
        raise ValueError(f"unsupported observation count kind: {kind!r}")

    def resolve(self, effective_inputs: Mapping[str, Any]) -> "VisibleObservationCount":
        if self.kind == "literal":
            return self
        name = self.input_name
        assert name is not None and self.add is not None
        if name not in effective_inputs:
            raise ValueError(f"missing effective input {name!r}")
        base = _strict_int(
            effective_inputs[name], f"effective input {name!r}", minimum=1
        )
        return self.literal(base + self.add)

    def canonical_mapping(self) -> dict[str, Any]:
        if self.kind == "literal":
            return {"kind": self.kind, "value": self.value}
        return {"kind": self.kind, "input_name": self.input_name, "add": self.add}


@dataclass(frozen=True, slots=True)
class DatasetReadScope:
    """Declared read needs for one dataset of one feature version."""

    dataset_id: str
    observation_count: VisibleObservationCount | None = None
    initial_visible_state: str | None = None
    split_safety_anchor_interval: bool = False
    fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    unconsumed_membership: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_id, str) or not self.dataset_id.strip():
            raise ValueError("dataset_id must be a non-empty string")
        object.__setattr__(self, "dataset_id", self.dataset_id.strip())
        count = self.observation_count
        if count is not None and not isinstance(count, VisibleObservationCount):
            raise ValueError("observation_count is malformed")
        state = self.initial_visible_state
        if state is not None:
            object.__setattr__(
                self,
                "initial_visible_state",
                _closed_text(state, _INITIAL_STATES, "initial_visible_state"),
            )
        object.__setattr__(
            self,
            "split_safety_anchor_interval",
            _strict_bool(
                self.split_safety_anchor_interval, "split_safety_anchor_interval"
            ),
        )
        fields = _unique_fields(self.fields, _REQUIRED_FIELDS, "fields")
        optional = _unique_fields(
            self.optional_fields, _OPTIONAL_FIELDS, "optional_fields"
        )
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "optional_fields", optional)
        object.__setattr__(
            self,
            "unconsumed_membership",
            _strict_bool(self.unconsumed_membership, "unconsumed_membership"),
        )
        if self.unconsumed_membership and (
            count is not None
            or self.initial_visible_state is not None
            or self.split_safety_anchor_interval
            or fields
            or optional
        ):
            raise ValueError("unconsumed membership cannot declare a read need")
        if (
            count is None
            and self.initial_visible_state is None
            and not self.split_safety_anchor_interval
            and not fields
            and not optional
            and not self.unconsumed_membership
        ):
            raise ValueError("dataset read scope must declare at least one need")

    @classmethod
    def from_mapping(cls, raw: Any) -> "DatasetReadScope":
        mapping = _mapping(raw, _SCOPE_KEYS, "dataset read scope")
        count_raw = mapping.get("observation_count")
        return cls(
            dataset_id=mapping.get("dataset_id"),
            observation_count=(
                None
                if count_raw is None
                else VisibleObservationCount.from_mapping(count_raw)
            ),
            initial_visible_state=mapping.get("initial_visible_state"),
            split_safety_anchor_interval=mapping.get(
                "split_safety_anchor_interval", False
            ),
            fields=mapping.get("fields", ()),
            optional_fields=mapping.get("optional_fields", ()),
            unconsumed_membership=mapping.get("unconsumed_membership", False),
        )

    def referenced_input_names(self) -> tuple[str, ...]:
        count = self.observation_count
        if count is None or count.input_name is None:
            return ()
        return (count.input_name,)

    def resolve(self, effective_inputs: Mapping[str, Any]) -> "DatasetReadScope":
        count = self.observation_count
        if count is None:
            return self
        resolved = count.resolve(effective_inputs)
        if resolved is count:
            return self
        return replace(self, observation_count=resolved)

    def canonical_mapping(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "fields": list(self.fields),
            "initial_visible_state": self.initial_visible_state,
            "observation_count": (
                None
                if self.observation_count is None
                else self.observation_count.canonical_mapping()
            ),
            "optional_fields": list(self.optional_fields),
            "split_safety_anchor_interval": self.split_safety_anchor_interval,
            "unconsumed_membership": self.unconsumed_membership,
        }


def normalize_dataset_read_scopes(value: Any) -> tuple[DatasetReadScope, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("read_scopes must be an array of dataset read scopes")
    scopes: list[DatasetReadScope] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, DatasetReadScope):
            raise ValueError("read_scopes entries must be DatasetReadScope values")
        if item.dataset_id in seen:
            raise ValueError(f"duplicate dataset read scope for {item.dataset_id!r}")
        seen.add(item.dataset_id)
        scopes.append(item)
    return tuple(sorted(scopes, key=lambda scope: scope.dataset_id))


def referenced_read_scope_inputs(scopes: Sequence[DatasetReadScope]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for scope in scopes:
        for name in scope.referenced_input_names():
            if name not in seen:
                seen.add(name)
                names.append(name)
    return tuple(names)


def require_complete_feature_read_scopes(
    dataset_dependencies: Sequence[str],
    read_scopes: Sequence[DatasetReadScope],
) -> None:
    if not read_scopes:
        raise ValueError("scope-enabled feature metadata requires declared read scopes")
    declared = {scope.dataset_id for scope in read_scopes}
    missing = [
        dataset_id
        for dataset_id in dataset_dependencies
        if dataset_id not in declared
    ]
    if missing:
        raise ValueError(f"missing per-dataset read scope for {missing}")


def resolve_dataset_read_scopes(
    scopes: Sequence[DatasetReadScope],
    effective_inputs: Mapping[str, Any],
) -> tuple[DatasetReadScope, ...]:
    """Replace named counts with validated literal counts in the same shape."""
    if not isinstance(effective_inputs, Mapping) or isinstance(
        effective_inputs, (str, bytes)
    ):
        raise ValueError("effective_inputs must be an object")
    return tuple(
        scope.resolve(effective_inputs)
        for scope in normalize_dataset_read_scopes(scopes)
    )


def feature_read_scopes_payload(
    scopes: Sequence[DatasetReadScope],
) -> dict[str, Any]:
    return {
        "contract": READ_SCOPE_CONTRACT,
        "datasets": [scope.canonical_mapping() for scope in scopes],
        "through": THROUGH_BOUND_DECISION_VISIBLE_VIEW,
    }


__all__ = [
    "DatasetReadScope",
    "VisibleObservationCount",
    "READ_SCOPE_CONTRACT",
    "THROUGH_BOUND_DECISION_VISIBLE_VIEW",
    "feature_read_scopes_payload",
    "normalize_dataset_read_scopes",
    "referenced_read_scope_inputs",
    "require_complete_feature_read_scopes",
    "resolve_dataset_read_scopes",
]
