"""Research holding-period / turnover metrics (W65 / w0815bf) — 研究用・未宣言.

Purpose
-------
Illustrate **how long a discrete signal sign (+1 / −1) persists** per code,
and how a fixed one-way cost assumption amortizes over a hold of N days.

This module is **research-only**:

* labels: **仮定に依存・研究用・未宣言**
* does **not** mint READY / arm Mass / open Phase7 / authorize orders
* does **not** claim edge / significance / operational GO
* pure functions preferred (unit-testable without R2 / D1)

Run-length definition
---------------------
Given a chronological sequence of per-(day, code) signal signs:

* consecutive **same non-zero** signs form a run of length N (days)
* ``0`` (flat) and ``None`` (missing) **break** the current run
* a sign flip (+1 ↔ −1) ends the current run and starts a new one

Cost amortization (research illustration)
-----------------------------------------
For a fixed one-way cost ``c`` (default 10bp = 0.001), if a position is
entered once and held N days without re-trading, a simple illustration is:

    effective_daily_cost ≈ c / N

This is **not** a trading model, not slippage calibration, and not GO.
Round-trip illustration uses ``2c / N``.
"""

from __future__ import annotations

from statistics import mean, median
from typing import Any, Mapping, Sequence

from research.freezes import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    EDGE_CLAIMED,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PHASE7,
    READY_DECLARED,
    SIGNIFICANCE_CLAIMED,
)

# ---------------------------------------------------------------------------
# Identity / freeze (must never arm)
# ---------------------------------------------------------------------------

HOLDING_METRICS_VERSION: str = "research-holding-metrics/v1"
HOLDING_METRICS_LABEL: str = (
    "仮定に依存・研究用保有・回転メトリクス・未宣言 "
    "(READY未接続 / Mass NO-GO / 運用GOではない)"
)

# Match robustness_gate / single_shot research cost convention.
DEFAULT_ONE_WAY_COST_BP: float = 10.0
DEFAULT_ONE_WAY_COST: float = DEFAULT_ONE_WAY_COST_BP / 10_000.0  # 0.001
DEFAULT_ROUND_TRIP_COST: float = DEFAULT_ONE_WAY_COST * 2.0  # 0.002

DEFAULT_HOLD_DAYS: tuple[int, ...] = (1, 2, 3, 5, 10, 20)
# Histogram bucket right-edges (inclusive): 1, 2, 3, 4-5, 6-10, 11+
DEFAULT_HISTOGRAM_BUCKETS: tuple[tuple[int, int | None], ...] = (
    (1, 1),
    (2, 2),
    (3, 3),
    (4, 5),
    (6, 10),
    (11, None),  # 11+
)


def _freeze_fields() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "edge_claimed": EDGE_CLAIMED,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "label": HOLDING_METRICS_LABEL,
    }


def holding_metrics_document() -> dict[str, Any]:
    """Public document for the research holding / turnover metrics surface."""
    doc = {
        "version": HOLDING_METRICS_VERSION,
        "label": HOLDING_METRICS_LABEL,
        "run_length_rule": (
            "consecutive same non-zero sign (+1 or -1); "
            "0 and None break runs; sign flip starts a new run"
        ),
        "cost_amortization": {
            "one_way_cost_bp": DEFAULT_ONE_WAY_COST_BP,
            "one_way_cost": DEFAULT_ONE_WAY_COST,
            "formula_one_way": "effective_daily_cost ≈ one_way_cost / hold_days_N",
            "formula_round_trip": (
                "effective_daily_cost_rt ≈ 2*one_way_cost / hold_days_N"
            ),
            "note": "研究用イラストのみ・仮定に依存・運用モデルではない",
        },
        "default_hold_days": list(DEFAULT_HOLD_DAYS),
        "default_histogram_buckets": [
            {"lo": lo, "hi": hi, "label": _bucket_label(lo, hi)}
            for lo, hi in DEFAULT_HISTOGRAM_BUCKETS
        ],
        "note": (
            "Research helpers only. No READY, no Mass, no Phase7, no orders, "
            "no edge/significance claim. 仮定に依存・研究用・未宣言."
        ),
    }
    doc.update(_freeze_fields())
    return doc


