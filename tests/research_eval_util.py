"""Shared offline fixtures for single-shot / eval-harness tests.

Not collected by pytest (no ``test_`` prefix). D1/R2 doubles stay injected;
Mass/READY remain fail-closed in the helpers that assert them.
"""

from __future__ import annotations

import ast
import json
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


def _assert_mass_ready_off(obj) -> None:
    """Fail-closed Mass/READY (and freeze extras when the payload carries them)."""
    assert _field(obj, "ready_declared") is False
    assert _field(obj, "mass_research") == "NO-GO"
    phase7 = _field(obj, "phase7")
    if phase7 is not _MISSING:
        assert phase7 == "OFF"
    connected_ready = _field(obj, "connected_to_ready")
    if connected_ready is not _MISSING:
        assert connected_ready is False
    connected_mass = _field(obj, "connected_to_mass")
    if connected_mass is not _MISSING:
        assert connected_mass is False
    candidate = _field(obj, "research_candidate")
    if candidate is not _MISSING:
        assert candidate is False
    operational = _field(obj, "operational_go")
    if operational is not _MISSING:
        assert operational is False


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
