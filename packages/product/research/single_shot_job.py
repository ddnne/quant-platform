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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
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
    DEFAULT_SHORT_RATIO_SECTION,
    DEFAULT_SIGNAL_DATASETS,
    DEFAULT_VOLUME_CHANGE_ABS_MIN,
    DEFAULT_VOLUME_SIGN_ABS_MIN,
    EXTRA_HYP_DATASETS,
    EXTRA_HYP_FEATURE_IDS,
    MULTI_SIGNAL_DATASETS,
    MULTI_SIGNAL_FEATURE_IDS,
    SIGNAL_ID as DEFAULT_SIGNAL_ID,
    SIGNAL_ID_MARGIN_CHANGE,
    SIGNAL_ID_SHORT_RATIO_DELTA,
    SIGNAL_ID_TOPIX_DISC,
    SIGNAL_ID_TOPIX_REL,
    SIGNAL_ID_VOLUME_SIGN,
    SIGNAL_VERSION as DEFAULT_SIGNAL_VERSION,
    compute_margin_sign_from_feature_observations,
    compute_short_delta_from_feature_observations,
    compute_signal_from_feature_observations,
    compute_topix_disc_from_feature_observations,
    compute_volume_sign_from_feature_observations,
    extra_hyp_definitions,
    multi_signal_definitions,
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


def _nextday_setup(
    rows_by_ds: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    period_start: str,
    period_end: str,
    need_close_index: bool = True,
) -> tuple[list[str], dict[str, str | None], dict[tuple[str, str], dict[str, Any]]]:
    full_trading_days = discover_tip_trading_days(
        rows_by_ds, period_start=period_start, period_end=period_end
    )
    bar_days = sorted(
        {
            str(r.get("date") or "")[:10]
            for r in (rows_by_ds.get("equities_bars_daily") or [])
            if r.get("date")
        }
    )
    next_map = next_trading_day_map(
        sorted(set(full_trading_days or []) | set(bar_days))
    )
    close_index = (
        build_equity_close_index(rows_by_ds) if need_close_index else {}
    )
    return full_trading_days, next_map, close_index


def _cap_as_of_days(
    as_of_days: Sequence[str] | None,
    full_trading_days: Sequence[str],
    max_days: int,
) -> list[str]:
    if as_of_days:
        day_list = sorted({str(d).strip()[:10] for d in as_of_days if str(d).strip()})
    else:
        day_list = list(full_trading_days)
    if len(day_list) > max_days:
        day_list = day_list[-int(max_days) :]
    return day_list


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
    history_source: str = "d1_tip",
    r2_object_keys_by_dataset: Mapping[str, Sequence[str]] | None = None,
    r2_local_paths_by_dataset: Mapping[str, Sequence[str | Path]] | None = None,
    r2_raw_lines_by_dataset: Mapping[str, Sequence[Any]] | None = None,
    r2_get: Callable[[str, str], bytes] | None = None,
    r2_bucket: str = "quant-structured",
) -> MultidaySignalEval:
    """Run single_shot-equivalent signal compute across multiple as_of days.

    Flow (Mass OFF · no READY · no orders):

    1. One history/tip payload extract for the window (not local SQLite SoT).
       Default ``history_source="d1_tip"`` (CF D1 hot tip). Optional
       ``history_source="r2"`` loads R2 structured JSONL/archive via
       :mod:`research.r2_feature_context` (keys/fixtures required).
    2. Discover trading days (or use caller ``as_of_days``).
    3. For each day: FeatureContext → approved-leg features → signal.
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
    start, end, jid = _require_job_window(period_start, period_end, job_id)
    _ = min_days  # accepted for API compat; short windows still run honestly

    dataset_ids = require_complete_21_only(
        DEFAULT_SIGNAL_DATASETS, context="multiday signal eval datasets"
    )
    selected_codes = _select_codes(codes)

    hist_src, tip_feature_extract = _load_history_feature_rows(
        dataset_ids,
        period_start=start,
        period_end=end,
        codes=selected_codes,
        feature_row_limit=feature_row_limit,
        history_source=history_source,
        d1_execute=d1_execute,
        r2_object_keys_by_dataset=r2_object_keys_by_dataset,
        r2_local_paths_by_dataset=r2_local_paths_by_dataset,
        r2_raw_lines_by_dataset=r2_raw_lines_by_dataset,
        r2_get=r2_get,
        r2_bucket=r2_bucket,
        context="multiday signal feature extract",
    )
    rows_by_ds = tip_feature_extract.get("rows_by_dataset") or {}
    if codes is None and tip_feature_extract.get("selected_codes"):
        selected_codes = list(tip_feature_extract["selected_codes"])

    full_trading_days, next_map, close_index = _nextday_setup(
        rows_by_ds,
        period_start=start,
        period_end=end,
        need_close_index=bool(attach_nextday_returns),
    )
    day_list = _cap_as_of_days(as_of_days, full_trading_days, max_days)
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
        "history_source": hist_src,
        "tip_plane": tip_feature_extract.get("plane")
        or ("R2_history" if hist_src == "r2" else "D1_hot_tip"),
        "d1_database": (
            None if hist_src == "r2" else D1_DATABASE_NAME
        ),
        "r2_bucket": (
            tip_feature_extract.get("bucket")
            if hist_src == "r2"
            else None
        ),
        "tip_extracted_row_counts": tip_feature_extract.get("extracted_row_counts"),
        "tip_raw_tip_counts": tip_feature_extract.get("raw_tip_counts")
        or tip_feature_extract.get("raw_envelope_counts"),
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
        return _put_research_json(
            key,
            payload,
            r2_put=r2_put,
            wrangler=wrangler,
            wrangler_config=wrangler_config,
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
    history_source: str = "d1_tip",
    r2_object_keys_by_dataset: Mapping[str, Sequence[str]] | None = None,
    r2_local_paths_by_dataset: Mapping[str, Sequence[str | Path]] | None = None,
    r2_raw_lines_by_dataset: Mapping[str, Sequence[Any]] | None = None,
    r2_get: Callable[[str, str], bytes] | None = None,
    r2_bucket: str = "quant-structured",
) -> MultidaySignalEval:
    """W55/W56 entry: multiday signal eval with next-day return alignment.

    Thin wrapper around :func:`execute_multiday_signal_eval` with
    ``attach_nextday_returns=True``. Default ``max_days=20`` (W56 expand toward
    ~20 trading days within available CF tip). Research only
    (**小サンプル / 研究用・未宣言**) — Mass OFF, READY not declared, no orders,
    no densify, no significance / edge claim. If tip yields fewer than 20
    trading days, returns max available (honest n_days).

    Optional ``history_source="r2"`` (W59) loads R2 structured history instead
    of D1 tip — see :mod:`research.r2_feature_context`.
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
        history_source=history_source,
        r2_object_keys_by_dataset=r2_object_keys_by_dataset,
        r2_local_paths_by_dataset=r2_local_paths_by_dataset,
        r2_raw_lines_by_dataset=r2_raw_lines_by_dataset,
        r2_get=r2_get,
        r2_bucket=r2_bucket,
        write_per_day_artifacts=write_per_day_artifacts,
        dry_run=dry_run,
        d1_execute=d1_execute,
        r2_put=r2_put,
        staging_dir=staging_dir,
        wrangler=wrangler,
        wrangler_config=wrangler_config,
    )


