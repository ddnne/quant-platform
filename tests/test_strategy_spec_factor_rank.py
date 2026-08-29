"""Focused tests for the closed StrategySpec v4 factor-rank rule."""

from __future__ import annotations

from types import SimpleNamespace

import core
import features
import pytest

from strategies.spec import (
    FactorRankRule,
    STRATEGY_SPEC_VERSION,
    STRATEGY_SPEC_VERSION_V4,
    StrategySpec,
    StrategySpecError,
    interpret_strategy_spec,
)
from strategies.spec.interpreter import _cross_section_rank_signs, _percentile_values
from research.factor_cohorts import (
    COMPACT_MARKET_COHORT_ID,
    personal_specs_for_cohort,
)


def _leg(feature_id: str, *, weight: float = 1.0, direction: str = "high_good"):
    params = {"n": 5} if feature_id == "momentum_n" else {}
    return {
        "feature": {"id": feature_id, "version": "1.0.0", "params": params},
        "weight": weight,
        "direction": direction,
    }


def _payload(
    *,
    legs=None,
    group: str = "market",
    min_eligible_ratio: float = 0.8,
    min_eligible_count: int = 3,
    min_group_count: int = 2,
):
    return {
        "version": STRATEGY_SPEC_VERSION_V4,
        "strategy_id": "bounded_factor_rank",
        "rebalance": "daily",
        "rule": {
            "type": "factor_rank",
            "legs": legs
            if legs is not None
            else [
                _leg("return_1d"),
                _leg("momentum_n", direction="low_good"),
            ],
            "normalization": "percentile",
            "group": group,
            "long_frac": 0.25,
            "short_frac": 0.25,
            "allow_short": True,
            "min_eligible_ratio": min_eligible_ratio,
            "min_eligible_count": min_eligible_count,
            "min_group_count": min_group_count,
        },
        "rationale": "closed ratio-factor fixture",
    }


def _master(code: str, *, sector: str, scale: str = "TOPIX Mid400"):
    return core.EquityMaster(
        code=code,
        snapshot_date="2025-04-01",
        company_name=f"Co-{code}",
        sector_17_code=None,
        sector_33_code=sector,
        market_code="0111",
        scale_category=scale,
    )


class _Context:
    def __init__(self, values, groups, *, positions=()):
        self.universe = tuple(sorted(groups))
        self.master = {
            code: _master(code, sector=sector, scale=scale)
            for code, (sector, scale) in groups.items()
        }
        self.positions = {code: SimpleNamespace() for code in positions}
        self._values = values

    def feature(self, feature_id, *, version=None, code=None, **_params):
        assert version == "1.0.0"
        return features.FeatureOutput(value=self._values[feature_id].get(code))


def test_factor_rank_v4_exact_round_trip_and_v3_default_is_stable():
    payload = _payload()
    spec = StrategySpec.from_dict(payload)

    assert isinstance(spec.rule, FactorRankRule)
    assert spec.to_dict() == payload
    assert STRATEGY_SPEC_VERSION == "strategy-spec/v3"

    v3 = {
        "version": "strategy-spec/v3",
        "strategy_id": "legacy_v3",
        "rebalance": "daily",
        "rule": {
            "type": "cross_section_rank",
            "feature": {
                "id": "return_1d",
                "version": "1.0.0",
                "params": {},
            },
            "long_frac": 0.3,
            "short_frac": 0.3,
            "allow_short": True,
        },
        "rationale": "unchanged",
    }
    assert StrategySpec.from_dict(v3).to_dict() == v3