# ---------------------------------------------------------------------------
# Sign helpers
# ---------------------------------------------------------------------------


def sign_from_value(x: Any) -> int | None:
    """Map a raw signal value to discrete sign ``+1 / 0 / −1``, or ``None``.

    * ``None`` / non-numeric → ``None``
    * ``> 0`` → ``+1``
    * ``< 0`` → ``−1``
    * ``== 0`` → ``0``
    """
    if x is None:
        return None
    if isinstance(x, str):
        s = x.strip()
        if s in ("", "null", "None", "nan", "NaN"):
            return None
        if s in ("+1", "1", "+"):
            return 1
        if s in ("-1", "-"):
            return -1
        if s in ("0", "flat"):
            return 0
        try:
            x = float(s)
        except ValueError:
            return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Run-length (pure)
# ---------------------------------------------------------------------------


def run_lengths_for_sign_sequence(
    signs: Sequence[Any],
    *,
    non_zero_only: bool = True,
) -> list[int]:
    """Compute consecutive same non-zero sign run lengths from a day sequence.

    Parameters
    ----------
    signs:
        Chronological sequence of sign-like values (``+1/0/−1/None`` or raw).
    non_zero_only:
        When True (default), ``0`` breaks a run (only non-zero signs count).
        When False, ``0`` is treated as a sign that can form its own runs.

    Returns
    -------
    list[int]
        Lengths of completed runs (empty if no non-zero consecutive blocks).

    Notes
    -----
    * ``None`` always breaks the current run (missing observation).
    * A sign flip ends the current run and starts a new one of length 1.
    """
    runs: list[int] = []
    cur: int | None = None
    n = 0
    for raw in signs:
        s = sign_from_value(raw)
        if s is None:
            if n > 0:
                runs.append(n)
            cur = None
            n = 0
            continue
        if non_zero_only and s == 0:
            if n > 0:
                runs.append(n)
            cur = None
            n = 0
            continue
        if cur is None or s != cur:
            if n > 0:
                runs.append(n)
            cur = s
            n = 1
        else:
            n += 1
    if n > 0:
        runs.append(n)
    return runs


def _percentile_nearest_rank(sorted_vals: Sequence[float], p: float) -> float | None:
    """Nearest-rank percentile on a pre-sorted non-empty sequence; p in [0, 100]."""
    if not sorted_vals:
        return None
    if p <= 0:
        return float(sorted_vals[0])
    if p >= 100:
        return float(sorted_vals[-1])
    n = len(sorted_vals)
    # Nearest-rank: rank = ceil(p/100 * n), 1-indexed.
    rank = int((p / 100.0) * n)
    if rank < 1:
        rank = 1
    if rank > n:
        rank = n
    # If p/100*n is exact integer, nearest-rank uses that rank; ceil when fractional.
    import math

    rank = max(1, min(n, int(math.ceil((p / 100.0) * n))))
    return float(sorted_vals[rank - 1])


def _bucket_label(lo: int, hi: int | None) -> str:
    if hi is None:
        return f"{lo}+"
    if lo == hi:
        return str(lo)
    return f"{lo}-{hi}"


def histogram_run_lengths(
    run_lengths: Sequence[int],
    *,
    buckets: Sequence[tuple[int, int | None]] | None = None,
) -> list[dict[str, Any]]:
    """Bucket run lengths into histogram rows ``{label, lo, hi, count, share}``."""
    bks = list(buckets) if buckets is not None else list(DEFAULT_HISTOGRAM_BUCKETS)
    counts = [0 for _ in bks]
    total = 0
    for raw in run_lengths:
        try:
            L = int(raw)
        except (TypeError, ValueError):
            continue
        if L <= 0:
            continue
        total += 1
        placed = False
        for i, (lo, hi) in enumerate(bks):
            if L < lo:
                continue
            if hi is None or L <= hi:
                counts[i] += 1
                placed = True
                break
        if not placed:
            # Longer than last finite bucket and no open-ended tail: skip.
            pass
    out: list[dict[str, Any]] = []
    for (lo, hi), c in zip(bks, counts):
        out.append(
            {
                "label": _bucket_label(lo, hi),
                "lo": lo,
                "hi": hi,
                "count": int(c),
                "share": (float(c) / float(total)) if total else None,
            }
        )
    return out


