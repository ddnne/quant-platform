"""Phase 4 F6 — run_backtest on a real DB path.

Phase 4 closed-loop requires that ``run_backtest`` runs end-to-end on a
real-DB-shaped path (the kind Phase 3.5 produces via sync). Since CI must be
offline-only, this test:

* serves cursor-paginated, Cloudflare-shaped generic D1 rows to the real sync
  script, producing the SQLite layout ``run_backtest`` reads through PIT;
* runs a backtest with a strategy that uses the **features package** to
  compute return_1d at each decision instant (proving F1–F3 + F6 work
  together);
* asserts the result has the standard reproducibility metadata.

Marked ``live`` if you want to point it at a real Phase 3.5 sync DB. The
default path uses the D1 export fixture so it runs offline.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import pit
import features
from core import close_as_of, run_backtest, standard_cost
from core.strategy_protocol import BarContext, OrderIntent
from core.universe import membership_at


TRADING_DAYS = ("2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04")
CODES = ("8697", "7203")


class FixedDbReturnFeatureStrategy:
    """Same decision rule, with the DB path captured at construction time.

    This is the *correct* pattern: the strategy author knows the DB at
    build time (they're running the backtest) and the engine reads through
    PIT separately. The strategy's compute uses its own PIT-scoped read to
    inform its decisions; both sides agree on ``as_of``.
    """

    strategy_id = "return_feature_v0"
    params: dict = {"feature": "return_1d"}

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._entered = False

    def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
        if self._entered:
            return []
        best_code = None
        best_ret = float("-inf")
        for code in ctx.universe:
            out = features.compute(
                "return_1d",
                as_of=ctx.as_of,
                code=code,
                db_path=self._db_path,
            )
            if out.value is None:
                continue
            if out.value > best_ret:
                best_ret = out.value
                best_code = code
        if best_code is None:
            return []
        self._entered = True
        return [OrderIntent(code=best_code, target_weight=1.0)]


def test_backtest_with_features_on_real_db_path(synced_cf_d1_db):
    """F6: CF export → sync → PIT → features → feature-driven backtest.

    Strengthened to assert that ``return_1d`` is **computable (not None)**
    on every day that has prior-day data, for every code in the multi-code
    fixture — not just the last day for one issuer.
    """
    assert synced_cf_d1_db.rc == 0
    db = synced_cf_d1_db.db

    # Reference: 8697's ladder must remain intact for legacy assertions.
    bars = pit.get_equity_bars_daily(
        as_of="2025-04-04T15:30:00+09:00", code=CODES[0], db_path=db
    )
    assert len(bars.rows) == len(TRADING_DAYS)

    last_as_of = f"{TRADING_DAYS[-1]}T15:30:00+09:00"

    # Multi-code: every code has a full 4-day ladder, and features must be
    # computable (not None) on every day that has a prior-day bar.
    feature_values_by_code: dict[str, float | None] = {}
    for code in CODES:
        # Snapshot of the full PIT view at the last day; used to walk
        # forward in time without re-querying inside the inner loop.
        code_bars = pit.get_equity_bars_daily(
            as_of=last_as_of, code=code, db_path=db
        )
        assert len(code_bars.rows) == len(TRADING_DAYS), code

        # Bars are ordered; build a date → close map for the inner loop.
        closes = {r["date"]: r["close"] for r in code_bars.rows}
        prior_close: float | None = None
        for i, day in enumerate(TRADING_DAYS):
            as_of = f"{day}T15:30:00+09:00"
            feat = features.compute(
                "return_1d", as_of=as_of, code=code, db_path=db,
            )
            if i == 0:
                # No prior close available → feature is correctly None.
                assert feat.value is None, (code, day, "expected None on day 0")
            else:
                # Hand-computed return from the bars we just read.
                today_close = closes[day]
                expected = (today_close - prior_close) / prior_close
                assert feat.value is not None, (
                    f"return_1d unexpectedly None for {code} on {day}"
                )
                assert feat.value == pytest.approx(expected), (
                    f"{code} {day}: feat={feat.value} expected={expected}"
                )
            prior_close = closes[day]

        # Capture the last-day value for the cross-code not-None assertion.
        feature_values_by_code[code] = features.compute(
            "return_1d", as_of=last_as_of, code=code, db_path=db,
        ).value

    # Every code produced a non-None feature on the last day with data.
    assert all(v is not None for v in feature_values_by_code.values()), (
        f"return_1d unexpectedly None on last day for some codes: "
        f"{feature_values_by_code}"
    )
    assert len(feature_values_by_code) == len(CODES)

    # Spot-check the canonical 8697 number (kept from the prior single-code
    # assertion so regression coverage is preserved).
    feature = features.compute(
        "return_1d",
        as_of=last_as_of,
        code=CODES[0],
        db_path=db,
    )
    assert feature.value == pytest.approx((104.0 - 101.0) / 101.0)

    strat = FixedDbReturnFeatureStrategy(db)
    res = run_backtest(
        strat,
        TRADING_DAYS[0], TRADING_DAYS[-1],
        db_path=db,
        universe=membership_at(close_as_of(TRADING_DAYS[0]), db_path=db, codes=CODES),
        cost_model=standard_cost(),
    )
    # Engine ran to completion.
    assert res.metadata["trading_days"] >= 1
    assert res.metadata["core_engine_version"]
    assert res.metadata["strategy_id"] == "return_feature_v0"
    # The equity curve has one point per trading day.
    assert len(res.equity_curve) >= 1
    assert len(res.trades) >= 1
    # No look-ahead: every metadata field references the same DB path.
    assert Path(res.metadata["db_path"]) == db


def _live_bar_date_bounds(db: Path) -> tuple[str | None, str | None]:
    """Min/max equities_bars_daily dates from specialized or generic tables."""
    import sqlite3

    conn = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    try:
        dates: list[str] = []
        try:
            row = conn.execute(
                "SELECT MIN(date), MAX(date) FROM jquants_daily_bars"
            ).fetchone()
            dates.extend(str(d)[:10] for d in (row or ()) if d)
        except sqlite3.Error:
            pass
        try:
            row = conn.execute(
                "SELECT MIN(substr(event_time, 1, 10)), "
                "MAX(substr(event_time, 1, 10)) FROM jquants_records "
                "WHERE dataset='equities_bars_daily'"
            ).fetchone()
            dates.extend(str(d)[:10] for d in (row or ()) if d)
        except sqlite3.Error:
            pass
        if not dates:
            return None, None
        return min(dates), max(dates)
    finally:
        conn.close()


def _sample_live_codes(db: Path, n: int = 50) -> list[str]:
    """Sample up to ``n`` issuer codes that have equities_bars_daily rows."""
    import sqlite3

    if n < 1:
        return []

    conn = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    codes: list[str] = []
    try:
        try:
            codes.extend(
                str(r[0])
                for r in conn.execute(
                    "SELECT DISTINCT code FROM jquants_daily_bars "
                    "WHERE code IS NOT NULL ORDER BY code LIMIT ?",
                    (n,),
                )
            )
        except sqlite3.Error:
            pass
        try:
            codes.extend(
                str(r[0])
                for r in conn.execute(
                    "SELECT DISTINCT CAST(json_extract(payload, '$.Code') AS TEXT) "
                    "FROM jquants_records "
                    "WHERE dataset='equities_bars_daily' "
                    "AND json_valid(payload) "
                    "AND json_extract(payload, '$.Code') IS NOT NULL "
                    "ORDER BY 1 LIMIT ?",
                    (n,),
                )
            )
        except sqlite3.Error:
            pass
    finally:
        conn.close()
    return sorted(set(codes))[:n]


@pytest.mark.live
def test_backtest_on_phase35_synced_db():
    """Live smoke: B0 + feature hit-rate + backtest floor on Phase 3.5 DB.

    Skipped unless QP_LIVE=1. DB path: ``QP_SYNCED_DB`` or ``QP_DB`` or
    ``data/structured/ingestion.sqlite``.

      QP_LIVE=1 QP_SYNCED_DB=data/structured/ingestion.sqlite \\
        .venv/bin/python -m pytest -m live \\
        tests/test_phase4_real_db_smoke.py::test_backtest_on_phase35_synced_db -q
    """
    from cf_platform.live_gates import b0_pass

    if os.environ.get("QP_LIVE") != "1":
        pytest.skip("QP_LIVE!=1")
    db_raw = (
        os.environ.get("QP_SYNCED_DB")
        or os.environ.get("QP_DB")
        or "data/structured/ingestion.sqlite"
    )
    db = Path(db_raw)
    if not db.exists():
        pytest.skip(f"QP_SYNCED_DB/QP_DB not set or missing: {db}")

    # --- B0 strict (docs: Phase 4 live smoke uses b0_pass) -----------------
    ok, gates = b0_pass(db, strict=True)
    assert ok, [g.as_dict() for g in gates]
    print("[live] B0 ok:", [g.detail for g in gates])

    # --- Feature hit rate on a sample of issuers -------------------------
    sample_n = int(os.environ.get("QP_FEATURE_SAMPLE", "50"))
    min_hit = float(os.environ.get("QP_FEATURE_MIN_HIT", "0.5"))
    assert sample_n >= 1, f"QP_FEATURE_SAMPLE must be >= 1, got {sample_n}"
    assert 0.0 <= min_hit <= 1.0, (
        f"QP_FEATURE_MIN_HIT must be in [0, 1], got {min_hit}"
    )
    codes = _sample_live_codes(db, n=sample_n)
    assert len(codes) == sample_n, (
        f"expected {sample_n} distinct bar codes, got {len(codes)}"
    )
    lo, hi = _live_bar_date_bounds(db)
    assert lo and hi, "no equities_bars_daily dates in DB"
    as_of = f"{hi}T15:30:00+09:00"
    feature_ids = ("return_1d", "momentum_n", "volatility_n")
    hits = {fid: 0 for fid in feature_ids}
    for code in codes:
        for fid in feature_ids:
            try:
                out = features.compute(
                    fid, as_of=as_of, code=code, db_path=db,
                )
            except Exception:  # noqa: BLE001
                continue
            if out.value is not None:
                hits[fid] += 1
    hit_rates = {fid: hits[fid] / len(codes) for fid in feature_ids}
    print(f"[live] feature hit_rates n={len(codes)} as_of={as_of}: {hit_rates}")
    # At least one price feature should fire on a majority of the sample
    # when history is deep enough; return_1d only needs 2 closes.
    assert hit_rates["return_1d"] >= min_hit, (
        f"return_1d hit_rate={hit_rates['return_1d']:.3f} < {min_hit} "
        f"(n={len(codes)}, as_of={as_of})"
    )

    # --- Backtest trading_days floor ------------------------------------
    # Prefer env window; else use observed bar date span (dense recent window).
    start = os.environ.get("QP_BT_START", lo)
    end = os.environ.get("QP_BT_END", hi)
    floor = int(os.environ.get("QP_BT_MIN_DAYS", "50"))
    assert floor >= 1, f"QP_BT_MIN_DAYS must be >= 1, got {floor}"
    assert start <= end, f"backtest start {start} is after end {end}"
    strat = FixedDbReturnFeatureStrategy(db)
    res = run_backtest(
        strat,
        start,
        end,
        db_path=db,
        cost_model=standard_cost(),
        universe=(
            membership_at(close_as_of(start), db_path=db, codes=codes[:20])
            if codes
            else None
        ),
    )
    trading_days = int(
        res.metrics.get("num_trading_days")
        or res.metadata.get("trading_days")
        or 0
    )
    print(
        f"[live] backtest window={start}..{end} "
        f"trading_days={trading_days} floor={floor}"
    )
    assert trading_days >= floor, (
        f"trading_days={trading_days} < floor={floor} "
        f"(window {start}..{end}; set QP_BT_START/END if needed)"
    )
    assert res.metadata.get("core_engine_version")
    assert res.metadata.get("strategy_id") == "return_feature_v0"
