"""D1 hot-tip extract + tip FeatureContext (Mass OFF / READY not declared).

Bounded CF D1 ``quant-ingest`` tip reads and COMPLETE-21 min-feature compute
on an in-memory :class:`features.runtime.FeatureContext`. History SoT remains
R2 ``quant-structured``; local SQLite is not used.

Execute / multiday jobs stay in :mod:`research.single_shot_job`. This module
is the shared tip-row / PIT reader surface used by the R2 history bridge
(:mod:`research.r2_feature_context`).

Fail-closed: COMPLETE 21 only, permanent DEFER 5 hard-reject, Mass OFF,
READY not declared. No densify, no orders.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping, Sequence

from features.registry import get as get_feature
from features.runtime import FEATURES_RUNTIME_VERSION, FeatureContext
from features.types import FeatureOutput

from research.freezes import (
    MASS_RESEARCH as MASS_RESEARCH_STATUS,
    PHASE7 as PHASE7_STATUS,
    READY_DECLARED,
    READY_PUBLICATION as READY_PUBLICATION_STATUS,
)
from research.single_shot_job import (
    DEFAULT_CANDIDATE_FEATURES,
    DEFAULT_FEATURE_CODE_LIMIT,
    DEFAULT_FEATURE_ROW_LIMIT,
    DEFAULT_TIP_SAMPLE_LIMIT,
    D1ExecuteFn,
    D1_DATABASE_NAME,
    SingleShotJobError,
    _DEFAULT_WRANGLER,
    _DEFAULT_WRANGLER_CONFIG,
    _REPO_ROOT,
    require_complete_21_only,
)

# Code-keyed tip extracts (index / calendar / JSDA macro datasets excluded).
_CODE_KEYED_TIP_DATASETS: frozenset[str] = frozenset(
    {
        "equities_bars_daily",
        "fins_summary",
        "fins_details",
        "fins_dividend",
        "markets_margin_interest",
        "markets_margin_alert",
        "markets_short_sale_report",
        "equities_investor_types",
    }
)


def _sql_str(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def default_d1_execute(
    sql: str,
    *,
    wrangler: str | Path | None = None,
    config: str | Path | None = None,
    database: str = D1_DATABASE_NAME,
    retries: int = 6,
    timeout_s: int = 240,
) -> list[dict[str, Any]]:
    """Run one SQL command against remote D1 via wrangler (CF hot tip plane)."""
    wr = Path(wrangler) if wrangler else _DEFAULT_WRANGLER
    cfg = Path(config) if config else _DEFAULT_WRANGLER_CONFIG
    if not wr.is_file():
        raise SingleShotJobError(f"wrangler binary not found: {wr}")
    if not cfg.is_file():
        raise SingleShotJobError(f"wrangler config not found: {cfg}")

    last: Exception | None = None
    for attempt in range(retries):
        proc = subprocess.run(
            [
                str(wr),
                "d1",
                "execute",
                database,
                "--remote",
                f"--config={cfg}",
                f"--command={sql}",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(_REPO_ROOT),
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            if isinstance(data, list) and data:
                return list(data[0].get("results") or [])
            if isinstance(data, dict):
                return list(data.get("results") or [])
            return []
        combined = (proc.stderr or "") + (proc.stdout or "")
        if (
            "7403" in combined
            or "network connection was lost" in combined.lower()
            or "D1_ERROR" in combined
        ):
            time.sleep(2.0 * (1.5**attempt))
            last = RuntimeError(combined[-800:])
            continue
        raise SingleShotJobError(
            f"d1 execute failed rc={proc.returncode}: {combined[-1200:]}"
        )
    raise SingleShotJobError(f"d1 execute failed after retries: {last}")


def extract_d1_tip_summaries(
    dataset_ids: Sequence[str],
    *,
    period_start: str,
    period_end: str,
    sample_limit: int = DEFAULT_TIP_SAMPLE_LIMIT,
    d1_execute: D1ExecuteFn | None = None,
    context: str = "single-shot tip extract",
) -> dict[str, Any]:
    """Bounded D1 tip extract: count + min/max event_time + sample keys. Fail-closed."""
    ids = require_complete_21_only(dataset_ids, context=context)
    start = str(period_start).strip()
    end = str(period_end).strip()
    if not start or not end:
        raise SingleShotJobError("period_start and period_end are required")
    limit = max(1, min(int(sample_limit), 200))
    exec_fn = d1_execute or default_d1_execute

    extracts: dict[str, Any] = {}
    for ds in ids:
        jsda_table = _JSDA_TIP_TABLE_BY_DATASET.get(ds)
        if jsda_table is not None:
            # Dedicated JSDA fact table (e.g. jsda_repo_rates). Date grain is
            # as_of_date; event_time is present for PIT ordering.
            count_sql = (
                "SELECT COUNT(*) AS n, "
                "MIN(event_time) AS min_event_time, "
                "MAX(event_time) AS max_event_time "
                f"FROM {jsda_table} WHERE "
                f"as_of_date >= {_sql_str(start)} "
                f"AND as_of_date <= {_sql_str(end)}"
            )
            count_rows = exec_fn(count_sql)
            row0 = count_rows[0] if count_rows else {}
            n = int(row0.get("n") or 0)
            sample_sql = (
                "SELECT source, as_of_date, tenor, rate_type, "
                "event_time, available_at "
                f"FROM {jsda_table} WHERE "
                f"as_of_date >= {_sql_str(start)} "
                f"AND as_of_date <= {_sql_str(end)} "
                "ORDER BY as_of_date, tenor, rate_type "
                f"LIMIT {limit}"
            )
            samples = exec_fn(sample_sql)
            extracts[ds] = {
                "dataset": ds,
                "table": jsda_table,
                "row_count": n,
                "min_event_time": row0.get("min_event_time"),
                "max_event_time": row0.get("max_event_time"),
                "sample_limit": limit,
                "sample_rows": [
                    {
                        "natural_key": (
                            f"{r.get('as_of_date')}|{r.get('tenor')}|"
                            f"{r.get('rate_type')}"
                        ),
                        "event_time": r.get("event_time"),
                        "available_at": r.get("available_at"),
                        "as_of_date": r.get("as_of_date"),
                        "tenor": r.get("tenor"),
                        "rate_type": r.get("rate_type"),
                    }
                    for r in samples
                ],
            }
            continue

        count_sql = (
            "SELECT COUNT(*) AS n, "
            "MIN(event_time) AS min_event_time, "
            "MAX(event_time) AS max_event_time "
            "FROM jquants_records WHERE "
            f"dataset = {_sql_str(ds)} "
            f"AND substr(event_time, 1, 10) >= {_sql_str(start)} "
            f"AND substr(event_time, 1, 10) <= {_sql_str(end)}"
        )
        count_rows = exec_fn(count_sql)
        row0 = count_rows[0] if count_rows else {}
        n = int(row0.get("n") or 0)
        sample_sql = (
            "SELECT natural_key, event_time, available_at "
            "FROM jquants_records WHERE "
            f"dataset = {_sql_str(ds)} "
            f"AND substr(event_time, 1, 10) >= {_sql_str(start)} "
            f"AND substr(event_time, 1, 10) <= {_sql_str(end)} "
            "ORDER BY event_time, natural_key "
            f"LIMIT {limit}"
        )
        samples = exec_fn(sample_sql)
        extracts[ds] = {
            "dataset": ds,
            "row_count": n,
            "min_event_time": row0.get("min_event_time"),
            "max_event_time": row0.get("max_event_time"),
            "sample_limit": limit,
            "sample_rows": [
                {
                    "natural_key": r.get("natural_key"),
                    "event_time": r.get("event_time"),
                    "available_at": r.get("available_at"),
                }
                for r in samples
            ],
        }

    return {
        "source": "cloudflare_d1_remote",
        "d1_database": D1_DATABASE_NAME,
        "plane": "D1_hot_tip",
        "period_start": start,
        "period_end": end,
        "dataset_ids": list(ids),
        "extracts": extracts,
        "note": (
            "Bounded tip extract from remote D1. Not a READY snapshot. "
            "Not full-history SoT (history lives on R2 quant-structured)."
        ),
    }


# ---------------------------------------------------------------------------
# W51 — tip FeatureContext + COMPLETE-21 candidate feature compute
# ---------------------------------------------------------------------------


def _decode_json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            loaded = json.loads(value)
            if isinstance(loaded, dict):
                return loaded
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _pick_num(payload: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        if name not in payload or payload[name] is None or payload[name] == "":
            continue
        try:
            return float(payload[name])
        except (TypeError, ValueError):
            continue
    return None


def _pick_str(payload: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        v = payload.get(name)
        if v is None or v == "":
            continue
        return str(v)
    return None


def _as_of_from_period_end(period_end: str) -> str:
    """Session-close as_of at period_end (JST) for tip feature compute."""
    d = str(period_end).strip()[:10]
    return f"{d}T15:30:00+09:00"


def _available_at_ok(row_available_at: Any, as_of: str) -> bool:
    """PIT gate: available_at must be present and <= as_of (lexicographic ISO)."""
    if row_available_at is None or row_available_at == "":
        return False
    return str(row_available_at) <= str(as_of)


def _normalize_tip_bar_row(
    *,
    payload: Mapping[str, Any],
    event_time: Any,
    available_at: Any,
    natural_key: Any,
) -> dict[str, Any] | None:
    """Map a D1 tip bar payload to curated equity-bar fields (no ingestion import)."""
    code = _pick_str(payload, "Code", "code")
    date = _pick_str(payload, "Date", "date")
    if date is None and event_time is not None:
        date = str(event_time)[:10]
    if code is None and natural_key is not None:
        nk = _decode_json_obj(natural_key)
        code = _pick_str(nk, "Code", "code")
        if date is None:
            date = _pick_str(nk, "Date", "date")
    if not code or not date:
        return None
    return {
        "source": "jquants",
        "code": str(code),
        "date": str(date)[:10],
        "event_time": event_time,
        "available_at": available_at,
        "volume": _pick_num(payload, "Volume", "Vo", "AdjVo", "AVo"),
        "close": _pick_num(payload, "Close", "C", "AdjC", "AC"),
        "open": _pick_num(payload, "Open", "O", "AdjO", "AO"),
        "high": _pick_num(payload, "High", "H", "AdjH", "AH"),
        "low": _pick_num(payload, "Low", "L", "AdjL", "AL"),
        "payload": dict(payload),
        "raw_payload": dict(payload),
    }


def _normalize_tip_calendar_row(
    *,
    payload: Mapping[str, Any],
    event_time: Any,
    available_at: Any,
    natural_key: Any,
) -> dict[str, Any] | None:
    date = _pick_str(payload, "Date", "date")
    if date is None and event_time is not None:
        date = str(event_time)[:10]
    if date is None and natural_key is not None:
        nk = _decode_json_obj(natural_key)
        date = _pick_str(nk, "Date", "date")
    if not date:
        return None
    hol = _pick_str(payload, "HolidayDivision", "HolDiv", "holiday_division")
    return {
        "source": "jquants",
        "date": str(date)[:10],
        "event_time": event_time,
        "available_at": available_at,
        "holiday_division": hol,
        "payload": dict(payload),
        "raw_payload": dict(payload),
    }


def _normalize_tip_catalog_row(
    *,
    dataset: str,
    payload: Mapping[str, Any],
    event_time: Any,
    available_at: Any,
    natural_key: Any,
) -> dict[str, Any]:
    """Generic catalog row shape for get_jquants_records (topix etc.)."""
    return {
        "source": "jquants",
        "dataset": dataset,
        "natural_key": natural_key,
        "event_time": event_time,
        "available_at": available_at,
        "payload": dict(payload),
        "raw_payload": dict(payload),
        # Flatten common fields for pure helpers that inspect row tops.
        "date": _pick_str(payload, "Date", "date", "DiscDate", "PublishedDate")
        or (str(event_time)[:10] if event_time else None),
        "close": _pick_num(payload, "Close", "C", "AdjC", "AC"),
        "volume": _pick_num(payload, "Volume", "Vo", "AdjVo", "AVo"),
        "Code": _pick_str(payload, "Code", "code"),
        "Date": _pick_str(payload, "Date", "date", "DiscDate", "PublishedDate"),
        # S33 sector code for markets_short_ratio (short_ratio_level tip path).
        "S33": _pick_str(payload, "S33", "section"),
        "section": _pick_str(payload, "S33", "section"),
    }


# COMPLETE-21 JSDA datasets live on dedicated D1 fact tables (not jquants_records).
_JSDA_TIP_TABLE_BY_DATASET: dict[str, str] = {
    "jsda_tokyo_repo_rates": "jsda_repo_rates",
}


def _normalize_tip_jsda_repo_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Map a D1 ``jsda_repo_rates`` tip row for FeatureContext.get_jsda_repo_rates."""
    as_of_date = row.get("as_of_date") or row.get("date")
    if as_of_date is None or as_of_date == "":
        return None
    rate = row.get("rate")
    try:
        rate_f = float(rate) if rate is not None and rate != "" else None
    except (TypeError, ValueError):
        rate_f = None
    raw = row.get("raw_payload")
    raw_obj = _decode_json_obj(raw) if raw is not None else {}
    return {
        "source": str(row.get("source") or "jsda"),
        "as_of_date": str(as_of_date)[:10],
        "date": str(as_of_date)[:10],
        "tenor": str(row.get("tenor") or ""),
        "rate_type": str(row.get("rate_type") or ""),
        "rate": rate_f,
        "event_time": row.get("event_time"),
        "available_at": row.get("available_at"),
        "ingested_at": row.get("ingested_at"),
        "raw_payload": raw_obj if raw_obj else raw,
        "payload": {
            "as_of_date": str(as_of_date)[:10],
            "tenor": row.get("tenor"),
            "rate_type": row.get("rate_type"),
            "rate": rate_f,
        },
    }


