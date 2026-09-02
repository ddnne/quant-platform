"""CF multi-logic × multi-period mass-eval job spec / panel cache. Not a pass / not GO."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

_DEFAULT_WRANGLER = None
DEFAULT_RESEARCH_WORKER_URL = (
    "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
)
from qp_paths import repo_root as _qp_repo_root
from research.bar_native_specs import BAR_NATIVE_SPECS
from research.cf_mass_eval_stage import (
    DEFAULT_MAX_CODES,
    DEFAULT_MAX_DAYS,
    RESEARCH_ARTIFACT_BUCKET,
    RESEARCH_ARTIFACT_PREFIX,
    normalize_period_row,
    stage_real_panels_to_r2,
)
from research.eval_windows import DEFAULT_REAL_MULTIYEAR_PERIODS
from research.freezes import CONTINUOUS_PAPER, MASS_RESEARCH, PHASE7
from research.research_capabilities import require_capability

CF_MASS_EVAL_VERSION: str = "cf-mass-eval-job/v6"
CF_MASS_EVAL_WAVE: str = "research-mass-eval"
DEFAULT_WORKER_URL: str = DEFAULT_RESEARCH_WORKER_URL
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

_REPO_ROOT = _qp_repo_root()
_WORKER_DIR = _REPO_ROOT / "platform" / "workers" / "research-mass-eval"
_WORKER_CONFIG = _WORKER_DIR / "wrangler.toml"


class CfMassEvalError(RuntimeError):
    pass


def refuse_missing_capability(name: str) -> dict[str, Any] | None:
    """None if allowed. Else refuse pack. Env flags cannot grant. Not GO."""
    gate = require_capability(name)
    if gate.get("allowed"):
        return None
    return {
        "ok": False,
        "error": "capability_missing",
        "capability": str(gate.get("capability") or name),
        "reasons": list(gate.get("reasons") or []),
        "go": False,
        "not_a_pass": True,
    }


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
    from ops.research_token import resolve_research_run_token as _resolve

    return _resolve()


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
                }
            )
            continue
        out.append(
            {
                "logic_id": row["logic_id"],
                "family_id": row["family_id"],
                "params": dict(row.get("params") or {}),
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


def try_r2_get_json(
    key: str, *, getter: Callable[[str, str], dict[str, Any] | None] | None = None
) -> dict[str, Any] | None:
    """Product port: JSON result only. Operator I/O is injected."""

    if getter is None:
        raise RuntimeError("closed artifact get port is required")
    return getter(RESEARCH_ARTIFACT_BUCKET, key)


def resolve_or_stage_panels(
    *,
    job_id: str,
    periods: Sequence[Mapping[str, Any]] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    force_stage: bool = False,
    staging_dir: str | Path | None = None,
    track: str | None = None,
    artifact_put: Callable[..., Any] | None = None,
    artifact_get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Reuse track×periods×codes×days panel cache, or stage once. Never head-N."""
    from research.mass_disabled import refuse_mass_host_entrypoint

    refuse_mass_host_entrypoint("resolve_or_stage_panels")
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
        existing = try_r2_get_json(meta_key, getter=artifact_get)
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
        if artifact_put is None:
            raise RuntimeError("closed artifact put port is required")
        artifact_put(
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
    mode_s = str(mode or DEFAULT_MASS_EVAL_MODE).strip()
    if mode_s not in ALLOWED_MODES:
        raise CfMassEvalError(
            f"mode must be one of {sorted(ALLOWED_MODES)}, got {mode_s!r}"
        )
    jid = str(job_id or f"mass-eval-{uuid4().hex[:12]}")
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
        "freezes": _freeze(),
    }


def invoke_cf_mass_eval_worker(*args, **kwargs):
    from research.cf_mass_eval_run import invoke_cf_mass_eval_worker as invoke

    return invoke(*args, **kwargs)


def run_cf_mass_eval_job(*args, **kwargs):
    from research.cf_mass_eval_run import run_cf_mass_eval_job as run

    return run(*args, **kwargs)


def try_cf_mass_eval_status(*args, **kwargs):
    from research.cf_mass_eval_run import try_cf_mass_eval_status as status

    return status(*args, **kwargs)


__all__ = [
    "CF_MASS_EVAL_VERSION",
    "CF_MASS_EVAL_WAVE",
    "CF_BAR_NATIVE_LOGIC_IDS",
    "DEFAULT_LITE_PERIODS",
    "DEFAULT_REAL_MULTIYEAR_PERIODS",
    "DEFAULT_MASS_EVAL_MODE",
    "ALLOWED_MODES",
    "DEFAULT_WORKER_URL",
    "CfMassEvalError",
    "refuse_missing_capability",
    "resolve_research_run_token",
    "design_mass_factory_paths",
    "default_logic_specs",
    "resolve_or_stage_panels",
    "panels_cache_id",
    "PANELS_CACHE_PREFIX",
    "normalize_period_row",
    "build_cf_mass_eval_job_spec",
    "invoke_cf_mass_eval_worker",
    "run_cf_mass_eval_job",
    "try_cf_mass_eval_status",
]
