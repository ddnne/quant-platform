"""Offline multi-year class-hypothesis eval (W78 / w0816m).

Runs **multi_day_hold** and **macro_conditioned** research signals over
local bar mirrors + local ``jsda_repo_rates`` SQLite, then feeds cost-aware
robustness gate + checklist v2.

Hard constraints
----------------
* Not simple_daily_sign · no S1–S5 un-reject
* Not READY / Mass / Phase7 / orders
* No invent fill on repo gaps
* research_candidate is never auto-promoted here
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from features.class_signals import (
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    CLASS_SIGNALS_VERSION,
    CLASS_SIGNALS_WAVE,
    DEFAULT_HOLD_DAYS,
    DEFAULT_REPO_HIGH_THRESHOLD,
    DEFAULT_REPO_LOW_THRESHOLD,
    SIGNAL_ID_CROSS_SECTION,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_MULTI_DAY_HOLD,
    SUPPORTED_HOLD_DAYS,
    amortized_one_way_cost,
    apply_sticky_hold,
    class_signal_definitions,
    class_signals_document,
    compute_cross_section_signal,
    compute_macro_conditioned_signal,
    compute_multi_day_hold_signal,
    cross_section_rank_signs,
    multi_day_forward_return,
    sign_from_numeric,
)
from research.cost_models import (
    DEFAULT_ONE_WAY_COST,
    REPO_DATASET_ID,
    annotate_period_rows_with_extended_costs,
    build_leverage_short_cost_assumption,
    default_long_only_unlevered_cost_assumption,
    load_repo_rate_series_from_rows,
    lookup_repo_rate,
    mean_repo_rate_pct,
)
from research.holding_metrics import (
    cost_amortization_report,
    holding_metrics_report,
)
from research.risk_scenarios import (
    SCENARIO_CRASH,
    SCENARIO_HIGH_VOL,
    SCENARIO_LIQUIDITY_STRESS,
    SCENARIO_RATE_DOWN,
    SCENARIO_RATE_UP,
    evaluate_risk_scenarios,
    scenario_row,
)
from research.robustness_gate import evaluate_research_robustness_gate

# ---------------------------------------------------------------------------
# Freeze / identity
# ---------------------------------------------------------------------------

CLASS_HYP_EVAL_VERSION: str = "class-hyp-eval/v1"
CLASS_HYP_EVAL_WAVE: str = CLASS_SIGNALS_WAVE
MASS_RESEARCH: str = "NO-GO"
PHASE7: str = "OFF"
READY_DECLARED: bool = False

# Default codes matching multi-year harness probes.
DEFAULT_EVAL_CODES: tuple[str, ...] = (
    "13010",
    "72030",
    "67580",
    "99840",
    "68610",
    "40630",
    "65010",
    "80350",
    "45020",
    "94320",
    "72670",
    "77510",
    "69020",
    "63670",
    "60980",
    "79740",
    "69810",
    "45680",
    "80010",
    "80020",
    "80580",
    "94330",
    "29140",
    "33820",
    "46610",
    "49010",
    "51080",
    "54010",
    "57130",
    "65030",
)

# Q4 windows used by W63/W64 multi-year path.
DEFAULT_PERIODS: tuple[dict[str, Any], ...] = (
    {"period_id": "y2015_q4", "year": 2015, "period_start": "2015-09-01", "period_end": "2015-12-29"},
    {"period_id": "y2017_q4", "year": 2017, "period_start": "2017-09-01", "period_end": "2017-12-29"},
    {"period_id": "y2019_q4", "year": 2019, "period_start": "2019-09-01", "period_end": "2019-12-29"},
    {"period_id": "y2021_q4", "year": 2021, "period_start": "2021-09-01", "period_end": "2021-12-29"},
    {"period_id": "y2023_q4", "year": 2023, "period_start": "2023-09-01", "period_end": "2023-12-29"},
    {"period_id": "y2025_q4", "year": 2025, "period_start": "2025-09-01", "period_end": "2025-12-29"},
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BARS_MIRROR_DIR: Path = (
    _REPO_ROOT / ".glm-logs" / "w0815bd_w63_multiyear" / "r2_mirror"
)
DEFAULT_SQLITE: Path = _REPO_ROOT / "data" / "structured" / "ingestion.sqlite"


def _freeze() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": False,
        "connected_to_ready": False,
        "connected_to_mass": False,
        "significance_claimed": False,
        "edge_claimed": False,
        "s1_s5_unreject": False,
        "simple_daily_sign": False,
    }


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def load_bars_ndjson(
    path: str | Path,
    *,
    codes: Sequence[str] | None = None,
    max_days: int | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Load equities_bars_daily ndjson → ``{code: [(date, close), ...]}`` sorted."""
    p = Path(path)
    code_filter = {str(c).strip() for c in codes} if codes else None
    by_code: dict[str, dict[str, float]] = {}
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = row.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    continue
            if not isinstance(payload, Mapping):
                continue
            code = str(payload.get("Code") or payload.get("code") or "").strip()
            date = str(payload.get("Date") or payload.get("date") or "")[:10]
            if not code or not date:
                continue
            if code_filter is not None and code not in code_filter:
                continue
            close = payload.get("C")
            if close is None:
                close = payload.get("Close") or payload.get("AdjC")
            try:
                c = float(close)
            except (TypeError, ValueError):
                continue
            by_code.setdefault(code, {})[date] = c

    out: dict[str, list[tuple[str, float]]] = {}
    for code, dmap in by_code.items():
        pairs = sorted(dmap.items(), key=lambda x: x[0])
        if max_days is not None and len(pairs) > int(max_days):
            pairs = pairs[-int(max_days) :]
        out[code] = pairs
    return out