def _discover_tip_codes(
    d1_execute: D1ExecuteFn,
    *,
    period_start: str,
    period_end: str,
    code_limit: int,
) -> list[str]:
    """Pick tip codes that have multi-day bar history (for 1d features)."""
    # Prefer a small fixed probe set that is known liquid on TSE; fall back to
    # first multi-day codes if those miss in the tip window.
    preferred = ("13010", "72030", "67580", "99840", "83060")
    found: list[str] = []
    for code in preferred:
        # Precompute LIKE pattern: nested f-string backslashes are illegal in 3.11.
        nk_pat = '%"Code":"' + code + '"%'
        sql = (
            "SELECT COUNT(*) AS n FROM jquants_records WHERE "
            f"dataset = {_sql_str('equities_bars_daily')} "
            f"AND substr(event_time, 1, 10) >= {_sql_str(period_start)} "
            f"AND substr(event_time, 1, 10) <= {_sql_str(period_end)} "
            f"AND natural_key LIKE {_sql_str(nk_pat)}"
        )
        rows = d1_execute(sql)
        n = int((rows[0] or {}).get("n") or 0) if rows else 0
        if n >= 2:
            found.append(code)
        if len(found) >= code_limit:
            return found
    if found:
        return found[:code_limit]

    # Fallback: sample natural keys and group by Code in Python.
    sample_sql = (
        "SELECT natural_key FROM jquants_records WHERE "
        f"dataset = {_sql_str('equities_bars_daily')} "
        f"AND substr(event_time, 1, 10) >= {_sql_str(period_start)} "
        f"AND substr(event_time, 1, 10) <= {_sql_str(period_end)} "
        "ORDER BY event_time, natural_key LIMIT 400"
    )
    samples = d1_execute(sample_sql)
    by_code: dict[str, set[str]] = {}
    for row in samples:
        nk = _decode_json_obj(row.get("natural_key"))
        code = _pick_str(nk, "Code", "code")
        date = _pick_str(nk, "Date", "date")
        if not code or not date:
            continue
        by_code.setdefault(str(code), set()).add(str(date)[:10])
    ranked = sorted(
        ((c, len(ds)) for c, ds in by_code.items() if len(ds) >= 2),
        key=lambda x: (-x[1], x[0]),
    )
    return [c for c, _ in ranked[:code_limit]]


