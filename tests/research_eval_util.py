"""Shared offline fixtures for single-shot / eval-harness tests.

Not collected by pytest (no ``test_`` prefix). D1/R2 doubles stay injected;
Mass/READY remain fail-closed in the helpers that assert them.
"""

from __future__ import annotations

import ast
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_MISSING = object()

MD_ASOF = (
    "2026-08-04",
    "2026-08-05",
    "2026-08-06",
    "2026-08-07",
    "2026-08-10",
    "2026-08-11",
    "2026-08-12",
)
_MD_BARS = (
    ("2026-08-03", 1000.0, 100.0),
    ("2026-08-04", 1010.0, 110.0),
    ("2026-08-05", 1005.0, 120.0),
    ("2026-08-06", 1020.0, 130.0),
    ("2026-08-07", 1015.0, 140.0),
    ("2026-08-10", 1030.0, 150.0),
    ("2026-08-11", 1025.0, 160.0),
    ("2026-08-12", 1040.0, 170.0),
)
_MD_TOPIX = (
    ("2026-08-03", 3000.0),
    ("2026-08-04", 3005.0),
    ("2026-08-05", 3010.0),
    ("2026-08-06", 3000.0),
    ("2026-08-07", 3015.0),
    ("2026-08-10", 3020.0),
    ("2026-08-11", 3010.0),
    ("2026-08-12", 3030.0),
)
_MD_CAL = (
    "2026-08-03",
    "2026-08-04",
    "2026-08-05",
    "2026-08-06",
    "2026-08-07",
    "2026-08-08",
    "2026-08-09",
    "2026-08-10",
    "2026-08-11",
    "2026-08-12",
)
_AST_BANNED_IMPORTS = (
    "agents",
    "mass_research",
    "start_mass_research",
    "require_mass_research_start",
    "VerifiedResearchReadiness",
    "ResearchReadinessService",
    "OrderIntent",
    "paper_service",
)
_AST_BANNED_CALLS = (
    "start_mass_research",
    "place_order",
    "submit_order",
    "mint_ready",
)
REPO_ROOT = Path(__file__).resolve().parents[1]
_RESEARCH_PKG = REPO_ROOT / "packages" / "product" / "research"
EVAL_HARNESS_PATH = _RESEARCH_PKG / "eval_harness.py"
EVAL_HARNESS_MULTIYEAR_PATH = _RESEARCH_PKG / "eval_harness_multiyear.py"
EVAL_HARNESS_CHECKLIST_PATH = _RESEARCH_PKG / "eval_harness_checklist.py"
EVAL_HARNESS_STANDARD_PATH = _RESEARCH_PKG / "eval_harness_standard.py"
EVAL_HARNESS_S1_PATH = _RESEARCH_PKG / "eval_harness_s1.py"
EVAL_HARNESS_EXTRA_HYP_PATH = _RESEARCH_PKG / "eval_harness_extra_hyp.py"
SINGLE_SHOT_PATH = _RESEARCH_PKG / "single_shot_job.py"
MINIMAL_SIGNAL_PATH = (
    REPO_ROOT / "packages" / "research_runtime" / "features" / "minimal_signal.py"
)
MINIMAL_SIGNAL_DOCS_PATH = (
    REPO_ROOT / "packages" / "research_runtime" / "features" / "minimal_signal_docs.py"
)
C21_SIGNAL_DATASETS = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
)
SYNTH_CODES = ("13010", "72030", "67580")
_FREEZE_FALSE = (
    "connected_to_ready",
    "connected_to_mass",
    "connected_to_mass_research_loop",
    "order_execution",
    "local_sot",
    "operational_go",
    "significance_claimed",
    "edge_claimed",
    "human_main_candidates_selected",
    "frozen_defaults_retuned",
)


def _field(obj: Any, name: str, missing: object = _MISSING) -> Any:
    if isinstance(obj, dict):
        return obj[name] if name in obj else missing
    return getattr(obj, name, missing)


