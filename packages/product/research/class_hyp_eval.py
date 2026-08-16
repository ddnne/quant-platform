"""Offline multi-year class-hypothesis eval (W78 / w0816m · W79 / w0816n).

Runs class research signals over local bar mirrors + local SQLite
(``jsda_repo_rates``, ``fins_summary``, margin/short), then feeds
cost-aware robustness gate + checklist v2 + economic-net candidate bar.

Classes covered
---------------
* multi_day_hold · macro_conditioned · cross_section_relative (improve)
* event_post · flow_demand · fundamentals_price (W79 remaining)

Hard constraints
----------------
* Not simple_daily_sign · no S1–S5 un-reject
* Not READY / Mass / Phase7 / orders
* No invent fill on repo / fins / margin gaps
* research_candidate is never auto-promoted here
* weak consistent-negative is **not_candidate** (economic net bar)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from features.class_signals import (
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    CLASS_SIGNALS_VERSION,
    CLASS_SIGNALS_WAVE,
    DEFAULT_EVENT_POST_HOLD_DAYS,
    DEFAULT_FLOW_HOLD_DAYS,
    DEFAULT_FUND_HOLD_DAYS,
    DEFAULT_FUND_MOMENTUM_N,
    DEFAULT_HOLD_DAYS,
    DEFAULT_MIN_ECONOMIC_NET,
    DEFAULT_REPO_HIGH_THRESHOLD,
    DEFAULT_REPO_LOW_THRESHOLD,
    SIGNAL_ID_CROSS_SECTION,
    SIGNAL_ID_EVENT_POST,
    SIGNAL_ID_FLOW_DEMAND,
    SIGNAL_ID_FUNDAMENTALS_PRICE,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_MULTI_DAY_HOLD,
    SUPPORTED_HOLD_DAYS,
    amortized_one_way_cost,
    apply_sticky_hold,
    class_signal_definitions,
    class_signals_document,
    compute_event_post_signal,
    compute_flow_demand_signal,
    compute_fundamentals_price_signal,
    compute_macro_conditioned_signal,
    cross_section_rank_signs,
    earnings_surprise_proxy,
    economic_net_meaningful,
    fundamental_value_score,
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

CLASS_HYP_EVAL_VERSION: str = "class-hyp-eval/v2"
CLASS_HYP_EVAL_WAVE: str = CLASS_SIGNALS_WAVE
MASS_RESEARCH: str = "NO-GO"
PHASE7: str = "OFF"
READY_DECLARED: bool = False
# Economic net bar (research): weak consistent-negative never candidate.
MIN_ECONOMIC_NET: float = DEFAULT_MIN_ECONOMIC_NET

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


def _period_year(period_id: str) -> int | None:
    for token in str(period_id).split("_"):
        if token.startswith("y") and token[1:].isdigit():
            return int(token[1:])
    if str(period_id).isdigit():
        return int(period_id)
    return None


def resolve_bars_path(
    period_id: str,
    *,
    mirror_dir: str | Path = DEFAULT_BARS_MIRROR_DIR,
) -> Path | None:
    """Map period_id like y2015_q4 → local ndjson mirror path if present."""
    d = Path(mirror_dir)
    year = _period_year(period_id)
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


def resolve_margin_path(
    period_id: str,
    *,
    mirror_dir: str | Path = DEFAULT_BARS_MIRROR_DIR,
) -> Path | None:
    """Map period_id → markets_margin_interest local ndjson if present."""
    d = Path(mirror_dir)
    year = _period_year(period_id)
    if year is None:
        return None
    candidates = [
        d / f"markets_margin_interest_y{year}_q4.ndjson",
        d / f"markets_margin_interest_y{year}_full.ndjson",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def load_margin_ndjson(
    path: str | Path,
    *,
    codes: Sequence[str] | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Load markets_margin_interest ndjson → ``{code: [(date, total_vol), ...]}``.

    total_vol = LongVol + ShrtVol when both present, else LongVol or ShrtVol.
    """
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
            long_v = payload.get("LongVol")
            shrt_v = payload.get("ShrtVol")
            total = None
            try:
                if long_v is not None and shrt_v is not None:
                    total = float(long_v) + float(shrt_v)
                elif long_v is not None:
                    total = float(long_v)
                elif shrt_v is not None:
                    total = float(shrt_v)
            except (TypeError, ValueError):
                continue
            if total is None:
                continue
            by_code.setdefault(code, {})[date] = total
    out: dict[str, list[tuple[str, float]]] = {}
    for code, dmap in by_code.items():
        out[code] = sorted(dmap.items(), key=lambda x: x[0])
    return out


