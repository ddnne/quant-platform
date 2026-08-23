"""Shared offline fixtures for research eval tests.

Not collected by pytest (no ``test_`` prefix). Mass/READY remain fail-closed
in the helpers that assert them.
"""

from __future__ import annotations

import ast
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_MISSING = object()

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
HARNESS_AST_PATHS = (
    _RESEARCH_PKG / "r2_io.py",
    _RESEARCH_PKG / "complete21.py",
    _RESEARCH_PKG / "r2_feature_context.py",
    _RESEARCH_PKG / "r2_feature_parse.py",
    _RESEARCH_PKG / "r2_feature_normalize.py",
    _RESEARCH_PKG / "r2_feature_mirror.py",
    _RESEARCH_PKG / "r2_available_at.py",
    _RESEARCH_PKG / "daily_path_eval.py",
)
_DEFAULT_INGESTED_AT = "2026-08-12T00:00:00+09:00"
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
    "go",
    "promote_as_main",
)


def _field(obj: Any, name: str, missing: object = _MISSING) -> Any:
    if isinstance(obj, dict):
        return obj[name] if name in obj else missing
    return getattr(obj, name, missing)


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


def _r2_jsonl(
    dataset: str,
    day: str,
    payload: dict,
    *,
    code: str | None = None,
    aa_time: str = "15:30:00",
    available_at: str | None = None,
    event_time: str | None = None,
    ingested_at: str | None = None,
) -> str:
    nk: dict = {"Date": day}
    if code is not None:
        nk["Code"] = code
    if "S33" in payload:
        nk = {"Date": day, "S33": payload["S33"]}
    aa = available_at if available_at is not None else f"{day}T{aa_time}+09:00"
    et = event_time if event_time is not None else f"{day}T{aa_time}+09:00"
    row = {
        "source": "jquants",
        "dataset": dataset,
        "natural_key": json.dumps(nk, sort_keys=True),
        "event_time": et,
        "available_at": aa,
        "payload": payload,
        "raw_payload": payload,
    }
    if ingested_at is not None:
        row["ingested_at"] = ingested_at
    return json.dumps(row, ensure_ascii=True)


def _r2_bar_line(
    code: str,
    day: str,
    *,
    close: float = 100.0,
    volume: float = 1000.0,
    available_at: str | None = None,
    event_time: str | None = None,
) -> str:
    return _r2_jsonl(
        "equities_bars_daily",
        day,
        {
            "Code": code,
            "Date": day,
            "O": close,
            "H": close,
            "L": close,
            "C": close,
            "Vo": volume,
        },
        code=code,
        available_at=available_at,
        event_time=event_time,
        ingested_at=_DEFAULT_INGESTED_AT,
    )


def _r2_topix_line(
    day: str,
    *,
    close: float = 3000.0,
    available_at: str | None = None,
) -> str:
    return _r2_jsonl(
        "indices_bars_daily_topix",
        day,
        {"Date": day, "C": close, "O": close, "H": close, "L": close},
        available_at=available_at,
        ingested_at=_DEFAULT_INGESTED_AT,
    )


def _r2_cal_line(
    day: str,
    *,
    hol: str = "1",
    available_at: str | None = None,
) -> str:
    aa = available_at if available_at is not None else f"{day}T09:00:00+09:00"
    return _r2_jsonl(
        "markets_calendar",
        day,
        {"Date": day, "HolDiv": hol},
        available_at=aa,
        event_time=f"{day}T00:00:00+09:00",
        ingested_at=aa,
    )


def _r2_catalog_line(
    dataset: str,
    day: str,
    *,
    code: str | None = "13010",
    available_at: str | None = None,
    extra_payload: dict | None = None,
) -> str:
    payload = {"Date": day, **(extra_payload or {})}
    if code is not None:
        payload["Code"] = code
    return _r2_jsonl(dataset, day, payload, code=code, available_at=available_at)


