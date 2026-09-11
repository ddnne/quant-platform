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

from research.closed_clients import ClosedDeployPort, ClosedJsonClient

from research.cf_mass_eval_job import (
    CF_MASS_EVAL_VERSION,
    CF_MASS_EVAL_WAVE,
    DEFAULT_MASS_EVAL_MODE,
    DEFAULT_MAX_CODES,
    DEFAULT_MAX_DAYS,
    DEFAULT_ONE_WAY,
    DEFAULT_WORKER_URL,
    CfMassEvalError,
    _freeze,
    refuse_missing_capability,
)


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

