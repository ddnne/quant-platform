"""R2 structured history → FeatureContext research bridge.

History SoT = R2 ``quant-structured``. D1 = hot tip only. Disposable SQLite
mirror is never SoT. Permanent DEFER hard-reject. PIT: ``available_at``
required and ``<= as_of``. Mass OFF · READY undeclared.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    reject_permanent_defer_for_history,
)
from features.runtime import FeatureContext
from research.complete21 import (
    COMPLETE_21_DATASETS,
    DEFAULT_FEATURE_DATASETS,
    require_complete_21_only,
)
from research.r2_available_at import (
    AVAILABLE_AT_REPAIR_POLICY,
    available_at_policy_document,
    repair_available_at_research,
)
from research.r2_feature_normalize import normalize_r2_history_row
from research.r2_feature_parse import (
    _decode_json_obj,
    parse_r2_structured_bytes,
    parse_r2_structured_line,
)
from research.r2_io import DEFAULT_WRANGLER, DEFAULT_WRANGLER_CONFIG, REPO_ROOT

HISTORY_SOURCE_R2: str = "r2"
HISTORY_SOURCE_D1_TIP: str = "d1_tip"
HISTORY_SOURCES: frozenset[str] = frozenset({HISTORY_SOURCE_R2, HISTORY_SOURCE_D1_TIP})

R2_HISTORY_BUCKET: str = "quant-structured"
R2_HISTORY_PLANE: str = "R2_history"
R2_HISTORY_SOURCE: str = "cloudflare_r2_structured"
R2_TABLE_PREFIX: str = "r2"

DEFAULT_R2_ROW_LIMIT_PER_DATASET: int = 50_000

S1_SIGNAL_HISTORY_DATASETS: tuple[str, ...] = DEFAULT_FEATURE_DATASETS

MULTI_SIGNAL_HISTORY_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
    "fins_summary",
    "markets_margin_interest",
)

# COMPLETE datasets beyond S1; DEFER remains hard-rejected.
BRIDGE_EXPAND_DATASETS: tuple[str, ...] = (
    "markets_margin_interest",
    "markets_short_ratio",
    "fins_summary",
    "markets_margin_alert",
)

COMPLETE_21_R2_INVENTORY: dict[str, dict[str, Any]] = {
    ds: {
        "jsonl_prefix": f"structured/jsonl/{ds}/",
        "archive_prefix": f"archive/jquants_records/{ds}/",
    }
    for ds in COMPLETE_21_DATASETS
}

PERMANENT_DEFER_R2_NOTE: dict[str, dict[str, Any]] = {
    ds: {"permanent_defer": True} for ds in sorted(PERMANENT_DEFER_DATASETS)
}

_CODE_KEYED_HISTORY_DATASETS: frozenset[str] = frozenset(
    {
        "equities_bars_daily",
        "fins_summary",
        "fins_details",
        "fins_dividend",
        "markets_margin_interest",
        "markets_margin_alert",
        "markets_short_sale_report",
        "equities_investor_types",
        "indices_bars_daily",
        "derivatives_bars_daily_futures",
        "derivatives_bars_daily_options",
        "derivatives_bars_daily_options_225",
        "markets_breakdown",
        "edinet_major_shareholders",
        "edinet_cross_shareholdings",
        "edinet_large_volume_shareholders",
    }
)

R2GetFn = Callable[[str, str], bytes]  # (bucket, key) -> body bytes

class R2FeatureContextError(ValueError):
    """Invalid R2 history bridge input or load failure."""


def _available_at_ok(row_available_at: Any, as_of: str) -> bool:
    """PIT gate: available_at must be present and <= as_of (lexicographic ISO)."""
    if row_available_at is None or row_available_at == "":
        return False
    return str(row_available_at) <= str(as_of)


def _row_event_day(row: Mapping[str, Any]) -> str | None:
    for key in ("date", "Date", "as_of_date"):
        v = row.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()[:10]
    et = row.get("event_time")
    if et is not None and str(et).strip():
        return str(et).strip()[:10]
    return None

def _row_code(row: Mapping[str, Any]) -> str | None:
    for key in ("code", "Code"):
        v = row.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    for key in ("Code", "code"):
        v = payload.get(key) if isinstance(payload, dict) else None
        if v is not None and str(v).strip():
            return str(v).strip()
    nk = _decode_json_obj(row.get("natural_key"))
    for key in ("Code", "code"):
        v = nk.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None

def filter_history_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    period_start: str | None = None,
    period_end: str | None = None,
    codes: Sequence[str] | None = None,
    code_filter: bool = False,
    require_available_at: bool = True,
) -> list[dict[str, Any]]:
    """Filter normalized history rows by window / codes; drop null available_at."""
    start = str(period_start).strip()[:10] if period_start else None
    end = str(period_end).strip()[:10] if period_end else None
    code_set = {str(c).strip() for c in (codes or []) if str(c).strip()} or None
    out: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        if require_available_at:
            aa = row.get("available_at")
            if aa is None or aa == "":
                continue
        day = _row_event_day(row)
        if day is None:
            continue
        if start is not None and day < start:
            continue
        if end is not None and day > end:
            continue
        if code_filter and code_set is not None:
            c = _row_code(row)
            if c is None or c not in code_set:
                continue
        out.append(row)
    return out


def default_r2_get_object(
    bucket: str,
    key: str,
    *,
    wrangler: str | Path | None = None,
    config: str | Path | None = None,
    timeout: int = 300,
) -> bytes:
    """Fetch one R2 object body via ``wrangler r2 object get`` (remote)."""
    wr = Path(wrangler) if wrangler else DEFAULT_WRANGLER
    cfg = Path(config) if config else DEFAULT_WRANGLER_CONFIG
    if not wr.is_file():
        raise R2FeatureContextError(
            f"wrangler binary not found for R2 get: {wr}. "
            "Inject r2_get= or supply local_paths / pre-parsed rows."
        )
    with tempfile.NamedTemporaryFile(
        prefix="r2fc_get_", suffix=".bin", delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [
                str(wr),
                "r2",
                "object",
                "get",
                f"{bucket}/{key}",
                f"--file={tmp_path}",
                "--remote",
                f"--config={cfg}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO_ROOT),
        )
        if proc.returncode != 0:
            combined = (proc.stderr or "") + (proc.stdout or "")
            raise R2FeatureContextError(
                f"r2 get failed for {bucket}/{key} rc={proc.returncode}: "
                f"{combined[-1200:]}"
            )
        return tmp_path.read_bytes()
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

def _load_envelopes_from_sources(
    *,
    dataset: str,
    object_keys: Sequence[str] | None,
    local_paths: Sequence[str | Path] | None,
    raw_lines: Sequence[str | bytes | Mapping[str, Any]] | None,
    r2_get: R2GetFn | None,
    bucket: str,
) -> list[dict[str, Any]]:
    envelopes: list[dict[str, Any]] = []

    if raw_lines is not None:
        for line in raw_lines:
            row = parse_r2_structured_line(line)
            if row is not None and row.get("dataset") == dataset:
                envelopes.append(row)
            elif row is not None and not row.get("dataset"):
                row = dict(row)
                row["dataset"] = dataset
                envelopes.append(row)

    if local_paths is not None:
        for p in local_paths:
            path = Path(p)
            if not path.is_file():
                raise R2FeatureContextError(f"local R2 mirror path not found: {path}")
            envelopes.extend(
                r
                for r in parse_r2_structured_bytes(path.read_bytes())
                if r.get("dataset") == dataset or not r.get("dataset")
            )

    if object_keys:
        get_fn = r2_get or default_r2_get_object
        for key in object_keys:
            body = get_fn(bucket, str(key))
            for r in parse_r2_structured_bytes(body):
                if r.get("dataset") == dataset or not r.get("dataset"):
                    if not r.get("dataset"):
                        r = dict(r)
                        r["dataset"] = dataset
                    envelopes.append(r)

    return envelopes

def extract_r2_history_feature_rows(
    dataset_ids: Sequence[str],
    *,
    period_start: str,
    period_end: str,
    codes: Sequence[str] | None = None,
    object_keys_by_dataset: Mapping[str, Sequence[str]] | None = None,
    local_paths_by_dataset: Mapping[str, Sequence[str | Path]] | None = None,
    raw_lines_by_dataset: Mapping[str, Sequence[str | bytes | Mapping[str, Any]]]
    | None = None,
    r2_get: R2GetFn | None = None,
    bucket: str = R2_HISTORY_BUCKET,
    row_limit_per_dataset: int = DEFAULT_R2_ROW_LIMIT_PER_DATASET,
    allow_empty_datasets: Sequence[str] | None = None,
    apply_available_at_repair: bool = True,
    context: str = "r2 history feature extract",
) -> dict[str, Any]:
    """Load R2 structured history and normalize to FeatureContext row shapes."""
    ids = require_complete_21_only(dataset_ids, context=context)
    reject_permanent_defer_for_history(ids, context=context)

    start = str(period_start).strip()[:10]
    end = str(period_end).strip()[:10]
    if not start or not end:
        raise R2FeatureContextError("period_start and period_end are required")

    selected_codes = [str(c).strip() for c in (codes or []) if str(c).strip()]
    limit = max(1, int(row_limit_per_dataset))
    keys_map = {str(k): list(v) for k, v in (object_keys_by_dataset or {}).items()}
    paths_map = {str(k): list(v) for k, v in (local_paths_by_dataset or {}).items()}
    lines_map = {str(k): list(v) for k, v in (raw_lines_by_dataset or {}).items()}
    empty_ok = {str(x).strip() for x in (allow_empty_datasets or []) if str(x).strip()}

    rows_by_dataset: dict[str, list[dict[str, Any]]] = {}
    raw_counts: dict[str, int] = {}
    source_channels: dict[str, list[str]] = {}
    aa_repairs: dict[str, dict[str, Any]] = {}

    for ds in ids:
        has_keys = bool(keys_map.get(ds))
        has_paths = bool(paths_map.get(ds))
        has_lines = bool(lines_map.get(ds))
        if not (has_keys or has_paths or has_lines):
            if ds in empty_ok:
                source_channels[ds] = ["empty_allowed"]
                raw_counts[ds] = 0
                rows_by_dataset[ds] = []
                aa_repairs[ds] = {"repair_applied": "none", "n_fixed": 0}
                continue
            raise R2FeatureContextError(
                f"{context}: dataset {ds!r} has no R2 input channel "
                "(object_keys / local_paths / raw_lines). "
                "List keys via artifacts-join-plan or supply fixtures."
            )
        channels: list[str] = []
        if has_keys:
            channels.append("r2_object_keys")
        if has_paths:
            channels.append("local_paths_mirror")
        if has_lines:
            channels.append("raw_lines")
        source_channels[ds] = channels

        envelopes = _load_envelopes_from_sources(
            dataset=ds,
            object_keys=keys_map.get(ds),
            local_paths=paths_map.get(ds),
            raw_lines=lines_map.get(ds),
            r2_get=r2_get,
            bucket=bucket,
        )
        raw_counts[ds] = len(envelopes)

        normalized: list[dict[str, Any]] = []
        for env in envelopes:
            if str(env.get("dataset") or ds) != ds:
                continue
            row = normalize_r2_history_row(env, dataset=ds)
            if row is not None:
                normalized.append(row)

        if apply_available_at_repair:
            repaired = repair_available_at_research(
                normalized, dataset=ds, policy="auto"
            )
            normalized = list(repaired["rows"])
            aa_repairs[ds] = {
                k: repaired[k]
                for k in (
                    "n_in",
                    "n_out",
                    "n_fixed",
                    "n_dropped_null_aa",
                    "repair_applied",
                    "policy",
                )
            }
        else:
            aa_repairs[ds] = {"repair_applied": "skipped", "n_fixed": 0}

        code_filter = ds in _CODE_KEYED_HISTORY_DATASETS and bool(selected_codes)
        filtered = filter_history_rows(
            normalized,
            period_start=start,
            period_end=end,
            codes=selected_codes if code_filter else None,
            code_filter=code_filter,
            require_available_at=True,
        )
        filtered.sort(
            key=lambda r: (
                str(_row_event_day(r) or ""),
                str(_row_code(r) or ""),
                str(r.get("natural_key") or ""),
            )
        )
        if len(filtered) > limit:
            filtered = filtered[:limit]
        rows_by_dataset[ds] = filtered

    return {
        "history_source": HISTORY_SOURCE_R2,
        "plane": R2_HISTORY_PLANE,
        "bucket": bucket,
        "selected_codes": list(selected_codes),
        "raw_envelope_counts": raw_counts,
        "extracted_row_counts": {
            ds: len(rows_by_dataset.get(ds) or []) for ds in ids
        },
        "source_channels": source_channels,
        "rows_by_dataset": rows_by_dataset,
        "available_at_repairs": aa_repairs,
        "local_sot": False,
        "disposable_mirror": True,
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
    """Build a FeatureContext whose PIT reads come from in-memory rows."""
    as_of_s = str(as_of).strip()
    if not as_of_s:
        raise R2FeatureContextError("as_of is required for tip FeatureContext")
    plane_s = str(plane).strip() or "D1_hot_tip"
    source_s = str(source).strip() or "cloudflare_d1_tip"
    prefix = str(table_prefix).strip() or "tip"

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


def build_r2_feature_context(
    rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    as_of: str,
    inputs: Mapping[str, Any] | None = None,
) -> FeatureContext:
    """Build FeatureContext from R2 history rows (PIT-gated available_at)."""
    reject_permanent_defer_for_history(
        list(rows_by_dataset.keys()),
        context="build_r2_feature_context",
    )
    return build_tip_feature_context(
        rows_by_dataset,
        as_of=as_of,
        inputs=inputs,
        plane=R2_HISTORY_PLANE,
        source=R2_HISTORY_SOURCE,
        table_prefix=R2_TABLE_PREFIX,
    )

def materialize_disposable_sqlite_mirror(
    rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    db_path: str | Path | None = None,
) -> Path:
    """Write normalized R2 rows into a disposable SQLite table. Never SoT."""
    reject_permanent_defer_for_history(
        list(rows_by_dataset.keys()),
        context="disposable sqlite mirror",
    )
    if db_path is None:
        tmp = tempfile.NamedTemporaryFile(
            prefix="r2fc_mirror_", suffix=".sqlite", delete=False
        )
        path = Path(tmp.name)
        tmp.close()
    else:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()

    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE jquants_records ("
            "source TEXT NOT NULL, dataset TEXT NOT NULL, natural_key TEXT NOT NULL, "
            "event_time TEXT NOT NULL, available_at TEXT NOT NULL, ingested_at TEXT NOT NULL, "
            "payload TEXT, raw_payload TEXT, "
            "PRIMARY KEY (source, dataset, natural_key))"
        )
        conn.execute(
            "CREATE TABLE jquants_daily_bars ("
            "source TEXT NOT NULL, code TEXT NOT NULL, date TEXT NOT NULL, "
            "event_time TEXT NOT NULL, available_at TEXT NOT NULL, ingested_at TEXT NOT NULL, "
            "open REAL, high REAL, low REAL, close REAL, volume REAL, payload TEXT, "
            "PRIMARY KEY (source, code, date))"
        )
        conn.execute(
            "CREATE TABLE jquants_market_calendar ("
            "source TEXT NOT NULL, date TEXT NOT NULL, event_time TEXT NOT NULL, "
            "available_at TEXT NOT NULL, ingested_at TEXT NOT NULL, "
            "holiday_division TEXT, payload TEXT, PRIMARY KEY (source, date))"
        )
        for ds, rows in rows_by_dataset.items():
            for row in rows:
                aa = row.get("available_at")
                if aa is None or aa == "":
                    continue
                et = row.get("event_time") or aa
                ingested = row.get("ingested_at") or aa
                source = str(row.get("source") or "jquants")
                payload = row.get("payload")
                if isinstance(payload, dict):
                    payload_s = json.dumps(payload, ensure_ascii=True)
                elif payload is None:
                    payload_s = None
                else:
                    payload_s = str(payload)
                raw = row.get("raw_payload")
                if isinstance(raw, dict):
                    raw_s = json.dumps(raw, ensure_ascii=True)
                elif raw is None:
                    raw_s = payload_s
                else:
                    raw_s = str(raw)

                if ds == "equities_bars_daily":
                    code = str(row.get("code") or "")
                    d = str(row.get("date") or "")[:10]
                    if not code or not d:
                        continue
                    nk = json.dumps(
                        {"Code": code, "Date": d}, ensure_ascii=True, sort_keys=True
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO jquants_records "
                        "(source, dataset, natural_key, event_time, available_at, "
                        "ingested_at, payload, raw_payload) VALUES (?,?,?,?,?,?,?,?)",
                        (source, ds, nk, str(et), str(aa), str(ingested), payload_s, raw_s),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO jquants_daily_bars "
                        "(source, code, date, event_time, available_at, ingested_at, "
                        "open, high, low, close, volume, payload) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            source,
                            code,
                            d,
                            str(et),
                            str(aa),
                            str(ingested),
                            row.get("open"),
                            row.get("high"),
                            row.get("low"),
                            row.get("close"),
                            row.get("volume"),
                            payload_s,
                        ),
                    )
                elif ds == "markets_calendar":
                    d = str(row.get("date") or "")[:10]
                    if not d:
                        continue
                    nk = json.dumps({"Date": d}, ensure_ascii=True, sort_keys=True)
                    conn.execute(
                        "INSERT OR REPLACE INTO jquants_records "
                        "(source, dataset, natural_key, event_time, available_at, "
                        "ingested_at, payload, raw_payload) VALUES (?,?,?,?,?,?,?,?)",
                        (source, ds, nk, str(et), str(aa), str(ingested), payload_s, raw_s),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO jquants_market_calendar "
                        "(source, date, event_time, available_at, ingested_at, "
                        "holiday_division, payload) VALUES (?,?,?,?,?,?,?)",
                        (
                            source,
                            d,
                            str(et),
                            str(aa),
                            str(ingested),
                            row.get("holiday_division"),
                            payload_s,
                        ),
                    )
                else:
                    nk = row.get("natural_key")
                    if isinstance(nk, dict):
                        nk_s = json.dumps(nk, ensure_ascii=True, sort_keys=True)
                    elif nk is None or nk == "":
                        d = _row_event_day(row) or "0000-01-01"
                        c = _row_code(row)
                        nk_obj = {"Date": d}
                        if c:
                            nk_obj["Code"] = c
                        nk_s = json.dumps(nk_obj, ensure_ascii=True, sort_keys=True)
                    else:
                        nk_s = str(nk)
                    conn.execute(
                        "INSERT OR REPLACE INTO jquants_records "
                        "(source, dataset, natural_key, event_time, available_at, "
                        "ingested_at, payload, raw_payload) VALUES (?,?,?,?,?,?,?,?)",
                        (source, ds, nk_s, str(et), str(aa), str(ingested), payload_s, raw_s),
                    )
        conn.commit()
    finally:
        conn.close()
    return path

def r2_inventory_document() -> dict[str, Any]:
    """COMPLETE 21 inventory + DEFER exclude."""
    return {
        "complete_21_count": len(COMPLETE_21_DATASETS),
        "complete_21": COMPLETE_21_R2_INVENTORY,
        "permanent_defer_count": len(PERMANENT_DEFER_DATASETS),
        "permanent_defer_excluded": PERMANENT_DEFER_R2_NOTE,
        "bridge_expand_datasets": list(BRIDGE_EXPAND_DATASETS),
        "local_sot": False,
    }

def write_r2_inventory_json(path: str | Path) -> Path:
    """Write inventory JSON to ``path``."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = r2_inventory_document()
    out.write_text(
        json.dumps(doc, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out

def schema_mapping_document() -> dict[str, Any]:
    """R2 envelope → FeatureContext field map."""
    return {
        "pit_gate": {
            "null_available_at": "excluded (hard)",
        },
        "s1_column_map": {
            "equities_bars_daily": {},
            "indices_bars_daily_topix": {},
            "markets_calendar": {},
        },
        "bridge_expand_column_map": {ds: {} for ds in BRIDGE_EXPAND_DATASETS},
    }

def can_build_40d_asof(
    rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    *,
    min_trading_days: int = 40,
) -> dict[str, Any]:
    """Whether supplied history rows can support a ~40 trading-day as_of window."""
    if rows_by_dataset is None:
        return {"can_build_40d_asof": True, "code_path": True}
    bar_days = sorted(
        {
            str(r.get("date") or "")[:10]
            for r in (rows_by_dataset.get("equities_bars_daily") or [])
            if r.get("date") and r.get("available_at")
        }
    )
    topix_days = sorted(
        {
            str(_row_event_day(r) or "")
            for r in (rows_by_dataset.get("indices_bars_daily_topix") or [])
            if _row_event_day(r) and r.get("available_at")
        }
    )
    n = len(bar_days)
    ok = n >= int(min_trading_days) and len(topix_days) >= 2
    return {
        "can_build_40d_asof": ok,
        "code_path": True,
        "equities_bars_trading_days": n,
    }

def resolve_history_source(value: str | None) -> str:
    """Normalize history_source token; default d1_tip."""
    if value is None or str(value).strip() == "":
        return HISTORY_SOURCE_D1_TIP
    v = str(value).strip().lower()
    if v in ("r2", "r2_history", "cloudflare_r2", "structured_r2"):
        return HISTORY_SOURCE_R2
    if v in ("d1_tip", "d1", "tip", "cloudflare_d1_tip"):
        return HISTORY_SOURCE_D1_TIP
    raise R2FeatureContextError(
        f"unknown history_source={value!r}; expected one of "
        f"{sorted(HISTORY_SOURCES)}"
    )

__all__ = [
    "COMPLETE_21_R2_INVENTORY",
    "DEFAULT_R2_ROW_LIMIT_PER_DATASET",
    "HISTORY_SOURCE_D1_TIP",
    "HISTORY_SOURCE_R2",
    "HISTORY_SOURCES",
    "PERMANENT_DEFER_R2_NOTE",
    "R2GetFn",
    "R2FeatureContextError",
    "R2_HISTORY_BUCKET",
    "R2_HISTORY_PLANE",
    "R2_HISTORY_SOURCE",
    "R2_TABLE_PREFIX",
    "AVAILABLE_AT_REPAIR_POLICY",
    "BRIDGE_EXPAND_DATASETS",
    "MULTI_SIGNAL_HISTORY_DATASETS",
    "S1_SIGNAL_HISTORY_DATASETS",
    "available_at_policy_document",
    "build_r2_feature_context",
    "can_build_40d_asof",
    "default_r2_get_object",
    "extract_r2_history_feature_rows",
    "filter_history_rows",
    "materialize_disposable_sqlite_mirror",
    "normalize_r2_history_row",
    "parse_r2_structured_bytes",
    "parse_r2_structured_line",
    "r2_inventory_document",
    "repair_available_at_research",
    "resolve_history_source",
    "schema_mapping_document",
    "write_r2_inventory_json",
]