def load_repo_rows_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    start: str | None = None,
    end: str | None = None,
    tenor_contains: str | None = "overnight",
) -> list[dict[str, Any]]:
    """Load jsda_repo_rates rows from local SQLite (research offline path)."""
    db = Path(db_path)
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    try:
        sql = (
            "SELECT as_of_date, tenor, rate_type, rate, available_at, event_time "
            "FROM jsda_repo_rates WHERE rate IS NOT NULL"
        )
        params: list[Any] = []
        if start:
            sql += " AND as_of_date >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND as_of_date <= ?"
            params.append(str(end)[:10])
        if tenor_contains:
            sql += " AND lower(tenor) LIKE ?"
            params.append(f"%{str(tenor_contains).lower()}%")
        sql += " ORDER BY as_of_date ASC"
        cur = con.execute(sql, params)
        rows: list[dict[str, Any]] = []
        for as_of_date, tenor, rate_type, rate, available_at, event_time in cur:
            rows.append(
                {
                    "as_of_date": str(as_of_date)[:10],
                    "tenor": tenor,
                    "rate_type": rate_type,
                    "rate": float(rate) if rate is not None else None,
                    "available_at": available_at,
                    "event_time": event_time,
                }
            )
        return rows
    finally:
        con.close()


def resolve_bars_path(
    period_id: str,
    *,
    mirror_dir: str | Path = DEFAULT_BARS_MIRROR_DIR,
) -> Path | None:
    """Map period_id like y2015_q4 → local ndjson mirror path if present."""
    d = Path(mirror_dir)
    # Prefer q4 mirrors from W63; fall back to full if present (W64).
    year = None
    for token in str(period_id).split("_"):
        if token.startswith("y") and token[1:].isdigit():
            year = int(token[1:])
            break
    if year is None and period_id.isdigit():
        year = int(period_id)
    if year is None:
        return None
    candidates = [
        d / f"equities_bars_daily_y{year}_q4.ndjson",
        d / f"equities_bars_daily_y{year}_full.ndjson",
        # W64 full mirrors live under cost_full
        _REPO_ROOT
        / ".glm-logs"
        / "w0815be_w64_cost_full"
        / "r2_mirror"
        / f"equities_bars_daily_y{year}_full.ndjson",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


# ---------------------------------------------------------------------------
# Momentum + hold panel pure compute
# ---------------------------------------------------------------------------


def momentum_series(
    closes: Sequence[tuple[str, float]],
    *,
    n: int,
) -> list[tuple[str, float | None]]:
    """Per-date momentum_n from sorted (date, close) pairs."""
    n_i = int(n)
    out: list[tuple[str, float | None]] = []
    for i, (d, _) in enumerate(closes):
        if i < n_i:
            out.append((d, None))
            continue
        base = closes[i - n_i][1]
        last = closes[i][1]
        if base == 0:
            out.append((d, None))
        else:
            out.append((d, (last - base) / base))
    return out


def evaluate_multi_day_hold_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    hold_days: int = DEFAULT_HOLD_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    rebalance_mode: str = "fixed_horizon",
) -> dict[str, Any]:
    """Evaluate multi_day_hold signal on an in-memory bars panel.

    Entry = sign(momentum_n) with n=hold_days; sticky hold; gross = mean of
    sign * hold-horizon forward return on rebalance days only.
    Cost net uses amortized one-way over hold_days.
    """
    h = int(hold_days)
    if h < 1:
        raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")
    am_cost = amortized_one_way_cost(one_way_cost, h)

    signed_returns: list[float] = []
    holding_records: list[dict[str, Any]] = []
    n_rebalance = 0
    n_active = 0
    per_code_stats: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 2:
            continue
        moms = momentum_series(pairs_l, n=h)
        entry_signs = [sign_from_numeric(m) for _, m in moms]
        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode=rebalance_mode
        )
        closes = [c for _, c in pairs_l]
        dates = [d for d, _ in pairs_l]
        code_signed: list[float] = []
        for i, pos in enumerate(held):
            holding_records.append(
                {
                    "date": dates[i],
                    "code": code,
                    "sign": pos,
                }
            )
            if pos is None or pos == 0.0:
                continue
            # Only score on rebalance boundaries for fixed_horizon.
            if rebalance_mode == "fixed_horizon" and i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_rebalance += 1
            n_active += 1
            sr = float(pos) * float(fwd)
            signed_returns.append(sr)
            code_signed.append(sr)
        if code_signed:
            per_code_stats.append(
                {
                    "code": code,
                    "n": len(code_signed),
                    "gross_mean": mean(code_signed),
                }
            )

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    # dailyized residual illustration (research only)
    net_daily = (gross - one_way_cost) if gross is not None else None

    return {
        "signal_id": SIGNAL_ID_MULTI_DAY_HOLD,
        "hypothesis_class": CLASS_MULTI_DAY_HOLD,
        "hold_days": h,
        "rebalance_mode": rebalance_mode,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "net_daily_flip_cost_illustration": net_daily,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_rebalance_events": n_rebalance,
        "n_signed_returns": len(signed_returns),
        "n_codes": len(bars_by_code),
        "per_code_sample": per_code_stats[:10],
        "holding_records": holding_records,
        "non_null": n_active,
        "non_null_rate": (
            float(n_active) / float(len(holding_records))
            if holding_records
            else None
        ),
        **_freeze(),
        "note": (
            f"Multi-day hold n={h}: sticky fixed_horizon; "
            "gross = mean(sign * R_hold); net = gross - one_way/hold_days. "
            "Not READY / not Mass."
        ),
    }


