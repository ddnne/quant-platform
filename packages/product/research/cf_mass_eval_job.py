"""CF multi-logic × multi-period mass-eval job spec / panel cache.

Worker: ``platform/workers/research-mass-eval``. Staging: ``cf_mass_eval_stage``.
Run/invoke: ``cf_mass_eval_run``. Period-net n_survivors is not a pass / not GO.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from research.bar_native_specs import BAR_NATIVE_SPECS
from research.cf_mass_eval_stage import (
    COMPLETE_22_DATASETS,
    COMPLETE_22_DATASET_SET,
    DEFAULT_MAX_CODES,
    DEFAULT_MAX_DAYS,
    PRIMARY_BARS_DATASET,
    PRIMARY_INDEX_DATASETS,
    RESEARCH_ARTIFACT_BUCKET,
    RESEARCH_ARTIFACT_PREFIX,
    THICKEN_PANEL_DATASETS,
    build_real_period_panel,
    inventory_complete22,
    normalize_period_row,
    stage_real_panels_to_r2,
)
from research.eval_windows import DEFAULT_REAL_MULTIYEAR_PERIODS
from research.freezes import CONTINUOUS_PAPER, MASS_RESEARCH, PHASE7
from research.single_shot_job import default_r2_put

CF_MASS_EVAL_VERSION: str = "cf-mass-eval-job/v6"
CF_MASS_EVAL_WAVE: str = "research-mass-eval"
DEFAULT_WORKER_NAME: str = "quant-platform-research-mass-eval"
DEFAULT_WORKER_URL: str = (
    "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
)
DEFAULT_ONE_WAY: float = 0.001

DEFAULT_MASS_EVAL_MODE: str = "r2_panels"
ALLOWED_MODES: frozenset[str] = frozenset(
    {"r2_panels", "d1_bars", "synthetic", "nets_only"}
)

CF_BAR_NATIVE_LOGIC_IDS: tuple[str, ...] = tuple(BAR_NATIVE_SPECS)

DEFAULT_LITE_PERIODS: tuple[dict[str, str], ...] = (
    {"period_id": "p2024_q4", "start": "2024-10-01", "end": "2024-12-27"},
    {"period_id": "p2025_q1", "start": "2025-01-06", "end": "2025-03-28"},
    {"period_id": "p2025_q2", "start": "2025-04-01", "end": "2025-06-27"},
    {"period_id": "p2025_q3", "start": "2025-07-01", "end": "2025-09-26"},
    {"period_id": "p2025_q4", "start": "2025-10-01", "end": "2025-12-26"},
    {"period_id": "p2026_h1", "start": "2026-01-05", "end": "2026-06-30"},
)

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
_WORKER_DIR = _REPO_ROOT / "platform" / "workers" / "research-mass-eval"
_WORKER_CONFIG = _WORKER_DIR / "wrangler.toml"


class CfMassEvalError(RuntimeError):
    """CF mass-eval job failed."""


def _freeze() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": False,
        "operational_go": False,
        "continuous_paper": CONTINUOUS_PAPER,
        "live_orders": False,
        "s1_s5_unreject": False,
        "simple_daily_sign_as_diversity": False,
        "frozen_defaults_retuned": False,
        "factory_version": CF_MASS_EVAL_VERSION,
    }


def resolve_research_run_token() -> str | None:
    """Token that gates the mass-eval Worker (reuses ingestion run token)."""
    for env_name in (
        "RESEARCH_RUN_TOKEN",
        "INGESTION_RUN_TOKEN",
        "MASS_EVAL_RUN_TOKEN",
    ):
        v = (os.environ.get(env_name) or "").strip()
        if v:
            return v
    for name in ("ingestion_run_token", "data_export_token"):
        p = Path.home() / ".config" / "quant-platform" / name
        if p.is_file():
            try:
                t = p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
                if t:
                    return t
            except OSError:
                continue
    return None


def design_mass_factory_paths(job_id: str) -> dict[str, Any]:
    jid = str(job_id).strip() or "unknown"
    prefix = f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}"
    return {
        "bucket": RESEARCH_ARTIFACT_BUCKET,
        "prefix": prefix,
        "job_id": jid,
        "manifest_r2_key": f"{prefix}/manifest.json",
        "input_plan_r2_key": f"{prefix}/input_plan.json",
        "batch_summary_r2_key": f"{prefix}/batch_summary.json",
        "results_r2_key": f"{prefix}/results.json",
        "screens_r2_key": f"{prefix}/screens.json",
        "ranking_r2_key": f"{prefix}/ranking.json",
    }


def is_unique_period_net_unsupported(logic_id: str) -> bool:
    """Unique event/CS theses are not evaluable on period-net mass-eval."""
    from research.unique_logic.constants import (
        CF_EVENT_DAILY_PATH_IDS,
        CF_NEW_CS_THESIS_IDS,
        CS_LOGIC_IDS,
    )

    lid = str(logic_id or "")
    if lid in CF_EVENT_DAILY_PATH_IDS or lid in CF_NEW_CS_THESIS_IDS or lid in CS_LOGIC_IDS:
        return True
    return (
        lid.startswith("event_")
        or lid.startswith("surprise_xs")
        or lid.startswith("cs_")
    )


def default_logic_specs(
    logic_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """CF-ready specs from catalog/YAML. Leftover unknown ids get family_id=unknown."""
    ids = list(logic_ids) if logic_ids is not None else list(CF_BAR_NATIVE_LOGIC_IDS)
    out: list[dict[str, Any]] = []
    from research.unique_logic import all_unique_logic_specs
    from research.unique_logic.catalog import load_catalog_specs

    py_by_id = {str(s.get("logic_id")): s for s in all_unique_logic_specs()}
    yaml_by_id = {str(s.get("logic_id")): s for s in load_catalog_specs()}
    for lid in ids:
        spec = py_by_id.get(str(lid)) or yaml_by_id.get(str(lid))
        if spec:
            params = dict(spec.get("params") or {})
            g = params.get("gates")
            if isinstance(g, str):
                params["gates"] = [
                    x.strip()
                    for x in g.split(",")
                    if x.strip() and x.strip() != "None"
                ]
            elif g is None and spec.get("gates") is not None:
                params["gates"] = list(spec.get("gates") or [])
            out.append(
                {
                    "logic_id": str(spec.get("logic_id") or lid),
                    "family_id": str(spec.get("family_id") or "unique_logic"),
                    "params": params,
                    "thesis": spec.get("thesis") or "",
                    "signal_definition": spec.get("signal_definition") or "",
                    "position_rule": spec.get("position_rule") or "",
                    "datasets_used": list(spec.get("datasets") or []),
                }
            )
            continue
        row = BAR_NATIVE_SPECS.get(str(lid))
        if row is None:
            out.append(
                {
                    "logic_id": lid,
                    "family_id": "unknown",
                    "params": {},
                    "thesis": "",
                    "signal_definition": "",
                    "position_rule": "",
                    "datasets_used": [],
                }
            )
            continue
        out.append(
            {
                "logic_id": row["logic_id"],
                "family_id": row["family_id"],
                "params": dict(row.get("params") or {}),
                "thesis": row.get("thesis") or "",
                "signal_definition": row.get("signal_definition") or "",
                "position_rule": row.get("position_rule") or "",
                "datasets_used": list(row.get("datasets_used") or []),
            }
        )
    return out


PANELS_CACHE_PREFIX = "research/mass_eval/panels_cache"


def panels_cache_id(
    periods: Sequence[Mapping[str, Any]],
    *,
    max_codes: int,
    max_days: int,
    track: str | None = None,
) -> str:
    from research.eval_tracks import infer_eval_track

    tid = str(track or infer_eval_track(max_codes=max_codes))
    ids = ",".join(str(p.get("period_id") or "") for p in periods)
    raw = f"v11_track|{tid}|{ids}|c{int(max_codes)}|d{int(max_days)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def try_r2_get_json(key: str) -> dict[str, Any] | None:
    """Best-effort remote R2 JSON get via wrangler (None if missing)."""
    wr = _DEFAULT_WRANGLER
    cfg = (
        _REPO_ROOT
        / "platform"
        / "workers"
        / "ingestion-premium"
        / "wrangler.toml"
    )
    wr_bin = str(wr) if wr.is_file() else "npx"
    cmd = [wr_bin] if wr.is_file() else ["npx", "wrangler"]
    cmd += [
        "r2",
        "object",
        "get",
        f"{RESEARCH_ARTIFACT_BUCKET}/{key}",
        "--pipe",
        f"--config={cfg}",
        "--remote",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cfg.parent),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        obj = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def resolve_or_stage_panels(
    *,
    job_id: str,
    periods: Sequence[Mapping[str, Any]] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    force_stage: bool = False,
    staging_dir: str | Path | None = None,
    track: str | None = None,
) -> dict[str, Any]:
    """Reuse track×periods×codes×days panel cache, or stage once. Never head-N."""
    from research.eval_tracks import eval_track, infer_eval_track
    from research.eval_universe import select_eval_universe

    t0 = time.perf_counter()
    period_rows = [
        normalize_period_row(p)
        for p in (periods or DEFAULT_REAL_MULTIYEAR_PERIODS)
    ]
    tid = str(track or infer_eval_track(max_codes=max_codes))
    tspec = eval_track(tid)
    cid = panels_cache_id(
        period_rows, max_codes=max_codes, max_days=max_days, track=tid
    )
    meta_key = f"{PANELS_CACHE_PREFIX}/{cid}/meta.json"
    prefix = f"{PANELS_CACHE_PREFIX}/{cid}/panels"

    if not force_stage:
        existing = try_r2_get_json(meta_key)
        if existing and int(existing.get("n_ok") or 0) > 0:
            existing["reused"] = True
            existing["force_stage"] = False
            existing["stage_sec"] = 0.0
            existing["cache_id"] = cid
            existing["meta_key"] = meta_key
            return existing
    selected_codes = select_eval_universe(max_codes=int(max_codes))
    staged = stage_real_panels_to_r2(
        job_id,
        period_rows,
        codes=selected_codes,
        max_codes=max_codes,
        max_days=max_days,
        staging_dir=staging_dir,
        panels_prefix=prefix,
    )
    stage_sec = round(time.perf_counter() - t0, 3)
    meta = {
        "cache_id": cid,
        "meta_key": meta_key,
        "panels_prefix": prefix,
        "n_ok": int(staged.get("n_ok") or 0),
        "n_periods": int(staged.get("n_periods") or 0),
        "max_codes": int(max_codes),
        "max_days": int(max_days),
        "universe_select": tspec["universe_select"],
        "eval_track": tid,
        "n_selected_codes": len(selected_codes),
        "selected_codes": list(selected_codes),
        "period_ids": [p.get("period_id") for p in period_rows],
        "reused": False,
        "force_stage": bool(force_stage),
        "stage_sec": stage_sec,
        "job_id_staged": str(job_id),
    }
    try:
        default_r2_put(
            RESEARCH_ARTIFACT_BUCKET,
            meta_key,
            json.dumps(meta, indent=2, default=str).encode("utf-8"),
        )
    except Exception:
        meta["meta_put_error"] = True
    meta["stage"] = {k: staged.get(k) for k in ("n_ok", "n_missing", "dataset")}
    return meta


def build_cf_mass_eval_job_spec(
    *,
    job_id: str | None = None,
    logic_ids: Sequence[str] | None = None,
    periods: Sequence[Mapping[str, Any]] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY,
    seed: int = 870816,
    extra_logics: Sequence[Mapping[str, Any]] | None = None,
    mode: str = DEFAULT_MASS_EVAL_MODE,
    panels_prefix: str | None = None,
    drop_unique_unsupported: bool = True,
) -> dict[str, Any]:
    """Declarative job payload for the CF mass-eval Worker."""
    mode_s = str(mode or DEFAULT_MASS_EVAL_MODE).strip()
    if mode_s not in ALLOWED_MODES:
        raise CfMassEvalError(
            f"mode must be one of {sorted(ALLOWED_MODES)}, got {mode_s!r}"
        )
    jid = str(job_id or f"mass-eval-{uuid4().hex[:12]}")
    paths = design_mass_factory_paths(jid)
    logics = default_logic_specs(logic_ids)
    if extra_logics:
        for raw in extra_logics:
            logics.append(dict(raw))
    dropped_unique: list[str] = []
    if drop_unique_unsupported:
        dropped_unique = [
            str(L.get("logic_id") or "")
            for L in logics
            if is_unique_period_net_unsupported(str(L.get("logic_id") or ""))
        ]
        logics = [
            L
            for L in logics
            if not is_unique_period_net_unsupported(str(L.get("logic_id") or ""))
        ]
    default_periods: Sequence[Mapping[str, Any]] = (
        DEFAULT_REAL_MULTIYEAR_PERIODS
        if mode_s in {"r2_panels", "d1_bars"}
        else DEFAULT_LITE_PERIODS
    )
    period_rows = [
        normalize_period_row(p) for p in (periods or default_periods)
    ]
    pfx = panels_prefix or f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}/panels"
    return {
        "version": CF_MASS_EVAL_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "job_id": jid,
        "seed": int(seed),
        "mode": mode_s,
        "panels_prefix": pfx,
        "logics": logics,
        "dropped_unique_unsupported": dropped_unique,
        "unique_unsupported_on_period_net": True,
        "candidate_eval_sot": "daily_path_mtm_after_cost/v1",
        "periods": period_rows,
        "max_codes": int(max_codes),
        "max_days": int(max_days),
        "one_way_cost": float(one_way_cost),
        "artifact": paths,
        "freezes": _freeze(),
        "mass_research": MASS_RESEARCH,
        "ready_declared": False,
        "operational_go": False,
        "continuous_paper": CONTINUOUS_PAPER,
    }


from research.cf_mass_eval_run import (  # noqa: E402
    deploy_cf_mass_eval_worker,
    invoke_cf_mass_eval_worker,
    put_local_fallback_artifacts,
    run_cf_mass_eval_job,
    try_cf_mass_eval_status,
)


__all__ = [
    "CF_MASS_EVAL_VERSION",
    "CF_MASS_EVAL_WAVE",
    "CF_BAR_NATIVE_LOGIC_IDS",
    "COMPLETE_22_DATASETS",
    "COMPLETE_22_DATASET_SET",
    "PRIMARY_BARS_DATASET",
    "PRIMARY_INDEX_DATASETS",
    "THICKEN_PANEL_DATASETS",
    "DEFAULT_LITE_PERIODS",
    "DEFAULT_REAL_MULTIYEAR_PERIODS",
    "DEFAULT_MASS_EVAL_MODE",
    "ALLOWED_MODES",
    "DEFAULT_WORKER_URL",
    "RESEARCH_ARTIFACT_BUCKET",
    "RESEARCH_ARTIFACT_PREFIX",
    "CfMassEvalError",
    "resolve_research_run_token",
    "design_mass_factory_paths",
    "default_logic_specs",
    "resolve_or_stage_panels",
    "panels_cache_id",
    "PANELS_CACHE_PREFIX",
    "normalize_period_row",
    "inventory_complete22",
    "build_real_period_panel",
    "stage_real_panels_to_r2",
    "build_cf_mass_eval_job_spec",
    "invoke_cf_mass_eval_worker",
    "deploy_cf_mass_eval_worker",
    "put_local_fallback_artifacts",
    "run_cf_mass_eval_job",
    "try_cf_mass_eval_status",
]