def _d1_row(
    nk: dict, day: str, payload: dict | None = None, *, aa: str = "T15:30:00+09:00"
):
    row = {
        "natural_key": json.dumps(nk),
        "event_time": f"{day}T09:00:00+09:00",
        "available_at": f"{day}{aa}",
    }
    if payload is not None:
        row["payload"] = json.dumps(payload)
    return row


def _fake_d1_tables(tables: dict[str, list[dict]]):
    def fake_d1(sql: str):
        sl = sql.lower()
        for ds, rows in tables.items():
            if ds not in sl:
                continue
            if "count(*)" in sl and "payload" not in sl:
                et = [r.get("event_time") or r.get("available_at") for r in rows]
                return [
                    {
                        "n": len(rows),
                        "min_event_time": et[0],
                        "max_event_time": et[-1],
                    }
                ]
            if "SELECT natural_key FROM" in sql:
                return [{"natural_key": r["natural_key"]} for r in rows]
            return rows
        if "count(*)" in sl:
            return [{"n": 0}]
        return [
            {
                "natural_key": json.dumps({"Date": "2026-08-04"}),
                "event_time": "2026-08-04",
                "available_at": "2026-08-04",
            }
        ]

    return fake_d1


def _fake_d1_multiday(sql: str):
    s = sql.lower()
    if "count(*)" in s:
        return [
            {
                "n": 12,
                "min_event_time": "2026-08-03",
                "max_event_time": "2026-08-12",
            }
        ]
    if "payload" in s and "equities_bars_daily" in s:
        return [
            _d1_row(
                {"Code": code, "Date": d},
                d,
                {"Code": code, "Date": d, "C": c + base, "Vo": vo},
            )
            for code, base in (("13010", 0.0), ("72030", 50.0))
            for d, c, vo in _MD_BARS
        ]
    if "payload" in s and "indices_bars_daily_topix" in s:
        return [_d1_row({"Date": d}, d, {"Date": d, "C": c}) for d, c in _MD_TOPIX]
    if "payload" in s and "markets_calendar" in s:
        return [
            _d1_row(
                {"Date": d},
                d,
                {
                    "Date": d,
                    "HolidayDivision": "0" if d in ("2026-08-08", "2026-08-09") else "1",
                },
                aa="T00:00:00+09:00",
            )
            | {"event_time": d}
            for d in _MD_CAL
        ]
    if "equities_bars_daily" in s:
        return [_d1_row({"Code": "13010", "Date": d}, d) for d, _, _ in _MD_BARS]
    return [
        _d1_row({"Date": "2026-08-04"}, "2026-08-04")
        | {"event_time": "2026-08-04", "available_at": "2026-08-04"}
    ]


def _capture_puts():
    puts: dict[str, bytes] = {}
    buckets: list[str] = []

    def fake_put(bucket: str, key: str, body: bytes, **kwargs):
        puts[key] = body
        buckets.append(bucket)
        return {"bucket": bucket, "key": key, "bytes": len(body), "status": "injected"}

    fake_put.buckets = buckets  # type: ignore[attr-defined]
    return puts, fake_put


def _assert_mass_ready_off(obj, *, allow_research_candidate: bool = False) -> None:
    """Fail-closed Mass/READY (and freeze extras when the payload carries them)."""
    assert _field(obj, "ready_declared") is False
    assert _field(obj, "mass_research") == "NO-GO"
    phase7 = _field(obj, "phase7")
    if phase7 is not _MISSING:
        assert phase7 == "OFF"
    for name in _FREEZE_FALSE:
        val = _field(obj, name)
        if val is not _MISSING:
            assert val is False, name
    paper = _field(obj, "continuous_paper")
    if paper is not _MISSING:
        assert paper == "UNARMED"
    if not allow_research_candidate:
        candidate = _field(obj, "research_candidate")
        if candidate is not _MISSING:
            assert candidate is False


