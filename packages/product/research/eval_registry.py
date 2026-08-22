"""Experiment job index contract (R2 artifacts + small D1 rows).

Git is not the eval warehouse. Local ``.glm-logs`` is scratch.
A run is recorded only when a manifest is written under
``quant-structured/research/eval/job={id}/`` (and, when wired, a D1 row).

Mass / READY / GO remain closed. This module does not promote candidates.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

EVAL_REGISTRY_VERSION: str = "research-eval-registry/v1"
R2_BUCKET: str = "quant-structured"
R2_PREFIX: str = "research/eval"
PROTOCOL_CF_SCREEN: str = "cf_mass_eval_period_net"
PROTOCOL_DAILY_PATH: str = "daily_path_mtm_after_cost/v1"
# Candidate SoT is daily_path. Period-net is bar-native auxiliary only.
CANDIDATE_EVAL_SOT: str = PROTOCOL_DAILY_PATH
PERIOD_NET_NOT_CANDIDATE_GRADE: bool = True


def is_path_collapsed_cell(cell: Mapping[str, Any]) -> bool:
    """True when period-net MDH fallback ate a unique/event/CS logic."""
    extra = cell.get("extra") if isinstance(cell.get("extra"), Mapping) else {}
    if cell.get("path_collapsed") or extra.get("path_collapsed"):
        return True
    sig = str(cell.get("signal_id") or extra.get("signal_id") or "")
    if sig.startswith("c21_lite_fallback_mdh"):
        return True
    reason = str(cell.get("skip_reason") or extra.get("skip_reason") or "")
    return reason.startswith("unique_unsupported") or reason.startswith("path_collapsed")


def is_path_broken_cell(cell: Mapping[str, Any]) -> bool:
    """True when the eval path is generic CS/MDH fallback or tagged broken."""
    if is_path_collapsed_cell(cell):
        return True
    extra = cell.get("extra") if isinstance(cell.get("extra"), Mapping) else {}
    path = str(cell.get("eval_path") or extra.get("eval_path") or "")
    fallback = str(cell.get("path_fallback") or extra.get("path_fallback") or "")
    if path in {"cs_generic", "mdh_generic", "unknown"}:
        return True
    return fallback.startswith("path_broken") or fallback.startswith("mdh_empty")


def is_daily_path_complete_cell(cell: Mapping[str, Any]) -> bool:
    """Candidate-grade complete: DD measured and the path is not broken."""
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
    promote_as_main: bool = False
    go: bool = False
    mass: str = "NO-GO"
    research_candidate: bool = False
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
            "mass": "NO-GO",
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
    """Scratch copy only — not SoT. R2/D1 is the record."""
    from pathlib import Path as P

    staging = P(staging_dir)
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
    """Small index rows for D1. No bars. MCP remains read-only."""
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
        f"'{job['r2_prefix']}', 'recorded', 0, 0, 'NO-GO', 0, '{notes}'"
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


def list_eval_jobs_from_d1(*, limit: int = 20) -> list[dict[str, Any]]:
    """Thin D1 job index (no scores copied into Git)."""
    import subprocess
    from qp_paths import repo_root

    root = repo_root()
    wr = (
        root
        / "platform"
        / "workers"
        / "ingestion-premium"
        / "node_modules"
        / ".bin"
        / "wrangler"
    )
    wr_bin = str(wr) if wr.is_file() else "npx"
    cmd = [wr_bin] if wr.is_file() else ["npx", "wrangler"]
    sql = (
        "SELECT job_id, protocol, n_logics, n_cells, status, r2_prefix, "
        "created_at FROM research_eval_jobs "
        f"ORDER BY created_at DESC LIMIT {int(limit)};"
    )
    cmd += [
        "d1",
        "execute",
        "quant-ingest",
        "--remote",
        "--json",
        f"--command={sql}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        return [{"error": (proc.stderr or proc.stdout or "d1 list failed")[:500]}]
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [{"error": "d1 json parse failed", "stdout": proc.stdout[:300]}]
    rows: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for block in payload:
            for r in (block.get("results") or []) if isinstance(block, dict) else []:
                if isinstance(r, dict):
                    rows.append(r)
    elif isinstance(payload, dict):
        for r in payload.get("results") or []:
            if isinstance(r, dict):
                rows.append(r)
    return rows


def family_counts(logic_ids: Sequence[str]) -> dict[str, int]:
    """Bucket logic_ids for a job listing (no scores)."""
    from research.unique_logic.constants import (
        CF_EVENT_DAILY_PATH_IDS,
        CF_NEW_CS_THESIS_IDS,
        CF_NEW_EVENT_THESIS_IDS,
        CS_LOGIC_IDS,
    )

    out = {"event": 0, "event_new": 0, "unique_cs": 0, "cs_new": 0, "other": 0}
    for lid in logic_ids:
        if lid in CF_NEW_EVENT_THESIS_IDS:
            out["event_new"] += 1
        elif lid in CF_EVENT_DAILY_PATH_IDS:
            out["event"] += 1
        elif lid in CF_NEW_CS_THESIS_IDS:
            out["cs_new"] += 1
        elif lid in CS_LOGIC_IDS:
            out["unique_cs"] += 1
        else:
            out["other"] += 1
    return out


def summarize_daily_path_cells(
    cells: Sequence[Mapping[str, Any]],
    *,
    job_id: str,
) -> dict[str, Any]:
    """Family/logic flags from daily_path cells. Scores stay off Git."""
    from collections import Counter, defaultdict

    from research.cf_mass_eval_job import CF_BAR_NATIVE_LOGIC_IDS
    from research.unique_logic.constants import (
        ALWAYS_ON_OCCUPANCY_WARN,
        CANDIDATE_POLICY,
        CF_EVENT_DAILY_PATH_IDS,
        CF_NEW_CS_THESIS_IDS,
        CF_NEW_EVENT_THESIS_IDS,
        CS_LOGIC_IDS,
        NEAR_EMPTY_OCCUPANCY,
        TERM_STRUCTURE_REQUIRED,
        SPARSE_ON_15NAME_SHARD,
    )

    def _fam(lid: str) -> str:
        if lid in CF_NEW_EVENT_THESIS_IDS:
            return "event_new"
        if lid in CF_EVENT_DAILY_PATH_IDS:
            return "event"
        if lid in CF_NEW_CS_THESIS_IDS:
            return "cs_new"
        if lid in CS_LOGIC_IDS:
            return "unique_cs"
        if lid in CF_BAR_NATIVE_LOGIC_IDS:
            return "bar_native"
        return "other"

    by: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for c in cells:
        by[str(c.get("logic_id") or "")].append(c)

    def _mean(xs: list[Any]) -> float | None:
        vs = [float(x) for x in xs if x is not None]
        return (sum(vs) / len(vs)) if vs else None

    logics: list[dict[str, Any]] = []
    for lid, cs in by.items():
        if not lid:
            continue
        occs = [c.get("occupancy") if c.get("occupancy") is not None else c.get("occupancy_frac") for c in cs]
        nets = [c.get("total_ret_net") for c in cs]
        signs = [
            1 if (n or 0) > 1e-6 else (-1 if (n or 0) < -1e-6 else 0) for n in nets
        ]
        n_pos = sum(s > 0 for s in signs)
        n_neg = sum(s < 0 for s in signs)
        m_occ = _mean(occs)
        m_net = _mean(nets)
        paths = sorted(
            {
                str(c.get("eval_path") or "")
                for c in cs
                if c.get("eval_path")
            }
        )
        fallbacks = sorted(
            {
                str(c.get("path_fallback") or "")
                for c in cs
                if c.get("path_fallback")
            }
        )
        flags: list[str] = []
        if any(is_path_collapsed_cell(c) for c in cs):
            flags.append("path_collapsed")
        if any(is_path_broken_cell(c) for c in cs) or any(
            p in {"cs_generic", "mdh_generic"} for p in paths
        ) or any(
            str(f).startswith("path_broken") or str(f).startswith("mdh_empty")
            for f in fallbacks
        ):
            flags.append("path_broken")
        if m_occ is not None and m_occ >= ALWAYS_ON_OCCUPANCY_WARN:
            flags.append("always_on")
        if m_occ is not None and m_occ <= float(NEAR_EMPTY_OCCUPANCY):
            flags.append("near_empty")
        if lid in TERM_STRUCTURE_REQUIRED and (
            m_occ is None or m_occ <= float(NEAR_EMPTY_OCCUPANCY)
        ):
            flags.append("data_requirement_unmet")
        if lid in SPARSE_ON_15NAME_SHARD:
            flags.append("data_requirement_unmet")
        if m_net is not None and abs(m_net) < 1e-4:
            flags.append("near_zero_net")
        if n_pos >= 2 and n_neg >= 2:
            flags.append("sign_unstable")
        tag = "weak"
        if "path_collapsed" in flags:
            tag = "path_collapsed"
        elif "path_broken" in flags:
            tag = "path_broken"
        elif "always_on" in flags or "near_empty" in flags:
            tag = "suspicious"
        elif (
            m_net is not None
            and m_net > 0
            and n_pos >= 4
            and "sign_unstable" not in flags
            and "path_broken" not in flags
            and "always_on" not in flags
        ):
            tag = "strong"
        elif "sign_unstable" in flags:
            tag = "unstable"
        t_stats = [c.get("t_stat") for c in cs]
        sharpes = [c.get("sharpe_daily") for c in cs]
        dds = [c.get("daily_path_DD") for c in cs]
        exclude = set(CANDIDATE_POLICY["exclude"])  # type: ignore[arg-type]
        candidate = not bool(exclude.intersection(flags))
        logics.append(
            {
                "logic_id": lid,
                "family": _fam(lid),
                "n_windows": len(cs),
                "mean_occupancy": m_occ,
                "mean_total_ret_net": m_net,
                "mean_t_stat": _mean(t_stats),
                "mean_sharpe_daily": _mean(sharpes),
                "mean_daily_path_DD": _mean(dds),
                "n_pos_windows": n_pos,
                "n_neg_windows": n_neg,
                "eval_paths": paths,
                "path_fallbacks": fallbacks,
                "flags": flags,
                "tag": tag,
                "explore_flagged": tag == "strong",
                "candidate": candidate,
                "main_pool": candidate,
                "explore_only": True,
                "promote_as_main": False,
                "go": False,
            }
        )
    tags = Counter(r["tag"] for r in logics)
    fams = Counter(r["family"] for r in logics)
    cand_fams = Counter(r["family"] for r in logics if r.get("candidate"))
    return {
        "version": "eval-family-summary/v1",
        "job_id": job_id,
        "n_logics": len(logics),
        "n_cells": len(cells),
        "tag_counts": dict(tags),
        "family_counts": dict(fams),
        "n_strong": int(tags.get("strong") or 0),
        "n_weak": int(tags.get("weak") or 0),
        "n_suspicious": int(tags.get("suspicious") or 0),
        "n_unstable": int(tags.get("unstable") or 0),
        "n_path_broken": int(tags.get("path_broken") or 0),
        "n_path_collapsed": int(tags.get("path_collapsed") or 0),
        "n_always_on": sum(1 for r in logics if "always_on" in r["flags"]),
        "n_complete_cells": sum(1 for c in cells if is_daily_path_complete_cell(c)),
        "n_candidate_logics": sum(1 for r in logics if r.get("candidate")),
        "candidate_family_counts": dict(cand_fams),
        "n_near_empty": sum(1 for r in logics if "near_empty" in r["flags"]),
        "n_data_requirement_unmet": sum(
            1 for r in logics if "data_requirement_unmet" in r["flags"]
        ),
        "always_on_excluded_from_main": True,
        "near_empty_excluded_from_candidate": True,
        "path_broken_excluded_from_complete": True,
        "path_collapsed_excluded_from_complete": True,
        "path_collapsed_excluded_from_candidate": True,
        "strong_t_floor": None,
        "strong_sharpe_floor": None,
        "simple_strategies_kept_for_combinations": True,
        "candidate_policy": dict(CANDIDATE_POLICY),
        "always_on_warn": ALWAYS_ON_OCCUPANCY_WARN,
        "n_survivors_are_not_a_pass": True,
        "promote_as_main": False,
        "go": False,
        "logics": logics,
        "notes": (
            "candidate = not path_broken, not path_collapsed, not always_on, "
            "not near_empty, not data_requirement_unmet. Simple gated theses stay for "
            "combination/funds even with modest t/Sharpe. strong is an "
            "interest flag with no t/Sharpe floor and is never a promote/GO."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    p = argparse.ArgumentParser(description="Eval registry index (D1/R2). No Git scores.")
    p.add_argument("--list", action="store_true", help="List recent D1 research_eval_jobs")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--summarize-table", type=Path, help="JSON cells array")
    p.add_argument("--job-id", default="")
    args = p.parse_args(argv)
    if args.list:
        rows = list_eval_jobs_from_d1(limit=int(args.limit))
        print(json.dumps({"n": len(rows), "jobs": rows, "scores_in_git": False}, indent=2, default=str))
        return 0
    if args.summarize_table:
        cells = json.loads(Path(args.summarize_table).read_text(encoding="utf-8"))
        if not isinstance(cells, list):
            raise SystemExit("summarize-table must be a JSON array")
        print(json.dumps(summarize_daily_path_cells(cells, job_id=str(args.job_id or "unknown")), indent=2, default=str))
        return 0
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
