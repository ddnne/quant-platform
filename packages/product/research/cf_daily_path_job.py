"""Candidate-grade daily_path on Cloudflare via isolate fan-out.

Bottleneck this replaces
------------------------
``python -m research.unique_logic --all`` evaluates logics × windows × shards
in **one process**, so wall-clock is the sum. The mass-eval Worker also
``.map``s logics inside one isolate.

Model
-----
1. Stage COMPLETE-backed panels once (shared R2 prefix).
2. POST ``/v1/daily-path`` **once per logic** (write_artifacts=false).
3. Cloudflare runs isolates concurrently; batch wall-clock ≈ longest POST
   + staging, not the sum of logics.
4. Driver aggregates cells and records ``research/eval/job={id}/`` (R2+D1).

Does not promote / GO / Mass / retune pins. period-net n_survivors is not
this protocol.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from qp_paths import repo_root
from research.cf_mass_eval_job import (
    CF_BAR_NATIVE_LOGIC_IDS,
    CF_MASS_EVAL_WAVE,
    DEFAULT_MASS_EVAL_MODE,
    DEFAULT_MAX_CODES,
    DEFAULT_MAX_DAYS,
    DEFAULT_ONE_WAY,
    DEFAULT_REAL_MULTIYEAR_PERIODS,
    DEFAULT_WORKER_URL,
    CfMassEvalError,
    build_cf_mass_eval_job_spec,
    invoke_cf_mass_eval_worker,
    normalize_period_row,
    resolve_or_stage_panels,
)
from research.daily_path_eval import git_sha
from research.eval_registry import PROTOCOL_DAILY_PATH, is_daily_path_complete_cell
from research.mass_strategy_factory import MASS_FACTORY_VERSION, MASS_RESEARCH
from research.unique_logic.constants import CF_EVENT_DAILY_PATH_IDS as _CF_EVENT_SET

CF_EVENT_DAILY_PATH_IDS: tuple[str, ...] = tuple(sorted(_CF_EVENT_SET))

ROOT = repo_root()
FANOUT_VERSION = "cf-daily-path-fanout/v2"
DEFAULT_FANOUT_WORKERS = 16


def invoke_cf_daily_path(
    job_spec: Mapping[str, Any],
    *,
    worker_url: str = DEFAULT_WORKER_URL,
    timeout: int = 180,
    http_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """POST /v1/daily-path (one isolate)."""
    spec = dict(job_spec)
    spec["eval_kind"] = "daily_path"
    spec["write_artifacts"] = False
    url = worker_url.rstrip("/") + "/v1/daily-path"
    # Reuse mass-eval invoker by swapping path via a thin wrapper.
    patched_url = url

    def _post(*, url: str, body: bytes, headers: dict[str, str]) -> Any:
        # invoke_cf_mass_eval_worker builds /v1/mass-eval; we ignore that url.
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        if http_post is not None:
            return http_post(url=patched_url, body=body, headers=headers)
        req = Request(patched_url, data=body, method="POST", headers=headers)
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:2000]
            except Exception:
                detail = str(exc)
            raise CfMassEvalError(
                f"daily-path HTTP {exc.code}: {detail}"
            ) from exc

    return invoke_cf_mass_eval_worker(
        spec,
        worker_url=worker_url,
        timeout=timeout,
        http_post=_post,
    )


def run_cf_daily_path_fanout(
    *,
    job_id: str | None = None,
    logic_ids: Sequence[str] | None = None,
    periods: Sequence[Mapping[str, Any]] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY,
    seed: int = 870816,
    mode: str = DEFAULT_MASS_EVAL_MODE,
    worker_url: str = DEFAULT_WORKER_URL,
    max_workers: int = DEFAULT_FANOUT_WORKERS,
    timeout: int = 180,
    http_post: Callable[..., Any] | None = None,
    skip_stage: bool = False,
    staging_dir: str | Path | None = None,
    panels_prefix: str | None = None,
    track: str | None = None,
) -> dict[str, Any]:
    """Stage once, fan-out one CF isolate per logic, aggregate cells.

    Wall-clock target: staging + max(isolate), not sum(logics).
    """
    t0 = time.perf_counter()
    jid = str(job_id or f"eval-cf-dp-{uuid4().hex[:10]}")
    ids = list(logic_ids) if logic_ids is not None else list(CF_BAR_NATIVE_LOGIC_IDS)
    if len(ids) < 1:
        raise CfMassEvalError("logic_ids required")
    period_rows = [
        normalize_period_row(p)
        for p in (periods or DEFAULT_REAL_MULTIYEAR_PERIODS)
    ]
    stage_meta: dict[str, Any] | None = None
    if panels_prefix:
        stage_meta = {
            "reused": True,
            "stage_sec": 0.0,
            "panels_prefix": panels_prefix,
            "note": "explicit panels_prefix",
        }
    elif skip_stage:
        panels_prefix = f"research/mass_eval/job={jid}/panels"
        stage_meta = {
            "reused": True,
            "stage_sec": 0.0,
            "panels_prefix": panels_prefix,
            "note": "skip_stage job-scoped prefix",
        }
    elif mode == "r2_panels":
        stage_meta = resolve_or_stage_panels(
            job_id=jid,
            periods=period_rows,
            max_codes=max_codes,
            max_days=max_days,
            staging_dir=staging_dir,
            track=track,
        )
        if int(stage_meta.get("n_ok") or 0) <= 0:
            raise CfMassEvalError(
                "r2_panels staging produced 0 ok panels for daily_path fan-out"
            )
        panels_prefix = str(stage_meta.get("panels_prefix") or panels_prefix)
    else:
        panels_prefix = panels_prefix or f"research/mass_eval/job={jid}/panels"

    t_fan0 = time.perf_counter()
    per_logic: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def _one(lid: str) -> dict[str, Any]:
        t_i = time.perf_counter()
        spec = build_cf_mass_eval_job_spec(
            job_id=f"{jid}__{lid}",
            logic_ids=[lid],
            periods=period_rows,
            max_codes=max_codes,
            max_days=max_days,
            one_way_cost=one_way_cost,
            seed=seed,
            mode=mode,
            panels_prefix=panels_prefix,
            drop_unique_unsupported=False,
        )
        spec["eval_kind"] = "daily_path"
        spec["write_artifacts"] = False
        resp = invoke_cf_daily_path(
            spec, worker_url=worker_url, timeout=timeout, http_post=http_post
        )
        elapsed = time.perf_counter() - t_i
        logic_cells = list(resp.get("cells") or [])
        n_ok = sum(1 for c in logic_cells if is_daily_path_complete_cell(c))
        return {
            "logic_id": lid,
            "wall_sec": round(elapsed, 3),
            "n_cells": len(logic_cells),
            "n_complete": n_ok,
            "ok": bool(resp.get("ok", True)) and n_ok > 0,
            "cells": logic_cells,
            "error": resp.get("error") or resp.get("detail"),
        }

    n_workers = max(1, min(int(max_workers), len(ids)))
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = {pool.submit(_one, lid): lid for lid in ids}
        for fut in as_completed(futs):
            lid = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:  # noqa: BLE001 — isolate failure disclosed
                errors.append({"logic_id": lid, "error": str(exc)})
                per_logic.append(
                    {
                        "logic_id": lid,
                        "ok": False,
                        "wall_sec": None,
                        "error": str(exc),
                    }
                )
                continue
            per_logic.append({k: v for k, v in row.items() if k != "cells"})
            cells.extend(row.get("cells") or [])
            if row.get("error") and not row.get("ok"):
                errors.append({"logic_id": lid, "error": row.get("error")})

    fan_sec = time.perf_counter() - t_fan0
    walls = [float(p["wall_sec"]) for p in per_logic if p.get("wall_sec") is not None]
    longest = max(walls) if walls else None
    n_ok_logic = sum(1 for p in per_logic if p.get("ok"))
    out_dir = ROOT / "data" / "ops" / "research_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    table_path = out_dir / f"{jid}_cells.json"
    table_path.write_text(
        json.dumps(cells, indent=2, default=str) + "\n", encoding="utf-8"
    )
    pack = {
        "version": FANOUT_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "job_id": jid,
        "protocol": PROTOCOL_DAILY_PATH,
        "eval_kind": "daily_path",
        "parallel_model": "cf_isolate_fanout_one_logic",
        "wall_clock_target": "batch ≈ longest isolate + staging",
        "mode": mode,
        "n_logics": len(ids),
        "logic_ids": ids,
        "n_periods": len(period_rows),
        "period_ids": [p.get("period_id") for p in period_rows],
        "n_cells": len(cells),
        "n_daily_path_complete": sum(
            1 for c in cells if is_daily_path_complete_cell(c)
        ),
        "n_logic_ok": n_ok_logic,
        "n_errors": len(errors),
        "errors": errors,
        "per_logic": per_logic,
        "fanout_workers": n_workers,
        "stage_panels": stage_meta,
        "panels_prefix": panels_prefix,
        "stage_sec": (
            0.0
            if not stage_meta
            else float(stage_meta.get("stage_sec") or stage_meta.get("wall_time_sec") or 0.0)
        ),
        "stage_reused": bool((stage_meta or {}).get("reused")),
        "stage_cache_id": (stage_meta or {}).get("cache_id"),
        "fanout_sec": round(fan_sec, 3),
        "longest_isolate_sec": round(longest, 3) if longest is not None else None,
        "wall_sec": round(time.perf_counter() - t0, 3),
        "table_path": str(table_path),
        "git_sha": git_sha(cwd=ROOT),
        "factory_version": MASS_FACTORY_VERSION,
        "promote_as_main": False,
        "go": False,
        "mass_research": MASS_RESEARCH,
        "survived": False,
        "candidate_grade": True,
        "period_net_dd_only_pass_forbidden": True,
        "notes": (
            "CF isolate fan-out daily_path_DD. Windows are Worker period_ids "
            "(real multi-year shards), not local HONEST_3Y stitch. "
            "Not a promotion."
        ),
    }
    return pack
