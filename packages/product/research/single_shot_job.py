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
* **Eval extract:** :func:`execute_multiday_signal_eval` / nextday live in
  :mod:`research.single_shot_eval`; cost/compare in
  :mod:`research.single_shot_compare`. Both are re-exported here.
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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
    DEFAULT_VOLUME_SIGN_ABS_MIN,
    MULTI_SIGNAL_DATASETS,
    MULTI_SIGNAL_FEATURE_IDS,
    SIGNAL_ID as DEFAULT_SIGNAL_ID,
    SIGNAL_ID_TOPIX_DISC,
    SIGNAL_ID_TOPIX_REL,
    SIGNAL_ID_VOLUME_SIGN,
    SIGNAL_VERSION as DEFAULT_SIGNAL_VERSION,
    compute_signal_from_feature_observations,
    signal_definition,
)

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

# W52–W53 minimal signal: primary topix_relative_1d approved (W53); filter/gate
# is_trading_day + volume_change_1d approved (W52). candidate_only=False.
# Signal id is fixed in features.minimal_signal; no order execution path.

# ---------------------------------------------------------------------------
# Freeze constants (T9: tests assert these remain closed — do not arm)
# ---------------------------------------------------------------------------

from research.freezes import (
    MASS_RESEARCH as MASS_RESEARCH_STATUS,
    MASS_RESEARCH_ENV_ARMING_SWITCHES,
    PHASE7 as PHASE7_STATUS,
    PHASE7_ENV_ARMING_SWITCHES,
    READY_DECLARED,
    READY_PUBLICATION as READY_PUBLICATION_STATUS,
)

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


# D1 tip extract + FeatureContext live in research.single_shot_tip (re-exported).
# Module import (not from-import) so tip-first load does not circular-import.
import research.single_shot_tip as _single_shot_tip

_as_of_from_period_end = getattr(_single_shot_tip, "_as_of_from_period_end", None)
_available_at_ok = getattr(_single_shot_tip, "_available_at_ok", None)
_decode_json_obj = getattr(_single_shot_tip, "_decode_json_obj", None)
_normalize_tip_bar_row = getattr(_single_shot_tip, "_normalize_tip_bar_row", None)
_normalize_tip_calendar_row = getattr(
    _single_shot_tip, "_normalize_tip_calendar_row", None
)
_normalize_tip_catalog_row = getattr(_single_shot_tip, "_normalize_tip_catalog_row", None)
_normalize_tip_jsda_repo_row = getattr(
    _single_shot_tip, "_normalize_tip_jsda_repo_row", None
)
_pick_num = getattr(_single_shot_tip, "_pick_num", None)
_pick_str = getattr(_single_shot_tip, "_pick_str", None)
_sql_str = getattr(_single_shot_tip, "_sql_str", None)
build_tip_feature_context = getattr(_single_shot_tip, "build_tip_feature_context", None)
compute_tip_candidate_features = getattr(
    _single_shot_tip, "compute_tip_candidate_features", None
)
default_d1_execute = getattr(_single_shot_tip, "default_d1_execute", None)
discover_tip_trading_days = getattr(_single_shot_tip, "discover_tip_trading_days", None)
extract_d1_tip_feature_rows = getattr(
    _single_shot_tip, "extract_d1_tip_feature_rows", None
)
extract_d1_tip_summaries = getattr(_single_shot_tip, "extract_d1_tip_summaries", None)


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


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _put_research_json(
    key: str,
    payload: Mapping[str, Any],
    *,
    r2_put: R2PutFn | None,
    wrangler: str | Path | None = None,
    wrangler_config: str | Path | None = None,
    dry_run: bool = False,
    staging_dir: str | Path | None = None,
    bucket: str = RESEARCH_ARTIFACT_BUCKET,
) -> dict[str, Any]:
    """Put one JSON artifact (injected callable or wrangler / dry-run)."""
    body = _json_bytes(payload)
    if r2_put is not None:
        meta = r2_put(bucket, key, body)
        if "status" not in meta:
            meta = {**meta, "status": "injected"}
        return meta
    return default_r2_put(
        bucket,
        key,
        body,
        wrangler=wrangler,
        config=wrangler_config,
        dry_run=dry_run,
        staging_dir=staging_dir,
    )


_DEFAULT_SMOKE_CODES: tuple[str, ...] = ("13010", "72030", "67580")


def _require_job_window(
    period_start: str, period_end: str, job_id: str
) -> tuple[str, str, str]:
    start = str(period_start).strip()[:10]
    end = str(period_end).strip()[:10]
    if not start or not end:
        raise SingleShotJobError("period_start and period_end are required")
    jid = str(job_id).strip()
    if not jid or "/" in jid or "\\" in jid or ".." in jid:
        raise SingleShotJobError("job_id must be a non-empty path-safe token")
    return start, end, jid


def _select_codes(codes: Sequence[str] | None) -> list[str]:
    if codes:
        return [str(c).strip() for c in codes if str(c).strip()]
    return list(_DEFAULT_SMOKE_CODES)