# ---------------------------------------------------------------------------
# Multi-signal compare + research-only cost (W58 / w0815ay_g2 · T4–T8)
# ---------------------------------------------------------------------------

# Research-only cost assumption (not operational GO).
# One-way 10bp = 0.001; round-trip 20bp if both sides traded.
RESEARCH_ONE_WAY_COST_BP: float = 10.0
RESEARCH_ONE_WAY_COST: float = RESEARCH_ONE_WAY_COST_BP / 10_000.0  # 0.001
RESEARCH_ROUND_TRIP_COST: float = RESEARCH_ONE_WAY_COST * 2.0  # 0.002
RESEARCH_COST_LABEL: str = "仮定に依存・研究用・運用GOではない"
RESEARCH_COST_NOTE: str = (
    "Research-only net next-day return assumes a fixed one-way cost of "
    f"{RESEARCH_ONE_WAY_COST_BP:.0f}bp ({RESEARCH_ONE_WAY_COST}) per signed "
    "position. Round-trip equivalent is "
    f"{RESEARCH_ONE_WAY_COST_BP * 2:.0f}bp ({RESEARCH_ROUND_TRIP_COST}) if "
    "both entry and exit are charged. Cost is subtracted from signed PnL "
    "(|position| * cost) and does NOT model capacity, borrow, impact, or "
    "partial fills. 仮定に依存・研究用・運用GOではない — not operational GO, "
    "not READY, not Mass, no significance / edge claim."
)


