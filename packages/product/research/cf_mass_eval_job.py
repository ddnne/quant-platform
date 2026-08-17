"""Cloudflare multi-logic × multi-period mass eval job (W90 / w0816y).

Implements a real CF Worker path for evaluating **multiple economic logics**
across **multiple period windows**, writing artifacts to R2
``quant-structured`` under ``research/mass_factory/job={id}/…``.

Architecture
------------
* **Worker:** ``platform/workers/mass-eval`` (TypeScript)
  - Loads lite bar panels from D1 ``jquants_daily_bars``
  - Evaluates bar-native logics (mdh / xs / vol) across period shards
  - Writes ``batch_summary.json`` + ``results.json`` to R2
* **Driver (this module):** builds job payload, invokes Worker via HTTPS,
  records job id / counts / artifact keys. Optionally uploads a denser
  input shard to R2 for non-bar-native logics.

Lite shard policy (first cut)
-----------------------------
* max_codes ≤ 20, max_days ≤ 80 per period, ≤ 6 periods
* Full multi-year deep eval remains local ``run_mass_factory`` /
  ``class_hyp_eval`` for promising survivors only

Does **not** arm Mass / READY / GO / continuous paper / live.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from research.mass_strategy_factory import (
    CONTINUOUS_PAPER,
    LOGIC_TEMPLATES,
    LOGIC_TEMPLATE_IDS,
    MASS_FACTORY_VERSION,
    MASS_RESEARCH,
    PHASE7,
    MassFactoryConfig,
    generate_strategy_batch,
    run_batch_eval,
)
from research.single_shot_job import default_r2_put

CF_MASS_EVAL_VERSION: str = "cf-mass-eval-job/v1"
CF_MASS_EVAL_WAVE: str = "W90 / w0816y"
RESEARCH_ARTIFACT_BUCKET: str = "quant-structured"
RESEARCH_ARTIFACT_PREFIX: str = "research/mass_eval"
DEFAULT_WORKER_NAME: str = "quant-platform-research-mass-eval"
DEFAULT_WORKER_URL: str = (
    "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
)
RESEARCH_ARTIFACT_PREFIX_LEGACY: str = "research/mass_factory"
DEFAULT_MAX_CODES: int = 15
DEFAULT_MAX_DAYS: int = 60
DEFAULT_ONE_WAY: float = 0.001

# Bar-native logics the CF Worker can evaluate without extra panels.
CF_BAR_NATIVE_LOGIC_IDS: tuple[str, ...] = (
    "mdh_sticky_momentum",
    "mdh_mean_reversion",
    "xs_rank_ls_sticky",
    "xs_rank_ls_daily",
    "vol_mom_over_vol",
    "vol_low_vol_long",
)

# Lite multi-period shards (documented; wall-clock safe on CF).
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
        "factory_version": MASS_FACTORY_VERSION,
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


def default_logic_specs(
    logic_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Build CF-ready logic specs from catalog templates."""
    ids = list(logic_ids) if logic_ids is not None else list(CF_BAR_NATIVE_LOGIC_IDS)
    out: list[dict[str, Any]] = []
    for lid in ids:
        tpl = LOGIC_TEMPLATES.get(lid)
        if tpl is None:
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
                "logic_id": tpl.logic_id,
                "family_id": tpl.family_id,
                "params": dict(tpl.base_params),
                "thesis": tpl.thesis,
                "signal_definition": tpl.signal_definition,
                "position_rule": tpl.position_rule,
                "datasets_used": list(tpl.datasets_used),
                "logic_fingerprint": tpl.logic_fingerprint(),
            }
        )
    return out