def evaluate_macro_conditioned_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    repo_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 5,
    mode: str = "rate_change",
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
) -> dict[str, Any]:
    """Evaluate macro_conditioned signal using bars + repo rate series.

    Uses daily momentum entry, conditions on repo regime (level or change),
    scores next-session return (T→T+1) when conditioned signal is active.
    Cost: full one-way per active day (conservative; daily condition check).
    """
    n = int(momentum_n)
    h = int(hold_days)
    signed_returns: list[float] = []
    n_active = 0
    n_regime_gap = 0
    n_conditioned_null = 0
    regime_counts: dict[str, int] = {}
    holding_records: list[dict[str, Any]] = []

    # Build prev repo map by sorted dates
    rates_by_date = dict((repo_series or {}).get("rates_by_date") or {})
    repo_dates = sorted(rates_by_date.keys())
    prev_map: dict[str, float | None] = {}
    for i, d in enumerate(repo_dates):
        prev_map[d] = rates_by_date[repo_dates[i - 1]] if i > 0 else None

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < n + 2:
            continue
        moms = momentum_series(pairs_l, n=n)
        closes = [c for _, c in pairs_l]
        for i, (d, mom) in enumerate(moms):
            if i + 1 >= len(closes):
                break
            # Lookup repo for date; gap → honest null (no invent)
            hit = lookup_repo_rate(repo_series, d)
            if hit.get("is_gap"):
                n_regime_gap += 1
                holding_records.append(
                    {"date": d, "code": code, "sign": None, "regime_gap": True}
                )
                continue
            rate = hit.get("rate_pct")
            # prev: prior calendar repo date or prior bar date lookup
            prev_rate = prev_map.get(str(d)[:10])
            if prev_rate is None and repo_dates:
                # find last repo date < d
                earlier = [x for x in repo_dates if x < str(d)[:10]]
                if earlier:
                    prev_rate = rates_by_date.get(earlier[-1])

            rec = compute_macro_conditioned_signal(
                momentum=mom,
                repo_rate=rate,
                prev_repo_rate=prev_rate,
                is_trading_day=1.0,
                mode=mode,
                high_threshold=high_threshold,
                low_threshold=low_threshold,
                code=code,
                date=d,
            )
            val = rec.get("value")
            regime = rec.get("regime")
            if regime is not None:
                regime_counts[str(regime)] = regime_counts.get(str(regime), 0) + 1
            holding_records.append(
                {
                    "date": d,
                    "code": code,
                    "sign": val,
                    "regime": regime,
                    "repo_rate": rate,
                }
            )
            if val is None or val == 0.0:
                n_conditioned_null += 1
                continue
            # next-day return (conservative daily re-check of regime)
            c0 = closes[i]
            c1 = closes[i + 1]
            if c0 is None or c1 is None or c0 == 0:
                continue
            r1 = (float(c1) / float(c0)) - 1.0
            n_active += 1
            signed_returns.append(float(val) * r1)

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - float(one_way_cost)) if gross is not None else None

    return {
        "signal_id": SIGNAL_ID_MACRO_CONDITIONED,
        "hypothesis_class": CLASS_MACRO_CONDITIONED,
        "mode": mode,
        "momentum_n": n,
        "hold_days_documented": h,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_regime_gap": n_regime_gap,
        "n_conditioned_null": n_conditioned_null,
        "regime_counts": regime_counts,
        "n_codes": len(bars_by_code),
        "holding_records": holding_records,
        "non_null": n_active,
        "non_null_rate": (
            float(n_active) / float(len(holding_records))
            if holding_records
            else None
        ),
        "repo_dataset": REPO_DATASET_ID,
        **_freeze(),
        "note": (
            f"Macro-conditioned momentum mode={mode} on jsda_tokyo_repo_rates. "
            "Repo gaps → no trade (no invent). Not READY / not Mass."
        ),
    }


