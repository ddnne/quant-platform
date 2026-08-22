"""Offline multi-year class-hypothesis eval (W78–W83).

Runs class research signals over local bar mirrors + local SQLite
(``jsda_repo_rates``, ``fins_summary``, ``fins_earnings_date``, margin/short),
then feeds cost-aware robustness gate + checklist v2 + economic-net +
**occurrence-rate** + **W81 statistical bar** (t-stat / Sharpe / win-rate)
production candidate bar.

Classes covered
---------------
* multi_day_hold · multi_day_hold_10 · macro_conditioned · cross_section_relative
* cross_section sticky hold=10 (W83 default path when enabled)
* event_post (PIT DiscDate+DiscTime only; no look-ahead revival)
* flow_demand · fundamentals_price

Hard constraints
----------------
* Not simple_daily_sign · no S1–S5 un-reject
* Not READY / Mass / Phase7 / orders
* No invent fill on repo / fins / margin / liquidity gaps
* W81+: ``research_candidate=True`` only when production bar fully met
  including |t| / Sharpe / period win-rate (still never auto-connects
  Mass / READY / operational GO)
* W86+: sign flip both-sides after cost for default/main explore
  (xs hold10 mom5/mom3 · fund hold10); record ``chosen_sign``;
  both near-zero / non-positive → reject or explore demote
* No mean-bp-only promotion
* weak consistent-negative is **not_candidate** (economic net bar)
* noisy low t/Sharpe / unstable yearly signs → demote to discussion_only
* Event sufficiency = occurrence **rate** (not absolute count alone);
  short window with OK rate → extend and re-eval
* event_post entry = W82 PIT first non-look-ahead session close
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from research.eval_tracks import (
    EVAL_TRACK_LIQ_LARGE,
    EVAL_TRACK_MID_N,
    EVAL_TRACKS,
    UNIVERSE_SELECT_ADV,
    eval_track,
    infer_eval_track,
)
from research.unique_logic.constants import (
    FINS_SUMMARY_EQ_KEY,
    FINS_SUMMARY_EQAR_KEY,
    FINS_SUMMARY_OFFICIAL_KEYS,
    FINS_SUMMARY_TA_KEY,
)
from features.class_signals import (
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_INDEX_VOL_REGIME,
    CLASS_OPTIONS_VOL_REGIME,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    CLASS_MULTI_FACTOR,
    CLASS_RATE_FACTOR,
    CLASS_SIGNALS_VERSION,
    CLASS_SIGNALS_WAVE,
    DEFAULT_CURVE_INVERT_THRESHOLD,
    DEFAULT_CURVE_STEEP_THRESHOLD,
    DEFAULT_EVENT_POST_HOLD_DAYS,
    DEFAULT_FLOW_HOLD_DAYS,
    DEFAULT_FUND_HOLD_DAYS,
    DEFAULT_FUND_MOMENTUM_N,
    DEFAULT_HOLD_DAYS,
    DEFAULT_MAX_YEAR_POS_NET_SHARE,
    DEFAULT_MIN_ABS_T_STAT,
    DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY,
    DEFAULT_MIN_ECONOMIC_NET,
    DEFAULT_MIN_EVENTS_PER_CODE_YEAR,
    DEFAULT_MIN_EVENTS_PER_TRADING_DAY,
    DEFAULT_MIN_PERIOD_WIN_RATE,
    DEFAULT_MIN_POSITIVE_PERIODS,
    DEFAULT_MIN_SHARPE_PERIOD,
    DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE,
    DEFAULT_NKY_VOL_COMPRESS_RATIO,
    DEFAULT_NKY_VOL_EXPAND_RATIO,
    DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    DEFAULT_NKY_VOL_LONG_N,
    DEFAULT_NKY_VOL_LOW_THRESHOLD,
    DEFAULT_NKY_VOL_SHORT_N,
    DEFAULT_REPO_HIGH_THRESHOLD,
    DEFAULT_REPO_LOW_THRESHOLD,
    DEFAULT_TRADING_DAYS_PER_YEAR,
    NKY_VOL_PROXY_NK225F,
    NKY_VOL_PROXY_TOPIX,
    REPO_CURVE_LONG_TENOR,
    REPO_CURVE_SHORT_TENOR,
    SIGNAL_ID_CROSS_SECTION,
    SIGNAL_ID_EVENT_POST,
    SIGNAL_ID_FLOW_DEMAND,
    SIGNAL_ID_FUNDAMENTALS_PRICE,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_MF_FLOW_PRICE,
    SIGNAL_ID_MF_VALUE_MOM_RATE,
    SIGNAL_ID_MULTI_DAY_HOLD,
    SIGNAL_ID_NKY_VOL_ABS_LEVEL,
    SIGNAL_ID_NKY_VOL_TERM_LEVELS,
    SIGNAL_ID_NKY_VOL_TERM_RATIO,
    SIGNAL_ID_OPT225_BASEVOL_ABS,
    SIGNAL_ID_OPT225_BASEVOL_TERM_LEVELS,
    SIGNAL_ID_OPT225_BASEVOL_TERM_RATIO,
    SIGNAL_ID_OPT225_ATM_IV_ABS,
    SIGNAL_ID_OPT225_ATM_IV_TERM_LEVELS,
    SIGNAL_ID_OPT225_ATM_IV_TERM_RATIO,
    SIGNAL_ID_OPT225_SPREAD_ABS,
    SIGNAL_ID_OPT225_SPREAD_CHANGE,
    SIGNAL_ID_OPT225_SKEW_ABS,
    SIGNAL_ID_OPT225_CM_TERM_ABS,
    SIGNAL_ID_OPT225_BASEVOL_DELTA_ABS,
    SIGNAL_ID_RATE_CURVE_XS,
    SIGNAL_ID_RATE_LEVEL_XS,
    DEFAULT_OPT225_VOL_HIGH_THRESHOLD,
    DEFAULT_OPT225_VOL_LOW_THRESHOLD,
    DEFAULT_OPT225_SPREAD_HIGH_THRESHOLD,
    DEFAULT_OPT225_SPREAD_LOW_THRESHOLD,
    DEFAULT_OPT225_VOL_EXPAND_RATIO,
    DEFAULT_OPT225_VOL_COMPRESS_RATIO,
    OPT225_SPREAD_CONVENTION,
    SUPPORTED_HOLD_DAYS,
    TRADING_DAYS_ANN,
    amortized_one_way_cost,
    apply_sticky_hold,
    class_signal_definitions,
    class_signals_document,
    compute_event_post_signal,
    compute_flow_demand_signal,
    compute_fundamentals_price_signal,
    compute_macro_conditioned_signal,
    compute_mf_flow_price_signal,
    compute_mf_value_mom_rate_signal,
    compute_nky_vol_abs_level_signal,
    compute_nky_vol_term_levels_signal,
    compute_nky_vol_term_ratio_signal,
    compute_opt225_vol_signal,
    compute_rate_curve_xs_signal,
    compute_rate_level_xs_signal,
    cross_section_rank_signs,
    earnings_surprise_proxy,
    economic_net_meaningful,
    fundamental_value_score,
    multi_day_forward_return,
    multi_year_skew_check,
    occurrence_rate_event_post,
    occurrence_rate_multiday,
    production_candidate_bar,
    event_post_entry_bar_index,
    sign_from_numeric,
    EVENT_POST_ENTRY_MODE,
)
from research.stats_metrics import (
    period_stats_report,
    stats_bar_check,
    stats_metrics_document,
    trade_stats_report,
)
from research.sign_selection import (
    SIGN_INVERTED,
    SIGN_ORIGINAL,
    SIGN_SELECTION_VERSION,
    SIGN_SELECTION_WAVE,
    sign_selection_document,
    sign_selection_from_period_rows,
)
from research.cost_models import (
    DEFAULT_ONE_WAY_COST,
    REPO_DATASET_ID,
    SHORT_BORROW_SPREAD_SENSITIVITY,
    annotate_period_rows_with_extended_costs,
    apply_liquidity_to_one_way_cost,
    build_leverage_short_cost_assumption,
    compute_liquidity_proxy_from_bars,
    default_long_only_unlevered_cost_assumption,
    liquidity_bucket_from_proxy,
    liquidity_cost_multipliers,
    load_repo_rate_series_from_rows,
    lookup_repo_rate,
    mean_repo_rate_pct,
    remeasure_period_rows_with_short_cost,
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

from research.freezes import MASS_RESEARCH, PHASE7, READY_DECLARED

CLASS_HYP_EVAL_VERSION: str = "class-hyp-eval/v7"
CLASS_HYP_EVAL_WAVE: str = "W86 / w0816u"
# Economic net bar (research): weak consistent-negative never candidate.
MIN_ECONOMIC_NET: float = DEFAULT_MIN_ECONOMIC_NET
MIN_ACTIVATION_RATE_MULTIDAY: float = DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY
MIN_EVENTS_PER_CODE_YEAR: float = DEFAULT_MIN_EVENTS_PER_CODE_YEAR
MIN_EVENTS_PER_TRADING_DAY: float = DEFAULT_MIN_EVENTS_PER_TRADING_DAY
MIN_YEARS_RESEARCH_CANDIDATE: int = DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE
MAX_YEAR_POS_NET_SHARE: float = DEFAULT_MAX_YEAR_POS_NET_SHARE
# W81 statistical bar floors (period nets).
MIN_ABS_T_STAT: float = DEFAULT_MIN_ABS_T_STAT
MIN_SHARPE_PERIOD: float = DEFAULT_MIN_SHARPE_PERIOD
MIN_PERIOD_WIN_RATE: float = DEFAULT_MIN_PERIOD_WIN_RATE
MIN_POSITIVE_PERIODS: int = DEFAULT_MIN_POSITIVE_PERIODS

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
    "62730",
    "63010",
    "83060",
    "72010",
    "72690",
    "67020",
    "67520",
    "69520",
    "77310",
    "84110",
    "86010",
    "90200",
    "91010",
    "25020",
    "34020",
    "45190",
    "54060",
    "64710",
    "88020",
    "95030",
    "28020",
    "34070",
    "40040",
    "41880",
    "44520",
    "45030",
    "49020",
    "50200",
    "54110",
    "58020",
    "63260",
    "64720",
    "69540",
    "72020",
    "72700",
    "77330",
    "77520",
    "78320",
    "83080",
    "83160",
    "85910",
    "86040",
    "86300",
    "87250",
    "87500",
    "87660",
    "88010",
    "88300",
    "92020",
    "95310",
    "79120",
    "69880",
    "34010",
    "34050",
    "41830",
    "18010",
    "18020",
    "18120",
    "19250",
    "19280",
    "19630",
    "20020",
    "22690",
    "22820",
    "25010",
    "25310",
    "28010",
    "90050",
    "90210",
    "95320",
)

# Ranked pool for ADV/fins selection. DEFAULT_EVAL_CODES is the legacy head-N
# list; production panels use select_eval_universe (skip missing, no invent).
EVAL_UNIVERSE_POOL: tuple[str, ...] = DEFAULT_EVAL_CODES + (
    "70110",
    "72050",
    "72610",
    "73090",
    "80530",
    "82670",
    "86970",
    "90070",
    "90220",
    "91040",
    "91070",
    "95020",
    "95130",
    "57110",
    "63020",
    "65020",
    "67010",
    "67620",
    "68410",
    "70120",
    "77350",
    "79510",
    "80320",
    "82520",
    "83090",
    "84180",
    "84730",
    "85930",
    "86980",
    "87290",
)
UNIVERSE_SELECT_RULE: str = UNIVERSE_SELECT_ADV
UNIVERSE_MIN_BAR_DAYS: int = 40
# One TA/EqAR print is enough to keep a name. Requiring 4 in a 10-month
# window collapsed the pool to quarterly-only names (~7). Skip zero; no invent.
UNIVERSE_MIN_FINS_TA: int = 1
UNIVERSE_MIN_FINS_EQAR: int = 1


def rank_eval_codes(
    scored: Sequence[Mapping[str, Any]],
    *,
    max_codes: int,
    min_bar_days: int = UNIVERSE_MIN_BAR_DAYS,
    min_fins_ta: int = UNIVERSE_MIN_FINS_TA,
    min_fins_eqar: int = UNIVERSE_MIN_FINS_EQAR,
) -> list[str]:
    """Rank by ADV; skip missing bars/TA/EqAR. No invent, not list-order."""
    rows: list[tuple[float, str]] = []
    for raw in scored:
        code = str(raw.get("code") or "").strip()
        if not code:
            continue
        try:
            adv = float(raw.get("adv"))
        except (TypeError, ValueError):
            continue
        if adv <= 0:
            continue
        try:
            n_bars = int(raw.get("n_bars") or 0)
            n_ta = int(raw.get("n_ta") or 0)
            n_eqar = int(raw.get("n_eqar") or 0)
        except (TypeError, ValueError):
            continue
        if n_bars < int(min_bar_days):
            continue
        if n_ta < int(min_fins_ta) or n_eqar < int(min_fins_eqar):
            continue
        rows.append((adv, code))
    rows.sort(key=lambda x: (-x[0], x[1]))
    out: list[str] = []
    seen: set[str] = set()
    for _adv, code in rows:
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
        if len(out) >= int(max_codes):
            break
    return out


def select_eval_universe(
    *,
    max_codes: int,
    pool: Sequence[str] | None = None,
    period_start: str = "2019-01-01",
    period_end: str = "2019-10-21",
) -> list[str]:
    """Liquidity-first universe. Missing bars/fins → skip. Never invent."""
    src = EVAL_UNIVERSE_POOL if pool is None else pool
    want = [str(c).strip() for c in src if str(c).strip()]
    n = max(1, int(max_codes))
    if not want:
        # Head-N list slice is forbidden on both eval tracks.
        return []
    rich = load_bars_from_sqlite_rich(
        codes=want,
        period_start=period_start,
        period_end=period_end,
    )
    fins = load_fins_events_from_sqlite(
        codes=want, start=period_start, end=period_end
    )
    scored: list[dict[str, Any]] = []
    for code in want:
        pairs = list(rich.get(code) or [])
        adv_vals: list[float] = []
        for _d, rec in pairs:
            if not isinstance(rec, Mapping):
                continue
            va = rec.get("Va")
            try:
                if va is not None:
                    adv_vals.append(float(va))
                    continue
            except (TypeError, ValueError):
                pass
            try:
                vo = rec.get("Vo")
                px = rec.get("close")
                if vo is not None and px is not None:
                    adv_vals.append(float(vo) * float(px))
            except (TypeError, ValueError):
                continue
        evs = list(fins.get(code) or [])
        scored.append(
            {
                "code": code,
                "adv": (sum(adv_vals) / len(adv_vals)) if adv_vals else 0.0,
                "n_bars": len(pairs),
                "n_ta": sum(1 for e in evs if e.get("ta") is not None),
                "n_eqar": sum(1 for e in evs if e.get("eq_ar") is not None),
            }
        )
    ranked = rank_eval_codes(scored, max_codes=n)
    if len(ranked) >= n:
        return ranked
    # Fill only from ranked-eligible remainder; never invent empty names.
    return ranked


# W80: prefer full-year windows when W64 full mirrors exist; else Q4.
# Full mirrors currently cover 2015/2019/2021/2023 (~Jan–Oct). Q4 kept for
# 2017/2025 so multi-year span remains ≥6 years with rate-based sufficiency.
DEFAULT_PERIODS: tuple[dict[str, Any], ...] = (
    {
        "period_id": "y2015_full",
        "year": 2015,
        "period_start": "2015-01-05",
        "period_end": "2015-10-21",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2017_q4",
        "year": 2017,
        "period_start": "2017-09-01",
        "period_end": "2017-12-29",
        "window_kind": "q4",
    },
    {
        "period_id": "y2019_full",
        "year": 2019,
        "period_start": "2019-01-04",
        "period_end": "2019-10-18",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2021_full",
        "year": 2021,
        "period_start": "2021-01-04",
        "period_end": "2021-10-15",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2023_full",
        "year": 2023,
        "period_start": "2023-01-04",
        "period_end": "2023-10-13",
        "window_kind": "full_prefer",
    },
    {
        "period_id": "y2025_q4",
        "year": 2025,
        "period_start": "2025-09-01",
        "period_end": "2025-12-29",
        "window_kind": "q4",
    },
)
# Legacy Q4-only periods (W63/W79 baseline) for regression compare.
DEFAULT_PERIODS_Q4: tuple[dict[str, Any], ...] = (
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
DEFAULT_BARS_FULL_MIRROR_DIR: Path = (
    _REPO_ROOT / ".glm-logs" / "w0815be_w64_cost_full" / "r2_mirror"
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
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Load equities_bars_daily ndjson → ``{code: [(date, close), ...]}`` sorted."""
    rich = load_bars_ndjson_rich(
        path,
        codes=codes,
        max_days=max_days,
        period_start=period_start,
        period_end=period_end,
    )
    return {c: [(d, float(r["close"])) for d, r in pairs] for c, pairs in rich.items()}