def extract_d1_tip_feature_rows(
    dataset_ids: Sequence[str],
    *,
    period_start: str,
    period_end: str,
    codes: Sequence[str] | None = None,
    row_limit_per_dataset: int = DEFAULT_FEATURE_ROW_LIMIT,
    code_limit: int = DEFAULT_FEATURE_CODE_LIMIT,
    d1_execute: D1ExecuteFn | None = None,
    context: str = "single-shot tip feature extract",
) -> dict[str, Any]:
    """Bounded tip payload extract for FeatureContext. Fail-closed on DEFER / non-21."""
    ids = require_complete_21_only(dataset_ids, context=context)
    start = str(period_start).strip()
    end = str(period_end).strip()
    if not start or not end:
        raise SingleShotJobError("period_start and period_end are required")
    limit = max(1, min(int(row_limit_per_dataset), 2000))
    exec_fn = d1_execute or default_d1_execute

    selected_codes: list[str]
    if codes:
        selected_codes = [str(c).strip() for c in codes if str(c).strip()]
    elif "equities_bars_daily" in ids:
        selected_codes = _discover_tip_codes(
            exec_fn, period_start=start, period_end=end, code_limit=code_limit
        )
    else:
        selected_codes = []

    rows_by_dataset: dict[str, list[dict[str, Any]]] = {}
    raw_counts: dict[str, int] = {}

    for ds in ids:
        jsda_table = _JSDA_TIP_TABLE_BY_DATASET.get(ds)
        if jsda_table is not None:
            # Dedicated JSDA fact table (hot tip on D1; not jquants_records).
            count_sql = (
                f"SELECT COUNT(*) AS n FROM {jsda_table} WHERE "
                f"as_of_date >= {_sql_str(start)} "
                f"AND as_of_date <= {_sql_str(end)}"
            )
            count_rows = exec_fn(count_sql)
            raw_counts[ds] = (
                int((count_rows[0] or {}).get("n") or 0) if count_rows else 0
            )
            payload_sql = (
                "SELECT source, as_of_date, tenor, rate_type, event_time, "
                "available_at, ingested_at, rate, raw_payload "
                f"FROM {jsda_table} WHERE "
                f"as_of_date >= {_sql_str(start)} "
                f"AND as_of_date <= {_sql_str(end)} "
                "ORDER BY as_of_date, tenor, rate_type "
                f"LIMIT {limit}"
            )
            raw_rows = exec_fn(payload_sql)
            normalized: list[dict[str, Any]] = []
            for r in raw_rows:
                row = _normalize_tip_jsda_repo_row(r)
                if row is not None:
                    normalized.append(row)
            rows_by_dataset[ds] = normalized
            continue

        count_sql = (
            "SELECT COUNT(*) AS n FROM jquants_records WHERE "
            f"dataset = {_sql_str(ds)} "
            f"AND substr(event_time, 1, 10) >= {_sql_str(start)} "
            f"AND substr(event_time, 1, 10) <= {_sql_str(end)}"
        )
        count_rows = exec_fn(count_sql)
        raw_counts[ds] = int((count_rows[0] or {}).get("n") or 0) if count_rows else 0

        where_extra = ""
        if selected_codes and ds in _CODE_KEYED_TIP_DATASETS:
            # Precompute LIKE patterns (no backslash inside f-string expr on 3.11).
            # Code-filter bars + code-keyed catalog tips (fins / margin / short / …)
            # so LIMIT does not sample other issuers and miss the probe codes.
            like_parts = []
            for c in selected_codes:
                nk_pat = '%"Code":"' + c + '"%'
                like_parts.append(f"natural_key LIKE {_sql_str(nk_pat)}")
            likes = " OR ".join(like_parts)
            where_extra = f" AND ({likes})"

        payload_sql = (
            "SELECT natural_key, event_time, available_at, payload "
            "FROM jquants_records WHERE "
            f"dataset = {_sql_str(ds)} "
            f"AND substr(event_time, 1, 10) >= {_sql_str(start)} "
            f"AND substr(event_time, 1, 10) <= {_sql_str(end)}"
            f"{where_extra} "
            "ORDER BY event_time, natural_key "
            f"LIMIT {limit}"
        )
        raw_rows = exec_fn(payload_sql)
        normalized = []
        for r in raw_rows:
            payload = _decode_json_obj(r.get("payload"))
            if ds == "equities_bars_daily":
                row = _normalize_tip_bar_row(
                    payload=payload,
                    event_time=r.get("event_time"),
                    available_at=r.get("available_at"),
                    natural_key=r.get("natural_key"),
                )
            elif ds == "markets_calendar":
                row = _normalize_tip_calendar_row(
                    payload=payload,
                    event_time=r.get("event_time"),
                    available_at=r.get("available_at"),
                    natural_key=r.get("natural_key"),
                )
            else:
                row = _normalize_tip_catalog_row(
                    dataset=ds,
                    payload=payload,
                    event_time=r.get("event_time"),
                    available_at=r.get("available_at"),
                    natural_key=r.get("natural_key"),
                )
            if row is not None:
                normalized.append(row)
        rows_by_dataset[ds] = normalized

    return {
        "source": "cloudflare_d1_remote",
        "d1_database": D1_DATABASE_NAME,
        "plane": "D1_hot_tip",
        "period_start": start,
        "period_end": end,
        "dataset_ids": list(ids),
        "selected_codes": list(selected_codes),
        "raw_tip_counts": raw_counts,
        "extracted_row_counts": {
            ds: len(rows_by_dataset.get(ds) or []) for ds in ids
        },
        "rows_by_dataset": rows_by_dataset,
        "local_sot": False,
        "note": "Bounded tip payload extract. Not READY. History remains on R2.",
    }