def signed_position_from_signal(value: Any) -> float | None:
    """Map signal value to research position: +1 / 0 / −1, or None if null."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v == 1.0:
        return 1.0
    if v == -1.0:
        return -1.0
    if v == 0.0:
        return 0.0
    return None


def attach_research_cost_fields(
    aligned_rows: Sequence[Mapping[str, Any]],
    *,
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
) -> list[dict[str, Any]]:
    """Attach gross/net signed next-day PnL under research cost assumption.

    For each row with non-null signal and non-null next_day_return:

    * position = sign(signal) ∈ {+1, 0, −1}
    * gross_signed_return = position * next_day_return
    * net_signed_return_one_way = gross − |position| * one_way_cost
    * net_signed_return_round_trip = gross − |position| * 2 * one_way_cost

    Null signal or null return → cost fields null. Label:
    **仮定に依存・研究用・運用GOではない**.
    """
    out: list[dict[str, Any]] = []
    rt_cost = float(one_way_cost) * 2.0
    for row in aligned_rows:
        rec = dict(row)
        pos = signed_position_from_signal(row.get("value"))
        ret = row.get("next_day_return")
        rec["research_cost_one_way"] = float(one_way_cost)
        rec["research_cost_round_trip"] = rt_cost
        rec["research_cost_label"] = RESEARCH_COST_LABEL
        if pos is None or ret is None:
            rec["position"] = pos
            rec["gross_signed_return"] = None
            rec["net_signed_return_one_way"] = None
            rec["net_signed_return_round_trip"] = None
            out.append(rec)
            continue
        try:
            r = float(ret)
        except (TypeError, ValueError):
            rec["position"] = pos
            rec["gross_signed_return"] = None
            rec["net_signed_return_one_way"] = None
            rec["net_signed_return_round_trip"] = None
            out.append(rec)
            continue
        gross = float(pos) * r
        abs_pos = abs(float(pos))
        rec["position"] = pos
        rec["gross_signed_return"] = gross
        rec["net_signed_return_one_way"] = gross - abs_pos * float(one_way_cost)
        rec["net_signed_return_round_trip"] = gross - abs_pos * rt_cost
        out.append(rec)
    return out


def summarize_research_cost(
    costed_rows: Sequence[Mapping[str, Any]],
    *,
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
) -> dict[str, Any]:
    """Aggregate gross / net signed PnL under the research cost assumption."""

    def _bucket(field: str) -> dict[str, Any]:
        vals = [
            float(r[field])
            for r in costed_rows
            if r.get(field) is not None and r.get("position") is not None
            and float(r.get("position") or 0) != 0.0
        ]
        # Include flat (0) positions too for "signed overall including flat"
        all_signed = [
            float(r[field])
            for r in costed_rows
            if r.get(field) is not None and r.get("position") is not None
        ]
        n_pos = sum(
            1
            for r in costed_rows
            if r.get("position") is not None and abs(float(r["position"])) > 0
        )
        mean_active = (sum(vals) / len(vals)) if vals else None
        mean_all = (sum(all_signed) / len(all_signed)) if all_signed else None
        med_active = _median_f(vals)
        return {
            "n_active_positions": n_pos,
            "n_with_pnl": len(vals),
            "mean_active": mean_active,
            "median_active": med_active,
            "mean_all_signed_incl_flat": mean_all,
        }

    return {
        "version": "research-cost-summary/v1",
        "label": RESEARCH_COST_LABEL,
        "one_way_cost_bp": one_way_cost * 10_000.0,
        "one_way_cost": float(one_way_cost),
        "round_trip_cost_bp": one_way_cost * 2.0 * 10_000.0,
        "round_trip_cost": float(one_way_cost) * 2.0,
        "gross_signed_return": _bucket("gross_signed_return"),
        "net_signed_return_one_way": _bucket("net_signed_return_one_way"),
        "net_signed_return_round_trip": _bucket("net_signed_return_round_trip"),
        "assumption_note": RESEARCH_COST_NOTE,
        "ready_declared": False,
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "order_execution": False,
        "operational_go": False,
        "significance_claimed": False,
        "edge_claimed": False,
    }


def _summarize_one_signal_batch(
    day_obs_by_signal: Sequence[Sequence[Mapping[str, Any]]],
    *,
    signal_id: str,
    definition: Mapping[str, Any],
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
) -> dict[str, Any]:
    """Aggregate multiday observations for one signal id (nextday + cost)."""
    all_rows: list[Mapping[str, Any]] = []
    for day_rows in day_obs_by_signal:
        all_rows.extend(day_rows)

    total = len(all_rows)
    non_null = sum(1 for r in all_rows if r.get("value") is not None)
    null_n = total - non_null
    long_n = sum(1 for r in all_rows if r.get("value") == 1.0)
    short_n = sum(1 for r in all_rows if r.get("value") == -1.0)
    flat_n = sum(1 for r in all_rows if r.get("value") == 0.0)
    nextday = summarize_nextday_by_sign(all_rows)
    costed = attach_research_cost_fields(all_rows, one_way_cost=one_way_cost)
    cost_summary = summarize_research_cost(costed, one_way_cost=one_way_cost)

    return {
        "signal_id": signal_id,
        "signal_version": DEFAULT_SIGNAL_VERSION,
        "status": "candidate",
        "candidate_only": False,
        "approved_legs_only": True,
        "definition": dict(definition),
        "aggregate": {
            "signal_count": total,
            "non_null": non_null,
            "null": null_n,
            "non_null_rate": (float(non_null) / float(total)) if total else None,
            "sign_distribution": {
                "+1": long_n,
                "0": flat_n,
                "-1": short_n,
                "null": null_n,
            },
        },
        "nextday_return": nextday,
        "research_cost": cost_summary,
        "label": NEXTDAY_RESEARCH_LABEL,
        "cost_label": RESEARCH_COST_LABEL,
        "significance_claimed": False,
        "edge_claimed": False,
        "ready_declared": False,
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "order_execution": False,
        "operational_go": False,
    }


def _compare_row_from_signal_body(
    sid: str, body: Mapping[str, Any]
) -> dict[str, Any]:
    """Compact compare-table row from one signal's batch summary body."""
    nd = body.get("nextday_return") or {}
    by_sign = nd.get("by_sign") or {}
    cost = body.get("research_cost") or {}
    agg = body.get("aggregate") or {}
    return {
        "signal_id": sid,
        "signal_count": agg.get("signal_count"),
        "non_null": agg.get("non_null"),
        "non_null_rate": agg.get("non_null_rate"),
        "sign_plus": (agg.get("sign_distribution") or {}).get("+1"),
        "sign_zero": (agg.get("sign_distribution") or {}).get("0"),
        "sign_minus": (agg.get("sign_distribution") or {}).get("-1"),
        "mean_R_plus": (by_sign.get("+1") or {}).get("mean_next_day_return"),
        "median_R_plus": (by_sign.get("+1") or {}).get("median_next_day_return"),
        "mean_R_minus": (by_sign.get("-1") or {}).get("mean_next_day_return"),
        "median_R_minus": (by_sign.get("-1") or {}).get("median_next_day_return"),
        "overall_mean_R": (nd.get("overall") or {}).get("mean_next_day_return"),
        "overall_median_R": (nd.get("overall") or {}).get("median_next_day_return"),
        "null_return_rate": (nd.get("overall") or {}).get("null_return_rate"),
        "gross_signed_mean_active": (
            (cost.get("gross_signed_return") or {}).get("mean_active")
        ),
        "net_one_way_mean_active": (
            (cost.get("net_signed_return_one_way") or {}).get("mean_active")
        ),
        "net_round_trip_mean_active": (
            (cost.get("net_signed_return_round_trip") or {}).get("mean_active")
        ),
        "n_active_positions": (
            (cost.get("gross_signed_return") or {}).get("n_active_positions")
        ),
    }