def load_bars_ndjson_rich(
    path: str | Path,
    *,
    codes: Sequence[str] | None = None,
    max_days: int | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Load bars with close + liquidity fields for W80 cost modulation.

    Each value: ``(date, {close, Va, Vo, AdjC, AdjVo, Code, Date})``.
    """
    p = Path(path)
    code_filter = {str(c).strip() for c in codes} if codes else None
    p_start = str(period_start)[:10] if period_start else None
    p_end = str(period_end)[:10] if period_end else None
    by_code: dict[str, dict[str, dict[str, Any]]] = {}
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
            if p_start and date < p_start:
                continue
            if p_end and date > p_end:
                continue
            close = payload.get("C")
            if close is None:
                close = payload.get("Close") or payload.get("AdjC")
            try:
                c = float(close)
            except (TypeError, ValueError):
                continue
            rec = {
                "close": c,
                "C": c,
                "Close": c,
                "Code": code,
                "Date": date,
                "date": date,
                "Va": payload.get("Va") or payload.get("AVa") or payload.get("MVa"),
                "Vo": payload.get("Vo") or payload.get("AVo") or payload.get("MVo"),
                "AdjC": payload.get("AdjC") or payload.get("AAdjC"),
                "AdjVo": payload.get("AdjVo") or payload.get("AAdjVo"),
            }
            by_code.setdefault(code, {})[date] = rec

    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for code, dmap in by_code.items():
        pairs = sorted(dmap.items(), key=lambda x: x[0])
        if max_days is not None and len(pairs) > int(max_days):
            pairs = pairs[-int(max_days) :]
        out[code] = pairs
    return out


def load_bars_from_sqlite_rich(
    *,
    codes: Sequence[str],
    period_start: str,
    period_end: str,
    db_path: str | Path = DEFAULT_SQLITE,
    max_days: int | None = None,
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Load extra names from sqlite ``jquants_records`` via PK range per code.

    Local ndjson mirrors are a 30-name shard. Missing requested codes are
    filled from COMPLETE-backed sqlite (no invent). Empty code → omitted.
    """
    db = Path(db_path)
    want = [str(c).strip() for c in codes if str(c).strip()]
    if not db.exists() or not want:
        return {}
    p0 = str(period_start)[:10]
    p1 = str(period_end)[:10]
    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT payload FROM jquants_records "
            "WHERE source = 'jquants' AND dataset = 'equities_bars_daily' "
            "AND natural_key >= ? AND natural_key <= ?"
        )
        for code in want:
            lo = json.dumps({"Code": code, "Date": p0}, separators=(",", ":"))
            hi = json.dumps({"Code": code, "Date": p1 + "~"}, separators=(",", ":"))
            dmap: dict[str, dict[str, Any]] = {}
            for (payload,) in con.execute(sql, (lo, hi)):
                try:
                    pl = json.loads(payload) if isinstance(payload, str) else payload
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(pl, Mapping):
                    continue
                date = str(pl.get("Date") or pl.get("date") or "")[:10]
                if not date or date < p0 or date > p1:
                    continue
                close = pl.get("C")
                if close is None:
                    close = pl.get("Close") or pl.get("AdjC") or pl.get("AAdjC")
                try:
                    c = float(close)
                except (TypeError, ValueError):
                    continue
                dmap[date] = {
                    "close": c,
                    "C": c,
                    "Close": c,
                    "Code": code,
                    "Date": date,
                    "date": date,
                    "Va": pl.get("Va") or pl.get("AVa") or pl.get("MVa"),
                    "Vo": pl.get("Vo") or pl.get("AVo") or pl.get("MVo"),
                    "AdjC": pl.get("AdjC") or pl.get("AAdjC"),
                    "AdjVo": pl.get("AdjVo") or pl.get("AAdjVo"),
                }
            if not dmap:
                continue
            pairs = sorted(dmap.items(), key=lambda x: x[0])
            if max_days is not None and len(pairs) > int(max_days):
                pairs = pairs[-int(max_days) :]
            out[code] = pairs
    finally:
        con.close()
    return out


def fins_summary_ta_eqar_stats(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Count TA / EqAR / Eq non-null rates in fins_summary payloads. No invent."""
    db = Path(db_path)
    out: dict[str, Any] = {
        "dataset": "fins_summary",
        "official_keys": dict(FINS_SUMMARY_OFFICIAL_KEYS),
        "n_rows": 0,
        "n_ta_nonnull": 0,
        "n_eqar_nonnull": 0,
        "n_eq_nonnull": 0,
        "ncta_nonnull": 0,
        "sample_ta": [],
        "sample_eqar": [],
        "invent": False,
        "note": (
            "NCTA is a non-consolidated alias and is sparse. Official v2 "
            "summary uses TA (total assets) and EqAR (equity/assets)."
        ),
    }
    if not db.exists():
        out["error"] = "sqlite_missing"
        return out
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = "SELECT payload FROM jquants_records WHERE dataset = 'fins_summary'"
        if limit:
            sql += f" LIMIT {int(limit)}"
        n = n_ta = n_eqar = n_eq = n_ncta = 0
        samples_ta: list[dict[str, Any]] = []
        samples_eqar: list[dict[str, Any]] = []
        for (payload,) in con.execute(sql):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            n += 1

            def _ok(key: str) -> bool:
                v = pl.get(key)
                if v in (None, ""):
                    return False
                try:
                    float(v)
                    return True
                except (TypeError, ValueError):
                    return False

            if _ok(FINS_SUMMARY_TA_KEY):
                n_ta += 1
                if len(samples_ta) < 3:
                    samples_ta.append(
                        {
                            "code": pl.get("Code"),
                            "disc": pl.get("DiscDate"),
                            "ta": pl.get(FINS_SUMMARY_TA_KEY),
                            "doctype": pl.get("DocType"),
                        }
                    )
            if _ok(FINS_SUMMARY_EQAR_KEY):
                n_eqar += 1
                if len(samples_eqar) < 3:
                    samples_eqar.append(
                        {
                            "code": pl.get("Code"),
                            "disc": pl.get("DiscDate"),
                            "eq_ar": pl.get(FINS_SUMMARY_EQAR_KEY),
                            "doctype": pl.get("DocType"),
                        }
                    )
            if _ok(FINS_SUMMARY_EQ_KEY):
                n_eq += 1
            if _ok("NCTA"):
                n_ncta += 1
        out.update(
            {
                "n_rows": n,
                "n_ta_nonnull": n_ta,
                "n_eqar_nonnull": n_eqar,
                "n_eq_nonnull": n_eq,
                "ncta_nonnull": n_ncta,
                "ta_rate": (n_ta / n) if n else None,
                "eqar_rate": (n_eqar / n) if n else None,
                "eq_rate": (n_eq / n) if n else None,
                "ncta_rate": (n_ncta / n) if n else None,
                "sample_ta": samples_ta,
                "sample_eqar": samples_eqar,
            }
        )
    finally:
        con.close()
    return out


def bars_rich_to_close_panel(
    rich: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
) -> dict[str, list[tuple[str, float]]]:
    """Strip rich bars to (date, close) panel."""
    return {
        str(c): [(d, float(r["close"])) for d, r in pairs]
        for c, pairs in rich.items()
    }


def collect_liquidity_bar_rows(
    rich: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
) -> list[dict[str, Any]]:
    """Flatten rich bars to rows for ``compute_liquidity_proxy_from_bars``."""
    rows: list[dict[str, Any]] = []
    for code, pairs in rich.items():
        for d, r in pairs:
            row = dict(r)
            row.setdefault("Code", code)
            row.setdefault("Date", d)
            rows.append(row)
    return rows


def repo_history_plane_status(
    db_path: str | Path = DEFAULT_SQLITE,
) -> dict[str, Any]:
    """Disclose sqlite history vs D1 hot tip vs PIT fail-closed.

    Coverage V2 COMPLETE is receipt-owned (quant-mcp). This helper does not
    invent COMPLETE, does not ffill, and does not declare READY.
    """
    db = Path(db_path)
    n = 0
    mn = mx = None
    tenors = 0
    if db.exists():
        con = sqlite3.connect(str(db))
        try:
            n, mn, mx = con.execute(
                "SELECT COUNT(*), MIN(as_of_date), MAX(as_of_date) "
                "FROM jsda_repo_rates"
            ).fetchone()
            tenors = int(
                con.execute(
                    "SELECT COUNT(DISTINCT tenor) FROM jsda_repo_rates"
                ).fetchone()[0]
                or 0
            )
        except sqlite3.Error:
            n = 0
        finally:
            con.close()
    return {
        "dataset": "jsda_tokyo_repo_rates",
        "table": "jsda_repo_rates",
        "sqlite_rows": int(n or 0),
        "sqlite_min": mn,
        "sqlite_max": mx,
        "sqlite_tenors": int(tenors or 0),
        "d1_role": "hot_tip_only",
        "pit_path": "fail_closed_until_READY",
        "research_loader": "load_repo_rows_all_tenors_from_sqlite",
        "invent_complete": False,
        "ffill_applied": False,
        "note": (
            "D1 jsda_repo_rates is hot tip (~days). Historical eval reads "
            "this sqlite / R2. PIT get_jsda_repo_rates stays fail-closed "
            "while production READY is undeclared."
        ),
    }


def load_repo_rows_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    start: str | None = None,
    end: str | None = None,
    tenor_contains: str | None = "overnight",
) -> list[dict[str, Any]]:
    """Load jsda_repo_rates rows from local SQLite (research offline path).

    Not the PIT path. PIT ``get_jsda_repo_rates`` is fail-closed until READY.
    D1 holds hot tip only; this sqlite holds the COMPLETE time-series history.
    """
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


def load_repo_rows_all_tenors_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    """Load all JSDA Tokyo repo tenors (for curve-shape proxy; no invent)."""
    return load_repo_rows_from_sqlite(
        db_path, start=start, end=end, tenor_contains=None
    )


def build_repo_curve_series(
    rows: Sequence[Mapping[str, Any]] | None,
    *,
    short_tenor: str = REPO_CURVE_SHORT_TENOR,
    long_tenor: str = REPO_CURVE_LONG_TENOR,
) -> dict[str, Any]:
    """Build date-keyed short/long rates + spread from multi-tenor rows.

    Curve definition (documented):
    ``spread[d] = rate(long_tenor, d) − rate(short_tenor, d)``.
    Only observed JSDA repo tenors; missing either leg → gap (no invent/ffill).
    This is a **funding term-structure proxy**, not a sovereign JGB/OIS curve.
    """
    by_date_tenor: dict[str, dict[str, float]] = {}
    for raw in rows or []:
        d = str(raw.get("as_of_date") or raw.get("date") or "")[:10]
        if not d or len(d) < 10:
            continue
        t = str(raw.get("tenor") or "")
        rate = raw.get("rate")
        if rate is None or rate == "":
            continue
        try:
            rate_f = float(rate)
        except (TypeError, ValueError):
            continue
        by_date_tenor.setdefault(d, {})[t] = rate_f

    short_by: dict[str, float] = {}
    long_by: dict[str, float] = {}
    spread_by: dict[str, float] = {}
    gap_dates: list[str] = []
    for d, tenors in sorted(by_date_tenor.items()):
        s = tenors.get(short_tenor)
        lo = tenors.get(long_tenor)
        if s is not None:
            short_by[d] = s
        if lo is not None:
            long_by[d] = lo
        if s is not None and lo is not None:
            spread_by[d] = lo - s
        else:
            gap_dates.append(d)

    return {
        "kind": "repo_curve_series",
        "dataset": "jsda_tokyo_repo_rates",
        "short_tenor": short_tenor,
        "long_tenor": long_tenor,
        "definition": "spread = long_tenor_rate - short_tenor_rate (same as_of_date)",
        "note": (
            "Funding term-structure proxy from JSDA Tokyo repo tenors only. "
            "Not JGB/OIS. Gaps disclosed; never ffilled or invented."
        ),
        "short_rates_by_date": dict(sorted(short_by.items())),
        "long_rates_by_date": dict(sorted(long_by.items())),
        "spread_by_date": dict(sorted(spread_by.items())),
        # Alias used by rate-level path when overnight preferred
        "rates_by_date": dict(sorted(short_by.items())),
        "n_obs_short": len(short_by),
        "n_obs_long": len(long_by),
        "n_obs_spread": len(spread_by),
        "n_gap_either_leg": len(gap_dates),
        "gap_dates_sample": gap_dates[:20],
        "ffill_applied": False,
        "invent_fill": False,
        "tenors_observed": sorted(
            {t for m in by_date_tenor.values() for t in m.keys()}
        ),
    }


def _annualized_realized_vol(
    closes: Sequence[float], end_i: int, window: int
) -> float | None:
    """Sample stdev of 1-session returns over ``window``, annualized √252."""
    if end_i < window or window < 2:
        return None
    rets: list[float] = []
    for j in range(end_i - window + 1, end_i + 1):
        if j < 1:
            return None
        c0, c1 = closes[j - 1], closes[j]
        if c0 is None or c1 is None or float(c0) == 0.0:
            return None
        rets.append((float(c1) / float(c0)) - 1.0)
    if len(rets) < 2:
        return None
    m = mean(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    if var < 0:
        return None
    return float(var ** 0.5) * (float(TRADING_DAYS_ANN) ** 0.5)


def load_topix_close_series_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[tuple[str, float]]:
    """Load TOPIX closes from indices_bars_daily_topix (prefer) or code 0000."""
    db = Path(db_path)
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out: list[tuple[str, float]] = []
        # Prefer dedicated TOPIX dataset
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'indices_bars_daily_topix'"
        )
        params: list[Any] = []
        if start:
            sql += " AND event_time >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND event_time <= ?"
            params.append(str(end)[:10] + "T23:59:59")
        sql += " ORDER BY event_time ASC"
        for _nk, event_time, payload in con.execute(sql, params):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            d = str(pl.get("Date") or str(event_time or "")[:10])[:10]
            c = pl.get("C") if pl.get("C") is not None else pl.get("Close")
            if not d or c is None or c == "":
                continue
            try:
                out.append((d, float(c)))
            except (TypeError, ValueError):
                continue
        if out:
            return out
        # Fallback: indices_bars_daily code 0000 (TOPIX)
        sql2 = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'indices_bars_daily' "
            "AND (natural_key LIKE '%\"Code\":\"0000\"%' OR natural_key LIKE '%\"code\":\"0000\"%')"
        )
        params2: list[Any] = []
        if start:
            sql2 += " AND event_time >= ?"
            params2.append(str(start)[:10])
        if end:
            sql2 += " AND event_time <= ?"
            params2.append(str(end)[:10] + "T23:59:59")
        sql2 += " ORDER BY event_time ASC"
        for _nk, event_time, payload in con.execute(sql2, params2):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            d = str(pl.get("Date") or str(event_time or "")[:10])[:10]
            c = pl.get("C") if pl.get("C") is not None else pl.get("Close")
            if not d or c is None or c == "":
                continue
            try:
                out.append((d, float(c)))
            except (TypeError, ValueError):
                continue
        return out
    finally:
        con.close()


def load_nk225f_front_close_series_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[tuple[str, float]]:
    """Continuous front Nikkei 225 futures closes (max open interest per day).

    Cash Nikkei average is not in indices_bars_daily; NK225F front is the
    primary price proxy for Nikkei realized-vol construction.
    """
    db = Path(db_path)
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'derivatives_bars_daily_futures' "
            "AND payload LIKE '%\"ProdCat\":\"NK225F\"%'"
        )
        params: list[Any] = []
        if start:
            # lookback buffer for long RV window
            sql += " AND event_time >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND event_time <= ?"
            params.append(str(end)[:10] + "T23:59:59")
        sql += " ORDER BY event_time ASC"
        by_date: dict[str, list[tuple[float, float]]] = {}
        for _nk, event_time, payload in con.execute(sql, params):
            try:
                pl = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(pl, Mapping):
                continue
            if str(pl.get("ProdCat") or "") != "NK225F":
                continue
            d = str(pl.get("Date") or str(event_time or "")[:10])[:10]
            if not d:
                continue
            px = pl.get("C")
            if px is None or px == "" or float(px or 0) <= 0:
                px = pl.get("Settle")
            if px is None or px == "" or float(px or 0) <= 0:
                px = pl.get("AC")
            try:
                px_f = float(px) if px is not None and px != "" else 0.0
            except (TypeError, ValueError):
                continue
            if px_f <= 0:
                continue
            try:
                oi = float(pl.get("OI") or 0.0)
            except (TypeError, ValueError):
                oi = 0.0
            by_date.setdefault(d, []).append((oi, px_f))
        out: list[tuple[str, float]] = []
        for d in sorted(by_date.keys()):
            best = max(by_date[d], key=lambda x: x[0])
            out.append((d, best[1]))
        return out
    finally:
        con.close()


def build_nky_vol_series(
    close_pairs: Sequence[tuple[str, float]] | None,
    *,
    short_n: int = DEFAULT_NKY_VOL_SHORT_N,
    long_n: int = DEFAULT_NKY_VOL_LONG_N,
    source: str = NKY_VOL_PROXY_NK225F,
    dataset: str = "derivatives_bars_daily_futures",
) -> dict[str, Any]:
    """Build date-keyed short/long annualized realized vol + ratio.

    Gaps disclosed; no invent/ffill of missing sessions.
    """
    sn = int(short_n)
    ln = int(long_n)
    if sn < 2:
        sn = DEFAULT_NKY_VOL_SHORT_N
    if ln < sn:
        ln = max(sn + 1, DEFAULT_NKY_VOL_LONG_N)
    pairs = sorted(
        [(str(d)[:10], float(c)) for d, c in (close_pairs or []) if d and c is not None],
        key=lambda x: x[0],
    )
    # de-dup last wins
    by_d: dict[str, float] = {}
    for d, c in pairs:
        by_d[d] = c
    dates = sorted(by_d.keys())
    closes = [by_d[d] for d in dates]
    short_by: dict[str, float] = {}
    long_by: dict[str, float] = {}
    ratio_by: dict[str, float] = {}
    for i, d in enumerate(dates):
        s = _annualized_realized_vol(closes, i, sn)
        lo = _annualized_realized_vol(closes, i, ln)
        if s is not None:
            short_by[d] = s
        if lo is not None:
            long_by[d] = lo
        if s is not None and lo is not None and lo > 1e-12:
            ratio_by[d] = s / lo
    return {
        "kind": "nky_vol_series",
        "dataset": dataset,
        "source": source,
        "proxy_note": (
            "Cash Nikkei not in indices_bars_daily. Prefer NK225F front "
            "realized; TOPIX fallback. NKVIF is implied-vol futures (optional)."
        ),
        "short_n": sn,
        "long_n": ln,
        "annualization": f"sample_stdev * sqrt({TRADING_DAYS_ANN})",
        "closes_by_date": dict(sorted(by_d.items())),
        "rv_short_by_date": dict(sorted(short_by.items())),
        "rv_long_by_date": dict(sorted(long_by.items())),
        "rv_ratio_by_date": dict(sorted(ratio_by.items())),
        # abs-level uses short window by default
        "rv_abs_by_date": dict(sorted(short_by.items())),
        "n_close_obs": len(by_d),
        "n_obs_short": len(short_by),
        "n_obs_long": len(long_by),
        "n_obs_ratio": len(ratio_by),
        "ffill_applied": False,
        "invent_fill": False,
    }


def load_topix_close_series_from_ndjson(
    path: str | Path,
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[tuple[str, float]]:
    """Load TOPIX closes from a local indices_bars_daily_topix ndjson mirror."""
    p = Path(path)
    if not p.is_file():
        return []
    p_start = str(start)[:10] if start else None
    p_end = str(end)[:10] if end else None
    by_date: dict[str, float] = {}
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = row.get("payload") if isinstance(row, Mapping) else None
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    continue
            if not isinstance(payload, Mapping):
                payload = row if isinstance(row, Mapping) else None
            if not isinstance(payload, Mapping):
                continue
            d = str(payload.get("Date") or payload.get("date") or "")[:10]
            if not d:
                continue
            if p_start and d < p_start:
                continue
            if p_end and d > p_end:
                continue
            c = payload.get("C")
            if c is None:
                c = payload.get("Close") or payload.get("close")
            try:
                px = float(c)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if px > 0:
                by_date[d] = px
    return sorted(by_date.items(), key=lambda x: x[0])


def load_nky_vol_series_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    start: str | None = None,
    end: str | None = None,
    short_n: int = DEFAULT_NKY_VOL_SHORT_N,
    long_n: int = DEFAULT_NKY_VOL_LONG_N,
    prefer: str = "ndjson_topix",
) -> dict[str, Any]:
    """Load Nikkei-proxy closes and build short/long realized-vol series.

    Priority (wall-clock safe):
      1. Local TOPIX ndjson mirror (fast, multi-year COMPLETE-backed)
      2. Optional sqlite NK225F / TOPIX (slow on full D1 dump — skipped by default)
    Prefer=ndjson_topix is the default for factory/CF staging.
    """
    pref = str(prefer or "ndjson_topix").strip().lower()
    lookback_days = max(int(long_n) * 3, 120)
    load_start = start
    if start:
        try:
            from datetime import date as _date
            from datetime import timedelta

            ds = _date.fromisoformat(str(start)[:10])
            load_start = (ds - timedelta(days=lookback_days)).isoformat()
        except ValueError:
            load_start = start

    nk_pairs: list[tuple[str, float]] = []
    source = NKY_VOL_PROXY_TOPIX
    dataset = "indices_bars_daily_topix"

    # Fast path: local TOPIX ndjson (W60 multi-signal mirror).
    if pref in {"ndjson_topix", "topix", "auto", "ndjson"}:
        topix_ndjson = (
            _REPO_ROOT
            / ".glm-logs"
            / "w0815ba_w60_long_multisignal"
            / "r2_mirror"
            / "indices_bars_daily_topix.ndjson"
        )
        if topix_ndjson.is_file():
            nk_pairs = load_topix_close_series_from_ndjson(
                topix_ndjson, start=load_start, end=end
            )
            if nk_pairs:
                source = NKY_VOL_PROXY_TOPIX
                dataset = "indices_bars_daily_topix"
                return build_nky_vol_series(
                    nk_pairs,
                    short_n=short_n,
                    long_n=long_n,
                    source=source,
                    dataset=dataset,
                )

    # Slow optional path: sqlite (only when explicitly requested).
    if pref in {"nk225f", "sqlite", "sqlite_nk225f"}:
        nk_pairs = load_nk225f_front_close_series_from_sqlite(
            db_path, start=load_start, end=end
        )
        source = NKY_VOL_PROXY_NK225F
        dataset = "derivatives_bars_daily_futures"
    if len(nk_pairs) < max(int(long_n) + 2, 30) and pref in {
        "nk225f",
        "sqlite",
        "sqlite_topix",
        "sqlite_nk225f",
    }:
        topix = load_topix_close_series_from_sqlite(
            db_path, start=load_start, end=end
        )
        if len(topix) > len(nk_pairs):
            nk_pairs = topix
            source = NKY_VOL_PROXY_TOPIX
            dataset = "indices_bars_daily_topix"
    return build_nky_vol_series(
        nk_pairs, short_n=short_n, long_n=long_n, source=source, dataset=dataset
    )


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
    prefer_full: bool = True,
) -> Path | None:
    """Map period_id like y2015_q4 / y2015_full → local ndjson mirror path.

    W80: prefer full-year W64 mirrors when ``prefer_full`` and period is full
    or period_id contains ``full``.
    """
    d = Path(mirror_dir)
    year = _period_year(period_id)
    if year is None:
        return None
    pid = str(period_id).lower()
    want_full = prefer_full and ("full" in pid or not pid.endswith("q4"))
    full_path = (
        DEFAULT_BARS_FULL_MIRROR_DIR / f"equities_bars_daily_y{year}_full.ndjson"
    )
    q4_path = d / f"equities_bars_daily_y{year}_q4.ndjson"
    candidates: list[Path] = []
    if want_full:
        candidates.extend(
            [
                full_path,
                d / f"equities_bars_daily_y{year}_full.ndjson",
                q4_path,
            ]
        )
    else:
        candidates.extend(
            [
                q4_path,
                full_path,
                d / f"equities_bars_daily_y{year}_full.ndjson",
            ]
        )
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

    Each event: disc_date, disc_time, eps, feps, bps, prior_eps, event_time,
    available_at (row envelope when selected). DiscTime never invented.
    """
    db = Path(db_path)
    if not db.exists():
        return {}
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        # Prefer available_at when column present (PIT envelope).
        cols = {
            r[1]
            for r in con.execute("PRAGMA table_info(jquants_records)").fetchall()
        }
        has_aa = "available_at" in cols
        aa_sel = ", available_at" if has_aa else ""
        sql = (
            "SELECT natural_key, event_time, payload"
            f"{aa_sel} FROM jquants_records "
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
        for row in con.execute(sql, params):
            if has_aa:
                _nk, event_time, payload, row_aa = row
            else:
                _nk, event_time, payload = row
                row_aa = None
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
            disc = str(pl.get("DiscDate") or pl.get("DisclosedDate") or str(event_time or "")[:10])[:10]
            if not disc:
                continue
            disc_time = pl.get("DiscTime") or pl.get("DisclosedTime")
            if disc_time is not None:
                disc_time = str(disc_time).strip() or None

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
                    "disc_time": disc_time,
                    "eps": _f("EPS"),
                    "feps": _f("FEPS"),
                    "bps": _f("BPS"),
                    "roe": _f("ROE"),
                    "div_ann": _f("DivAnn"),
                    "np": _f("NP"),
                    "sales": _f("Sales"),
                    "eq": (
                        _f(FINS_SUMMARY_EQ_KEY)
                        if _f(FINS_SUMMARY_EQ_KEY) is not None
                        else _f("ShEq")
                    ),
                    "ta": _f(FINS_SUMMARY_TA_KEY),
                    "eq_ar": _f(FINS_SUMMARY_EQAR_KEY),
                    "event_time": str(event_time) if event_time else None,
                    "available_at": str(row_aa) if row_aa else None,
                    "source": "fins_summary",
                }
            )
        # Attach prior_eps chronologically
        for code, events in by_code.items():
            events.sort(key=lambda e: e["disc_date"])
            last_eps = None
            last_ta = None
            for ev in events:
                ev["prior_eps"] = last_eps
                ev["prior_ta"] = last_ta
                if ev.get("eps") is not None:
                    last_eps = ev["eps"]
                if ev.get("ta") is not None:
                    last_ta = ev["ta"]
        return by_code
    finally:
        con.close()


