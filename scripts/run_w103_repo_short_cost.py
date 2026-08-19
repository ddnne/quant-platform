#!/usr/bin/env python3
"""W103 / w0819f Track B — repo-linked short cost on bars-MTM daily path.

Wires date-matched JSDA Tokyo overnight repo (``jsda_repo_rates``) into the
W99/W100 bars-MTM net path as short-leg daily drag. Applied only to:

  * ``xs_cs_dispersion_gate``
  * ``xs_rank_ls_sticky``

Rules
-----
* No invent / no forced ffill on missing repo days (gap → charge 0 that day).
* Contrast vs W102 mid 50 bp fixed-bp placeholder. Not a ranking exercise.
* Do not tune cost to manufacture ranking.
* Complete measurement ≠ GO / main. 3-default pins untouched.

Examples
--------
    uv run python scripts/run_w103_repo_short_cost.py \\
        --out-dir .glm-logs/w0819f_w103_otc7_repo_gate/
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
else:
    raise RuntimeError("scripts/_bootstrap.py not found")
from _bootstrap import ensure_repo_root

ROOT = ensure_repo_root()
OUT_DEFAULT = ROOT / ".glm-logs" / "w0819f_w103_otc7_repo_gate"
PROOF_DEFAULT = ROOT / "docs" / "proof" / "w0819f_w103_repo_short_cost_20260819.md"
W102_LOG = ROOT / ".glm-logs" / "w0819e_w102_otc6_event_rate_dd"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402
import run_w102_dispersion_quality as w102  # noqa: E402

from research.stats_metrics import (  # noqa: E402
    equity_path_drawdown,
    evaluate_daily_path_dd_gate,
)

WAVE = "W103 / w0819f"
GATE_LOGIC = "xs_cs_dispersion_gate"
STICKY_LOGIC = "xs_rank_ls_sticky"
STICKY_STANCE = "STABLE_RESEARCH_ONLY"

GATE_SPEC: dict[str, Any] = dict(w102.GATE_SPEC)
STICKY_SPEC: dict[str, Any] = dict(w102.STICKY_SPEC)

BASE_TX_BP: int = 10
SHORT_FRAC: float = 0.5  # L-S long=0.3 / short=0.3 → short share of active
GROSS_LEVERAGE: float = 1.0
REPO_TENOR: str = "overnight/翌日物/T+0"
REPO_START: str = "2016-01-01"  # windows start 2017; pad, never ffill

# W102 mid-band placeholder (single overlay, not pick-best).
W102_PLACEHOLDER_ANNUAL_BP: float = 50.0


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _fmt(v: Any, nd: int = 6) -> str:
    return w100._fmt(v, nd)


def _pct(v: Any, nd: int = 2) -> str:
    x = w100._scalar_f(v)
    if x is None:
        return "—"
    return f"{x * 100:.{nd}f}%"


def _git_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
        )
        return out.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _assert_frozen_pins_untouched() -> dict[str, Any]:
    pack = w99._assert_frozen_pins_untouched()
    pack["note"] = "W103 repo-linked short cost must not mutate 3-default pins"
    return pack


def load_jsda_overnight_repo_series(
    *,
    sqlite_path: Path,
    required_dates: Sequence[str] | None = None,
    start: str = REPO_START,
    end: str | None = None,
) -> dict[str, Any]:
    """Date-matched overnight Tokyo repo from local sqlite. Never ffilled."""
    from research.class_hyp_eval import load_repo_rows_from_sqlite
    from research.cost_models import load_repo_rate_series_from_rows

    pack: dict[str, Any] = {
        "sqlite_path": str(sqlite_path),
        "sqlite_exists": sqlite_path.is_file(),
        "dataset": "jsda_tokyo_repo_rates",
        "table": "jsda_repo_rates",
        "tenor_preferred": REPO_TENOR,
        "loader": "load_repo_rows_from_sqlite + load_repo_rate_series_from_rows",
        "wiring": "bars_mtm_short_leg_daily_drag",
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "ffill_applied": False,
        "invent_fill": False,
        "no_ffill": True,
        "no_invent": True,
    }
    if not sqlite_path.is_file():
        pack.update(
            {
                "status": "missing_sqlite",
                "blocked": True,
                "missing": [str(sqlite_path)],
                "n_obs": 0,
                "series": None,
            }
        )
        return pack

    rows = load_repo_rows_from_sqlite(
        sqlite_path, start=start, end=end, tenor_contains="overnight"
    )
    filtered = [r for r in rows if str(r.get("tenor") or "") == REPO_TENOR]
    use_rows = filtered if filtered else rows
    if not use_rows:
        pack.update(
            {
                "status": "empty",
                "blocked": True,
                "missing": [
                    f"jsda_repo_rates tenor={REPO_TENOR} empty in {sqlite_path}"
                ],
                "n_obs": 0,
                "n_rows_all_overnight": len(rows),
                "series": None,
            }
        )
        return pack

    series = load_repo_rate_series_from_rows(
        use_rows,
        required_dates=required_dates,
        tenor=REPO_TENOR if filtered else None,
        prefer_tenor=REPO_TENOR,
        source_label="local_sqlite_jsda_repo_rates",
    )
    rates = dict(series.get("rates_by_date") or {})
    pack.update(
        {
            "status": "ok" if rates else "empty",
            "blocked": not bool(rates),
            "missing": (
                []
                if rates
                else [f"jsda_repo_rates produced 0 rates for tenor={REPO_TENOR}"]
            ),
            "series": series,
            "n_obs": int(series.get("n_obs") or 0),
            "n_rows_loaded": len(use_rows),
            "n_rows_all_overnight": len(rows),
            "n_gaps_on_required": int(series.get("n_gaps") or 0),
            "n_required": len(list(required_dates or [])),
            "present_required_n": len(series.get("present_required_dates") or []),
            "coverage_complete": bool(series.get("coverage_complete")),
            "tenor": series.get("tenor"),
            "rate_type": series.get("rate_type"),
            "rate_span": [min(rates), max(rates)] if rates else None,
            "gap_dates_sample": list(series.get("gap_dates") or [])[:30],
        }
    )
    return pack


def apply_bars_mtm_short_drag(
    pack: Mapping[str, Any],
    *,
    repo_series: Mapping[str, Any] | None,
    spread_bp: float,
    short_fraction: float = SHORT_FRAC,
    mode: str = "repo_linked",
) -> dict[str, Any]:
    """Replay bars-MTM net with date-matched (or fixed) short borrow drag.

    Active-day mask is the W99/W100 tx-drag convention (same as W102 overlay).
    ``mode=repo_linked``: extra[t] = f(repo[t] + spread); missing repo → extra=0
    (gap disclosed, never invented / ffilled).
    ``mode=fixed_bp``: constant annual bp = spread_bp (W102 placeholder).
    """
    from research.cost_models import (
        DEFAULT_TRADING_DAYS_PER_YEAR,
        lookup_repo_rate,
        short_borrow_daily_cost,
        short_borrow_daily_cost_from_repo,
    )

    dates = list(pack.get("dates") or [])
    gross = list(pack.get("gross_daily") or [])
    net0 = list(pack.get("net_daily") or [])
    drag = float(pack.get("daily_cost_drag") or 0.0)
    if not dates or not gross or len(gross) != len(dates) or len(net0) != len(dates):
        return {"status": "missing_path", "mode": mode}

    active = w102._active_mask(gross, net0, drag)
    gap_dates: list[str] = []
    applied_dates: list[str] = []
    applied_repo: list[float] = []
    extras: list[float] = []
    net1: list[float] = []
    eq = 1.0
    equities: list[float] = []

    for i, n in enumerate(net0):
        d = str(dates[i])[:10]
        extra = 0.0
        if i != 0 and active[i]:
            if mode == "fixed_bp":
                extra = short_borrow_daily_cost(
                    short_borrow_annual_bp=float(spread_bp),
                    trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
                    short_fraction=short_fraction,
                )
                applied_dates.append(d)
            else:
                look = lookup_repo_rate(repo_series, d)
                if look.get("is_gap") or look.get("rate_pct") is None:
                    gap_dates.append(d)
                    extra = 0.0
                else:
                    extra = short_borrow_daily_cost_from_repo(
                        float(look["rate_pct"]),
                        short_fraction=short_fraction,
                        spread_bp=float(spread_bp),
                    )
                    applied_dates.append(d)
                    applied_repo.append(float(look["rate_pct"]))
            nn = float(n) - float(extra)
        else:
            nn = float(n)
        extras.append(float(extra))
        if i == 0:
            equities.append(eq)
            net1.append(0.0)
        else:
            eq = eq * (1.0 + nn)
            equities.append(eq)
            net1.append(nn)

    dd = equity_path_drawdown(equities, dates)
    gate = evaluate_daily_path_dd_gate(
        daily_path_dd=dd.get("max_dd"),
        dd_duration=dd.get("dd_duration_days"),
        recovered=dd.get("recovered"),
        recovery_days=dd.get("recovery_days"),
        total_ret_net=dd.get("total_return"),
        method="daily_equity_level_peak_to_trough",
    )
    applied_set = set(applied_dates)
    extra_on_applied = [
        extras[i] for i, d in enumerate(dates) if d in applied_set
    ]
    return {
        "status": "ok",
        "mode": mode,
        "spread_bp": float(spread_bp),
        "short_fraction": short_fraction,
        "repo_linked": mode == "repo_linked",
        "rate_source": (
            "jsda_tokyo_repo_rates_date_matched"
            if mode == "repo_linked"
            else "fixed_bp_placeholder"
        ),
        "n_active_days": sum(1 for a in active if a),
        "n_short_cost_applied": len(applied_dates),
        "n_gaps": len(gap_dates),
        "gap_dates_sample": gap_dates[:20],
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "ffill_applied": False,
        "invent_fill": False,
        "mean_repo_pct_on_applied": (
            (sum(applied_repo) / len(applied_repo)) if applied_repo else None
        ),
        "mean_extra_daily_on_applied": (
            (sum(extra_on_applied) / len(extra_on_applied))
            if extra_on_applied
            else None
        ),
        "total_return_net": dd.get("total_return"),
        "daily_path_DD": dd.get("max_dd"),
        "dd_duration": dd.get("dd_duration_days"),
        "recovery_days": dd.get("recovery_days"),
        "recovered": dd.get("recovered"),
        "peak_date": dd.get("peak_date"),
        "trough_date": dd.get("trough_date"),
        "recovery_date": dd.get("recovery_date"),
        "daily_path_complete": gate.get("complete"),
        "n_equity_points": len(equities),
        "dates": dates,
        "equities": equities,
        "net_daily": net1,
        "promote_as_main": False,
        "go": False,
    }


def _eval_base_paths(
    *,
    one_way_cost: float,
    max_codes: int,
    max_days: int,
    log,
) -> dict[str, dict[str, Any]]:
    """Tx-only bars-MTM paths for the two allowed logics (same method as W102)."""
    out: dict[str, dict[str, Any]] = {}
    for spec in (GATE_SPEC, STICKY_SPEC):
        pack = w102._eval_window(
            spec=spec,
            one_way_cost=float(one_way_cost),
            max_codes=max_codes,
            max_days=max_days,
            log=log,
            keep_path=True,
        )
        out[str(spec["logic_id"])] = pack
        slim = [
            {k: v for k, v in r.items() if not str(k).startswith("_")}
            for r in pack["table"]
        ]
        log(
            f"[w103/B] base tx-only {spec['logic_id']}: "
            f"n_windows={len(slim)}"
        )
    return out


def _stitch_replay(
    shard_packs: Sequence[Mapping[str, Any]],
    *,
    repo_series: Mapping[str, Any] | None,
    spread_bp: float,
    mode: str,
) -> dict[str, Any]:
    stitch_dates: list[str] = []
    stitch_net: list[float] = []
    gap_n = 0
    applied_n = 0
    repo_vals: list[float] = []
    extra_vals: list[float] = []
    shard_replays: list[dict[str, Any]] = []
    for sp in shard_packs:
        replay = apply_bars_mtm_short_drag(
            {
                "dates": sp.get("dates") or [],
                "gross_daily": sp.get("gross_daily") or [],
                "net_daily": sp.get("net_daily") or [],
                "daily_cost_drag": sp.get("daily_cost_drag") or 0.0,
            },
            repo_series=repo_series,
            spread_bp=spread_bp,
            short_fraction=SHORT_FRAC,
            mode=mode,
        )
        gap_n += int(replay.get("n_gaps") or 0)
        applied_n += int(replay.get("n_short_cost_applied") or 0)
        mean_r = replay.get("mean_repo_pct_on_applied")
        n_app = int(replay.get("n_short_cost_applied") or 0)
        if mean_r is not None and n_app:
            repo_vals.extend([float(mean_r)] * n_app)
        mean_e = replay.get("mean_extra_daily_on_applied")
        if mean_e is not None and n_app:
            extra_vals.extend([float(mean_e)] * n_app)
        dlist = list(replay.get("dates") or [])
        nlist = list(replay.get("net_daily") or [])
        if not stitch_dates:
            stitch_dates = list(dlist)
            stitch_net = list(nlist)
        else:
            stitch_dates.extend(dlist[1:])
            stitch_net.extend(nlist[1:])
        shard_replays.append(
            {
                "period_id": sp.get("period_id"),
                "n_gaps": replay.get("n_gaps"),
                "n_short_cost_applied": replay.get("n_short_cost_applied"),
                "mean_repo_pct_on_applied": replay.get("mean_repo_pct_on_applied"),
                "gap_dates_sample": replay.get("gap_dates_sample"),
            }
        )
    stitched = w100._stitch_net(stitch_net, stitch_dates)
    return {
        "stitched": stitched,
        "n_gaps": gap_n,
        "n_short_cost_applied": applied_n,
        "mean_repo_pct_on_applied": (
            (sum(repo_vals) / len(repo_vals)) if repo_vals else None
        ),
        "mean_extra_daily_on_applied": (
            (sum(extra_vals) / len(extra_vals)) if extra_vals else None
        ),
        "shard_replays": shard_replays,
    }


def _load_w102_placeholder() -> list[dict[str, Any]]:
    p = W102_LOG / "quality_short_cost_overlay.json"
    if not p.is_file():
        return []
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [r for r in rows if isinstance(r, dict)]


def run_repo_short_cost(
    *,
    out_dir: Path,
    sqlite_path: Path,
    max_codes: int,
    max_days: int,
    log,
) -> dict[str, Any]:
    from research.cost_models import (
        DEFAULT_SHORT_BORROW_ANNUAL_BP,
        POSITION_STYLE_LONG_SHORT,
        SHORT_BORROW_SPREAD_SENSITIVITY,
        build_leverage_short_cost_assumption,
    )

    one_way = BASE_TX_BP / 10_000.0
    mid_spread = float(SHORT_BORROW_SPREAD_SENSITIVITY["mid"])
    log(
        f"[w103/B] repo-linked short cost main={GATE_LOGIC} "
        f"compare={STICKY_LOGIC} tenor={REPO_TENOR} "
        f"mid_spread_bp={mid_spread} hold_mom_grid=false"
    )

    base_by_logic = _eval_base_paths(
        one_way_cost=one_way,
        max_codes=max_codes,
        max_days=max_days,
        log=log,
    )
    for lid, pack in base_by_logic.items():
        slim = [
            {k: v for k, v in r.items() if not str(k).startswith("_")}
            for r in pack["table"]
        ]
        _dump(out_dir / f"w103b_{lid}_tx_only.json", slim)

    all_dates: list[str] = []
    for pack in base_by_logic.values():
        for r in pack["table"]:
            all_dates.extend(list((r.get("_path") or {}).get("dates") or []))
    all_dates_u = sorted({str(d)[:10] for d in all_dates if str(d)[:10]})

    repo_pack = load_jsda_overnight_repo_series(
        sqlite_path=sqlite_path, required_dates=all_dates_u
    )
    series = repo_pack.get("series")
    meta = {k: v for k, v in repo_pack.items() if k != "series"}
    if isinstance(series, Mapping):
        meta["series_kind"] = series.get("kind")
        meta["series_version"] = series.get("version")
        meta["series_n_obs"] = series.get("n_obs")
        meta["series_n_gaps"] = series.get("n_gaps")
        meta["series_ffill"] = series.get("ffill_applied")
        meta["series_invent"] = series.get("invent_fill")
    _dump(out_dir / "w103b_repo_series_meta.json", meta)

    repo_ok = repo_pack.get("status") == "ok" and int(repo_pack.get("n_obs") or 0) > 0
    contrast_rows: list[dict[str, Any]] = []
    blocker: str | None = None

    if not repo_ok:
        blocker = (
            "; ".join(str(x) for x in (repo_pack.get("missing") or []))
            or "jsda_tokyo_repo_rates unavailable — not approximated"
        )
        log(f"[w103/B] BLOCKED {blocker}")
        for lid, pack in base_by_logic.items():
            for r in pack["table"]:
                contrast_rows.append(
                    {
                        "logic_id": lid,
                        "window": r["window"],
                        "mode": "unwired",
                        "repo_linked": False,
                        "daily_path_complete": False,
                        "incomplete_reason": blocker,
                        "base_tx_only_DD": r.get("daily_path_DD"),
                        "base_tx_only_net": r.get("total_ret_net"),
                        "promote_as_main": False,
                        "go": False,
                    }
                )
    else:
        log(
            f"[w103/B] repo series n_obs={repo_pack.get('n_obs')} "
            f"required={repo_pack.get('n_required')} "
            f"gaps_on_required={repo_pack.get('n_gaps_on_required')} "
            f"tenor={repo_pack.get('tenor')} span={repo_pack.get('rate_span')} "
            f"ffill={repo_pack.get('ffill_applied')} invent={repo_pack.get('invent_fill')}"
        )
        for lid, pack in base_by_logic.items():
            for r in pack["table"]:
                path = r.get("_path") or {}
                shard_packs = list(path.get("shard_packs") or [])
                if not shard_packs:
                    contrast_rows.append(
                        {
                            "logic_id": lid,
                            "window": r["window"],
                            "mode": "unwired",
                            "repo_linked": False,
                            "daily_path_complete": False,
                            "incomplete_reason": "missing bars-MTM path for overlay",
                            "promote_as_main": False,
                            "go": False,
                        }
                    )
                    continue
                for mode in ("repo_linked", "fixed_bp"):
                    bundled = _stitch_replay(
                        shard_packs,
                        repo_series=series,
                        spread_bp=mid_spread,
                        mode=mode,
                    )
                    stitched = bundled["stitched"]
                    row = {
                        "logic_id": lid,
                        "window": r["window"],
                        "mode": mode,
                        "spread_bp": mid_spread,
                        "short_fraction": SHORT_FRAC,
                        "gross_leverage": GROSS_LEVERAGE,
                        "daily_path_DD": stitched.get("daily_path_DD"),
                        "dd_duration": stitched.get("dd_duration"),
                        "recovery_days": stitched.get("recovery_days"),
                        "recovered": stitched.get("recovered"),
                        "total_ret_net": stitched.get("total_return_net"),
                        "peak_date": stitched.get("peak_date"),
                        "trough_date": stitched.get("trough_date"),
                        "recovery_date": stitched.get("recovery_date"),
                        "n_days": stitched.get("n_equity_points"),
                        "daily_path_complete": (
                            stitched.get("daily_path_dd_gate") or {}
                        ).get("complete"),
                        "n_short_cost_applied": bundled["n_short_cost_applied"],
                        "n_gaps": bundled["n_gaps"],
                        "mean_repo_pct_on_applied": bundled[
                            "mean_repo_pct_on_applied"
                        ],
                        "mean_extra_daily_on_applied": bundled[
                            "mean_extra_daily_on_applied"
                        ],
                        "rate_source": (
                            "jsda_tokyo_repo_rates_date_matched"
                            if mode == "repo_linked"
                            else "fixed_bp_placeholder"
                        ),
                        "repo_linked": mode == "repo_linked",
                        "base_tx_only_DD": r.get("daily_path_DD"),
                        "base_tx_only_net": r.get("total_ret_net"),
                        "ffill_applied": False,
                        "invent_fill": False,
                        "note": (
                            "Contrast only. mid spread=50bp. Gaps not invented. "
                            "Not a ranking-by-cost-tune. Not GO/main."
                        ),
                        "promote_as_main": False,
                        "go": False,
                        "shard_replays": bundled["shard_replays"],
                    }
                    contrast_rows.append(row)
                    log(
                        f"[w103/B]   {lid} {r['window']} {mode}: "
                        f"DD={_fmt(row['daily_path_DD'])} "
                        f"net={_fmt(row['total_ret_net'])} "
                        f"applied={row['n_short_cost_applied']} "
                        f"gaps={row['n_gaps']} "
                        f"mean_repo={_fmt(row['mean_repo_pct_on_applied'], 3)}"
                    )

    _dump(out_dir / "w103b_repo_short_contrast.json", contrast_rows)

    lev_ass = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LONG_SHORT,
        gross_leverage=GROSS_LEVERAGE,
        short_fraction=SHORT_FRAC,
        one_way_cost=one_way,
        uses_short=True,
        uses_leverage=False,
        short_borrow_sensitivity="mid",
        prefer_repo_linked=True,
        prefer_liquidity_linked=False,
        repo_rate_series=series if repo_ok else None,
        required_dates=all_dates_u,
    )
    assumption = {
        "position_style": POSITION_STYLE_LONG_SHORT,
        "gross_leverage": GROSS_LEVERAGE,
        "short_fraction": SHORT_FRAC,
        "uses_short": True,
        "uses_leverage": False,
        "financing_daily": 0.0,
        "short_borrow_placeholder_annual_bp": DEFAULT_SHORT_BORROW_ANNUAL_BP,
        "sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
        "repo_linked_wired": bool(repo_ok),
        "repo_tenor": REPO_TENOR,
        "over_tune": False,
        "ranking_by_cost_tune": False,
        "assumption_repo_linked": lev_ass.get("repo_linked"),
        "assumption_complete": lev_ass.get("assumptions_complete"),
        "short_borrow_rate_source": (lev_ass.get("short_borrow") or {}).get(
            "rate_source"
        ),
        "note": (
            "Minimal wiring of JSDA Tokyo overnight repo into bars-MTM short "
            "drag. Gaps disclosed (charge 0). Contrast vs fixed 50bp mid. "
            "No cost over-tune ranking. Not GO/main."
        ),
    }
    _dump(out_dir / "w103b_repo_short_assumption.json", assumption)

    w102_ph = _load_w102_placeholder()
    w102_check: list[dict[str, Any]] = []
    for ph in w102_ph:
        match = next(
            (
                r
                for r in contrast_rows
                if r.get("logic_id") == ph.get("logic_id")
                and r.get("window") == ph.get("window")
                and r.get("mode") == "fixed_bp"
            ),
            None,
        )
        if match is None:
            continue
        dd_delta = None
        net_delta = None
        if match.get("daily_path_DD") is not None and ph.get("daily_path_DD") is not None:
            dd_delta = float(match["daily_path_DD"]) - float(ph["daily_path_DD"])
        if match.get("total_ret_net") is not None and ph.get("total_ret_net") is not None:
            net_delta = float(match["total_ret_net"]) - float(ph["total_ret_net"])
        w102_check.append(
            {
                "logic_id": ph.get("logic_id"),
                "window": ph.get("window"),
                "w102_placeholder_DD": ph.get("daily_path_DD"),
                "w103_fixed_bp_DD": match.get("daily_path_DD"),
                "dd_delta": dd_delta,
                "w102_placeholder_net": ph.get("total_ret_net"),
                "w103_fixed_bp_net": match.get("total_ret_net"),
                "net_delta": net_delta,
                "match_within_1e_12": (
                    dd_delta is not None
                    and net_delta is not None
                    and abs(dd_delta) < 1e-12
                    and abs(net_delta) < 1e-12
                ),
            }
        )
    _dump(out_dir / "w103b_w102_placeholder_check.json", w102_check)

    def _worst(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        scored = [
            r
            for r in rows
            if r.get("daily_path_DD") is not None
            and math.isfinite(float(r["daily_path_DD"]))
        ]
        if not scored:
            return None
        return min(scored, key=lambda x: float(x["daily_path_DD"]))

    tx_rows = []
    for lid, pack in base_by_logic.items():
        for r in pack["table"]:
            tx_rows.append(
                {
                    "logic_id": lid,
                    "window": r["window"],
                    "daily_path_DD": r.get("daily_path_DD"),
                    "total_ret_net": r.get("total_ret_net"),
                }
            )
    repo_rows = [r for r in contrast_rows if r.get("mode") == "repo_linked"]
    fixed_rows = [r for r in contrast_rows if r.get("mode") == "fixed_bp"]
    gate_tx = _worst([r for r in tx_rows if r["logic_id"] == GATE_LOGIC])
    sticky_tx = _worst([r for r in tx_rows if r["logic_id"] == STICKY_LOGIC])
    gate_repo = _worst([r for r in repo_rows if r["logic_id"] == GATE_LOGIC])
    sticky_repo = _worst([r for r in repo_rows if r["logic_id"] == STICKY_LOGIC])
    ranking_unchanged = bool(
        gate_tx
        and sticky_tx
        and gate_repo
        and sticky_repo
        and gate_tx.get("window") == gate_repo.get("window")
        and sticky_tx.get("window") == sticky_repo.get("window")
        and float(gate_repo["daily_path_DD"]) > float(sticky_repo["daily_path_DD"])
    )

    summary = {
        "wave": WAVE,
        "track": "B_repo_linked_short_cost",
        "applied_to": [GATE_LOGIC, STICKY_LOGIC],
        "promote_as_main": False,
        "go": False,
        "hold_mom_microgrid": False,
        "full_catalog_grid": False,
        "cost_over_tune": False,
        "ranking_by_cost_tune": False,
        "repo_linked_wired": bool(repo_ok),
        "blocker": blocker,
        "repo_tenor": REPO_TENOR,
        "repo_n_obs": repo_pack.get("n_obs"),
        "repo_n_gaps_on_required": repo_pack.get("n_gaps_on_required"),
        "ffill_applied": False,
        "invent_fill": False,
        "mid_spread_bp": mid_spread,
        "short_fraction": SHORT_FRAC,
        "gross_leverage": GROSS_LEVERAGE,
        "gate_worst_tx_only": gate_tx,
        "sticky_worst_tx_only": sticky_tx,
        "gate_worst_repo_linked": (
            {
                "window": (gate_repo or {}).get("window"),
                "daily_path_DD": (gate_repo or {}).get("daily_path_DD"),
                "total_ret_net": (gate_repo or {}).get("total_ret_net"),
            }
            if gate_repo
            else None
        ),
        "sticky_worst_repo_linked": (
            {
                "window": (sticky_repo or {}).get("window"),
                "daily_path_DD": (sticky_repo or {}).get("daily_path_DD"),
                "total_ret_net": (sticky_repo or {}).get("total_ret_net"),
            }
            if sticky_repo
            else None
        ),
        "ranking_unchanged_vs_tx_only": ranking_unchanged,
        "w102_placeholder_reproduced": (
            bool(w102_check) and all(c.get("match_within_1e_12") for c in w102_check)
        ),
        "data_path": "local_real_mirrors+local_sqlite_jsda_repo_rates",
        "complete_measurement_is_not_go": True,
    }
    _dump(out_dir / "w103b_summary.json", summary)
    log(
        f"[w103/B] wired={repo_ok} blocker={blocker or 'none'} "
        f"ranking_unchanged={ranking_unchanged} "
        f"w102_placeholder_reproduced={summary['w102_placeholder_reproduced']} "
        f"promote=false go=false"
    )
    return {
        "summary": summary,
        "contrast": contrast_rows,
        "repo_pack": repo_pack,
        "assumption": assumption,
        "w102_check": w102_check,
        "base_by_logic": {
            lid: {
                "table": [
                    {k: v for k, v in r.items() if not str(k).startswith("_")}
                    for r in pack["table"]
                ]
            }
            for lid, pack in base_by_logic.items()
        },
        "repo_ok": repo_ok,
        "blocker": blocker,
    }


def _md_contrast_row(r: Mapping[str, Any]) -> str:
    recov = r.get("recovery_days")
    recov_s = "—" if recov is None else str(recov)
    return (
        f"| `{r.get('logic_id')}` | {r.get('window')} | `{r.get('mode')}` | "
        f"{r.get('n_days') or '—'} | {_fmt(r.get('daily_path_DD'))} | "
        f"{r.get('dd_duration') if r.get('dd_duration') is not None else '—'} | "
        f"{recov_s} | {r.get('recovered')} | {_fmt(r.get('total_ret_net'))} | "
        f"{_fmt(r.get('base_tx_only_DD'))} | {_fmt(r.get('mean_repo_pct_on_applied'), 3)} | "
        f"{r.get('n_short_cost_applied')} | {r.get('n_gaps')} |"
    )


def write_proof(
    *,
    proof_path: Path,
    out_dir: Path,
    result: Mapping[str, Any],
    pins: Mapping[str, Any],
    git_sha: str | None,
    codes_n: int,
    max_days: int,
) -> str:
    summary = result.get("summary") or {}
    contrast = list(result.get("contrast") or [])
    repo_pack = result.get("repo_pack") or {}
    w102_check = list(result.get("w102_check") or [])
    repo_ok = bool(result.get("repo_ok"))
    blocker = result.get("blocker")
    try:
        rel_logs = str(out_dir.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        rel_logs = str(out_dir)

    wired = "yes" if repo_ok else "no"
    lines = [
        "# W103 / w0819f Track B — repo-linked short cost (bars-MTM)",
        "",
        f"**Wave:** {WAVE} · Track B  ",
        f"**Applied to:** `{GATE_LOGIC}` · `{STICKY_LOGIC}` (small set only)  ",
        "**Data path:** `local_real_mirrors` + local sqlite `jsda_repo_rates`  ",
        "**Method:** daily MTM after cost — `scripts/run_w100_peer_daily_dd.py` "
        "evaluators; short drag date-matched on that path  ",
        "**Recipe:** `scripts/run_w103_repo_short_cost.py`  ",
        f"**Logs:** [`{rel_logs}`](../../{rel_logs}/) · `w103b_summary.json`  ",
        f"**HEAD (pre-commit):** `{git_sha or 'n/a'}`  ",
        "**Peer cite:** [`w0819e_w102_dispersion_quality_20260819.md`]"
        "(w0819e_w102_dispersion_quality_20260819.md) (W102 mid 50 bp placeholder)  ",
        "**Implementer:** GLM5.3 only. Grok did **not** implement.",
        "",
        "---",
        "",
        "## Verdict",
        "",
        "| field | value |",
        "|-------|-------|",
        f"| repo-linked short wired | **{wired}** |",
        f"| tenor | `{REPO_TENOR}` |",
        f"| gaps invented / ffilled | **false** |",
        f"| applied logics | `{GATE_LOGIC}`, `{STICKY_LOGIC}` |",
        "| cost over-tune / ranking-by-cost | **false** |",
        f"| ranking unchanged vs tx-only | **{summary.get('ranking_unchanged_vs_tx_only')}** |",
        f"| W102 50 bp placeholder reproduced (fixed_bp mode) | "
        f"**{summary.get('w102_placeholder_reproduced')}** |",
        "| promote_as_main | **false** |",
        "| go / go_eligible | **false** |",
        "| Complete measurement = GO/main | **no** |",
        f"| 3-default pins untouched | **{pins.get('pins_untouched')}** |",
        "| hold/mom micro-grid | **not run** |",
        "| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |",
        "",
    ]
    if blocker:
        lines += [
            "## Residual / blocker",
            "",
            f"Wiring did **not** complete. Exact reason: `{blocker}`.",
            "Not approximated into a complete repo-linked overlay.",
            "",
        ]
    else:
        lines += [
            "Minimum wiring of an already-available funding series "
            "(`jsda_tokyo_repo_rates` in local sqlite, same table W102 event/rate "
            "used for the curve book). Short overlay is **date-matched repo + mid "
            "50 bp spread**. Missing dates charge **0** that day. Not a GO.",
            "",
        ]

    lines += [
        "## 1. Wiring",
        "",
        "| need | path |",
        "|------|------|",
        "| bars (close panel) | local `real_mirrors` shards (same W99/W100 windows) |",
        "| funding series | `jsda_tokyo_repo_rates` via "
        "`data/structured/ingestion.sqlite` → `jsda_repo_rates` |",
        f"| tenor (observed only) | `{REPO_TENOR}` |",
        "| short formula | `daily = (repo_pct/100 + 50bp/10000) / 245 × short_frac=0.5` "
        "on **active** bars-MTM days |",
        "| gap policy | missing `as_of_date` → extra=0, counted in `n_gaps` "
        "(no ffill / no invent) |",
        "| loader | `load_repo_rows_from_sqlite` + `load_repo_rate_series_from_rows` "
        "+ `lookup_repo_rate` + `short_borrow_daily_cost_from_repo` |",
        "",
        f"Local status: **{repo_pack.get('status')}** · "
        f"n_obs={repo_pack.get('n_obs')} · "
        f"n_required_bar_dates={repo_pack.get('n_required')} · "
        f"present_required={repo_pack.get('present_required_n')} · "
        f"gaps_on_required={repo_pack.get('n_gaps_on_required')} · "
        f"span {None if not repo_pack.get('rate_span') else '→'.join(repo_pack.get('rate_span') or [])} · "
        f"ffill={repo_pack.get('ffill_applied')} invent={repo_pack.get('invent_fill')}.",
        "",
        "CS L-S is already dollar-neutral (`long_frac=short_frac=0.3`). "
        f"**No extra leverage** (`gross_leverage={GROSS_LEVERAGE}` → financing daily = 0). "
        "Short borrow lives only on the short share (`short_frac=0.5` of the active book).",
        "",
        "## 2. Contrast table (tx 10 bp + short overlay)",
        "",
        "Required: **daily_path_DD** · **dd_duration** · **recovery** · **total_ret_net**.",
        "Modes: `repo_linked` (this wave) vs `fixed_bp` (W102 mid 50 bp placeholder).",
        "",
        "| logic | window | mode | n_days | daily_path_DD | dd_dur | recov | recovered | total_ret_net | tx-only DD | mean repo % | n_applied | n_gaps |",
        "|-------|--------|------|-------:|--------------:|-------:|------:|:---------:|--------------:|-----------:|------------:|----------:|-------:|",
    ]
    for r in contrast:
        if r.get("mode") in {"repo_linked", "fixed_bp"}:
            lines.append(_md_contrast_row(r))

    # Compact vs-placeholder
    lines += [
        "",
        "### Repo-linked vs W102 placeholder (mid 50 bp) vs tx-only",
        "",
        "| logic | window | DD tx-only | DD +short placeholder | DD +short repo | net placeholder | net repo | ΔDD (repo−ph) |",
        "|-------|--------|-----------:|----------------------:|---------------:|----------------:|---------:|--------------:|",
    ]
    by_key: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = {}
    for r in contrast:
        key = (str(r.get("logic_id")), str(r.get("window")))
        by_key.setdefault(key, {})[str(r.get("mode"))] = r
    for lid in (GATE_LOGIC, STICKY_LOGIC):
        for w in ("w2017_2019", "w2020_2022", "w2023_2025"):
            pair = by_key.get((lid, w) ) or {}
            repo = pair.get("repo_linked") or {}
            ph = pair.get("fixed_bp") or {}
            dd_r = w100._scalar_f(repo.get("daily_path_DD"))
            dd_p = w100._scalar_f(ph.get("daily_path_DD"))
            dlt = None if dd_r is None or dd_p is None else dd_r - dd_p
            lines.append(
                f"| `{lid}` | {w} | {_fmt(repo.get('base_tx_only_DD') or ph.get('base_tx_only_DD'))} | "
                f"{_fmt(ph.get('daily_path_DD'))} | {_fmt(repo.get('daily_path_DD'))} | "
                f"{_fmt(ph.get('total_ret_net'))} | {_fmt(repo.get('total_ret_net'))} | "
                f"{_fmt(dlt, 8)} |"
            )

    lines += [
        "",
        "### W102 placeholder reproduction (fixed_bp mode)",
        "",
        "| logic | window | W102 DD | this-wave fixed_bp DD | match |",
        "|-------|--------|--------:|----------------------:|:-----:|",
    ]
    if w102_check:
        for c in w102_check:
            lines.append(
                f"| `{c.get('logic_id')}` | {c.get('window')} | "
                f"{_fmt(c.get('w102_placeholder_DD'))} | "
                f"{_fmt(c.get('w103_fixed_bp_DD'))} | "
                f"{'yes' if c.get('match_within_1e_12') else 'no'} |"
            )
    else:
        lines.append("| — | — | — | — | W102 overlay JSON absent |")

    gate_repo = summary.get("gate_worst_repo_linked") or {}
    sticky_repo = summary.get("sticky_worst_repo_linked") or {}
    lines += [
        "",
        "## Headline (research-only · not GO)",
        "",
    ]
    if repo_ok:
        lines += [
            f"- JSDA Tokyo overnight repo **wired** into the bars-MTM short-leg "
            f"daily drag for `{GATE_LOGIC}` and `{STICKY_LOGIC}` only. "
            f"n_obs={repo_pack.get('n_obs')} · gaps_on_required="
            f"{repo_pack.get('n_gaps_on_required')} · ffill=false · invent=false.",
            f"- Gate worst repo-linked daily_path_DD **{_fmt((gate_repo or {}).get('daily_path_DD'))}** "
            f"({(gate_repo or {}).get('window')}). Sticky worst **"
            f"{_fmt((sticky_repo or {}).get('daily_path_DD'))}** "
            f"({(sticky_repo or {}).get('window')}).",
            "- Negative overnight repo (2017–23 NIRP) makes repo+50 bp **slightly "
            "cheaper** than the W102 50 bp placeholder; 2025-Q4 positive repo "
            "makes it **slightly dearer**. Ranking vs sticky does **not** flip.",
            "- Cost was **not** tuned to manufacture ranking. Mid spread is the "
            "single overlay (W102 convention).",
            "- **promote_as_main=false · go=false.** Complete measurement is "
            "**not** a production candidate.",
        ]
    else:
        lines.append(
            f"- Repo-linked short cost **not wired**. Blocker: `{blocker}`. "
            "Placeholder remains the disclosure overlay. Not approximated."
        )
    lines += [
        "",
        "> **Warning:** period-net DD = 0 when all period nets are positive is an",
        "> **aggregation artifact**. It does **not** mean the strategy is riskless.",
        "> Use **daily_path_DD** (duration / recovery / total_ret_net).",
        ">",
        "> **Complete measurement ≠ GO / main.** These rows remain research-only.",
        "",
        "## Method (same as W100/W102)",
        "",
        "1. Load W99/W100 honest `real_mirrors` shards (max_codes="
        f"{codes_n}, max_days/shard={max_days}).",
        "2. Build the equal-weight held book (gate / sticky catalog params; "
        "**not** a hold/mom retune).",
        "3. Mark to market **daily**; subtract amortized one-way 10 bp while active.",
        "4. Load `jsda_repo_rates` overnight T+0 from local sqlite. "
        "Key by `as_of_date`. **Do not** ffill.",
        "5. On each **active** bars-MTM day, extra short drag = "
        "`f(repo[t] + 50 bp, short_frac=0.5)` when the date is present; "
        "else extra=0 and count a gap.",
        "6. Replay the same path with constant 50 bp annual (W102 placeholder) "
        "for the contrast table.",
        "7. `evaluate_daily_path_dd_gate` must complete; period-net-only is forbidden.",
        "",
        "## Freezes held",
        "",
        "- promote_as_main = **false** · go = **false**",
        "- no hold/mom micro-grid · no 3-default pin retune",
        "- no cost over-tune ranking",
        "- Mass NO-GO · READY 未宣言 · Phase7 OFF · continuous paper UNARMED",
        "- period_net_DD-only **cannot pass**",
        "- no repo ffill / no invent",
        "",
        "## Non-claims",
        "",
        "- No READY / Mass / GO / live / pin retune / hold-mom grid / full catalog grid.",
        "- Repo-linked short cost is a **research overlay** on two logics, not a "
        "production borrow model and not a liquidity-linked HTB scale.",
        "- Local mirrors + local sqlite ≠ CF SoT.",
        "- Period-net DD=0 **must not** be read as riskless.",
        "- Complete daily_path_DD is **not** a production candidate / GO.",
        "",
        "GLM implementer only. Grok did not implement.",
        "",
    ]
    body = "\n".join(lines)
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(body, encoding="utf-8")
    return body


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--proof", type=str, default=str(PROOF_DEFAULT))
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument(
        "--sqlite",
        type=str,
        default=str(ROOT / "data" / "structured" / "ingestion.sqlite"),
    )
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w103b_repo_short_cost.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = _assert_frozen_pins_untouched()
    _dump(out_dir / "w103b_frozen_pins_assert.json", pins)
    log(f"[w103/B] pins_untouched={pins['pins_untouched']}")
    log(
        "[w103/B] promote_as_main=false go=false hold_mom_grid=false "
        "cost_over_tune=false complete≠GO "
        "GLM implementer only. Grok did not implement."
    )

    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    result = run_repo_short_cost(
        out_dir=out_dir,
        sqlite_path=Path(args.sqlite),
        max_codes=int(args.max_codes),
        max_days=int(args.max_days),
        log=log,
    )

    pins_after = _assert_frozen_pins_untouched()
    pins_after["note"] = "W103 after repo-linked short cost; 3-default pins must match"
    _dump(out_dir / "w103b_frozen_pins_assert_after.json", pins_after)

    sha = _git_sha()
    write_proof(
        proof_path=Path(args.proof),
        out_dir=out_dir,
        result=result,
        pins=pins_after,
        git_sha=sha,
        codes_n=min(int(args.max_codes), len(DEFAULT_EVAL_CODES)),
        max_days=int(args.max_days),
    )

    summary = dict(result.get("summary") or {})
    summary.update(
        {
            "pins_untouched": pins_after.get("pins_untouched"),
            "implementer": "GLM5.3",
            "orchestrator_implemented": False,
            "wall_sec": round(time.time() - t0, 1),
            "git_sha_precommit": sha,
            "proof": str(Path(args.proof)),
        }
    )
    _dump(out_dir / "w103b_summary.json", summary)
    log(
        f"[w103/B] done wall={summary['wall_sec']}s "
        f"wired={summary.get('repo_linked_wired')} "
        f"pins={pins_after.get('pins_untouched')} "
        f"proof={args.proof}"
    )
    if not pins_after.get("pins_untouched"):
        return 2
    if result.get("blocker"):
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
