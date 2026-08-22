"""Adapt class_hyp / research candidate payloads into an unarmed receptacle.

Does not arm the paper scheduler, call ``run_paper``, or touch the live
order path. Mass NO-GO · Phase7 OFF · READY undeclared · GO closed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from strategies.spec import STRATEGY_SPEC_VERSION, StrategySpec

from research.freezes import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    EDGE_CLAIMED,
    MASS_RESEARCH,
    OPERATIONAL_GO,
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
from research.paper_candidate_specs import (
    DEFAULT_CS_LONG_FRAC,
    DEFAULT_CS_MOMENTUM_N,
    DEFAULT_CS_SHORT_FRAC,
    DEFAULT_FUND_MOMENTUM_N,
    DEFAULT_TOP_K,
    build_cross_section_hold_strategy_spec,
    build_event_post_strategy_spec,
    build_fundamentals_hold_strategy_spec,
    build_multi_day_hold_strategy_spec,
)

PAPER_CANDIDATE_SPEC_VERSION: str = "paper-candidate-spec/v1"
PAPER_CANDIDATE_ADAPTER_VERSION: str = "paper-candidate-adapter/v2"
PAPER_CANDIDATE_WAVE: str = "W86 / w0816u"

DEFAULT_ONE_WAY_COST: float = 0.001  # 10bp
DEFAULT_LOOKBACK_DAYS: int = 30

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
    "research_candidate",
    "armed",
    "go",
)
_HINT_CLOSED: frozenset[str] = frozenset(
    {"scheduler_armed", "run_now", "continuous", "require_ready_snapshot"}
)
_COST_STRIP: frozenset[str] = frozenset(
    {
        "mass_research",
        "phase7",
        "ready_declared",
        "operational_go",
        "connected_to_ready",
        "connected_to_mass",
        "significance_claimed",
        "edge_claimed",
    }
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


def _first_float(block: Mapping[str, Any], keys: Sequence[str], *, scale: float = 1.0) -> float | None:
    for key in keys:
        if block.get(key) is not None:
            return float(block[key]) * scale
    return None


def _one_way_cost_from_payload(payload: Mapping[str, Any]) -> float:
    cost_block = payload.get("cost_assumption") or payload.get("costs") or {}
    if isinstance(cost_block, Mapping):
        tx = cost_block.get("transaction")
        if isinstance(tx, Mapping):
            got = _first_float(tx, ("one_way_cost", "one_way", "cost"))
            if got is None:
                got = _first_float(tx, ("one_way_cost_bp", "bp"), scale=1 / 10_000.0)
            if got is not None:
                return got
        got = _first_float(cost_block, ("one_way_cost", "one_way"))
        if got is None:
            got = _first_float(cost_block, ("one_way_cost_bp",), scale=1 / 10_000.0)
        if got is not None:
            return got
    got = _first_float(payload, ("one_way_cost",))
    if got is None:
        got = _first_float(payload, ("one_way_cost_bp",), scale=1 / 10_000.0)
    return DEFAULT_ONE_WAY_COST if got is None else got


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
    cid = str(payload.get("hypothesis_class") or class_id)
    if cid == CLASS_MULTI_DAY_HOLD and "10" in str(payload.get("label") or ""):
        return 10
    return max(1, int(default))


def _pin_hold_10(payload: Mapping[str, Any], variants: set[str], current: int) -> int:
    return 10 if str(payload.get("variant") or "") in variants else current


def _signal_sign(payload: Mapping[str, Any]) -> int:
    raw = payload.get("chosen_sign", payload.get("signal_sign", 1))
    try:
        return int(raw) if int(raw) in (1, -1) else 1
    except (TypeError, ValueError):
        return 1


def _universe_from_payload(payload: Mapping[str, Any], *, class_id: str) -> list[str]:
    u = payload.get("universe")
    if isinstance(u, (list, tuple)):
        return [str(x) for x in u if str(x).strip()]
    if isinstance(u, str) and u.strip():
        return [u.strip()]
    codes = payload.get("codes")
    if isinstance(codes, (list, tuple)) and codes:
        return [str(c).strip() for c in codes if str(c).strip()]
    try:
        return list(get_hypothesis_class(class_id).universe)
    except KeyError:
        return ["tse_prime_liquid"]


def _source_candidate_block(payload: Mapping[str, Any]) -> dict[str, Any]:
    cand = payload.get("candidate") if isinstance(payload.get("candidate"), Mapping) else {}
    summary = (
        payload.get("candidate_summary")
        if isinstance(payload.get("candidate_summary"), Mapping)
        else {}
    )
    allowed = bool(cand.get("research_candidate_allowed", summary.get("research_candidate_allowed", False)))
    return {
        "research_candidate": False,
        "research_candidate_allowed": allowed,
        "candidate_yes_no": str(
            summary.get("candidate_yes_no")
            or cand.get("candidate_yes_no")
            or ("no_discussion_only" if allowed else "no")
        ),
        "verdict": str(
            cand.get("verdict") or summary.get("verdict") or "discussion_only_not_auto_promoted"
        ),
        "gate_passed": bool(cand.get("gate_passed", summary.get("gate_passed", False))),
        "economic_net_ok": bool(cand.get("economic_net_ok", summary.get("economic_net_ok", False))),
        "signal_id": str(payload.get("signal_id") or cand.get("signal_id") or summary.get("signal_id") or ""),
    }


@dataclass(frozen=True)
class PaperCandidateReceptacle:
    """Paper-readable, unarmed receptacle for a research candidate."""

    strategy_spec: StrategySpec
    hypothesis_class: str
    horizon: str
    universe: tuple[str, ...]
    rebalance: str
    costs: Mapping[str, Any]
    signal_id: str = ""
    hold_days: int | None = None
    strategy_spec_fidelity: str = "aligned"
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
                **{k: v for k, v in dict(self.paper_run_hints).items() if k not in _HINT_CLOSED},
                "scheduler_armed": False,
                "run_now": False,
                "continuous": False,
                "require_ready_snapshot": False,
            },
            "arm": arm,
            **arm,
            "note": self.note
            or "UNARMED paper receptacle. Mass NO-GO · Phase7 OFF · READY undeclared · GO closed.",
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
        "cost_bps": float(one_way_cost) * 10_000.0,
        "position_style": "long_only_unlevered",
        "uses_short": False,
        "uses_leverage": False,
    }
    if cost_assumption:
        out["research_cost_assumption"] = {
            k: v for k, v in cost_assumption.items() if k not in _COST_STRIP
        }
    return out


def _cs_momentum_n(payload: Mapping[str, Any], hold_days: int) -> int:
    variant_s = str(payload.get("variant") or "")
    n_mom = payload.get("momentum_n")
    if n_mom is None:
        n_mom = payload.get("cross_section_hold10_momentum_n")
    if n_mom is None and variant_s in {
        "hold_10_mom3",
        "cross_section_hold_10_mom3",
    }:
        n_mom = payload.get("cross_section_hold10_mom3_momentum_n", 3)
    if n_mom is not None:
        return int(n_mom)
    return 5 if hold_days == 10 else hold_days


def adapt_class_hyp_candidate(
    payload: Mapping[str, Any],
    *,
    class_id: str | None = None,
    hold_days: int | None = None,
    top_k: int = DEFAULT_TOP_K,
    strategy_id: str | None = None,
) -> PaperCandidateReceptacle:
    """Adapt a class_hyp / research candidate payload → unarmed paper receptacle.

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

    residual_notes: list[str] = []
    known_hold10 = {
        CLASS_MULTI_DAY_HOLD,
        CLASS_CROSS_SECTION_RELATIVE,
        CLASS_FUNDAMENTALS_PRICE,
    }
    h = int(
        hold_days
        if hold_days is not None
        else _hold_days_from_payload(
            payload,
            default=10 if cid in known_hold10 else 5,
            class_id=cid,
        )
    )
    _mtm = ["paper MTM vs research trade-level mean", "no margin/borrow on short leg"]

    if cid == CLASS_MULTI_DAY_HOLD:
        h = _pin_hold_10(payload, {"hold_10", "10", "10d"}, h)
        n_mom_i = int(payload["momentum_n"]) if payload.get("momentum_n") is not None else h
        spec = build_multi_day_hold_strategy_spec(
            hold_days=h, top_k=top_k, momentum_n=n_mom_i, strategy_id=strategy_id
        )
        horizon, rebalance = f"{h}d_hold", f"fixed_horizon_{h}d"
        fidelity = "aligned_with_residuals"
        residual_notes.append("entry is top_k momentum (research uses sign(momentum) L/S)")
        signal_id = signal_id or "c21_multi_day_momentum_hold"
        note = f"multi_day_hold hold={h}d mom_n={n_mom_i} top_k. UNARMED."
    elif cid == CLASS_CROSS_SECTION_RELATIVE:
        h = _pin_hold_10(
            payload,
            {
                "hold_10",
                "cross_section_hold_10",
                "hold_10_mom3",
                "cross_section_hold_10_mom3",
                "10",
                "10d",
            },
            h,
        )
        n_mom_i = _cs_momentum_n(payload, h)
        long_frac = float(payload.get("long_frac", DEFAULT_CS_LONG_FRAC))
        short_frac = float(payload.get("short_frac", DEFAULT_CS_SHORT_FRAC))
        spec = build_cross_section_hold_strategy_spec(
            hold_days=h,
            momentum_n=n_mom_i,
            long_frac=long_frac,
            short_frac=short_frac,
            allow_short=bool(payload.get("allow_short", True)),
            signal_sign=_signal_sign(payload),
            strategy_id=strategy_id,
        )
        horizon, rebalance = f"hold_{h}d_mom{n_mom_i}", f"fixed_horizon_{h}d"
        fidelity = "aligned_with_residuals"
        residual_notes.extend(_mtm)
        signal_id = signal_id or "c21_cross_section_momentum_rank"
        note = (
            f"cross_section hold={h}d mom_n={n_mom_i} L-S "
            f"{long_frac}/{short_frac}. UNARMED."
        )
    elif cid == CLASS_FUNDAMENTALS_PRICE:
        h = _pin_hold_10(
            payload, {"hold_10", "fundamentals_hold_10", "10", "10d"}, h
        )
        n_mom = payload.get("momentum_n", payload.get("fund_hold10_momentum_n"))
        n_mom_i = int(n_mom) if n_mom is not None else (10 if h == 10 else h)
        mode = str(payload.get("mode") or "value_momentum_agree")
        spec = build_fundamentals_hold_strategy_spec(
            hold_days=h,
            momentum_n=n_mom_i,
            mode=mode,
            allow_short=bool(payload.get("allow_short", True)),
            signal_sign=_signal_sign(payload),
            strategy_id=strategy_id,
        )
        horizon, rebalance = f"hold_{h}d_mom{n_mom_i}", f"fixed_horizon_{h}d"
        fidelity = "aligned_with_residuals"
        residual_notes.extend(
            ["value benchmark = same-bar CS median (research uses global-window)", *_mtm]
        )
        signal_id = signal_id or "c21_fundamentals_price_value"
        note = f"fundamentals_price hold={h}d mom_n={n_mom_i} mode={mode}. UNARMED."
    elif cid == CLASS_EVENT_POST:
        if payload.get("post_hold_days") is not None:
            h = max(1, int(payload["post_hold_days"]))
        spec = build_event_post_strategy_spec(
            post_hold_days=h, strategy_id=strategy_id
        )
        horizon, rebalance = f"1d_to_{h}d_post_event", f"event_entry_hold_{h}d_sticky"
        fidelity = "proxy"
        residual_notes.append("disclosure_flag threshold, not signed surprise")
        signal_id = signal_id or "c21_event_post_disclosure_hold"
        note = f"event_post post_hold={h}d sticky discussion_only proxy. UNARMED."
    else:
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
            rationale=f"Generic unarmed proxy for class {cid!r} via momentum_n.",
        )
        rebalance = f"fixed_horizon_{h}d"
        fidelity = "proxy"
        residual_notes.append("generic class falls back to momentum top_k sticky")
        note = f"Generic unarmed paper receptacle for class={cid}."

    residual_block = {
        "notes": residual_notes,
        "policy": "Align paper toward research; residuals only when unavoidable.",
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
        discussion_only=True,
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


def _apply_class_key_defaults(block: dict[str, Any], class_key: str) -> None:
    hold10 = "hold_10" in class_key or class_key.endswith("_10") or "10" in class_key
    if class_key.startswith("multi_day_hold"):
        block.setdefault("hypothesis_class", CLASS_MULTI_DAY_HOLD)
        if hold10:
            block.setdefault("variant", "hold_10")
            block.setdefault("hold_days", 10)
    elif class_key.startswith("cross_section"):
        block.setdefault("hypothesis_class", CLASS_CROSS_SECTION_RELATIVE)
        if hold10:
            block.setdefault("variant", "hold_10")
            block.setdefault("hold_days", 10)
            block.setdefault("momentum_n", DEFAULT_CS_MOMENTUM_N)
    elif class_key.startswith("fundamentals"):
        block.setdefault("hypothesis_class", CLASS_FUNDAMENTALS_PRICE)
        if hold10:
            block.setdefault("variant", "hold_10")
            block.setdefault("hold_days", 10)
            block.setdefault("momentum_n", DEFAULT_FUND_MOMENTUM_N)
    elif class_key == "event_post":
        block.setdefault("hypothesis_class", CLASS_EVENT_POST)


def adapt_from_class_hyp_bundle(
    bundle: Mapping[str, Any],
    class_key: str,
    *,
    top_k: int = DEFAULT_TOP_K,
) -> PaperCandidateReceptacle:
    """Pull one class block (e.g. multi_day_hold_10, event_post) from a bundle."""
    summary = bundle.get("candidate_summary")
    from_summary = False
    if class_key in bundle:
        if not isinstance(bundle[class_key], Mapping):
            raise TypeError(f"bundle[{class_key!r}] must be a mapping")
        block = dict(bundle[class_key])
    elif isinstance(summary, Mapping) and class_key in summary:
        block = dict(summary[class_key])
        from_summary = True
    else:
        raise KeyError(f"class_key {class_key!r} not in bundle")
    _apply_class_key_defaults(block, class_key)
    if from_summary and class_key == "event_post":
        block.setdefault("post_hold_days", 5)
    if not from_summary and isinstance(summary, Mapping) and class_key in summary:
        block.setdefault("candidate_summary", summary[class_key])
    if bundle.get("one_way_cost") is not None:
        block.setdefault("one_way_cost", bundle["one_way_cost"])
    if bundle.get("codes") is not None:
        block.setdefault("codes", bundle["codes"])
    return adapt_class_hyp_candidate(block, top_k=top_k)


def _discussion_payload(signal_id: str) -> dict[str, Any]:
    cand = {
        "research_candidate": False,
        "research_candidate_allowed": True,
        "gate_passed": True,
        "economic_net_ok": True,
        "verdict": "discussion_only_not_auto_promoted",
    }
    return {
        "signal_id": signal_id,
        "one_way_cost": DEFAULT_ONE_WAY_COST,
        "candidate": cand,
        "candidate_summary": {
            "candidate_yes_no": "no_discussion_only",
            "research_candidate": False,
            "research_candidate_allowed": True,
            "verdict": cand["verdict"],
            "signal_id": signal_id,
        },
    }


def example_multi_day_hold_10d_payload() -> dict[str, Any]:
    """Synthetic discussion_only multi_day_hold 10d candidate payload."""
    return {
        "hypothesis_class": CLASS_MULTI_DAY_HOLD,
        "variant": "hold_10",
        "hold_days": 10,
        **_discussion_payload("c21_multi_day_momentum_hold"),
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
        "post_hold_days": 5,
        **_discussion_payload("c21_event_post_disclosure_hold"),
        "paper_scheduler_armed": True,
        "live_orders": True,
        "go": True,
    }


def _write_json(path: Path, body: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def emit_example_paper_specs(out_dir: str | Path) -> dict[str, Path]:
    """Write multi_day_hold 10d + event_post paper specs (UNARMED)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, rec in (
        ("multi_day_hold_10d.json", adapt_class_hyp_candidate(example_multi_day_hold_10d_payload())),
        ("event_post.json", adapt_class_hyp_candidate(example_event_post_payload())),
    ):
        body = rec.to_dict()
        assert_unarmed(body)
        path = out / name
        _write_json(path, body)
        paths[name] = path
        bare = out / name.replace(".json", "_strategy_spec.json")
        _write_json(bare, rec.strategy_spec_dict())
        paths[bare.name] = bare
    index = {
        "version": PAPER_CANDIDATE_SPEC_VERSION,
        "adapter_version": PAPER_CANDIDATE_ADAPTER_VERSION,
        "wave": PAPER_CANDIDATE_WAVE,
        "status": "paper_receptacle_unarmed",
        "files": sorted(paths.keys()),
        **_freeze_arm_flags(),
        "note": "Example paper receptacles. UNARMED.",
    }
    assert_unarmed(index)
    index_path = out / "index.json"
    _write_json(index_path, index)
    paths["index.json"] = index_path
    return paths
