"""Experiment job index contract (R2 artifacts + small D1 rows).

Git is not the eval warehouse. A run is recorded when a manifest is written
under ``quant-structured/research/eval/job={id}/``. Mass / READY / GO closed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from features.research_freezes import MASS_RESEARCH

EVAL_REGISTRY_VERSION: str = "research-eval-registry/v1"
R2_PREFIX: str = "research/eval"
PROTOCOL_DAILY_PATH: str = "daily_path_mtm_after_cost/v1"


def is_path_collapsed_cell(cell: Mapping[str, Any]) -> bool:
    extra = cell.get("extra") if isinstance(cell.get("extra"), Mapping) else {}
    if cell.get("path_collapsed") or extra.get("path_collapsed"):
        return True
    sig = str(cell.get("signal_id") or extra.get("signal_id") or "")
    if sig.startswith("c21_lite_fallback_mdh"):
        return True
    reason = str(cell.get("skip_reason") or extra.get("skip_reason") or "")
    return reason.startswith("unique_unsupported") or reason.startswith("path_collapsed")


def is_path_broken_cell(cell: Mapping[str, Any]) -> bool:
    if is_path_collapsed_cell(cell):
        return True
    extra = cell.get("extra") if isinstance(cell.get("extra"), Mapping) else {}
    path = str(cell.get("eval_path") or extra.get("eval_path") or "")
    fallback = str(cell.get("path_fallback") or extra.get("path_fallback") or "")
    if path in {"cs_generic", "mdh_generic", "unknown"}:
        return True
    return fallback.startswith("path_broken") or fallback.startswith("mdh_empty")


def is_daily_path_complete_cell(cell: Mapping[str, Any]) -> bool:
    if is_path_broken_cell(cell):
        return False
    return bool(cell.get("daily_path_complete"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def r2_job_prefix(job_id: str) -> str:
    jid = str(job_id).strip()
    if not jid:
        raise ValueError("job_id required")
    return f"{R2_PREFIX}/job={jid}"


def r2_manifest_key(job_id: str) -> str:
    return f"{r2_job_prefix(job_id)}/manifest.json"


def r2_cells_key(job_id: str) -> str:
    return f"{r2_job_prefix(job_id)}/cells.json"


@dataclass(frozen=True)
class EvalCell:
    logic_id: str
    window_id: str
    daily_path_DD: float | None = None
    total_ret_net: float | None = None
    occupancy: float | None = None
    dd_duration: int | None = None
    recovered: bool | None = None
    n_days: int | None = None
    survived: bool = False
    daily_path_complete: bool = False
    params_hash: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        row = {
            "logic_id": self.logic_id,
            "window_id": self.window_id,
            "daily_path_DD": self.daily_path_DD,
            "total_ret_net": self.total_ret_net,
            "occupancy": self.occupancy,
            "dd_duration": self.dd_duration,
            "recovered": self.recovered,
            "n_days": self.n_days,
            "survived": self.survived,
            "daily_path_complete": self.daily_path_complete,
            "params_hash": self.params_hash,
        }
        if self.extra:
            row["extra"] = dict(self.extra)
        return row


@dataclass(frozen=True)
class EvalJobManifest:
    job_id: str
    protocol: str
    git_sha: str | None
    logic_ids: tuple[str, ...]
    window_ids: tuple[str, ...]
    one_way_cost: float
    cells: tuple[EvalCell, ...]
    created_at: str = field(default_factory=_now)
    factory_version: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": EVAL_REGISTRY_VERSION,
            "job_id": self.job_id,
            "protocol": self.protocol,
            "git_sha": self.git_sha,
            "created_at": self.created_at,
            "factory_version": self.factory_version,
            "logic_ids": list(self.logic_ids),
            "window_ids": list(self.window_ids),
            "one_way_cost": self.one_way_cost,
            "n_logics": len(self.logic_ids),
            "n_windows": len(self.window_ids),
            "n_cells": len(self.cells),
            "n_daily_path_complete": sum(
                1 for c in self.cells if c.daily_path_complete
            ),
            "r2_prefix": r2_job_prefix(self.job_id),
            "r2_manifest_key": r2_manifest_key(self.job_id),
            "r2_cells_key": r2_cells_key(self.job_id),
            "promote_as_main": False,
            "go": False,
            "mass": MASS_RESEARCH,
            "research_candidate": False,
            "notes": self.notes,
            "cells": [c.to_dict() for c in self.cells],
        }


def manifest_from_window_rows(
    *,
    job_id: str,
    protocol: str,
    git_sha: str | None,
    rows: Sequence[Mapping[str, Any]],
    one_way_cost: float,
    factory_version: str | None = None,
    notes: str = "",
) -> EvalJobManifest:
    cells: list[EvalCell] = []
    logics: list[str] = []
    windows: list[str] = []
    for row in rows:
        lid = str(row.get("logic_id") or "")
        wid = str(row.get("window") or row.get("window_id") or "")
        if not lid or not wid:
            continue
        if lid not in logics:
            logics.append(lid)
        if wid not in windows:
            windows.append(wid)
        dd = row.get("daily_path_DD")
        if dd is None:
            dd = row.get("max_dd")
        occ = row.get("occupancy_frac")
        if occ is None:
            occ = row.get("occupancy")
        cells.append(
            EvalCell(
                logic_id=lid,
                window_id=wid,
                daily_path_DD=None if dd is None else float(dd),
                total_ret_net=(
                    None
                    if row.get("total_ret_net") is None
                    else float(row.get("total_ret_net"))  # type: ignore[arg-type]
                ),
                occupancy=None if occ is None else float(occ),
                dd_duration=(
                    None
                    if row.get("dd_duration") is None
                    and row.get("dd_duration_days") is None
                    else int(row.get("dd_duration") or row.get("dd_duration_days") or 0)
                ),
                recovered=row.get("recovered"),
                n_days=(
                    None if row.get("n_days") is None else int(row.get("n_days"))
                ),
                survived=bool(row.get("survived")),
                daily_path_complete=is_daily_path_complete_cell(row),
                params_hash=(
                    None
                    if row.get("params_hash") is None
                    else str(row.get("params_hash"))
                ),
                extra={
                    k: row[k]
                    for k in (
                        "t_stat",
                        "sharpe_daily",
                        "eval_path",
                        "path_fallback",
                    )
                    if k in row
                },
            )
        )
    return EvalJobManifest(
        job_id=job_id,
        protocol=protocol,
        git_sha=git_sha,
        logic_ids=tuple(logics),
        window_ids=tuple(windows),
        one_way_cost=float(one_way_cost),
        cells=tuple(cells),
        factory_version=factory_version,
        notes=notes,
    )


def dumps_manifest(manifest: EvalJobManifest) -> str:
    return json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False, default=str) + "\n"


def write_manifest_local(manifest: EvalJobManifest, staging_dir: Path) -> Path:
    staging = Path(staging_dir)
    job_dir = staging / "research_eval" / f"job={manifest.job_id}"
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "manifest.json"
    path.write_text(dumps_manifest(manifest), encoding="utf-8")
    cells_path = job_dir / "cells.json"
    cells_path.write_text(
        json.dumps([c.to_dict() for c in manifest.cells], indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def d1_upsert_sql(manifest: EvalJobManifest) -> str:
    job = manifest.to_dict()
    notes = (job.get("notes") or "").replace("'", "''")
    sha = job.get("git_sha") or ""
    sha_sql = "NULL" if not sha else f"'{sha}'"
    fv = job.get("factory_version") or ""
    fv_sql = "NULL" if not fv else f"'{str(fv).replace(chr(39), chr(39)*2)}'"
    lines = [
        "INSERT INTO research_eval_jobs ("
        "job_id, created_at, protocol, git_sha, factory_version, "
        "n_logics, n_windows, n_cells, one_way_cost, r2_prefix, status, "
        "promote_as_main, go_flag, mass, research_candidate, notes"
        ") VALUES ("
        f"'{job['job_id']}', '{job['created_at']}', '{job['protocol']}', "
        f"{sha_sql}, {fv_sql}, {job['n_logics']}, {job['n_windows']}, "
        f"{job['n_cells']}, {float(job['one_way_cost'])}, "
        f"'{job['r2_prefix']}', 'recorded', 0, 0, '{MASS_RESEARCH}', 0, '{notes}'"
        ") ON CONFLICT(job_id) DO UPDATE SET "
        "n_cells=excluded.n_cells, status='recorded';",
    ]
    for cell in job["cells"]:
        rec = 1 if cell.get("recovered") else 0 if cell.get("recovered") is not None else "NULL"
        dd = cell.get("daily_path_DD")
        net = cell.get("total_ret_net")
        occ = cell.get("occupancy")
        dur = cell.get("dd_duration")
        nd = cell.get("n_days")
        ph = cell.get("params_hash")
        ph_sql = "NULL" if not ph else f"'{str(ph).replace(chr(39), chr(39)*2)}'"

        def _n(v: object) -> str:
            return "NULL" if v is None else str(v)

        lines.append(
            "INSERT INTO research_eval_cells ("
            "job_id, logic_id, window_id, daily_path_DD, total_ret_net, occupancy, "
            "dd_duration, recovered, n_days, survived, daily_path_complete, params_hash"
            ") VALUES ("
            f"'{job['job_id']}', '{cell['logic_id']}', '{cell['window_id']}', "
            f"{_n(dd)}, {_n(net)}, {_n(occ)}, {_n(dur)}, {rec}, {_n(nd)}, "
            f"{1 if cell.get('survived') else 0}, "
            f"{1 if cell.get('daily_path_complete') else 0}, {ph_sql}"
            ") ON CONFLICT(job_id, logic_id, window_id) DO UPDATE SET "
            "daily_path_DD=excluded.daily_path_DD, total_ret_net=excluded.total_ret_net;"
        )
    return "\n".join(lines) + "\n"