def execute_extra_hyp_signals_compare(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "w0815bc-g1-extra-hyp",
    codes: Sequence[str] | None = None,
    as_of_days: Sequence[str] | None = None,
    max_days: int = 40,
    min_days: int = 10,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
    short_ratio_section: str = DEFAULT_SHORT_RATIO_SECTION,
    write_per_day_artifacts: bool = False,
    dry_run: bool = False,
    d1_execute: D1ExecuteFn | None = None,
    r2_put: R2PutFn | None = None,
    staging_dir: str | Path | None = None,
    wrangler: str | Path | None = None,
    wrangler_config: str | Path | None = None,
    history_source: str = "r2",
    r2_object_keys_by_dataset: Mapping[str, Sequence[str]] | None = None,
    r2_local_paths_by_dataset: Mapping[str, Sequence[str | Path]] | None = None,
    r2_raw_lines_by_dataset: Mapping[str, Sequence[Any]] | None = None,
    r2_get: Callable[[str, str], bytes] | None = None,
    r2_bucket: str = "quant-structured",
    r2_allow_empty_datasets: Sequence[str] | None = None,
) -> MultidaySignalEval:
    """S4/S5 research hypotheses (not S1 rehash) multi-day compare.

    S4: sign(margin_interest_change_1d)
    S5: sign(Δ short_ratio_level) for ``short_ratio_section``, broadcast.

    Empty datasets → honest null signals. Not READY / Mass OFF.
    """
    assert_mass_and_phase7_off()
    start, end, jid = _require_job_window(period_start, period_end, job_id)
    _ = min_days

    dataset_ids = require_complete_21_only(
        EXTRA_HYP_DATASETS, context="extra hyp datasets"
    )
    selected_codes = _select_codes(codes)
    section = str(short_ratio_section).strip() or DEFAULT_SHORT_RATIO_SECTION
    _fids: list[str] = []
    for x in list(EXTRA_HYP_FEATURE_IDS) + ["is_trading_day"]:
        if x not in _fids:
            _fids.append(x)
    feature_ids = tuple(_fids)
    definitions = {
        d["signal_id"]: d for d in extra_hyp_definitions(section=section)
    }

    hist_src, tip_feature_extract = _load_history_feature_rows(
        dataset_ids,
        period_start=start,
        period_end=end,
        codes=selected_codes,
        feature_row_limit=feature_row_limit,
        history_source=history_source,
        d1_execute=d1_execute,
        r2_object_keys_by_dataset=r2_object_keys_by_dataset,
        r2_local_paths_by_dataset=r2_local_paths_by_dataset,
        r2_raw_lines_by_dataset=r2_raw_lines_by_dataset,
        r2_get=r2_get,
        r2_bucket=r2_bucket,
        r2_allow_empty_datasets=r2_allow_empty_datasets
        or (
            "markets_margin_interest",
            "markets_short_ratio",
        ),
        context="extra hyp feature extract",
    )
    rows_by_ds = tip_feature_extract.get("rows_by_dataset") or {}

    full_trading_days, next_map, close_index = _nextday_setup(
        rows_by_ds, period_start=start, period_end=end
    )
    day_list = _cap_as_of_days(as_of_days, full_trading_days, max_days)
    if not day_list:
        raise SingleShotJobError(
            f"extra hyp compare: no trading days in {start}..{end}"
        )

    paths = design_artifact_paths(jid)
    prefix = str(paths["prefix"])
    batch_key = f"{prefix}/batch_summary.json"
    executed_at = _now_utc()

    signal_day_rows: dict[str, list[list[dict[str, Any]]]] = {
        SIGNAL_ID_MARGIN_CHANGE: [],
        SIGNAL_ID_SHORT_RATIO_DELTA: [],
    }
    day_results: list[dict[str, Any]] = []
    prev_short: float | None = None

    for d in day_list:
        as_of = session_close_as_of(d)
        feature_payload = compute_tip_candidate_features(
            rows_by_ds,
            as_of=as_of,
            feature_ids=feature_ids,
            codes=selected_codes,
            dates=[d],
            sections=[section],
        )
        obs = feature_payload.get("observations") or []
        s4 = compute_margin_sign_from_feature_observations(
            obs, as_of=as_of, codes=selected_codes
        )
        s5 = compute_short_delta_from_feature_observations(
            obs,
            as_of=as_of,
            prev_short_ratio_level=prev_short,
            codes=selected_codes,
            section=section,
        )
        # update prev short from observations
        for o in obs:
            if str(o.get("feature_id") or "") == "short_ratio_level" and o.get(
                "value"
            ) is not None:
                try:
                    prev_short = float(o["value"])
                except (TypeError, ValueError):
                    pass
                break

        nxt = next_map.get(d)
        eval_as_of = session_close_as_of(nxt) if nxt else None
        per_signal_day: dict[str, Any] = {}
        for sid, core in (
            (SIGNAL_ID_MARGIN_CHANGE, s4),
            (SIGNAL_ID_SHORT_RATIO_DELTA, s5),
        ):
            aligned = attach_next_day_returns(
                list(core.get("observations") or []),
                signal_date=d,
                next_date=nxt,
                close_index=close_index,
                evaluation_as_of=eval_as_of,
                feature_as_of=as_of,
            )
            costed = attach_research_cost_fields(aligned, one_way_cost=one_way_cost)
            signal_day_rows[sid].append(costed)
            day_summary = summarize_signal_day(
                {**core, "observations": costed}, as_of=as_of
            )
            day_summary["nextday_day_summary"] = summarize_nextday_by_sign(costed)
            day_summary["research_cost_day"] = summarize_research_cost(
                costed, one_way_cost=one_way_cost
            )
            day_summary["observations"] = costed
            day_summary["next_day_date"] = nxt
            day_summary["evaluation_as_of"] = eval_as_of
            day_summary["feature_as_of"] = as_of
            day_summary["definition"] = definitions.get(sid)
            per_signal_day[sid] = day_summary

        day_results.append(
            {
                "date": d,
                "as_of": as_of,
                "signals": per_signal_day,
                "codes": list(selected_codes),
                "label": NEXTDAY_RESEARCH_LABEL,
                "mass_research": MASS_RESEARCH_STATUS,
                "phase7": PHASE7_STATUS,
                "ready_declared": READY_DECLARED,
            }
        )

    by_signal: dict[str, Any] = {}
    for sid in (SIGNAL_ID_MARGIN_CHANGE, SIGNAL_ID_SHORT_RATIO_DELTA):
        by_signal[sid] = _summarize_one_signal_batch(
            signal_day_rows[sid],
            signal_id=sid,
            definition=definitions.get(sid) or {},
            one_way_cost=one_way_cost,
        )

    compare_rows = [
        _compare_row_from_signal_body(sid, by_signal[sid])
        for sid in (SIGNAL_ID_MARGIN_CHANGE, SIGNAL_ID_SHORT_RATIO_DELTA)
    ]

    batch_summary: dict[str, Any] = {
        "version": "extra-hyp-multisignal-nextday-batch/v1",
        "job_id": jid,
        "pipeline": "extra_hyp_signals_compare",
        "signal_ids": [SIGNAL_ID_MARGIN_CHANGE, SIGNAL_ID_SHORT_RATIO_DELTA],
        "definitions": extra_hyp_definitions(section=section),
        "feature_ids": list(feature_ids),
        "short_ratio_section": section,
        "dataset_ids": list(dataset_ids),
        "period_start": start,
        "period_end": end,
        "codes": list(selected_codes),
        "n_codes": len(selected_codes),
        "n_days": len(day_results),
        "as_of_days": [d.get("date") for d in day_results],
        "history_source": hist_src,
        "tip_plane": (
            tip_feature_extract.get("plane")
            if hist_src == "r2"
            else "D1_hot_tip"
        ),
        "tip_extracted_row_counts": tip_feature_extract.get("extracted_row_counts"),
        "by_signal": by_signal,
        "compare_table": compare_rows,
        "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
        "executed_at_utc": executed_at,
        "artifact": {
            "bucket": RESEARCH_ARTIFACT_BUCKET,
            "prefix": prefix,
            "batch_summary_r2_key": batch_key,
        },
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "order_execution": False,
        "local_sot": False,
        "densify": False,
        "label": NEXTDAY_RESEARCH_LABEL,
        "cost_label": RESEARCH_COST_LABEL,
        "significance_claimed": False,
        "edge_claimed": False,
        "operational_go": False,
        "not_s1_rehash": True,
        "note": (
            "S4/S5 research hypotheses (margin change / short ratio Δ). "
            "小サンプル / 研究用・未宣言. Not READY. No Mass. No densify invent."
        ),
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
        )

    puts.append(_put(batch_key, batch_summary))
    if write_per_day_artifacts:
        for d in day_results:
            date_s = str(d.get("date") or "")[:10]
            day_key = f"{prefix}/days/date={date_s}/signals.json"
            puts.append(_put(day_key, d))

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
        attach_nextday_returns=True,
        version="extra-hyp-multisignal-nextday-eval/v1",
    )


