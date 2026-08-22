"""CF isolate fan-out daily_path. Not a pass / not GO."""
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
from research.freezes import MASS_RESEARCH
from research.unique_logic.constants import CF_EVENT_DAILY_PATH_IDS as _CF_EVENT_SET

CF_EVENT_DAILY_PATH_IDS: tuple[str, ...] = tuple(sorted(_CF_EVENT_SET))

ROOT = repo_root()
FANOUT_VERSION = "cf-daily-path-fanout/v2"
BOTH_TRACK_SLEEVE_FANOUT_VERSION = "both-track-sleeve-fanout/v1"
BOTH_TRACK_QUEUE_ID = "both_track_sleeve_durability"
DEFAULT_FANOUT_WORKERS = 16


def invoke_cf_daily_path(
    job_spec: Mapping[str, Any],
    *,
    worker_url: str = DEFAULT_WORKER_URL,
    timeout: int = 180,
    http_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    spec = dict(job_spec)
    spec["eval_kind"] = "daily_path"
    spec["write_artifacts"] = bool(spec.get("write_artifacts"))
    patched_url = worker_url.rstrip("/") + "/v1/daily-path"

    def _post(*, url: str, body: bytes, headers: dict[str, str]) -> Any:
        # invoke_cf_mass_eval_worker builds /v1/mass-eval; ignore that url.
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
    write_artifacts: bool = False,
) -> dict[str, Any]:
    from research.eval_tracks import infer_eval_track

    t0 = time.perf_counter()
    jid = str(job_id or f"eval-cf-dp-{uuid4().hex[:10]}")
    track = track or infer_eval_track(max_codes=max_codes)
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
        spec["write_artifacts"] = bool(write_artifacts)
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
    from research.combo_basket import (
        primary_sleeve_and_meta_cells,
        summarize_basket_trends,
    )

    basket_cells = primary_sleeve_and_meta_cells(cells)
    basket_summary = summarize_basket_trends(basket_cells, job_id=jid)
    basket_summary["not_a_pass"] = True
    basket_summary["go"] = False
    pack = {
        "version": FANOUT_VERSION,
        "wave": CF_MASS_EVAL_WAVE,
        "job_id": jid,
        "protocol": PROTOCOL_DAILY_PATH,
        "eval_kind": "daily_path",
        "parallel_model": "cf_isolate_fanout_one_logic",
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
        "eval_track": track or (stage_meta or {}).get("eval_track"),
        "fanout_sec": round(fan_sec, 3),
        "longest_isolate_sec": round(longest, 3) if longest is not None else None,
        "wall_sec": round(time.perf_counter() - t0, 3),
        "table_path": str(table_path),
        "git_sha": git_sha(cwd=ROOT),
        "factory_version": FANOUT_VERSION,
        "promote_as_main": False,
        "go": False,
        "not_a_pass": True,
        "mass_research": MASS_RESEARCH,
        "survived": False,
        "candidate_grade": True,
        "period_net_dd_only_pass_forbidden": True,
        "notes": "CF isolate fan-out daily_path_DD. Not a promotion.",
        "baskets": basket_summary,
        "n_basket_cells": len(basket_cells),
        "write_artifacts": bool(write_artifacts),
    }
    return pack


def sleeve_durability_logic_ids() -> list[str]:
    from research.combo_basket_catalog import mechanical_basket_defs

    want = {"fundamentals_sleeve", "margin_flow_sleeve", "event_fund_cross"}
    ids: list[str] = []
    seen: set[str] = set()
    for d in mechanical_basket_defs():
        if str(d.get("rule") or "") not in want:
            continue
        for m in d.get("members") or []:
            lid = str(m)
            if lid and lid not in seen:
                seen.add(lid)
                ids.append(lid)
    return ids