def _load_history_feature_rows(
    dataset_ids: Sequence[str],
    *,
    period_start: str,
    period_end: str,
    codes: Sequence[str],
    feature_row_limit: int,
    history_source: str,
    d1_execute: D1ExecuteFn | None,
    r2_object_keys_by_dataset: Mapping[str, Sequence[str]] | None,
    r2_local_paths_by_dataset: Mapping[str, Sequence[str | Path]] | None,
    r2_raw_lines_by_dataset: Mapping[str, Sequence[Any]] | None,
    r2_get: Callable[[str, str], bytes] | None,
    r2_bucket: str,
    context: str,
    r2_allow_empty_datasets: Sequence[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Load tip/history rows from D1 hot tip or R2 structured history."""
    from research.r2_feature_context import (
        HISTORY_SOURCE_D1_TIP,
        HISTORY_SOURCE_R2,
        extract_r2_history_feature_rows,
        resolve_history_source,
    )

    hist_src = resolve_history_source(history_source)
    if hist_src == HISTORY_SOURCE_R2:
        extract = extract_r2_history_feature_rows(
            dataset_ids,
            period_start=period_start,
            period_end=period_end,
            codes=codes,
            object_keys_by_dataset=r2_object_keys_by_dataset,
            local_paths_by_dataset=r2_local_paths_by_dataset,
            raw_lines_by_dataset=r2_raw_lines_by_dataset,
            r2_get=r2_get,
            bucket=r2_bucket,
            row_limit_per_dataset=max(int(feature_row_limit), 5000),
            allow_empty_datasets=r2_allow_empty_datasets,
            context=context,
        )
        return hist_src, extract
    if hist_src != HISTORY_SOURCE_D1_TIP:
        raise SingleShotJobError(f"unsupported history_source={hist_src!r}")
    extract = extract_d1_tip_feature_rows(
        dataset_ids,
        period_start=period_start,
        period_end=period_end,
        codes=codes,
        row_limit_per_dataset=feature_row_limit,
        d1_execute=d1_execute,
        context=context,
    )
    return hist_src, extract


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
        return _put_research_json(
            key,
            payload,
            r2_put=r2_put,
            wrangler=wrangler,
            wrangler_config=wrangler_config,
            dry_run=dry_run,
            staging_dir=staging_dir,
            bucket=spec.artifact_bucket,
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


# Multiday / nextday eval lives in research.single_shot_eval; cost/compare
# in research.single_shot_compare (both re-exported). Lazy getattr so
# job-first and eval/compare-first loads all bind.
_COMPARE_EXPORTS: frozenset[str] = frozenset(
    {
        "RESEARCH_COST_LABEL",
        "RESEARCH_COST_NOTE",
        "RESEARCH_ONE_WAY_COST",
        "RESEARCH_ONE_WAY_COST_BP",
        "RESEARCH_ROUND_TRIP_COST",
        "attach_research_cost_fields",
        "execute_extra_hyp_signals_compare",
        "execute_multiday_multisignal_compare",
        "signed_position_from_signal",
        "summarize_research_cost",
    }
)
_EVAL_EXPORTS: frozenset[str] = frozenset(
    {
        "MultidaySignalEval",
        "NEXTDAY_LOOKAHEAD_POLICY",
        "NEXTDAY_RESEARCH_LABEL",
        "attach_next_day_returns",
        "build_equity_close_index",
        "execute_multiday_nextday_return_eval",
        "execute_multiday_signal_eval",
        "next_trading_day_map",
        "session_close_as_of",
        "summarize_nextday_by_sign",
        "summarize_signal_day",
    }
)


def __getattr__(name: str):
    if name in _COMPARE_EXPORTS:
        import research.single_shot_compare as _single_shot_compare

        return getattr(_single_shot_compare, name)
    if name in _EVAL_EXPORTS:
        import research.single_shot_eval as _single_shot_eval

        return getattr(_single_shot_eval, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(
        set(globals()) | _COMPARE_EXPORTS | _EVAL_EXPORTS | set(__all__)
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
    "DEFAULT_VOLUME_SIGN_ABS_MIN",
    "MASS_RESEARCH_ENV_ARMING_SWITCHES",
    "MASS_RESEARCH_STATUS",
    "MULTI_SIGNAL_DATASETS",
    "MULTI_SIGNAL_FEATURE_IDS",
    "NEXTDAY_LOOKAHEAD_POLICY",
    "NEXTDAY_RESEARCH_LABEL",
    "PHASE7_ENV_ARMING_SWITCHES",
    "PHASE7_STATUS",
    "READY_DECLARED",
    "READY_PUBLICATION_STATUS",
    "RESEARCH_ARTIFACT_BUCKET",
    "RESEARCH_ARTIFACT_PREFIX",
    "RESEARCH_COST_LABEL",
    "RESEARCH_COST_NOTE",
    "RESEARCH_ONE_WAY_COST",
    "RESEARCH_ONE_WAY_COST_BP",
    "RESEARCH_ROUND_TRIP_COST",
    "SIGNAL_CANDIDATE_ONLY",
    "SIGNAL_ID_TOPIX_DISC",
    "SIGNAL_ID_TOPIX_REL",
    "SIGNAL_ID_VOLUME_SIGN",
    "MultidaySignalEval",
    "PermanentDeferHistoryError",
    "SingleShotExecution",
    "SingleShotJobError",
    "SingleShotJobSpec",
    "assert_mass_and_phase7_off",
    "attach_next_day_returns",
    "attach_research_cost_fields",
    "build_equity_close_index",
    "build_single_shot_job_spec",
    "build_tip_feature_context",
    "compute_tip_candidate_features",
    "content_hash_payload",
    "default_d1_execute",
    "default_r2_put",
    "design_artifact_paths",
    "discover_tip_trading_days",
    "execute_extra_hyp_signals_compare",
    "execute_multiday_multisignal_compare",
    "execute_multiday_nextday_return_eval",
    "execute_multiday_signal_eval",
    "execute_single_shot_job",
    "extract_d1_tip_feature_rows",
    "extract_d1_tip_summaries",
    "freeze_status",
    "next_trading_day_map",
    "signed_position_from_signal",
    "summarize_research_cost",
    "require_complete_21_only",
    "session_close_as_of",
    "signal_definition",
    "summarize_nextday_by_sign",
    "summarize_signal_day",
]
