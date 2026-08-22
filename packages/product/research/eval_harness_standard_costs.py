"""Standard eval cost/leverage pack (W56 next-day; not candidate SoT).

Used by :mod:`research.eval_harness_standard`. Public imports stay on
:mod:`research.eval_harness` / :mod:`research.eval_harness_multiyear`.
Mass/READY/GO closed.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from research.cost_models import (
    build_leverage_short_cost_assumption,
    default_long_only_unlevered_cost_assumption,
    load_repo_rate_series,
    mean_repo_rate_pct,
)
from research.eval_harness import EvalHarnessError, _closed_flags
from research.robustness_gate import DEFAULT_ONE_WAY_COST


def _block_assumption(
    lev_short: Mapping[str, Any],
    missing_key: str,
    **flags: Any,
) -> dict[str, Any]:
    lev = dict(lev_short)
    lev["assumptions_complete"] = False
    missing = list(lev.get("missing_disclosure") or [])
    if missing_key not in missing:
        missing.append(missing_key)
    lev["missing_disclosure"] = missing
    lev.update(flags)
    return lev


def _attach_repo_disclosure(
    lev_short: dict[str, Any],
    repo_series_norm: Mapping[str, Any],
    *,
    prefer_repo_linked: bool,
    repo_required_dates: Sequence[Any] | None,
) -> None:
    if lev_short.get("repo_rate"):
        return
    m = mean_repo_rate_pct(repo_series_norm, dates=repo_required_dates)
    lev_short["repo_rate"] = {
        "preferred": bool(prefer_repo_linked),
        "series_supplied": True,
        "series_usable": int(m.get("n_obs") or 0) > 0,
        "series": repo_series_norm,
        "mean_rate_pct": m.get("mean_rate_pct"),
        "mean_annual_bp": m.get("mean_annual_bp"),
        "n_obs": int(m.get("n_obs") or 0),
        "gap_dates": list(repo_series_norm.get("gap_dates") or []),
        "n_gaps": int(repo_series_norm.get("n_gaps") or 0),
        "ffill_applied": False,
        "invent_fill": False,
    }


def build_standard_eval_costs(
    kw: Mapping[str, Any],
) -> tuple[float, dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """Tx + leverage/short pack. Changing 10bp needs cost_change_reason."""
    default_cost = float(DEFAULT_ONE_WAY_COST)
    cost = float(kw["one_way_cost"])
    cost_bp = cost * 10_000.0
    reason = kw.get("cost_change_reason")
    if abs(cost - default_cost) > 1e-15 and not (reason and str(reason).strip()):
        raise EvalHarnessError(
            "changing one_way_cost from default 10bp requires cost_change_reason"
        )
    cost_assumption: dict[str, Any] = {
        "one_way_cost": cost,
        "one_way_cost_bp": cost_bp,
        "round_trip_cost": cost * 2.0,
        "round_trip_cost_bp": cost_bp * 2.0,
        "require_net_sign_majority": bool(kw["require_net_sign_majority"]),
        "default_one_way_cost": default_cost,
        "default_one_way_cost_bp": default_cost * 10_000.0,
        "changed_from_default": abs(cost - default_cost) > 1e-15,
        "change_reason": str(reason).strip() if reason else None,
        "label": "仮定に依存・研究用・運用GOではない",
    }

    repo_series_norm: dict[str, Any] | None = None
    if kw.get("repo_rate_series") is not None:
        repo_series_norm = load_repo_rate_series(
            kw["repo_rate_series"],
            required_dates=kw.get("repo_required_dates"),
        )

    prefer_repo = bool(kw.get("prefer_repo_linked", True))
    prefer_liq = bool(kw.get("prefer_liquidity_linked", True))
    liq = dict(
        liquidity_proxy=kw.get("liquidity_proxy"),
        liquidity_bars=kw.get("liquidity_bars"),
        liquidity_bucket=kw.get("liquidity_bucket"),
        liquidity_adv_jpy=kw.get("liquidity_adv_jpy"),
        is_topix=kw.get("is_topix"),
        scale_category=kw.get("scale_category"),
        prefer_liquidity_linked=prefer_liq,
    )
    supplied = kw.get("leverage_short_cost_assumption")
    if supplied is not None:
        lev_short = {**dict(supplied), **_closed_flags()}
        if "assumptions_complete" not in lev_short:
            lev_short["assumptions_complete"] = bool(
                lev_short.get("assumptions_disclosed", False)
            )
        if repo_series_norm is not None:
            _attach_repo_disclosure(
                lev_short,
                repo_series_norm,
                prefer_repo_linked=prefer_repo,
                repo_required_dates=kw.get("repo_required_dates"),
            )
    else:
        style = str(kw.get("position_style") or "long_only_unlevered").strip().lower()
        if (
            style == "long_only_unlevered"
            and float(kw.get("gross_leverage") or 1.0) <= 1.0 + 1e-12
            and not kw.get("uses_short")
            and not kw.get("uses_leverage")
        ):
            lev_short = default_long_only_unlevered_cost_assumption(
                one_way_cost=cost,
                cost_change_reason=reason,
                repo_rate_series=repo_series_norm,
                **liq,
            )
        else:
            lev_short = build_leverage_short_cost_assumption(
                position_style=style,
                gross_leverage=float(kw.get("gross_leverage") or 1.0),
                short_fraction=float(kw.get("short_fraction") or 0.0),
                one_way_cost=cost,
                short_borrow_annual_bp=kw.get("short_borrow_annual_bp"),
                financing_annual_bp=kw.get("financing_annual_bp"),
                cost_change_reason=reason,
                short_borrow_change_reason=kw.get("short_borrow_change_reason"),
                financing_change_reason=kw.get("financing_change_reason"),
                uses_short=kw.get("uses_short"),
                uses_leverage=kw.get("uses_leverage"),
                repo_rate_series=repo_series_norm,
                prefer_repo_linked=prefer_repo,
                short_borrow_spread_bp=kw.get("short_borrow_spread_bp"),
                short_borrow_sensitivity=kw.get("short_borrow_sensitivity"),
                borrow_proxy_annual_bp=kw.get("borrow_proxy_annual_bp"),
                required_dates=kw.get("repo_required_dates"),
                require_liquidity_linked=bool(kw.get("require_liquidity_linked")),
                liquidity_required_dates=kw.get("liquidity_required_dates"),
                **liq,
            )

    repo_req = bool(kw.get("require_repo_linked"))
    uses_ls = bool(lev_short.get("uses_short") or lev_short.get("uses_leverage"))
    if repo_req and uses_ls and not bool(lev_short.get("repo_linked")):
        lev_short = _block_assumption(
            lev_short,
            "repo_rate_series",
            require_repo_linked=True,
            repo_linked_requirement_failed=True,
        )

    liq_req = bool(kw.get("require_liquidity_linked"))
    liq_block = lev_short.get("liquidity") or {}
    liq_gap = bool(liq_block.get("is_gap", True)) if liq_block else True
    if liq_req and liq_gap:
        lev_short = _block_assumption(
            lev_short,
            "liquidity_proxy",
            require_liquidity_linked=True,
            liquidity_linked_requirement_failed=True,
        )

    cost_assumption["leverage_short"] = {
        "position_style": lev_short.get("position_style"),
        "assumptions_complete": lev_short.get("assumptions_complete"),
        "uses_short": lev_short.get("uses_short"),
        "uses_leverage": lev_short.get("uses_leverage"),
        "short_borrow_daily": (lev_short.get("short_borrow") or {}).get("daily_cost"),
        "financing_daily": (lev_short.get("leverage_financing") or {}).get(
            "daily_cost"
        ),
        "repo_linked": lev_short.get("repo_linked"),
        "prefer_repo_linked": prefer_repo,
        "require_repo_linked": repo_req,
        "liquidity_linked": lev_short.get("liquidity_linked"),
        "prefer_liquidity_linked": prefer_liq,
        "require_liquidity_linked": liq_req,
        "liquidity_bucket": (lev_short.get("liquidity") or {}).get("bucket"),
        "short_rate_source": (lev_short.get("short_borrow") or {}).get("rate_source"),
        "financing_rate_source": (lev_short.get("leverage_financing") or {}).get(
            "rate_source"
        ),
    }
    cost_assumption["repo_rate"] = lev_short.get("repo_rate")
    cost_assumption["liquidity"] = lev_short.get("liquidity")
    return cost, cost_assumption, lev_short, repo_series_norm
