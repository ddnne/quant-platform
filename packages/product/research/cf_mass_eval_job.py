"""Cloudflare multi-logic × multi-period mass eval job.

Implements a real CF Worker path for evaluating **multiple economic logics**
across **multiple period windows**, writing artifacts to R2
``quant-structured`` under ``research/mass_eval/job={id}/…``.

Architecture
------------
* **Worker:** ``platform/workers/research-mass-eval`` (TypeScript)
  - ``mode=r2_panels`` — staged COMPLETE-backed real bars (preferred)
  - ``mode=d1_bars`` — D1 ``jquants_records`` tip extract (hot window only)
  - ``mode=synthetic`` — deterministic PRNG (smoke)
  - ``mode=nets_only`` — pre-baked period nets
  - Evaluates bar-native logics (mdh / xs / vol) across period shards
  - Writes summary/results/ranking to R2
* **Driver (this module):** builds job payload, stages real panels from
  local COMPLETE-backed R2 mirrors, invokes Worker via HTTPS,
  records job id / counts / artifact keys.
* **Staging:** ``research.cf_mass_eval_stage`` (sidecar panels, not SoT).

Multi-period policy
-------------------
* ≥4–6 multi-year windows (full-prefer 2015/19/21/23 + Q4 2017/25)
* max_codes default 100 (ADV-ranked, skip missing bars/TA/EqAR); max_days ≤ 200 per period (CF wall-clock)
* Heavy multi-year deep eval remains local offline eval for promising
  survivors only

Does **not** arm Mass / READY / GO / continuous paper / live.
Does **not** retune the three frozen default-path representatives.
Period-net screen survivors are **not** a pass (``daily_path_DD`` required).
Candidate-grade SoT is ``POST /v1/daily-path``. Unique event/CS logics are
**unsupported** on period-net (MDH collapse is tagged ``path_collapsed``
and cannot survive).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from data_contracts.permanent_defer import PERMANENT_DEFER_DATASETS
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

# Preferred default is real staged panels (not synthetic).
DEFAULT_MASS_EVAL_MODE: str = "r2_panels"
ALLOWED_MODES: frozenset[str] = frozenset(
    {"r2_panels", "d1_bars", "synthetic", "nets_only"}
)

# Bar-native logics the CF Worker can evaluate without extra panels.
# Catalog: research.bar_native_specs (not offline.factory).
# nky_vol_* need staged index closes (__NKY_PROXY__) in panels.
# opt225_* need staged opt225_regime maps (BaseVol/ATM IV/spread).
# macro_repo_rate_* consume staged repo_rate_regime when present.
# flow/fund/mf consume flow_regime / fund_regime (missing sidecar → disclosed MDH).
CF_BAR_NATIVE_LOGIC_IDS: tuple[str, ...] = tuple(BAR_NATIVE_SPECS)

# Lite multi-period shards (synthetic / tip smoke).
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
    """Build CF-ready logic specs.

    Unique/combo params (including ``gates``) come from Python catalog rows.
    YAML is declaration; it currently stores gates as a comma string.
    Bar-native ids come from ``bar_native_specs`` (not factory templates).
    Leftover unknown ids get ``family_id=unknown``.
    """
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
                "logic_fingerprint": row.get("logic_fingerprint") or "",
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
    """Reuse a content-keyed panel cache, or stage once and record meta on R2.

    Cache key is track × period_ids × max_codes × max_days. Subsequent
    fan-out jobs skip the serial stage. ``stage_sec`` is 0.0 on reuse.
    Selection is ADV/fins on every track — never head-N.
    """
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
        "datasets": {
            "primary_bars": PRIMARY_BARS_DATASET,
            "complete_22": list(COMPLETE_22_DATASETS),
            "permanent_defer": sorted(PERMANENT_DEFER_DATASETS),
        },
        "shard_policy": {
            "kind": (
                "real_multiyear_r2_panels"
                if mode_s == "r2_panels"
                else (
                    "d1_tip_bars"
                    if mode_s == "d1_bars"
                    else "lite_multi_period"
                )
            ),
            "note": (
                f"mode={mode_s}; ≤{max_codes} codes × ≤{max_days} days × "
                f"{len(period_rows)} periods × {len(logics)} logics. "
                "Heavy multi-year stays local for promising survivors. "
                "Default is real staged panels (not synthetic)."
            ),
        },
        "freezes": _freeze(),
        "mass_research": MASS_RESEARCH,
        "ready_declared": False,
        "operational_go": False,
        "continuous_paper": CONTINUOUS_PAPER,
    }


def invoke_cf_mass_eval_worker(
    job_spec: Mapping[str, Any],
    *,
    worker_url: str = DEFAULT_WORKER_URL,
    token: str | None = None,
    timeout: int = 120,
    http_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """POST job to CF Worker; return parsed JSON response."""
    url = worker_url.rstrip("/") + "/v1/mass-eval"
    tok = (token if token is not None else resolve_research_run_token()) or ""
    body = json.dumps(dict(job_spec), default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "quant-platform-cf-mass-eval/1.0",
    }
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
        headers["X-Research-Run-Token"] = tok
        headers["X-Mass-Eval-Token"] = tok
        headers["X-Ingestion-Token"] = tok

    t0 = time.perf_counter()
    if http_post is not None:
        raw_resp = http_post(url=url, body=body, headers=headers)
        latency = time.perf_counter() - t0
        if isinstance(raw_resp, Mapping):
            return {
                **dict(raw_resp),
                "invoke_latency_sec": round(latency, 3),
                "worker_url": url,
            }
        text = raw_resp if isinstance(raw_resp, str) else raw_resp.decode("utf-8")
        return {
            **json.loads(text),
            "invoke_latency_sec": round(latency, 3),
            "worker_url": url,
        }

    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:2000]
        except Exception:
            detail = str(exc)
        raise CfMassEvalError(
            f"CF mass-eval HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise CfMassEvalError(f"CF mass-eval network error: {exc}") from exc
    latency = time.perf_counter() - t0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CfMassEvalError(
            f"CF mass-eval non-json (HTTP {status}): {raw[:500]}"
        ) from exc
    if not isinstance(payload, dict):
        raise CfMassEvalError("CF mass-eval response not an object")
    payload["invoke_latency_sec"] = round(latency, 3)
    payload["worker_url"] = url
    payload["http_status"] = status
    return payload


def deploy_cf_mass_eval_worker(
    *,
    wrangler: str | Path | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    """Deploy the mass-eval Worker via wrangler (best-effort)."""
    wr = Path(wrangler) if wrangler else _DEFAULT_WRANGLER
    if not wr.is_file():
        alt = _WORKER_DIR / "node_modules" / ".bin" / "wrangler"
        wr = alt if alt.is_file() else wr
    if not wr.is_file():
        raise CfMassEvalError(f"wrangler not found: {wr}")
    if not _WORKER_CONFIG.is_file():
        raise CfMassEvalError(f"worker config missing: {_WORKER_CONFIG}")
    proc = subprocess.run(
        [str(wr), "deploy", f"--config={_WORKER_CONFIG}"],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(_WORKER_DIR),
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        raise CfMassEvalError(
            f"wrangler deploy failed rc={proc.returncode}: {combined[-2000:]}"
        )
    url = DEFAULT_WORKER_URL
    for line in combined.splitlines():
        if "workers.dev" in line and "https://" in line:
            for part in line.split():
                if part.startswith("https://") and "workers.dev" in part:
                    url = part.strip()
                    break
    return {
        "status": "deployed",
        "worker_url": url,
        "wrangler_rc": 0,
        "log_tail": combined[-1500:],
    }


def put_local_fallback_artifacts(
    job_spec: Mapping[str, Any],
    result_body: Mapping[str, Any],
    *,
    r2_put: Callable[..., Mapping[str, Any]] | None = None,
    dry_run: bool = False,
    staging_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Write job artifacts to R2 (or stage) from the driver side.

    Used after a successful Worker response (mirror) or when the Worker
    already wrote R2 (driver records the keys).
    """
    paths = design_mass_factory_paths(str(job_spec.get("job_id") or "unknown"))
    put_fn = r2_put or (
        lambda bucket, key, body: default_r2_put(
            bucket,
            key,
            body,
            dry_run=dry_run,
            staging_dir=staging_dir,
        )
    )
    puts: list[dict[str, Any]] = []
    artifacts = {
        paths["manifest_r2_key"]: {
            "job_id": job_spec.get("job_id"),
            "version": CF_MASS_EVAL_VERSION,
            "wave": CF_MASS_EVAL_WAVE,
            "artifact": paths,
            **_freeze(),
        },
        paths["input_plan_r2_key"]: dict(job_spec),
        paths["batch_summary_r2_key"]: dict(result_body),
    }
    if "results" in result_body:
        artifacts[paths["results_r2_key"]] = result_body.get("results")
    if "screens" in result_body:
        artifacts[paths["screens_r2_key"]] = result_body.get("screens")
    if "ranking" in result_body:
        artifacts[paths["ranking_r2_key"]] = result_body.get("ranking")

    for key, obj in artifacts.items():
        body = json.dumps(obj, indent=2, default=str).encode("utf-8")
        meta = put_fn(RESEARCH_ARTIFACT_BUCKET, key, body)
        puts.append(dict(meta) if isinstance(meta, Mapping) else {"key": key})
    return puts


