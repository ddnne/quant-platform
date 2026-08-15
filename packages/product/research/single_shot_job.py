"""Single-shot research job (Mass OFF / Phase7 OFF / READY not declared).

W49 skeleton (declare + path design) + W50 minimal CF-backed execute +
W51 COMPLETE-21 feature compute on tip FeatureContext +
W52–W53 minimal signal write + W54 multi-day as_of batch (Mass OFF):

* **Inputs:** COMPLETE 21 dataset ids only (permanent DEFER excluded via
  ``data_contracts.permanent_defer``).
* **Read:** CF D1 ``quant-ingest`` hot tip extract (bounded; not full-history SoT).
* **Features:** tip-backed :class:`features.runtime.FeatureContext` (not local
  SQLite SoT) computing COMPLETE-21 min features (approved preferred).
* **Signal (W52–W53):** ``c21_topix_relative_sign`` =
  ``sign(topix_relative_1d)`` + ``is_trading_day`` filter + optional volume
  gate. All three legs are registry-**approved** after W53; signal status
  remains ``candidate`` with ``candidate_only=False``. Written under
  ``…/signals/``.
* **Multi-day (W54):** :func:`execute_multiday_signal_eval` reuses one tip
  extract across 5–10 trading-day as_of values; aggregates sign stats and
  writes ``batch_summary.json`` (still Mass OFF / no READY / no orders).
* **Next-day return (W55):** optional attach of ``R_{T→T+1}`` close-to-close
  returns per code/day + mean-by-sign summary (研究用・未宣言). Feature
  ``as_of`` remains T session close; evaluation uses T+1 close availability
  only (no look-ahead into features). See :data:`NEXTDAY_LOOKAHEAD_POLICY`.
* **Expand window (W56):** multiday + nextday eval may use up to ~20 trading
  days from the available CF D1 tip (or max available; honest if tip is
  shorter). Sign-wise mean **and median** next-day return; outputs always
  labeled **小サンプル / 研究用・未宣言** (no significance / no edge claim).
* **Write:** R2 ``quant-structured`` under ``research/single_shot/job={id}/…``.
  Local FS is **not** Source of Truth (optional dry-run stages payloads only).
* **Not** connected to ``agents.mass_research`` / mass research loop.
* Does **not** set READY / mint readiness / arm Phase7.
* Does **not** emit orders or call paper execution.

This module does not open market HTTP, densify, or publish READY snapshots.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
    reject_permanent_defer_for_history,
)
from features.minimal_signal import (
    CANDIDATE_ONLY as SIGNAL_CANDIDATE_ONLY,
    DEFAULT_FEATURE_IDS as DEFAULT_SIGNAL_FEATURE_IDS,
    DEFAULT_SIGNAL_DATASETS,
    DEFAULT_VOLUME_CHANGE_ABS_MIN,
    SIGNAL_ID as DEFAULT_SIGNAL_ID,
    SIGNAL_VERSION as DEFAULT_SIGNAL_VERSION,
    compute_signal_from_feature_observations,
    signal_definition,
)
from features.registry import get as get_feature
from features.runtime import FEATURES_RUNTIME_VERSION, FeatureContext
from features.types import FeatureOutput

# Repo root: packages/product/research/this_file.py → parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_WRANGLER = (
    _REPO_ROOT
    / "platform"
    / "workers"
    / "ingestion-premium"
    / "node_modules"
    / ".bin"
    / "wrangler"
)
_DEFAULT_WRANGLER_CONFIG = (
    _REPO_ROOT / "platform" / "workers" / "ingestion-premium" / "wrangler.toml"
)
D1_DATABASE_NAME: str = "quant-ingest"
DEFAULT_TIP_SAMPLE_LIMIT: int = 20
DEFAULT_FEATURE_ROW_LIMIT: int = 400
DEFAULT_FEATURE_CODE_LIMIT: int = 5

# COMPLETE-21 min features used by the tip feature path (W51 default set).
# W52–W53: volume_change_1d / is_trading_day / topix_relative_1d are
# registry-approved (v1.0.0 pin). Name kept for path stability; statuses
# mirror the registry. No READY / Mass / Phase7 claim.
DEFAULT_CANDIDATE_FEATURES: tuple[str, ...] = (
    "volume_change_1d",
    "is_trading_day",
    "topix_relative_1d",
)

# Datasets sufficient for the default 2–3 candidate features.
DEFAULT_FEATURE_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
)

# Code-keyed tip extracts: apply natural_key Code filter when codes selected.
# (Index / calendar / section / JSDA macro datasets are intentionally excluded.)
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

# W52–W53 minimal signal: primary topix_relative_1d approved (W53); filter/gate
# is_trading_day + volume_change_1d approved (W52). candidate_only=False.
# Signal id is fixed in features.minimal_signal; no order execution path.

# ---------------------------------------------------------------------------
# Freeze constants (T9: tests assert these remain closed — do not arm)
# ---------------------------------------------------------------------------

MASS_RESEARCH_STATUS: str = "NO-GO"
PHASE7_STATUS: str = "OFF"
READY_PUBLICATION_STATUS: str = "OFF"
READY_DECLARED: bool = False

# No env/flag arming switches exist for Phase7 / mass research.
# Keep empty frozensets as the explicit contract tests freeze against.
PHASE7_ENV_ARMING_SWITCHES: frozenset[str] = frozenset()
MASS_RESEARCH_ENV_ARMING_SWITCHES: frozenset[str] = frozenset()

# ---------------------------------------------------------------------------
# COMPLETE 21 dataset ids (residual SoT held; do not invent 22)
# Source list: docs/proof/coverage_baseline_21_usage_notes_20260815.md
# Relation: governed 26 − permanent DEFER 5 == these 21.
# ---------------------------------------------------------------------------

COMPLETE_21_DATASETS: tuple[str, ...] = (
    "derivatives_bars_daily_futures",
    "derivatives_bars_daily_options",
    "derivatives_bars_daily_options_225",
    "edinet_cross_shareholdings",
    "edinet_large_volume_shareholders",
    "edinet_major_shareholders",
    "equities_bars_daily",
    "equities_investor_types",
    "fins_details",
    "fins_dividend",
    "fins_summary",
    "indices_bars_daily",
    "indices_bars_daily_topix",
    "jsda_corporate_bond_transactions",
    "jsda_tokyo_repo_rates",
    "markets_breakdown",
    "markets_calendar",
    "markets_margin_alert",
    "markets_margin_interest",
    "markets_short_ratio",
    "markets_short_sale_report",
)

COMPLETE_21_DATASET_SET: frozenset[str] = frozenset(COMPLETE_21_DATASETS)

if len(COMPLETE_21_DATASETS) != 21:
    raise RuntimeError(
        f"COMPLETE_21_DATASETS must have exactly 21 ids, got {len(COMPLETE_21_DATASETS)}"
    )
if COMPLETE_21_DATASET_SET & PERMANENT_DEFER_DATASETS:
    raise RuntimeError(
        "COMPLETE_21_DATASETS must not intersect permanent DEFER: "
        f"{sorted(COMPLETE_21_DATASET_SET & PERMANENT_DEFER_DATASETS)}"
    )

# ---------------------------------------------------------------------------
# R2 / CF artifact path design (local is not SoT)
# ---------------------------------------------------------------------------

RESEARCH_ARTIFACT_BUCKET: str = "quant-structured"
RESEARCH_ARTIFACT_PREFIX: str = "research/single_shot"
# History inputs remain on the CF history plane (not local SQLite SoT):
#   structured/jsonl/{dataset}/dt=YYYY-MM-DD/{run_id}.jsonl
#   archive/jquants_records/{dataset}/batch/...
# Job outputs land under RESEARCH_ARTIFACT_PREFIX (same bucket).


class SingleShotJobError(ValueError):
    """Invalid single-shot job input or path design."""


@dataclass(frozen=True)
class SingleShotJobSpec:
    """Declarative single-shot job (not a runnable mass research session)."""

    job_id: str
    dataset_ids: tuple[str, ...]
    period_start: str
    period_end: str
    artifact_bucket: str
    artifact_prefix: str
    manifest_r2_key: str
    input_plan_r2_key: str
    result_r2_key_template: str
    features_r2_key_template: str = ""
    signals_r2_key_template: str = ""
    mass_research: str = MASS_RESEARCH_STATUS
    phase7: str = PHASE7_STATUS
    ready_declared: bool = READY_DECLARED
    local_sot: bool = False
    version: str = "single-shot-job/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "job_id": self.job_id,
            "dataset_ids": list(self.dataset_ids),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "artifact": {
                "bucket": self.artifact_bucket,
                "prefix": self.artifact_prefix,
                "manifest_r2_key": self.manifest_r2_key,
                "input_plan_r2_key": self.input_plan_r2_key,
                "result_r2_key_template": self.result_r2_key_template,
                "features_r2_key_template": self.features_r2_key_template,
                "signals_r2_key_template": self.signals_r2_key_template,
                "local_sot": self.local_sot,
            },
            "mass_research": self.mass_research,
            "phase7": self.phase7,
            "ready_declared": self.ready_declared,
            "ready_publication": READY_PUBLICATION_STATUS,
            "order_execution": False,
        }


def design_artifact_paths(job_id: str) -> dict[str, Any]:
    """Return R2 key layout for a single-shot job.

    Local filesystem paths are intentionally **not** returned as SoT.
    Operators may stage drafts locally, but the designed authority keys are R2.
    """
    jid = str(job_id).strip()
    if not jid:
        raise SingleShotJobError("job_id must be non-empty")
    if "/" in jid or "\\" in jid or ".." in jid:
        raise SingleShotJobError("job_id must not contain path separators")
    prefix = f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}"
    return {
        "bucket": RESEARCH_ARTIFACT_BUCKET,
        "prefix": prefix,
        "manifest_r2_key": f"{prefix}/manifest.json",
        "input_plan_r2_key": f"{prefix}/input_plan.json",
        "result_r2_key_template": f"{prefix}/result/{{content_hash}}.json",
        "features_r2_key_template": f"{prefix}/features/{{content_hash}}.json",
        "signals_r2_key_template": f"{prefix}/signals/{{content_hash}}.json",
        "local_sot": False,
        "history_input_patterns": {
            "structured_jsonl": "structured/jsonl/{dataset}/dt=YYYY-MM-DD/{run_id}.jsonl",
            "archive_ndjson": "archive/jquants_records/{dataset}/batch/{run_id}_after{rowid}.ndjson",
            "note": "History SoT is R2 quant-structured; D1 is hot tip only; local SQLite is mirror only.",
        },
    }


def require_complete_21_only(
    datasets: Sequence[str] | str,
    *,
    context: str = "single-shot research job",
) -> tuple[str, ...]:
    """Return ordered unique dataset ids if all are COMPLETE-21 eligible.

    Fail-closed when:

    * any permanent DEFER id is present (imports permanent_defer guards)
    * any id is outside the residual COMPLETE 21 set
    * the list is empty
    """
    if isinstance(datasets, str):
        requested = (datasets,)
    else:
        requested = tuple(datasets)

    # Permanent DEFER hard reject first (shared contract with history loaders).
    reject_permanent_defer_for_history(requested, context=context)

    out: list[str] = []
    seen: set[str] = set()
    unknown: list[str] = []
    for item in requested:
        value = str(item).strip()
        if not value or value in seen:
            continue
        if value not in COMPLETE_21_DATASET_SET:
            unknown.append(value)
            continue
        seen.add(value)
        out.append(value)

    if unknown:
        raise SingleShotJobError(
            f"{context}: dataset(s) not in COMPLETE 21 allowlist: "
            f"{sorted(set(unknown))}. Prefer residual COMPLETE 21; "
            "do not invent Dataset COMPLETE 22."
        )
    if not out:
        raise SingleShotJobError(
            f"{context}: at least one COMPLETE 21 dataset id is required"
        )
    return tuple(out)


def build_single_shot_job_spec(
    *,
    dataset_ids: Sequence[str],
    period_start: str,
    period_end: str,
    job_id: str | None = None,
) -> SingleShotJobSpec:
    """Build a single-shot job declaration.

    Does **not**:

    * call ``start_mass_research`` / mass research loop
    * set READY / mint ``VerifiedResearchReadiness``
    * arm Phase7 env switches
    * write local SoT artifacts as authority
    """
    start = str(period_start).strip()
    end = str(period_end).strip()
    if not start or not end:
        raise SingleShotJobError("period_start and period_end are required")

    ids = require_complete_21_only(dataset_ids)
    jid = str(job_id).strip() if job_id else str(uuid4())
    paths = design_artifact_paths(jid)

    return SingleShotJobSpec(
        job_id=jid,
        dataset_ids=ids,
        period_start=start,
        period_end=end,
        artifact_bucket=str(paths["bucket"]),
        artifact_prefix=str(paths["prefix"]),
        manifest_r2_key=str(paths["manifest_r2_key"]),
        input_plan_r2_key=str(paths["input_plan_r2_key"]),
        result_r2_key_template=str(paths["result_r2_key_template"]),
        features_r2_key_template=str(paths["features_r2_key_template"]),
        signals_r2_key_template=str(paths["signals_r2_key_template"]),
        mass_research=MASS_RESEARCH_STATUS,
        phase7=PHASE7_STATUS,
        ready_declared=READY_DECLARED,
        local_sot=False,
    )


def freeze_status() -> dict[str, Any]:
    """Return Phase7 / Mass / READY freeze surface (never arms switches)."""
    return {
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_publication": READY_PUBLICATION_STATUS,
        "ready_declared": READY_DECLARED,
        "phase7_env_arming_switches": sorted(PHASE7_ENV_ARMING_SWITCHES),
        "mass_research_env_arming_switches": sorted(MASS_RESEARCH_ENV_ARMING_SWITCHES),
        "complete_21_count": len(COMPLETE_21_DATASETS),
        "permanent_defer_count": len(PERMANENT_DEFER_DATASETS),
        "connected_to_mass_research_loop": False,
        "sets_ready": False,
        "order_execution": False,
        "local_sot": False,
        "artifact_bucket": RESEARCH_ARTIFACT_BUCKET,
        "artifact_prefix": RESEARCH_ARTIFACT_PREFIX,
        "default_signal_id": DEFAULT_SIGNAL_ID,
        "signal_candidate_only": SIGNAL_CANDIDATE_ONLY,
    }


def assert_mass_and_phase7_off() -> Mapping[str, Any]:
    """Hard-check freeze constants; raise if any switch is not closed.

    Tests and operators may call this as a guard. It never enables anything.
    """
    status = freeze_status()
    if status["mass_research"] != "NO-GO":
        raise RuntimeError(f"mass_research must be NO-GO, got {status['mass_research']!r}")
    if status["phase7"] != "OFF":
        raise RuntimeError(f"phase7 must be OFF, got {status['phase7']!r}")
    if status["ready_publication"] != "OFF":
        raise RuntimeError(
            f"ready_publication must be OFF, got {status['ready_publication']!r}"
        )
    if status["ready_declared"] is not False:
        raise RuntimeError("ready_declared must be False")
    if status["phase7_env_arming_switches"]:
        raise RuntimeError("PHASE7 env arming switches must remain empty")
    if status["mass_research_env_arming_switches"]:
        raise RuntimeError("MASS_RESEARCH env arming switches must remain empty")
    if status["connected_to_mass_research_loop"] is not False:
        raise RuntimeError("single-shot skeleton must not connect to mass loop")
    if status["sets_ready"] is not False:
        raise RuntimeError("single-shot skeleton must not set READY")
    if status.get("order_execution") is not False:
        raise RuntimeError("single-shot skeleton must not execute orders")
    return status


# ---------------------------------------------------------------------------
# W50 — minimal CF-backed execute (D1 tip read + R2 artifact put)
# ---------------------------------------------------------------------------

D1ExecuteFn = Callable[[str], list[dict[str, Any]]]
R2PutFn = Callable[[str, str, bytes], dict[str, Any]]


@dataclass(frozen=True)
class SingleShotExecution:
    """Outcome of one single-shot execute pass (not READY, not mass)."""

    job_id: str
    spec: SingleShotJobSpec
    dry_run: bool
    content_hash: str
    result_r2_key: str
    manifest_r2_key: str
    input_plan_r2_key: str
    tip_extracts: Mapping[str, Any]
    r2_puts: tuple[dict[str, Any], ...]
    features_r2_key: str | None = None
    feature_result: Mapping[str, Any] | None = None
    signals_r2_key: str | None = None
    signal_result: Mapping[str, Any] | None = None
    mass_research: str = MASS_RESEARCH_STATUS
    phase7: str = PHASE7_STATUS
    ready_declared: bool = READY_DECLARED
    local_sot: bool = False
    version: str = "single-shot-execution/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "job_id": self.job_id,
            "dry_run": self.dry_run,
            "content_hash": self.content_hash,
            "result_r2_key": self.result_r2_key,
            "manifest_r2_key": self.manifest_r2_key,
            "input_plan_r2_key": self.input_plan_r2_key,
            "features_r2_key": self.features_r2_key,
            "feature_result": (
                dict(self.feature_result) if self.feature_result is not None else None
            ),
            "signals_r2_key": self.signals_r2_key,
            "signal_result": (
                dict(self.signal_result) if self.signal_result is not None else None
            ),
            "tip_extracts": dict(self.tip_extracts),
            "r2_puts": list(self.r2_puts),
            "spec": self.spec.to_dict(),
            "mass_research": self.mass_research,
            "phase7": self.phase7,
            "ready_declared": self.ready_declared,
            "ready_publication": READY_PUBLICATION_STATUS,
            "order_execution": False,
            "local_sot": self.local_sot,
        }


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sql_str(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def content_hash_payload(payload: Mapping[str, Any]) -> str:
    """Stable sha256 of a JSON-canonical payload (no READY semantics)."""
    blob = json.dumps(
        dict(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


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
    """Bounded tip extract from remote D1 ``jquants_records`` (not full history).

    Fail-closed on permanent DEFER / non-COMPLETE-21 ids before any query.
    Returns per-dataset count + min/max event_time + sample natural_keys only
    (payload bodies are not exported — tip proof, not a READY dump).
    """
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
        "date": _pick_str(payload, "Date", "date")
        or (str(event_time)[:10] if event_time else None),
        "close": _pick_num(payload, "Close", "C", "AdjC", "AC"),
        "volume": _pick_num(payload, "Volume", "Vo", "AdjVo", "AVo"),
        "Code": _pick_str(payload, "Code", "code"),
        "Date": _pick_str(payload, "Date", "date"),
        # S33 sector code for markets_short_ratio (short_ratio_level tip path).
        "S33": _pick_str(payload, "S33", "section"),
        "section": _pick_str(payload, "S33", "section"),
    }


# COMPLETE-21 JSDA datasets live on dedicated D1 fact tables (not
# jquants_records). Tip feature extract / summary must hit these tables.
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
    """Bounded tip **payload** extract for FeatureContext (not full history).

    Fail-closed on permanent DEFER / non-COMPLETE-21 before any query.
    Returns normalized tip rows suitable for :func:`build_tip_feature_context`.
    """
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
        "note": (
            "Bounded tip payload extract for candidate feature compute. "
            "Not READY. Not local SQLite SoT. History remains on R2."
        ),
    }


def build_tip_feature_context(
    tip_rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    as_of: str,
    inputs: Mapping[str, Any] | None = None,
) -> FeatureContext:
    """Build a FeatureContext whose PIT reads come from in-memory tip rows.

    Local SQLite is **not** used. Rows are gated by ``available_at <= as_of``.
    """
    as_of_s = str(as_of).strip()
    if not as_of_s:
        raise SingleShotJobError("as_of is required for tip FeatureContext")

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
                    "table": "tip_equities_bars_daily",
                    "count": len(out),
                    "source": "cloudflare_d1_tip",
                    "plane": "D1_hot_tip",
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
                    "table": "tip_markets_calendar",
                    "count": len(out),
                    "source": "cloudflare_d1_tip",
                    "plane": "D1_hot_tip",
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
                    "table": "tip_jquants_records",
                    "dataset": dataset,
                    "count": len(out),
                    "source": "cloudflare_d1_tip",
                    "plane": "D1_hot_tip",
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
                    "table": "tip_jsda_tokyo_repo_rates",
                    "count": len(out),
                    "source": "cloudflare_d1_tip",
                    "plane": "D1_hot_tip",
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


def _discover_tip_sections(
    tip_rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    section_limit: int = DEFAULT_FEATURE_CODE_LIMIT,
) -> list[str]:
    """Discover S33 section codes from tip ``markets_short_ratio`` rows.

    Prefers well-known probe sections (``0050`` …) when present, then fills
    from remaining tip S33 values (stable sort). Empty when tip has no S33.
    """
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
    # Prefer catalog/test probe sections when present in tip.
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
    """Compute COMPLETE-21 min features on a tip FeatureContext.

    Does not use local SQLite. Returns per-feature values + row/null counts
    for the research artifact / manifest. Per-feature ``status`` mirrors the
    registry (approved or candidate); overall path is still not READY.

    ``sections`` supplies S33 codes for ``short_ratio_level``; when omitted,
    sections are discovered from tip ``markets_short_ratio`` rows.
    """
    fids = tuple(feature_ids) if feature_ids else DEFAULT_CANDIDATE_FEATURES
    as_of_s = str(as_of).strip()

    # Discover codes from tip bars when not provided.
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

    # Dates for is_trading_day: explicit, else calendar tip dates, else as_of day.
    cal_rows = list(tip_rows_by_dataset.get("markets_calendar") or [])
    if dates:
        date_list = [str(d)[:10] for d in dates]
    elif cal_rows:
        date_list = sorted({str(r.get("date"))[:10] for r in cal_rows if r.get("date")})
    else:
        date_list = [as_of_s[:10]]

    # S33 sections for short_ratio_level (explicit or tip-discovered).
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
        values: list[Any] = []
        feature_obs: list[dict[str, Any]] = []

        if fid in ("volume_change_1d", "topix_relative_1d", "disclosure_flag_fins",
                   "margin_interest_change_1d", "margin_alert_flag", "return_1d_c21"):
            targets = code_list
            if not targets:
                feature_blocks.append(
                    {
                        "feature_id": fid,
                        "version": version,
                        "status": reg_status,
                        "row_counts": {
                            "computed": 0,
                            "non_null": 0,
                            "null": 0,
                        },
                        "null_counts": 0,
                        "reason": "no tip codes with multi-day history",
                    }
                )
                continue
            for code in targets:
                ctx = build_tip_feature_context(
                    tip_rows_by_dataset,
                    as_of=as_of_s,
                    inputs={"code": code},
                )
                out = feat.compute(ctx)
                if not isinstance(out, FeatureOutput):
                    raise TypeError(
                        f"feature {fid!r} returned {type(out).__name__}; "
                        "expected FeatureOutput"
                    )
                rec = _augment_feature_output(
                    fid,
                    version,
                    as_of_s,
                    out,
                    status=reg_status,
                    extra_meta={"code": code},
                )
                values.append(rec["value"])
                feature_obs.append(rec)
                observations.append(rec)
        elif fid == "is_trading_day":
            for d in date_list:
                ctx = build_tip_feature_context(
                    tip_rows_by_dataset,
                    as_of=as_of_s,
                    inputs={"date": d},
                )
                out = feat.compute(ctx)
                if not isinstance(out, FeatureOutput):
                    raise TypeError(
                        f"feature {fid!r} returned {type(out).__name__}; "
                        "expected FeatureOutput"
                    )
                rec = _augment_feature_output(
                    fid,
                    version,
                    as_of_s,
                    out,
                    status=reg_status,
                    extra_meta={"date": d},
                )
                values.append(rec["value"])
                feature_obs.append(rec)
                observations.append(rec)
        elif fid == "short_ratio_level":
            targets = section_list
            if not targets:
                feature_blocks.append(
                    {
                        "feature_id": fid,
                        "version": version,
                        "status": reg_status,
                        "row_counts": {"computed": 0, "non_null": 0, "null": 0},
                        "null_counts": 0,
                        "reason": (
                            "short_ratio_level requires section; no tip S33 "
                            "sections discovered and none provided"
                        ),
                    }
                )
                continue
            for section in targets:
                ctx = build_tip_feature_context(
                    tip_rows_by_dataset,
                    as_of=as_of_s,
                    inputs={"section": section},
                )
                out = feat.compute(ctx)
                if not isinstance(out, FeatureOutput):
                    raise TypeError(
                        f"feature {fid!r} returned {type(out).__name__}; "
                        "expected FeatureOutput"
                    )
                rec = _augment_feature_output(
                    fid,
                    version,
                    as_of_s,
                    out,
                    status=reg_status,
                    extra_meta={"section": section},
                )
                values.append(rec["value"])
                feature_obs.append(rec)
                observations.append(rec)
        else:
            # Features with no required kwargs (e.g. repo_rate_level,
            # futures_activity_proxy).
            ctx = build_tip_feature_context(
                tip_rows_by_dataset, as_of=as_of_s, inputs={}
            )
            out = feat.compute(ctx)
            if not isinstance(out, FeatureOutput):
                raise TypeError(
                    f"feature {fid!r} returned {type(out).__name__}; "
                    "expected FeatureOutput"
                )
            rec = _augment_feature_output(
                fid, version, as_of_s, out, status=reg_status
            )
            values.append(rec["value"])
            feature_obs.append(rec)
            observations.append(rec)

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
        "note": (
            "COMPLETE-21 min features on tip FeatureContext (D1 hot tip). "
            "Per-feature status from registry. Not READY. Not mass research."
        ),
    }


def default_r2_put(
    bucket: str,
    key: str,
    body: bytes,
    *,
    wrangler: str | Path | None = None,
    config: str | Path | None = None,
    content_type: str = "application/json",
    dry_run: bool = False,
    staging_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Put one object to R2 via wrangler (remote). dry_run stages only."""
    meta = {
        "bucket": bucket,
        "key": key,
        "bytes": len(body),
        "content_type": content_type,
        "object_path": f"{bucket}/{key}",
    }
    if dry_run:
        staged: str | None = None
        if staging_dir is not None:
            out = Path(staging_dir) / key.replace("/", "__")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(body)
            staged = str(out)
        return {**meta, "status": "dry_run", "staged_path": staged}

    wr = Path(wrangler) if wrangler else _DEFAULT_WRANGLER
    cfg = Path(config) if config else _DEFAULT_WRANGLER_CONFIG
    if not wr.is_file():
        raise SingleShotJobError(
            f"wrangler binary not found for R2 put: {wr}. "
            "Use dry_run=True to stage payloads without remote write."
        )

    with tempfile.NamedTemporaryFile(
        prefix="ssjob_", suffix=".json", delete=False
    ) as tmp:
        tmp.write(body)
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [
                str(wr),
                "r2",
                "object",
                "put",
                f"{bucket}/{key}",
                f"--file={tmp_path}",
                "--remote",
                f"--config={cfg}",
                f"--content-type={content_type}",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(_REPO_ROOT),
        )
        if proc.returncode != 0:
            combined = (proc.stderr or "") + (proc.stdout or "")
            raise SingleShotJobError(
                f"r2 put failed for {bucket}/{key} rc={proc.returncode}: "
                f"{combined[-1200:]}"
            )
        return {**meta, "status": "put_ok", "wrangler_rc": 0}
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def head_r2_object(
    bucket: str,
    key: str,
    *,
    wrangler: str | Path | None = None,
    config: str | Path | None = None,
) -> dict[str, Any]:
    """Confirm an R2 object exists via ``wrangler r2 object get`` to a temp file."""
    wr = Path(wrangler) if wrangler else _DEFAULT_WRANGLER
    cfg = Path(config) if config else _DEFAULT_WRANGLER_CONFIG
    with tempfile.NamedTemporaryFile(
        prefix="ssjob_head_", suffix=".bin", delete=False
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
            timeout=120,
            cwd=str(_REPO_ROOT),
        )
        if proc.returncode != 0:
            combined = (proc.stderr or "") + (proc.stdout or "")
            return {
                "bucket": bucket,
                "key": key,
                "exists": False,
                "error": combined[-800:],
            }
        size = tmp_path.stat().st_size if tmp_path.is_file() else 0
        return {
            "bucket": bucket,
            "key": key,
            "exists": True,
            "bytes": size,
        }
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def execute_single_shot_job(
    *,
    dataset_ids: Sequence[str],
    period_start: str,
    period_end: str,
    job_id: str | None = None,
    dry_run: bool = False,
    sample_limit: int = DEFAULT_TIP_SAMPLE_LIMIT,
    compute_features: bool = False,
    compute_signals: bool = False,
    feature_ids: Sequence[str] | None = None,
    feature_codes: Sequence[str] | None = None,
    feature_sections: Sequence[str] | None = None,
    feature_as_of: str | None = None,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    volume_change_abs_min: float | None = DEFAULT_VOLUME_CHANGE_ABS_MIN,
    d1_execute: D1ExecuteFn | None = None,
    r2_put: R2PutFn | None = None,
    staging_dir: str | Path | None = None,
    wrangler: str | Path | None = None,
    wrangler_config: str | Path | None = None,
) -> SingleShotExecution:
    """Run one CF-backed single-shot pass: D1 tip extract → R2 result+manifest.

    Parameters
    ----------
    dry_run:
        When True, design + D1 read still run; R2 puts are staged locally only
        (or recorded without remote write). Prefer real R2 put when credentials
        work.
    compute_features:
        When True, also extract tip payloads, build a tip FeatureContext
        (not local SQLite), compute COMPLETE-21 **candidate** features, and
        write a features artifact + feature stats on the manifest.
    compute_signals:
        When True, also compute the W52/W53 minimal tip signal from approved
        feature observations and write a signals artifact under
        ``research/single_shot/job={id}/signals/``. Implies feature compute
        for the signal's required feature ids. ``candidate_only=False``
        (legs approved; signal status remains candidate).
        Does **not** mint READY or emit orders.
    d1_execute / r2_put:
        Injectable callables for unit tests. Defaults use wrangler remote.

    Never connects to mass research, never sets READY, never arms Phase7,
    never executes orders.
    """
    assert_mass_and_phase7_off()
    # Signal path always needs features; never opens order/mass paths.
    if compute_signals:
        compute_features = True
    spec = build_single_shot_job_spec(
        dataset_ids=dataset_ids,
        period_start=period_start,
        period_end=period_end,
        job_id=job_id,
    )

    tip = extract_d1_tip_summaries(
        spec.dataset_ids,
        period_start=spec.period_start,
        period_end=spec.period_end,
        sample_limit=sample_limit,
        d1_execute=d1_execute,
        context="single-shot research job tip extract",
    )

    feature_payload: dict[str, Any] | None = None
    tip_feature_extract: dict[str, Any] | None = None
    signal_payload: dict[str, Any] | None = None
    if compute_features:
        # Ensure feature-required datasets are present when caller only passed
        # a summary subset; still COMPLETE-21 only / DEFER fail-closed.
        if feature_ids is not None:
            fids = tuple(feature_ids)
        elif compute_signals:
            fids = DEFAULT_SIGNAL_FEATURE_IDS
        else:
            fids = DEFAULT_CANDIDATE_FEATURES
        # Signal always needs its three feature legs.
        if compute_signals:
            for required_fid in DEFAULT_SIGNAL_FEATURE_IDS:
                if required_fid not in fids:
                    fids = fids + (required_fid,)
        needed: list[str] = list(spec.dataset_ids)
        # Map feature → required tip datasets (min surface for default 3).
        if "volume_change_1d" in fids or "topix_relative_1d" in fids:
            if "equities_bars_daily" not in needed:
                needed.append("equities_bars_daily")
        if "is_trading_day" in fids and "markets_calendar" not in needed:
            needed.append("markets_calendar")
        if "topix_relative_1d" in fids and "indices_bars_daily_topix" not in needed:
            needed.append("indices_bars_daily_topix")
        if "margin_interest_change_1d" in fids and "markets_margin_interest" not in needed:
            needed.append("markets_margin_interest")
        if "disclosure_flag_fins" in fids and "fins_summary" not in needed:
            needed.append("fins_summary")
        if "margin_alert_flag" in fids and "markets_margin_alert" not in needed:
            needed.append("markets_margin_alert")
        if "return_1d_c21" in fids and "equities_bars_daily" not in needed:
            needed.append("equities_bars_daily")
        if "repo_rate_level" in fids and "jsda_tokyo_repo_rates" not in needed:
            needed.append("jsda_tokyo_repo_rates")
        if "short_ratio_level" in fids and "markets_short_ratio" not in needed:
            needed.append("markets_short_ratio")
        if (
            "futures_activity_proxy" in fids
            and "derivatives_bars_daily_futures" not in needed
        ):
            needed.append("derivatives_bars_daily_futures")
        if compute_signals:
            for ds in DEFAULT_SIGNAL_DATASETS:
                if ds not in needed:
                    needed.append(ds)
        # Re-validate expanded set (DEFER still fail-closed).
        feature_datasets = require_complete_21_only(
            needed, context="single-shot feature datasets"
        )
        tip_feature_extract = extract_d1_tip_feature_rows(
            feature_datasets,
            period_start=spec.period_start,
            period_end=spec.period_end,
            codes=feature_codes,
            row_limit_per_dataset=feature_row_limit,
            d1_execute=d1_execute,
            context="single-shot tip feature extract",
        )
        as_of = feature_as_of or _as_of_from_period_end(spec.period_end)
        feature_payload = compute_tip_candidate_features(
            tip_feature_extract.get("rows_by_dataset") or {},
            as_of=as_of,
            feature_ids=fids,
            codes=feature_codes or tip_feature_extract.get("selected_codes"),
            sections=feature_sections,
        )
        feature_payload = {
            **feature_payload,
            "job_id": spec.job_id,
            "dataset_ids": list(feature_datasets),
            "period_start": spec.period_start,
            "period_end": spec.period_end,
            "tip_feature_extract": {
                "plane": tip_feature_extract.get("plane"),
                "raw_tip_counts": tip_feature_extract.get("raw_tip_counts"),
                "extracted_row_counts": tip_feature_extract.get(
                    "extracted_row_counts"
                ),
                "selected_codes": tip_feature_extract.get("selected_codes"),
            },
        }
        if compute_signals:
            # Pure join over tip feature observations — no mass, no READY, no orders.
            signal_core = compute_signal_from_feature_observations(
                feature_payload.get("observations") or [],
                as_of=as_of,
                volume_change_abs_min=volume_change_abs_min,
                codes=feature_codes or tip_feature_extract.get("selected_codes"),
            )
            signal_payload = {
                **signal_core,
                "job_id": spec.job_id,
                "definition": signal_definition(),
                "dataset_ids": list(feature_datasets),
                "period_start": spec.period_start,
                "period_end": spec.period_end,
                "feature_tip_input_row_counts": feature_payload.get(
                    "tip_input_row_counts"
                ),
                "tip_feature_extract": feature_payload.get("tip_feature_extract"),
            }

    executed_at = _now_utc()
    # Hash identity excludes wall-clock so re-runs with same tip facts are stable
    # when counts match; executed_at lives only in outer envelopes.
    result_identity: dict[str, Any] = {
        "version": "single-shot-result/v1",
        "job_id": spec.job_id,
        "dataset_ids": list(spec.dataset_ids),
        "period_start": spec.period_start,
        "period_end": spec.period_end,
        "tip_plane": tip["plane"],
        "d1_database": tip["d1_database"],
        "extracts": {
            ds: {
                "row_count": body["row_count"],
                "min_event_time": body["min_event_time"],
                "max_event_time": body["max_event_time"],
                "sample_limit": body["sample_limit"],
                "sample_natural_keys": [
                    row.get("natural_key") for row in body.get("sample_rows") or []
                ],
            }
            for ds, body in (tip.get("extracts") or {}).items()
        },
        "compute_features": bool(compute_features),
        "compute_signals": bool(compute_signals),
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "ready_publication": READY_PUBLICATION_STATUS,
        "order_execution": False,
        "local_sot": False,
    }
    if feature_payload is not None:
        # Stable feature identity for content hash (exclude sample dumps of floats only via features summary).
        result_identity["features_summary"] = [
            {
                "feature_id": f.get("feature_id"),
                "version": f.get("version"),
                "row_counts": f.get("row_counts"),
                "null_counts": f.get("null_counts"),
            }
            for f in (feature_payload.get("features") or [])
        ]
        result_identity["feature_as_of"] = feature_payload.get("as_of")
        result_identity["feature_ids"] = list(feature_payload.get("feature_ids") or [])
    if signal_payload is not None:
        result_identity["signal_summary"] = {
            "signal_id": signal_payload.get("signal_id"),
            "signal_version": signal_payload.get("signal_version"),
            "status": signal_payload.get("status"),
            "candidate_only": signal_payload.get("candidate_only"),
            "row_counts": signal_payload.get("row_counts"),
            "null_counts": signal_payload.get("null_counts"),
        }

    ch = content_hash_payload(result_identity)
    result_key = spec.result_r2_key_template.format(content_hash=ch.replace(":", "_"))
    features_key: str | None = None
    if feature_payload is not None and spec.features_r2_key_template:
        features_key = spec.features_r2_key_template.format(
            content_hash=ch.replace(":", "_")
        )
    signals_key: str | None = None
    if signal_payload is not None and spec.signals_r2_key_template:
        signals_key = spec.signals_r2_key_template.format(
            content_hash=ch.replace(":", "_")
        )

    result_body: dict[str, Any] = {
        **result_identity,
        "content_hash": ch,
        "executed_at_utc": executed_at,
        "artifact": {
            "bucket": spec.artifact_bucket,
            "result_r2_key": result_key,
            "manifest_r2_key": spec.manifest_r2_key,
            "input_plan_r2_key": spec.input_plan_r2_key,
            "features_r2_key": features_key,
            "signals_r2_key": signals_key,
        },
        "sample_rows": {
            ds: body.get("sample_rows") or []
            for ds, body in (tip.get("extracts") or {}).items()
        },
    }
    if feature_payload is not None:
        result_body["features"] = feature_payload.get("features")
        result_body["feature_codes"] = feature_payload.get("codes")
        result_body["feature_tip_input_row_counts"] = feature_payload.get(
            "tip_input_row_counts"
        )
    if signal_payload is not None:
        result_body["signal"] = {
            "signal_id": signal_payload.get("signal_id"),
            "version": signal_payload.get("signal_version"),
            "status": signal_payload.get("status"),
            "candidate_only": signal_payload.get("candidate_only"),
            "row_counts": signal_payload.get("row_counts"),
            "sample_values": signal_payload.get("sample_values"),
        }

    input_plan = {
        "version": "single-shot-input-plan/v1",
        "job_id": spec.job_id,
        "dataset_ids": list(spec.dataset_ids),
        "period_start": spec.period_start,
        "period_end": spec.period_end,
        "tip_source": {
            "plane": tip["plane"],
            "d1_database": tip["d1_database"],
            "table": "jquants_records",
        },
        "compute_features": bool(compute_features),
        "compute_signals": bool(compute_signals),
        "feature_ids": list(feature_payload.get("feature_ids") or [])
        if feature_payload
        else [],
        "signal_id": signal_payload.get("signal_id") if signal_payload else None,
        "history_sot_note": (
            "Full history SoT is R2 quant-structured JSONL/archive; "
            "this job only reads D1 hot tip for a bounded proof pass."
        ),
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "order_execution": False,
    }

    manifest: dict[str, Any] = {
        "version": "single-shot-manifest/v1",
        "job_id": spec.job_id,
        "bucket": spec.artifact_bucket,
        "prefix": spec.artifact_prefix,
        "keys": {
            "manifest": spec.manifest_r2_key,
            "input_plan": spec.input_plan_r2_key,
            "result": result_key,
            **({"features": features_key} if features_key else {}),
            **({"signals": signals_key} if signals_key else {}),
        },
        "content_hash": ch,
        "dataset_ids": list(spec.dataset_ids),
        "period_start": spec.period_start,
        "period_end": spec.period_end,
        "tip_row_counts": {
            ds: int((body or {}).get("row_count") or 0)
            for ds, body in (tip.get("extracts") or {}).items()
        },
        "compute_features": bool(compute_features),
        "compute_signals": bool(compute_signals),
        "executed_at_utc": executed_at,
        "dry_run": bool(dry_run),
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "ready_publication": READY_PUBLICATION_STATUS,
        "order_execution": False,
        "local_sot": False,
        "connected_to_mass_research_loop": False,
    }
    if feature_payload is not None:
        # T3: manifest carries feature_id, version, row_counts (+ null_counts).
        manifest["features"] = [
            {
                "feature_id": f.get("feature_id"),
                "version": f.get("version"),
                "status": f.get("status"),
                "row_counts": f.get("row_counts"),
                "null_counts": f.get("null_counts"),
            }
            for f in (feature_payload.get("features") or [])
        ]
        manifest["feature_as_of"] = feature_payload.get("as_of")
        manifest["feature_tip_input_row_counts"] = feature_payload.get(
            "tip_input_row_counts"
        )
        if tip_feature_extract is not None:
            manifest["feature_raw_tip_counts"] = tip_feature_extract.get(
                "raw_tip_counts"
            )
    if signal_payload is not None:
        manifest["signal"] = {
            "signal_id": signal_payload.get("signal_id"),
            "version": signal_payload.get("signal_version"),
            "status": signal_payload.get("status"),
            "candidate_only": signal_payload.get("candidate_only"),
            "row_counts": signal_payload.get("row_counts"),
            "null_counts": signal_payload.get("null_counts"),
            "feature_ids": signal_payload.get("feature_ids"),
            "as_of": signal_payload.get("as_of"),
            "order_execution": False,
        }

    features_body: dict[str, Any] | None = None
    if feature_payload is not None and features_key is not None:
        features_body = {
            **feature_payload,
            "content_hash": ch,
            "executed_at_utc": executed_at,
            "artifact": {
                "bucket": spec.artifact_bucket,
                "features_r2_key": features_key,
                "result_r2_key": result_key,
                "manifest_r2_key": spec.manifest_r2_key,
                "signals_r2_key": signals_key,
            },
        }

    signals_body: dict[str, Any] | None = None
    if signal_payload is not None and signals_key is not None:
        signals_body = {
            **signal_payload,
            "content_hash": ch,
            "executed_at_utc": executed_at,
            "artifact": {
                "bucket": spec.artifact_bucket,
                "signals_r2_key": signals_key,
                "features_r2_key": features_key,
                "result_r2_key": result_key,
                "manifest_r2_key": spec.manifest_r2_key,
            },
        }

    puts: list[dict[str, Any]] = []

    def _put(key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = _json_bytes(payload)
        if r2_put is not None:
            # Injected put: tests pass (bucket, key, body) -> meta
            meta = r2_put(spec.artifact_bucket, key, body)
            if "status" not in meta:
                meta = {**meta, "status": "injected"}
            return meta
        return default_r2_put(
            spec.artifact_bucket,
            key,
            body,
            wrangler=wrangler,
            config=wrangler_config,
            dry_run=dry_run,
            staging_dir=staging_dir,
        )

    puts.append(_put(spec.input_plan_r2_key, input_plan))
    puts.append(_put(result_key, result_body))
    if features_body is not None and features_key is not None:
        puts.append(_put(features_key, features_body))
    if signals_body is not None and signals_key is not None:
        puts.append(_put(signals_key, signals_body))
    puts.append(_put(spec.manifest_r2_key, manifest))

    return SingleShotExecution(
        job_id=spec.job_id,
        spec=spec,
        dry_run=bool(dry_run),
        content_hash=ch,
        result_r2_key=result_key,
        manifest_r2_key=spec.manifest_r2_key,
        input_plan_r2_key=spec.input_plan_r2_key,
        tip_extracts=tip,
        r2_puts=tuple(puts),
        features_r2_key=features_key,
        feature_result=feature_payload,
        signals_r2_key=signals_key,
        signal_result=signal_payload,
        mass_research=MASS_RESEARCH_STATUS,
        phase7=PHASE7_STATUS,
        ready_declared=READY_DECLARED,
        local_sot=False,
    )


# ---------------------------------------------------------------------------
# W54 — multi-day as_of signal eval (single_shot only · Mass OFF)
# W55 — next-day return alignment (research only · 研究用・未宣言)
# ---------------------------------------------------------------------------

# Look-ahead policy (documented for tests + proofs; do not weaken).
# Convention:
#   * At end of day T, signal S_T uses only data available at T session close
#     (feature as_of = ``{T}T15:30:00+09:00``; available_at ≤ feature as_of).
#   * Realized next-day return R_{T→T+1} = close(T+1)/close(T) − 1 uses bars
#     for trading days T and next trading day T+1.
#   * evaluation_as_of defaults to T+1 session close so the T+1 bar is
#     PIT-available (available_at ≤ evaluation_as_of). This is historical
#     research labeling — not a live trading claim, not READY, not Mass.
# Research-only sample label for nextday metrics (W55/W56). Never an edge claim.
NEXTDAY_RESEARCH_LABEL: str = "小サンプル / 研究用・未宣言"

NEXTDAY_LOOKAHEAD_POLICY: Mapping[str, Any] = MappingProxyType(
    {
        "version": "nextday-lookahead-policy/v1",
        "label": NEXTDAY_RESEARCH_LABEL,
        "feature_as_of": "signal_day_T_session_close",
        "feature_as_of_clock": "T15:30:00+09:00",
        "feature_pit_gate": "available_at <= feature_as_of",
        "return_definition": "close(T+1)/close(T) - 1",
        "evaluation_as_of": "next_trading_day_T1_session_close",
        "evaluation_as_of_clock": "T+1 15:30:00+09:00",
        "return_pit_gate": "available_at(T bar) and available_at(T+1 bar) <= evaluation_as_of",
        "no_feature_lookahead": True,
        "ready_declared": False,
        "mass_research": "NO-GO",
        "significance_claimed": False,
        "edge_claimed": False,
        "note": (
            "Signal features never see T+1 bars. Returns are attached only "
            "when both T and T+1 closes pass the evaluation PIT gate. "
            "Missing T+1 (tip edge) → null return, counted in null rate. "
            "小サンプル — no statistical significance / no edge claim."
        ),
    }
)


@dataclass(frozen=True)
class MultidaySignalEval:
    """Outcome of a multi-as_of tip signal batch (not READY, not mass, no orders)."""

    job_id: str
    n_days: int
    as_of_days: tuple[str, ...]
    codes: tuple[str, ...]
    batch_summary_r2_key: str
    batch_summary: Mapping[str, Any]
    day_results: tuple[Mapping[str, Any], ...]
    r2_puts: tuple[dict[str, Any], ...]
    dry_run: bool
    mass_research: str = MASS_RESEARCH_STATUS
    phase7: str = PHASE7_STATUS
    ready_declared: bool = READY_DECLARED
    local_sot: bool = False
    attach_nextday_returns: bool = False
    version: str = "multiday-signal-eval/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "job_id": self.job_id,
            "n_days": self.n_days,
            "as_of_days": list(self.as_of_days),
            "codes": list(self.codes),
            "batch_summary_r2_key": self.batch_summary_r2_key,
            "batch_summary": dict(self.batch_summary),
            "day_results": [dict(d) for d in self.day_results],
            "r2_puts": list(self.r2_puts),
            "dry_run": self.dry_run,
            "mass_research": self.mass_research,
            "phase7": self.phase7,
            "ready_declared": self.ready_declared,
            "ready_publication": READY_PUBLICATION_STATUS,
            "order_execution": False,
            "local_sot": self.local_sot,
            "connected_to_mass_research_loop": False,
            "attach_nextday_returns": self.attach_nextday_returns,
            "label": (
                NEXTDAY_RESEARCH_LABEL
                if self.attach_nextday_returns
                else "研究用・未宣言"
            ),
            "significance_claimed": False,
            "edge_claimed": False,
        }