def build_tip_feature_context(
    tip_rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    as_of: str,
    inputs: Mapping[str, Any] | None = None,
    plane: str = "D1_hot_tip",
    source: str = "cloudflare_d1_tip",
    table_prefix: str = "tip",
) -> FeatureContext:
    """Build a FeatureContext whose PIT reads come from in-memory rows.

    Local SQLite is **not** used as SoT. Rows are gated by
    ``available_at <= as_of`` (NULL/empty ``available_at`` excluded).

    ``plane`` / ``source`` / ``table_prefix`` default to the D1 hot-tip
    path. The R2 history bridge reuses this builder with
    ``plane="R2_history"`` / ``source="cloudflare_r2_structured"`` /
    ``table_prefix="r2"`` (see :mod:`research.r2_feature_context`).
    """
    as_of_s = str(as_of).strip()
    if not as_of_s:
        raise SingleShotJobError("as_of is required for tip FeatureContext")
    plane_s = str(plane).strip() or "D1_hot_tip"
    source_s = str(source).strip() or "cloudflare_d1_tip"
    prefix = str(table_prefix).strip() or "tip"

    # Materialize plain dicts once.
    store: dict[str, list[dict[str, Any]]] = {
        str(ds): [dict(r) for r in (rows or [])]
        for ds, rows in tip_rows_by_dataset.items()
    }

    def _pit_reader(resource: str, kwargs: Mapping[str, Any]) -> SimpleNamespace:
        kw = dict(kwargs)
        if resource == "equity_bars_daily":
            rows = list(store.get("equities_bars_daily") or [])
            code = kw.get("code")
            codes = kw.get("codes")
            from_event = kw.get("from_event")
            to_event = kw.get("to_event")
            out: list[dict[str, Any]] = []
            for row in rows:
                if not _available_at_ok(row.get("available_at"), as_of_s):
                    continue
                if code is not None and str(row.get("code")) != str(code):
                    continue
                if codes is not None and str(row.get("code")) not in {
                    str(c) for c in codes
                }:
                    continue
                d = str(row.get("date") or "")[:10]
                if from_event is not None and d < str(from_event)[:10]:
                    continue
                if to_event is not None and d > str(to_event)[:10]:
                    continue
                out.append(row)
            out.sort(key=lambda r: (str(r.get("code") or ""), str(r.get("date") or "")))
            return SimpleNamespace(
                rows=out,
                metadata={
                    "as_of": as_of_s,
                    "table": f"{prefix}_equities_bars_daily",
                    "count": len(out),
                    "source": source_s,
                    "plane": plane_s,
                },
            )

        if resource == "market_calendar":
            rows = list(store.get("markets_calendar") or [])
            from_date = kw.get("from_date")
            to_date = kw.get("to_date")
            out = []
            for row in rows:
                if not _available_at_ok(row.get("available_at"), as_of_s):
                    continue
                d = str(row.get("date") or "")[:10]
                if from_date is not None and d < str(from_date)[:10]:
                    continue
                if to_date is not None and d > str(to_date)[:10]:
                    continue
                out.append(row)
            out.sort(key=lambda r: str(r.get("date") or ""))
            return SimpleNamespace(
                rows=out,
                metadata={
                    "as_of": as_of_s,
                    "table": f"{prefix}_markets_calendar",
                    "count": len(out),
                    "source": source_s,
                    "plane": plane_s,
                },
            )

        if resource == "jquants_records":
            dataset = str(kw.get("dataset") or "")
            rows = list(store.get(dataset) or [])
            code = kw.get("code")
            out = []
            for row in rows:
                if not _available_at_ok(row.get("available_at"), as_of_s):
                    continue
                if code is not None:
                    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                    row_code = (
                        row.get("Code")
                        or row.get("code")
                        or (payload.get("Code") if isinstance(payload, dict) else None)
                        or (payload.get("code") if isinstance(payload, dict) else None)
                    )
                    if row_code is None or str(row_code) != str(code):
                        continue
                out.append(row)
            out.sort(
                key=lambda r: (
                    str(r.get("event_time") or ""),
                    str(r.get("natural_key") or ""),
                )
            )
            return SimpleNamespace(
                rows=out,
                metadata={
                    "as_of": as_of_s,
                    "table": f"{prefix}_jquants_records",
                    "dataset": dataset,
                    "count": len(out),
                    "source": source_s,
                    "plane": plane_s,
                },
            )

        if resource == "equity_master":
            # Permanent DEFER is blocked by FeatureContext before this reader.
            return SimpleNamespace(rows=[], metadata={"as_of": as_of_s, "count": 0})

        if resource == "jsda_repo_rates":
            rows = list(store.get("jsda_tokyo_repo_rates") or [])
            out = [r for r in rows if _available_at_ok(r.get("available_at"), as_of_s)]
            return SimpleNamespace(
                rows=out,
                metadata={
                    "as_of": as_of_s,
                    "table": f"{prefix}_jsda_tokyo_repo_rates",
                    "count": len(out),
                    "source": source_s,
                    "plane": plane_s,
                },
            )

        raise RuntimeError(f"unknown tip FeatureContext resource: {resource!r}")

    return FeatureContext(
        as_of=as_of_s,
        _input_values=MappingProxyType(dict(inputs or {})),
        _pit_reader=_pit_reader,
    )


