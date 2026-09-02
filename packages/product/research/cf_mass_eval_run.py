"""CF mass-eval Worker invoke / deploy / run. Not a pass / not GO.

wrangler deploy is opt-in fail-closed: only QP_ALLOW_MASS_EVAL_DEPLOY=1
allows subprocess wrangler deploy. Does not enable Mass.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from research.closed_clients import ClosedDeployPort, ClosedJsonClient

from research.cf_mass_eval_job import (
    CF_MASS_EVAL_VERSION,
    CF_MASS_EVAL_WAVE,
    DEFAULT_LITE_PERIODS,
    DEFAULT_MASS_EVAL_MODE,
    DEFAULT_MAX_CODES,
    DEFAULT_MAX_DAYS,
    DEFAULT_ONE_WAY,
    DEFAULT_WORKER_URL,
    CfMassEvalError,
    _freeze,
    _DEFAULT_WRANGLER,
    _WORKER_CONFIG,
    _WORKER_DIR,
    build_cf_mass_eval_job_spec,
    design_mass_factory_paths,
    refuse_missing_capability,
    resolve_or_stage_panels,
    resolve_research_run_token,
)
from research.cf_mass_eval_stage import (
    RESEARCH_ARTIFACT_BUCKET,
    RESEARCH_ARTIFACT_PREFIX,
    normalize_period_row,
    stage_real_panels_to_r2,
)
from research.eval_windows import DEFAULT_REAL_MULTIYEAR_PERIODS


MASS_EVAL_DEPLOY_ENV = "QP_ALLOW_MASS_EVAL_DEPLOY"


def mass_eval_deploy_allowed() -> bool:
    """True only when QP_ALLOW_MASS_EVAL_DEPLOY=1. Does not enable Mass."""
    return os.environ.get(MASS_EVAL_DEPLOY_ENV, "").strip() == "1"


def invoke_cf_mass_eval_worker(
    job_spec: Mapping[str, Any],
    *,
    client: ClosedJsonClient | None = None,
    http_post: Callable[..., Any] | None = None,
    worker_url: str = DEFAULT_WORKER_URL,
    token: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    refused = refuse_missing_capability("mass_screen")
    if refused is not None:
        return refused
    t0 = time.perf_counter()
    if client is not None:
        payload = dict(client.post(dict(job_spec)))
        payload["invoke_latency_sec"] = round(time.perf_counter() - t0, 3)
        return payload
    if http_post is None:
        raise CfMassEvalError("closed JSON client is required")
    url = worker_url.rstrip("/") + "/v1/mass-eval"
    body = json.dumps(dict(job_spec), default=str).encode("utf-8")
    headers = {"Content-Type": "application/json"}
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


def deploy_cf_mass_eval_worker(
    *,
    deployer: ClosedDeployPort | None = None,
    wrangler: str | Path | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    if not mass_eval_deploy_allowed():
        raise CfMassEvalError(
            "wrangler deploy refused without QP_ALLOW_MASS_EVAL_DEPLOY=1"
        )
    if deployer is None:
        raise CfMassEvalError("closed deploy port is required")
    del wrangler, timeout
    combined = deployer.deploy()
    return {
        "status": "deployed",
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
    from research.mass_disabled import refuse_mass_host_entrypoint

    refuse_mass_host_entrypoint("put_local_fallback_artifacts")
    paths = design_mass_factory_paths(str(job_spec.get("job_id") or "unknown"))
    if r2_put is None:
        raise CfMassEvalError("closed artifact put port is required")
    put_fn = r2_put
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
    from research.mass_disabled import refuse_mass_host_entrypoint

    refuse_mass_host_entrypoint("run_cf_mass_eval_job")
    refused = refuse_missing_capability("mass_screen")
    if refused is not None:
        return refused
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
    n_evaluated = int((worker_resp or {}).get("n_eval_ok") or 0)
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
        "n_eval_ok": n_evaluated,
        "n_survivors": n_survivors,
        "artifact_paths": paths,
        "r2_prefix": f"{RESEARCH_ARTIFACT_PREFIX}/job={jid}/",
        "r2_keys": r2_keys,
        "r2_puts": r2_puts,
        "panels_prefix": str(panels_prefix),
        "logic_ids": [L.get("logic_id") for L in (spec.get("logics") or [])],
        "period_ids": [P.get("period_id") for P in (spec.get("periods") or [])],
        "worker_response": worker_resp,
        "wall_time_sec": round(time.perf_counter() - t0, 3),
        **_freeze(),
    }


def try_cf_mass_eval_status() -> dict[str, Any]:
    return {
        "status": "implemented",
        "version": CF_MASS_EVAL_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "default_mode": DEFAULT_MASS_EVAL_MODE,
        "screen_kind": "period_net",
        "daily_path_complete": False,
        "candidate_grade": False,
        "candidate_eval_sot": "daily_path_mtm_after_cost/v1",
        "unique_unsupported_on_period_net": True,
        "n_survivors_are_not_a_pass": True,
        **_freeze(),
    }