def _s1_two_day_map(
    *,
    code: str = "13010",
    d0: str = "2026-06-02",
    d1: str = "2026-06-03",
    close0: float = 100.0,
    close1: float = 100.0,
    vol0: float = 1000.0,
    vol1: float = 1000.0,
    extra_bars=(),
    include_topix: bool = True,
    include_cal: bool = True,
):
    lines: dict[str, list[str]] = {
        "equities_bars_daily": [
            _r2_bar_line(code, d0, close=close0, volume=vol0),
            _r2_bar_line(code, d1, close=close1, volume=vol1),
            *extra_bars,
        ]
    }
    if include_topix:
        lines["indices_bars_daily_topix"] = [
            _r2_topix_line(d0, close=3000.0),
            _r2_topix_line(d1, close=3030.0),
        ]
    if include_cal:
        lines["markets_calendar"] = [_r2_cal_line(d0), _r2_cal_line(d1)]
    return lines


def _history_bar(code: str, day: str, close: float, volume: float | None = None, **extra):
    aa = extra.pop("available_at", f"{day}T15:30:00+09:00")
    row = {"code": code, "date": day, "close": close, "available_at": aa, **extra}
    if volume is not None:
        row["volume"] = volume
    if "event_time" not in row:
        row["event_time"] = aa
    return row


def _history_topix(day: str, close: float = 3000.0, **extra):
    aa = extra.pop("available_at", f"{day}T15:30:00+09:00")
    return {
        "date": day,
        "close": close,
        "available_at": aa,
        "event_time": extra.pop("event_time", aa),
        **extra,
    }


def _weekdays(start: date, n: int) -> list[str]:
    days: list[str] = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def assert_unique_family_specs(
    specs: list[dict[str, Any]],
    expected_ids: frozenset[str],
    *,
    disjoint_from: tuple[frozenset[str], ...] = (),
) -> None:
    """YAML-backed unique family identity. generation_enabled/go: catalog parity."""
    from research.offline.factory import propose_profit_hypotheses
    from research.unique_logic.constants import (
        KNOWN_DEMOTED_OR_WEAK,
        KNOWN_WEAK_THESIS,
        LOGIC_CATALOG_HEADLINE_BAN,
    )

    ids = [s["logic_id"] for s in specs]
    assert ids == sorted(expected_ids)
    assert ids
    for s in specs:
        assert s["new_unique_logic"] is True
        assert s["catalog"] is True
        assert s["catalog_map"] is None
        lid = s["logic_id"]
        assert lid not in LOGIC_CATALOG_HEADLINE_BAN
        assert lid not in KNOWN_WEAK_THESIS
        assert lid not in KNOWN_DEMOTED_OR_WEAK
        for other in disjoint_from:
            assert lid not in other
        params = s.get("params")
        assert isinstance(params, dict)
    out = propose_profit_hypotheses(specs, evaluate=False)
    assert out["n_accepted"] == len(specs)
    assert out["n_rejected"] == 0
    assert [a["logic_id"] for a in out["accepted"]] == ids
    for a in out["accepted"]:
        assert a["logic_id"] not in LOGIC_CATALOG_HEADLINE_BAN
        assert a.get("eval_mapped_to_catalog") in (None, False)


def _eval_cell(logic_id: str, **fields):
    return {"logic_id": logic_id, **fields}


def _eval_year_cells(
    logic_id: str, years=(2015, 2017, 2019, 2021, 2023, 2025), **fields
):
    return [_eval_cell(logic_id, window_id=f"y{y}", **fields) for y in years]


def _eval_complete_cell(logic_id: str, *, occupancy, **fields):
    row = {
        "window_id": "y2015_full",
        "occupancy": occupancy,
        "total_ret_net": 0.01,
        "daily_path_complete": True,
    }
    row.update(fields)
    return _eval_cell(logic_id, **row)