def load_margin_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Load margin interest levels from jquants_records (research offline)."""
    db = Path(db_path)
    if not db.exists():
        return {}
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'markets_margin_interest'"
        )
        params: list[Any] = []
        if start:
            sql += " AND event_time >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND event_time <= ?"
            params.append(str(end)[:10] + "T23:59:59")
        if code_list:
            # natural_key is JSON {"Code":"...","Date":"..."} — LIKE filter
            clauses = " OR ".join(["natural_key LIKE ?" for _ in code_list])
            sql += f" AND ({clauses})"
            params.extend([f'%"{c}"%' for c in code_list])
        sql += " ORDER BY event_time ASC"
        cur = con.execute(sql, params)
        by_code: dict[str, dict[str, float]] = {}
        code_set = set(code_list) if code_list else None
        for natural_key, event_time, payload in cur:
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            code = str(pl.get("Code") or "").strip()
            if not code:
                continue
            if code_set is not None and code not in code_set:
                continue
            date = str(pl.get("Date") or str(event_time or "")[:10])[:10]
            if not date:
                continue
            long_v = pl.get("LongVol")
            shrt_v = pl.get("ShrtVol")
            try:
                if long_v is not None and shrt_v is not None:
                    total = float(long_v) + float(shrt_v)
                elif long_v is not None:
                    total = float(long_v)
                elif shrt_v is not None:
                    total = float(shrt_v)
                else:
                    continue
            except (TypeError, ValueError):
                continue
            by_code.setdefault(code, {})[date] = total
        return {
            c: sorted(dmap.items(), key=lambda x: x[0]) for c, dmap in by_code.items()
        }
    finally:
        con.close()


def load_short_ratio_series_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    section: str = "0050",
    start: str | None = None,
    end: str | None = None,
) -> list[tuple[str, float]]:
    """Load market-level short ratio for one S33 section → sorted (date, ratio)."""
    db = Path(db_path)
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT event_time, payload FROM jquants_records "
            "WHERE dataset = 'markets_short_ratio' AND natural_key LIKE ?"
        )
        params: list[Any] = [f'%"{section}"%']
        if start:
            sql += " AND event_time >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND event_time <= ?"
            params.append(str(end)[:10] + "T23:59:59")
        sql += " ORDER BY event_time ASC"
        out: dict[str, float] = {}
        for event_time, payload in con.execute(sql, params):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            date = str(pl.get("Date") or str(event_time or "")[:10])[:10]
            if not date:
                continue
            try:
                with_r = float(pl.get("ShrtWithResVa") or 0.0)
                no_r = float(pl.get("ShrtNoResVa") or 0.0)
                sell = float(pl.get("SellExShortVa") or 0.0)
            except (TypeError, ValueError):
                continue
            if sell == 0.0:
                continue
            out[date] = (with_r + no_r) / sell
        return sorted(out.items(), key=lambda x: x[0])
    finally:
        con.close()


def load_fins_events_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load fins_summary disclosure events → ``{code: [event_dict, ...]}``.

    Each event: disc_date, eps, feps, bps, prior_eps (filled after sort).
    """
    db = Path(db_path)
    if not db.exists():
        return {}
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'fins_summary'"
        )
        params: list[Any] = []
        if start:
            # include a lookback buffer for prior EPS
            sql += " AND event_time >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND event_time <= ?"
            params.append(str(end)[:10] + "T23:59:59")
        if code_list:
            clauses = " OR ".join(["natural_key LIKE ?" for _ in code_list])
            sql += f" AND ({clauses})"
            params.extend([f'%"{c}"%' for c in code_list])
        sql += " ORDER BY event_time ASC"
        code_set = set(code_list) if code_list else None
        by_code: dict[str, list[dict[str, Any]]] = {}
        for _nk, event_time, payload in con.execute(sql, params):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            code = str(pl.get("Code") or "").strip()
            if not code:
                continue
            if code_set is not None and code not in code_set:
                continue
            disc = str(pl.get("DiscDate") or str(event_time or "")[:10])[:10]
            if not disc:
                continue

            def _f(key: str) -> float | None:
                v = pl.get(key)
                if v is None or v == "":
                    return None
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            by_code.setdefault(code, []).append(
                {
                    "disc_date": disc,
                    "eps": _f("EPS"),
                    "feps": _f("FEPS"),
                    "bps": _f("BPS"),
                    "event_time": str(event_time) if event_time else None,
                }
            )
        # Attach prior_eps chronologically
        for code, events in by_code.items():
            events.sort(key=lambda e: e["disc_date"])
            last_eps = None
            for ev in events:
                ev["prior_eps"] = last_eps
                if ev.get("eps") is not None:
                    last_eps = ev["eps"]
        return by_code
    finally:
        con.close()


