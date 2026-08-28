"""Closed StrategySpec builders. Equal-weight HOLD. Not GO."""
from __future__ import annotations

from strategies.spec import (
    CrossSectionRankRule,
    FeatureRef,
    REBALANCE_FIXED_HORIZON,
    STRATEGY_SPEC_VERSION,
    StrategySpec,
    ThresholdRule,
    TopKRule,
    ValueMomentumAgreeRule,
)

DEFAULT_MOMENTUM_FEATURE_VERSION: str = "1.0.0"
DEFAULT_DISCLOSURE_FEATURE_VERSION: str = "1.0.0"
DEFAULT_FUND_VALUE_FEATURE_VERSION: str = "1.0.0"
DEFAULT_TOP_K: int = 5
DEFAULT_CS_LONG_FRAC: float = 0.3
DEFAULT_CS_SHORT_FRAC: float = 0.3
DEFAULT_CS_MOMENTUM_N: int = 5  # hold=10 pin
DEFAULT_FUND_MOMENTUM_N: int = 10


def build_multi_day_hold_strategy_spec(
    *,
    hold_days: int = 10,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = 0.0,
    momentum_version: str = DEFAULT_MOMENTUM_FEATURE_VERSION,
    momentum_feature_id: str = "momentum_n",
    momentum_n: int | None = None,
    strategy_id: str | None = None,
    rationale: str = "",
    sticky: bool = True,
) -> StrategySpec:
    """Map multi_day_hold entry (momentum_n) into closed StrategySpec v3."""
    h = max(1, int(hold_days))
    n_mom = max(1, int(momentum_n if momentum_n is not None else h))
    sid = strategy_id or f"paper_mdh_hold{h}_momentum_topk"
    return StrategySpec(
        strategy_id=sid,
        version=STRATEGY_SPEC_VERSION,
        rule=TopKRule(
            feature=FeatureRef(
                id=str(momentum_feature_id),
                version=str(momentum_version),
                params={"n": n_mom},
            ),
            k=max(1, int(top_k)),
            min_score=float(min_score),
        ),
        rationale=rationale
        or f"Paper MDH hold={h}d mom_n={n_mom} top_k sticky. UNARMED.",
        rebalance=REBALANCE_FIXED_HORIZON if sticky and h > 1 else "daily",
        hold_days=h if sticky and h > 1 else None,
    )


def build_cross_section_hold_strategy_spec(
    *,
    hold_days: int = 10,
    momentum_n: int = DEFAULT_CS_MOMENTUM_N,
    long_frac: float = DEFAULT_CS_LONG_FRAC,
    short_frac: float = DEFAULT_CS_SHORT_FRAC,
    allow_short: bool = True,
    signal_sign: int = 1,
    momentum_version: str = DEFAULT_MOMENTUM_FEATURE_VERSION,
    momentum_feature_id: str = "momentum_n",
    strategy_id: str | None = None,
    rationale: str = "",
) -> StrategySpec:
    """CS sticky hold: rank L-S + fixed_horizon. ``signal_sign`` +1 / −1."""
    h = max(1, int(hold_days))
    n_mom = max(1, int(momentum_n))
    s_sign = int(signal_sign) if int(signal_sign) in (1, -1) else 1
    sid = strategy_id or f"paper_xs_hold{h}_mom{n_mom}_cs_rank"
    if s_sign == -1 and strategy_id is None:
        sid = f"{sid}_inv"
    return StrategySpec(
        strategy_id=sid,
        version=STRATEGY_SPEC_VERSION,
        rule=CrossSectionRankRule(
            feature=FeatureRef(
                id=str(momentum_feature_id),
                version=str(momentum_version),
                params={"n": n_mom},
            ),
            long_frac=float(long_frac),
            short_frac=float(short_frac),
            allow_short=bool(allow_short),
            signal_sign=s_sign,
        ),
        rationale=rationale
        or (
            f"Paper XS hold={h}d mom_n={n_mom} L-S "
            f"{long_frac}/{short_frac} sign={s_sign}. UNARMED."
        ),
        rebalance=REBALANCE_FIXED_HORIZON if h > 1 else "daily",
        hold_days=h if h > 1 else None,
    )


def build_fundamentals_hold_strategy_spec(
    *,
    hold_days: int = 10,
    momentum_n: int = DEFAULT_FUND_MOMENTUM_N,
    mode: str = "value_momentum_agree",
    allow_short: bool = True,
    signal_sign: int = 1,
    momentum_version: str = DEFAULT_MOMENTUM_FEATURE_VERSION,
    value_version: str = DEFAULT_FUND_VALUE_FEATURE_VERSION,
    momentum_feature_id: str = "momentum_n",
    value_feature_id: str = "fundamental_value_score",
    strategy_id: str | None = None,
    rationale: str = "",
) -> StrategySpec:
    """Fund path: value×mom agree + fixed_horizon. ``signal_sign`` +1 / −1."""
    h = max(1, int(hold_days))
    n_mom = max(1, int(momentum_n))
    s_sign = int(signal_sign) if int(signal_sign) in (1, -1) else 1
    sid = strategy_id or f"paper_fund_hold{h}_mom{n_mom}_value_mom"
    if s_sign == -1 and strategy_id is None:
        sid = f"{sid}_inv"
    return StrategySpec(
        strategy_id=sid,
        version=STRATEGY_SPEC_VERSION,
        rule=ValueMomentumAgreeRule(
            value_feature=FeatureRef(
                id=str(value_feature_id),
                version=str(value_version),
                params={},
            ),
            momentum_feature=FeatureRef(
                id=str(momentum_feature_id),
                version=str(momentum_version),
                params={"n": n_mom},
            ),
            mode=str(mode or "value_momentum_agree"),
            allow_short=bool(allow_short),
            signal_sign=s_sign,
        ),
        rationale=rationale
        or (
            f"Paper fund hold={h}d mom_n={n_mom} mode={mode} "
            f"sign={s_sign}. UNARMED."
        ),
        rebalance=REBALANCE_FIXED_HORIZON if h > 1 else "daily",
        hold_days=h if h > 1 else None,
    )


def build_event_post_strategy_spec(
    *,
    post_hold_days: int = 5,
    threshold: float = 0.5,
    disclosure_version: str = DEFAULT_DISCLOSURE_FEATURE_VERSION,
    strategy_id: str | None = None,
    rationale: str = "",
    sticky: bool = True,
) -> StrategySpec:
    """Map event_post into StrategySpec using disclosure_flag_fins (proxy)."""
    h = max(1, int(post_hold_days))
    sid = strategy_id or f"paper_event_post_hold{h}_disclosure_proxy"
    return StrategySpec(
        strategy_id=sid,
        version=STRATEGY_SPEC_VERSION,
        rule=ThresholdRule(
            feature=FeatureRef(
                id="disclosure_flag_fins",
                version=str(disclosure_version),
                params={},
            ),
            threshold=float(threshold),
        ),
        rationale=rationale
        or f"Paper event_post hold={h}d disclosure_flag proxy. UNARMED.",
        rebalance=REBALANCE_FIXED_HORIZON if sticky and h > 1 else "daily",
        hold_days=h if sticky and h > 1 else None,
    )
