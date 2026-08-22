"""UNARMED paper receptacle: class_hyp / research candidate → StrategySpec.

Closed envelope with nested StrategySpec plus horizon / costs / universe /
rebalance. Does not arm the paper scheduler, call ``run_paper``, or touch
the live order path. Mass NO-GO · Phase7 OFF · READY undeclared · GO closed.
``research_candidate`` is never auto-promoted. Hostile arm/live/go input is
stripped. Residuals (portfolio MTM vs trade-level mean; no short-margin
model) stay on the envelope. Do not simplify research.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

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

from research.freezes import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    EDGE_CLAIMED,
    LIVE_ORDER_PATH_ENABLED,
    LIVE_ORDERS,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PAPER_CONTINUOUS,
    PAPER_SCHEDULER_ARMED,
    PHASE7,
    READY_DECLARED,
    S1_S5_UNREJECT,
    SIGNIFICANCE_CLAIMED,
)
from research.hypothesis_classes import (
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_EVENT_POST,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MULTI_DAY_HOLD,
    get_hypothesis_class,
)

# ---------------------------------------------------------------------------
# Identity / freeze (must never arm)
# ---------------------------------------------------------------------------

PAPER_CANDIDATE_SPEC_VERSION: str = "paper-candidate-spec/v1"
PAPER_CANDIDATE_ADAPTER_VERSION: str = "paper-candidate-adapter/v2"
PAPER_CANDIDATE_WAVE: str = "W86 / w0816u"

DEFAULT_ONE_WAY_COST: float = 0.001  # 10bp
DEFAULT_MOMENTUM_FEATURE_VERSION: str = "1.0.0"
DEFAULT_DISCLOSURE_FEATURE_VERSION: str = "1.0.0"
DEFAULT_FUND_VALUE_FEATURE_VERSION: str = "1.0.0"
DEFAULT_TOP_K: int = 5
DEFAULT_LOOKBACK_DAYS: int = 30
DEFAULT_CS_LONG_FRAC: float = 0.3
DEFAULT_CS_SHORT_FRAC: float = 0.3
DEFAULT_CS_MOMENTUM_N: int = 5  # W82 pin for hold=10
DEFAULT_FUND_MOMENTUM_N: int = 10

# Boolean keys that must be False on adapter output (never arm / live / go).
_ARM_BOOL_FALSE_KEYS: tuple[str, ...] = (
    "paper_scheduler_armed",
    "paper_continuous",
    "live_orders",
    "live_order_path_enabled",
    "live_order_path",
    "ready_declared",
    "operational_go",
    "connected_to_ready",
    "connected_to_mass",
    "significance_claimed",
    "edge_claimed",
    "s1_s5_unreject",
    "research_candidate",  # never auto-promote
    "armed",
    "go",
)


def _freeze_arm_flags() -> dict[str, Any]:
    """Canonical unarmed surface. Callers cannot override these open."""
    return {
        "paper_scheduler_armed": False,
        "paper_continuous": False,
        "live_orders": False,
        "live_order_path_enabled": False,
        "live_order_path": False,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "edge_claimed": EDGE_CLAIMED,
        "s1_s5_unreject": S1_S5_UNREJECT,
        "research_candidate": False,
    }


def _assert_closed_flags(block: Mapping[str, Any], *, where: str) -> None:
    """Validate one flag surface (top-level or arm.*)."""
    prefix = f"{where}." if where else ""
    for key in _ARM_BOOL_FALSE_KEYS:
        if key not in block:
            continue
        val = block[key]
        if val not in (False, 0, None):
            raise ValueError(
                f"paper receptacle must stay unarmed: {prefix}{key}={val!r}"
            )
    if "mass_research" in block and block["mass_research"] not in (
        MASS_RESEARCH,
        "NO-GO",
        None,
    ):
        raise ValueError(
            f"mass_research must be NO-GO, got {block['mass_research']!r}"
        )
    if "phase7" in block and block["phase7"] not in (PHASE7, "OFF", None):
        raise ValueError(f"phase7 must be OFF, got {block['phase7']!r}")


def assert_unarmed(payload: Mapping[str, Any]) -> None:
    """Fail closed if a paper receptacle claims arm / live / GO."""
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    arm = payload.get("arm")
    if isinstance(arm, Mapping):
        _assert_closed_flags(arm, where="arm")
    elif arm is not None:
        raise ValueError(f"paper receptacle arm must be object or absent, got {arm!r}")
    _assert_closed_flags(payload, where="")
    status = str(payload.get("status") or "")
    if status in {"armed", "live", "go", "paper_armed", "scheduler_armed"}:
        raise ValueError(f"paper receptacle status must not arm: {status!r}")


# ---------------------------------------------------------------------------
# Costs / horizon helpers
# ---------------------------------------------------------------------------


def _one_way_cost_from_payload(payload: Mapping[str, Any]) -> float:
    cost_block = payload.get("cost_assumption") or payload.get("costs") or {}
    if isinstance(cost_block, Mapping):
        tx = cost_block.get("transaction")
        if isinstance(tx, Mapping):
            for key in ("one_way_cost", "one_way", "cost"):
                if tx.get(key) is not None:
                    return float(tx[key])
            if tx.get("one_way_cost_bp") is not None:
                return float(tx["one_way_cost_bp"]) / 10_000.0
            if tx.get("bp") is not None:
                return float(tx["bp"]) / 10_000.0
        for key in ("one_way_cost", "one_way"):
            if cost_block.get(key) is not None:
                return float(cost_block[key])
        if cost_block.get("one_way_cost_bp") is not None:
            return float(cost_block["one_way_cost_bp"]) / 10_000.0
    if payload.get("one_way_cost") is not None:
        return float(payload["one_way_cost"])
    if payload.get("one_way_cost_bp") is not None:
        return float(payload["one_way_cost_bp"]) / 10_000.0
    return DEFAULT_ONE_WAY_COST


def _hold_days_from_payload(
    payload: Mapping[str, Any],
    *,
    default: int,
    class_id: str,
) -> int:
    for key in ("hold_days", "post_hold_days", "horizon_days"):
        if payload.get(key) is not None:
            return max(1, int(payload[key]))
    variant = str(payload.get("variant") or "")
    if "hold_10" in variant or variant.endswith("_10") or variant == "10d":
        return 10
    if "hold_20" in variant:
        return 20
    if "hold_5" in variant:
        return 5
    horizon = str(payload.get("horizon") or "")
    for token in ("20d", "10d", "5d"):
        if token in horizon:
            return int(token.replace("d", ""))
    # class_hyp multi_day_hold_10 style keys
    cid = str(payload.get("hypothesis_class") or class_id)
    if cid == CLASS_MULTI_DAY_HOLD and "10" in str(payload.get("label") or ""):
        return 10
    return max(1, int(default))


def _universe_from_payload(
    payload: Mapping[str, Any],
    *,
    class_id: str,
) -> list[str]:
    if payload.get("universe") is not None:
        u = payload["universe"]
        if isinstance(u, (list, tuple)):
            return [str(x) for x in u if str(x).strip()]
        if isinstance(u, str) and u.strip():
            return [u.strip()]
    codes = payload.get("codes")
    if isinstance(codes, (list, tuple)) and codes:
        return [str(c).strip() for c in codes if str(c).strip()]
    try:
        spec = get_hypothesis_class(class_id)
        return list(spec.universe)
    except KeyError:
        return ["tse_prime_liquid"]


def _source_candidate_block(payload: Mapping[str, Any]) -> dict[str, Any]:
    cand = payload.get("candidate")
    if not isinstance(cand, Mapping):
        cand = {}
    summary = payload.get("candidate_summary")
    if not isinstance(summary, Mapping):
        summary = {}
    return {
        "research_candidate": False,  # never promote
        "research_candidate_allowed": bool(
            cand.get("research_candidate_allowed", summary.get("research_candidate_allowed", False))
        ),
        "candidate_yes_no": str(
            summary.get("candidate_yes_no")
            or cand.get("candidate_yes_no")
            or ("no_discussion_only" if cand.get("research_candidate_allowed") else "no")
        ),
        "verdict": str(
            cand.get("verdict")
            or summary.get("verdict")
            or "discussion_only_not_auto_promoted"
        ),
        "gate_passed": bool(cand.get("gate_passed", summary.get("gate_passed", False))),
        "economic_net_ok": bool(
            cand.get("economic_net_ok", summary.get("economic_net_ok", False))
        ),
        "signal_id": str(
            payload.get("signal_id")
            or cand.get("signal_id")
            or summary.get("signal_id")
            or ""
        ),
    }


# ---------------------------------------------------------------------------
# StrategySpec builders (approved features only)
# ---------------------------------------------------------------------------


def build_multi_day_hold_strategy_spec(
    *,
    hold_days: int = 10,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = 0.0,
    momentum_version: str = DEFAULT_MOMENTUM_FEATURE_VERSION,
    momentum_n: int | None = None,
    strategy_id: str | None = None,
    rationale: str = "",
    sticky: bool = True,
) -> StrategySpec:
    """Map multi_day_hold entry (momentum_n) into closed StrategySpec v3.

    Sticky multi-day hold uses ``rebalance=fixed_horizon`` + ``hold_days``
    (W84). Entry still top_k on momentum (research is sign(momentum); top_k is
    a residual long-only portfolio approximation).
    """
    h = max(1, int(hold_days))
    n_mom = max(1, int(momentum_n if momentum_n is not None else h))
    sid = strategy_id or f"paper_mdh_hold{h}_momentum_topk"
    return StrategySpec(
        strategy_id=sid,
        version=STRATEGY_SPEC_VERSION,
        rule=TopKRule(
            feature=FeatureRef(
                id="momentum_n",
                version=str(momentum_version),
                params={"n": n_mom},
            ),
            k=max(1, int(top_k)),
            min_score=float(min_score),
        ),
        rationale=rationale
        or (
            f"Paper receptacle for multi_day_hold {h}d: entry ≈ top_k of "
            f"momentum_n(n={n_mom}). Sticky fixed_horizon hold={h}d (v3). "
            "UNARMED — no continuous paper scheduler."
        ),
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
    strategy_id: str | None = None,
    rationale: str = "",
) -> StrategySpec:
    """Research-aligned CS sticky hold: rank L-S + fixed_horizon hold.

    Defaults match W83/W84 production candidate: hold=10 · mom=5 · frac=0.3.
    ``signal_sign``: +1 original / −1 inverted (W86 sign selection).
    """
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
                id="momentum_n",
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
            f"Paper for cross_section sticky hold={h}d mom_n={n_mom}: "
            f"rank L-S long_frac={long_frac} short_frac={short_frac} "
            f"allow_short={allow_short} signal_sign={s_sign}; "
            f"fixed_horizon rebalance. UNARMED limited trial only."
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
    strategy_id: str | None = None,
    rationale: str = "",
) -> StrategySpec:
    """Research-aligned fund path: value×mom agree + fixed_horizon hold.

    ``signal_sign``: +1 original / −1 inverted (W86 sign selection).
    """
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
                id="fundamental_value_score",
                version=str(value_version),
                params={},
            ),
            momentum_feature=FeatureRef(
                id="momentum_n",
                version=str(momentum_version),
                params={"n": n_mom},
            ),
            mode=str(mode or "value_momentum_agree"),
            allow_short=bool(allow_short),
            signal_sign=s_sign,
        ),
        rationale=rationale
        or (
            f"Paper for fundamentals_price hold={h}d mom_n={n_mom} mode={mode} "
            f"signal_sign={s_sign}: value score (BPS/P|EPS/P PIT) × momentum "
            "agree; fixed_horizon. UNARMED limited trial only."
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
    """Map event_post into StrategySpec using disclosure_flag_fins.

    Full surprise-proxy is still not expressible (no signed surprise feature
    on the whitelist). Sticky hold on the disclosure flag is now expressible
    via fixed_horizon (v3). Envelope marks fidelity=proxy for the signal.
    """
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
        or (
            f"Paper receptacle for event_post {h}d (discussion_only proxy): "
            "threshold on disclosure_flag_fins + sticky hold. Full signed "
            "surprise not on feature whitelist. UNARMED receptacle only."
        ),
        rebalance=REBALANCE_FIXED_HORIZON if sticky and h > 1 else "daily",
        hold_days=h if sticky and h > 1 else None,
    )

# ---------------------------------------------------------------------------
# Receptacle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaperCandidateReceptacle:
    """Paper-readable, unarmed receptacle for a research candidate.

    Aligns StrategySpec (nested) with research fields:
    horizon · costs · universe · rebalance
    """

    strategy_spec: StrategySpec
    hypothesis_class: str
    horizon: str
    universe: tuple[str, ...]
    rebalance: str
    costs: Mapping[str, Any]
    signal_id: str = ""
    hold_days: int | None = None
    strategy_spec_fidelity: str = "aligned"  # aligned | proxy
    discussion_only: bool = True
    source_candidate: Mapping[str, Any] = field(default_factory=dict)
    paper_run_hints: Mapping[str, Any] = field(default_factory=dict)
    note: str = ""
    version: str = PAPER_CANDIDATE_SPEC_VERSION
    adapter_version: str = PAPER_CANDIDATE_ADAPTER_VERSION
    wave: str = PAPER_CANDIDATE_WAVE
    status: str = "paper_receptacle_unarmed"

    def to_dict(self) -> dict[str, Any]:
        arm = _freeze_arm_flags()
        body: dict[str, Any] = {
            "version": self.version,
            "adapter_version": self.adapter_version,
            "wave": self.wave,
            "status": self.status,
            "hypothesis_class": self.hypothesis_class,
            "signal_id": self.signal_id,
            "horizon": self.horizon,
            "universe": list(self.universe),
            "rebalance": self.rebalance,
            "costs": dict(self.costs),
            "hold_days": self.hold_days,
            "strategy_spec": self.strategy_spec.to_dict(),
            "strategy_spec_fidelity": self.strategy_spec_fidelity,
            "discussion_only": bool(self.discussion_only),
            "source_candidate": {
                **dict(self.source_candidate),
                "research_candidate": False,
            },
            "paper_run_hints": {
                "lifecycle": "Draft",
                "execution_mode": "next_close",
                "lookback_days": DEFAULT_LOOKBACK_DAYS,
                **{
                    k: v
                    for k, v in dict(self.paper_run_hints).items()
                    if k
                    not in {
                        "scheduler_armed",
                        "run_now",
                        "continuous",
                        "require_ready_snapshot",
                    }
                },
                # force closed even if paper_run_hints tried to open
                "scheduler_armed": False,
                "run_now": False,
                "continuous": False,
                "require_ready_snapshot": False,
            },
            "arm": arm,
            **arm,
            "note": self.note
            or (
                "UNARMED paper receptacle. Pseudo-ops between research and live. "
                "Does not arm paper scheduler continuously. Does not enable live "
                "orders. Mass NO-GO · Phase7 OFF · READY undeclared · GO closed."
            ),
        }
        assert_unarmed(body)
        return body

    def strategy_spec_dict(self) -> dict[str, Any]:
        return self.strategy_spec.to_dict()


def _costs_block(
    *,
    one_way_cost: float,
    hold_days: int,
    cost_assumption: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    am = float(one_way_cost) / float(max(1, hold_days))
    out: dict[str, Any] = {
        "one_way_cost": float(one_way_cost),
        "one_way_cost_bp": float(one_way_cost) * 10_000.0,
        "amortized_one_way_cost": am,
        "amortization": "hold_days",
        "hold_days": int(hold_days),
        # PaperRunConfig.cost_bps alignment (basis points one-way)
        "cost_bps": float(one_way_cost) * 10_000.0,
        "position_style": "long_only_unlevered",
        "uses_short": False,
        "uses_leverage": False,
    }
    if cost_assumption:
        # keep research disclosure, strip any arm keys
        safe = {
            k: v
            for k, v in cost_assumption.items()
            if k
            not in {
                "mass_research",
                "phase7",
                "ready_declared",
                "operational_go",
                "connected_to_ready",
                "connected_to_mass",
                "significance_claimed",
                "edge_claimed",
            }
        }
        out["research_cost_assumption"] = safe
    return out


def adapt_class_hyp_candidate(
    payload: Mapping[str, Any],
    *,
    class_id: str | None = None,
    hold_days: int | None = None,
    top_k: int = DEFAULT_TOP_K,
    strategy_id: str | None = None,
) -> PaperCandidateReceptacle:
    """Adapt a class_hyp / research candidate payload → unarmed paper receptacle.

    Accepts:
    * class block from ``class_hyp_multi_year_bundle`` (multi_day_hold_10, event_post, …)
    * free-form research candidate with ``hypothesis_class`` / ``signal_id``
    * candidate_summary row plus optional overrides

    Always returns UNARMED; never sets live/go/mass/ready.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")

    cid = str(
        class_id
        or payload.get("hypothesis_class")
        or payload.get("class_id")
        or ""
    ).strip()
    if not cid:
        raise ValueError("hypothesis_class / class_id required")

    one_way = _one_way_cost_from_payload(payload)
    source = _source_candidate_block(payload)
    signal_id = str(payload.get("signal_id") or source.get("signal_id") or "")
    universe = tuple(_universe_from_payload(payload, class_id=cid))
    cost_assumption = payload.get("cost_assumption")
    if not isinstance(cost_assumption, Mapping):
        cost_assumption = None

    discussion_only = True
    residual_notes: list[str] = []

    if cid == CLASS_MULTI_DAY_HOLD:
        h = int(
            hold_days
            if hold_days is not None
            else _hold_days_from_payload(payload, default=10, class_id=cid)
        )
        # multi_day_hold_10 convention
        if str(payload.get("variant") or "") in {"hold_10", "10", "10d"}:
            h = 10
        n_mom = payload.get("momentum_n")
        n_mom_i = int(n_mom) if n_mom is not None else h
        spec = build_multi_day_hold_strategy_spec(
            hold_days=h,
            top_k=top_k,
            momentum_n=n_mom_i,
            strategy_id=strategy_id,
        )
        horizon = f"{h}d_hold"
        rebalance = f"fixed_horizon_{h}d"
        fidelity = "aligned_with_residuals"
        residual_notes.append(
            "entry is top_k momentum (research uses sign(momentum) L/S per name)"
        )
        if not signal_id:
            signal_id = "c21_multi_day_momentum_hold"
        note = (
            f"multi_day_hold paper receptacle hold={h}d sticky fixed_horizon. "
            f"StrategySpec v3 momentum_n(n={n_mom_i}) top_k. UNARMED."
        )
    elif cid == CLASS_CROSS_SECTION_RELATIVE:
        h = int(
            hold_days
            if hold_days is not None
            else _hold_days_from_payload(payload, default=10, class_id=cid)
        )
        variant_s = str(payload.get("variant") or "")
        if variant_s in {
            "hold_10",
            "cross_section_hold_10",
            "hold_10_mom3",
            "cross_section_hold_10_mom3",
            "10",
            "10d",
        }:
            h = 10
        n_mom = payload.get("momentum_n")
        if n_mom is None:
            n_mom = payload.get("cross_section_hold10_momentum_n")
        if n_mom is None and variant_s in {
            "hold_10_mom3",
            "cross_section_hold_10_mom3",
        }:
            n_mom = payload.get("cross_section_hold10_mom3_momentum_n", 3)
        # Sticky hold=10 uses mom=5 unless variant pins mom=3. Do not retune.
        if n_mom is not None:
            n_mom_i = int(n_mom)
        elif h == 10:
            n_mom_i = 5
        else:
            n_mom_i = h
        long_frac = float(payload.get("long_frac", DEFAULT_CS_LONG_FRAC))
        short_frac = float(payload.get("short_frac", DEFAULT_CS_SHORT_FRAC))
        allow_short = bool(payload.get("allow_short", True))
        # W86 chosen_sign from sign selection (default +1 original)
        s_sign_raw = payload.get("chosen_sign", payload.get("signal_sign", 1))
        try:
            s_sign = int(s_sign_raw) if int(s_sign_raw) in (1, -1) else 1
        except (TypeError, ValueError):
            s_sign = 1
        spec = build_cross_section_hold_strategy_spec(
            hold_days=h,
            momentum_n=n_mom_i,
            long_frac=long_frac,
            short_frac=short_frac,
            allow_short=allow_short,
            signal_sign=s_sign,
            strategy_id=strategy_id,
        )
        horizon = f"hold_{h}d_mom{n_mom_i}"
        rebalance = f"fixed_horizon_{h}d"
        fidelity = "aligned_with_residuals"
        residual_notes.extend(
            [
                "paper portfolio MTM (equal-weight long/short books) vs research "
                "trade-level mean of signed multi-day returns",
                "no margin/borrow model on short leg",
            ]
        )
        if not signal_id:
            signal_id = "c21_cross_section_momentum_rank"
        note = (
            f"cross_section sticky hold={h}d mom_n={n_mom_i} L-S "
            f"frac={long_frac}/{short_frac}. StrategySpec v3 cross_section_rank "
            f"+ fixed_horizon. UNARMED."
        )
    elif cid == CLASS_FUNDAMENTALS_PRICE:
        h = int(
            hold_days
            if hold_days is not None
            else _hold_days_from_payload(payload, default=10, class_id=cid)
        )
        if str(payload.get("variant") or "") in {
            "hold_10",
            "fundamentals_hold_10",
            "10",
            "10d",
        }:
            h = 10
        n_mom = payload.get("momentum_n")
        if n_mom is None:
            n_mom = payload.get("fund_hold10_momentum_n")
        n_mom_i = int(n_mom) if n_mom is not None else (10 if h == 10 else h)
        mode = str(payload.get("mode") or "value_momentum_agree")
        allow_short = bool(payload.get("allow_short", True))
        s_sign_raw = payload.get("chosen_sign", payload.get("signal_sign", 1))
        try:
            s_sign = int(s_sign_raw) if int(s_sign_raw) in (1, -1) else 1
        except (TypeError, ValueError):
            s_sign = 1
        spec = build_fundamentals_hold_strategy_spec(
            hold_days=h,
            momentum_n=n_mom_i,
            mode=mode,
            allow_short=allow_short,
            signal_sign=s_sign,
            strategy_id=strategy_id,
        )
        horizon = f"hold_{h}d_mom{n_mom_i}"
        rebalance = f"fixed_horizon_{h}d"
        fidelity = "aligned_with_residuals"
        residual_notes.extend(
            [
                "value benchmark = same-bar CS median of visible scores "
                "(research uses global-window median of value scores)",
                "paper portfolio MTM vs research trade-level mean",
                "no margin/borrow model on short leg",
            ]
        )
        if not signal_id:
            signal_id = "c21_fundamentals_price_value"
        note = (
            f"fundamentals_price hold={h}d mom_n={n_mom_i} mode={mode}. "
            "StrategySpec v3 value_momentum_agree + fixed_horizon. UNARMED."
        )
    elif cid == CLASS_EVENT_POST:
        h = int(
            hold_days
            if hold_days is not None
            else _hold_days_from_payload(payload, default=5, class_id=cid)
        )
        if payload.get("post_hold_days") is not None:
            h = max(1, int(payload["post_hold_days"]))
        spec = build_event_post_strategy_spec(
            post_hold_days=h,
            strategy_id=strategy_id,
        )
        horizon = f"1d_to_{h}d_post_event"
        rebalance = f"event_entry_hold_{h}d_sticky"
        fidelity = "proxy"
        residual_notes.append(
            "signal is disclosure_flag threshold, not signed surprise on event day"
        )
        if not signal_id:
            signal_id = "c21_event_post_disclosure_hold"
        note = (
            f"event_post paper receptacle post_hold={h}d sticky (discussion_only). "
            "StrategySpec proxy = disclosure_flag_fins threshold + fixed_horizon. "
            "Full surprise not on whitelist. UNARMED."
        )
    else:
        # Generic fallback: still emit a multi_day momentum receptacle, marked proxy
        h = int(
            hold_days
            if hold_days is not None
            else _hold_days_from_payload(payload, default=5, class_id=cid)
        )
        try:
            class_spec = get_hypothesis_class(cid)
            horizon = class_spec.horizon
            if not universe:
                universe = tuple(class_spec.universe)
        except KeyError:
            horizon = f"{h}d_hold"
        spec = build_multi_day_hold_strategy_spec(
            hold_days=h,
            top_k=top_k,
            strategy_id=strategy_id or f"paper_{cid}_proxy_momentum",
            rationale=(
                f"Generic paper receptacle proxy for class {cid!r} via momentum_n. "
                "UNARMED discussion_only."
            ),
        )
        rebalance = f"fixed_horizon_{h}d"
        fidelity = "proxy"
        residual_notes.append("generic class falls back to momentum top_k sticky")
        note = (
            f"Generic unarmed paper receptacle for class={cid}. "
            "Proxy StrategySpec (momentum_n sticky). Not live. Not armed."
        )
    residual_block = {
        "notes": residual_notes,
        "policy": (
            "Align paper/StrategySpec toward research; do not simplify research. "
            "Residuals only when unavoidable."
        ),
    }
    return PaperCandidateReceptacle(
        strategy_spec=spec,
        hypothesis_class=cid,
        horizon=horizon,
        universe=universe,
        rebalance=rebalance,
        costs=_costs_block(
            one_way_cost=one_way,
            hold_days=h,
            cost_assumption=cost_assumption,
        ),
        signal_id=signal_id,
        hold_days=h,
        strategy_spec_fidelity=fidelity,
        discussion_only=discussion_only,
        source_candidate=source,
        paper_run_hints={
            "lifecycle": "Draft",
            "execution_mode": "next_close",
            "lookback_days": max(DEFAULT_LOOKBACK_DAYS, h + 5),
            "cost_bps": float(one_way) * 10_000.0,
            "universe": list(universe),
            "hold_days": h,
            "strategy_spec_version": STRATEGY_SPEC_VERSION,
            "residual_approximations": residual_block,
        },
        note=note,
    )