def _eval_complete_year_cells(logic_id: str, *, occupancy, **fields):
    fields.setdefault("total_ret_net", 0.01)
    fields.setdefault("daily_path_complete", True)
    return _eval_year_cells(logic_id, occupancy=occupancy, **fields)


def _basket_row(basket_id: str, n_pos: int, n_neg: int, **extra):
    return {
        "basket_id": basket_id,
        "n_pos_windows": n_pos,
        "n_neg_windows": n_neg,
        **extra,
    }


def _theme_fund_row(n_pos: int, n_neg: int, **extra):
    return _basket_row("basket_theme_fund", n_pos, n_neg, **extra)


def _head4_row(n_pos: int, n_neg: int, **extra):
    return _basket_row("basket_head4", n_pos, n_neg, **extra)


def _flow_row(n_pos: int, n_neg: int, **extra):
    return _basket_row("basket_theme_flow", n_pos, n_neg, **extra)


def _baskets(*rows, job_id: str | None = None):
    out: dict[str, Any] = {"baskets": list(rows)}
    if job_id is not None:
        out["job_id"] = job_id
    return out


def _fund_head(fund: tuple[int, int], head: tuple[int, int], *, job_id: str | None = None):
    return _baskets(_theme_fund_row(*fund), _head4_row(*head), job_id=job_id)


def _fund_flow(fund: tuple[int, int], flow: tuple[int, int], *, job_id: str | None = None):
    return _baskets(_theme_fund_row(*fund), _flow_row(*flow), job_id=job_id)


def _aa_row(
    day: str,
    *,
    event_time: str | None = None,
    available_at=None,
    **extra,
):
    return {
        "date": day,
        "event_time": (
            event_time if event_time is not None else f"{day}T00:00:00+09:00"
        ),
        "available_at": available_at,
        **extra,
    }


EVENT_BAR_CODES = ("13010", "72030", "67580", "99840")


def _event_bars(
    n: int = 40,
    start: str = "2019-01-",
    *,
    mode: str = "cycle",
):
    dates = [f"{start}{d:02d}" for d in range(1, min(n, 28) + 1)]
    out: dict[str, list[tuple[str, float]]] = {}
    for ci, code in enumerate(EVENT_BAR_CODES):
        px = 100.0 + 10 * ci
        series = []
        for i, d in enumerate(dates):
            if mode == "filter":
                if code == "13010":
                    px *= 1.004
                elif code == "72030":
                    px *= 0.996
                else:
                    px *= 1.0 + 0.002 * ((i + ci) % 3 - 1)
            else:
                px *= 1.0 + 0.002 * ((i + ci) % 3 - 1)
            series.append((d, px))
        out[code] = series
    return out


def _disc_event(disc_date: str, **fields):
    return {"disc_date": disc_date, **fields}


def _two_name_events(
    *,
    t13010: str | None = "12:00:00",
    t72030: str | None = "12:00:00",
):
    return {
        "13010": [
            _disc_event(
                "2019-01-10",
                disc_time=t13010,
                eps=12.0,
                feps=10.0,
                prior_eps=9.0,
            )
        ],
        "72030": [
            _disc_event(
                "2019-01-12",
                disc_time=t72030,
                eps=4.0,
                feps=6.0,
                prior_eps=5.0,
            )
        ],
    }


def _event_eval_kw(*, with_period: bool = True, **extra):
    kw: dict[str, Any] = {"one_way_cost": 0.001}
    if with_period:
        kw["period_start"] = "2019-01-01"
        kw["period_end"] = "2019-01-28"
    kw.update(extra)
    return kw


def _logic_spec(rows, lid: str) -> dict:
    return dict(next(s for s in rows if s["logic_id"] == lid))


def _with_min_hist(spec: dict, min_hist: int = 5) -> dict:
    out = dict(spec)
    out["params"] = dict(spec.get("params") or {})
    out["params"]["min_hist"] = min_hist
    out["min_hist"] = min_hist
    return out