def _augment_feature_output(
    feature_id: str,
    version: str,
    as_of: str,
    out: FeatureOutput,
    *,
    status: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    md = dict(out.metadata)
    md.update(
        {
            "feature_id": feature_id,
            "feature_version": version,
            "version": version,
            "as_of": as_of,
            "features_runtime_version": FEATURES_RUNTIME_VERSION,
            "status": status if status is not None else get_feature(feature_id).status,
            "plane": "D1_hot_tip",
            "local_sot": False,
            "ready_declared": READY_DECLARED,
        }
    )
    if extra_meta:
        md.update(dict(extra_meta))
    return {
        "feature_id": feature_id,
        "version": version,
        "value": out.value,
        "metadata": md,
    }


_CODE_FEATURE_IDS: frozenset[str] = frozenset(
    {
        "volume_change_1d",
        "topix_relative_1d",
        "disclosure_flag_fins",
        "margin_interest_change_1d",
        "margin_alert_flag",
        "return_1d_c21",
    }
)


def _empty_feature_block(
    fid: str, version: str, status: str, reason: str
) -> dict[str, Any]:
    return {
        "feature_id": fid,
        "version": version,
        "status": status,
        "row_counts": {"computed": 0, "non_null": 0, "null": 0},
        "null_counts": 0,
        "reason": reason,
    }


def _run_feature_targets(
    *,
    fid: str,
    feat: Any,
    version: str,
    as_of_s: str,
    tip_rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    targets: Sequence[Any],
    extra_key: str | None,
    observations: list[dict[str, Any]],
) -> tuple[list[Any], list[dict[str, Any]]]:
    values: list[Any] = []
    feature_obs: list[dict[str, Any]] = []
    for target in targets:
        inputs = {extra_key: target} if extra_key else {}
        ctx = build_tip_feature_context(
            tip_rows_by_dataset, as_of=as_of_s, inputs=inputs
        )
        out = feat.compute(ctx)
        if not isinstance(out, FeatureOutput):
            raise TypeError(
                f"feature {fid!r} returned {type(out).__name__}; "
                "expected FeatureOutput"
            )
        extra = {extra_key: target} if extra_key else None
        rec = _augment_feature_output(
            fid, version, as_of_s, out, status=feat.status, extra_meta=extra
        )
        values.append(rec["value"])
        feature_obs.append(rec)
        observations.append(rec)
    return values, feature_obs


def _discover_tip_sections(
    tip_rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    section_limit: int = DEFAULT_FEATURE_CODE_LIMIT,
) -> list[str]:
    """Discover S33 codes from tip ``markets_short_ratio`` (probe sections first)."""
    short_rows = list(tip_rows_by_dataset.get("markets_short_ratio") or [])
    seen: set[str] = set()
    for row in short_rows:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        s33 = (
            row.get("S33")
            or row.get("section")
            or (payload.get("S33") if isinstance(payload, dict) else None)
            or (payload.get("section") if isinstance(payload, dict) else None)
        )
        if s33 is None or str(s33).strip() == "":
            continue
        seen.add(str(s33).strip())
    if not seen:
        return []
    preferred = ("0050", "1050", "2050", "3050", "3100", "3150", "3200", "3250", "3300")
    ordered: list[str] = [s for s in preferred if s in seen]
    for s in sorted(seen):
        if s not in ordered:
            ordered.append(s)
    return ordered[: max(1, int(section_limit))]


def compute_tip_candidate_features(
    tip_rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    as_of: str,
    feature_ids: Sequence[str] | None = None,
    codes: Sequence[str] | None = None,
    dates: Sequence[str] | None = None,
    sections: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Compute COMPLETE-21 min features on a tip FeatureContext (not local SQLite)."""
    fids = tuple(feature_ids) if feature_ids else DEFAULT_CANDIDATE_FEATURES
    as_of_s = str(as_of).strip()

    bar_rows = list(tip_rows_by_dataset.get("equities_bars_daily") or [])
    if codes:
        code_list = [str(c).strip() for c in codes if str(c).strip()]
    else:
        by_code: dict[str, set[str]] = {}
        for row in bar_rows:
            c = row.get("code")
            d = row.get("date")
            if c and d:
                by_code.setdefault(str(c), set()).add(str(d)[:10])
        ranked = sorted(
            ((c, len(ds)) for c, ds in by_code.items() if len(ds) >= 2),
            key=lambda x: (-x[1], x[0]),
        )
        code_list = [c for c, _ in ranked[:DEFAULT_FEATURE_CODE_LIMIT]]

    cal_rows = list(tip_rows_by_dataset.get("markets_calendar") or [])
    if dates:
        date_list = [str(d)[:10] for d in dates]
    elif cal_rows:
        date_list = sorted({str(r.get("date"))[:10] for r in cal_rows if r.get("date")})
    else:
        date_list = [as_of_s[:10]]

    if sections:
        section_list = [str(s).strip() for s in sections if str(s).strip()]
    else:
        section_list = _discover_tip_sections(tip_rows_by_dataset)

    tip_input_counts = {
        ds: len(list(rows or [])) for ds, rows in tip_rows_by_dataset.items()
    }

    feature_blocks: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []

    for fid in fids:
        feat = get_feature(fid)
        version = str(feat.version)
        reg_status = feat.status
        extra_key: str | None
        targets: Sequence[Any]
        if fid in _CODE_FEATURE_IDS:
            extra_key, targets = "code", code_list
            empty_reason = "no tip codes with multi-day history"
        elif fid == "is_trading_day":
            extra_key, targets = "date", date_list
            empty_reason = ""
        elif fid == "short_ratio_level":
            extra_key, targets = "section", section_list
            empty_reason = (
                "short_ratio_level requires section; no tip S33 "
                "sections discovered and none provided"
            )
        else:
            extra_key, targets, empty_reason = None, [None], ""

        if extra_key is not None and not targets:
            feature_blocks.append(
                _empty_feature_block(fid, version, reg_status, empty_reason)
            )
            continue
        values, feature_obs = _run_feature_targets(
            fid=fid,
            feat=feat,
            version=version,
            as_of_s=as_of_s,
            tip_rows_by_dataset=tip_rows_by_dataset,
            targets=targets,
            extra_key=extra_key,
            observations=observations,
        )

        non_null = sum(1 for v in values if v is not None)
        null_n = sum(1 for v in values if v is None)
        feature_blocks.append(
            {
                "feature_id": fid,
                "version": version,
                "status": reg_status,
                "row_counts": {
                    "computed": len(values),
                    "non_null": non_null,
                    "null": null_n,
                },
                "null_counts": null_n,
                "sample_values": [
                    {
                        "value": o["value"],
                        **{
                            k: o["metadata"].get(k)
                            for k in ("code", "date", "section")
                            if o["metadata"].get(k) is not None
                        },
                    }
                    for o in feature_obs[:10]
                ],
            }
        )

    statuses = {b.get("status") for b in feature_blocks}
    if statuses == {"approved"}:
        path_status = "approved"
    elif "approved" in statuses and "candidate" in statuses:
        path_status = "mixed"
    else:
        path_status = "candidate"

    return {
        "version": "single-shot-features/v1",
        "as_of": as_of_s,
        "feature_ids": list(fids),
        "codes": list(code_list),
        "dates": list(date_list),
        "sections": list(section_list),
        "tip_input_row_counts": tip_input_counts,
        "features": feature_blocks,
        "observations": observations,
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "ready_publication": READY_PUBLICATION_STATUS,
        "local_sot": False,
        "status": path_status,
        "note": "COMPLETE-21 min features on tip FeatureContext. Not READY.",
    }


def discover_tip_trading_days(
    tip_rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[str]:
    """Sorted trading-day dates from tip calendar (HolidayDivision==1), else bar dates."""
    start = str(period_start).strip()[:10] if period_start else None
    end = str(period_end).strip()[:10] if period_end else None
    cal_rows = list(tip_rows_by_dataset.get("markets_calendar") or [])
    days: list[str] = []
    for row in cal_rows:
        d = str(row.get("date") or "")[:10]
        if not d:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue
        hol = row.get("holiday_division")
        if hol is None and isinstance(row.get("payload"), Mapping):
            hol = row["payload"].get("HolidayDivision") or row["payload"].get(
                "holiday_division"
            )
        if str(hol).strip() == "1":
            days.append(d)
    if days:
        return sorted(set(days))

    bar_days: set[str] = set()
    for row in tip_rows_by_dataset.get("equities_bars_daily") or []:
        d = str(row.get("date") or "")[:10]
        if not d:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue
        bar_days.add(d)
    return sorted(bar_days)


def _reexport_on_job() -> None:
    """Copy this module's public tip surface onto ``single_shot_job`` after load."""
    import sys

    job = sys.modules.get("research.single_shot_job")
    if job is None:
        return
    for name in (
        "_as_of_from_period_end",
        "build_tip_feature_context",
        "compute_tip_candidate_features",
        "default_d1_execute",
        "discover_tip_trading_days",
        "extract_d1_tip_feature_rows",
        "extract_d1_tip_summaries",
    ):
        setattr(job, name, globals()[name])


_reexport_on_job()


__all__ = [
    "build_tip_feature_context",
    "compute_tip_candidate_features",
    "default_d1_execute",
    "discover_tip_trading_days",
    "extract_d1_tip_feature_rows",
    "extract_d1_tip_summaries",
]