def run_length_distribution(
    run_lengths: Sequence[int],
    *,
    histogram_buckets: Sequence[tuple[int, int | None]] | None = None,
) -> dict[str, Any]:
    """Summarize run lengths: mean / median / p50 / p90 + histogram.

    Empty input → null stats, empty histogram counts, ``n_runs=0``.
    """
    vals: list[int] = []
    for raw in run_lengths:
        try:
            L = int(raw)
        except (TypeError, ValueError):
            continue
        if L > 0:
            vals.append(L)
    vals_sorted = sorted(vals)
    n = len(vals_sorted)
    if n == 0:
        return {
            "n_runs": 0,
            "mean": None,
            "median": None,
            "p50": None,
            "p90": None,
            "min": None,
            "max": None,
            "histogram": histogram_run_lengths([], buckets=histogram_buckets),
        }
    p50 = _percentile_nearest_rank(vals_sorted, 50)
    p90 = _percentile_nearest_rank(vals_sorted, 90)
    med = float(median(vals_sorted))
    return {
        "n_runs": n,
        "mean": float(mean(vals_sorted)),
        "median": med,
        "p50": p50,
        "p90": p90,
        "min": float(vals_sorted[0]),
        "max": float(vals_sorted[-1]),
        "histogram": histogram_run_lengths(vals_sorted, buckets=histogram_buckets),
    }


# ---------------------------------------------------------------------------
# Panel helpers (day × code)
# ---------------------------------------------------------------------------


def panel_run_lengths_by_code(
    records: Sequence[Mapping[str, Any]],
    *,
    day_key: str = "date",
    code_key: str = "code",
    sign_key: str = "sign",
    non_zero_only: bool = True,
) -> dict[str, list[int]]:
    """Group panel records by code, sort by day, return per-code run lengths.

    Each record should include day, code, and a sign-like field (``sign`` or
    ``value`` — pass ``sign_key`` accordingly).
    """
    by_code: dict[str, list[tuple[str, Any]]] = {}
    for raw in records:
        if not isinstance(raw, Mapping):
            continue
        code = raw.get(code_key)
        day = raw.get(day_key)
        if code is None or day is None:
            continue
        code_s = str(code).strip()
        day_s = str(day).strip()[:10]
        if not code_s or not day_s:
            continue
        # Prefer explicit sign_key; fall back to value if missing.
        if sign_key in raw:
            sig = raw.get(sign_key)
        else:
            sig = raw.get("value")
        by_code.setdefault(code_s, []).append((day_s, sig))

    out: dict[str, list[int]] = {}
    for code, pairs in by_code.items():
        pairs_sorted = sorted(pairs, key=lambda t: t[0])
        # Deduplicate same day (keep last).
        dedup: list[tuple[str, Any]] = []
        for day_s, sig in pairs_sorted:
            if dedup and dedup[-1][0] == day_s:
                dedup[-1] = (day_s, sig)
            else:
                dedup.append((day_s, sig))
        out[code] = run_lengths_for_sign_sequence(
            [s for _, s in dedup],
            non_zero_only=non_zero_only,
        )
    return out