def load_fins_latest_asof_map(
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Per code: sorted (disc_date, event) for as-of PIT lookup."""
    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for code, events in events_by_code.items():
        pairs = [
            (str(e["disc_date"])[:10], dict(e))
            for e in events
            if e.get("disc_date")
        ]
        pairs.sort(key=lambda x: x[0])
        out[str(code)] = pairs
    return out


def fins_asof(
    series: Sequence[tuple[str, dict[str, Any]]],
    date: str,
) -> dict[str, Any] | None:
    """Last fins event with disc_date <= date (PIT by event date; disclosed)."""
    d = str(date)[:10]
    hit = None
    for ed, ev in series:
        if ed <= d:
            hit = ev
        else:
            break
    return hit


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
    hold_days: int = 1,
) -> dict[str, Any]:
    """Cross-section relative rank L-S on momentum.

    W79 improve: when ``hold_days`` > 1, apply sticky fixed_horizon hold per
    code and score multi-day forward returns on rebalance boundaries
    (amortized cost). hold_days=1 keeps prior daily L-S path.
    """
    n = int(momentum_n)
    h = int(hold_days)
    by_date: dict[str, dict[str, float | None]] = {}
    close_by: dict[str, dict[str, float]] = {}
    dates_by_code: dict[str, list[str]] = {}
    closes_list: dict[str, list[float]] = {}
    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        moms = momentum_series(pairs_l, n=n)
        for d, m in moms:
            by_date.setdefault(d, {})[code] = m
        dates_by_code[code] = [d for d, _ in pairs_l]
        closes_list[code] = [c for _, c in pairs_l]
        for d, c in pairs_l:
            close_by.setdefault(code, {})[d] = c

    dates = sorted(by_date.keys())
    signed_returns: list[float] = []
    n_active = 0

    if h <= 1:
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
        am_cost = float(one_way_cost)
    else:
        # Per-code sticky hold of daily rank signs
        daily_rank: dict[str, dict[str, float | None]] = {
            c: {} for c in bars_by_code
        }
        for d in dates:
            ranks = cross_section_rank_signs(
                by_date[d], long_frac=long_frac, short_frac=short_frac
            )
            for code, sign in ranks.items():
                daily_rank.setdefault(code, {})[d] = sign
        am_cost = amortized_one_way_cost(one_way_cost, h)
        for code, dlist in dates_by_code.items():
            entries = [daily_rank.get(code, {}).get(d) for d in dlist]
            held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
            closes = closes_list[code]
            for i, pos in enumerate(held):
                if pos is None or pos == 0.0:
                    continue
                if i % h != 0:
                    continue
                fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
                if fwd is None:
                    continue
                n_active += 1
                signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - float(am_cost)) if gross is not None else None
    return {
        "signal_id": SIGNAL_ID_CROSS_SECTION,
        "hypothesis_class": "cross_section_relative",
        "momentum_n": n,
        "hold_days": h,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "one_way_cost": float(one_way_cost),
        "amortized_one_way_cost": float(am_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        **_freeze(),
        "note": (
            f"Cross-section rank L-S hold_days={h}. Not READY / not Mass."
        ),
    }


def evaluate_event_post_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    post_hold_days: int = DEFAULT_EVENT_POST_HOLD_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Evaluate event_post: post-disclosure multi-day hold on surprise sign.

    Scores only on disclosure event days within period (event-defined entry).
    """
    h = int(post_hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    signed_returns: list[float] = []
    n_events = 0
    n_scored = 0
    n_no_surprise = 0
    n_no_bar_match = 0
    holding_records: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 1:
            continue
        date_to_idx = {d: i for i, (d, _) in enumerate(pairs_l)}
        closes = [c for _, c in pairs_l]
        events = list(events_by_code.get(code) or [])
        for ev in events:
            disc = str(ev.get("disc_date") or "")[:10]
            if not disc:
                continue
            if period_start and disc < str(period_start)[:10]:
                continue
            if period_end and disc > str(period_end)[:10]:
                continue
            n_events += 1
            surprise, s_meta = earnings_surprise_proxy(
                eps=ev.get("eps"),
                feps=ev.get("feps"),
                prior_eps=ev.get("prior_eps"),
            )
            # Match disc_date to bar date or next available bar
            idx = date_to_idx.get(disc)
            if idx is None:
                later = [d for d in date_to_idx if d >= disc]
                if not later:
                    n_no_bar_match += 1
                    continue
                idx = date_to_idx[min(later)]
                disc_matched = min(later)
            else:
                disc_matched = disc
            rec = compute_event_post_signal(
                surprise=surprise,
                is_event_day=True,
                is_trading_day=1.0,
                post_hold_days=h,
                code=code,
                date=disc_matched,
                disc_date=disc,
                extra_meta={"surprise_meta": s_meta},
            )
            val = rec.get("value")
            holding_records.append(
                {
                    "date": disc_matched,
                    "code": code,
                    "sign": val,
                    "disc_date": disc,
                    "surprise": surprise,
                }
            )
            if val is None or val == 0.0:
                n_no_surprise += 1
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=idx)
            if fwd is None:
                continue
            n_scored += 1
            signed_returns.append(float(val) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    return {
        "signal_id": SIGNAL_ID_EVENT_POST,
        "hypothesis_class": CLASS_EVENT_POST,
        "post_hold_days": h,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_scored,
        "n_signed_returns": len(signed_returns),
        "n_events": n_events,
        "n_no_surprise": n_no_surprise,
        "n_no_bar_match": n_no_bar_match,
        "n_codes": len(bars_by_code),
        "holding_records": holding_records,
        "non_null": n_scored,
        "non_null_rate": (
            float(n_scored) / float(n_events) if n_events else None
        ),
        **_freeze(),
        "note": (
            f"Event-post hold={h}d on fins DiscDate surprise proxy. "
            "Gaps → skip (no invent). Not READY / not Mass."
        ),
    }


def evaluate_flow_demand_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    margin_by_code: Mapping[str, Sequence[tuple[str, float]]],
    short_series: Sequence[tuple[str, float]] | None = None,
    *,
    hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    require_short_confirm: bool = False,
) -> dict[str, Any]:
    """Evaluate flow_demand: multi-day sticky hold of margin change sign.

    Distinct from rejected S4 (daily sign flip). Rebalance on margin
    observation updates; hold sticky for ``hold_days`` sessions.
    """
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    # short ratio change map by date
    short_chg: dict[str, float | None] = {}
    if short_series:
        s_pairs = list(short_series)
        for i, (d, r) in enumerate(s_pairs):
            if i == 0:
                short_chg[d] = None
            else:
                prev = s_pairs[i - 1][1]
                if prev == 0:
                    short_chg[d] = None
                else:
                    short_chg[d] = (float(r) - float(prev)) / float(prev)

    signed_returns: list[float] = []
    n_active = 0
    n_margin_obs = 0
    holding_records: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 2:
            continue
        margin_pairs = list(margin_by_code.get(code) or [])
        if len(margin_pairs) < 2:
            continue
        # Build daily entry signs: only non-null on margin update days
        margin_chg_by_date: dict[str, float | None] = {}
        for i, (d, m) in enumerate(margin_pairs):
            if i == 0:
                margin_chg_by_date[d] = None
                continue
            prev = margin_pairs[i - 1][1]
            if prev == 0:
                margin_chg_by_date[d] = None
            else:
                margin_chg_by_date[d] = (float(m) - float(prev)) / float(prev)
            n_margin_obs += 1

        dates = [d for d, _ in pairs_l]
        closes = [c for _, c in pairs_l]
        # Forward-fill last margin change onto bar calendar for entry series
        last_chg: float | None = None
        last_short: float | None = None
        entry_signs: list[float | None] = []
        for d in dates:
            if d in margin_chg_by_date and margin_chg_by_date[d] is not None:
                last_chg = margin_chg_by_date[d]
            if d in short_chg and short_chg[d] is not None:
                last_short = short_chg[d]
            # Only allow rebalance entry on margin observation days
            if d in margin_chg_by_date and margin_chg_by_date[d] is not None:
                rec = compute_flow_demand_signal(
                    margin_change=margin_chg_by_date[d],
                    short_ratio_change=last_short,
                    is_trading_day=1.0,
                    hold_days=h,
                    require_short_confirm=require_short_confirm,
                    code=code,
                    date=d,
                )
                entry_signs.append(rec.get("value"))
            else:
                # between margin prints: no new entry (sticky hold handles)
                entry_signs.append(None)

        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode="min_hold"
        )
        for i, pos in enumerate(held):
            holding_records.append(
                {"date": dates[i], "code": code, "sign": pos}
            )
            if pos is None or pos == 0.0:
                continue
            # Score on days where we have a fresh margin entry (rebalance)
            if entry_signs[i] is None or entry_signs[i] == 0.0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    return {
        "signal_id": SIGNAL_ID_FLOW_DEMAND,
        "hypothesis_class": CLASS_FLOW_DEMAND,
        "hold_days": h,
        "require_short_confirm": bool(require_short_confirm),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_margin_obs": n_margin_obs,
        "n_codes": len(bars_by_code),
        "n_codes_with_margin": sum(
            1 for c in bars_by_code if len(margin_by_code.get(c) or []) >= 2
        ),
        "holding_records": holding_records,
        "non_null": n_active,
        **_freeze(),
        "note": (
            f"Flow demand multi-day hold={h} from margin change "
            f"(short_confirm={require_short_confirm}). Not S4 daily. "
            "Not READY / not Mass."
        ),
    }