def run_cf_mass_eval_job(
    *,
    job_id: str | None = None,
    logic_ids: Sequence[str] | None = None,
    extra_logics: Sequence[Mapping[str, Any]] | None = None,
    periods: Sequence[Mapping[str, Any]] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY,
    seed: int = 870816,
    mode: str = DEFAULT_MASS_EVAL_MODE,
    stage_panels: bool | None = None,
    worker_url: str = DEFAULT_WORKER_URL,
    deploy_if_needed: bool = True,
    mirror_r2_from_driver: bool = True,
    dry_run_r2: bool = False,
    staging_dir: str | Path | None = None,
    http_post: Callable[..., Any] | None = None,
    skip_invoke: bool = False,
    timeout: int = 300,
) -> dict[str, Any]:
    """Build → stage real panels (r2_panels) → deploy → invoke CF job.

    Default ``mode=r2_panels`` (real COMPLETE-backed multi-year panels).
    Returns a pack with job_id, status, counts, artifact paths, and the
    Worker response body.
    """
    t0 = time.perf_counter()
    mode_s = str(mode or DEFAULT_MASS_EVAL_MODE).strip()
    do_stage = (
        bool(stage_panels)
        if stage_panels is not None
        else mode_s == "r2_panels"
    )
    jid_pre = str(job_id or f"mass-eval-{uuid4().hex[:12]}")
    period_rows = [
        normalize_period_row(p)
        for p in (
            periods
            or (
                DEFAULT_REAL_MULTIYEAR_PERIODS
                if mode_s in {"r2_panels", "d1_bars"}
                else DEFAULT_LITE_PERIODS
            )
        )
    ]

    stage_meta: dict[str, Any] | None = None
    if do_stage:
        if dry_run_r2:
            stage_meta = stage_real_panels_to_r2(
                jid_pre,
                period_rows,
                max_codes=max_codes,
                max_days=max_days,
                dry_run=True,
                staging_dir=staging_dir,
            )
        else:
            stage_meta = resolve_or_stage_panels(
                job_id=jid_pre,
                periods=period_rows,
                max_codes=max_codes,
                max_days=max_days,
                staging_dir=staging_dir,
            )
        if int(stage_meta.get("n_ok") or 0) <= 0 and mode_s == "r2_panels":
            raise CfMassEvalError(
                "r2_panels staging produced 0 ok panels; "
                "check COMPLETE-backed mirrors under "
                ".glm-logs/w0815bd_w63_multiyear and w0815be_w64_cost_full"
            )

    panels_prefix = (
        (stage_meta or {}).get("panels_prefix")
        or f"{RESEARCH_ARTIFACT_PREFIX}/job={jid_pre}/panels"
    )
    spec = build_cf_mass_eval_job_spec(
        job_id=jid_pre,
        logic_ids=logic_ids,
        periods=period_rows,
        max_codes=max_codes,
        max_days=max_days,
        one_way_cost=one_way_cost,
        seed=seed,
        extra_logics=extra_logics,
        mode=mode_s,
        panels_prefix=str(panels_prefix),
    )
    jid = str(spec["job_id"])
    if not spec.get("logics"):
        skip_invoke = True
    paths = design_mass_factory_paths(jid)
    deploy_meta: dict[str, Any] | None = None
    invoke_error: str | None = None
    worker_resp: dict[str, Any] | None = None
    url = worker_url

    if deploy_if_needed and http_post is None and not skip_invoke:
        try:
            deploy_meta = deploy_cf_mass_eval_worker()
            url = str(deploy_meta.get("worker_url") or url)
        except CfMassEvalError as exc:
            deploy_meta = {"status": "deploy_failed", "error": str(exc)}

    t_fan0 = time.perf_counter()
    if not skip_invoke:
        try:
            worker_resp = invoke_cf_mass_eval_worker(
                spec,
                worker_url=url,
                http_post=http_post,
                timeout=timeout,
            )
        except CfMassEvalError as exc:
            invoke_error = str(exc)
    fanout_sec = round(time.perf_counter() - t_fan0, 3)

    r2_puts: list[dict[str, Any]] = []
    status = "ok"
    if worker_resp is None:
        status = "invoke_failed"
    elif worker_resp.get("error") and not worker_resp.get("ok"):
        status = "worker_error"
    elif worker_resp.get("ok") is False:
        status = "worker_error"
    elif str(worker_resp.get("status") or "").lower() not in {
        "ok",
        "completed",
        "success",
        "",
    }:
        if not worker_resp.get("results") and not worker_resp.get("n_logics"):
            if worker_resp.get("ok") is not True:
                status = "worker_error"

    if worker_resp and mirror_r2_from_driver and status == "ok":
        if not worker_resp.get("r2_puts") and not worker_resp.get("r2_keys"):
            try:
                r2_puts = put_local_fallback_artifacts(
                    spec,
                    worker_resp,
                    dry_run=dry_run_r2,
                    staging_dir=staging_dir,
                )
            except Exception as exc:  # pragma: no cover - network
                r2_puts = [{"status": "put_failed", "error": str(exc)}]
        else:
            r2_puts = list(worker_resp.get("r2_puts") or [])

    n_logics = int(
        (worker_resp or {}).get("n_logics")
        or len(spec.get("logics") or [])
    )
    n_periods = int(
        (worker_resp or {}).get("n_periods")
        or len(spec.get("periods") or [])
    )
    n_evaluated = int(
        (worker_resp or {}).get("n_eval_ok")
        or (worker_resp or {}).get("n_evaluated")
        or 0
    )
    n_survivors = int((worker_resp or {}).get("n_survivors") or 0)
    r2_keys = dict((worker_resp or {}).get("r2_keys") or {})
    if not r2_keys:
        r2_keys = {
            "manifest": paths["manifest_r2_key"],
            "summary": paths["batch_summary_r2_key"],
            "results": paths["results_r2_key"],
            "ranking": paths["ranking_r2_key"],
            "panels_prefix": str(panels_prefix),
        }

    return {
        "version": CF_MASS_EVAL_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "status": status,
        "job_id": jid,
        "mode": mode_s,
        "worker_url": url,
        "deploy": deploy_meta,
        "stage_panels": stage_meta,
        "stage_sec": (
            0.0
            if not stage_meta
            else float(
                stage_meta.get("stage_sec")
                or stage_meta.get("wall_time_sec")
                or 0.0
            )
        ),
        "stage_reused": bool((stage_meta or {}).get("reused")),
        "stage_cache_id": (stage_meta or {}).get("cache_id"),
        "fanout_sec": fanout_sec,
        "invoke_error": invoke_error,
        "n_logics": n_logics,
        "n_periods": n_periods,
        "n_logic_period_cells": n_logics * n_periods,
        "n_evaluated": n_evaluated,
        "n_eval_ok": n_evaluated,
        "n_survivors": n_survivors,
        "artifact_paths": paths,
        "r2_prefix": f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}/",
        "r2_keys": r2_keys,
        "r2_puts": r2_puts,
        "panels_prefix": str(panels_prefix),
        "datasets_used": {
            "primary_bars": PRIMARY_BARS_DATASET,
            "complete_22": list(COMPLETE_22_DATASETS),
            "permanent_defer_excluded": sorted(PERMANENT_DEFER_DATASETS),
        },
        "job_spec": {
            k: spec[k]
            for k in (
                "job_id",
                "version",
                "wave",
                "seed",
                "mode",
                "panels_prefix",
                "max_codes",
                "max_days",
                "one_way_cost",
                "shard_policy",
                "datasets",
            )
            if k in spec
        },
        "logic_ids": [L.get("logic_id") for L in (spec.get("logics") or [])],
        "period_ids": [P.get("period_id") for P in (spec.get("periods") or [])],
        "periods": list(spec.get("periods") or []),
        "worker_response": worker_resp,
        "wall_time_sec": round(time.perf_counter() - t0, 3),
        **_freeze(),
    }