def panel_run_length_stats(
    records: Sequence[Mapping[str, Any]],
    *,
    day_key: str = "date",
    code_key: str = "code",
    sign_key: str = "sign",
    non_zero_only: bool = True,
    histogram_buckets: Sequence[tuple[int, int | None]] | None = None,
) -> dict[str, Any]:
    """Aggregate run-length distribution over a (day, code, sign) panel.

    Returns a research report dict with freeze flags always closed.
    """
    by_code = panel_run_lengths_by_code(
        records,
        day_key=day_key,
        code_key=code_key,
        sign_key=sign_key,
        non_zero_only=non_zero_only,
    )
    all_runs: list[int] = []
    per_code_mean: dict[str, float | None] = {}
    for code, runs in sorted(by_code.items()):
        all_runs.extend(runs)
        per_code_mean[code] = float(mean(runs)) if runs else None

    dist = run_length_distribution(all_runs, histogram_buckets=histogram_buckets)
    n_codes = len(by_code)
    n_records = len(records)

    # Rough turnover illustration: average flips per code-day.
    # turnover_proxy = 1 / mean_hold when mean_hold is defined.
    mean_hold = dist.get("mean")
    turnover_proxy = (1.0 / mean_hold) if mean_hold and mean_hold > 0 else None

    out: dict[str, Any] = {
        "version": HOLDING_METRICS_VERSION,
        "n_codes": n_codes,
        "n_records": n_records,
        "n_runs_total": dist["n_runs"],
        "run_length": dist,
        "turnover_proxy_per_day": turnover_proxy,
        "turnover_proxy_note": (
            "1/mean_run_length — research proxy for fraction of codes "
            "expected to flip per day if holds equal mean; 仮定に依存"
        ),
        "per_code_mean_run_length": per_code_mean,
        "non_zero_only": bool(non_zero_only),
    }
    out.update(_freeze_fields())
    return out


def majority_sign_from_distribution(
    sign_distribution: Mapping[str, Any] | None,
) -> int | None:
    """Pick strict majority sign from a ``{+1, -1, 0, null}`` count map.

    Returns ``None`` on tie or empty. Null counts are ignored for majority.
    """
    if not sign_distribution:
        return None
    counts = {
        1: int(sign_distribution.get("+1") or sign_distribution.get("1") or 0),
        -1: int(sign_distribution.get("-1") or 0),
        0: int(sign_distribution.get("0") or 0),
    }
    best_sign: int | None = None
    best_n = -1
    tie = False
    for s, n in counts.items():
        if n > best_n:
            best_n = n
            best_sign = s
            tie = False
        elif n == best_n and n > 0:
            tie = True
    if best_n <= 0 or tie:
        return None
    return best_sign