def evaluate_fundamentals_price_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    hold_days: int = DEFAULT_FUND_HOLD_DAYS,
    momentum_n: int = DEFAULT_FUND_MOMENTUM_N,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    mode: str = "value_momentum_agree",
) -> dict[str, Any]:
    """Evaluate fundamentals_price: PIT value score × momentum, multi-day hold."""
    h = int(hold_days)
    n = int(momentum_n)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    asof_map = load_fins_latest_asof_map(events_by_code)

    signed_returns: list[float] = []
    n_active = 0
    n_missing_fins = 0
    holding_records: list[dict[str, Any]] = []
    value_scores_all: list[float] = []

    # Cross-sectional benchmark: median value score per date when possible
    # First pass: collect value scores
    value_by_code_date: dict[str, dict[str, float | None]] = {}
    for code, pairs in bars_by_code.items():
        series = asof_map.get(code) or []
        value_by_code_date[code] = {}
        for d, close in pairs:
            fin = fins_asof(series, d)
            if fin is None:
                value_by_code_date[code][d] = None
                continue
            score, _ = fundamental_value_score(
                close=close, eps=fin.get("eps"), bps=fin.get("bps")
            )
            value_by_code_date[code][d] = score
            if score is not None:
                value_scores_all.append(score)

    global_median = None
    if value_scores_all:
        ss = sorted(value_scores_all)
        global_median = ss[len(ss) // 2]

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < max(h, n) + 2:
            continue
        moms = momentum_series(pairs_l, n=n)
        mom_by_date = {d: m for d, m in moms}
        closes = [c for _, c in pairs_l]
        dates = [d for d, _ in pairs_l]
        entries: list[float | None] = []
        for d, _close in pairs_l:
            vscore = value_by_code_date.get(code, {}).get(d)
            if vscore is None:
                n_missing_fins += 1
                entries.append(None)
                continue
            rec = compute_fundamentals_price_signal(
                value_score=vscore,
                momentum=mom_by_date.get(d),
                value_benchmark=global_median,
                is_trading_day=1.0,
                hold_days=h,
                mode=mode,
                code=code,
                date=d,
            )
            entries.append(rec.get("value"))
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        for i, pos in enumerate(held):
            holding_records.append(
                {"date": dates[i], "code": code, "sign": pos}
            )
            if pos is None or pos == 0.0:
                continue
            if i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    return {
        "signal_id": SIGNAL_ID_FUNDAMENTALS_PRICE,
        "hypothesis_class": CLASS_FUNDAMENTALS_PRICE,
        "hold_days": h,
        "momentum_n": n,
        "mode": mode,
        "value_benchmark_median": global_median,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_missing_fins_days": n_missing_fins,
        "n_codes": len(bars_by_code),
        "holding_records": holding_records,
        "non_null": n_active,
        **_freeze(),
        "note": (
            f"Fundamentals×price mode={mode} hold={h}d PIT fins. "
            "Not READY / not Mass."
        ),
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
    include_event_post: bool = True,
    include_flow_demand: bool = True,
    include_fundamentals_price: bool = True,
    include_multi_day_hold_10: bool = True,
    cross_section_hold_days: int = 5,
    event_hold_days: int = DEFAULT_EVENT_POST_HOLD_DAYS,
    flow_hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    fund_hold_days: int = DEFAULT_FUND_HOLD_DAYS,
    max_days: int = 80,
    min_periods_gate: int = 2,
    min_active_per_period: int = 20,
    min_economic_net: float = MIN_ECONOMIC_NET,
    apply_robustness_gate: bool = True,
) -> dict[str, Any]:
    """Multi-year offline eval for all enabled class hyps (W79).

    Uses local W63/W64 bar/margin mirrors and local SQLite
    (jsda_repo_rates, fins_summary, short_ratio).
    """
    period_list = [dict(p) for p in (periods or DEFAULT_PERIODS)]
    selected = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else list(DEFAULT_EVAL_CODES)
    )
    h = int(hold_days)
    if h not in SUPPORTED_HOLD_DAYS:
        if h < 1:
            raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")

    # Load full repo series once (research offline; as_of_date keyed).
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

    # Fins lookback buffer for prior EPS / as-of PIT
    fins_global_start = "2014-01-01"
    fins_global_end = "2026-12-31"
    fins_events = (
        load_fins_events_from_sqlite(
            sqlite_path,
            codes=selected,
            start=fins_global_start,
            end=fins_global_end,
        )
        if (include_event_post or include_fundamentals_price)
        else {}
    )
    fins_load_note = {
        "source": "local_sqlite_jquants_records_fins_summary",
        "path": str(sqlite_path),
        "n_codes": len(fins_events),
        "n_events": sum(len(v) for v in fins_events.values()),
        "pit_disclosure": (
            "fins_summary keyed by DiscDate / event_time for offline research. "
            "available_at may be event-time or bulk; research uses DiscDate as "
            "visibility key. Disclosed; no invent fill."
        ),
        "dataset": "fins_summary",
    }

    short_series_full = (
        load_short_ratio_series_from_sqlite(
            sqlite_path, section="0050", start="2014-01-01", end="2026-12-31"
        )
        if include_flow_demand
        else []
    )
    short_load_note = {
        "source": "local_sqlite_markets_short_ratio",
        "section": "0050",
        "n_dates": len(short_series_full),
        "dataset": "markets_short_ratio",
        "note": "Market-level S33=0050 ratio for optional flow confirm.",
    }

    results_md: list[dict[str, Any]] = []
    results_md10: list[dict[str, Any]] = []
    results_macro: list[dict[str, Any]] = []
    results_xs: list[dict[str, Any]] = []
    results_event: list[dict[str, Any]] = []
    results_flow: list[dict[str, Any]] = []
    results_fund: list[dict[str, Any]] = []

    for raw in period_list:
        p = dict(raw)
        pid = str(p.get("period_id") or p.get("year") or "period")
        year = p.get("year")
        p_start = str(p.get("period_start") or "")[:10] or None
        p_end = str(p.get("period_end") or "")[:10] or None
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
            if include_event_post:
                results_event.append(dict(skip))
            if include_flow_demand:
                results_flow.append(dict(skip))
            if include_fundamentals_price:
                results_fund.append(dict(skip))
            if include_multi_day_hold_10:
                results_md10.append(dict(skip))
            continue

        try:
            bars = load_bars_ndjson(
                bars_path, codes=selected, max_days=max_days
            )
            if not bars:
                raise RuntimeError("no bars after code filter")

            def _period_row(
                eval_out: Mapping[str, Any],
                *,
                signal_id: str,
                extra: Mapping[str, Any] | None = None,
            ) -> dict[str, Any]:
                row = {
                    "period_id": pid,
                    "year": year,
                    "status": "ok",
                    "period_start": p_start,
                    "period_end": p_end,
                    "bars_path": str(bars_path),
                    "n_codes": eval_out.get("n_codes"),
                    "gross_signed_mean_active": eval_out.get(
                        "gross_signed_mean_active"
                    ),
                    "net_one_way_mean_active": eval_out.get(
                        "net_one_way_mean_active"
                    ),
                    "n_active_positions": eval_out.get("n_active_positions"),
                    "non_null": eval_out.get("non_null")
                    or eval_out.get("n_active_positions"),
                    "non_null_rate": eval_out.get("non_null_rate"),
                    "signal_id": signal_id,
                    "holding_records": eval_out.get("holding_records"),
                }
                if extra:
                    row.update(dict(extra))
                return row

            md = evaluate_multi_day_hold_on_bars(
                bars, hold_days=h, one_way_cost=one_way_cost
            )
            results_md.append(
                _period_row(
                    md,
                    signal_id=SIGNAL_ID_MULTI_DAY_HOLD,
                    extra={
                        "amortized_one_way_cost": md.get(
                            "amortized_one_way_cost"
                        ),
                        "hold_days": h,
                    },
                )
            )

            if include_multi_day_hold_10 and h != 10:
                md10 = evaluate_multi_day_hold_on_bars(
                    bars, hold_days=10, one_way_cost=one_way_cost
                )
                results_md10.append(
                    _period_row(
                        md10,
                        signal_id=SIGNAL_ID_MULTI_DAY_HOLD,
                        extra={
                            "amortized_one_way_cost": md10.get(
                                "amortized_one_way_cost"
                            ),
                            "hold_days": 10,
                            "variant": "hold_10",
                        },
                    )
                )

            macro = evaluate_macro_conditioned_on_bars(
                bars,
                repo_series,
                momentum_n=h,
                hold_days=h,
                mode=macro_mode,
                one_way_cost=one_way_cost,
            )
            results_macro.append(
                _period_row(
                    macro,
                    signal_id=SIGNAL_ID_MACRO_CONDITIONED,
                    extra={
                        "n_regime_gap": macro.get("n_regime_gap"),
                        "regime_counts": macro.get("regime_counts"),
                        "mode": macro_mode,
                    },
                )
            )

            if include_cross_section:
                xs = evaluate_cross_section_on_bars(
                    bars,
                    momentum_n=h,
                    one_way_cost=one_way_cost,
                    hold_days=int(cross_section_hold_days),
                )
                results_xs.append(
                    _period_row(
                        xs,
                        signal_id=SIGNAL_ID_CROSS_SECTION,
                        extra={
                            "hold_days": int(cross_section_hold_days),
                            "amortized_one_way_cost": xs.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
                )

            if include_event_post:
                ep = evaluate_event_post_on_bars(
                    bars,
                    fins_events,
                    post_hold_days=int(event_hold_days),
                    one_way_cost=one_way_cost,
                    period_start=p_start,
                    period_end=p_end,
                )
                results_event.append(
                    _period_row(
                        ep,
                        signal_id=SIGNAL_ID_EVENT_POST,
                        extra={
                            "post_hold_days": int(event_hold_days),
                            "n_events": ep.get("n_events"),
                            "n_no_surprise": ep.get("n_no_surprise"),
                            "amortized_one_way_cost": ep.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
                )

            if include_flow_demand:
                margin_path = resolve_margin_path(pid, mirror_dir=mirror_dir)
                if margin_path is not None and Path(margin_path).exists():
                    margin = load_margin_ndjson(margin_path, codes=selected)
                    margin_src = f"ndjson:{margin_path}"
                else:
                    margin = load_margin_from_sqlite(
                        sqlite_path,
                        codes=selected,
                        start=p_start or (f"{year}-01-01" if year else None),
                        end=p_end or (f"{year}-12-31" if year else None),
                    )
                    margin_src = "sqlite:markets_margin_interest"
                # short slice for period
                short_slice = [
                    (d, r)
                    for d, r in short_series_full
                    if (not p_start or d >= p_start)
                    and (not p_end or d <= p_end)
                ]
                flow = evaluate_flow_demand_on_bars(
                    bars,
                    margin,
                    short_slice,
                    hold_days=int(flow_hold_days),
                    one_way_cost=one_way_cost,
                    require_short_confirm=False,
                )
                results_flow.append(
                    _period_row(
                        flow,
                        signal_id=SIGNAL_ID_FLOW_DEMAND,
                        extra={
                            "hold_days": int(flow_hold_days),
                            "margin_source": margin_src,
                            "n_margin_obs": flow.get("n_margin_obs"),
                            "n_codes_with_margin": flow.get(
                                "n_codes_with_margin"
                            ),
                            "amortized_one_way_cost": flow.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
                )

            if include_fundamentals_price:
                fund = evaluate_fundamentals_price_on_bars(
                    bars,
                    fins_events,
                    hold_days=int(fund_hold_days),
                    momentum_n=DEFAULT_FUND_MOMENTUM_N,
                    one_way_cost=one_way_cost,
                    mode="value_momentum_agree",
                )
                results_fund.append(
                    _period_row(
                        fund,
                        signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
                        extra={
                            "hold_days": int(fund_hold_days),
                            "n_missing_fins_days": fund.get(
                                "n_missing_fins_days"
                            ),
                            "value_benchmark_median": fund.get(
                                "value_benchmark_median"
                            ),
                            "amortized_one_way_cost": fund.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
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
            if include_event_post:
                results_event.append(dict(err))
            if include_flow_demand:
                results_flow.append(dict(err))
            if include_fundamentals_price:
                results_fund.append(dict(err))
            if include_multi_day_hold_10:
                results_md10.append(dict(err))

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
        # For sparse event_post, relax min_active (events are rare)
        min_active = min_active_per_period
        if signal_id == SIGNAL_ID_EVENT_POST:
            min_active = min(5, min_active_per_period)
        return evaluate_research_robustness_gate(
            period_rows,
            signal_id=signal_id,
            min_periods=min_periods_gate,
            min_active_per_period=min_active,
            one_way_cost=one_way_cost,
            require_net_sign_majority=True,
        )

    gate_md = _gate(results_md, SIGNAL_ID_MULTI_DAY_HOLD)
    gate_md10 = (
        _gate(results_md10, SIGNAL_ID_MULTI_DAY_HOLD + "_hold10")
        if include_multi_day_hold_10
        else None
    )
    gate_macro = _gate(results_macro, SIGNAL_ID_MACRO_CONDITIONED)
    gate_xs = (
        _gate(results_xs, SIGNAL_ID_CROSS_SECTION)
        if include_cross_section
        else None
    )
    gate_event = (
        _gate(results_event, SIGNAL_ID_EVENT_POST)
        if include_event_post
        else None
    )
    gate_flow = (
        _gate(results_flow, SIGNAL_ID_FLOW_DEMAND)
        if include_flow_demand
        else None
    )
    gate_fund = (
        _gate(results_fund, SIGNAL_ID_FUNDAMENTALS_PRICE)
        if include_fundamentals_price
        else None
    )

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
    cost_ls = build_leverage_short_cost_assumption(
        position_style="long_short",
        gross_leverage=1.0,
        short_fraction=0.5,
        one_way_cost=one_way_cost,
        uses_short=True,
        uses_leverage=False,
    )
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
        cost_ls["repo_linked"] = dict(cost_macro["repo_linked"])
    else:
        cost_macro["repo_linked"] = {
            "preferred": True,
            "available": False,
            "fallback": "fixed_bp_placeholder",
        }
        cost_ls["repo_linked"] = dict(cost_macro["repo_linked"])

    holding_md = None
    md_hold_recs: list[dict[str, Any]] = []
    for r in results_md:
        if r.get("status") == "ok" and r.get("holding_records"):
            md_hold_recs.extend(list(r["holding_records"]))
    if md_hold_recs:
        holding_md = holding_metrics_report(
            md_hold_recs, one_way_cost=one_way_cost
        )

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
        worst_i = min(range(len(grosses)), key=lambda i: grosses[i])
        vol_i = max(range(len(grosses)), key=lambda i: abs(grosses[i]))
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

    def _risk(rows: list[dict[str, Any]], signal_id: str) -> dict[str, Any]:
        return evaluate_risk_scenarios(
            _scen_from_rows(rows),
            rate_data_usable=True,
            liquidity_data_available=False,
            prefer_fail_on_sign_break=True,
            signal_id=signal_id,
        )

    risk_md = _risk(results_md, SIGNAL_ID_MULTI_DAY_HOLD)
    risk_macro = _risk(results_macro, SIGNAL_ID_MACRO_CONDITIONED)
    risk_xs = _risk(results_xs, SIGNAL_ID_CROSS_SECTION) if include_cross_section else None
    risk_event = _risk(results_event, SIGNAL_ID_EVENT_POST) if include_event_post else None
    risk_flow = _risk(results_flow, SIGNAL_ID_FLOW_DEMAND) if include_flow_demand else None
    risk_fund = (
        _risk(results_fund, SIGNAL_ID_FUNDAMENTALS_PRICE)
        if include_fundamentals_price
        else None
    )

    def _econ_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
        nets = [
            r.get("net_one_way_mean_active")
            for r in rows
            if r.get("status") == "ok"
            and r.get("net_one_way_mean_active") is not None
        ]
        return economic_net_meaningful(
            nets,
            min_mean_net=float(min_economic_net),
            require_positive_majority=True,
        )

    def _candidate_verdict(
        gate: dict[str, Any] | None,
        risk: dict[str, Any] | None,
        rows: list[dict[str, Any]],
        *,
        n_ok: int,
    ) -> dict[str, Any]:
        """Candidate bar: gate + risk + **economic net meaningful** (W79).

        Weak consistent-negative → not_candidate even if gate passes.
        research_candidate always False (no auto-promote).
        """
        gate_pass = bool(gate and gate.get("passed"))
        risk_ok = bool(risk and risk.get("research_candidate_allowed"))
        econ = _econ_from_rows(rows)
        econ_ok = bool(econ.get("meaningful"))
        # discussion_only if gate+risk ok but econ fails (weak negative etc.)
        structural_ok = bool(gate_pass and risk_ok and n_ok >= min_periods_gate)
        allowed = bool(structural_ok and econ_ok)
        if allowed:
            verdict = "discussion_only_not_auto_promoted"
        elif structural_ok and not econ_ok:
            verdict = "not_candidate_economic_net_not_meaningful"
        else:
            verdict = "not_candidate"
        return {
            "research_candidate": False,
            "research_candidate_allowed": allowed,
            "gate_passed": gate_pass,
            "risk_scenarios_ok": risk_ok,
            "economic_net": econ,
            "economic_net_ok": econ_ok,
            "n_ok_periods": n_ok,
            "verdict": verdict,
            "ready_declared": False,
            "mass_research": MASS_RESEARCH,
            "min_economic_net": float(min_economic_net),
            "note": (
                "Candidate bar = checklist/gate + risk not catastrophic + "
                "economically meaningful positive net majority. "
                "Weak consistent-negative is not_candidate. "
                "research_candidate always False (no auto-promote). "
                "Pass ≠ READY/Mass."
            ),
        }

    def _n_ok(rows: list[dict[str, Any]]) -> int:
        return sum(1 for r in rows if r.get("status") == "ok")

    n_ok_md = _n_ok(results_md)
    n_ok_macro = _n_ok(results_macro)
    n_ok_xs = _n_ok(results_xs)
    n_ok_event = _n_ok(results_event)
    n_ok_flow = _n_ok(results_flow)
    n_ok_fund = _n_ok(results_fund)
    n_ok_md10 = _n_ok(results_md10)

    def _compact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for r in rows:
            c = {k: v for k, v in r.items() if k != "holding_records"}
            out.append(c)
        return out

    def _class_block(
        *,
        signal_id: str,
        hyp_class: str,
        rows: list[dict[str, Any]],
        gate: dict[str, Any] | None,
        risk: dict[str, Any] | None,
        cost: dict[str, Any] | None = None,
        holding: dict[str, Any] | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        n_ok = _n_ok(rows)
        block: dict[str, Any] = {
            "signal_id": signal_id,
            "hypothesis_class": hyp_class,
            "years": _compact(rows),
            "cross_year_table": _compact(
                [r for r in rows if r.get("status") == "ok"]
            ),
            "robustness_gate": gate,
            "cost_assumption": cost,
            "risk_scenarios": risk,
            "candidate": _candidate_verdict(gate, risk, rows, n_ok=n_ok),
        }
        if holding is not None:
            block["holding"] = holding
        if extra:
            block.update(dict(extra))
        return block

    out: dict[str, Any] = {
        "version": CLASS_HYP_EVAL_VERSION,
        "wave": CLASS_HYP_EVAL_WAVE,
        "class_signals": class_signals_document(),
        "definitions": class_signal_definitions(
            hold_days=h,
            macro_mode=macro_mode,
            event_hold_days=int(event_hold_days),
            flow_hold_days=int(flow_hold_days),
            fund_hold_days=int(fund_hold_days),
        ),
        "hold_days": h,
        "macro_mode": macro_mode,
        "codes": selected,
        "one_way_cost": float(one_way_cost),
        "one_way_cost_bp": float(one_way_cost) * 10_000.0,
        "min_economic_net": float(min_economic_net),
        "repo_load": repo_load_note,
        "fins_load": fins_load_note,
        "short_load": short_load_note,
        "multi_day_hold": _class_block(
            signal_id=SIGNAL_ID_MULTI_DAY_HOLD,
            hyp_class=CLASS_MULTI_DAY_HOLD,
            rows=results_md,
            gate=gate_md,
            risk=risk_md,
            cost=cost_md,
            holding=holding_md,
            extra={
                "cost_amortization": cost_amortization_report(
                    one_way_cost=one_way_cost
                ),
            },
        ),
        "macro_conditioned": _class_block(
            signal_id=SIGNAL_ID_MACRO_CONDITIONED,
            hyp_class=CLASS_MACRO_CONDITIONED,
            rows=results_macro,
            gate=gate_macro,
            risk=risk_macro,
            cost=cost_macro,
        ),
        "n_years_requested": len(period_list),
        "n_years_ok_multi_day_hold": n_ok_md,
        "n_years_ok_macro_conditioned": n_ok_macro,
        "history_source": (
            "local_r2_mirror_ndjson + local_sqlite "
            "(jsda_repo_rates · fins_summary · margin · short_ratio)"
        ),
        "label": "研究用・複数年クラス仮説評価・未宣言",
        **_freeze(),
        "note": (
            "W79 class hyp multi-year offline eval. multi_day_hold + "
            "event_post + macro_conditioned + flow_demand + "
            "fundamentals_price (+ cross_section improve). "
            "Candidate only if economic net meaningful (positive majority "
            "and mean net >= min_economic_net). Weak consistent-negative "
            "→ not_candidate. research_candidate never auto-promoted. "
            "Not READY / Mass NO-GO / Phase7 OFF."
        ),
    }

    if include_multi_day_hold_10:
        out["multi_day_hold_10"] = _class_block(
            signal_id=SIGNAL_ID_MULTI_DAY_HOLD,
            hyp_class=CLASS_MULTI_DAY_HOLD,
            rows=results_md10,
            gate=gate_md10,
            risk=_risk(results_md10, SIGNAL_ID_MULTI_DAY_HOLD)
            if results_md10
            else None,
            cost=cost_md,
            extra={"variant": "hold_10", "n_ok": n_ok_md10},
        )
    if include_cross_section:
        out["cross_section_relative"] = _class_block(
            signal_id=SIGNAL_ID_CROSS_SECTION,
            hyp_class="cross_section_relative",
            rows=results_xs,
            gate=gate_xs,
            risk=risk_xs,
            cost=cost_ls,
            extra={"hold_days": int(cross_section_hold_days)},
        )
    if include_event_post:
        out["event_post"] = _class_block(
            signal_id=SIGNAL_ID_EVENT_POST,
            hyp_class=CLASS_EVENT_POST,
            rows=results_event,
            gate=gate_event,
            risk=risk_event,
            cost=cost_md,
            extra={"post_hold_days": int(event_hold_days), "n_ok": n_ok_event},
        )
    if include_flow_demand:
        out["flow_demand"] = _class_block(
            signal_id=SIGNAL_ID_FLOW_DEMAND,
            hyp_class=CLASS_FLOW_DEMAND,
            rows=results_flow,
            gate=gate_flow,
            risk=risk_flow,
            cost=cost_ls,
            extra={"hold_days": int(flow_hold_days), "n_ok": n_ok_flow},
        )
    if include_fundamentals_price:
        out["fundamentals_price"] = _class_block(
            signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
            hyp_class=CLASS_FUNDAMENTALS_PRICE,
            rows=results_fund,
            gate=gate_fund,
            risk=risk_fund,
            cost=cost_ls,
            extra={"hold_days": int(fund_hold_days), "n_ok": n_ok_fund},
        )

    # Summary yes/no per class
    summary: dict[str, Any] = {}
    for key in (
        "multi_day_hold",
        "multi_day_hold_10",
        "event_post",
        "macro_conditioned",
        "cross_section_relative",
        "flow_demand",
        "fundamentals_price",
    ):
        block = out.get(key)
        if not isinstance(block, Mapping):
            continue
        cand = block.get("candidate") or {}
        summary[key] = {
            "signal_id": block.get("signal_id"),
            "gate_passed": cand.get("gate_passed"),
            "economic_net_ok": cand.get("economic_net_ok"),
            "research_candidate_allowed": cand.get(
                "research_candidate_allowed"
            ),
            "research_candidate": False,
            "verdict": cand.get("verdict"),
            "candidate_yes_no": "no",  # never yes without economic+gate+risk
        }
        if cand.get("research_candidate_allowed"):
            # Still not production candidate; discussion only
            summary[key]["candidate_yes_no"] = "no_discussion_only"
    out["candidate_summary"] = summary
    return out


__all__ = [
    "CLASS_HYP_EVAL_VERSION",
    "CLASS_HYP_EVAL_WAVE",
    "DEFAULT_BARS_MIRROR_DIR",
    "DEFAULT_EVAL_CODES",
    "DEFAULT_PERIODS",
    "DEFAULT_SQLITE",
    "MIN_ECONOMIC_NET",
    "evaluate_cross_section_on_bars",
    "evaluate_event_post_on_bars",
    "evaluate_flow_demand_on_bars",
    "evaluate_fundamentals_price_on_bars",
    "evaluate_macro_conditioned_on_bars",
    "evaluate_multi_day_hold_on_bars",
    "fins_asof",
    "load_bars_ndjson",
    "load_fins_events_from_sqlite",
    "load_margin_from_sqlite",
    "load_margin_ndjson",
    "load_repo_rows_from_sqlite",
    "load_short_ratio_series_from_sqlite",
    "momentum_series",
    "resolve_bars_path",
    "resolve_margin_path",
    "run_class_hyp_multi_year_eval",
]