def evaluate_cross_section_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    momentum_n: int = 5,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
) -> dict[str, Any]:
    """Optional third: cross-section relative rank L-S on momentum."""
    n = int(momentum_n)
    # Align by date
    by_date: dict[str, dict[str, float | None]] = {}
    close_by: dict[str, dict[str, float]] = {}
    for code, pairs in bars_by_code.items():
        moms = momentum_series(list(pairs), n=n)
        for d, m in moms:
            by_date.setdefault(d, {})[code] = m
        for d, c in pairs:
            close_by.setdefault(code, {})[d] = c

    dates = sorted(by_date.keys())
    signed_returns: list[float] = []
    n_active = 0
    for i, d in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        ranks = cross_section_rank_signs(
            by_date[d], long_frac=long_frac, short_frac=short_frac
        )
        for code, sign in ranks.items():
            if sign is None or sign == 0.0:
                continue
            c0 = close_by.get(code, {}).get(d)
            c1 = close_by.get(code, {}).get(nxt)
            if c0 is None or c1 is None or c0 == 0:
                continue
            r1 = (float(c1) / float(c0)) - 1.0
            n_active += 1
            signed_returns.append(float(sign) * r1)

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - float(one_way_cost)) if gross is not None else None
    return {
        "signal_id": SIGNAL_ID_CROSS_SECTION,
        "hypothesis_class": "cross_section_relative",
        "momentum_n": n,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        **_freeze(),
        "note": "Optional cross-section rank L-S. Not READY / not Mass.",
    }


# ---------------------------------------------------------------------------
# Multi-year runner
# ---------------------------------------------------------------------------