def try_cf_mass_eval_status() -> dict[str, Any]:
    """Status helper replacing the old 'blocked' stub for residual docs."""
    return {
        "status": "implemented",
        "version": CF_MASS_EVAL_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "worker": DEFAULT_WORKER_NAME,
        "worker_url": DEFAULT_WORKER_URL,
        "entry": "research.cf_mass_eval_job.run_cf_mass_eval_job",
        "artifact_prefix": f"{RESEARCH_ARTIFACT_PREFIX}/job={{id}}/",
        "bucket": RESEARCH_ARTIFACT_BUCKET,
        "default_mode": DEFAULT_MASS_EVAL_MODE,
        "modes": sorted(ALLOWED_MODES),
        "shard_policy": "real_multiyear_r2_panels",
        "bar_native_logics": list(CF_BAR_NATIVE_LOGIC_IDS),
        "complete_22": list(COMPLETE_22_DATASETS),
        "real_multiyear_periods": [
            p["period_id"] for p in DEFAULT_REAL_MULTIYEAR_PERIODS
        ],
        "screen_kind": "period_net",
        "daily_path_complete": False,
        "candidate_grade": False,
        "candidate_eval_sot": "daily_path_mtm_after_cost/v1",
        "unique_unsupported_on_period_net": True,
        "n_survivors_are_not_a_pass": True,
        "scale_note": (
            "Real COMPLETE-backed multi-year panels staged to R2 "
            "(mode=r2_panels). D1 tip-only via mode=d1_bars. "
            "Period-net is bar-native auxiliary only. Unique event/CS "
            "logics collapse to MDH on this path and must not be scored "
            "as n_survivors. Candidate SoT is daily_path. "
            "Heavy multi-year promising-only remains local offline eval."
        ),
        "synthetic_gap": (
            "rate_abs_level_xs / rate_curve_shape_xs still local_only on "
            "pure-TS CF (disclosed MDH fallback). flow/fund/mf/macro_repo "
            "consume thicken sidecars when present. Synthetic = smoke only."
        ),
        **_freeze(),
    }


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