def test_core30_market_cohort_can_form_a_non_flat_book() -> None:
    spec = personal_specs_for_cohort(
        COMPACT_MARKET_COHORT_ID, universe_id="topix_core30"
    )[0]
    codes = tuple(f"{index:04d}0" for index in range(1, 31))
    groups = {code: (f"S{index % 10}", "TOPIX Core30") for index, code in enumerate(codes)}
    values = {
        ref.id: {code: float(index + 1) for index, code in enumerate(codes)}
        for ref in (leg.feature for leg in spec.rule.legs)
    }

    strategy = interpret_strategy_spec(spec)
    intents = strategy.on_bar(_Context(values, groups))

    assert strategy.last_diagnostics["status"] == "passed"
    assert strategy.last_diagnostics["eligible_count"] == 30
    assert any(intent.target_weight > 0 for intent in intents)


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda body: body.update(version="strategy-spec/v3"), "requires strategy-spec/v4"),
        (
            lambda body: body["rule"].update(normalization="zscore"),
            "normalization must be percentile",
        ),
        (
            lambda body: body["rule"].update(legs=[]),
            "1..5 legs",
        ),
        (
            lambda body: body["rule"].update(legs=[_leg("return_1d", weight=0.0)]),
            "weight must be > 0",
        ),
        (
            lambda body: body["rule"].update(legs=[_leg("return_1d", weight=-1.0)]),
            "weight must be > 0",
        ),
        (
            lambda body: body["rule"].update(
                legs=[_leg("return_1d", weight=float("nan"))]
            ),
            "weight must be finite",
        ),
        (
            lambda body: body["rule"]["legs"][0].update(direction="formula"),
            "high_good\\|low_good",
        ),
        (
            lambda body: body["rule"].update(formula="eval(x)"),
            "unknown factor_rank rule field",
        ),
    ],
)
def test_factor_rank_rejects_open_or_invalid_contracts(mutate, match):
    payload = _payload()
    mutate(payload)
    with pytest.raises(StrategySpecError, match=match):
        StrategySpec.from_dict(payload)


def test_sector_factor_rank_is_group_relative_and_all_equal_is_flat():
    groups = {
        "A": ("S1", "Large"),
        "B": ("S1", "Large"),
        "C": ("S1", "Small"),
        "D": ("S2", "Large"),
        "E": ("S2", "Small"),
        "F": ("S2", "Small"),
    }
    # Equal raw values must stay equal after percentile normalization and must
    # not turn the ticker spelling into a trading signal.
    values = {
        "return_1d": {code: 1.0 for code in groups},
    }
    payload = _payload(
        legs=[_leg("return_1d")],
        group="sector33",
        min_eligible_ratio=1.0,
        min_eligible_count=6,
        min_group_count=3,
    )
    strategy = interpret_strategy_spec(payload)
    context = _Context(values, groups)
    intents = {
        intent.code: intent.target_weight for intent in strategy.on_bar(context)
    }

    reverse_strategy = interpret_strategy_spec(payload)
    reverse_context = _Context(values, groups)
    reverse_context.universe = tuple(reversed(reverse_context.universe))
    reverse_intents = {
        intent.code: intent.target_weight
        for intent in reverse_strategy.on_bar(reverse_context)
    }

    assert reverse_intents == intents
    assert intents == {code: 0.0 for code in groups}
    assert strategy.last_diagnostics["status"] == "passed"
    assert strategy.last_diagnostics["composite_min"] == 0.5
    assert strategy.last_diagnostics["composite_max"] == 0.5
    assert strategy.last_diagnostics["group_counts"] == {
        "S1": {"universe": 3, "eligible": 3, "eligible_ratio": 1.0},
        "S2": {"universe": 3, "eligible": 3, "eligible_ratio": 1.0},
    }


def test_percentile_ties_receive_the_same_average_rank():
    forward = _percentile_values(
        {"A": 1.0, "B": 1.0, "C": 2.0}, direction="high_good"
    )
    reverse = _percentile_values(
        {"C": 2.0, "B": 1.0, "A": 1.0}, direction="high_good"
    )

    assert forward == reverse == {"A": 0.25, "B": 0.25, "C": 1.0}
    assert _percentile_values(
        {"A": 1.0, "B": 1.0, "C": 2.0}, direction="low_good"
    ) == {"A": 0.75, "B": 0.75, "C": 0.0}


def test_factor_rank_cutoff_ties_are_included_without_code_order_signal():
    forward = _cross_section_rank_signs(
        [("A", 2.0), ("B", 2.0), ("C", 1.0), ("D", 0.0)],
        long_frac=0.25,
        short_frac=0.25,
        allow_short=True,
        neutralize_cutoff_ties=True,
    )
    reverse = _cross_section_rank_signs(
        [("D", 0.0), ("C", 1.0), ("B", 2.0), ("A", 2.0)],
        long_frac=0.25,
        short_frac=0.25,
        allow_short=True,
        neutralize_cutoff_ties=True,
    )

    assert forward == reverse == {"A": 1.0, "B": 1.0, "C": 0.0, "D": -1.0}


