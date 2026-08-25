"""Occupancy-track / eval-wave run orchestration. Does not GO.

Daily-path fan-out and propose invoke. Classify, drift, usable snapshot, and
pack/R2 writes stay in occupancy_audit. Does not apply reconstitution.
Does not inject. Does not overwrite cells.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


def run_eval_wave(
    occupancy_by_track: Mapping[str, Mapping[str, float]] | None = None,
    *,
    wave: str | None = None,
    root: Path | None = None,
    put_r2: bool = False,
    propose: bool = True,
    propose_n: int = 3,
    invoke: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """One-call wave: occupancy maps + pack + propose write-gate. Never injects.

    Does not fan out occupancy. Does not apply reconstitution. Does not GO.
    """
    from research.cf_mass_eval_job import CfMassEvalError
    from research.eval_flags import CURRENT_EVAL_WAVE
    from research.occupancy_audit import (
        _float_occ_map,
        _ops_root,
        _put_eval_bytes,
        load_ops_occupancy,
        write_eval_wave_pack,
    )

    wave_id = str(wave or CURRENT_EVAL_WAVE).strip()
    if occupancy_by_track is None:
        occ: dict[str, dict[str, float]] = load_ops_occupancy(root)
    else:
        occ = {
            "mid_n_explore": _float_occ_map(occupancy_by_track.get("mid_n_explore")),
            "liq_large": _float_occ_map(occupancy_by_track.get("liq_large")),
        }
    pack = write_eval_wave_pack(occ, wave=wave_id, root=root, put_r2=put_r2)
    propose_job = f"eval-cf-propose-{wave_id}"
    propose_pack: dict[str, Any] = {
        "job_id": propose_job,
        "skipped": True,
        "written": False,
        "catalog_written": False,
        "auto_inject": False,
        "go": False,
        "not_a_pass": True,
    }
    puts = list(pack.get("puts") or [])
    if propose:
        from research.cf_propose_thesis import (
            invoke_cf_propose_thesis,
            propose_eval_pack,
        )

        fn = invoke or invoke_cf_propose_thesis
        try:
            invoke_out = fn(
                n=int(propose_n),
                write_artifacts=False,
                job_id=propose_job,
            )
        except (TimeoutError, CfMassEvalError) as exc:
            invoke_out = {
                "ok": False,
                "error": "llm_failed",
                "n_adoptable": 0,
                "proposals": [],
                "reviews": [],
                "exception": type(exc).__name__,
            }
        propose_pack = propose_eval_pack(
            invoke_out, occupancy_by_track=occ, job_id=propose_job
        )
        ops = _ops_root(root)
        raw = json.dumps(propose_pack, ensure_ascii=True, default=str)
        (ops / f"{propose_job}.json").write_text(raw, encoding="utf-8")
        put = _put_eval_bytes(
            job=propose_job,
            r2name="propose.json",
            body=raw.encode("utf-8"),
            put_r2=put_r2,
        )
        if put:
            puts.append(put)
    return {
        **pack,
        "wave": wave_id,
        "n_mid": len(occ.get("mid_n_explore") or {}),
        "n_liq": len(occ.get("liq_large") or {}),
        "propose_job": propose_job,
        "propose": propose_pack,
        "catalog_written": False,
        "auto_inject": False,
        "puts": puts,
        "go": False,
        "not_a_pass": True,
    }


def run_occupancy_track(
    *,
    job_id: str,
    logic_ids: Sequence[str],
    track: str,
    max_workers: int = 8,
    timeout: int = 300,
    write_artifacts: bool = True,
) -> dict[str, Any]:
    """One-track occupancy fanout. Does not overwrite cells.json. Does not GO."""
    from research.cf_daily_path_job import run_cf_daily_path_fanout
    from research.cf_mass_eval_job import (
        DEFAULT_MAX_DAYS,
        DEFAULT_REAL_MULTIYEAR_PERIODS,
        PANELS_CACHE_PREFIX,
        panels_cache_id,
    )
    from research.eval_tracks import eval_track
    from research.occupancy_audit import occupancy_from_cells_file

    ids = [str(x) for x in logic_ids if str(x).strip()]
    spec = eval_track(track)
    max_codes = int(spec["max_codes"])
    cid = panels_cache_id(
        DEFAULT_REAL_MULTIYEAR_PERIODS,
        max_codes=max_codes,
        max_days=DEFAULT_MAX_DAYS,
        track=track,
    )
    prefix = f"{PANELS_CACHE_PREFIX}/{cid}/panels"
    pack = run_cf_daily_path_fanout(
        job_id=job_id,
        logic_ids=ids,
        max_codes=max_codes,
        max_days=DEFAULT_MAX_DAYS,
        track=track,
        skip_stage=True,
        panels_prefix=prefix,
        mode="r2_panels",
        write_artifacts=bool(write_artifacts),
        timeout=int(timeout),
        max_workers=int(max_workers),
    )
    occ = dict(pack.get("occupancy_by_logic") or {})
    table_path = Path(pack.get("table_path") or "")
    if not occ and table_path.is_file():
        occ = occupancy_from_cells_file(table_path)
    missing = [x for x in ids if x not in occ]
    return {
        "job_id": job_id,
        "eval_track": track,
        "occupancy": occ,
        "missing": missing,
        "n_cells": pack.get("n_cells"),
        "n_complete": pack.get("n_daily_path_complete"),
        "n_errors": pack.get("n_errors"),
        "errors": pack.get("errors"),
        "table_path": pack.get("table_path"),
        "go": False,
        "not_a_pass": True,
    }


__all__ = [
    "run_eval_wave",
    "run_occupancy_track",
]
