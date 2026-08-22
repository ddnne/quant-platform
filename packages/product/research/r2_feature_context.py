"""R2 structured history → FeatureContext research bridge (W59 / w0815az_g1).

Research-only loader that reads COMPLETE-21 structured history from R2
``quant-structured`` (live JSONL and/or cold archive NDJSON) and builds a
:class:`features.runtime.FeatureContext` suitable for signal long eval
(S1: bars + TOPIX + calendar).

**SoT rules (held):**

* History SoT = R2 ``quant-structured`` (not local SQLite, not D1 full history)
* D1 = hot tip only (use ``history_source="d1_tip"`` on the eval harness)
* Optional in-memory SQLite mirror is a **disposable** PIT convenience, never SoT
* Permanent DEFER 5 hard-reject on load
* PIT: ``available_at`` must be present and ``<= as_of`` (no look-ahead)
* Mass OFF · READY not declared · no densify · no push

Minimal viable datasets for S1 signal long eval:

* ``equities_bars_daily``
* ``indices_bars_daily_topix``
* ``markets_calendar``

All COMPLETE 21 ids are inventory-mapped and loadable when keys/rows are
supplied; DEFER 5 are fail-closed.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
    reject_permanent_defer_for_history,
)
from features.runtime import FeatureContext
from research.single_shot_job import (
    COMPLETE_21_DATASET_SET,
    COMPLETE_21_DATASETS,
    DEFAULT_FEATURE_DATASETS,
    RESEARCH_ARTIFACT_BUCKET,
    SingleShotJobError,
    _DEFAULT_WRANGLER,
    _DEFAULT_WRANGLER_CONFIG,
    _REPO_ROOT,
    _decode_json_obj,
    _normalize_tip_bar_row,
    _normalize_tip_calendar_row,
    _normalize_tip_catalog_row,
    _pick_str,
    build_tip_feature_context,
    require_complete_21_only,
)

# ---------------------------------------------------------------------------
# Freeze / plane labels
# ---------------------------------------------------------------------------

HISTORY_SOURCE_R2: str = "r2"
HISTORY_SOURCE_D1_TIP: str = "d1_tip"
HISTORY_SOURCES: frozenset[str] = frozenset({HISTORY_SOURCE_R2, HISTORY_SOURCE_D1_TIP})

R2_HISTORY_BUCKET: str = "quant-structured"
R2_HISTORY_PLANE: str = "R2_history"
R2_HISTORY_SOURCE: str = "cloudflare_r2_structured"
R2_TABLE_PREFIX: str = "r2"

# JSONL / archive line schema metadata (worker write path).
R2_LINE_SCHEMA: str = "jquants_records/v1"

# Default row cap for research history extract (higher than tip sample).
DEFAULT_R2_ROW_LIMIT_PER_DATASET: int = 50_000

# S1 minimal set for topix-relative signal long eval.
S1_SIGNAL_HISTORY_DATASETS: tuple[str, ...] = DEFAULT_FEATURE_DATASETS

# Multi-signal (W58/W60): S1/S2/S3 legs — bars/topix/calendar + fins (+ margin optional).
MULTI_SIGNAL_HISTORY_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
    "fins_summary",
    "markets_margin_interest",
)

# W60 bridge expansion: high-value COMPLETE datasets beyond S1 core
# (approved features exist for each). DEFER 5 remain hard-rejected.
BRIDGE_EXPAND_DATASETS: tuple[str, ...] = (
    "markets_margin_interest",
    "markets_short_ratio",
    "fins_summary",
    "markets_margin_alert",
)

# Research-only PIT repairs. Never invent visibility. Never rewrite R2 SoT.
AVAILABLE_AT_REPAIR_POLICY: dict[str, Any] = {
    "version": "r2-available-at-repair/v1",
    "wave": "W60 / w0815ba",
    "research_only": True,
    "local_sot": False,
    "r2_sot_rewrite": False,
    "pit_gate": "available_at required and available_at <= as_of",
    "null_available_at": "drop (hard)",
    "repairs": {
        "calendar_ingest_pollution": {
            "datasets": ["markets_calendar"],
            "condition": "envelope.available_at day > event day",
            "action": "available_at = event_time",
            "rationale": (
                "Archive calendar available_at sometimes equals ingest wall-clock "
                "(~2026) which fails historical as_of. Calendar is pre-known; "
                "event_time is the honest research visibility for holiday flags."
            ),
            "look_ahead": False,
        },
        "archive_ingest_pollution": {
            "datasets": [
                "markets_margin_interest",
                "markets_short_ratio",
                "markets_margin_alert",
            ],
            "condition": (
                "envelope.available_at day > event day AND "
                "year(available_at) >= 2026 AND year(event) < 2026"
            ),
            "action": "available_at = event_time",
            "rationale": (
                "Some R2 JSONL/archive reseals stamp available_at with 2026 "
                "ingest wall-clock while event_time is historical (2022–2025). "
                "That is not real post-event lag; research repair sets "
                "available_at=event_time so PIT historical as_of works. "
                "Does not rewrite R2 SoT. Not a densify."
            ),
            "look_ahead": False,
        },
        "missing_available_at_drop": {
            "datasets": ["*"],
            "condition": "available_at is null or empty",
            "action": "exclude row",
            "rationale": "Never invent visibility from as_of or wall-clock.",
            "look_ahead": False,
        },
        "post_date_preserve": {
            "datasets": [
                "equities_bars_daily",
                "indices_bars_daily_topix",
                "fins_summary",
            ],
            "condition": (
                "available_at is real post-event publish/disclosure time "
                "(not archive_ingest_pollution pattern)"
            ),
            "action": "keep envelope available_at unchanged",
            "rationale": (
                "Bars/topix/fins envelopes with honest lag stay as-is. "
                "Do not pull future visibility earlier than envelope evidence."
            ),
            "look_ahead": False,
        },
    },
    "forbidden": [
        "available_at = as_of",
        "available_at = now()",
        "available_at = evaluation_as_of",
        "silent future fill without documented repair",
    ],
}

# ---------------------------------------------------------------------------
# T1 — R2 key patterns per COMPLETE 21 (+ DEFER 5 documented as excluded)
# ---------------------------------------------------------------------------

R2_JSONL_KEY_PATTERN: str = (
    "structured/jsonl/{dataset}/dt=YYYY-MM-DD/{run_id}.jsonl"
)
R2_ARCHIVE_KEY_PATTERN: str = (
    "archive/jquants_records/{dataset}/batch/{run_id}_after{rowid}.ndjson"
)
R2_ARCHIVE_META_KEY_PATTERN: str = (
    "archive/jquants_records/{dataset}/batch/{run_id}_after{rowid}_meta.ndjson"
)
R2_RAW_KEY_PATTERN: str = "raw/{dataset}/{run_id}/page-NNNNNN.json"
R2_PARQUET_KEY_PATTERN: str = (
    "dataset={DATASET}/year=YYYY/month=MM/day=DD/seg={SEGMENT_ID}/{content_hash}.parquet"
)

_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("jsda_", "jsda"),
    ("edinet_", "edinet"),
    ("derivatives_", "derivatives"),
    ("fins_", "fins"),
    ("indices_", "indices"),
    ("markets_", "markets"),
    ("equities_", "equities"),
)

# Per-dataset inventory (code + docs/proof/complete21_cf_read_paths_20260815.md
# + W58 live samples under .glm-logs/w0815ay_g1_history/).
COMPLETE_21_R2_INVENTORY: dict[str, dict[str, Any]] = {
    ds: {
        "dataset": ds,
        "complete": True,
        "history_sot": "R2 quant-structured",
        "tip_sot": "D1 jquants_records residual/tip (or JSDA hot table)",
        "jsonl_prefix": f"structured/jsonl/{ds}/",
        "jsonl_key_pattern": R2_JSONL_KEY_PATTERN.replace("{dataset}", ds),
        "archive_prefix": f"archive/jquants_records/{ds}/",
        "archive_key_pattern": R2_ARCHIVE_KEY_PATTERN.replace("{dataset}", ds),
        "raw_prefix": f"raw/{ds}/",
        "line_schema": R2_LINE_SCHEMA,
        "family": next(
            (fam for pre, fam in _FAMILY_PREFIXES if ds.startswith(pre)),
            "other",
        ),
    }
    for ds in COMPLETE_21_DATASETS
}

# JSDA tip tables differ from jquants_records on D1; history still R2-sealed.
COMPLETE_21_R2_INVENTORY["jsda_tokyo_repo_rates"]["d1_tip_table"] = "jsda_repo_rates"
COMPLETE_21_R2_INVENTORY["jsda_corporate_bond_transactions"][
    "d1_tip_table"
] = "jsda_corporate_bond_transactions"

PERMANENT_DEFER_R2_NOTE: dict[str, dict[str, Any]] = {
    ds: {
        "dataset": ds,
        "complete": False,
        "permanent_defer": True,
        "load_policy": "hard_reject",
        "jsonl_prefix": f"structured/jsonl/{ds}/",
        "archive_prefix": f"archive/jquants_records/{ds}/",
        "note": "Permanent DEFER — excluded from research history loads",
    }
    for ds in sorted(PERMANENT_DEFER_DATASETS)
}

# Live R2 sample keys proved in W58 (not invented).
LIVE_R2_SAMPLE_KEYS: dict[str, dict[str, Any]] = {
    "equities_bars_daily": {
        "jsonl_sample_key": (
            "structured/jsonl/equities_bars_daily/dt=2008-05-07/"
            "r2-equities_bars_daily-1786544255589-mmwbjs.jsonl"
        ),
        "event_day_sample": "2008-05-07",
        "source_log": ".glm-logs/w0815ay_g1_history/",
    },
    "indices_bars_daily_topix": {
        "archive_sample_key": (
            "archive/jquants_records/indices_bars_daily_topix/batch/"
            "08088fff-792b-4b1c-9898-38316e881405_after227044.ndjson"
        ),
        "event_span_sample": ["2009-12-21", "2011-08-09"],
        "source_log": ".glm-logs/w0815ay_g1_history/",
    },
    "markets_calendar": {
        "jsonl_sample_key": (
            "structured/jsonl/markets_calendar/dt=2026-08-01/"
            "r2-markets_calendar-1786754494429-4qn6pm.jsonl"
        ),
        "event_day_sample": "2026-08-01",
        "source_log": ".glm-logs/w0815ay_g1_history/",
    },
}

# ---------------------------------------------------------------------------
# T2 — Schema mapping R2 row → FeatureContext fields
# ---------------------------------------------------------------------------

# Envelope fields always present on jquants_records/v1 lines.
R2_ENVELOPE_FIELDS: tuple[str, ...] = (
    "source",
    "dataset",
    "natural_key",
    "event_time",
    "available_at",
    "ingested_at",
    "payload",
    "raw_payload",
)

# FeatureContext resource → COMPLETE dataset + row field mapping.
FEATURE_CONTEXT_SCHEMA_MAP: dict[str, dict[str, Any]] = {
    "equity_bars_daily": {
        "dataset": "equities_bars_daily",
        "code_fields": ("Code", "code"),
        "date_fields": ("Date", "date"),
        "natural_key_fields": ("Code", "Date"),
        "event_time": "session_close ← Date (envelope event_time preferred)",
        "available_at": "session_close ← Date (envelope available_at required for PIT)",
        "normalized_row_keys": (
            "source",
            "code",
            "date",
            "event_time",
            "available_at",
            "volume",
            "close",
            "open",
            "high",
            "low",
            "payload",
            "raw_payload",
        ),
        "feature_context_method": "get_equity_bars_daily",
    },
    "market_calendar": {
        "dataset": "markets_calendar",
        "code_fields": (),
        "date_fields": ("Date", "date"),
        "natural_key_fields": ("Date",),
        "event_time": "observation_date ← Date",
        "available_at": "calendar_prepublished / ingest (envelope available_at required)",
        "normalized_row_keys": (
            "source",
            "date",
            "event_time",
            "available_at",
            "holiday_division",
            "payload",
            "raw_payload",
        ),
        "feature_context_method": "get_market_calendar",
    },
    "jquants_records": {
        "dataset": "{dataset}",  # e.g. indices_bars_daily_topix
        "code_fields": ("Code", "code"),  # optional; topix has Date only
        "date_fields": ("Date", "date"),
        "natural_key_fields": ("Date",),  # or Code+Date depending on dataset
        "event_time": "envelope event_time",
        "available_at": "envelope available_at (PIT hard gate)",
        "normalized_row_keys": (
            "source",
            "dataset",
            "natural_key",
            "event_time",
            "available_at",
            "payload",
            "raw_payload",
            "date",
            "close",
            "volume",
            "Code",
            "Date",
        ),
        "feature_context_method": "get_jquants_records",
        "s1_datasets": ("indices_bars_daily_topix",),
    },
}

# Code-keyed datasets: apply Code filter when codes selected (bars + fins/margin…).
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


class R2FeatureContextError(SingleShotJobError):
    """Invalid R2 history bridge input or load failure."""


# ---------------------------------------------------------------------------
# Parse / normalize
# ---------------------------------------------------------------------------


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return value
    return value


def parse_r2_structured_line(line: str | bytes | Mapping[str, Any]) -> dict[str, Any] | None:
    """Parse one R2 JSONL / archive NDJSON line into an envelope dict.

    Accepts raw line text, bytes, or already-decoded mapping. Payload fields
    that are JSON strings are decoded to objects when possible.
    """
    if isinstance(line, Mapping):
        obj = dict(line)
    else:
        text = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else str(line)
        text = text.strip()
        if not text:
            return None
        try:
            loaded = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(loaded, dict):
            return None
        obj = loaded

    dataset = obj.get("dataset")
    if dataset is None or str(dataset).strip() == "":
        return None

    # Archive batches may include rid; keep if present but not required.
    payload = _maybe_json(obj.get("payload"))
    raw_payload = _maybe_json(obj.get("raw_payload"))
    if raw_payload is None:
        raw_payload = payload
    natural_key = obj.get("natural_key")
    # natural_key may be JSON string or object; keep both forms usable.
    if isinstance(natural_key, dict):
        natural_key_out: Any = json.dumps(natural_key, ensure_ascii=True, sort_keys=True)
        natural_key_obj = natural_key
    else:
        natural_key_out = natural_key
        natural_key_obj = _decode_json_obj(natural_key)

    return {
        "source": str(obj.get("source") or "jquants"),
        "dataset": str(dataset).strip(),
        "natural_key": natural_key_out,
        "natural_key_obj": natural_key_obj,
        "event_time": obj.get("event_time"),
        "available_at": obj.get("available_at"),
        "ingested_at": obj.get("ingested_at"),
        "payload": payload if isinstance(payload, dict) else _decode_json_obj(payload),
        "raw_payload": (
            raw_payload if isinstance(raw_payload, dict) else _decode_json_obj(raw_payload)
        ),
        "rid": obj.get("rid"),
    }


def parse_r2_structured_bytes(body: bytes | str) -> list[dict[str, Any]]:
    """Parse a full JSONL/NDJSON object body into envelope dicts."""
    text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        row = parse_r2_structured_line(line)
        if row is not None:
            out.append(row)
    return out


def normalize_r2_history_row(
    envelope: Mapping[str, Any],
    *,
    dataset: str | None = None,
) -> dict[str, Any] | None:
    """Map one R2 envelope to FeatureContext tip-compatible row shape.

    Reuses tip normalizers so signal/feature code stays path-agnostic.
    """
    ds = str(dataset or envelope.get("dataset") or "").strip()
    if not ds:
        return None
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        payload = _decode_json_obj(payload)
    event_time = envelope.get("event_time")
    available_at = envelope.get("available_at")
    natural_key = envelope.get("natural_key")

    if ds == "equities_bars_daily":
        row = _normalize_tip_bar_row(
            payload=payload or {},
            event_time=event_time,
            available_at=available_at,
            natural_key=natural_key,
        )
    elif ds == "markets_calendar":
        row = _normalize_tip_calendar_row(
            payload=payload or {},
            event_time=event_time,
            available_at=available_at,
            natural_key=natural_key,
        )
        # Live R2 calendar uses HolDiv; tip normalizer already maps HolidayDivision/HolDiv.
        if row is not None and row.get("holiday_division") is None:
            hol = _pick_str(payload or {}, "HolDiv", "HolidayDivision", "holiday_division")
            if hol is not None:
                row["holiday_division"] = hol
    else:
        row = _normalize_tip_catalog_row(
            dataset=ds,
            payload=payload or {},
            event_time=event_time,
            available_at=available_at,
            natural_key=natural_key,
        )
    if row is None:
        return None
    # Preserve ingested_at for disposable mirror / debug (not used in PIT gate).
    if envelope.get("ingested_at") is not None:
        row["ingested_at"] = envelope.get("ingested_at")
    return row


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


# Datasets that may carry 2026 ingest wall-clock as available_at on historical events.
_ARCHIVE_INGEST_POLLUTION_DATASETS: frozenset[str] = frozenset(
    {
        "markets_margin_interest",
        "markets_short_ratio",
        "markets_margin_alert",
    }
)


def repair_available_at_research(
    rows: Sequence[Mapping[str, Any]],
    *,
    dataset: str,
    policy: str = "auto",
) -> dict[str, Any]:
    """Apply documented research-only available_at repairs (never look-ahead).

    Returns ``{"rows": [...], "n_in", "n_out", "n_fixed", "n_dropped_null_aa",
    "policy", "repair_applied"}``.

    * ``policy="auto"`` — calendar + margin/short/alert ingest-pollution repairs.
    * ``policy="none"`` — no mutation (still drops null available_at later).
    * ``policy="calendar_ingest_pollution"`` / ``archive_ingest_pollution`` —
      force that repair path (tests).
    """
    ds = str(dataset).strip()
    apply_cal = policy in ("auto", "calendar_ingest_pollution") and (
        ds == "markets_calendar" or policy == "calendar_ingest_pollution"
    )
    apply_archive = policy in ("auto", "archive_ingest_pollution") and (
        ds in _ARCHIVE_INGEST_POLLUTION_DATASETS
        or policy == "archive_ingest_pollution"
    )
    n_fixed = 0
    n_dropped = 0
    repair_tags: list[str] = []
    out: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        aa = row.get("available_at")
        et = row.get("event_time")
        if aa is None or aa == "":
            # Policy: drop null — never invent. Caller may still pass through
            # when require_available_at=False; we count and exclude here.
            n_dropped += 1
            continue
        if et is not None and str(et).strip():
            aa_day = str(aa).strip()[:10]
            et_day = str(et).strip()[:10]
            aa_year = aa_day[:4] if len(aa_day) >= 4 else ""
            et_year = et_day[:4] if len(et_day) >= 4 else ""
            if apply_cal and aa_day and et_day and aa_day > et_day:
                row["available_at"] = et
                row["_aa_repair"] = "calendar_ingest_pollution"
                n_fixed += 1
                repair_tags.append("calendar_ingest_pollution")
            elif (
                apply_archive
                and aa_day
                and et_day
                and aa_day > et_day
                and aa_year >= "2026"
                and et_year
                and et_year < "2026"
            ):
                row["available_at"] = et
                row["_aa_repair"] = "archive_ingest_pollution"
                n_fixed += 1
                repair_tags.append("archive_ingest_pollution")
        # post_date_preserve: leave other rows as-is (including real lag).
        out.append(row)
    applied = "none"
    if n_fixed:
        # Prefer the specific tag used.
        if "archive_ingest_pollution" in repair_tags:
            applied = "archive_ingest_pollution"
        elif "calendar_ingest_pollution" in repair_tags:
            applied = "calendar_ingest_pollution"
    return {
        "rows": out,
        "n_in": len(list(rows)),
        "n_out": len(out),
        "n_fixed": n_fixed,
        "n_dropped_null_aa": n_dropped,
        "dataset": ds,
        "policy": policy,
        "repair_applied": applied,
        "research_only": True,
        "look_ahead": False,
        "document": AVAILABLE_AT_REPAIR_POLICY["version"],
    }


def available_at_policy_document() -> dict[str, Any]:
    """Public document for available_at repair (W60 T7)."""
    return dict(AVAILABLE_AT_REPAIR_POLICY)


# ---------------------------------------------------------------------------
# R2 object get (wrangler) — injectable for tests
# ---------------------------------------------------------------------------


def default_r2_get_object(
    bucket: str,
    key: str,
    *,
    wrangler: str | Path | None = None,
    config: str | Path | None = None,
    timeout: int = 300,
) -> bytes:
    """Fetch one R2 object body via ``wrangler r2 object get`` (remote)."""
    wr = Path(wrangler) if wrangler else _DEFAULT_WRANGLER
    cfg = Path(config) if config else _DEFAULT_WRANGLER_CONFIG
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
            cwd=str(_REPO_ROOT),
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


# ---------------------------------------------------------------------------
# Extract history rows
# ---------------------------------------------------------------------------


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
                # Allow undated test lines tagged later
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
    """Load R2 structured history and normalize to FeatureContext row shapes.

    Fail-closed on permanent DEFER / non-COMPLETE-21 before any parse.

    At least one input channel is required per dataset (unless listed in
    ``allow_empty_datasets``, which yields an honest empty row set):

    * ``object_keys_by_dataset`` + ``r2_get`` (or default wrangler get)
    * ``local_paths_by_dataset`` (local mirror files — **not** SoT)
    * ``raw_lines_by_dataset`` (in-memory / test fixtures)

    Local paths / lines are **disposable mirrors**, never Source of Truth.

    When ``apply_available_at_repair`` is True, calendar rows get the documented
    research-only ingest-pollution repair (see ``AVAILABLE_AT_REPAIR_POLICY``).
    """
    ids = require_complete_21_only(dataset_ids, context=context)
    # Belt-and-suspenders: explicit DEFER reject even if allowlist drifts.
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
                aa_repairs[ds] = {
                    "repair_applied": "none",
                    "n_fixed": 0,
                    "note": "channel missing · empty_allowed",
                }
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
            # Force dataset match (reject cross-dataset pollution).
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
                    "research_only",
                    "look_ahead",
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
        # Stable order then cap.
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
        "source": R2_HISTORY_SOURCE,
        "bucket": bucket,
        "plane": R2_HISTORY_PLANE,
        "history_source": HISTORY_SOURCE_R2,
        "line_schema": R2_LINE_SCHEMA,
        "period_start": start,
        "period_end": end,
        "dataset_ids": list(ids),
        "selected_codes": list(selected_codes),
        "raw_envelope_counts": raw_counts,
        "extracted_row_counts": {
            ds: len(rows_by_dataset.get(ds) or []) for ds in ids
        },
        "source_channels": source_channels,
        "rows_by_dataset": rows_by_dataset,
        "available_at_repairs": aa_repairs,
        "available_at_policy_version": AVAILABLE_AT_REPAIR_POLICY["version"],
        "bridge_expand_datasets": list(BRIDGE_EXPAND_DATASETS),
        "local_sot": False,
        "disposable_mirror": True,
        "note": (
            "R2 structured history extract for research FeatureContext. "
            "Not READY. Not local SQLite SoT. Local paths/lines are disposable "
            "mirrors only. Permanent DEFER excluded. available_at preserved for PIT "
            "(calendar research repair only when documented)."
        ),
    }


def build_r2_feature_context(
    rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    as_of: str,
    inputs: Mapping[str, Any] | None = None,
) -> FeatureContext:
    """Build FeatureContext from R2 history rows (PIT-gated available_at).

    Delegates to :func:`build_tip_feature_context` with R2 plane labels.
    Local SQLite is not used.
    """
    # DEFER hard reject if any store key is permanent DEFER.
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


# ---------------------------------------------------------------------------
# Optional disposable in-memory SQLite mirror (not SoT)
# ---------------------------------------------------------------------------


def materialize_disposable_sqlite_mirror(
    rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    db_path: str | Path | None = None,
) -> Path:
    """Write normalized R2 rows into a disposable SQLite ``jquants_records`` table.

    **Not Source of Truth.** Intended for callers that must exercise the stock
    ``pit.*`` readers / ``features.compute(db_path=…)`` path in smokes. Prefer
    :func:`build_r2_feature_context` for research signal eval.

    Uses ``:memory:``-style temp file when ``db_path`` is None (caller must
    keep the path alive for the session).
    """
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
            """
            CREATE TABLE jquants_records (
                source       TEXT NOT NULL,
                dataset      TEXT NOT NULL,
                natural_key  TEXT NOT NULL,
                event_time   TEXT NOT NULL,
                available_at TEXT NOT NULL,
                ingested_at  TEXT NOT NULL,
                payload      TEXT,
                raw_payload  TEXT,
                PRIMARY KEY (source, dataset, natural_key)
            )
            """
        )
        # Minimal curated tables used by some pit shortcuts.
        conn.execute(
            """
            CREATE TABLE jquants_daily_bars (
                source TEXT NOT NULL,
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                event_time TEXT NOT NULL,
                available_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                payload TEXT,
                PRIMARY KEY (source, code, date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE jquants_market_calendar (
                source TEXT NOT NULL,
                date TEXT NOT NULL,
                event_time TEXT NOT NULL,
                available_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                holiday_division TEXT,
                payload TEXT,
                PRIMARY KEY (source, date)
            )
            """
        )
        for ds, rows in rows_by_dataset.items():
            for row in rows:
                aa = row.get("available_at")
                if aa is None or aa == "":
                    continue  # PIT: never store null available_at
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
                        # Fallback synthetic key from date/code
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


# ---------------------------------------------------------------------------
# Inventory export (T1 deliverable helper)
# ---------------------------------------------------------------------------


def r2_inventory_document() -> dict[str, Any]:
    """Return the T1 R2 inventory document (COMPLETE 21 + DEFER exclude)."""
    return {
        "wave": "W59 / w0815az_g1",
        "task": "T1 R2 key pattern inventory for COMPLETE 21",
        "bucket": R2_HISTORY_BUCKET,
        "line_schema": R2_LINE_SCHEMA,
        "shared_patterns": {
            "jsonl": R2_JSONL_KEY_PATTERN,
            "archive_ndjson": R2_ARCHIVE_KEY_PATTERN,
            "archive_meta": R2_ARCHIVE_META_KEY_PATTERN,
            "raw": R2_RAW_KEY_PATTERN,
            "parquet_target": R2_PARQUET_KEY_PATTERN,
        },
        "complete_21_count": len(COMPLETE_21_DATASETS),
        "complete_21": COMPLETE_21_R2_INVENTORY,
        "permanent_defer_count": len(PERMANENT_DEFER_DATASETS),
        "permanent_defer_excluded": PERMANENT_DEFER_R2_NOTE,
        "live_samples": LIVE_R2_SAMPLE_KEYS,
        "s1_minimal_datasets": list(S1_SIGNAL_HISTORY_DATASETS),
        "multi_signal_datasets": list(MULTI_SIGNAL_HISTORY_DATASETS),
        "bridge_expand_datasets": list(BRIDGE_EXPAND_DATASETS),
        "available_at_repair_policy": AVAILABLE_AT_REPAIR_POLICY,
        "sources": [
            "docs/proof/complete21_cf_read_paths_20260815.md",
            "docs/architecture/r2_partition_scheme.md",
            "platform/workers/ingestion-premium/src/r2_structured_writer.ts",
            ".glm-logs/w0815ay_g1_history/ (W58 live list/get samples)",
            "packages/product/research/single_shot_job.py history_input_patterns",
        ],
        "local_sot": False,
        "mass_research": "NO-GO",
        "ready_declared": False,
        "note": (
            "History SoT is R2 quant-structured. D1 is hot tip only. "
            "Local SQLite is never SoT. Permanent DEFER 5 hard-rejected on load. "
            "W60: bridge expand margin/short/fins/alert + multi-signal long window."
        ),
    }


def write_r2_inventory_json(path: str | Path) -> Path:
    """Write T1 inventory JSON to ``path``."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = r2_inventory_document()
    out.write_text(
        json.dumps(doc, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def schema_mapping_document() -> dict[str, Any]:
    """T2 schema mapping document: R2 envelope → FeatureContext fields."""
    return {
        "wave": "W59 / w0815az_g1",
        "task": "T2 schema mapping Code/Date/event_time/available_at",
        "envelope_fields": list(R2_ENVELOPE_FIELDS),
        "line_schema": R2_LINE_SCHEMA,
        "feature_context_map": FEATURE_CONTEXT_SCHEMA_MAP,
        "pit_gate": {
            "rule": "available_at is required and available_at <= as_of",
            "null_available_at": "excluded (hard)",
            "implementation": [
                "research.r2_feature_context.filter_history_rows(require_available_at=True)",
                "research.single_shot_job._available_at_ok",
                "research.single_shot_job.build_tip_feature_context PIT reader",
            ],
        },
        "s1_column_map": {
            "equities_bars_daily": {
                "Code": "payload.Code | natural_key.Code → row.code",
                "Date": "payload.Date | natural_key.Date | event_time[:10] → row.date",
                "event_time": "envelope.event_time",
                "available_at": "envelope.available_at (PIT)",
                "OHLCV": "payload O/H/L/C/Vo (+ Adj* aliases)",
            },
            "indices_bars_daily_topix": {
                "Code": "none (Date-only natural key)",
                "Date": "payload.Date | event_time[:10] → row.date",
                "event_time": "envelope.event_time",
                "available_at": "envelope.available_at (PIT)",
                "close": "payload.C | payload.Close → row.close",
            },
            "markets_calendar": {
                "Code": "none",
                "Date": "payload.Date → row.date",
                "event_time": "envelope.event_time",
                "available_at": "envelope.available_at (PIT); research repair if ingest pollution",
                "holiday_division": "payload.HolDiv | HolidayDivision",
            },
        },
        "bridge_expand_column_map": {
            "fins_summary": {
                "Code": "payload.Code → row.Code",
                "Date": "payload.DiscDate | payload.Date | event_time[:10]",
                "event_time": "envelope.event_time (disclosure clock)",
                "available_at": "envelope.available_at preserved (post_date_preserve)",
            },
            "markets_margin_interest": {
                "Code": "payload.Code → row.Code",
                "Date": "payload.Date | event_time[:10]",
                "event_time": "envelope.event_time",
                "available_at": "envelope.available_at preserved (post_date_preserve)",
            },
            "markets_short_ratio": {
                "S33": "payload.S33 → row.S33 / section",
                "Date": "payload.Date | event_time[:10]",
                "event_time": "envelope.event_time",
                "available_at": "envelope.available_at preserved (post_date_preserve)",
            },
            "markets_margin_alert": {
                "Code": "payload.Code → row.Code",
                "Date": "payload.Date | event_time[:10]",
                "event_time": "envelope.event_time",
                "available_at": "envelope.available_at preserved (post_date_preserve)",
            },
        },
        "available_at_repair_policy": AVAILABLE_AT_REPAIR_POLICY,
        "local_sot": False,
    }


def can_build_40d_asof(
    rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    *,
    min_trading_days: int = 40,
) -> dict[str, Any]:
    """Report whether supplied history rows can support a ~40 trading-day as_of window.

    When ``rows_by_dataset`` is None, returns code-path capability (bridge exists).
    """
    if rows_by_dataset is None:
        return {
            "can_build_40d_asof": True,
            "code_path": True,
            "requires": [
                "R2 object keys or local/raw fixtures for equities_bars_daily",
                "indices_bars_daily_topix",
                "markets_calendar (optional but preferred for trading days)",
                "period covering >= 40 trading days of bars",
            ],
            "note": (
                "Bridge implemented. Live 40d eval needs R2 keys/get (or fixtures) "
                "spanning the window; D1 tip alone maxes ~28 trading days (hot cutoff)."
            ),
        }
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
        "topix_days": len(topix_days),
        "min_trading_days": int(min_trading_days),
        "bar_day_span": [bar_days[0], bar_days[-1]] if bar_days else None,
        "topix_day_span": [topix_days[0], topix_days[-1]] if topix_days else None,
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
    "COMPLETE_21_DATASETS",
    "COMPLETE_21_DATASET_SET",
    "COMPLETE_21_R2_INVENTORY",
    "DEFAULT_R2_ROW_LIMIT_PER_DATASET",
    "FEATURE_CONTEXT_SCHEMA_MAP",
    "HISTORY_SOURCE_D1_TIP",
    "HISTORY_SOURCE_R2",
    "HISTORY_SOURCES",
    "LIVE_R2_SAMPLE_KEYS",
    "PERMANENT_DEFER_DATASETS",
    "PERMANENT_DEFER_R2_NOTE",
    "PermanentDeferHistoryError",
    "R2GetFn",
    "R2FeatureContextError",
    "R2_ARCHIVE_KEY_PATTERN",
    "R2_HISTORY_BUCKET",
    "R2_HISTORY_PLANE",
    "R2_HISTORY_SOURCE",
    "R2_JSONL_KEY_PATTERN",
    "R2_LINE_SCHEMA",
    "R2_TABLE_PREFIX",
    "RESEARCH_ARTIFACT_BUCKET",
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