def extract_sign_panel_from_batch_summary(
    batch_summary: Mapping[str, Any],
    *,
    prefer_sample_values: bool = True,
    expand_majority_to_codes: bool = True,
) -> dict[str, Any]:
    """Best-effort (day, code, sign) panel from a multiday ``batch_summary``.

    Strategy
    --------
    1. If ``per_day[].sample_values`` has ``code`` + ``value``, use those rows
       (partial coverage — only the sample slice stored in the artifact).
    2. If ``expand_majority_to_codes`` and ``codes`` + ``sign_distribution``
       are present, expand the **majority sign of each day to every code**.
       This is exact only when all codes share the same sign that day
       (observed for S1 topix_rel batches where distribution is 30/0).
       Documented as research reconstruction; not a full row re-eval.

    Returns
    -------
    dict with ``records``, ``source``, ``codes``, ``dates``, freeze flags.
    """
    codes = [str(c).strip() for c in (batch_summary.get("codes") or []) if str(c).strip()]
    per_day = list(batch_summary.get("per_day") or [])
    records: list[dict[str, Any]] = []
    source = "empty"
    dates: list[str] = []

    sample_records: list[dict[str, Any]] = []
    if prefer_sample_values:
        for day in per_day:
            date_s = str(day.get("date") or day.get("as_of") or "")[:10]
            if not date_s:
                continue
            for sv in day.get("sample_values") or []:
                if not isinstance(sv, Mapping):
                    continue
                code = sv.get("code")
                if code is None:
                    continue
                val = sv.get("value") if "value" in sv else sv.get("sign")
                sample_records.append(
                    {
                        "date": date_s,
                        "code": str(code).strip(),
                        "sign": sign_from_value(val),
                        "value": val,
                    }
                )

    # Detect whether majority expansion is faithful (all mass on one sign).
    unanimous_days = 0
    mixed_days = 0
    majority_records: list[dict[str, Any]] = []
    if expand_majority_to_codes and codes:
        for day in per_day:
            date_s = str(day.get("date") or day.get("as_of") or "")[:10]
            if not date_s:
                continue
            dates.append(date_s)
            sd = day.get("sign_distribution") or {}
            maj = majority_sign_from_distribution(sd)
            p1 = int(sd.get("+1") or 0)
            m1 = int(sd.get("-1") or 0)
            z = int(sd.get("0") or 0)
            active = p1 + m1 + z
            # Unanimous among non-null discrete signs if one bucket == active.
            if active > 0 and max(p1, m1, z) == active:
                unanimous_days += 1
            elif active > 0:
                mixed_days += 1
            for code in codes:
                majority_records.append(
                    {
                        "date": date_s,
                        "code": code,
                        "sign": maj,
                        "value": float(maj) if maj is not None else None,
                    }
                )

    if expand_majority_to_codes and codes and majority_records and mixed_days == 0:
        records = majority_records
        source = "sign_distribution_majority_expanded_unanimous"
    elif sample_records:
        records = sample_records
        source = "sample_values_partial"
        dates = sorted({r["date"] for r in records})
    elif majority_records:
        records = majority_records
        source = "sign_distribution_majority_expanded_mixed"
    else:
        records = []
        source = "empty"

    if not dates:
        dates = sorted({r["date"] for r in records})

    out: dict[str, Any] = {
        "version": HOLDING_METRICS_VERSION,
        "source": source,
        "signal_id": batch_summary.get("signal_id"),
        "job_id": batch_summary.get("job_id"),
        "codes": codes,
        "dates": dates,
        "n_records": len(records),
        "unanimous_days": unanimous_days,
        "mixed_days": mixed_days,
        "records": records,
        "note": (
            "研究用パネル再構成。sample_values は部分標本。"
            "majority expand は当日全コード同符号のときのみ厳密。"
            "仮定に依存・研究用・未宣言。"
        ),
    }
    out.update(_freeze_fields())
    return out


# ---------------------------------------------------------------------------
# Cost amortization table (research illustration)
# ---------------------------------------------------------------------------


def cost_amortization_table(
    *,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    hold_days: Sequence[int] | None = None,
    one_way_cost_bp: float | None = None,
) -> list[dict[str, Any]]:
    """Reference table: effective daily cost ≈ one_way / N for hold N days.

    Parameters
    ----------
    one_way_cost:
        Fractional one-way cost (default 0.001 = 10bp).
    hold_days:
        Positive integers N (default 1,2,3,5,10,20).
    one_way_cost_bp:
        If set, overrides ``one_way_cost`` via ``bp / 10_000``.

    Returns
    -------
    list of row dicts (no READY / Mass fields — pure table). Use
    :func:`cost_amortization_report` for a freeze-wrapped document.
    """
    if one_way_cost_bp is not None:
        c = float(one_way_cost_bp) / 10_000.0
        bp = float(one_way_cost_bp)
    else:
        c = float(one_way_cost)
        bp = c * 10_000.0
    days = list(hold_days) if hold_days is not None else list(DEFAULT_HOLD_DAYS)
    rows: list[dict[str, Any]] = []
    for n in days:
        n_i = int(n)
        if n_i <= 0:
            raise ValueError(f"hold_days entries must be positive, got {n!r}")
        eff = c / float(n_i)
        eff_rt = (2.0 * c) / float(n_i)
        rows.append(
            {
                "hold_days_N": n_i,
                "one_way_cost": c,
                "one_way_cost_bp": bp,
                "effective_daily_cost": eff,
                "effective_daily_cost_bp": eff * 10_000.0,
                "effective_daily_cost_round_trip": eff_rt,
                "effective_daily_cost_round_trip_bp": eff_rt * 10_000.0,
                "formula": "effective_daily_cost = one_way_cost / hold_days_N",
            }
        )
    return rows