def test_missing_any_leg_excludes_code_and_flattens_that_position():
    groups = {code: ("S1", "Large") for code in ("A", "B", "C", "D")}
    values = {
        "return_1d": {code: float(index) for index, code in enumerate(groups)},
        "momentum_n": {"A": 1.0, "C": 1.0, "D": 1.0},
    }
    strategy = interpret_strategy_spec(
        _payload(
            min_eligible_ratio=0.5,
            min_eligible_count=1,
            min_group_count=1,
        )
    )

    intents = {intent.code: intent.target_weight for intent in strategy.on_bar(
        _Context(values, groups, positions=("B",))
    )}

    assert strategy.last_diagnostics["status"] == "passed"
    assert strategy.last_diagnostics["eligible_count"] == 3
    assert intents["B"] == 0.0


def test_global_coverage_failure_flattens_every_existing_position():
    groups = {code: ("S1", "Large") for code in ("A", "B", "C", "D")}
    values = {
        "return_1d": {code: 1.0 for code in groups},
        "momentum_n": {"A": 1.0, "C": 1.0, "D": 1.0},
    }
    strategy = interpret_strategy_spec(
        _payload(
            min_eligible_ratio=1.0,
            min_eligible_count=4,
            min_group_count=1,
        )
    )

    intents = strategy.on_bar(_Context(values, groups, positions=("A", "ZZ")))

    assert [(intent.code, intent.target_weight) for intent in intents] == [
        ("A", 0.0),
        ("ZZ", 0.0),
    ]
    assert strategy.last_diagnostics["status"] == "flattened"
    assert set(strategy.last_diagnostics["reason_codes"]) == {
        "eligible_count_below_floor",
        "eligible_ratio_below_floor",
        "group_coverage_below_floor",
    }


def test_genuinely_small_group_is_excluded_without_flattening_valid_groups():
    groups = {
        "A": ("S1", "Large"),
        "B": ("S1", "Large"),
        "C": ("S1", "Large"),
        "D": ("S2", "Small"),
        "E": ("S2", "Small"),
    }
    values = {
        "return_1d": {code: 1.0 for code in groups},
        "momentum_n": {code: 1.0 for code in groups},
    }
    strategy = interpret_strategy_spec(
        _payload(
            group="sector33",
            min_eligible_ratio=1.0,
            min_eligible_count=3,
            min_group_count=3,
        )
    )

    intents = strategy.on_bar(_Context(values, groups, positions=("D",)))

    assert all(intent.target_weight == 0.0 for intent in intents)
    assert strategy.last_diagnostics["status"] == "passed"
    assert strategy.last_diagnostics["failed_groups"] == ()
    assert strategy.last_diagnostics["excluded_small_groups"] == ("S2",)


def test_large_group_with_sparse_features_flattens_entire_book():
    groups = {code: ("S1", "Large") for code in ("A", "B", "C", "D", "E")}
    values = {
        "return_1d": {code: 1.0 for code in groups},
        "momentum_n": {"A": 1.0, "B": 1.0, "C": 1.0},
    }
    strategy = interpret_strategy_spec(
        _payload(
            group="sector33",
            min_eligible_ratio=0.8,
            min_eligible_count=3,
            min_group_count=3,
        )
    )

    intents = strategy.on_bar(_Context(values, groups, positions=("A",)))

    assert [(intent.code, intent.target_weight) for intent in intents] == [
        ("A", 0.0)
    ]
    assert strategy.last_diagnostics["status"] == "flattened"
    assert strategy.last_diagnostics["failed_groups"] == ("S1",)
    assert "group_coverage_below_floor" in strategy.last_diagnostics[
        "reason_codes"
    ]


def test_missing_group_labels_are_measured_against_the_whole_pit_universe():
    groups = {
        **{f"M{index}": (None, "Large") for index in range(100)},
        **{f"S{index}": ("S1", "Large") for index in range(10)},
    }
    values = {
        "return_1d": {code: 1.0 for code in groups},
        "momentum_n": {code: 1.0 for code in groups},
    }
    strategy = interpret_strategy_spec(
        _payload(
            group="sector33",
            min_eligible_ratio=0.8,
            min_eligible_count=3,
            min_group_count=3,
        )
    )

    intents = strategy.on_bar(_Context(values, groups, positions=("S0",)))

    assert [(intent.code, intent.target_weight) for intent in intents] == [
        ("S0", 0.0)
    ]
    assert strategy.last_diagnostics["status"] == "flattened"
    assert strategy.last_diagnostics["missing_group_count"] == 100
    assert strategy.last_diagnostics["group_label_count"] == 10
    assert strategy.last_diagnostics["group_label_ratio"] == pytest.approx(10 / 110)
    assert "group_label_coverage_below_floor" in strategy.last_diagnostics[
        "reason_codes"
    ]