def _ast_imports_and_calls(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
                for alias in node.names:
                    imported.add(alias.name)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    return imported, called


def assert_ast_bans_mass_ready_orders(
    path: Path, *, extra_banned_imports: tuple[str, ...] = ()
) -> str:
    imported, called = _ast_imports_and_calls(path)
    src = path.read_text(encoding="utf-8")
    for name in _AST_BANNED_IMPORTS + extra_banned_imports:
        assert name not in imported, path.name
    for name in _AST_BANNED_CALLS:
        assert name not in called, path.name
    assert "MASS_RESEARCH_ENABLE" not in src
    assert "PHASE7_ENABLE" not in src
    assert 'MASS_RESEARCH_STATUS: str = "GO"' not in src
    assert 'PHASE7_STATUS: str = "ON"' not in src
    assert "READY_DECLARED: bool = True" not in src
    assert "ORDER_EXECUTION: bool = True" not in src
    return src


def _injected_multiday(tmp_path: Path, *, job_id: str, n_asof: int = 7, **overrides):
    puts, fake_put = _capture_puts()
    kw = {
        "period_start": "2026-08-01",
        "period_end": "2026-08-14",
        "job_id": job_id,
        "codes": ["13010", "72030"],
        "as_of_days": list(MD_ASOF[:n_asof]),
        "max_days": 10,
        "min_days": 5,
        "dry_run": True,
        "d1_execute": _fake_d1_multiday,
        "r2_put": fake_put,
        "staging_dir": tmp_path,
    }
    kw.update(overrides)
    return puts, kw


def _put_json(puts: dict[str, bytes], key: str):
    return json.loads(puts[key].decode("utf-8"))


def _boom_d1():
    calls: list[str] = []

    def boom(sql: str):
        calls.append(sql)
        raise AssertionError("d1 must not be called for permanent DEFER input")

    return calls, boom


def _single_shot_kw(*, job_id: str, **overrides):
    kw = {
        "period_start": "2026-08-01",
        "period_end": "2026-08-15",
        "job_id": job_id,
        "dry_run": True,
    }
    kw.update(overrides)
    return kw


def _injected_single_shot(
    tmp_path: Path, *, job_id: str, tables=None, d1_execute=None, **overrides
):
    puts, fake_put = _capture_puts()
    kw = _single_shot_kw(job_id=job_id)
    kw.update(
        {
            "dataset_ids": list(C21_SIGNAL_DATASETS),
            "d1_execute": (
                d1_execute
                if d1_execute is not None
                else _fake_d1_tables(tables or {})
            ),
            "r2_put": fake_put,
            "staging_dir": tmp_path,
        }
    )
    kw.update(overrides)
    return puts, kw


def _c21_d1_tables(
    *,
    bars,
    topix,
    cal_days,
    code: str = "13010",
    hol_key: str = "HolidayDivision",
    cal_aa: str = "T00:00:00+09:00",
    cal_event_time: bool = False,
):
    cal_rows = [
        _d1_row({"Date": d}, d, {"Date": d, hol_key: "1"}, aa=cal_aa)
        for d in cal_days
    ]
    if cal_event_time:
        cal_rows = [row | {"event_time": d} for row, d in zip(cal_rows, cal_days)]
    return {
        "equities_bars_daily": [
            _d1_row(
                {"Code": code, "Date": d},
                d,
                {"Code": code, "Date": d, "C": c, "Vo": vo},
            )
            for d, c, vo in bars
        ],
        "indices_bars_daily_topix": [
            _d1_row({"Date": d}, d, {"Date": d, "C": c}) for d, c in topix
        ],
        "markets_calendar": cal_rows,
    }


def _tip_bar(code: str, day: str, close: float, volume: float) -> dict:
    return {
        "code": code,
        "date": day,
        "volume": volume,
        "close": close,
        "available_at": f"{day}T15:30:00+09:00",
        "event_time": f"{day}T09:00:00+09:00",
    }


def _tip_cal_row(day: str, hol: str = "1") -> dict:
    return {
        "date": day,
        "holiday_division": hol,
        "available_at": f"{day}T09:00:00+09:00",
        "event_time": f"{day}T09:00:00+09:00",
    }


def _tip_topix_row(day: str, close: float) -> dict:
    return {
        "date": day,
        "close": close,
        "available_at": f"{day}T15:30:00+09:00",
        "event_time": f"{day}T09:00:00+09:00",
        "payload": {"Date": day, "C": close},
    }


def _r2_jsonl(
    dataset: str,
    day: str,
    payload: dict,
    *,
    code: str | None = None,
    aa_time: str = "15:30:00",
) -> str:
    nk: dict = {"Date": day}
    if code is not None:
        nk["Code"] = code
    aa = f"{day}T{aa_time}+09:00"
    return json.dumps(
        {
            "source": "jquants",
            "dataset": dataset,
            "natural_key": json.dumps(nk, sort_keys=True),
            "event_time": aa,
            "available_at": aa,
            "payload": payload,
            "raw_payload": payload,
        },
        ensure_ascii=True,
    )


def _weekdays(start: date, n: int) -> list[str]:
    days: list[str] = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def _synth_window(
    start: date,
    n_weekdays: int,
    *,
    with_fins: bool = False,
    with_margin: bool = False,
    close_fn=None,
    vol_fn=None,
    codes: tuple[str, ...] = SYNTH_CODES,
):
    days = _weekdays(start, n_weekdays)
    bars, topix, cal, fins, margin = [], [], [], [], []
    for i, day in enumerate(days):
        for j, code in enumerate(codes):
            close = (
                close_fn(i, j, code)
                if close_fn
                else 100.0 + i + (0.5 if code == "13010" else 0)
            )
            vol = vol_fn(i) if vol_fn else 1000 + i * 20
            bars.append(
                _r2_jsonl(
                    "equities_bars_daily",
                    day,
                    {
                        "Code": code,
                        "Date": day,
                        "O": close,
                        "H": close,
                        "L": close,
                        "C": close,
                        "Vo": vol,
                    },
                    code=code,
                )
            )
            if with_margin:
                margin.append(
                    _r2_jsonl(
                        "markets_margin_interest",
                        day,
                        {
                            "Code": code,
                            "Date": day,
                            "ShortMarginTradeVolume": 500 + i * 5,
                            "LongMarginTradeVolume": 1000 + i * 10 + j,
                        },
                        code=code,
                    )
                )
        topix.append(
            _r2_jsonl(
                "indices_bars_daily_topix", day, {"Date": day, "C": 3000.0 + i * 0.1}
            )
        )
        cal.append(
            _r2_jsonl(
                "markets_calendar",
                day,
                {"Date": day, "HolDiv": "1"},
                aa_time="00:00:00",
            )
        )
        if with_fins and i % 4 == 0:
            fins.append(
                _r2_jsonl(
                    "fins_summary",
                    day,
                    {"Code": "13010", "DiscDate": day},
                    code="13010",
                )
            )
    lines = {
        "equities_bars_daily": bars,
        "indices_bars_daily_topix": topix,
        "markets_calendar": cal,
    }
    if with_fins:
        lines["fins_summary"] = fins
    if with_margin:
        lines["markets_margin_interest"] = margin
        lines["markets_short_ratio"] = []
    return days, lines


def _synth_q4(year: int, **kw):
    return _synth_window(date(year, 9, 1), 24, **kw)


def _r2_period(
    period_id: str,
    days: list[str],
    lines: dict,
    *,
    year: int | None = None,
    s4_eligible: bool | None = None,
    allow_empty=(),
    extra=None,
):
    row = {
        "period_id": period_id,
        "period_start": days[0],
        "period_end": days[-1],
        "max_days": 20,
        "min_days": 10,
        "r2_raw_lines_by_dataset": lines,
    }
    if year is not None:
        row["year"] = year
    if s4_eligible is not None:
        row["s4_eligible"] = s4_eligible
    if allow_empty:
        row["r2_allow_empty_datasets"] = list(allow_empty)
    if extra:
        row.update(extra)
    return row


def _r2_eval_kw(tmp_path: Path, fake_put, **extra):
    kw = {
        "codes": list(SYNTH_CODES),
        "write_per_day_artifacts": False,
        "dry_run": True,
        "r2_put": fake_put,
        "staging_dir": tmp_path,
        "history_source": "r2",
    }
    kw.update(extra)
    return kw


def _r2_skip_period(period_id: str, start: str, end: str, **extra):
    row = {"period_id": period_id, "period_start": start, "period_end": end}
    row.update(extra)
    return row