def adapt_from_class_hyp_bundle(
    bundle: Mapping[str, Any],
    class_key: str,
    *,
    top_k: int = DEFAULT_TOP_K,
) -> PaperCandidateReceptacle:
    """Pull one class block (e.g. multi_day_hold_10, event_post) from a bundle."""
    if class_key not in bundle:
        # try candidate_summary-only construction
        summary = bundle.get("candidate_summary")
        if isinstance(summary, Mapping) and class_key in summary:
            row = dict(summary[class_key])
            # map multi_day_hold_10 → class
            if class_key.startswith("multi_day_hold"):
                row.setdefault("hypothesis_class", CLASS_MULTI_DAY_HOLD)
                if "10" in class_key:
                    row.setdefault("variant", "hold_10")
                    row.setdefault("hold_days", 10)
            elif class_key == "event_post":
                row.setdefault("hypothesis_class", CLASS_EVENT_POST)
                row.setdefault("post_hold_days", 5)
            if bundle.get("one_way_cost") is not None:
                row.setdefault("one_way_cost", bundle["one_way_cost"])
            if bundle.get("codes") is not None:
                row.setdefault("codes", bundle["codes"])
            return adapt_class_hyp_candidate(row, top_k=top_k)
        raise KeyError(f"class_key {class_key!r} not in bundle")

    block = dict(bundle[class_key])
    if not isinstance(bundle[class_key], Mapping):
        raise TypeError(f"bundle[{class_key!r}] must be a mapping")

    if class_key.startswith("multi_day_hold"):
        block.setdefault("hypothesis_class", CLASS_MULTI_DAY_HOLD)
        if "10" in class_key:
            block.setdefault("variant", "hold_10")
            block.setdefault("hold_days", 10)
    elif class_key.startswith("cross_section"):
        block.setdefault("hypothesis_class", CLASS_CROSS_SECTION_RELATIVE)
        if "hold_10" in class_key or class_key.endswith("_10"):
            block.setdefault("variant", "hold_10")
            block.setdefault("hold_days", 10)
            block.setdefault("momentum_n", DEFAULT_CS_MOMENTUM_N)
    elif class_key.startswith("fundamentals"):
        block.setdefault("hypothesis_class", CLASS_FUNDAMENTALS_PRICE)
        if "hold_10" in class_key or class_key.endswith("_10"):
            block.setdefault("variant", "hold_10")
            block.setdefault("hold_days", 10)
            block.setdefault("momentum_n", DEFAULT_FUND_MOMENTUM_N)
    elif class_key == "event_post":
        block.setdefault("hypothesis_class", CLASS_EVENT_POST)

    # attach candidate_summary row if present
    summary = bundle.get("candidate_summary")
    if isinstance(summary, Mapping) and class_key in summary:
        block.setdefault("candidate_summary", summary[class_key])

    if bundle.get("one_way_cost") is not None:
        block.setdefault("one_way_cost", bundle["one_way_cost"])
    if bundle.get("codes") is not None:
        block.setdefault("codes", bundle["codes"])

    return adapt_class_hyp_candidate(block, top_k=top_k)


