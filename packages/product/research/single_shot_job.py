"""Single-shot research job (Mass OFF / Phase7 OFF / READY not declared).

W49 skeleton (declare + path design) + W50 minimal CF-backed execute:

* **Inputs:** COMPLETE 21 dataset ids only (permanent DEFER excluded via
  ``data_contracts.permanent_defer``).
* **Read:** CF D1 ``quant-ingest`` hot tip extract (bounded; not full-history SoT).
* **Write:** R2 ``quant-structured`` under ``research/single_shot/job={id}/…``.
  Local FS is **not** Source of Truth (optional dry-run stages payloads only).
* **Not** connected to ``agents.mass_research`` / mass research loop.
* Does **not** set READY / mint readiness / arm Phase7.

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
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
    reject_permanent_defer_for_history,
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
                "local_sot": self.local_sot,
            },
            "mass_research": self.mass_research,
            "phase7": self.phase7,
            "ready_declared": self.ready_declared,
            "ready_publication": READY_PUBLICATION_STATUS,
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
        "local_sot": False,
        "artifact_bucket": RESEARCH_ARTIFACT_BUCKET,
        "artifact_prefix": RESEARCH_ARTIFACT_PREFIX,
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
            "tip_extracts": dict(self.tip_extracts),
            "r2_puts": list(self.r2_puts),
            "spec": self.spec.to_dict(),
            "mass_research": self.mass_research,
            "phase7": self.phase7,
            "ready_declared": self.ready_declared,
            "ready_publication": READY_PUBLICATION_STATUS,
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
    d1_execute / r2_put:
        Injectable callables for unit tests. Defaults use wrangler remote.

    Never connects to mass research, never sets READY, never arms Phase7.
    """
    assert_mass_and_phase7_off()
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

    executed_at = _now_utc()
    # Hash identity excludes wall-clock so re-runs with same tip facts are stable
    # when counts match; executed_at lives only in outer envelopes.
    result_identity = {
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
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "ready_publication": READY_PUBLICATION_STATUS,
        "local_sot": False,
    }
    ch = content_hash_payload(result_identity)
    result_key = spec.result_r2_key_template.format(content_hash=ch.replace(":", "_"))

    result_body = {
        **result_identity,
        "content_hash": ch,
        "executed_at_utc": executed_at,
        "artifact": {
            "bucket": spec.artifact_bucket,
            "result_r2_key": result_key,
            "manifest_r2_key": spec.manifest_r2_key,
            "input_plan_r2_key": spec.input_plan_r2_key,
        },
        "sample_rows": {
            ds: body.get("sample_rows") or []
            for ds, body in (tip.get("extracts") or {}).items()
        },
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
        "history_sot_note": (
            "Full history SoT is R2 quant-structured JSONL/archive; "
            "this job only reads D1 hot tip for a bounded proof pass."
        ),
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
    }

    manifest = {
        "version": "single-shot-manifest/v1",
        "job_id": spec.job_id,
        "bucket": spec.artifact_bucket,
        "prefix": spec.artifact_prefix,
        "keys": {
            "manifest": spec.manifest_r2_key,
            "input_plan": spec.input_plan_r2_key,
            "result": result_key,
        },
        "content_hash": ch,
        "dataset_ids": list(spec.dataset_ids),
        "period_start": spec.period_start,
        "period_end": spec.period_end,
        "tip_row_counts": {
            ds: int((body or {}).get("row_count") or 0)
            for ds, body in (tip.get("extracts") or {}).items()
        },
        "executed_at_utc": executed_at,
        "dry_run": bool(dry_run),
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "ready_publication": READY_PUBLICATION_STATUS,
        "local_sot": False,
        "connected_to_mass_research_loop": False,
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
        mass_research=MASS_RESEARCH_STATUS,
        phase7=PHASE7_STATUS,
        ready_declared=READY_DECLARED,
        local_sot=False,
    )


__all__ = [
    "COMPLETE_21_DATASETS",
    "COMPLETE_21_DATASET_SET",
    "D1_DATABASE_NAME",
    "DEFAULT_TIP_SAMPLE_LIMIT",
    "MASS_RESEARCH_ENV_ARMING_SWITCHES",
    "MASS_RESEARCH_STATUS",
    "PHASE7_ENV_ARMING_SWITCHES",
    "PHASE7_STATUS",
    "READY_DECLARED",
    "READY_PUBLICATION_STATUS",
    "RESEARCH_ARTIFACT_BUCKET",
    "RESEARCH_ARTIFACT_PREFIX",
    "PermanentDeferHistoryError",
    "SingleShotExecution",
    "SingleShotJobError",
    "SingleShotJobSpec",
    "assert_mass_and_phase7_off",
    "build_single_shot_job_spec",
    "content_hash_payload",
    "default_d1_execute",
    "default_r2_put",
    "design_artifact_paths",
    "execute_single_shot_job",
    "extract_d1_tip_summaries",
    "freeze_status",
    "head_r2_object",
    "require_complete_21_only",
]
