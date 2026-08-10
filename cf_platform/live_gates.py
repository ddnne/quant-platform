"""B0 order-of-magnitude gates shared by Phase 3.5 validation and Phase 4 live smoke.

Lives outside ``features/`` so the features package stays PIT-only (no sqlite3).
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LIVE_GATES: dict[str, float] = {
    "master_min_issuers": 3000,
    "bars_min_issuers": 3000,
    "bars_min_rows_latest_day": 3000,
    "trading_days_per_year_lo": 230,
    "trading_days_per_year_hi": 255,
}


@dataclass(frozen=True)
class GateResult:
    name: str
    ok: bool
    value: float
    gate: float
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "value": self.value,
            "gate": self.gate,
            "detail": self.detail,
        }


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def measure_b0(db_path: str | Path) -> list[GateResult]:
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    out: list[GateResult] = []
    try:
        master_n = 0
        if _table_exists(conn, "jquants_listed_info"):
            master_n = int(conn.execute(
                "SELECT COUNT(DISTINCT code) FROM jquants_listed_info"
            ).fetchone()[0] or 0)
        g = LIVE_GATES["master_min_issuers"]
        out.append(GateResult("B0_master", master_n >= g, float(master_n), g,
                              f"master issuers={master_n} gate>={g}"))
        bars_n = 0
        latest_day_n = 0
        if _table_exists(conn, "jquants_daily_bars"):
            bars_n = int(conn.execute(
                "SELECT COUNT(DISTINCT code) FROM jquants_daily_bars"
            ).fetchone()[0] or 0)
            row = conn.execute(
                "SELECT date, COUNT(*) FROM jquants_daily_bars "
                "GROUP BY date ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if row:
                latest_day_n = int(row[1])
        g2 = LIVE_GATES["bars_min_issuers"]
        out.append(GateResult("B0_bars_issuers", bars_n >= g2, float(bars_n), g2,
                              f"bar issuers={bars_n} gate>={g2}"))
        g3 = LIVE_GATES["bars_min_rows_latest_day"]
        out.append(GateResult("B0_bars_latest_day", latest_day_n >= g3,
                              float(latest_day_n), g3,
                              f"latest day rows={latest_day_n} gate>={g3}"))
    finally:
        conn.close()
    return out


def b0_pass(db_path: str | Path, *, strict: bool | None = None) -> tuple[bool, list[GateResult]]:
    if strict is None:
        strict = os.environ.get("QP_LIVE", "") == "1"
    results = measure_b0(db_path)
    if not strict:
        return True, results
    return all(r.ok for r in results), results