def example_multi_day_hold_10d_payload() -> dict[str, Any]:
    """Synthetic discussion_only multi_day_hold 10d candidate payload."""
    return {
        "hypothesis_class": CLASS_MULTI_DAY_HOLD,
        "signal_id": "c21_multi_day_momentum_hold",
        "variant": "hold_10",
        "hold_days": 10,
        "one_way_cost": DEFAULT_ONE_WAY_COST,
        "candidate": {
            "research_candidate": False,
            "research_candidate_allowed": True,
            "gate_passed": True,
            "economic_net_ok": True,
            "verdict": "discussion_only_not_auto_promoted",
        },
        "candidate_summary": {
            "candidate_yes_no": "no_discussion_only",
            "research_candidate": False,
            "research_candidate_allowed": True,
            "verdict": "discussion_only_not_auto_promoted",
            "signal_id": "c21_multi_day_momentum_hold",
        },
        # hostile input: must be stripped
        "paper_scheduler_armed": True,
        "live_orders": True,
        "operational_go": True,
        "ready_declared": True,
        "mass_research": "GO",
        "phase7": "ON",
    }


def example_event_post_payload() -> dict[str, Any]:
    """Synthetic discussion_only event_post candidate payload."""
    return {
        "hypothesis_class": CLASS_EVENT_POST,
        "signal_id": "c21_event_post_disclosure_hold",
        "post_hold_days": 5,
        "one_way_cost": DEFAULT_ONE_WAY_COST,
        "candidate": {
            "research_candidate": False,
            "research_candidate_allowed": True,
            "gate_passed": True,
            "economic_net_ok": True,
            "verdict": "discussion_only_not_auto_promoted",
        },
        "candidate_summary": {
            "candidate_yes_no": "no_discussion_only",
            "research_candidate": False,
            "research_candidate_allowed": True,
            "verdict": "discussion_only_not_auto_promoted",
            "signal_id": "c21_event_post_disclosure_hold",
        },
        "paper_scheduler_armed": True,
        "live_orders": True,
        "go": True,
    }