def run_both_track_sleeve_fanout(
    *,
    job_id: str | None = None,
    dry_run: bool = True,
    logic_ids: Sequence[str] | None = None,
    periods: Sequence[Mapping[str, Any]] | None = None,
    select_universe: Callable[..., list[str]] | None = None,
    run_fanout: Callable[..., Mapping[str, Any]] | None = None,
    http_post: Callable[..., Any] | None = None,
    skip_stage: bool | None = None,
    mode: str | None = None,
    max_workers: int = DEFAULT_FANOUT_WORKERS,
    timeout: int = 180,
    worker_url: str = DEFAULT_WORKER_URL,
    staging_dir: str | Path | None = None,
    panels_prefix: str | None = None,
    max_days: int = DEFAULT_MAX_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY,
    universe_pool: Sequence[str] | None = None,
) -> dict[str, Any]:
    from research.combo_basket_compare import compare_mid_vs_liq
    from research.eval_tracks import (
        EVAL_TRACK_LIQ_LARGE,
        EVAL_TRACK_MID_N,
        EVAL_TRACKS,
        eval_track,
        track_is_not_a_pass,
    )
    from research.eval_universe import select_eval_universe

    t0 = time.perf_counter()
    jid = str(job_id or f"eval-cf-dp-both-sleeves-{uuid4().hex[:10]}")
    ids = (
        list(logic_ids)
        if logic_ids is not None
        else sleeve_durability_logic_ids()
    )
    if len(ids) < 1:
        raise CfMassEvalError("logic_ids required")
    selector = select_universe or select_eval_universe
    fan = run_fanout or run_cf_daily_path_fanout
    invoke_fanout = (not dry_run) or http_post is not None or run_fanout is not None
    use_skip_stage = True if skip_stage is None and dry_run else bool(skip_stage)
    use_mode = (
        "synthetic"
        if mode is None and dry_run
        else (mode or DEFAULT_MASS_EVAL_MODE)
    )
    skipped_live_cf = bool(dry_run) or http_post is not None or run_fanout is not None
    tracks_out: list[dict[str, Any]] = []
    by_tid: dict[str, dict[str, Any]] = {}

    track_ids = (EVAL_TRACK_MID_N, EVAL_TRACK_LIQ_LARGE)
    if set(track_ids) != set(EVAL_TRACKS):
        raise CfMassEvalError("both-track fanout requires mid_n_explore and liq_large")
    for tid in track_ids:
        spec = eval_track(tid)
        max_codes = int(spec["max_codes"])
        if select_universe is not None:
            codes = list(selector(max_codes=max_codes) or [])
        else:
            codes = list(
                selector(max_codes=max_codes, pool=universe_pool) or []
            )
        track_jid = f"{jid}-{tid}"
        fan_pack: dict[str, Any] | None = None
        if invoke_fanout:
            fan_pack = dict(
                fan(
                    job_id=track_jid,
                    logic_ids=ids,
                    periods=periods,
                    max_codes=max_codes,
                    max_days=max_days,
                    one_way_cost=one_way_cost,
                    mode=use_mode,
                    worker_url=worker_url,
                    max_workers=max_workers,
                    timeout=timeout,
                    http_post=http_post,
                    skip_stage=use_skip_stage,
                    staging_dir=staging_dir,
                    panels_prefix=panels_prefix,
                    track=tid,
                    write_artifacts=not bool(dry_run),
                )
            )
            fan_pack["not_a_pass"] = True
            fan_pack["go"] = False
            fan_pack["promote_as_main"] = False
        row = {
            "eval_track": tid,
            "max_codes": max_codes,
            "min_codes": int(spec["min_codes"]),
            "universe_select": spec["universe_select"],
            "head_n_forbidden": True,
            "n_selected_codes": len(codes),
            "selected_codes": list(codes),
            "job_id": (fan_pack or {}).get("job_id") or track_jid,
            "logic_ids": ids,
            "n_logics": len(ids),
            "dry_run": bool(dry_run),
            "skipped_live_cf": skipped_live_cf,
            "table_path": (fan_pack or {}).get("table_path"),
            "n_cells": (fan_pack or {}).get("n_cells"),
            "n_logic_ok": (fan_pack or {}).get("n_logic_ok"),
            "n_daily_path_complete": (fan_pack or {}).get("n_daily_path_complete"),
            "baskets": (fan_pack or {}).get("baskets") or {"baskets": []},
            "not_a_pass": True,
            "go": False,
            "promote_as_main": False,
        }
        if not track_is_not_a_pass(spec):
            raise CfMassEvalError(f"eval track {tid} must stay not_a_pass")
        tracks_out.append(row)
        by_tid[tid] = row

    compare = compare_mid_vs_liq(
        by_tid[EVAL_TRACK_MID_N].get("baskets")
        or {"job_id": by_tid[EVAL_TRACK_MID_N]["job_id"], "baskets": []},
        by_tid[EVAL_TRACK_LIQ_LARGE].get("baskets")
        or {"job_id": by_tid[EVAL_TRACK_LIQ_LARGE]["job_id"], "baskets": []},
    )
    compare["not_a_pass"] = True
    compare["go"] = False
    compare["promote_as_main"] = False
    compare["liq_print_is_not_stable"] = True

    out_dir = ROOT / "data" / "ops" / "research_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    table_path = out_dir / f"{jid}_both_track.json"
    pack = {
        "version": BOTH_TRACK_SLEEVE_FANOUT_VERSION,
        "queue_id": BOTH_TRACK_QUEUE_ID,
        "job_id": jid,
        "protocol": PROTOCOL_DAILY_PATH,
        "eval_kind": "daily_path",
        "parallel_model": "both_track_sleeve_fanout",
        "dry_run": bool(dry_run),
        "skipped_live_cf": skipped_live_cf,
        "logic_ids": ids,
        "n_logics": len(ids),
        "tracks": tracks_out,
        "n_tracks": len(tracks_out),
        "head_n_forbidden": True,
        "universe_select": "adv_desc_skip_missing_bars_and_fins",
        "compare": compare,
        "table_path": str(table_path),
        "git_sha": git_sha(cwd=ROOT),
        "factory_version": BOTH_TRACK_SLEEVE_FANOUT_VERSION,
        "promote_as_main": False,
        "go": False,
        "not_a_pass": True,
        "mass_research": MASS_RESEARCH,
        "survived": False,
        "candidate_grade": True,
        "period_net_dd_only_pass_forbidden": True,
        "liq_print_is_not_stable": True,
        "sleeve_majority_is_not_a_pass": True,
        "wall_sec": round(time.perf_counter() - t0, 3),
        "notes": "Both-track sleeve daily_path. Never head-N. Not a pass.",
    }
    table_path.write_text(
        json.dumps(pack, indent=2, default=str) + "\n", encoding="utf-8"
    )
    if not dry_run:
        from research.cf_mass_eval_stage import RESEARCH_ARTIFACT_BUCKET
        from research.r2_io import default_r2_put

        key = f"research/eval/job={jid}/both_track.json"
        default_r2_put(
            RESEARCH_ARTIFACT_BUCKET,
            key,
            json.dumps(pack, default=str).encode("utf-8"),
        )
        pack["r2_keys"] = {"both_track": key}
    return pack