def discover_tip_trading_days(
    tip_rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[str]:
    """Return sorted trading-day dates from tip calendar rows (HolidayDivision==1).

    Falls back to bar event dates when calendar rows are missing (still not READY).
    """
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

    # Fallback: unique bar dates in tip (assume listed session days).
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


def summarize_signal_day(
    signal_payload: Mapping[str, Any],
    *,
    as_of: str,
) -> dict[str, Any]:
    """Per-day aggregate: signal count, non-null rate, sign distribution (+1/0/-1)."""
    rc = signal_payload.get("row_counts") if isinstance(signal_payload, Mapping) else None
    if not isinstance(rc, Mapping):
        rc = {}
    computed = int(rc.get("computed") or 0)
    non_null = int(rc.get("non_null") or 0)
    null_n = int(rc.get("null") or 0)
    long_n = int(rc.get("long") or 0)
    short_n = int(rc.get("short") or 0)
    flat_n = int(rc.get("flat") or 0)
    rate = (float(non_null) / float(computed)) if computed else None
    sample = list(signal_payload.get("sample_values") or [])[:10]
    return {
        "date": str(as_of)[:10],
        "as_of": str(as_of),
        "signal_count": computed,
        "non_null": non_null,
        "null": null_n,
        "non_null_rate": rate,
        "sign_distribution": {
            "+1": long_n,
            "0": flat_n,
            "-1": short_n,
            "null": null_n,
        },
        "row_counts": {
            "computed": computed,
            "non_null": non_null,
            "null": null_n,
            "long": long_n,
            "short": short_n,
            "flat": flat_n,
        },
        "sample_values": sample,
        "signal_id": signal_payload.get("signal_id"),
        "candidate_only": signal_payload.get("candidate_only"),
        "order_execution": False,
        "ready_declared": False,
        "mass_research": MASS_RESEARCH_STATUS,
    }


def session_close_as_of(date: str) -> str:
    """JST equity session-close as_of clock for a calendar date."""
    d = str(date).strip()[:10]
    return f"{d}T15:30:00+09:00"


def build_equity_close_index(
    tip_rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Map ``(code, date)`` → ``{close, available_at, ...}`` from tip equity bars.

    Used only for research next-day return attachment (not feature compute).
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in tip_rows_by_dataset.get("equities_bars_daily") or []:
        code = str(row.get("code") or "").strip()
        date = str(row.get("date") or "")[:10]
        close = row.get("close")
        if not code or not date or close is None:
            continue
        try:
            close_f = float(close)
        except (TypeError, ValueError):
            continue
        out[(code, date)] = {
            "code": code,
            "date": date,
            "close": close_f,
            "available_at": row.get("available_at"),
            "event_time": row.get("event_time"),
        }
    return out


def next_trading_day_map(trading_days: Sequence[str]) -> dict[str, str | None]:
    """For each trading day, map to the next trading day (or None at tip edge)."""
    days = sorted({str(d).strip()[:10] for d in trading_days if str(d).strip()})
    out: dict[str, str | None] = {}
    for i, d in enumerate(days):
        out[d] = days[i + 1] if i + 1 < len(days) else None
    return out


def attach_next_day_returns(
    observations: Sequence[Mapping[str, Any]],
    *,
    signal_date: str,
    next_date: str | None,
    close_index: Mapping[tuple[str, str], Mapping[str, Any]],
    evaluation_as_of: str | None = None,
    feature_as_of: str | None = None,
) -> list[dict[str, Any]]:
    """Attach close-to-close next-day return per signal observation.

    Look-ahead policy (研究用・未宣言 — see :data:`NEXTDAY_LOOKAHEAD_POLICY`):

    * ``feature_as_of`` = signal day T session close (features already gated).
    * ``evaluation_as_of`` = next trading day T+1 session close so the T+1 bar
      is PIT-available; both T and T+1 closes require
      ``available_at <= evaluation_as_of``.
    * Features themselves never use T+1 data (caller must keep feature as_of
      at T close when computing the signal).
    """
    sig_d = str(signal_date).strip()[:10]
    feat_as_of = feature_as_of or session_close_as_of(sig_d)
    nxt_d = str(next_date).strip()[:10] if next_date else None
    eval_as_of = (
        evaluation_as_of
        if evaluation_as_of is not None
        else (session_close_as_of(nxt_d) if nxt_d else None)
    )

    out: list[dict[str, Any]] = []
    for obs in observations:
        rec = dict(obs)
        code = str(obs.get("code") or "").strip()
        close_t: float | None = None
        close_t1: float | None = None
        next_day_return: float | None = None
        pit_ok = False
        reason: str | None

        if not nxt_d:
            reason = "no_next_trading_day"
        elif not code:
            reason = "missing_code"
        elif eval_as_of is None:
            reason = "missing_evaluation_as_of"
        else:
            t_bar = close_index.get((code, sig_d))
            t1_bar = close_index.get((code, nxt_d))
            if t_bar is None:
                reason = "missing_close_T"
            elif t1_bar is None:
                reason = "missing_close_T1"
            elif not _available_at_ok(t_bar.get("available_at"), eval_as_of):
                reason = "pit_fail_T"
            elif not _available_at_ok(t1_bar.get("available_at"), eval_as_of):
                reason = "pit_fail_T1"
            else:
                try:
                    close_t = float(t_bar["close"])
                    close_t1 = float(t1_bar["close"])
                except (TypeError, ValueError, KeyError):
                    reason = "non_numeric_close"
                    close_t = None
                    close_t1 = None
                else:
                    if close_t == 0.0:
                        reason = "zero_close_T"
                    else:
                        next_day_return = (close_t1 / close_t) - 1.0
                        pit_ok = True
                        reason = None

        rec["signal_date"] = sig_d
        rec["next_day_date"] = nxt_d
        rec["close_T"] = close_t
        rec["close_T1"] = close_t1
        rec["next_day_return"] = next_day_return
        rec["feature_as_of"] = feat_as_of
        rec["evaluation_as_of"] = eval_as_of
        rec["next_day_return_pit_ok"] = pit_ok
        rec["next_day_return_null_reason"] = reason
        rec["label"] = NEXTDAY_RESEARCH_LABEL
        out.append(rec)
    return out


def _median_f(values: Sequence[float]) -> float | None:
    """Simple median of a non-empty numeric sequence (research helper)."""
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def summarize_nextday_by_sign(
    aligned_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """T2: mean/median next-day return by signal sign (+1 / 0 / −1), counts, null rates.

    Output is research-only (**小サンプル / 研究用・未宣言**). Does not claim
    READY / Mass / edge / statistical significance.
    """

    def _sign_key(value: Any) -> str:
        if value is None:
            return "null_signal"
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "null_signal"
        if v == 1.0:
            return "+1"
        if v == -1.0:
            return "-1"
        if v == 0.0:
            return "0"
        return "null_signal"

    def _bucket_summary(returns: Sequence[Any]) -> dict[str, Any]:
        n = len(returns)
        non_null = [float(r) for r in returns if r is not None]
        null_n = n - len(non_null)
        mean = (sum(non_null) / len(non_null)) if non_null else None
        median = _median_f(non_null)
        return {
            "count": n,
            "non_null_return_count": len(non_null),
            "null_return_count": null_n,
            "null_return_rate": (float(null_n) / float(n)) if n else None,
            "mean_next_day_return": mean,
            "median_next_day_return": median,
        }

    buckets: dict[str, list[Any]] = {
        "+1": [],
        "0": [],
        "-1": [],
        "null_signal": [],
    }
    for row in aligned_rows:
        key = _sign_key(row.get("value"))
        buckets[key].append(row.get("next_day_return"))

    by_sign = {k: _bucket_summary(v) for k, v in buckets.items()}
    overall = _bucket_summary([row.get("next_day_return") for row in aligned_rows])

    # Sign-aligned only (exclude null signal) for a compact research view.
    signed_rows = [
        row
        for row in aligned_rows
        if row.get("value") is not None
        and float(row["value"]) in (1.0, 0.0, -1.0)
    ]
    signed_overall = _bucket_summary(
        [row.get("next_day_return") for row in signed_rows]
    )

    return {
        "version": "nextday-by-sign/v2",
        "label": NEXTDAY_RESEARCH_LABEL,
        "by_sign": by_sign,
        "overall": overall,
        "signed_overall": signed_overall,
        "n_rows": len(aligned_rows),
        "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
        "ready_declared": False,
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "order_execution": False,
        "significance_claimed": False,
        "edge_claimed": False,
        "note": (
            "Mean and median next-day close-to-close return by signal sign. "
            "小サンプル / 研究用・未宣言 — not READY, not Mass, no order claim, "
            "no statistical significance, no edge claim."
        ),
    }


def execute_multiday_signal_eval(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "w0815au-g1-multiday",
    codes: Sequence[str] | None = None,
    as_of_days: Sequence[str] | None = None,
    max_days: int = 10,
    min_days: int = 5,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    volume_change_abs_min: float | None = DEFAULT_VOLUME_CHANGE_ABS_MIN,
    attach_nextday_returns: bool = False,
    write_per_day_artifacts: bool = True,
    dry_run: bool = False,
    d1_execute: D1ExecuteFn | None = None,
    r2_put: R2PutFn | None = None,
    staging_dir: str | Path | None = None,
    wrangler: str | Path | None = None,
    wrangler_config: str | Path | None = None,
) -> MultidaySignalEval:
    """Run single_shot-equivalent tip signal compute across multiple as_of days.

    Flow (Mass OFF · no READY · no orders · CF D1 tip only):

    1. One tip payload extract for the window (not local SQLite SoT).
    2. Discover trading days (or use caller ``as_of_days``).
    3. For each day: tip FeatureContext → approved-leg features → signal.
       Feature ``as_of`` is always T session close (no T+1 feature leak).
    4. Aggregate per-day counts / non-null rate / sign distribution.
    5. Optional (W55): attach next-day return per code/day when T+1 bar is
       PIT-available at evaluation_as_of = T+1 session close; summarize mean
       return by signal sign.
    6. Write ``research/single_shot/job={id}/batch_summary.json`` (+ optional
       per-day ``days/date=YYYY-MM-DD/signals.json``).

    Does **not** call ``agents.mass_research``, mint READY, or paper execution.
    Labels remain 研究用・未宣言 when next-day returns are attached.
    """
    assert_mass_and_phase7_off()
    start = str(period_start).strip()[:10]
    end = str(period_end).strip()[:10]
    if not start or not end:
        raise SingleShotJobError("period_start and period_end are required")
    jid = str(job_id).strip()
    if not jid or "/" in jid or "\\" in jid or ".." in jid:
        raise SingleShotJobError("job_id must be a non-empty path-safe token")

    dataset_ids = require_complete_21_only(
        DEFAULT_SIGNAL_DATASETS, context="multiday signal eval datasets"
    )
    selected_codes = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes
        else ["13010", "72030", "67580"]
    )

    tip_feature_extract = extract_d1_tip_feature_rows(
        dataset_ids,
        period_start=start,
        period_end=end,
        codes=selected_codes,
        row_limit_per_dataset=feature_row_limit,
        d1_execute=d1_execute,
        context="multiday signal tip feature extract",
    )
    rows_by_ds = tip_feature_extract.get("rows_by_dataset") or {}
    if codes is None and tip_feature_extract.get("selected_codes"):
        selected_codes = list(tip_feature_extract["selected_codes"])

    # Full tip trading calendar (used for next-day mapping even when as_of_days
    # is a caller subset).
    full_trading_days = discover_tip_trading_days(
        rows_by_ds, period_start=start, period_end=end
    )
    # Bar-date fallback for next-day when calendar is short of tip bars.
    bar_days = sorted(
        {
            str(r.get("date") or "")[:10]
            for r in (rows_by_ds.get("equities_bars_daily") or [])
            if r.get("date")
        }
    )
    next_day_source = full_trading_days if full_trading_days else bar_days
    # Union calendar + bars so T+1 can resolve from either plane.
    next_day_source = sorted(set(next_day_source) | set(bar_days))
    next_map = next_trading_day_map(next_day_source)
    close_index = (
        build_equity_close_index(rows_by_ds) if attach_nextday_returns else {}
    )

    if as_of_days:
        day_list = sorted({str(d).strip()[:10] for d in as_of_days if str(d).strip()})
    else:
        day_list = list(full_trading_days)
    # Prefer mid/late window days so 1d features have prior bars in the tip.
    if len(day_list) > max_days:
        day_list = day_list[-int(max_days) :]
    if len(day_list) < min_days and as_of_days is None:
        # Still proceed with whatever trading days exist; caller sees n_days.
        pass
    if not day_list:
        raise SingleShotJobError(
            "multiday signal eval: no trading days found in tip window "
            f"{start}..{end}"
        )

    paths = design_artifact_paths(jid)
    prefix = str(paths["prefix"])
    batch_key = f"{prefix}/batch_summary.json"
    executed_at = _now_utc()

    day_results: list[dict[str, Any]] = []
    for d in day_list:
        # Feature as_of is ALWAYS T session close — never T+1 (no look-ahead).
        as_of = session_close_as_of(d)
        feature_payload = compute_tip_candidate_features(
            rows_by_ds,
            as_of=as_of,
            feature_ids=DEFAULT_SIGNAL_FEATURE_IDS,
            codes=selected_codes,
            dates=[d],
        )
        signal_core = compute_signal_from_feature_observations(
            feature_payload.get("observations") or [],
            as_of=as_of,
            volume_change_abs_min=volume_change_abs_min,
            codes=selected_codes,
        )
        day_summary = summarize_signal_day(signal_core, as_of=as_of)
        day_summary["feature_tip_input_row_counts"] = feature_payload.get(
            "tip_input_row_counts"
        )
        day_summary["feature_ids"] = list(DEFAULT_SIGNAL_FEATURE_IDS)
        day_summary["codes"] = list(selected_codes)
        day_summary["feature_status"] = feature_payload.get("status")
        day_summary["definition"] = signal_definition()
        day_summary["observations"] = list(signal_core.get("observations") or [])
        day_summary["local_sot"] = False
        day_summary["phase7"] = PHASE7_STATUS
        day_summary["feature_as_of"] = as_of
        day_summary["label"] = (
            NEXTDAY_RESEARCH_LABEL if attach_nextday_returns else "研究用・未宣言"
        )

        if attach_nextday_returns:
            nxt = next_map.get(d)
            eval_as_of = session_close_as_of(nxt) if nxt else None
            aligned = attach_next_day_returns(
                day_summary["observations"],
                signal_date=d,
                next_date=nxt,
                close_index=close_index,
                evaluation_as_of=eval_as_of,
                feature_as_of=as_of,
            )
            day_summary["observations"] = aligned
            day_summary["next_day_date"] = nxt
            day_summary["evaluation_as_of"] = eval_as_of
            day_summary["attach_nextday_returns"] = True
            day_summary["look_ahead_policy"] = dict(NEXTDAY_LOOKAHEAD_POLICY)
            day_summary["sample_values"] = [
                {
                    "code": r.get("code"),
                    "value": r.get("value"),
                    "next_day_return": r.get("next_day_return"),
                    "next_day_date": r.get("next_day_date"),
                    "close_T": r.get("close_T"),
                    "close_T1": r.get("close_T1"),
                    "topix_relative": (r.get("metadata") or {}).get(
                        "topix_relative"
                    ),
                    "next_day_return_null_reason": r.get(
                        "next_day_return_null_reason"
                    ),
                }
                for r in aligned[:10]
            ]
            day_summary["nextday_day_summary"] = summarize_nextday_by_sign(aligned)

        day_results.append(day_summary)

    # Aggregate across days.
    total_computed = sum(int(d.get("signal_count") or 0) for d in day_results)
    total_non_null = sum(int(d.get("non_null") or 0) for d in day_results)
    total_null = sum(int(d.get("null") or 0) for d in day_results)
    total_long = sum(int((d.get("sign_distribution") or {}).get("+1") or 0) for d in day_results)
    total_short = sum(int((d.get("sign_distribution") or {}).get("-1") or 0) for d in day_results)
    total_flat = sum(int((d.get("sign_distribution") or {}).get("0") or 0) for d in day_results)
    overall_rate = (
        float(total_non_null) / float(total_computed) if total_computed else None
    )

    per_day_compact = [
        {
            "date": d.get("date"),
            "as_of": d.get("as_of"),
            "feature_as_of": d.get("feature_as_of"),
            "signal_count": d.get("signal_count"),
            "non_null": d.get("non_null"),
            "null": d.get("null"),
            "non_null_rate": d.get("non_null_rate"),
            "sign_distribution": d.get("sign_distribution"),
            "sample_values": d.get("sample_values"),
            **(
                {
                    "next_day_date": d.get("next_day_date"),
                    "evaluation_as_of": d.get("evaluation_as_of"),
                    "nextday_day_summary": d.get("nextday_day_summary"),
                }
                if attach_nextday_returns
                else {}
            ),
        }
        for d in day_results
    ]

    batch_summary: dict[str, Any] = {
        "version": (
            "multiday-signal-nextday-batch/v1"
            if attach_nextday_returns
            else "multiday-signal-batch/v1"
        ),
        "job_id": jid,
        "signal_id": DEFAULT_SIGNAL_ID,
        "signal_version": DEFAULT_SIGNAL_VERSION,
        "signal_status": "candidate",
        "candidate_only": SIGNAL_CANDIDATE_ONLY,
        "definition": signal_definition(),
        "feature_ids": list(DEFAULT_SIGNAL_FEATURE_IDS),
        "feature_status_pins": {
            "topix_relative_1d": "approved",
            "is_trading_day": "approved",
            "volume_change_1d": "approved",
        },
        "approved_legs_only": True,
        "dataset_ids": list(dataset_ids),
        "period_start": start,
        "period_end": end,
        "codes": list(selected_codes),
        "n_days": len(day_results),
        "as_of_days": [d.get("date") for d in day_results],
        "tip_plane": "D1_hot_tip",
        "d1_database": D1_DATABASE_NAME,
        "tip_extracted_row_counts": tip_feature_extract.get("extracted_row_counts"),
        "tip_raw_tip_counts": tip_feature_extract.get("raw_tip_counts"),
        "per_day": per_day_compact,
        "aggregate": {
            "signal_count": total_computed,
            "non_null": total_non_null,
            "null": total_null,
            "non_null_rate": overall_rate,
            "sign_distribution": {
                "+1": total_long,
                "0": total_flat,
                "-1": total_short,
                "null": total_null,
            },
        },
        "volume_change_abs_min": volume_change_abs_min,
        "executed_at_utc": executed_at,
        "artifact": {
            "bucket": RESEARCH_ARTIFACT_BUCKET,
            "prefix": prefix,
            "batch_summary_r2_key": batch_key,
            "per_day_key_template": f"{prefix}/days/date={{date}}/signals.json",
        },
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "ready_publication": READY_PUBLICATION_STATUS,
        "order_execution": False,
        "local_sot": False,
        "connected_to_mass_research_loop": False,
        "densify": False,
        "attach_nextday_returns": bool(attach_nextday_returns),
        "label": (
            NEXTDAY_RESEARCH_LABEL if attach_nextday_returns else "研究用・未宣言"
        ),
        "significance_claimed": False,
        "edge_claimed": False,
        "note": (
            (
                "W55/W56 multi-day tip signal + next-day return alignment via "
                "single_shot only. Feature as_of = T close; evaluation_as_of = "
                "T+1 close for return PIT. Approved-leg signal "
                "c21_topix_relative_sign (candidate_only=False). "
                "小サンプル / 研究用・未宣言 — no significance / no edge claim. "
                "Not READY. Not mass research. No order execution. "
                "CF D1 tip only. No densify."
            )
            if attach_nextday_returns
            else (
                "W54 multi-day tip signal eval via single_shot only. "
                "Approved-leg signal c21_topix_relative_sign (candidate_only=False). "
                "Not READY. Not mass research. No order execution. CF D1 tip only."
            )
        ),
    }

    if attach_nextday_returns:
        all_aligned: list[Mapping[str, Any]] = []
        for d in day_results:
            all_aligned.extend(d.get("observations") or [])
        nextday_summary = summarize_nextday_by_sign(all_aligned)
        batch_summary["nextday_return"] = nextday_summary
        batch_summary["look_ahead_policy"] = dict(NEXTDAY_LOOKAHEAD_POLICY)

    puts: list[dict[str, Any]] = []

    def _put(key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = _json_bytes(payload)
        if r2_put is not None:
            meta = r2_put(RESEARCH_ARTIFACT_BUCKET, key, body)
            if "status" not in meta:
                meta = {**meta, "status": "injected"}
            return meta
        return default_r2_put(
            RESEARCH_ARTIFACT_BUCKET,
            key,
            body,
            wrangler=wrangler,
            config=wrangler_config,
            dry_run=dry_run,
            staging_dir=staging_dir,
        )

    puts.append(_put(batch_key, batch_summary))

    if write_per_day_artifacts:
        for d in day_results:
            date_s = str(d.get("date") or "")[:10]
            day_key = f"{prefix}/days/date={date_s}/signals.json"
            day_body = {
                "version": (
                    "multiday-signal-nextday-day/v1"
                    if attach_nextday_returns
                    else "multiday-signal-day/v1"
                ),
                "job_id": jid,
                **{k: d[k] for k in d if k != "definition"},
                "definition": d.get("definition") or signal_definition(),
                "mass_research": MASS_RESEARCH_STATUS,
                "phase7": PHASE7_STATUS,
                "ready_declared": READY_DECLARED,
                "order_execution": False,
                "local_sot": False,
                "label": "研究用・未宣言",
            }
            puts.append(_put(day_key, day_body))
            d["signals_r2_key"] = day_key

    # Parent manifest (freeze surface + keys; no READY claim).
    manifest_key = str(paths["manifest_r2_key"])
    manifest = {
        "version": (
            "multiday-signal-nextday-manifest/v1"
            if attach_nextday_returns
            else "multiday-signal-manifest/v1"
        ),
        "job_id": jid,
        "bucket": RESEARCH_ARTIFACT_BUCKET,
        "prefix": prefix,
        "keys": {
            "manifest": manifest_key,
            "batch_summary": batch_key,
            **(
                {
                    f"day_{d.get('date')}": d.get("signals_r2_key")
                    for d in day_results
                    if d.get("signals_r2_key")
                }
                if write_per_day_artifacts
                else {}
            ),
        },
        "n_days": len(day_results),
        "as_of_days": [d.get("date") for d in day_results],
        "codes": list(selected_codes),
        "signal_id": DEFAULT_SIGNAL_ID,
        "candidate_only": SIGNAL_CANDIDATE_ONLY,
        "aggregate": batch_summary["aggregate"],
        "executed_at_utc": executed_at,
        "dry_run": bool(dry_run),
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "ready_publication": READY_PUBLICATION_STATUS,
        "order_execution": False,
        "local_sot": False,
        "connected_to_mass_research_loop": False,
        "attach_nextday_returns": bool(attach_nextday_returns),
        "label": "研究用・未宣言",
        **(
            {
                "nextday_return": batch_summary.get("nextday_return"),
                "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
            }
            if attach_nextday_returns
            else {}
        ),
    }
    puts.append(_put(manifest_key, manifest))
    batch_summary["manifest_r2_key"] = manifest_key

    return MultidaySignalEval(
        job_id=jid,
        n_days=len(day_results),
        as_of_days=tuple(str(d.get("date")) for d in day_results),
        codes=tuple(selected_codes),
        batch_summary_r2_key=batch_key,
        batch_summary=batch_summary,
        day_results=tuple(day_results),
        r2_puts=tuple(puts),
        dry_run=bool(dry_run),
        mass_research=MASS_RESEARCH_STATUS,
        phase7=PHASE7_STATUS,
        ready_declared=READY_DECLARED,
        local_sot=False,
        attach_nextday_returns=bool(attach_nextday_returns),
        version=(
            "multiday-signal-nextday-eval/v1"
            if attach_nextday_returns
            else "multiday-signal-eval/v1"
        ),
    )


def execute_multiday_nextday_return_eval(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "w0815aw-g1-expand20",
    codes: Sequence[str] | None = None,
    as_of_days: Sequence[str] | None = None,
    max_days: int = 20,
    min_days: int = 5,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    volume_change_abs_min: float | None = DEFAULT_VOLUME_CHANGE_ABS_MIN,
    write_per_day_artifacts: bool = True,
    dry_run: bool = False,
    d1_execute: D1ExecuteFn | None = None,
    r2_put: R2PutFn | None = None,
    staging_dir: str | Path | None = None,
    wrangler: str | Path | None = None,
    wrangler_config: str | Path | None = None,
) -> MultidaySignalEval:
    """W55/W56 entry: multiday signal eval with next-day return alignment.

    Thin wrapper around :func:`execute_multiday_signal_eval` with
    ``attach_nextday_returns=True``. Default ``max_days=20`` (W56 expand toward
    ~20 trading days within available CF tip). Research only
    (**小サンプル / 研究用・未宣言**) — Mass OFF, READY not declared, no orders,
    no densify, no significance / edge claim. If tip yields fewer than 20
    trading days, returns max available (honest n_days).
    """
    return execute_multiday_signal_eval(
        period_start=period_start,
        period_end=period_end,
        job_id=job_id,
        codes=codes,
        as_of_days=as_of_days,
        max_days=max_days,
        min_days=min_days,
        feature_row_limit=feature_row_limit,
        volume_change_abs_min=volume_change_abs_min,
        attach_nextday_returns=True,
        write_per_day_artifacts=write_per_day_artifacts,
        dry_run=dry_run,
        d1_execute=d1_execute,
        r2_put=r2_put,
        staging_dir=staging_dir,
        wrangler=wrangler,
        wrangler_config=wrangler_config,
    )


__all__ = [
    "COMPLETE_21_DATASETS",
    "COMPLETE_21_DATASET_SET",
    "D1_DATABASE_NAME",
    "DEFAULT_CANDIDATE_FEATURES",
    "DEFAULT_FEATURE_CODE_LIMIT",
    "DEFAULT_FEATURE_DATASETS",
    "DEFAULT_FEATURE_ROW_LIMIT",
    "DEFAULT_SIGNAL_DATASETS",
    "DEFAULT_SIGNAL_FEATURE_IDS",
    "DEFAULT_SIGNAL_ID",
    "DEFAULT_SIGNAL_VERSION",
    "DEFAULT_TIP_SAMPLE_LIMIT",
    "DEFAULT_VOLUME_CHANGE_ABS_MIN",
    "MASS_RESEARCH_ENV_ARMING_SWITCHES",
    "MASS_RESEARCH_STATUS",
    "NEXTDAY_LOOKAHEAD_POLICY",
    "NEXTDAY_RESEARCH_LABEL",
    "PHASE7_ENV_ARMING_SWITCHES",
    "PHASE7_STATUS",
    "READY_DECLARED",
    "READY_PUBLICATION_STATUS",
    "RESEARCH_ARTIFACT_BUCKET",
    "RESEARCH_ARTIFACT_PREFIX",
    "SIGNAL_CANDIDATE_ONLY",
    "MultidaySignalEval",
    "PermanentDeferHistoryError",
    "SingleShotExecution",
    "SingleShotJobError",
    "SingleShotJobSpec",
    "assert_mass_and_phase7_off",
    "attach_next_day_returns",
    "build_equity_close_index",
    "build_single_shot_job_spec",
    "build_tip_feature_context",
    "compute_tip_candidate_features",
    "content_hash_payload",
    "default_d1_execute",
    "default_r2_put",
    "design_artifact_paths",
    "discover_tip_trading_days",
    "execute_multiday_nextday_return_eval",
    "execute_multiday_signal_eval",
    "execute_single_shot_job",
    "extract_d1_tip_feature_rows",
    "extract_d1_tip_summaries",
    "freeze_status",
    "head_r2_object",
    "next_trading_day_map",
    "require_complete_21_only",
    "session_close_as_of",
    "signal_definition",
    "summarize_nextday_by_sign",
    "summarize_signal_day",
]