def run_class_hyp_multi_year_eval(
    periods: Sequence[Mapping[str, Any]] | None = None,
    *,
    codes: Sequence[str] | None = None,
    hold_days: int = DEFAULT_HOLD_DAYS,
    macro_mode: str = "rate_change",
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    mirror_dir: str | Path = DEFAULT_BARS_MIRROR_DIR,
    sqlite_path: str | Path = DEFAULT_SQLITE,
    include_cross_section: bool = True,
    max_days: int = 80,
    min_periods_gate: int = 2,
    min_active_per_period: int = 20,
    apply_robustness_gate: bool = True,
) -> dict[str, Any]:
    """Multi-year offline eval for multi_day_hold + macro_conditioned (+ optional xs).

    Uses local W63/W64 bar mirrors and local SQLite jsda_repo_rates.
    """
    period_list = [dict(p) for p in (periods or DEFAULT_PERIODS)]
    selected = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else list(DEFAULT_EVAL_CODES)
    )
    h = int(hold_days)
    if h not in SUPPORTED_HOLD_DAYS:
        # allow other positive holds but document
        if h < 1:
            raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")

    # Load full repo series once (research offline; as_of_date keyed).
    # PIT note: bulk available_at is 2026 ingest — research uses as_of_date
    # as the visibility key with explicit disclosure (no invent).
    repo_rows = load_repo_rows_from_sqlite(sqlite_path)
    repo_series = (
        load_repo_rate_series_from_rows(repo_rows) if repo_rows else None
    )
    repo_load_note = {
        "source": "local_sqlite_jsda_repo_rates",
        "path": str(sqlite_path),
        "n_rows": len(repo_rows),
        "series_n_dates": (
            len((repo_series or {}).get("rates_by_date") or {})
            if repo_series
            else 0
        ),
        "pit_disclosure": (
            "Local jsda_repo_rates rows carry bulk-ingest available_at "
            "(2026). Offline multi-year research keys regime by as_of_date "
            "(event date), not bulk available_at. Disclosed; no invent fill."
        ),
        "dataset": REPO_DATASET_ID,
    }

    results_md: list[dict[str, Any]] = []
    results_macro: list[dict[str, Any]] = []
    results_xs: list[dict[str, Any]] = []

    for raw in period_list:
        p = dict(raw)
        pid = str(p.get("period_id") or p.get("year") or "period")
        year = p.get("year")
        bars_path = p.get("bars_path") or resolve_bars_path(
            pid, mirror_dir=mirror_dir
        )
        if bars_path is None or not Path(bars_path).exists():
            skip = {
                "period_id": pid,
                "year": year,
                "status": "skipped",
                "skip_reason": f"bars mirror missing for {pid}",
            }
            results_md.append(skip)
            results_macro.append(dict(skip))
            if include_cross_section:
                results_xs.append(dict(skip))
            continue

        try:
            bars = load_bars_ndjson(
                bars_path, codes=selected, max_days=max_days
            )
            if not bars:
                raise RuntimeError("no bars after code filter")

            md = evaluate_multi_day_hold_on_bars(
                bars,
                hold_days=h,
                one_way_cost=one_way_cost,
            )
            md_row = {
                "period_id": pid,
                "year": year,
                "status": "ok",
                "period_start": p.get("period_start"),
                "period_end": p.get("period_end"),
                "bars_path": str(bars_path),
                "n_codes": md.get("n_codes"),
                "gross_signed_mean_active": md.get("gross_signed_mean_active"),
                "net_one_way_mean_active": md.get("net_one_way_mean_active"),
                "n_active_positions": md.get("n_active_positions"),
                "non_null": md.get("non_null"),
                "non_null_rate": md.get("non_null_rate"),
                "amortized_one_way_cost": md.get("amortized_one_way_cost"),
                "hold_days": h,
                "signal_id": SIGNAL_ID_MULTI_DAY_HOLD,
                "holding_records": md.get("holding_records"),
            }
            results_md.append(md_row)

            macro = evaluate_macro_conditioned_on_bars(
                bars,
                repo_series,
                momentum_n=h,
                hold_days=h,
                mode=macro_mode,
                one_way_cost=one_way_cost,
            )
            macro_row = {
                "period_id": pid,
                "year": year,
                "status": "ok",
                "period_start": p.get("period_start"),
                "period_end": p.get("period_end"),
                "bars_path": str(bars_path),
                "n_codes": macro.get("n_codes"),
                "gross_signed_mean_active": macro.get(
                    "gross_signed_mean_active"
                ),
                "net_one_way_mean_active": macro.get("net_one_way_mean_active"),
                "n_active_positions": macro.get("n_active_positions"),
                "non_null": macro.get("non_null"),
                "non_null_rate": macro.get("non_null_rate"),
                "n_regime_gap": macro.get("n_regime_gap"),
                "regime_counts": macro.get("regime_counts"),
                "mode": macro_mode,
                "signal_id": SIGNAL_ID_MACRO_CONDITIONED,
                "holding_records": macro.get("holding_records"),
            }
            results_macro.append(macro_row)

            if include_cross_section:
                xs = evaluate_cross_section_on_bars(
                    bars, momentum_n=h, one_way_cost=one_way_cost
                )
                results_xs.append(
                    {
                        "period_id": pid,
                        "year": year,
                        "status": "ok",
                        "gross_signed_mean_active": xs.get(
                            "gross_signed_mean_active"
                        ),
                        "net_one_way_mean_active": xs.get(
                            "net_one_way_mean_active"
                        ),
                        "n_active_positions": xs.get("n_active_positions"),
                        "non_null": xs.get("n_active_positions"),
                        "signal_id": SIGNAL_ID_CROSS_SECTION,
                    }
                )
        except Exception as exc:  # noqa: BLE001 — year isolation
            err = {
                "period_id": pid,
                "year": year,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
            results_md.append(err)
            results_macro.append(dict(err))
            if include_cross_section:
                results_xs.append(dict(err))

    def _gate(rows: list[dict[str, Any]], signal_id: str) -> dict[str, Any] | None:
        if not apply_robustness_gate:
            return None
        period_rows = [
            {
                "period_id": r["period_id"],
                "status": "ok",
                "gross_signed_mean_active": r.get("gross_signed_mean_active"),
                "net_one_way_mean_active": r.get("net_one_way_mean_active"),
                "n_active_positions": r.get("n_active_positions")
                or r.get("non_null"),
                "non_null": r.get("non_null"),
                "non_null_rate": r.get("non_null_rate"),
            }
            for r in rows
            if r.get("status") == "ok"
            and r.get("gross_signed_mean_active") is not None
        ]
        if not period_rows:
            return {
                "passed": False,
                "signal_id": signal_id,
                "reason": "no_ok_periods_with_gross",
                "research_candidate": False,
            }
        return evaluate_research_robustness_gate(
            period_rows,
            signal_id=signal_id,
            min_periods=min_periods_gate,
            min_active_per_period=min_active_per_period,
            one_way_cost=one_way_cost,
            require_net_sign_majority=True,
        )

    gate_md = _gate(results_md, SIGNAL_ID_MULTI_DAY_HOLD)
    gate_macro = _gate(results_macro, SIGNAL_ID_MACRO_CONDITIONED)
    gate_xs = (
        _gate(results_xs, SIGNAL_ID_CROSS_SECTION)
        if include_cross_section
        else None
    )

    # Cost assumptions: multi_day_hold long-only unlevered; macro may short.
    cost_md = default_long_only_unlevered_cost_assumption(
        one_way_cost=one_way_cost
    )
    cost_macro = build_leverage_short_cost_assumption(
        position_style="long_short",
        gross_leverage=1.0,
        short_fraction=0.5,
        one_way_cost=one_way_cost,
        uses_short=True,
        uses_leverage=False,
    )
    # Prefer repo mean for period when series present (repo-linked Task A).
    if repo_series is not None:
        mean_repo = mean_repo_rate_pct(repo_series)
        cost_macro["repo_linked"] = {
            "preferred": True,
            "dataset": REPO_DATASET_ID,
            "mean_rate_pct": mean_repo.get("mean_rate_pct"),
            "mean_annual_bp": mean_repo.get("mean_annual_bp"),
            "n_obs": mean_repo.get("n_obs"),
            "note": (
                "Task A cost_models v2 prefers date-matched repo rates; "
                "period-level mean disclosed for short/financing context."
            ),
        }
    else:
        cost_macro["repo_linked"] = {
            "preferred": True,
            "available": False,
            "fallback": "fixed_bp_placeholder",
        }

    # Holding metrics for multi_day_hold (near-required; multi-day is not HF daily)
    holding_md = None
    md_hold_recs: list[dict[str, Any]] = []
    for r in results_md:
        if r.get("status") == "ok" and r.get("holding_records"):
            md_hold_recs.extend(list(r["holding_records"]))
    if md_hold_recs:
        holding_md = holding_metrics_report(
            md_hold_recs, one_way_cost=one_way_cost
        )

    # Risk scenarios from period gross panels (honest)
    def _scen_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ok = [
            r
            for r in rows
            if r.get("status") == "ok"
            and r.get("gross_signed_mean_active") is not None
        ]
        if not ok:
            return [
                scenario_row(
                    SCENARIO_CRASH,
                    not_applicable=True,
                    na_reason="no ok periods",
                ),
                scenario_row(
                    SCENARIO_HIGH_VOL,
                    not_applicable=True,
                    na_reason="no ok periods",
                ),
                scenario_row(
                    SCENARIO_RATE_UP,
                    not_applicable=True,
                    na_reason="insufficient",
                ),
                scenario_row(
                    SCENARIO_RATE_DOWN,
                    not_applicable=True,
                    na_reason="insufficient",
                ),
                scenario_row(
                    SCENARIO_LIQUIDITY_STRESS,
                    not_applicable=True,
                    na_reason="no liq data",
                ),
            ]
        grosses = [float(r["gross_signed_mean_active"]) for r in ok]
        nets = [
            float(r["net_one_way_mean_active"])
            if r.get("net_one_way_mean_active") is not None
            else float(r["gross_signed_mean_active"]) - float(one_way_cost)
            for r in ok
        ]
        # crash proxy: worst period; high_vol proxy: highest |gross|
        worst_i = min(range(len(grosses)), key=lambda i: grosses[i])
        vol_i = max(range(len(grosses)), key=lambda i: abs(grosses[i]))
        # rate scenarios from macro regime years when available
        return [
            scenario_row(
                SCENARIO_CRASH,
                gross_signed_mean=grosses[worst_i],
                net_one_way_mean=nets[worst_i],
            ),
            scenario_row(
                SCENARIO_HIGH_VOL,
                gross_signed_mean=grosses[vol_i],
                net_one_way_mean=nets[vol_i],
            ),
            scenario_row(
                SCENARIO_RATE_UP,
                gross_signed_mean=mean(grosses),
                net_one_way_mean=mean(nets),
                notes="proxy: overall mean (rate_up slice not fully segmented)",
            ),
            scenario_row(
                SCENARIO_RATE_DOWN,
                gross_signed_mean=mean(grosses),
                net_one_way_mean=mean(nets),
                notes="proxy: overall mean (rate_down slice not fully segmented)",
            ),
            scenario_row(
                SCENARIO_LIQUIDITY_STRESS,
                not_applicable=True,
                na_reason="no liquidity stress dataset in this offline path",
            ),
        ]

    risk_md = evaluate_risk_scenarios(
        _scen_from_rows(results_md),
        rate_data_usable=True,
        liquidity_data_available=False,
        prefer_fail_on_sign_break=True,
        signal_id=SIGNAL_ID_MULTI_DAY_HOLD,
    )
    risk_macro = evaluate_risk_scenarios(
        _scen_from_rows(results_macro),
        rate_data_usable=True,
        liquidity_data_available=False,
        prefer_fail_on_sign_break=True,
        signal_id=SIGNAL_ID_MACRO_CONDITIONED,
    )

    def _candidate_verdict(
        gate: dict[str, Any] | None,
        risk: dict[str, Any] | None,
        *,
        n_ok: int,
    ) -> dict[str, Any]:
        gate_pass = bool(gate and gate.get("passed"))
        risk_ok = bool(risk and risk.get("research_candidate_allowed"))
        # Never auto-promote; honest discussion allowance only.
        allowed = bool(gate_pass and risk_ok and n_ok >= min_periods_gate)
        return {
            "research_candidate": False,  # harness never auto-promotes
            "research_candidate_allowed": allowed,
            "gate_passed": gate_pass,
            "risk_scenarios_ok": risk_ok,
            "n_ok_periods": n_ok,
            "verdict": (
                "not_candidate"
                if not allowed
                else "discussion_only_not_auto_promoted"
            ),
            "ready_declared": False,
            "mass_research": MASS_RESEARCH,
            "note": (
                "Even if allowed=True, research_candidate stays False "
                "(no auto-promote). Pass ≠ READY/Mass."
            ),
        }

    n_ok_md = sum(1 for r in results_md if r.get("status") == "ok")
    n_ok_macro = sum(1 for r in results_macro if r.get("status") == "ok")
    n_ok_xs = sum(1 for r in results_xs if r.get("status") == "ok")

    # Strip heavy holding_records from period tables for summary export
    def _compact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for r in rows:
            c = {k: v for k, v in r.items() if k != "holding_records"}
            out.append(c)
        return out

    return {
        "version": CLASS_HYP_EVAL_VERSION,
        "wave": CLASS_HYP_EVAL_WAVE,
        "class_signals": class_signals_document(),
        "definitions": class_signal_definitions(
            hold_days=h, macro_mode=macro_mode
        ),
        "hold_days": h,
        "macro_mode": macro_mode,
        "codes": selected,
        "one_way_cost": float(one_way_cost),
        "one_way_cost_bp": float(one_way_cost) * 10_000.0,
        "repo_load": repo_load_note,
        "multi_day_hold": {
            "signal_id": SIGNAL_ID_MULTI_DAY_HOLD,
            "hypothesis_class": CLASS_MULTI_DAY_HOLD,
            "years": _compact(results_md),
            "cross_year_table": _compact(
                [r for r in results_md if r.get("status") == "ok"]
            ),
            "robustness_gate": gate_md,
            "cost_assumption": cost_md,
            "cost_amortization": cost_amortization_report(
                one_way_cost=one_way_cost
            ),
            "holding": holding_md,
            "risk_scenarios": risk_md,
            "candidate": _candidate_verdict(gate_md, risk_md, n_ok=n_ok_md),
        },
        "macro_conditioned": {
            "signal_id": SIGNAL_ID_MACRO_CONDITIONED,
            "hypothesis_class": CLASS_MACRO_CONDITIONED,
            "years": _compact(results_macro),
            "cross_year_table": _compact(
                [r for r in results_macro if r.get("status") == "ok"]
            ),
            "robustness_gate": gate_macro,
            "cost_assumption": cost_macro,
            "risk_scenarios": risk_macro,
            "candidate": _candidate_verdict(
                gate_macro, risk_macro, n_ok=n_ok_macro
            ),
        },
        "cross_section_relative": (
            {
                "signal_id": SIGNAL_ID_CROSS_SECTION,
                "hypothesis_class": "cross_section_relative",
                "years": _compact(results_xs),
                "robustness_gate": gate_xs,
                "candidate": _candidate_verdict(
                    gate_xs, None, n_ok=n_ok_xs
                ),
            }
            if include_cross_section
            else None
        ),
        "n_years_requested": len(period_list),
        "n_years_ok_multi_day_hold": n_ok_md,
        "n_years_ok_macro_conditioned": n_ok_macro,
        "history_source": "local_r2_mirror_ndjson + local_sqlite_jsda_repo_rates",
        "label": "研究用・複数年クラス仮説評価・未宣言",
        **_freeze(),
        "note": (
            "W78 class hyp multi-year offline eval. multi_day_hold + "
            "macro_conditioned (+ optional cross_section). Uses amortized "
            "cost for multi-day hold and repo-linked cost_models v2 for macro "
            "short context. research_candidate never auto-promoted. "
            "Not READY / Mass NO-GO / Phase7 OFF."
        ),
    }


__all__ = [
    "CLASS_HYP_EVAL_VERSION",
    "CLASS_HYP_EVAL_WAVE",
    "DEFAULT_BARS_MIRROR_DIR",
    "DEFAULT_EVAL_CODES",
    "DEFAULT_PERIODS",
    "DEFAULT_SQLITE",
    "evaluate_cross_section_on_bars",
    "evaluate_macro_conditioned_on_bars",
    "evaluate_multi_day_hold_on_bars",
    "load_bars_ndjson",
    "load_repo_rows_from_sqlite",
    "momentum_series",
    "resolve_bars_path",
    "run_class_hyp_multi_year_eval",
]