def load_fins_earnings_date_from_sqlite(
    db_path: str | Path = DEFAULT_SQLITE,
    *,
    codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load fins_earnings_date calendar → ``{code: [event_dict, ...]}``.

    Event keys: disc_date (PubDate prefer, else SchDate), sch_date, pub_date,
    source=fins_earnings_date. No invent; missing PubDate uses SchDate.
    """
    db = Path(db_path)
    if not db.exists():
        return {}
    code_list = [str(c).strip() for c in (codes or []) if str(c).strip()]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT natural_key, event_time, payload FROM jquants_records "
            "WHERE dataset = 'fins_earnings_date'"
        )
        params: list[Any] = []
        if start:
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
            pub = str(pl.get("PubDate") or "")[:10] or None
            sch = str(pl.get("SchDate") or "")[:10] or None
            disc = pub or sch or str(event_time or "")[:10]
            if not disc:
                continue
            by_code.setdefault(code, []).append(
                {
                    "disc_date": disc,
                    "pub_date": pub,
                    "sch_date": sch,
                    "eps": None,
                    "feps": None,
                    "bps": None,
                    "prior_eps": None,
                    "source": "fins_earnings_date",
                    "event_time": str(event_time) if event_time else None,
                    "fq_name": pl.get("FQName"),
                }
            )
        for code, events in by_code.items():
            events.sort(key=lambda e: e["disc_date"])
        return by_code
    finally:
        con.close()


def merge_event_calendars(
    fins_summary: Mapping[str, Sequence[Mapping[str, Any]]],
    earnings_date: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Thicken event calendar: fins_summary primary; earnings_date fills gaps.

    Same (code, disc_date) prefers fins_summary (has EPS/FEPS for surprise).
    Earnings-only dates enter with null surprise (skipped by scoring unless
    later joined). Disclosed; no invent of surprise.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    codes = set(fins_summary.keys()) | set((earnings_date or {}).keys())
    for code in codes:
        by_date: dict[str, dict[str, Any]] = {}
        for ev in earnings_date.get(code, []) if earnings_date else []:
            d = str(ev.get("disc_date") or "")[:10]
            if not d:
                continue
            by_date[d] = dict(ev)
            by_date[d]["source"] = "fins_earnings_date"
        for ev in fins_summary.get(code, []) or []:
            d = str(ev.get("disc_date") or "")[:10]
            if not d:
                continue
            base = by_date.get(d, {})
            merged = dict(base)
            merged.update(dict(ev))
            merged["source"] = "fins_summary"
            if base.get("source") == "fins_earnings_date":
                merged["thickened_from_earnings_date"] = True
            by_date[d] = merged
        events = list(by_date.values())
        events.sort(key=lambda e: e["disc_date"])
        # re-attach prior_eps from fins_summary eps chain
        last_eps = None
        for ev in events:
            if ev.get("prior_eps") is None:
                ev["prior_eps"] = last_eps
            if ev.get("eps") is not None:
                last_eps = ev["eps"]
        out[str(code)] = events
    return out


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
    trade_stats = trade_stats_report(
        signed_returns,
        hold_days=h,
        one_way_cost=float(one_way_cost),
        amortize_cost=True,
        trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
    )

    n_code_days = len(holding_records)
    n_codes = len(bars_by_code)
    all_dates = {r["date"] for r in holding_records}
    n_trading_days = len(all_dates)
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )

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
        "n_codes": n_codes,
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        "trade_stats": trade_stats,
        "per_code_sample": per_code_stats[:10],
        "holding_records": holding_records,
        "non_null": n_active,
        "non_null_rate": (
            float(n_active) / float(n_code_days) if n_code_days else None
        ),
        **_freeze(),
        "note": (
            f"Multi-day hold n={h}: sticky fixed_horizon; "
            "gross = mean(sign * R_hold); net = gross - one_way/hold_days. "
            "Occurrence = activation rate (not count alone). "
            "trade_stats = t/Sharpe/winrate on hold nets. "
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
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=1,  # daily re-check path
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )

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
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        "holding_records": holding_records,
        "non_null": n_active,
        "non_null_rate": (
            float(n_active) / float(n_code_days) if n_code_days else None
        ),
        "repo_dataset": REPO_DATASET_ID,
        **_freeze(),
        "note": (
            f"Macro-conditioned momentum mode={mode} on jsda_tokyo_repo_rates. "
            "Repo gaps → no trade (no invent). Not READY / not Mass."
        ),
    }


def evaluate_rate_level_xs_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    repo_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
) -> dict[str, Any]:
    """Absolute rate-level factor × CS book (risk-on/off), multi-day sticky.

    Distinct from macro_conditioned rate_level (unidirectional mom gate).
    """
    from research.cost_models import lookup_repo_rate

    n = int(momentum_n)
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    by_date: dict[str, dict[str, float | None]] = {}
    dates_by_code: dict[str, list[str]] = {}
    closes_list: dict[str, list[float]] = {}
    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        moms = momentum_series(pairs_l, n=n)
        for d, m in moms:
            by_date.setdefault(d, {})[code] = m
        dates_by_code[code] = [d for d, _ in pairs_l]
        closes_list[code] = [c for _, c in pairs_l]

    dates = sorted(by_date.keys())
    # Daily CS rank signs, then rate-level risk-adjust
    daily_adj: dict[str, dict[str, float | None]] = {c: {} for c in bars_by_code}
    n_regime_gap = 0
    regime_counts: dict[str, int] = {}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date[d], long_frac=long_frac, short_frac=short_frac
        )
        hit = lookup_repo_rate(repo_series, d) if repo_series else {"is_gap": True}
        if hit.get("is_gap") or hit.get("rate_pct") is None:
            n_regime_gap += 1
            for code in ranks:
                daily_adj.setdefault(code, {})[d] = None
            continue
        rate = hit.get("rate_pct")
        for code, cs_sign in ranks.items():
            rec = compute_rate_level_xs_signal(
                cs_sign=cs_sign,
                repo_rate=rate,
                high_threshold=high_threshold,
                low_threshold=low_threshold,
                code=code,
                date=d,
            )
            reg = rec.get("regime")
            if reg is not None:
                regime_counts[str(reg)] = regime_counts.get(str(reg), 0) + 1
            daily_adj.setdefault(code, {})[d] = rec.get("value")

    signed_returns: list[float] = []
    n_active = 0
    holding_records: list[dict[str, Any]] = []
    for code, dlist in dates_by_code.items():
        entries = [daily_adj.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        closes = closes_list[code]
        for i, pos in enumerate(held):
            holding_records.append({"date": dlist[i], "code": code, "sign": pos})
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
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": SIGNAL_ID_RATE_LEVEL_XS,
        "hypothesis_class": CLASS_RATE_FACTOR,
        "mode": "rate_level_xs_risk_adj",
        "momentum_n": n,
        "hold_days": h,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            "Absolute rate-level factor × CS risk-on/off book on "
            "jsda_tokyo_repo_rates. Not macro mom-gate. Not READY / not Mass."
        ),
    }


def evaluate_rate_curve_xs_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    curve_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    steep_threshold: float = DEFAULT_CURVE_STEEP_THRESHOLD,
    invert_threshold: float = DEFAULT_CURVE_INVERT_THRESHOLD,
) -> dict[str, Any]:
    """Repo curve-shape factor × CS book (steep keep / inverted reverse)."""
    n = int(momentum_n)
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    short_by = dict((curve_series or {}).get("short_rates_by_date") or {})
    long_by = dict((curve_series or {}).get("long_rates_by_date") or {})

    by_date: dict[str, dict[str, float | None]] = {}
    dates_by_code: dict[str, list[str]] = {}
    closes_list: dict[str, list[float]] = {}
    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        moms = momentum_series(pairs_l, n=n)
        for d, m in moms:
            by_date.setdefault(d, {})[code] = m
        dates_by_code[code] = [d for d, _ in pairs_l]
        closes_list[code] = [c for _, c in pairs_l]

    dates = sorted(by_date.keys())
    daily_adj: dict[str, dict[str, float | None]] = {c: {} for c in bars_by_code}
    n_regime_gap = 0
    regime_counts: dict[str, int] = {}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date[d], long_frac=long_frac, short_frac=short_frac
        )
        # exact date match; no invent/ffill
        s_rate = short_by.get(str(d)[:10])
        l_rate = long_by.get(str(d)[:10])
        if s_rate is None or l_rate is None:
            n_regime_gap += 1
            for code in ranks:
                daily_adj.setdefault(code, {})[d] = None
            continue
        for code, cs_sign in ranks.items():
            rec = compute_rate_curve_xs_signal(
                cs_sign=cs_sign,
                short_rate=s_rate,
                long_rate=l_rate,
                steep_threshold=steep_threshold,
                invert_threshold=invert_threshold,
                code=code,
                date=d,
            )
            reg = rec.get("regime")
            if reg is not None:
                regime_counts[str(reg)] = regime_counts.get(str(reg), 0) + 1
            daily_adj.setdefault(code, {})[d] = rec.get("value")

    signed_returns: list[float] = []
    n_active = 0
    holding_records: list[dict[str, Any]] = []
    for code, dlist in dates_by_code.items():
        entries = [daily_adj.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        closes = closes_list[code]
        for i, pos in enumerate(held):
            holding_records.append({"date": dlist[i], "code": code, "sign": pos})
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
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": SIGNAL_ID_RATE_CURVE_XS,
        "hypothesis_class": CLASS_RATE_FACTOR,
        "mode": "rate_curve_shape_xs",
        "momentum_n": n,
        "hold_days": h,
        "curve_short_tenor": (curve_series or {}).get("short_tenor")
        or REPO_CURVE_SHORT_TENOR,
        "curve_long_tenor": (curve_series or {}).get("long_tenor")
        or REPO_CURVE_LONG_TENOR,
        "curve_definition": (curve_series or {}).get("definition"),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            "Repo curve-shape factor (3M−overnight) × CS book. "
            "JSDA tenors only; no invent. Not READY / not Mass."
        ),
    }


def _evaluate_nky_vol_xs_core(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    nky_vol_series: Mapping[str, Any] | None,
    *,
    mode: str,
    momentum_n: int,
    hold_days: int,
    long_frac: float,
    short_frac: float,
    one_way_cost: float,
    high_threshold: float,
    low_threshold: float,
    expand_ratio: float,
    compress_ratio: float,
) -> dict[str, Any]:
    """Shared CS × index-vol regime evaluator for abs / term_levels / term_ratio."""
    n = int(momentum_n)
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    m = str(mode or "nky_vol_abs_level")
    short_by = dict((nky_vol_series or {}).get("rv_short_by_date") or {})
    long_by = dict((nky_vol_series or {}).get("rv_long_by_date") or {})
    abs_by = dict(
        (nky_vol_series or {}).get("rv_abs_by_date")
        or (nky_vol_series or {}).get("rv_short_by_date")
        or {}
    )

    by_date: dict[str, dict[str, float | None]] = {}
    dates_by_code: dict[str, list[str]] = {}
    closes_list: dict[str, list[float]] = {}
    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        moms = momentum_series(pairs_l, n=n)
        for d, mom in moms:
            by_date.setdefault(d, {})[code] = mom
        dates_by_code[code] = [d for d, _ in pairs_l]
        closes_list[code] = [c for _, c in pairs_l]

    dates = sorted(by_date.keys())
    daily_adj: dict[str, dict[str, float | None]] = {c: {} for c in bars_by_code}
    n_regime_gap = 0
    regime_counts: dict[str, int] = {}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date[d], long_frac=long_frac, short_frac=short_frac
        )
        dk = str(d)[:10]
        for code, cs_sign in ranks.items():
            if m == "nky_vol_term_ratio":
                rec = compute_nky_vol_term_ratio_signal(
                    cs_sign=cs_sign,
                    short_vol=short_by.get(dk),
                    long_vol=long_by.get(dk),
                    expand_ratio=expand_ratio,
                    compress_ratio=compress_ratio,
                    code=code,
                    date=d,
                )
            elif m == "nky_vol_term_levels":
                rec = compute_nky_vol_term_levels_signal(
                    cs_sign=cs_sign,
                    short_vol=short_by.get(dk),
                    long_vol=long_by.get(dk),
                    high_threshold=high_threshold,
                    low_threshold=low_threshold,
                    code=code,
                    date=d,
                )
            else:
                rec = compute_nky_vol_abs_level_signal(
                    cs_sign=cs_sign,
                    vol_level=abs_by.get(dk),
                    high_threshold=high_threshold,
                    low_threshold=low_threshold,
                    code=code,
                    date=d,
                )
            if rec.get("regime") is None and rec.get("value") is None:
                n_regime_gap += 1
            reg = rec.get("regime")
            if reg is not None:
                regime_counts[str(reg)] = regime_counts.get(str(reg), 0) + 1
            daily_adj.setdefault(code, {})[d] = rec.get("value")

    signed_returns: list[float] = []
    n_active = 0
    holding_records: list[dict[str, Any]] = []
    for code, dlist in dates_by_code.items():
        entries = [daily_adj.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        closes = closes_list[code]
        for i, pos in enumerate(held):
            holding_records.append({"date": dlist[i], "code": code, "sign": pos})
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
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    sid = {
        "nky_vol_abs_level": SIGNAL_ID_NKY_VOL_ABS_LEVEL,
        "nky_vol_term_levels": SIGNAL_ID_NKY_VOL_TERM_LEVELS,
        "nky_vol_term_ratio": SIGNAL_ID_NKY_VOL_TERM_RATIO,
    }.get(m, SIGNAL_ID_NKY_VOL_ABS_LEVEL)
    return {
        "signal_id": sid,
        "hypothesis_class": CLASS_INDEX_VOL_REGIME,
        "mode": m,
        "momentum_n": n,
        "hold_days": h,
        "vol_source": (nky_vol_series or {}).get("source"),
        "vol_dataset": (nky_vol_series or {}).get("dataset"),
        "short_n": (nky_vol_series or {}).get("short_n"),
        "long_n": (nky_vol_series or {}).get("long_n"),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            f"Index-level Nikkei/TOPIX vol regime mode={m} × CS book. "
            "Not per-name vol_risk_adjusted. Not READY / not Mass."
        ),
    }


def evaluate_nky_vol_abs_level_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    nky_vol_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_NKY_VOL_LOW_THRESHOLD,
) -> dict[str, Any]:
    """Absolute index RV level × CS risk-on/off book."""
    return _evaluate_nky_vol_xs_core(
        bars_by_code,
        nky_vol_series,
        mode="nky_vol_abs_level",
        momentum_n=momentum_n,
        hold_days=hold_days,
        long_frac=long_frac,
        short_frac=short_frac,
        one_way_cost=one_way_cost,
        high_threshold=high_threshold,
        low_threshold=low_threshold,
        expand_ratio=DEFAULT_NKY_VOL_EXPAND_RATIO,
        compress_ratio=DEFAULT_NKY_VOL_COMPRESS_RATIO,
    )


def evaluate_nky_vol_term_levels_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    nky_vol_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_NKY_VOL_LOW_THRESHOLD,
) -> dict[str, Any]:
    """Short+long absolute RV levels (agreement) × CS book."""
    return _evaluate_nky_vol_xs_core(
        bars_by_code,
        nky_vol_series,
        mode="nky_vol_term_levels",
        momentum_n=momentum_n,
        hold_days=hold_days,
        long_frac=long_frac,
        short_frac=short_frac,
        one_way_cost=one_way_cost,
        high_threshold=high_threshold,
        low_threshold=low_threshold,
        expand_ratio=DEFAULT_NKY_VOL_EXPAND_RATIO,
        compress_ratio=DEFAULT_NKY_VOL_COMPRESS_RATIO,
    )


def evaluate_nky_vol_term_ratio_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    nky_vol_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    expand_ratio: float = DEFAULT_NKY_VOL_EXPAND_RATIO,
    compress_ratio: float = DEFAULT_NKY_VOL_COMPRESS_RATIO,
) -> dict[str, Any]:
    """Short/long RV ratio × CS risk-on/off book."""
    return _evaluate_nky_vol_xs_core(
        bars_by_code,
        nky_vol_series,
        mode="nky_vol_term_ratio",
        momentum_n=momentum_n,
        hold_days=hold_days,
        long_frac=long_frac,
        short_frac=short_frac,
        one_way_cost=one_way_cost,
        high_threshold=DEFAULT_NKY_VOL_HIGH_THRESHOLD,
        low_threshold=DEFAULT_NKY_VOL_LOW_THRESHOLD,
        expand_ratio=expand_ratio,
        compress_ratio=compress_ratio,
    )


_OPT225_SIGNAL_IDS: dict[str, str] = {
    "opt225_basevol_abs_level": SIGNAL_ID_OPT225_BASEVOL_ABS,
    "opt225_basevol_term_levels": SIGNAL_ID_OPT225_BASEVOL_TERM_LEVELS,
    "opt225_basevol_term_ratio": SIGNAL_ID_OPT225_BASEVOL_TERM_RATIO,
    "opt225_atm_iv_abs_level": SIGNAL_ID_OPT225_ATM_IV_ABS,
    "opt225_atm_iv_term_levels": SIGNAL_ID_OPT225_ATM_IV_TERM_LEVELS,
    "opt225_atm_iv_term_ratio": SIGNAL_ID_OPT225_ATM_IV_TERM_RATIO,
    "opt225_iv_base_spread_abs": SIGNAL_ID_OPT225_SPREAD_ABS,
    "opt225_iv_base_spread_change": SIGNAL_ID_OPT225_SPREAD_CHANGE,
    "opt225_skew_abs_level": SIGNAL_ID_OPT225_SKEW_ABS,
    "opt225_cm_term_abs_level": SIGNAL_ID_OPT225_CM_TERM_ABS,
    "opt225_basevol_delta_abs": SIGNAL_ID_OPT225_BASEVOL_DELTA_ABS,
}


def evaluate_opt225_vol_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    opt225_series: Mapping[str, Any] | None,
    *,
    mode: str = "opt225_basevol_abs_level",
    series_kind: str = "basevol",
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_OPT225_VOL_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_OPT225_VOL_LOW_THRESHOLD,
    expand_ratio: float = DEFAULT_OPT225_VOL_EXPAND_RATIO,
    compress_ratio: float = DEFAULT_OPT225_VOL_COMPRESS_RATIO,
) -> dict[str, Any]:
    """options_225 BaseVol / ATM IV / spread regime × CS book."""
    n = int(momentum_n)
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    m = str(mode or "opt225_basevol_abs_level")
    sk = str(series_kind or "basevol")
    series = opt225_series or {}
    # Accept either a single regime map or a bundle keyed by series_kind.
    if "rv_abs_by_date" not in series and sk in series:
        series = dict(series.get(sk) or {})
    short_by = dict(series.get("rv_short_by_date") or {})
    long_by = dict(series.get("rv_long_by_date") or {})
    abs_by = dict(
        series.get("rv_abs_by_date")
        or series.get("level_by_date")
        or series.get("rv_short_by_date")
        or {}
    )
    transform = "abs_level"
    if "term_ratio" in m:
        transform = "term_ratio"
    elif "term_levels" in m:
        transform = "term_levels"

    sid = _OPT225_SIGNAL_IDS.get(m, SIGNAL_ID_OPT225_BASEVOL_ABS)
    feature_id = {
        "basevol": "opt225_basevol_level",
        "atm_iv": "opt225_atm_iv_level",
        "spread": "opt225_iv_base_spread",
        "spread_change": "opt225_iv_base_spread",
        "skew": "opt225_skew_95put",
        "cm_term": "opt225_cm_term_near_next",
        "basevol_delta": "opt225_basevol_delta",
    }.get(sk, "opt225_basevol_level")

    by_date: dict[str, dict[str, float | None]] = {}
    dates_by_code: dict[str, list[str]] = {}
    closes_list: dict[str, list[float]] = {}
    for code, pairs in bars_by_code.items():
        if str(code).startswith("__"):
            continue
        pairs_l = list(pairs)
        moms = momentum_series(pairs_l, n=n)
        for d, mom in moms:
            by_date.setdefault(d, {})[code] = mom
        dates_by_code[code] = [d for d, _ in pairs_l]
        closes_list[code] = [c for _, c in pairs_l]

    dates = sorted(by_date.keys())
    daily_adj: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_regime_gap = 0
    regime_counts: dict[str, int] = {}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date[d], long_frac=long_frac, short_frac=short_frac
        )
        dk = str(d)[:10]
        for code, cs_sign in ranks.items():
            rec = compute_opt225_vol_signal(
                mode=transform,
                cs_sign=cs_sign,
                vol_level=abs_by.get(dk),
                short_vol=short_by.get(dk),
                long_vol=long_by.get(dk),
                high_threshold=high_threshold,
                low_threshold=low_threshold,
                expand_ratio=expand_ratio,
                compress_ratio=compress_ratio,
                signal_id=sid,
                feature_id=feature_id,
                series_kind=sk,
                code=code,
                date=d,
            )
            if rec.get("regime") is None and rec.get("value") is None:
                n_regime_gap += 1
            reg = rec.get("regime")
            if reg is not None:
                regime_counts[str(reg)] = regime_counts.get(str(reg), 0) + 1
            daily_adj.setdefault(code, {})[d] = rec.get("value")

    signed_returns: list[float] = []
    n_active = 0
    holding_records: list[dict[str, Any]] = []
    for code, dlist in dates_by_code.items():
        entries = [daily_adj.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        closes = closes_list[code]
        for i, pos in enumerate(held):
            holding_records.append({"date": dlist[i], "code": code, "sign": pos})
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
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(dates_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": sid,
        "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
        "mode": m,
        "series_kind": sk,
        "transform": transform,
        "momentum_n": n,
        "hold_days": h,
        "vol_source": series.get("source"),
        "vol_dataset": series.get("dataset") or "derivatives_bars_daily_options_225",
        "units": series.get("units") or "percent_vol_points",
        "spread_convention": OPT225_SPREAD_CONVENTION,
        "short_n": series.get("short_n"),
        "long_n": series.get("long_n"),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_codes": len(dates_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            f"options_225 {sk} regime mode={m} × CS book. Canonical Nikkei vol SoT. "
            "nky_vol_* remains proxy/compare only. Not READY / not Mass."
        ),
    }


def load_opt225_regime_bundle_for_eval(
    *,
    log_dir: str | Path | None = None,
    short_n: int = DEFAULT_NKY_VOL_SHORT_N,
    long_n: int = DEFAULT_NKY_VOL_LONG_N,
) -> dict[str, Any] | None:
    """Load cached options_225 series and build regime maps for factory/CF."""
    try:
        from research.options_225_vol_series import (
            DEFAULT_OPT225_LONG_N,
            DEFAULT_OPT225_SHORT_N,
            build_opt225_regime_bundle,
            load_opt225_series_cache,
        )
    except Exception:
        return None
    cache = load_opt225_series_cache(log_dir)
    if not cache:
        return None
    sn = int(short_n) if short_n else DEFAULT_OPT225_SHORT_N
    ln = int(long_n) if long_n else DEFAULT_OPT225_LONG_N
    return build_opt225_regime_bundle(
        cache.get("base_vol_series") or [],
        cache.get("atm_iv_series") or [],
        cache.get("spread_series"),
        skew_rows=cache.get("skew_series") or None,
        term_rows=cache.get("cm_term_series") or None,
        basevol_delta_rows=cache.get("basevol_delta_series") or None,
        short_n=sn,
        long_n=ln,
    )


def evaluate_mf_value_mom_rate_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    repo_series: Mapping[str, Any] | None,
    *,
    hold_days: int = DEFAULT_FUND_HOLD_DAYS,
    momentum_n: int = DEFAULT_FUND_MOMENTUM_N,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
) -> dict[str, Any]:
    """Multi-factor value × mom × rate-level (PIT + cost)."""
    from research.cost_models import lookup_repo_rate

    h = int(hold_days)
    n = int(momentum_n)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    asof_map = load_fins_latest_asof_map(events_by_code)

    value_by_code_date: dict[str, dict[str, float | None]] = {}
    value_scores_all: list[float] = []
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

    signed_returns: list[float] = []
    n_active = 0
    n_missing = 0
    holding_records: list[dict[str, Any]] = []
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
            hit = (
                lookup_repo_rate(repo_series, d)
                if repo_series
                else {"is_gap": True}
            )
            rate = None if hit.get("is_gap") else hit.get("rate_pct")
            if vscore is None:
                n_missing += 1
                entries.append(None)
                continue
            rec = compute_mf_value_mom_rate_signal(
                value_score=vscore,
                momentum=mom_by_date.get(d),
                repo_rate=rate,
                value_benchmark=global_median,
                high_threshold=high_threshold,
                low_threshold=low_threshold,
                hold_days=h,
                code=code,
                date=d,
            )
            entries.append(rec.get("value"))
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        for i, pos in enumerate(held):
            holding_records.append({"date": dates[i], "code": code, "sign": pos})
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
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": SIGNAL_ID_MF_VALUE_MOM_RATE,
        "hypothesis_class": CLASS_MULTI_FACTOR,
        "mode": "value_mom_rate",
        "hold_days": h,
        "momentum_n": n,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_missing_fins_or_rate": n_missing,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            "Multi-factor value×mom×rate. Distinct from fund_value_mom_agree. "
            "PIT fins + date-matched repo. Not READY / not Mass."
        ),
    }


def evaluate_mf_flow_price_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    margin_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    momentum_n: int = 10,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
) -> dict[str, Any]:
    """Multi-factor flow × price-mom confirm (parallel to flow hard/soft)."""
    h = int(hold_days)
    n = int(momentum_n)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    signed_returns: list[float] = []
    n_active = 0
    n_margin_obs = 0
    holding_records: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < max(h, n) + 2:
            continue
        margin_pairs = list(margin_by_code.get(code) or [])
        if len(margin_pairs) < 2:
            continue
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

        moms = momentum_series(pairs_l, n=n)
        mom_by_date = {d: m for d, m in moms}
        dates = [d for d, _ in pairs_l]
        closes = [c for _, c in pairs_l]
        entry_signs: list[float | None] = []
        for d in dates:
            if d in margin_chg_by_date and margin_chg_by_date[d] is not None:
                rec = compute_mf_flow_price_signal(
                    margin_change=margin_chg_by_date[d],
                    momentum=mom_by_date.get(d),
                    is_trading_day=1.0,
                    hold_days=h,
                    code=code,
                    date=d,
                )
                entry_signs.append(rec.get("value"))
            else:
                entry_signs.append(None)

        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode="min_hold"
        )
        for i, pos in enumerate(held):
            holding_records.append({"date": dates[i], "code": code, "sign": pos})
            if pos is None or pos == 0.0:
                continue
            if entry_signs[i] is None or entry_signs[i] == 0.0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": SIGNAL_ID_MF_FLOW_PRICE,
        "hypothesis_class": CLASS_MULTI_FACTOR,
        "mode": "flow_price",
        "hold_days": h,
        "momentum_n": n,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_margin_obs": n_margin_obs,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            "Multi-factor flow×price confirm. Near-group parallel to "
            "flow_margin_hard/soft (do not merge). Not READY / not Mass."
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
    n_codes = len(bars_by_code)
    n_trading_days = len(dates)
    n_code_days = n_trading_days * n_codes if n_trading_days and n_codes else 0
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        hold_days=h if h > 1 else 1,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
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
        "n_codes": n_codes,
        "n_trading_days": n_trading_days,
        "n_code_days": n_code_days,
        "occurrence": occ,
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
    entry_mode: str = EVENT_POST_ENTRY_MODE,
) -> dict[str, Any]:
    """Evaluate event_post: post-disclosure multi-day hold on surprise sign.

    Scores only on disclosure events within period. Entry is **PIT-safe**:
    DiscDate+DiscTime SoT → first session close that does not look ahead
    (after-close / missing DiscTime → next trading bar). Hold is close-to-close
    over ``post_hold_days`` sessions from that entry.
    """
    h = int(post_hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    signed_returns: list[float] = []
    n_events = 0
    n_scored = 0
    n_no_surprise = 0
    n_no_bar_match = 0
    n_same_day_entry = 0
    n_next_session_entry = 0
    holding_records: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 1:
            continue
        date_to_idx = {str(d)[:10]: i for i, (d, _) in enumerate(pairs_l)}
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
            # Prefer envelope available_at / event_time when present (dataset SoT)
            disc_time = ev.get("disc_time")
            event_time = ev.get("event_time") or ev.get("available_at")
            idx, entry_date, entry_meta = event_post_entry_bar_index(
                date_to_idx,
                disc_date=disc,
                disc_time=disc_time,
                event_time=str(event_time) if event_time else None,
                entry_mode=entry_mode,
            )
            if idx is None or entry_date is None:
                n_no_bar_match += 1
                holding_records.append(
                    {
                        "date": None,
                        "code": code,
                        "sign": None,
                        "disc_date": disc,
                        "disc_time": disc_time,
                        "surprise": surprise,
                        "entry_meta": entry_meta,
                        "skip": "no_eligible_entry_bar",
                    }
                )
                continue
            if entry_date == disc:
                n_same_day_entry += 1
            else:
                n_next_session_entry += 1
            rec = compute_event_post_signal(
                surprise=surprise,
                is_event_day=True,
                is_trading_day=1.0,
                post_hold_days=h,
                code=code,
                date=entry_date,
                disc_date=disc,
                as_of=entry_meta.get("available_at"),
                extra_meta={
                    "surprise_meta": s_meta,
                    "entry_meta": entry_meta,
                },
            )
            val = rec.get("value")
            holding_records.append(
                {
                    "date": entry_date,
                    "code": code,
                    "sign": val,
                    "disc_date": disc,
                    "disc_time": disc_time,
                    "surprise": surprise,
                    "entry_meta": entry_meta,
                    "available_at": entry_meta.get("available_at"),
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
    trade_stats = trade_stats_report(
        signed_returns,
        hold_days=h,
        one_way_cost=float(one_way_cost),
        amortize_cost=True,
        trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
    )
    n_codes = len(bars_by_code)
    all_bar_dates: set[str] = set()
    for pairs in bars_by_code.values():
        for d, _ in pairs:
            all_bar_dates.add(str(d)[:10])
    if period_start:
        all_bar_dates = {d for d in all_bar_dates if d >= str(period_start)[:10]}
    if period_end:
        all_bar_dates = {d for d in all_bar_dates if d <= str(period_end)[:10]}
    n_trading_days = len(all_bar_dates)
    n_code_days = n_trading_days * n_codes if n_trading_days and n_codes else 0
    occ = occurrence_rate_event_post(
        n_events=n_events,
        n_scored=n_scored,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        n_code_days=n_code_days,
        trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
        min_events_per_code_year=MIN_EVENTS_PER_CODE_YEAR,
        min_events_per_trading_day=MIN_EVENTS_PER_TRADING_DAY,
    )
    return {
        "signal_id": SIGNAL_ID_EVENT_POST,
        "hypothesis_class": CLASS_EVENT_POST,
        "post_hold_days": h,
        "entry_mode": str(entry_mode),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_scored,
        "n_signed_returns": len(signed_returns),
        "n_events": n_events,
        "n_no_surprise": n_no_surprise,
        "n_no_bar_match": n_no_bar_match,
        "n_same_day_entry": n_same_day_entry,
        "n_next_session_entry": n_next_session_entry,
        "n_codes": n_codes,
        "n_trading_days": n_trading_days,
        "n_code_days": n_code_days,
        "occurrence": occ,
        "trade_stats": trade_stats,
        "holding_records": holding_records,
        "non_null": n_scored,
        "non_null_rate": (
            float(n_scored) / float(n_events) if n_events else None
        ),
        **_freeze(),
        "note": (
            f"Event-post hold={h}d PIT entry (mode={entry_mode}) on fins "
            "DiscDate+DiscTime surprise proxy (+ fins_earnings_date thicken "
            "when merged; no invent surprise). Entry = first session close "
            "not looking ahead of availability. Occurrence = rate not count. "
            "trade_stats = t/Sharpe/winrate on hold nets. Gaps → skip. "
            "Not READY / not Mass."
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
    short_confirm_mode: str | None = None,
) -> dict[str, Any]:
    """Evaluate flow_demand: multi-day sticky hold of margin change sign.

    Distinct from rejected S4 (daily sign flip). Rebalance on margin
    observation updates; hold sticky for ``hold_days`` sessions.

    ``short_confirm_mode`` (W85):
    * ``off`` — margin only (default when require_short_confirm=False)
    * ``hard`` — same-sign short required; missing short → no entry
    * ``soft`` — same-sign when short present; margin-only on short gap
      (cheap near-miss improve for occurrence without look-ahead)
    """
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    # Resolve confirm mode (backward-compat with require_short_confirm bool).
    mode_raw = short_confirm_mode
    if mode_raw is None:
        mode_s = "hard" if require_short_confirm else "off"
    else:
        mode_s = str(mode_raw).strip().lower()
        if mode_s in {"true", "1", "yes", "on", "require"}:
            mode_s = "hard"
        elif mode_s in {"false", "0", "no", "none", "off"}:
            mode_s = "off"
        elif mode_s not in {"off", "hard", "soft"}:
            raise ValueError(
                f"short_confirm_mode must be off|hard|soft, got {mode_raw!r}"
            )
    require_hard = mode_s == "hard"
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
                    require_short_confirm=require_hard,
                    short_confirm_mode=mode_s,
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
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    n_codes = len(bars_by_code)
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": SIGNAL_ID_FLOW_DEMAND,
        "hypothesis_class": CLASS_FLOW_DEMAND,
        "hold_days": h,
        "require_short_confirm": bool(require_hard),
        "short_confirm_mode": mode_s,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_margin_obs": n_margin_obs,
        "n_codes": n_codes,
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        "n_codes_with_margin": sum(
            1 for c in bars_by_code if len(margin_by_code.get(c) or []) >= 2
        ),
        "holding_records": holding_records,
        "non_null": n_active,
        **_freeze(),
        "note": (
            f"Flow demand multi-day hold={h} from margin change "
            f"(short_confirm_mode={mode_s}). Not S4 daily. "
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
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    n_codes = len(bars_by_code)
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        hold_days=h,
        # value×momentum agree is sparse by design; floor lower than sticky mom
        min_activation_rate=min(MIN_ACTIVATION_RATE_MULTIDAY, 0.01),
    )
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
        "n_codes": n_codes,
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
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
    include_cross_section_hold_10: bool = True,
    # W85: promote explore xs hold=10 mom=3 after multi-window paper align.
    include_cross_section_hold_10_mom3: bool = True,
    include_event_post: bool = True,
    include_flow_demand: bool = True,
    include_fundamentals_price: bool = True,
    include_fundamentals_hold_10: bool = True,
    include_multi_day_hold_10: bool = True,
    cross_section_hold_days: int = 5,
    cross_section_momentum_n: int | None = None,
    # Sticky hold=10 uses short mom lookback (W82 pin). Content-matched
    # mom=10 collapses residual (W83 explore) — do not "align" blindly.
    cross_section_hold10_momentum_n: int = 5,
    # W85 promoted: sticky hold=10 with mom=3 (research standout + multi-window paper).
    cross_section_hold10_mom3_momentum_n: int = 3,
    cross_section_long_frac: float = 0.3,
    cross_section_short_frac: float = 0.3,
    event_hold_days: int = DEFAULT_EVENT_POST_HOLD_DAYS,
    flow_hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    flow_require_short_confirm: bool = False,
    flow_short_confirm_mode: str | None = None,  # off|hard|soft (W85)
    # W85: apply short = f(repo[t]+spread) remeasure on L-S classes (default on).
    apply_short_cost_remeasure: bool = True,
    short_borrow_sensitivity: str = "mid",
    short_fraction_ls: float = 0.5,
    fund_hold_days: int = DEFAULT_FUND_HOLD_DAYS,
    fund_momentum_n: int = DEFAULT_FUND_MOMENTUM_N,
    # W83 candidate: hold=10 mom=10 value×momentum agree (separate block).
    fund_hold10_momentum_n: int = 10,
    fund_mode: str = "value_momentum_agree",
    max_days: int | None = None,
    min_periods_gate: int = 2,
    min_active_per_period: int = 20,
    min_economic_net: float = MIN_ECONOMIC_NET,
    min_activation_rate_multiday: float = MIN_ACTIVATION_RATE_MULTIDAY,
    min_events_per_code_year: float = MIN_EVENTS_PER_CODE_YEAR,
    min_events_per_trading_day: float = MIN_EVENTS_PER_TRADING_DAY,
    min_years_research_candidate: int = MIN_YEARS_RESEARCH_CANDIDATE,
    max_year_pos_net_share: float = MAX_YEAR_POS_NET_SHARE,
    min_abs_t_stat: float = MIN_ABS_T_STAT,
    min_sharpe_period: float = MIN_SHARPE_PERIOD,
    min_period_win_rate: float = MIN_PERIOD_WIN_RATE,
    min_positive_periods: int = MIN_POSITIVE_PERIODS,
    require_stats_bar: bool = True,
    apply_robustness_gate: bool = True,
    prefer_liquidity_linked: bool = True,
    thicken_event_with_earnings_date: bool = True,
    checklist_complete: bool = True,
) -> dict[str, Any]:
    """Multi-year offline eval for all enabled class hyps (W81–W83).

    Uses local W63 Q4 + W64 full bar/margin mirrors and local SQLite
    (jsda_repo_rates, fins_summary, fins_earnings_date, short_ratio).

    Production ``research_candidate=True`` only when gate + economic net +
    occurrence rate + multi-year skew + risk + **statistical bar**
    (|t|, Sharpe, period win-rate) all pass (still not READY/Mass).
    No mean-bp-only promotion. event_post uses W82 PIT entry only.

    W83: default path always includes sticky cross_section hold=10 as a
    separate block when ``include_cross_section_hold_10`` (parallel to
    multi_day_hold_10). Primary ``cross_section_hold_days`` default remains 5.
    """
    period_list = [dict(p) for p in (periods or DEFAULT_PERIODS)]
    selected = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else select_eval_universe(max_codes=len(DEFAULT_EVAL_CODES))
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
    fins_summary_events = (
        load_fins_events_from_sqlite(
            sqlite_path,
            codes=selected,
            start=fins_global_start,
            end=fins_global_end,
        )
        if (include_event_post or include_fundamentals_price)
        else {}
    )
    earn_date_events: dict[str, list[dict[str, Any]]] = {}
    if thicken_event_with_earnings_date and (
        include_event_post or include_fundamentals_price
    ):
        earn_date_events = load_fins_earnings_date_from_sqlite(
            sqlite_path,
            codes=selected,
            start=fins_global_start,
            end=fins_global_end,
        )
    if thicken_event_with_earnings_date and earn_date_events:
        fins_events = merge_event_calendars(fins_summary_events, earn_date_events)
        event_source = "fins_summary+fins_earnings_date"
    else:
        fins_events = fins_summary_events
        event_source = "fins_summary"
    fins_load_note = {
        "source": "local_sqlite_jquants_records_" + event_source.replace("+", "_"),
        "path": str(sqlite_path),
        "n_codes": len(fins_events),
        "n_events": sum(len(v) for v in fins_events.values()),
        "n_events_fins_summary": sum(len(v) for v in fins_summary_events.values()),
        "n_events_fins_earnings_date": sum(
            len(v) for v in earn_date_events.values()
        ),
        "thickened_with_earnings_date": bool(
            thicken_event_with_earnings_date and earn_date_events
        ),
        "event_source": event_source,
        "pit_disclosure": (
            "fins_summary SoT: DiscDate + DiscTime (aliases DisclosedDate/"
            "DisclosedTime); envelope event_time/available_at when present. "
            "W82 entry = first session close not looking ahead of availability "
            "(after-close or missing DiscTime → next trading bar; no invent "
            "timestamps). fins_earnings_date thickens calendar via PubDate|"
            "SchDate when available; surprise still requires fins_summary "
            "EPS/FEPS (no invent). Disclosed."
        ),
        "entry_mode": EVENT_POST_ENTRY_MODE,
        "dataset": event_source,
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
    results_xs10: list[dict[str, Any]] = []
    results_xs10_mom3: list[dict[str, Any]] = []
    results_event: list[dict[str, Any]] = []
    results_flow: list[dict[str, Any]] = []
    results_fund: list[dict[str, Any]] = []
    results_fund10: list[dict[str, Any]] = []
    xs_mom_n = (
        int(cross_section_momentum_n)
        if cross_section_momentum_n is not None
        else int(cross_section_hold_days)
    )
    xs10_mom_n = int(cross_section_hold10_momentum_n)
    xs10_mom3_n = int(cross_section_hold10_mom3_momentum_n)
    xs_long_frac = float(cross_section_long_frac)
    xs_short_frac = float(cross_section_short_frac)
    fund_mom_n = int(fund_momentum_n)
    fund10_mom_n = int(fund_hold10_momentum_n)
    fund_mode_s = str(fund_mode or "value_momentum_agree")
    flow_short_confirm = bool(flow_require_short_confirm)

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
            if include_cross_section_hold_10:
                results_xs10.append(dict(skip))
            if include_cross_section_hold_10_mom3:
                results_xs10_mom3.append(dict(skip))
            if include_event_post:
                results_event.append(dict(skip))
            if include_flow_demand:
                results_flow.append(dict(skip))
            if include_fundamentals_price:
                results_fund.append(dict(skip))
            if include_fundamentals_hold_10:
                results_fund10.append(dict(skip))
            if include_multi_day_hold_10:
                results_md10.append(dict(skip))
            continue

        try:
            # Full-year windows need more than 80 days; Q4 can stay capped.
            window_kind = str(p.get("window_kind") or "")
            if max_days is not None:
                period_max_days = int(max_days)
            elif "full" in str(pid).lower() or window_kind.startswith("full"):
                period_max_days = 260
            else:
                period_max_days = 80

            rich = load_bars_ndjson_rich(
                bars_path,
                codes=selected,
                max_days=period_max_days,
                period_start=p_start,
                period_end=p_end,
            )
            bars = bars_rich_to_close_panel(rich)
            if not bars:
                raise RuntimeError("no bars after code filter")

            # Liquidity-linked one-way cost (prefer when ADV available)
            liq_rows = collect_liquidity_bar_rows(rich)
            liq_proxy = compute_liquidity_proxy_from_bars(
                liq_rows, source_label=f"bars:{pid}"
            )
            liq_bucket = liquidity_bucket_from_proxy(liq_proxy)
            liq_mults = liquidity_cost_multipliers(
                str(liq_bucket.get("bucket") or "missing")
            )
            tx_mult = (
                float(liq_mults.get("tx_mult") or 1.0)
                if prefer_liquidity_linked
                else 1.0
            )
            if not prefer_liquidity_linked:
                tx_mult = 1.0
            # missing bucket → mult 1.0 unmodulated (no invent)
            if liq_bucket.get("is_gap") or str(liq_bucket.get("bucket")) == "missing":
                if prefer_liquidity_linked:
                    tx_mult = float(liq_mults.get("tx_mult") or 1.0)
            one_way_eff = apply_liquidity_to_one_way_cost(
                one_way_cost, tx_mult=tx_mult
            )
            liq_extra = {
                "liquidity_bucket": liq_bucket.get("bucket"),
                "liquidity_adv_jpy": liq_proxy.get("adv_jpy"),
                "liquidity_tx_mult": tx_mult,
                "one_way_cost_base": float(one_way_cost),
                "one_way_cost_eff": float(one_way_eff),
                "prefer_liquidity_linked": bool(prefer_liquidity_linked),
                "liquidity_is_gap": bool(liq_bucket.get("is_gap")),
            }

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
                    "window_kind": window_kind or None,
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
                    "n_trading_days": eval_out.get("n_trading_days"),
                    "n_code_days": eval_out.get("n_code_days"),
                    "occurrence": eval_out.get("occurrence"),
                    "trade_stats": eval_out.get("trade_stats"),
                    "signal_id": signal_id,
                    "holding_records": eval_out.get("holding_records"),
                    **liq_extra,
                }
                if extra:
                    row.update(dict(extra))
                return row

            md = evaluate_multi_day_hold_on_bars(
                bars, hold_days=h, one_way_cost=one_way_eff
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
                    bars, hold_days=10, one_way_cost=one_way_eff
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
                one_way_cost=one_way_eff,
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
                    momentum_n=xs_mom_n,
                    one_way_cost=one_way_eff,
                    hold_days=int(cross_section_hold_days),
                    long_frac=xs_long_frac,
                    short_frac=xs_short_frac,
                )
                results_xs.append(
                    _period_row(
                        xs,
                        signal_id=SIGNAL_ID_CROSS_SECTION,
                        extra={
                            "hold_days": int(cross_section_hold_days),
                            "momentum_n": xs_mom_n,
                            "long_frac": xs_long_frac,
                            "short_frac": xs_short_frac,
                            "amortized_one_way_cost": xs.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
                )

            if include_cross_section_hold_10 and int(cross_section_hold_days) != 10:
                # W83 default path: sticky hold=10 with W82-pin mom lookback
                # (mom=5). Content-matched mom=10 fails multi-year residual.
                xs10 = evaluate_cross_section_on_bars(
                    bars,
                    momentum_n=xs10_mom_n,
                    one_way_cost=one_way_eff,
                    hold_days=10,
                    long_frac=xs_long_frac,
                    short_frac=xs_short_frac,
                )
                results_xs10.append(
                    _period_row(
                        xs10,
                        signal_id=SIGNAL_ID_CROSS_SECTION,
                        extra={
                            "hold_days": 10,
                            "momentum_n": xs10_mom_n,
                            "variant": "hold_10",
                            "long_frac": xs_long_frac,
                            "short_frac": xs_short_frac,
                            "amortized_one_way_cost": xs10.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
                )

            if include_cross_section_hold_10_mom3 and not (
                include_cross_section_hold_10 and int(xs10_mom_n) == int(xs10_mom3_n)
            ):
                # W85 promote_default: sticky hold=10 mom=3 (research standout
                # t≈3.0 + multi-window paper majority positive). Parallel to
                # mom=5 pin — does not replace W82 pin block.
                xs10m3 = evaluate_cross_section_on_bars(
                    bars,
                    momentum_n=xs10_mom3_n,
                    one_way_cost=one_way_eff,
                    hold_days=10,
                    long_frac=xs_long_frac,
                    short_frac=xs_short_frac,
                )
                results_xs10_mom3.append(
                    _period_row(
                        xs10m3,
                        signal_id=SIGNAL_ID_CROSS_SECTION,
                        extra={
                            "hold_days": 10,
                            "momentum_n": xs10_mom3_n,
                            "variant": "hold_10_mom3",
                            "long_frac": xs_long_frac,
                            "short_frac": xs_short_frac,
                            "amortized_one_way_cost": xs10m3.get(
                                "amortized_one_way_cost"
                            ),
                            "promoted_wave": "W85 / w0816t",
                        },
                    )
                )

            if include_event_post:
                ep = evaluate_event_post_on_bars(
                    bars,
                    fins_events,
                    post_hold_days=int(event_hold_days),
                    one_way_cost=one_way_eff,
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
                            "n_no_bar_match": ep.get("n_no_bar_match"),
                            "n_same_day_entry": ep.get("n_same_day_entry"),
                            "n_next_session_entry": ep.get(
                                "n_next_session_entry"
                            ),
                            "entry_mode": ep.get("entry_mode"),
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
                    one_way_cost=one_way_eff,
                    require_short_confirm=flow_short_confirm,
                    short_confirm_mode=flow_short_confirm_mode,
                )
                results_flow.append(
                    _period_row(
                        flow,
                        signal_id=SIGNAL_ID_FLOW_DEMAND,
                        extra={
                            "hold_days": int(flow_hold_days),
                            "require_short_confirm": bool(
                                flow.get("require_short_confirm")
                            ),
                            "short_confirm_mode": flow.get(
                                "short_confirm_mode"
                            ),
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
                    momentum_n=fund_mom_n,
                    one_way_cost=one_way_eff,
                    mode=fund_mode_s,
                )
                results_fund.append(
                    _period_row(
                        fund,
                        signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
                        extra={
                            "hold_days": int(fund_hold_days),
                            "momentum_n": fund_mom_n,
                            "mode": fund_mode_s,
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

            if include_fundamentals_hold_10 and (
                int(fund_hold_days) != 10 or int(fund_mom_n) != int(fund10_mom_n)
            ):
                # W83: fund hold=10 mom=10 on default path (candidate in explore).
                fund10 = evaluate_fundamentals_price_on_bars(
                    bars,
                    fins_events,
                    hold_days=10,
                    momentum_n=fund10_mom_n,
                    one_way_cost=one_way_eff,
                    mode=fund_mode_s,
                )
                results_fund10.append(
                    _period_row(
                        fund10,
                        signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
                        extra={
                            "hold_days": 10,
                            "momentum_n": fund10_mom_n,
                            "mode": fund_mode_s,
                            "variant": "hold_10_mom_matched",
                            "n_missing_fins_days": fund10.get(
                                "n_missing_fins_days"
                            ),
                            "value_benchmark_median": fund10.get(
                                "value_benchmark_median"
                            ),
                            "amortized_one_way_cost": fund10.get(
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
            if include_cross_section_hold_10:
                results_xs10.append(dict(err))
            if include_cross_section_hold_10_mom3:
                results_xs10_mom3.append(dict(err))
            if include_event_post:
                results_event.append(dict(err))
            if include_flow_demand:
                results_flow.append(dict(err))
            if include_fundamentals_price:
                results_fund.append(dict(err))
            if include_fundamentals_hold_10:
                results_fund10.append(dict(err))
            if include_multi_day_hold_10:
                results_md10.append(dict(err))

    # ------------------------------------------------------------------
    # W85: short cost remeasure on L-S classes
    # short = f(repo[t] + fixed spread bp); low/mid/high sensitivity
    # Primary (default mid) overwrites net_one_way_mean_active for gates/stats.
    # ------------------------------------------------------------------
    short_cost_remeasure_blocks: dict[str, Any] = {}
    short_frac_ls = float(short_fraction_ls)
    short_sens = str(short_borrow_sensitivity or "mid").strip().lower()
    if short_sens not in SHORT_BORROW_SPREAD_SENSITIVITY:
        short_sens = "mid"

    def _apply_short_remeasure(
        rows: list[dict[str, Any]],
        *,
        hold_days: int,
        block_key: str,
    ) -> list[dict[str, Any]]:
        if not apply_short_cost_remeasure or not rows:
            return rows
        # Per-row liquidity short_spread_mult when present (else 1.0)
        # Remeasure uses date-matched repo; no invent on gaps.
        pack = remeasure_period_rows_with_short_cost(
            rows,
            repo_rate_series=repo_series,
            short_fraction=short_frac_ls,
            hold_days=int(hold_days),
            default_sensitivity=short_sens,
            sensitivities=("low", "mid", "high"),
            apply_primary_net=True,
            fallback_mean_repo_when_date_gap=False,
        )
        short_cost_remeasure_blocks[block_key] = {
            "summary_by_sensitivity": pack.get("summary_by_sensitivity"),
            "n_short_cost_obs": pack.get("n_short_cost_obs"),
            "n_repo_gaps": pack.get("n_repo_gaps"),
            "default_sensitivity": pack.get("default_sensitivity"),
            "short_fraction": pack.get("short_fraction"),
            "formula": pack.get("formula"),
            "assumptions": pack.get("assumptions"),
            "mean_repo": pack.get("mean_repo"),
        }
        return list(pack.get("period_rows") or rows)

    if apply_short_cost_remeasure:
        results_macro = _apply_short_remeasure(
            results_macro, hold_days=h, block_key="macro_conditioned"
        )
        if include_cross_section:
            results_xs = _apply_short_remeasure(
                results_xs,
                hold_days=int(cross_section_hold_days),
                block_key="cross_section_relative",
            )
        if include_cross_section_hold_10 and results_xs10:
            results_xs10 = _apply_short_remeasure(
                results_xs10,
                hold_days=10,
                block_key="cross_section_hold_10",
            )
        if include_cross_section_hold_10_mom3 and results_xs10_mom3:
            results_xs10_mom3 = _apply_short_remeasure(
                results_xs10_mom3,
                hold_days=10,
                block_key="cross_section_hold_10_mom3",
            )
        if include_fundamentals_price:
            results_fund = _apply_short_remeasure(
                results_fund,
                hold_days=int(fund_hold_days),
                block_key="fundamentals_price",
            )
        if include_fundamentals_hold_10 and results_fund10:
            results_fund10 = _apply_short_remeasure(
                results_fund10,
                hold_days=10,
                block_key="fundamentals_hold_10",
            )

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
    gate_xs10 = (
        _gate(results_xs10, SIGNAL_ID_CROSS_SECTION + "_hold10")
        if include_cross_section_hold_10 and results_xs10
        else None
    )
    gate_xs10_mom3 = (
        _gate(results_xs10_mom3, SIGNAL_ID_CROSS_SECTION + "_hold10_mom3")
        if include_cross_section_hold_10_mom3 and results_xs10_mom3
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
    gate_fund10 = (
        _gate(results_fund10, SIGNAL_ID_FUNDAMENTALS_PRICE + "_hold10")
        if include_fundamentals_hold_10 and results_fund10
        else None
    )

    cost_md = default_long_only_unlevered_cost_assumption(
        one_way_cost=one_way_cost
    )
    cost_md["prefer_liquidity_linked"] = bool(prefer_liquidity_linked)
    cost_md["liquidity_note"] = (
        "Per-period one_way_eff = one_way_base * tx_mult[bucket] from "
        "equities_bars ADV. Missing ADV → mult=1.0 gap disclosed (no invent)."
    )
    cost_macro = build_leverage_short_cost_assumption(
        position_style="long_short",
        gross_leverage=1.0,
        short_fraction=short_frac_ls,
        one_way_cost=one_way_cost,
        uses_short=True,
        uses_leverage=False,
        repo_rate_series=repo_series,
        prefer_repo_linked=True,
        short_borrow_sensitivity=short_sens,
    )
    cost_ls = build_leverage_short_cost_assumption(
        position_style="long_short",
        gross_leverage=1.0,
        short_fraction=short_frac_ls,
        one_way_cost=one_way_cost,
        uses_short=True,
        uses_leverage=False,
        repo_rate_series=repo_series,
        prefer_repo_linked=True,
        short_borrow_sensitivity=short_sens,
    )
    cost_ls["short_cost_remeasure"] = {
        "applied": bool(apply_short_cost_remeasure),
        "default_sensitivity": short_sens,
        "sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
        "formula": (
            "net = gross - amortized_one_way - "
            "short_borrow_daily(repo[t]+spread)*hold_days"
        ),
        "blocks": short_cost_remeasure_blocks,
        "proof": "docs/proof/w0816t_w85_short_cost_repo_spread_20260817.md",
    }
    cost_macro["short_cost_remeasure"] = dict(cost_ls["short_cost_remeasure"])
    if repo_series is not None:
        mean_repo = mean_repo_rate_pct(repo_series)
        cost_macro["repo_linked"] = {
            "preferred": True,
            "dataset": REPO_DATASET_ID,
            "mean_rate_pct": mean_repo.get("mean_rate_pct"),
            "mean_annual_bp": mean_repo.get("mean_annual_bp"),
            "n_obs": mean_repo.get("n_obs"),
            "note": (
                "W85: date-matched repo[t]+spread applied to L-S period nets; "
                "mean disclosed for summary. Gaps never invent-filled."
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
    risk_xs10 = (
        _risk(results_xs10, SIGNAL_ID_CROSS_SECTION)
        if include_cross_section_hold_10 and results_xs10
        else None
    )
    risk_xs10_mom3 = (
        _risk(results_xs10_mom3, SIGNAL_ID_CROSS_SECTION)
        if include_cross_section_hold_10_mom3 and results_xs10_mom3
        else None
    )
    risk_event = _risk(results_event, SIGNAL_ID_EVENT_POST) if include_event_post else None
    risk_flow = _risk(results_flow, SIGNAL_ID_FLOW_DEMAND) if include_flow_demand else None
    risk_fund = (
        _risk(results_fund, SIGNAL_ID_FUNDAMENTALS_PRICE)
        if include_fundamentals_price
        else None
    )
    risk_fund10 = (
        _risk(results_fund10, SIGNAL_ID_FUNDAMENTALS_PRICE)
        if include_fundamentals_hold_10 and results_fund10
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

    def _aggregate_occurrence_multiday(
        rows: list[dict[str, Any]], *, hold_days: int
    ) -> dict[str, Any]:
        ok = [r for r in rows if r.get("status") == "ok"]
        n_active = sum(int(r.get("n_active_positions") or 0) for r in ok)
        n_cd = sum(int(r.get("n_code_days") or 0) for r in ok)
        n_td = sum(int(r.get("n_trading_days") or 0) for r in ok)
        n_codes = 0
        for r in ok:
            n_codes = max(n_codes, int(r.get("n_codes") or 0))
        occ = occurrence_rate_multiday(
            n_active=n_active,
            n_code_days=n_cd,
            n_trading_days=n_td,
            n_codes=n_codes,
            hold_days=hold_days,
            min_activation_rate=float(min_activation_rate_multiday),
        )
        occ["per_period"] = [
            {
                "period_id": r.get("period_id"),
                "occurrence": r.get("occurrence"),
                "n_active": r.get("n_active_positions"),
                "n_code_days": r.get("n_code_days"),
                "n_trading_days": r.get("n_trading_days"),
            }
            for r in ok
        ]
        return occ

    def _aggregate_occurrence_event(
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ok = [r for r in rows if r.get("status") == "ok"]
        n_events = sum(int(r.get("n_events") or 0) for r in ok)
        n_scored = sum(int(r.get("n_active_positions") or 0) for r in ok)
        n_td = sum(int(r.get("n_trading_days") or 0) for r in ok)
        n_cd = sum(int(r.get("n_code_days") or 0) for r in ok)
        n_codes = 0
        for r in ok:
            n_codes = max(n_codes, int(r.get("n_codes") or 0))
        occ = occurrence_rate_event_post(
            n_events=n_events,
            n_scored=n_scored,
            n_trading_days=n_td,
            n_codes=n_codes,
            n_code_days=n_cd,
            trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
            min_events_per_code_year=float(min_events_per_code_year),
            min_events_per_trading_day=float(min_events_per_trading_day),
        )
        occ["per_period"] = [
            {
                "period_id": r.get("period_id"),
                "occurrence": r.get("occurrence"),
                "n_events": r.get("n_events"),
                "n_scored": r.get("n_active_positions"),
                "n_trading_days": r.get("n_trading_days"),
            }
            for r in ok
        ]
        return occ

    def _skew_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
        nets: dict[str, float | None] = {}
        for r in rows:
            if r.get("status") != "ok":
                continue
            pid_r = str(r.get("period_id") or r.get("year") or "p")
            nets[pid_r] = r.get("net_one_way_mean_active")
        return multi_year_skew_check(
            nets, max_pos_share=float(max_year_pos_net_share)
        )

    def _stats_from_rows(
        rows: list[dict[str, Any]],
        *,
        hold_days: int | None = None,
    ) -> dict[str, Any]:
        """Period-net statistical pack + W81 stats bar check."""
        ok_rows = [
            r
            for r in rows
            if r.get("status") == "ok"
            and r.get("net_one_way_mean_active") is not None
        ]
        nets = [float(r["net_one_way_mean_active"]) for r in ok_rows]
        pids = [str(r.get("period_id") or r.get("year") or "p") for r in ok_rows]
        stats = period_stats_report(
            nets, period_ids=pids, hold_days=hold_days
        )
        # Attach per-period trade_stats summaries when present (no raw trades).
        trade_rows = []
        for r in ok_rows:
            ts = r.get("trade_stats")
            if isinstance(ts, Mapping):
                trade_rows.append(
                    {
                        "period_id": r.get("period_id"),
                        "n_trades": ts.get("n_trades"),
                        "mean_net": ts.get("mean_net"),
                        "t_stat": ts.get("t_stat"),
                        "sharpe_ann": ts.get("sharpe_ann"),
                        "win_rate": ts.get("win_rate"),
                        "payoff": ts.get("payoff"),
                        "max_dd": ts.get("max_dd"),
                    }
                )
        if trade_rows:
            stats["per_period_trade_stats"] = trade_rows
        bar = stats_bar_check(
            stats,
            min_abs_t=float(min_abs_t_stat),
            min_sharpe=float(min_sharpe_period),
            min_win_rate=float(min_period_win_rate),
            min_positive_periods=int(min_positive_periods),
        )
        return {"stats": stats, "stats_bar": bar}

    def _candidate_verdict(
        gate: dict[str, Any] | None,
        risk: dict[str, Any] | None,
        rows: list[dict[str, Any]],
        *,
        n_ok: int,
        occurrence: Mapping[str, Any] | None = None,
        hyp_kind: str = "generic",
        hold_days_for_occ: int = 5,
    ) -> dict[str, Any]:
        """W81 production bar: gate + risk + econ + occurrence + skew + stats.

        Weak consistent-negative → not_candidate even if gate passes.
        Noisy low t/Sharpe / unstable yearly signs → demote discussion_only.
        research_candidate=True only when all production criteria pass
        (still not READY / Mass / operational GO).
        """
        gate_pass = bool(gate and gate.get("passed"))
        risk_ok = bool(risk and risk.get("research_candidate_allowed"))
        econ = _econ_from_rows(rows)
        econ_ok = bool(econ.get("meaningful"))
        if occurrence is None:
            if hyp_kind == "event_post":
                occurrence = _aggregate_occurrence_event(rows)
            elif hyp_kind in {"multi_day_hold", "multi_day_hold_10"}:
                occurrence = _aggregate_occurrence_multiday(
                    rows, hold_days=hold_days_for_occ
                )
            else:
                # generic: treat n_active/code_days if present
                occurrence = _aggregate_occurrence_multiday(
                    rows, hold_days=hold_days_for_occ
                )
        occ_ok = bool((occurrence or {}).get("sufficient"))
        skew = _skew_from_rows(rows)
        skew_ok = bool(skew.get("ok"))
        multi_year_ok = bool(n_ok >= int(min_years_research_candidate))
        stats_pack = _stats_from_rows(rows, hold_days=hold_days_for_occ)
        stats = stats_pack["stats"]
        sbar = stats_pack["stats_bar"]
        stats_ok = bool(sbar.get("stats_ok"))

        bar = production_candidate_bar(
            checklist_complete=bool(checklist_complete),
            gate_passed=gate_pass,
            risk_ok=risk_ok,
            economic_net_ok=econ_ok,
            occurrence_ok=occ_ok,
            multi_year_ok=multi_year_ok,
            skew_ok=skew_ok,
            n_ok_periods=n_ok,
            min_years=int(min_years_research_candidate),
            economic_net=econ,
            occurrence=occurrence,
            skew=skew,
            stats_ok=stats_ok,
            stats=stats,
            stats_bar=sbar,
            require_stats=bool(require_stats_bar),
        )
        return {
            "research_candidate": bool(bar.get("research_candidate")),
            "research_candidate_allowed": bool(
                bar.get("research_candidate_allowed")
            ),
            "candidate_yes_no": bar.get("candidate_yes_no"),
            "gate_passed": gate_pass,
            "risk_scenarios_ok": risk_ok,
            "economic_net": econ,
            "economic_net_ok": econ_ok,
            "occurrence": dict(occurrence or {}),
            "occurrence_ok": occ_ok,
            "skew": skew,
            "skew_ok": skew_ok,
            "stats": stats,
            "stats_bar": sbar,
            "stats_ok": stats_ok,
            "production_criteria": bar.get("production_criteria"),
            "n_ok_periods": n_ok,
            "verdict": bar.get("verdict"),
            "ready_declared": False,
            "mass_research": MASS_RESEARCH,
            "phase7": PHASE7,
            "operational_go": False,
            "connected_to_ready": False,
            "connected_to_mass": False,
            "min_economic_net": float(min_economic_net),
            "min_years_research_candidate": int(min_years_research_candidate),
            "min_abs_t_stat": float(min_abs_t_stat),
            "min_sharpe_period": float(min_sharpe_period),
            "min_period_win_rate": float(min_period_win_rate),
            "min_positive_periods": int(min_positive_periods),
            "note": bar.get("note"),
        }

    def _n_ok(rows: list[dict[str, Any]]) -> int:
        return sum(1 for r in rows if r.get("status") == "ok")

    n_ok_md = _n_ok(results_md)
    n_ok_macro = _n_ok(results_macro)
    n_ok_xs = _n_ok(results_xs)
    n_ok_xs10 = _n_ok(results_xs10)
    n_ok_xs10_mom3 = _n_ok(results_xs10_mom3)
    n_ok_event = _n_ok(results_event)
    n_ok_flow = _n_ok(results_flow)
    n_ok_fund = _n_ok(results_fund)
    n_ok_fund10 = _n_ok(results_fund10)
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
        hyp_kind: str = "generic",
        hold_days_for_occ: int = 5,
    ) -> dict[str, Any]:
        n_ok = _n_ok(rows)
        cand = _candidate_verdict(
            gate,
            risk,
            rows,
            n_ok=n_ok,
            hyp_kind=hyp_kind,
            hold_days_for_occ=hold_days_for_occ,
        )
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
            "candidate": cand,
            "occurrence": cand.get("occurrence"),
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
        "prefer_liquidity_linked": bool(prefer_liquidity_linked),
        "apply_short_cost_remeasure": bool(apply_short_cost_remeasure),
        "short_borrow_sensitivity": short_sens,
        "short_fraction_ls": short_frac_ls,
        "short_cost_sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
        "short_cost_remeasure": short_cost_remeasure_blocks,
        "min_economic_net": float(min_economic_net),
        "min_activation_rate_multiday": float(min_activation_rate_multiday),
        "min_events_per_code_year": float(min_events_per_code_year),
        "min_events_per_trading_day": float(min_events_per_trading_day),
        "min_years_research_candidate": int(min_years_research_candidate),
        "max_year_pos_net_share": float(max_year_pos_net_share),
        "min_abs_t_stat": float(min_abs_t_stat),
        "min_sharpe_period": float(min_sharpe_period),
        "min_period_win_rate": float(min_period_win_rate),
        "min_positive_periods": int(min_positive_periods),
        "require_stats_bar": bool(require_stats_bar),
        "stats_metrics": stats_metrics_document(),
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
            hyp_kind="multi_day_hold",
            hold_days_for_occ=h,
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
            hyp_kind="generic",
            hold_days_for_occ=h,
        ),
        "n_years_requested": len(period_list),
        "n_years_ok_multi_day_hold": n_ok_md,
        "n_years_ok_macro_conditioned": n_ok_macro,
        "history_source": (
            "local_r2_mirror_ndjson (W63 q4 + W64 full) + local_sqlite "
            "(jsda_repo_rates · fins_summary · fins_earnings_date · "
            "margin · short_ratio)"
        ),
        "label": "研究用・複数年クラス仮説評価・W81統計バー再判定・未宣言",
        **_freeze(),
        "note": (
            "W85 class hyp multi-year offline eval with occurrence rates + "
            "liquidity-linked costs + short=repo[t]+spread (L/M/H) remeasure "
            "on CS L-S / fund L-S / macro + extended full-year windows + "
            "statistical bar (|t|≥1.5, Sharpe≥0.5, period win-rate≥0.6, "
            "≥4 positive periods). No mean-bp-only promotion. "
            "Default path includes sticky cross_section hold=10 (mom=5 pin), "
            "W85-promoted hold=10 mom=3, and fundamentals hold=10 mom=10. "
            "event_post uses W82 PIT DiscDate+DiscTime entry only. "
            "research_candidate=True only if checklist v2 + gate + risk + "
            "economic net meaningful + occurrence rate sufficient + "
            "multi-year (≥min_years) without extreme skew + stats bar. "
            "Weak consistent-negative → not_candidate. "
            "Noisy low t/Sharpe / unstable yearly signs → demote. "
            "READY/Mass/operational GO never auto-connect. "
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
            hyp_kind="multi_day_hold_10",
            hold_days_for_occ=10,
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
            hyp_kind="generic",
            hold_days_for_occ=int(cross_section_hold_days),
            extra={
                "hold_days": int(cross_section_hold_days),
                "momentum_n": xs_mom_n,
                "long_frac": xs_long_frac,
                "short_frac": xs_short_frac,
            },
        )
    if include_cross_section_hold_10 and results_xs10:
        out["cross_section_hold_10"] = _class_block(
            signal_id=SIGNAL_ID_CROSS_SECTION,
            hyp_class="cross_section_relative",
            rows=results_xs10,
            gate=gate_xs10,
            risk=risk_xs10,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=10,
            extra={
                "hold_days": 10,
                "momentum_n": xs10_mom_n,
                "variant": "hold_10",
                "long_frac": xs_long_frac,
                "short_frac": xs_short_frac,
                "n_ok": n_ok_xs10,
                "note": (
                    f"W83 default-path sticky hold=10 with momentum_n="
                    f"{xs10_mom_n} (W82 pin; mom=10 collapses). "
                    "W86 sign-selection applies both sides after cost. "
                    "Not Mass/READY."
                ),
            },
        )
    if include_cross_section_hold_10_mom3 and results_xs10_mom3:
        out["cross_section_hold_10_mom3"] = _class_block(
            signal_id=SIGNAL_ID_CROSS_SECTION,
            hyp_class="cross_section_relative",
            rows=results_xs10_mom3,
            gate=gate_xs10_mom3,
            risk=risk_xs10_mom3,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=10,
            extra={
                "hold_days": 10,
                "momentum_n": xs10_mom3_n,
                "variant": "hold_10_mom3",
                "long_frac": xs_long_frac,
                "short_frac": xs_short_frac,
                "n_ok": n_ok_xs10_mom3,
                "promoted_wave": "W85 / w0816t",
                "note": (
                    f"W85 promote_default: sticky hold=10 momentum_n="
                    f"{xs10_mom3_n}. Research hard RC (t≈3.0) + multi-window "
                    "paper majority positive. Parallel to mom=5 pin — does not "
                    "replace W82 pin. W86 sign-selection both sides. "
                    "Not Mass/READY/live."
                ),
            },
        )
    if include_event_post:
        out["event_post"] = _class_block(
            signal_id=SIGNAL_ID_EVENT_POST,
            hyp_class=CLASS_EVENT_POST,
            rows=results_event,
            gate=gate_event,
            risk=risk_event,
            cost=cost_md,
            hyp_kind="event_post",
            hold_days_for_occ=int(event_hold_days),
            extra={
                "post_hold_days": int(event_hold_days),
                "n_ok": n_ok_event,
                "entry_mode": EVENT_POST_ENTRY_MODE,
                "pit_definition": "W82 DiscDate+DiscTime first non-look-ahead close",
            },
        )
    if include_flow_demand:
        out["flow_demand"] = _class_block(
            signal_id=SIGNAL_ID_FLOW_DEMAND,
            hyp_class=CLASS_FLOW_DEMAND,
            rows=results_flow,
            gate=gate_flow,
            risk=risk_flow,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=int(flow_hold_days),
            extra={
                "hold_days": int(flow_hold_days),
                "require_short_confirm": flow_short_confirm,
                "n_ok": n_ok_flow,
            },
        )
    if include_fundamentals_price:
        out["fundamentals_price"] = _class_block(
            signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
            hyp_class=CLASS_FUNDAMENTALS_PRICE,
            rows=results_fund,
            gate=gate_fund,
            risk=risk_fund,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=int(fund_hold_days),
            extra={
                "hold_days": int(fund_hold_days),
                "momentum_n": fund_mom_n,
                "mode": fund_mode_s,
                "n_ok": n_ok_fund,
            },
        )
    if include_fundamentals_hold_10 and results_fund10:
        out["fundamentals_hold_10"] = _class_block(
            signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
            hyp_class=CLASS_FUNDAMENTALS_PRICE,
            rows=results_fund10,
            gate=gate_fund10,
            risk=risk_fund10,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=10,
            extra={
                "hold_days": 10,
                "momentum_n": fund10_mom_n,
                "mode": fund_mode_s,
                "variant": "hold_10_mom_matched",
                "n_ok": n_ok_fund10,
                "note": (
                    "W83 default-path fund hold=10 mom-matched. "
                    "W86 sign-selection applies both sides after cost "
                    "(paper-negative → flip-first). Not Mass/READY."
                ),
            },
        )

    # ------------------------------------------------------------------
    # W86 / w0816u: sign flip both-sides after cost for default/main
    # explore representatives. Record chosen_sign for reproducibility.
    # ------------------------------------------------------------------
    # paper_mean_negative flags from W85 multi-window paper honesty:
    # xs mom5 −0.49% · fund mom10 −1.77% · mom3 +0.66% (not paper-neg).
    _SIGN_FLIP_TARGETS: tuple[tuple[str, bool, int | None], ...] = (
        # key, paper_mean_negative, hold_days override
        ("cross_section_hold_10", True, 10),
        ("cross_section_hold_10_mom3", False, 10),
        ("fundamentals_hold_10", True, 10),
    )
    sign_selection_blocks: dict[str, Any] = {}
    for skey, paper_neg, hold_ov in _SIGN_FLIP_TARGETS:
        block = out.get(skey)
        if not isinstance(block, Mapping):
            continue
        rows_ss = list(block.get("years") or block.get("cross_year_table") or [])
        hold_ss = hold_ov
        if hold_ss is None:
            hold_ss = int(block.get("hold_days") or 10)
        sel = sign_selection_from_period_rows(
            rows_ss,
            hold_days=int(hold_ss),
            min_mean_net=float(min_economic_net),
            paper_mean_negative=bool(paper_neg),
        )
        # Attach to block (mutable dicts produced by _class_block)
        if isinstance(block, dict):
            block["sign_selection"] = sel
            block["chosen_sign"] = sel.get("chosen_sign")
            block["chosen_sign_label"] = sel.get("chosen_label")
            block["sign_selection_decision"] = sel.get("decision")
            # Effective metrics after selection (chosen side)
            if sel.get("chosen_sign") == SIGN_INVERTED:
                inv = sel.get("inverted") or {}
                block["metrics_after_sign"] = {
                    "sign": SIGN_INVERTED,
                    "mean_net": inv.get("mean_net"),
                    "mean_net_bp": inv.get("mean_net_bp"),
                    "t_stat": inv.get("t_stat"),
                    "sharpe": inv.get("sharpe"),
                    "win_rate": inv.get("win_rate"),
                    "n_pos": inv.get("n_pos"),
                    "n_neg": inv.get("n_neg"),
                }
            elif sel.get("chosen_sign") == SIGN_ORIGINAL:
                orig = sel.get("original") or {}
                block["metrics_after_sign"] = {
                    "sign": SIGN_ORIGINAL,
                    "mean_net": orig.get("mean_net"),
                    "mean_net_bp": orig.get("mean_net_bp"),
                    "t_stat": orig.get("t_stat"),
                    "sharpe": orig.get("sharpe"),
                    "win_rate": orig.get("win_rate"),
                    "n_pos": orig.get("n_pos"),
                    "n_neg": orig.get("n_neg"),
                }
            else:
                block["metrics_after_sign"] = {
                    "sign": None,
                    "mean_net": None,
                    "reason": sel.get("decision"),
                }
            # Demote research_candidate when both sides fail non-zero
            cand_b = block.get("candidate")
            if isinstance(cand_b, dict) and sel.get("chosen_sign") is None:
                cand_b["sign_selection_demote"] = True
                cand_b["research_candidate"] = False
                cand_b["research_candidate_allowed"] = False
                cand_b["candidate_yes_no"] = "no"
                cand_b["verdict"] = "not_candidate_sign_both_sides_fail"
                cand_b["note_sign"] = (
                    "W86 both sides fail non-zero / non-positive after cost "
                    "→ demote (not Mass/READY path)."
                )
            elif isinstance(cand_b, dict):
                cand_b["chosen_sign"] = sel.get("chosen_sign")
                cand_b["chosen_sign_label"] = sel.get("chosen_label")
                cand_b["sign_selection_decision"] = sel.get("decision")
                # If flipped, expose chosen-side stats for transparency
                if sel.get("chosen_sign") == SIGN_INVERTED:
                    inv = sel.get("inverted") or {}
                    cand_b["stats_original_side"] = cand_b.get("stats")
                    cand_b["stats_chosen_side"] = {
                        "mean_net": inv.get("mean_net"),
                        "t_stat": inv.get("t_stat"),
                        "sharpe": inv.get("sharpe"),
                        "win_rate": inv.get("win_rate"),
                        "n_pos": inv.get("n_pos"),
                        "n_neg": inv.get("n_neg"),
                        "sign": SIGN_INVERTED,
                    }
        sign_selection_blocks[skey] = {
            "chosen_sign": sel.get("chosen_sign"),
            "chosen_label": sel.get("chosen_label"),
            "decision": sel.get("decision"),
            "verdict": sel.get("verdict"),
            "chosen_mean_net_bp": sel.get("chosen_mean_net_bp"),
            "chosen_t_stat": sel.get("chosen_t_stat"),
            "chosen_sharpe": sel.get("chosen_sharpe"),
            "original_mean_net_bp": (sel.get("original") or {}).get("mean_net_bp"),
            "original_t_stat": (sel.get("original") or {}).get("t_stat"),
            "original_sharpe": (sel.get("original") or {}).get("sharpe"),
            "inverted_mean_net_bp": (sel.get("inverted") or {}).get("mean_net_bp"),
            "inverted_t_stat": (sel.get("inverted") or {}).get("t_stat"),
            "inverted_sharpe": (sel.get("inverted") or {}).get("sharpe"),
            "paper_mean_negative": bool(paper_neg),
            "reasons": sel.get("reasons"),
        }

    out["sign_selection"] = {
        "version": SIGN_SELECTION_VERSION,
        "wave": SIGN_SELECTION_WAVE,
        "document": sign_selection_document(),
        "blocks": sign_selection_blocks,
        "note": (
            "W86 evaluate both original and inverted after costs; "
            "prefer positive mean net with non-zero evidence (t guideline). "
            "Both fail → reject/explore demote. Not Mass/READY/live."
        ),
    }

    # Default-path representatives after sign selection.
    # Policy: do not over-invest mom3 vs mom5 — keep both if both survive,
    # else keep the surviving primary. Primary = mom5 pin if survives,
    # else mom3; fund separate.
    survivors: list[dict[str, Any]] = []
    for skey, _pn, _h in _SIGN_FLIP_TARGETS:
        ss = sign_selection_blocks.get(skey) or {}
        block = out.get(skey)
        if not isinstance(block, Mapping):
            continue
        cand = block.get("candidate") or {}
        chosen = ss.get("chosen_sign")
        if chosen is None:
            continue
        rc = bool(cand.get("research_candidate"))
        survivors.append(
            {
                "block_key": skey,
                "chosen_sign": chosen,
                "chosen_label": ss.get("chosen_label"),
                "momentum_n": block.get("momentum_n"),
                "hold_days": block.get("hold_days"),
                "research_candidate": rc,
                "mean_net_bp_chosen": ss.get("chosen_mean_net_bp"),
                "t_stat_chosen": ss.get("chosen_t_stat"),
                "sharpe_chosen": ss.get("chosen_sharpe"),
                "decision": ss.get("decision"),
            }
        )

    xs_surv = [s for s in survivors if s["block_key"].startswith("cross_section")]
    fund_surv = [s for s in survivors if s["block_key"].startswith("fundamentals")]
    # mom3 vs mom5 compression rule
    mom_compress_note: str
    xs_default: list[dict[str, Any]]
    if len(xs_surv) >= 2:
        # both survive → keep both as parallel defaults (W85 already promoted mom3)
        xs_default = list(xs_surv)
        mom_compress_note = (
            "both xs mom5 and mom3 survive sign selection → keep both "
            "as parallel default representatives (no over-invest; not merge)"
        )
    elif len(xs_surv) == 1:
        xs_default = list(xs_surv)
        mom_compress_note = (
            f"single xs survivor after sign selection: {xs_surv[0]['block_key']}"
        )
    else:
        xs_default = []
        mom_compress_note = "no xs survivor after sign selection → demote both"

    default_reps = {
        "wave": SIGN_SELECTION_WAVE,
        "xs_representatives": xs_default,
        "fund_representatives": fund_surv,
        "all_survivors": survivors,
        "mom3_vs_mom5": mom_compress_note,
        "n_default_wired_candidates": len(xs_default) + len(fund_surv),
        "mass_research": MASS_RESEARCH,
        "ready_declared": False,
        "operational_go": False,
        "phase7": PHASE7,
        "note": (
            "Default representatives after W86 sign selection. "
            "research_candidate on block still requires full production bar; "
            "chosen_sign is recorded for StrategySpec signal_sign wiring. "
            "Not Mass / READY / ops GO / live."
        ),
    }
    out["default_path_representatives"] = default_reps

    # Summary yes/no per class (honest; may be yes if research_candidate)
    summary: dict[str, Any] = {}
    any_research_candidate = False
    for key in (
        "multi_day_hold",
        "multi_day_hold_10",
        "event_post",
        "macro_conditioned",
        "cross_section_relative",
        "cross_section_hold_10",
        "cross_section_hold_10_mom3",
        "flow_demand",
        "fundamentals_price",
        "fundamentals_hold_10",
    ):
        block = out.get(key)
        if not isinstance(block, Mapping):
            continue
        cand = block.get("candidate") or {}
        rc = bool(cand.get("research_candidate"))
        if rc:
            any_research_candidate = True
        stats = cand.get("stats") or {}
        ss_sum = sign_selection_blocks.get(key) or {}
        summary[key] = {
            "signal_id": block.get("signal_id"),
            "gate_passed": cand.get("gate_passed"),
            "economic_net_ok": cand.get("economic_net_ok"),
            "occurrence_ok": cand.get("occurrence_ok"),
            "skew_ok": cand.get("skew_ok"),
            "stats_ok": cand.get("stats_ok"),
            "research_candidate_allowed": cand.get(
                "research_candidate_allowed"
            ),
            "research_candidate": rc,
            "verdict": cand.get("verdict"),
            "candidate_yes_no": cand.get("candidate_yes_no") or "no",
            "mean_net": (cand.get("economic_net") or {}).get("mean_net"),
            "t_stat": stats.get("t_stat"),
            "sharpe": stats.get("sharpe"),
            "win_rate": stats.get("win_rate"),
            "payoff": stats.get("payoff"),
            "max_dd": stats.get("max_dd"),
            "calmar": stats.get("calmar"),
            "n_ok_periods": cand.get("n_ok_periods"),
            "chosen_sign": ss_sum.get("chosen_sign", block.get("chosen_sign")),
            "chosen_sign_label": ss_sum.get(
                "chosen_label", block.get("chosen_sign_label")
            ),
            "sign_selection_decision": ss_sum.get("decision"),
            "mean_net_bp_original": ss_sum.get("original_mean_net_bp"),
            "mean_net_bp_inverted": ss_sum.get("inverted_mean_net_bp"),
            "t_stat_original": ss_sum.get("original_t_stat"),
            "t_stat_inverted": ss_sum.get("inverted_t_stat"),
            "decision": (
                "keep"
                if rc
                else (
                    "demote"
                    if (
                        (cand.get("production_criteria") or {}).get("w80_core_ok")
                        and not cand.get("stats_ok")
                    )
                    or cand.get("sign_selection_demote")
                    else "not_candidate"
                )
            ),
        }
    out["candidate_summary"] = summary
    out["any_research_candidate"] = any_research_candidate
    out["ready_declared"] = False
    out["mass_research"] = MASS_RESEARCH
    out["phase7"] = PHASE7
    out["operational_go"] = False
    return out


__all__ = [
    "CLASS_HYP_EVAL_VERSION",
    "CLASS_HYP_EVAL_WAVE",
    "DEFAULT_BARS_FULL_MIRROR_DIR",
    "DEFAULT_BARS_MIRROR_DIR",
    "DEFAULT_EVAL_CODES",
    "EVAL_UNIVERSE_POOL",
    "UNIVERSE_SELECT_RULE",
    "EVAL_TRACKS",
    "EVAL_TRACK_MID_N",
    "EVAL_TRACK_LIQ_LARGE",
    "eval_track",
    "infer_eval_track",
    "rank_eval_codes",
    "select_eval_universe",
    "DEFAULT_PERIODS",
    "DEFAULT_PERIODS_Q4",
    "DEFAULT_SQLITE",
    "MAX_YEAR_POS_NET_SHARE",
    "MIN_ABS_T_STAT",
    "MIN_ACTIVATION_RATE_MULTIDAY",
    "MIN_ECONOMIC_NET",
    "MIN_EVENTS_PER_CODE_YEAR",
    "MIN_EVENTS_PER_TRADING_DAY",
    "MIN_PERIOD_WIN_RATE",
    "MIN_POSITIVE_PERIODS",
    "MIN_SHARPE_PERIOD",
    "MIN_YEARS_RESEARCH_CANDIDATE",
    "bars_rich_to_close_panel",
    "collect_liquidity_bar_rows",
    "fins_summary_ta_eqar_stats",
    "load_bars_from_sqlite_rich",
    "build_nky_vol_series",
    "build_repo_curve_series",
    "evaluate_cross_section_on_bars",
    "evaluate_event_post_on_bars",
    "evaluate_flow_demand_on_bars",
    "evaluate_fundamentals_price_on_bars",
    "evaluate_macro_conditioned_on_bars",
    "evaluate_mf_flow_price_on_bars",
    "evaluate_mf_value_mom_rate_on_bars",
    "evaluate_multi_day_hold_on_bars",
    "evaluate_nky_vol_abs_level_on_bars",
    "evaluate_nky_vol_term_levels_on_bars",
    "evaluate_nky_vol_term_ratio_on_bars",
    "evaluate_rate_curve_xs_on_bars",
    "evaluate_rate_level_xs_on_bars",
    "fins_asof",
    "load_bars_ndjson",
    "load_bars_ndjson_rich",
    "load_fins_earnings_date_from_sqlite",
    "load_fins_events_from_sqlite",
    "load_margin_from_sqlite",
    "load_margin_ndjson",
    "load_nk225f_front_close_series_from_sqlite",
    "load_nky_vol_series_from_sqlite",
    "load_repo_rows_all_tenors_from_sqlite",
    "load_repo_rows_from_sqlite",
    "repo_history_plane_status",
    "load_short_ratio_series_from_sqlite",
    "load_topix_close_series_from_sqlite",
    "merge_event_calendars",
    "momentum_series",
    "resolve_bars_path",
    "resolve_margin_path",
    "run_class_hyp_multi_year_eval",
    "sign_selection_document",
    "sign_selection_from_period_rows",
]
