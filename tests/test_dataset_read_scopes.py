"""Closed dataset read-scope declarations and scope-enabled metadata digest."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

import features
from data_contracts.read_scopes import (
    DatasetReadScope,
    VisibleObservationCount,
    resolve_dataset_read_scopes,
)
from features.complete21_min_parsers import _latest_fins_per_share_observation
from features.registry import FEATURE_DEFINITION_METADATA_V2

_SCOPED_IDS = (
    "retrospective_split_adjusted_momentum_n",
    "disclosure_flag_fins",
    "retrospective_split_safe_fundamental_value_score",
)


def _bars_scope(**overrides) -> DatasetReadScope:
    payload = {
        "dataset_id": "equities_bars_daily",
        "observation_count": VisibleObservationCount.named_integer_input_plus(
            "n", add=1
        ),
        "fields": ("adjustment_close", "date"),
    }
    payload.update(overrides)
    return DatasetReadScope(**payload)


def _definition(**overrides) -> features.FeatureDefinition:
    payload = {
        "id": "scoped_fixture",
        "version": features.FeatureVersion(1, 0, 0),
        "inputs": features.FeatureInput(
            required_kwargs=("code",),
            optional_kwargs={"n": 20},
        ),
        "description": "fixture",
        "compute": lambda ctx: features.FeatureOutput(value=None),
        "intended_role": "utility",
        "dataset_dependencies": ("equities_bars_daily",),
        "read_scopes": (_bars_scope(),),
    }
    payload.update(overrides)
    return features.FeatureDefinition(**payload)


def test_dataset_read_scope_is_frozen_and_rejects_malformed_values() -> None:
    scope = _bars_scope()
    with pytest.raises(FrozenInstanceError):
        scope.dataset_id = "fins_summary"  # type: ignore[misc]
    with pytest.raises(ValueError, match="unsupported fields"):
        DatasetReadScope.from_mapping(
            {
                "dataset_id": "equities_bars_daily",
                "fields": ["adjustment_close"],
                "sql": "select 1",
            }
        )
    with pytest.raises(ValueError, match="must be an integer"):
        VisibleObservationCount.literal(True)
    with pytest.raises(ValueError, match="must be an integer"):
        VisibleObservationCount.named_integer_input_plus("n", add=True)
    with pytest.raises(ValueError, match="must be >= 1"):
        VisibleObservationCount.literal(0)
    with pytest.raises(ValueError, match="duplicates"):
        _bars_scope(fields=("adjustment_close", "adjustment_close"))
    with pytest.raises(ValueError, match="unsupported canonical field"):
        _bars_scope(fields=("MAdjC",))
    with pytest.raises(ValueError, match="unsupported canonical field"):
        _bars_scope(fields=("split_adjustment_factor",))
    with pytest.raises(ValueError, match="unsupported canonical field"):
        _bars_scope(fields=("volume",))
    with pytest.raises(ValueError, match="unsupported initial_visible_state"):
        DatasetReadScope(
            dataset_id="fins_summary",
            initial_visible_state="current_day_event",
        )
    with pytest.raises(ValueError, match="duplicate dataset read scope"):
        _definition(read_scopes=(_bars_scope(), _bars_scope()))
    with pytest.raises(ValueError, match="among dataset_dependencies"):
        _definition(
            dataset_dependencies=("fins_summary",),
            read_scopes=(_bars_scope(),),
        )
    with pytest.raises(ValueError, match="unknown feature inputs"):
        _definition(
            inputs=features.FeatureInput(required_kwargs=("code",)),
            read_scopes=(_bars_scope(),),
        )


def test_named_integer_input_resolves_to_n_plus_one() -> None:
    momentum = features.get(
        "retrospective_split_adjusted_momentum_n", version="1.0.0"
    )
    assert momentum.inputs.optional_kwargs == {"n": 20}
    count = momentum.read_scopes[0].observation_count
    assert count is not None
    assert count.canonical_mapping() == {
        "kind": "named_integer_input_plus",
        "input_name": "n",
        "add": 1,
    }
    assert momentum.read_scopes[0].fields == ("adjustment_close", "date")
    assert "close" not in momentum.read_scopes[0].fields
    resolved = resolve_dataset_read_scopes(momentum.read_scopes, {"n": 20})
    assert len(resolved) == 1
    assert resolved[0].observation_count == VisibleObservationCount.literal(21)
    with pytest.raises(ValueError, match="missing effective input 'n'"):
        resolve_dataset_read_scopes(momentum.read_scopes, {})
    with pytest.raises(ValueError, match="must be an integer"):
        resolve_dataset_read_scopes(momentum.read_scopes, {"n": 20.0})
    with pytest.raises(ValueError, match="must be an integer"):
        resolve_dataset_read_scopes(momentum.read_scopes, {"n": True})


def test_financial_semantics_match_existing_compute_and_am_volume_projection() -> None:
    disclosure = features.get("disclosure_flag_fins", version="1.0.0")
    assert disclosure.inputs.required_kwargs == ("code",)
    assert disclosure.inputs.optional_kwargs == {}
    disc = disclosure.read_scopes[0]
    assert disc.dataset_id == "fins_summary"
    assert disc.initial_visible_state == "all_visible_existence_and_count"
    assert disc.observation_count is None
    assert disc.fields == ()

    fund = features.get(
        "retrospective_split_safe_fundamental_value_score", version="1.0.0"
    )
    by_dataset = {scope.dataset_id: scope for scope in fund.read_scopes}
    bars = by_dataset["equities_bars_daily"]
    fins = by_dataset["fins_summary"]
    assert bars.observation_count == VisibleObservationCount.literal(1)
    assert bars.split_safety_anchor_interval is True
    assert bars.fields == ("adjustment_close", "close", "date")
    assert bars.optional_fields == ("adjustment_volume", "volume")
    assert fins.initial_visible_state == "latest_qualifying_bps_preferred_else_eps"
    assert fins.fields == ("payload", "raw_payload")
    master = DatasetReadScope(
        dataset_id="equities_master",
        initial_visible_state="latest_complete_snapshot_plus_updates",
        fields=("snapshot_date",),
    )
    calendar = DatasetReadScope(
        dataset_id="markets_calendar",
        fields=("date", "holiday_division"),
    )
    assert DatasetReadScope.from_mapping(master.canonical_mapping()) == master
    assert DatasetReadScope.from_mapping(calendar.canonical_mapping()) == calendar


def test_declared_fins_catalog_fields_preserve_parser_selection() -> None:
    fund = features.get(
        "retrospective_split_safe_fundamental_value_score", version="1.0.0"
    )
    fins = next(
        scope for scope in fund.read_scopes if scope.dataset_id == "fins_summary"
    )
    rows = [
        {
            "payload": {
                "BPS": 250.0,
                "CurPerEn": "2022-12-31",
                "DiscDate": "2023-02-15",
            },
            "raw_payload": {"Note": "kept only as complete catalog object"},
        },
        {"payload": {"EPS": 12.0, "CurrentPeriodEndDate": "2023-06-30"}},
        {"payload": {"NetSales": 1.0}, "raw_payload": {}},
    ]
    projected = [
        {field: row[field] for field in fins.fields if field in row} for row in rows
    ]
    expected = _latest_fins_per_share_observation(rows)
    observed = _latest_fins_per_share_observation(projected)
    assert expected is not None and observed is not None
    assert observed["bps"] == expected["bps"] == 250.0
    assert observed["split_safety_anchor"] == expected["split_safety_anchor"] == (
        "2022-12-31"
    )
    assert observed["fins_rows"] == expected["fins_rows"] == 3


def test_scope_values_round_trip_canonical_mapping() -> None:
    named = VisibleObservationCount.named_integer_input_plus("n", add=1)
    literal = VisibleObservationCount.literal(21)
    assert VisibleObservationCount.from_mapping(named.canonical_mapping()) == named
    assert VisibleObservationCount.from_mapping(literal.canonical_mapping()) == literal
    for feature_id in _SCOPED_IDS:
        definition = features.get(feature_id, version="1.0.0")
        for scope in definition.read_scopes:
            assert DatasetReadScope.from_mapping(scope.canonical_mapping()) == scope


def test_scope_enabled_digest_binds_requirements_and_rejects_incomplete() -> None:
    momentum = features.get(
        "retrospective_split_adjusted_momentum_n", version="1.0.0"
    )
    v1 = features.feature_definition_digest(momentum)
    v2 = features.feature_definition_digest(momentum, metadata_version="v2")
    assert v1 != v2
    assert v2 == features.feature_definition_digest(
        momentum, metadata_version=FEATURE_DEFINITION_METADATA_V2
    )
    widened = replace(
        momentum,
        read_scopes=(
            replace(
                momentum.read_scopes[0],
                fields=("adjustment_close", "close", "date"),
            ),
        ),
    )
    assert features.feature_definition_digest(widened) == v1
    assert features.feature_definition_digest(widened, metadata_version="v2") != v2
    unscoped = features.get("return_1d", version="1.0.0")
    assert unscoped.read_scopes == ()
    with pytest.raises(ValueError, match="requires declared read scopes"):
        features.feature_definition_digest(unscoped, metadata_version="v2")
    partial = _definition(
        dataset_dependencies=("equities_bars_daily", "fins_summary"),
        read_scopes=(_bars_scope(),),
    )
    assert partial.read_scopes
    with pytest.raises(ValueError, match="missing per-dataset read scope"):
        features.feature_definition_digest(partial, metadata_version="v2")