def execute_multiday_multisignal_compare(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "w0815ay-g2-multisignal",
    codes: Sequence[str] | None = None,
    as_of_days: Sequence[str] | None = None,
    max_days: int = 20,
    min_days: int = 5,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    volume_sign_abs_min: float = DEFAULT_VOLUME_SIGN_ABS_MIN,
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
    write_per_day_artifacts: bool = True,
    dry_run: bool = False,
    d1_execute: D1ExecuteFn | None = None,
    r2_put: R2PutFn | None = None,
    staging_dir: str | Path | None = None,
    wrangler: str | Path | None = None,
    wrangler_config: str | Path | None = None,
    history_source: str = "d1_tip",
    r2_object_keys_by_dataset: Mapping[str, Sequence[str]] | None = None,
    r2_local_paths_by_dataset: Mapping[str, Sequence[str | Path]] | None = None,
    r2_raw_lines_by_dataset: Mapping[str, Sequence[Any]] | None = None,
    r2_get: Callable[[str, str], bytes] | None = None,
    r2_bucket: str = "quant-structured",
    r2_allow_empty_datasets: Sequence[str] | None = None,
) -> MultidaySignalEval:
    """Multi-signal compare (approved legs only).

    Signals (all candidate; candidate_only=False; not READY):

    1. ``c21_topix_relative_sign`` — baseline sign(topix_relative_1d)
    2. ``c21_volume_change_sign`` — sign(volume_change_1d) with abs threshold
    3. ``c21_topix_rel_disclosure_filter`` — topix relative + disclosure filter

    Same codes / as_of days / next-day returns across signals. Optional
    research-only net PnL under one-way 10bp cost (仮定に依存・研究用・運用GOではない).

    ``history_source``:
        * ``"d1_tip"`` (default) — CF D1 hot tip extract
        * ``"r2"`` — R2 structured history bridge

    Does **not** connect Mass, mint READY, densify, or execute orders.
    """
    assert_mass_and_phase7_off()
    start, end, jid = _require_job_window(period_start, period_end, job_id)
    _ = min_days

    dataset_ids = require_complete_21_only(
        MULTI_SIGNAL_DATASETS, context="multisignal compare datasets"
    )
    selected_codes = _select_codes(codes)
    feature_ids = tuple(MULTI_SIGNAL_FEATURE_IDS)
    definitions = {
        d["signal_id"]: d
        for d in multi_signal_definitions(volume_sign_abs_min=volume_sign_abs_min)
    }

    hist_src, tip_feature_extract = _load_history_feature_rows(
        dataset_ids,
        period_start=start,
        period_end=end,
        codes=selected_codes,
        feature_row_limit=feature_row_limit,
        history_source=history_source,
        d1_execute=d1_execute,
        r2_object_keys_by_dataset=r2_object_keys_by_dataset,
        r2_local_paths_by_dataset=r2_local_paths_by_dataset,
        r2_raw_lines_by_dataset=r2_raw_lines_by_dataset,
        r2_get=r2_get,
        r2_bucket=r2_bucket,
        r2_allow_empty_datasets=r2_allow_empty_datasets
        or (
            "fins_summary",
            "markets_margin_interest",
        ),
        context="multisignal feature extract",
    )
    rows_by_ds = tip_feature_extract.get("rows_by_dataset") or {}
    if codes is None and tip_feature_extract.get("selected_codes"):
        selected_codes = list(tip_feature_extract["selected_codes"])

    full_trading_days, next_map, close_index = _nextday_setup(
        rows_by_ds, period_start=start, period_end=end
    )
    day_list = _cap_as_of_days(as_of_days, full_trading_days, max_days)
    if not day_list:
        raise SingleShotJobError(
            "multisignal compare: no trading days found in tip window "
            f"{start}..{end}"
        )

    paths = design_artifact_paths(jid)
    prefix = str(paths["prefix"])
    batch_key = f"{prefix}/batch_summary.json"
    executed_at = _now_utc()

    # Per-signal accumulation of aligned rows across days.
    signal_day_rows: dict[str, list[list[dict[str, Any]]]] = {
        SIGNAL_ID_TOPIX_REL: [],
        SIGNAL_ID_VOLUME_SIGN: [],
        SIGNAL_ID_TOPIX_DISC: [],
    }
    day_results: list[dict[str, Any]] = []

    for d in day_list:
        as_of = session_close_as_of(d)
        feature_payload = compute_tip_candidate_features(
            rows_by_ds,
            as_of=as_of,
            feature_ids=feature_ids,
            codes=selected_codes,
            dates=[d],
        )
        obs = feature_payload.get("observations") or []

        s1 = compute_signal_from_feature_observations(
            obs,
            as_of=as_of,
            volume_change_abs_min=None,  # baseline: volume gate off
            codes=selected_codes,
        )
        s2 = compute_volume_sign_from_feature_observations(
            obs,
            as_of=as_of,
            volume_change_abs_min=volume_sign_abs_min,
            codes=selected_codes,
        )
        s3 = compute_topix_disc_from_feature_observations(
            obs,
            as_of=as_of,
            codes=selected_codes,
        )

        nxt = next_map.get(d)
        eval_as_of = session_close_as_of(nxt) if nxt else None
        per_signal_day: dict[str, Any] = {}
        for sid, core in (
            (SIGNAL_ID_TOPIX_REL, s1),
            (SIGNAL_ID_VOLUME_SIGN, s2),
            (SIGNAL_ID_TOPIX_DISC, s3),
        ):
            aligned = attach_next_day_returns(
                list(core.get("observations") or []),
                signal_date=d,
                next_date=nxt,
                close_index=close_index,
                evaluation_as_of=eval_as_of,
                feature_as_of=as_of,
            )
            costed = attach_research_cost_fields(aligned, one_way_cost=one_way_cost)
            signal_day_rows[sid].append(costed)
            day_summary = summarize_signal_day(
                {**core, "observations": costed}, as_of=as_of
            )
            day_summary["nextday_day_summary"] = summarize_nextday_by_sign(costed)
            day_summary["research_cost_day"] = summarize_research_cost(
                costed, one_way_cost=one_way_cost
            )
            day_summary["observations"] = costed
            day_summary["next_day_date"] = nxt
            day_summary["evaluation_as_of"] = eval_as_of
            day_summary["feature_as_of"] = as_of
            day_summary["definition"] = definitions.get(sid)
            per_signal_day[sid] = day_summary

        day_results.append(
            {
                "date": d,
                "as_of": as_of,
                "feature_as_of": as_of,
                "next_day_date": nxt,
                "evaluation_as_of": eval_as_of,
                "feature_ids": list(feature_ids),
                "feature_tip_input_row_counts": feature_payload.get(
                    "tip_input_row_counts"
                ),
                "codes": list(selected_codes),
                "signals": per_signal_day,
                "attach_nextday_returns": True,
                "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
                "label": NEXTDAY_RESEARCH_LABEL,
                "cost_label": RESEARCH_COST_LABEL,
                "local_sot": False,
                "mass_research": MASS_RESEARCH_STATUS,
                "phase7": PHASE7_STATUS,
                "ready_declared": READY_DECLARED,
                "order_execution": False,
            }
        )

    # Per-signal batch summaries.
    by_signal: dict[str, Any] = {}
    for sid in (SIGNAL_ID_TOPIX_REL, SIGNAL_ID_VOLUME_SIGN, SIGNAL_ID_TOPIX_DISC):
        by_signal[sid] = _summarize_one_signal_batch(
            signal_day_rows[sid],
            signal_id=sid,
            definition=definitions.get(sid) or {},
            one_way_cost=one_way_cost,
        )

    compare_rows = [
        _compare_row_from_signal_body(sid, by_signal[sid])
        for sid in (SIGNAL_ID_TOPIX_REL, SIGNAL_ID_VOLUME_SIGN, SIGNAL_ID_TOPIX_DISC)
    ]

    batch_summary: dict[str, Any] = {
        "version": "multiday-multisignal-nextday-batch/v1",
        "job_id": jid,
        "pipeline": "multi_signal_compare",
        "signal_ids": [
            SIGNAL_ID_TOPIX_REL,
            SIGNAL_ID_VOLUME_SIGN,
            SIGNAL_ID_TOPIX_DISC,
        ],
        "definitions": multi_signal_definitions(
            volume_sign_abs_min=volume_sign_abs_min
        ),
        "feature_ids": list(feature_ids),
        "feature_status_pins": {
            "topix_relative_1d": "approved",
            "is_trading_day": "approved",
            "volume_change_1d": "approved",
            "disclosure_flag_fins": "approved",
            "margin_interest_change_1d": "approved",
        },
        "approved_legs_only": True,
        "volume_sign_abs_min": volume_sign_abs_min,
        "dataset_ids": list(dataset_ids),
        "period_start": start,
        "period_end": end,
        "codes": list(selected_codes),
        "n_codes": len(selected_codes),
        "n_days": len(day_results),
        "as_of_days": [d.get("date") for d in day_results],
        "history_source": hist_src,
        "tip_plane": (
            tip_feature_extract.get("plane")
            if hist_src == "r2"
            else "D1_hot_tip"
        ),
        "d1_database": D1_DATABASE_NAME if hist_src == "d1_tip" else None,
        "tip_extracted_row_counts": tip_feature_extract.get("extracted_row_counts"),
        "tip_raw_tip_counts": tip_feature_extract.get("raw_tip_counts")
        or tip_feature_extract.get("raw_envelope_counts"),
        "history_source_channels": tip_feature_extract.get("source_channels"),
        "available_at_repairs": tip_feature_extract.get("available_at_repairs"),
        "by_signal": by_signal,
        "compare_table": compare_rows,
        "research_cost_assumption": {
            "one_way_cost_bp": one_way_cost * 10_000.0,
            "one_way_cost": float(one_way_cost),
            "round_trip_cost_bp": one_way_cost * 2.0 * 10_000.0,
            "round_trip_cost": float(one_way_cost) * 2.0,
            "label": RESEARCH_COST_LABEL,
            "note": RESEARCH_COST_NOTE,
        },
        "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
        "per_day_compact": [
            {
                "date": d.get("date"),
                "as_of": d.get("as_of"),
                "next_day_date": d.get("next_day_date"),
                "signals": {
                    sid: {
                        "signal_count": (d.get("signals") or {})
                        .get(sid, {})
                        .get("signal_count"),
                        "non_null": (d.get("signals") or {})
                        .get(sid, {})
                        .get("non_null"),
                        "sign_distribution": (d.get("signals") or {})
                        .get(sid, {})
                        .get("sign_distribution"),
                        "nextday_day_summary": (d.get("signals") or {})
                        .get(sid, {})
                        .get("nextday_day_summary"),
                    }
                    for sid in (
                        SIGNAL_ID_TOPIX_REL,
                        SIGNAL_ID_VOLUME_SIGN,
                        SIGNAL_ID_TOPIX_DISC,
                    )
                },
            }
            for d in day_results
        ],
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
        "attach_nextday_returns": True,
        "label": NEXTDAY_RESEARCH_LABEL,
        "cost_label": RESEARCH_COST_LABEL,
        "significance_claimed": False,
        "edge_claimed": False,
        "operational_go": False,
        "note": (
            "Multi-signal compare via single_shot only "
            f"(history_source={hist_src}). "
            "Three approved-leg research signals on the same universe/period. "
            "Next-day returns + optional research cost (10bp one-way). "
            "小サンプル / 研究用・未宣言 · 仮定に依存・研究用・運用GOではない. "
            "Not READY. Not mass research. No order execution. No densify."
        ),
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
        )

    puts.append(_put(batch_key, batch_summary))

    if write_per_day_artifacts:
        for d in day_results:
            date_s = str(d.get("date") or "")[:10]
            day_key = f"{prefix}/days/date={date_s}/signals.json"
            # Drop heavy observation lists from R2 day body size if needed —
            # keep them for research transparency (same as prior waves).
            day_body = {
                "version": "multiday-multisignal-nextday-day/v1",
                "job_id": jid,
                **{k: d[k] for k in d},
                "mass_research": MASS_RESEARCH_STATUS,
                "phase7": PHASE7_STATUS,
                "ready_declared": READY_DECLARED,
                "order_execution": False,
                "local_sot": False,
                "label": NEXTDAY_RESEARCH_LABEL,
                "cost_label": RESEARCH_COST_LABEL,
            }
            puts.append(_put(day_key, day_body))
            d["signals_r2_key"] = day_key

    manifest_key = str(paths["manifest_r2_key"])
    manifest = {
        "version": "multiday-multisignal-nextday-manifest/v1",
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
        "n_codes": len(selected_codes),
        "as_of_days": [d.get("date") for d in day_results],
        "codes": list(selected_codes),
        "signal_ids": list(batch_summary["signal_ids"]),
        "compare_table": compare_rows,
        "executed_at_utc": executed_at,
        "dry_run": bool(dry_run),
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "ready_publication": READY_PUBLICATION_STATUS,
        "order_execution": False,
        "local_sot": False,
        "connected_to_mass_research_loop": False,
        "attach_nextday_returns": True,
        "label": NEXTDAY_RESEARCH_LABEL,
        "cost_label": RESEARCH_COST_LABEL,
        "operational_go": False,
        "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
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
        attach_nextday_returns=True,
        version="multiday-multisignal-nextday-eval/v1",
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