def build_cf_mass_eval_job_spec(
    *,
    job_id: str | None = None,
    logic_ids: Sequence[str] | None = None,
    periods: Sequence[Mapping[str, str]] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY,
    seed: int = 870816,
    extra_logics: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Declarative job payload for the CF mass-eval Worker."""
    jid = str(job_id or f"w90-cf-{uuid4().hex[:12]}")
    paths = design_mass_factory_paths(jid)
    logics = default_logic_specs(logic_ids)
    if extra_logics:
        for raw in extra_logics:
            logics.append(dict(raw))
    period_rows = [dict(p) for p in (periods or DEFAULT_LITE_PERIODS)]
    return {
        "version": CF_MASS_EVAL_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "job_id": jid,
        "seed": int(seed),
        "logics": logics,
        "periods": period_rows,
        "max_codes": int(max_codes),
        "max_days": int(max_days),
        "one_way_cost": float(one_way_cost),
        "artifact": paths,
        "shard_policy": {
            "kind": "lite_multi_period",
            "note": (
                "Documented lite shard for CF wall-clock: "
                f"≤{max_codes} codes × ≤{max_days} days × "
                f"{len(period_rows)} periods × {len(logics)} logics. "
                "Heavy multi-year stays local for promising survivors."
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
        "User-Agent": "quant-platform-w90-cf-mass-eval/1.0",
    }
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
        headers["X-Research-Run-Token"] = tok

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
        # try npx wrangler from worker dir node_modules after install
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
    # parse workers.dev URL if present
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
    periods: Sequence[Mapping[str, str]] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY,
    seed: int = 870816,
    worker_url: str = DEFAULT_WORKER_URL,
    deploy_if_needed: bool = True,
    mirror_r2_from_driver: bool = True,
    dry_run_r2: bool = False,
    staging_dir: str | Path | None = None,
    http_post: Callable[..., Any] | None = None,
    skip_invoke: bool = False,
) -> dict[str, Any]:
    """Build → (optional deploy) → invoke CF job → record artifacts.

    Returns a pack with job_id, status, counts, artifact paths, and the
    Worker response body.
    """
    t0 = time.perf_counter()
    spec = build_cf_mass_eval_job_spec(
        job_id=job_id,
        logic_ids=logic_ids,
        periods=periods,
        max_codes=max_codes,
        max_days=max_days,
        one_way_cost=one_way_cost,
        seed=seed,
        extra_logics=extra_logics,
    )
    jid = str(spec["job_id"])
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

    if not skip_invoke:
        try:
            worker_resp = invoke_cf_mass_eval_worker(
                spec,
                worker_url=url,
                http_post=http_post,
            )
        except CfMassEvalError as exc:
            invoke_error = str(exc)

    r2_puts: list[dict[str, Any]] = []
    status = "ok"
    if worker_resp is None:
        status = "invoke_failed"
    elif worker_resp.get("error"):
        status = "worker_error"
    elif str(worker_resp.get("status") or "").lower() not in {
        "ok",
        "completed",
        "success",
        "",
    }:
        # accept missing status if results present
        if not worker_resp.get("results") and not worker_resp.get("n_logics"):
            status = "worker_error"

    # Prefer Worker-reported artifact keys; mirror if requested and needed.
    if worker_resp and mirror_r2_from_driver and status == "ok":
        # If worker already wrote R2, still optionally mirror summary from driver
        # only when worker did not claim r2_puts.
        if not worker_resp.get("r2_puts") and not worker_resp.get("artifacts"):
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
    n_evaluated = int((worker_resp or {}).get("n_evaluated") or 0)
    n_survivors = int((worker_resp or {}).get("n_survivors") or 0)

    return {
        "version": CF_MASS_EVAL_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "status": status,
        "job_id": jid,
        "worker_url": url,
        "deploy": deploy_meta,
        "invoke_error": invoke_error,
        "n_logics": n_logics,
        "n_periods": n_periods,
        "n_logic_period_cells": n_logics * n_periods,
        "n_evaluated": n_evaluated,
        "n_survivors": n_survivors,
        "artifact_paths": paths,
        "r2_puts": r2_puts,
        "job_spec": {
            k: spec[k]
            for k in (
                "job_id",
                "version",
                "wave",
                "seed",
                "max_codes",
                "max_days",
                "one_way_cost",
                "shard_policy",
            )
            if k in spec
        },
        "logic_ids": [L.get("logic_id") for L in (spec.get("logics") or [])],
        "period_ids": [P.get("period_id") for P in (spec.get("periods") or [])],
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
        "shard_policy": "lite_multi_period",
        "bar_native_logics": list(CF_BAR_NATIVE_LOGIC_IDS),
        "scale_note": (
            "Lite shard on CF (codes×days×periods). Heavy multi-year "
            "promising-only remains local class_hyp_eval."
        ),
        **_freeze(),
    }


def run_local_wide_eval_pack(
    *,
    llm_accepted: Sequence[Mapping[str, Any]] | None = None,
    seed: int = 870816,
    synthetic: bool = False,
    max_codes: int = 20,
    max_days: int = 80,
    progress: bool = False,
) -> dict[str, Any]:
    """Wide local eval: catalog after_dedup + LLM-accepted (exclude only impossible).

    Used for the broad results table; CF lite is complementary evidence.
    """
    cfg = MassFactoryConfig(
        seed=seed,
        n=100,
        max_codes=max_codes,
        max_days_per_period=max_days,
        use_q4_periods=True,
    )
    gen = generate_strategy_batch(cfg)
    strategies = list(gen.get("strategies_after_dedup") or [])
    # Merge LLM accepted (by logic_id) without collapsing near-groups
    seen = {str(s.get("logic_id")) for s in strategies}
    extra = 0
    for raw in llm_accepted or []:
        lid = str(raw.get("logic_id") or "")
        if not lid or lid in seen:
            # still include ad-hoc under unique key
            if lid in seen and str(raw.get("source") or "").startswith("profit"):
                continue
            if lid in seen:
                lid = f"{lid}__llm_{extra}"
                raw = {**dict(raw), "logic_id": lid}
        strategies.append(dict(raw))
        seen.add(lid)
        extra += 1

    gen_for_eval = {
        **gen,
        "strategies_after_dedup": strategies,
        "n_after_dedup": len(strategies),
    }

    def _cb(i: int, n: int, sid: str) -> None:
        if progress:
            print(f"[wide-eval] {i}/{n} {sid}", flush=True)

    batch = run_batch_eval(
        gen_for_eval,
        config=cfg,
        synthetic=synthetic,
        progress_cb=_cb if progress else None,
    )
    return {
        "version": CF_MASS_EVAL_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "kind": "local_wide_eval",
        "n_strategies": len(strategies),
        "n_catalog_after_dedup": int(gen.get("n_after_dedup") or 0),
        "n_llm_merged": extra,
        "batch": {
            k: batch[k]
            for k in batch
            if k not in {"results"}
        },
        "screens": batch.get("screens"),
        "ranking": batch.get("ranking"),
        "results_compact": [
            {
                "strategy_id": r.get("strategy_id"),
                "logic_id": r.get("logic_id"),
                "family_id": r.get("family_id"),
                "survived": (r.get("screen") or {}).get("survived"),
                "mean_net": r.get("mean_net"),
                "t_stat": r.get("t_stat"),
                "sharpe_period": r.get("sharpe_period"),
                "chosen_sign": r.get("chosen_sign"),
                "n_periods_ok": r.get("n_periods_ok"),
                "reject_reasons": (r.get("screen") or {}).get("reject_reasons"),
            }
            for r in (batch.get("results") or [])
        ],
        **_freeze(),
    }


__all__ = [
    "CF_MASS_EVAL_VERSION",
    "CF_MASS_EVAL_WAVE",
    "CF_BAR_NATIVE_LOGIC_IDS",
    "DEFAULT_LITE_PERIODS",
    "DEFAULT_WORKER_URL",
    "RESEARCH_ARTIFACT_BUCKET",
    "RESEARCH_ARTIFACT_PREFIX",
    "CfMassEvalError",
    "resolve_research_run_token",
    "design_mass_factory_paths",
    "default_logic_specs",
    "build_cf_mass_eval_job_spec",
    "invoke_cf_mass_eval_worker",
    "deploy_cf_mass_eval_worker",
    "put_local_fallback_artifacts",
    "run_cf_mass_eval_job",
    "try_cf_mass_eval_status",
    "run_local_wide_eval_pack",
]