def cost_amortization_report(
    *,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    hold_days: Sequence[int] | None = None,
    one_way_cost_bp: float | None = None,
) -> dict[str, Any]:
    """Freeze-wrapped amortization table (研究用イラスト・仮定に依存)."""
    rows = cost_amortization_table(
        one_way_cost=one_way_cost,
        hold_days=hold_days,
        one_way_cost_bp=one_way_cost_bp,
    )
    c = rows[0]["one_way_cost"] if rows else float(one_way_cost)
    bp = rows[0]["one_way_cost_bp"] if rows else float(c) * 10_000.0
    out: dict[str, Any] = {
        "version": HOLDING_METRICS_VERSION,
        "table_kind": "cost_amortization_research_illustration",
        "one_way_cost": c,
        "one_way_cost_bp": bp,
        "round_trip_cost": 2.0 * c,
        "round_trip_cost_bp": 2.0 * bp,
        "formula_one_way": "effective_daily_cost ≈ one_way_cost / hold_days_N",
        "formula_round_trip": (
            "effective_daily_cost_rt ≈ 2*one_way_cost / hold_days_N"
        ),
        "rows": rows,
        "note": (
            "研究用コスト償却イラストのみ。スリッページ校正でも執行モデルでもない。"
            "仮定に依存・研究用・未宣言。"
        ),
    }
    out.update(_freeze_fields())
    return out


def holding_metrics_report(
    records: Sequence[Mapping[str, Any]],
    *,
    day_key: str = "date",
    code_key: str = "code",
    sign_key: str = "sign",
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    hold_days: Sequence[int] | None = None,
    include_amortization: bool = True,
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Full research report: run-length stats + optional amortization table.

    Always returns closed freeze flags (Mass NO-GO / READY false / no edge).
    """
    stats = panel_run_length_stats(
        records,
        day_key=day_key,
        code_key=code_key,
        sign_key=sign_key,
    )
    out: dict[str, Any] = {
        "version": HOLDING_METRICS_VERSION,
        "run_length_stats": stats,
    }
    if include_amortization:
        out["cost_amortization"] = cost_amortization_report(
            one_way_cost=one_way_cost,
            hold_days=hold_days,
        )
        # Cross-walk: at mean hold, what effective daily cost would be.
        mean_hold = (stats.get("run_length") or {}).get("mean")
        c = float(one_way_cost)
        if mean_hold and mean_hold > 0:
            out["implied_at_mean_hold"] = {
                "mean_hold_days": mean_hold,
                "one_way_cost": c,
                "effective_daily_cost": c / float(mean_hold),
                "effective_daily_cost_bp": (c / float(mean_hold)) * 10_000.0,
                "note": (
                    "イラスト: 平均保有日数で one_way を割った実効日次コスト。"
                    "仮定に依存・研究用・未宣言。"
                ),
            }
        else:
            out["implied_at_mean_hold"] = None
    if meta:
        out["meta"] = dict(meta)
    out.update(_freeze_fields())
    return out


__all__ = [
    "CONNECTED_TO_MASS",
    "CONNECTED_TO_READY",
    "DEFAULT_HOLD_DAYS",
    "DEFAULT_HISTOGRAM_BUCKETS",
    "DEFAULT_ONE_WAY_COST",
    "DEFAULT_ONE_WAY_COST_BP",
    "DEFAULT_ROUND_TRIP_COST",
    "EDGE_CLAIMED",
    "HOLDING_METRICS_LABEL",
    "HOLDING_METRICS_VERSION",
    "MASS_RESEARCH",
    "OPERATIONAL_GO",
    "PHASE7",
    "READY_DECLARED",
    "SIGNIFICANCE_CLAIMED",
    "cost_amortization_report",
    "cost_amortization_table",
    "extract_sign_panel_from_batch_summary",
    "histogram_run_lengths",
    "holding_metrics_document",
    "holding_metrics_report",
    "majority_sign_from_distribution",
    "panel_run_length_stats",
    "panel_run_lengths_by_code",
    "run_length_distribution",
    "run_lengths_for_sign_sequence",
    "sign_from_value",
]