def emit_example_paper_specs(out_dir: str | Path) -> dict[str, Path]:
    """Write multi_day_hold 10d + event_post paper specs (UNARMED)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mdh = adapt_class_hyp_candidate(example_multi_day_hold_10d_payload())
    ep = adapt_class_hyp_candidate(example_event_post_payload())
    paths: dict[str, Path] = {}
    for name, rec in (
        ("multi_day_hold_10d.json", mdh),
        ("event_post.json", ep),
    ):
        path = out / name
        body = rec.to_dict()
        assert_unarmed(body)
        # also write nested strategy_spec alone for paper consumers
        path.write_text(
            json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        paths[name] = path
        bare = out / name.replace(".json", "_strategy_spec.json")
        bare.write_text(
            json.dumps(rec.strategy_spec_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths[bare.name] = bare

    index = {
        "version": PAPER_CANDIDATE_SPEC_VERSION,
        "adapter_version": PAPER_CANDIDATE_ADAPTER_VERSION,
        "wave": PAPER_CANDIDATE_WAVE,
        "status": "paper_receptacle_unarmed",
        "files": sorted(paths.keys()),
        **_freeze_arm_flags(),
        "note": (
            "Example paper receptacles. UNARMED. "
            "Not continuous paper scheduler. Not live orders."
        ),
    }
    assert_unarmed(index)
    index_path = out / "index.json"
    index_path.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    paths["index.json"] = index_path
    return paths


__all__ = [
    "CONNECTED_TO_MASS",
    "CONNECTED_TO_READY",
    "DEFAULT_CS_LONG_FRAC",
    "DEFAULT_CS_MOMENTUM_N",
    "DEFAULT_CS_SHORT_FRAC",
    "DEFAULT_FUND_MOMENTUM_N",
    "DEFAULT_ONE_WAY_COST",
    "EDGE_CLAIMED",
    "LIVE_ORDER_PATH_ENABLED",
    "LIVE_ORDERS",
    "MASS_RESEARCH",
    "OPERATIONAL_GO",
    "PAPER_CANDIDATE_ADAPTER_VERSION",
    "PAPER_CANDIDATE_SPEC_VERSION",
    "PAPER_CANDIDATE_WAVE",
    "PAPER_CONTINUOUS",
    "PAPER_SCHEDULER_ARMED",
    "PHASE7",
    "READY_DECLARED",
    "SIGNIFICANCE_CLAIMED",
    "PaperCandidateReceptacle",
    "adapt_class_hyp_candidate",
    "adapt_from_class_hyp_bundle",
    "assert_unarmed",
    "build_cross_section_hold_strategy_spec",
    "build_event_post_strategy_spec",
    "build_fundamentals_hold_strategy_spec",
    "build_multi_day_hold_strategy_spec",
    "emit_example_paper_specs",
    "example_event_post_payload",
    "example_multi_day_hold_10d_payload",
]
