"""Verify daily_path cost ON vs OFF and ADV-bucket drag. Not a pass / not GO.

Uses ``held_book_daily_mtm`` (same daily_path eval path). dry_run=True skips
live CF. Does not write score tables to Git.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
from uuid import uuid4

from research.daily_path_eval import held_book_daily_mtm
from research.eval_registry import PROTOCOL_DAILY_PATH
from research.freezes import MASS_RESEARCH

COST_VERIFY_VERSION = "cf-cost-verify/v1"
HIGH_ADV_JPY = 2e9
LOW_ADV_JPY = 1e7

_SYN_DATES = ("2024-01-02", "2024-01-03", "2024-01-04")
_SYN_CODE = "7203"


def _synthetic_book() -> tuple[
    list[str],
    dict[str, dict[str, float]],
    dict[str, dict[str, float]],
]:
    dates = list(_SYN_DATES)
    held = {_SYN_CODE: {dates[0]: 1.0, dates[1]: 1.0}}
    close = {
        _SYN_CODE: {dates[0]: 100.0, dates[1]: 101.0, dates[2]: 102.0},
    }
    return dates, held, close


def _occupancy(pack: Mapping[str, Any]) -> float | None:
    n_cal = int(pack.get("n_calendar_days") or 0)
    n_act = int(pack.get("n_active_days") or 0)
    if n_cal < 2:
        return None
    return float(n_act) / float(n_cal - 1)


def _path_cost_drag(pack: Mapping[str, Any]) -> float:
    gross = list(pack.get("gross_daily") or [])
    net = list(pack.get("net_daily") or [])
    drag = 0.0
    for i in range(1, min(len(gross), len(net))):
        drag += float(gross[i]) - float(net[i])
    return drag


def _nets_differ(a: Sequence[float], b: Sequence[float]) -> bool:
    if len(a) != len(b):
        return True
    for x, y in zip(a, b):
        if abs(float(x) - float(y)) > 1e-15:
            return True
    return False


def _run_mtm(
    *,
    logic_id: str,
    one_way: float,
    hold_days: int,
    held_by_code_date: Mapping[str, Mapping[str, float | None]],
    close_by: Mapping[str, Mapping[str, float]],
    dates: Sequence[str],
    repo_by_date: Mapping[str, float] | None,
    adv_by_code: Mapping[str, float] | None,
) -> dict[str, Any]:
    return held_book_daily_mtm(
        held_by_code_date=held_by_code_date,
        close_by=close_by,
        dates=dates,
        hold_days=hold_days,
        one_way_cost=float(one_way),
        logic_id=logic_id,
        repo_by_date=repo_by_date,
        adv_by_code=adv_by_code,
    )


def run_cost_on_off_compare(
    *,
    logic_ids: Sequence[str],
    one_way_on: float = 0.001,
    one_way_off: float = 0.0,
    dry_run: bool = True,
    hold_days: int = 10,
    held_by_code_date: Mapping[str, Mapping[str, float | None]] | None = None,
    close_by: Mapping[str, Mapping[str, float]] | None = None,
    dates: Sequence[str] | None = None,
    repo_by_date: Mapping[str, float] | None = None,
    adv_by_code: Mapping[str, float] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Compare cost ON vs OFF and high vs low ADV on the daily_path held book.

    dry_run=True (default): no live CF, no Git score write. This helper never
    fires CF even if dry_run=False.
    """
    ids = [str(x) for x in logic_ids if str(x).strip()]
    if not ids:
        raise ValueError("logic_ids required")
    syn_dates, syn_held, syn_close = _synthetic_book()
    use_dates = list(dates) if dates is not None else syn_dates
    use_held = dict(held_by_code_date) if held_by_code_date is not None else syn_held
    use_close = dict(close_by) if close_by is not None else syn_close
    use_adv = (
        dict(adv_by_code)
        if adv_by_code is not None
        else {_SYN_CODE: HIGH_ADV_JPY}
    )
    jid = str(job_id or f"eval-cf-cost-{uuid4().hex[:10]}")
    lid0 = ids[0]
    h = int(hold_days)

    on_pack = _run_mtm(
        logic_id=lid0,
        one_way=one_way_on,
        hold_days=h,
        held_by_code_date=use_held,
        close_by=use_close,
        dates=use_dates,
        repo_by_date=repo_by_date,
        adv_by_code=use_adv,
    )
    off_pack = _run_mtm(
        logic_id=lid0,
        one_way=one_way_off,
        hold_days=h,
        held_by_code_date=use_held,
        close_by=use_close,
        dates=use_dates,
        repo_by_date=repo_by_date,
        adv_by_code=use_adv,
    )
    occ = _occupancy(on_pack)
    occupied = float(occ or 0.0) > 0.0
    on_off_differs = _nets_differ(
        list(on_pack.get("net_daily") or []),
        list(off_pack.get("net_daily") or []),
    )
    on_off_must_differ = occupied and float(one_way_on) > 0.0 and float(one_way_on) != float(
        one_way_off
    )

    high_pack = _run_mtm(
        logic_id=lid0,
        one_way=one_way_on,
        hold_days=h,
        held_by_code_date=syn_held,
        close_by=syn_close,
        dates=syn_dates,
        repo_by_date=None,
        adv_by_code={_SYN_CODE: HIGH_ADV_JPY},
    )
    low_pack = _run_mtm(
        logic_id=lid0,
        one_way=one_way_on,
        hold_days=h,
        held_by_code_date=syn_held,
        close_by=syn_close,
        dates=syn_dates,
        repo_by_date=None,
        adv_by_code={_SYN_CODE: LOW_ADV_JPY},
    )
    high_drag = _path_cost_drag(high_pack)
    low_drag = _path_cost_drag(low_pack)

    missing_pack = _run_mtm(
        logic_id=lid0,
        one_way=one_way_on,
        hold_days=h,
        held_by_code_date=syn_held,
        close_by=syn_close,
        dates=syn_dates,
        repo_by_date=None,
        adv_by_code=None,
    )
    missing_nets = [float(x) for x in (missing_pack.get("net_daily") or [])[1:]]
    missing_skipped = bool(missing_pack.get("cost_adv_incomplete")) and all(
        abs(x) < 1e-15 for x in missing_nets
    )

    short_dates, short_held, short_close = _synthetic_book()
    short_held = {_SYN_CODE: {short_dates[0]: -1.0, short_dates[1]: -1.0}}
    short_on = _run_mtm(
        logic_id=lid0,
        one_way=one_way_on,
        hold_days=h,
        held_by_code_date=short_held,
        close_by=short_close,
        dates=short_dates,
        repo_by_date=repo_by_date or {"2024-01-02": 0.001, "2024-01-03": 0.001},
        adv_by_code=use_adv,
    )
    short_off = _run_mtm(
        logic_id=lid0,
        one_way=one_way_off,
        hold_days=h,
        held_by_code_date=short_held,
        close_by=short_close,
        dates=short_dates,
        repo_by_date=repo_by_date or {"2024-01-02": 0.001, "2024-01-03": 0.001},
        adv_by_code=use_adv,
    )
    short_differs = _nets_differ(
        list(short_on.get("net_daily") or []),
        list(short_off.get("net_daily") or []),
    )

    turn_held = {_SYN_CODE: {short_dates[0]: 1.0, short_dates[1]: -1.0}}
    turn_on = _run_mtm(
        logic_id=lid0,
        one_way=one_way_on,
        hold_days=1,
        held_by_code_date=turn_held,
        close_by=short_close,
        dates=short_dates,
        repo_by_date=None,
        adv_by_code=use_adv,
    )
    turn_off = _run_mtm(
        logic_id=lid0,
        one_way=one_way_off,
        hold_days=1,
        held_by_code_date=turn_held,
        close_by=short_close,
        dates=short_dates,
        repo_by_date=None,
        adv_by_code=use_adv,
    )
    turn_differs = _nets_differ(
        list(turn_on.get("net_daily") or []),
        list(turn_off.get("net_daily") or []),
    )

    written = False
    r2_key = None
    rows = []
    for lid in ids:
        rows.append(
            {
                "logic_id": lid,
                "occupancy": occ,
                "n_active_days": on_pack.get("n_active_days"),
                "cost_adv_incomplete": bool(on_pack.get("cost_adv_incomplete")),
                "on_off_differs": on_off_differs,
            }
        )
    out = {
        "version": COST_VERIFY_VERSION,
        "protocol": PROTOCOL_DAILY_PATH,
        "job_id": jid,
        "logic_ids": ids,
        "n_logics": len(ids),
        "one_way_on": float(one_way_on),
        "one_way_off": float(one_way_off),
        "dry_run": bool(dry_run),
        "skipped_live_cf": True,
        "written_git_scores": False,
        "r2_key": r2_key,
        "not_a_pass": True,
        "go": False,
        "promote_as_main": False,
        "mass_research": MASS_RESEARCH,
        "on_off": {
            "differs": on_off_differs,
            "must_differ": on_off_must_differ,
            "occupancy": occ,
            "occupied": occupied,
            "net_daily_on": list(on_pack.get("net_daily") or []),
            "net_daily_off": list(off_pack.get("net_daily") or []),
        },
        "adv_bucket": {
            "high_adv": HIGH_ADV_JPY,
            "low_adv": LOW_ADV_JPY,
            "cost_drag_high": high_drag,
            "cost_drag_low": low_drag,
            "high_cheaper": abs(high_drag) < abs(low_drag),
        },
        "missing_adv": {
            "cost_adv_incomplete": bool(missing_pack.get("cost_adv_incomplete")),
            "n_active_days": missing_pack.get("n_active_days"),
            "net_daily": list(missing_pack.get("net_daily") or []),
            "skipped_no_invent": missing_skipped,
        },
        "short_book": {
            "differs": short_differs,
            "cost_adv_incomplete": bool(short_on.get("cost_adv_incomplete")),
        },
        "high_turnover": {
            "differs": turn_differs,
            "cost_adv_incomplete": bool(turn_on.get("cost_adv_incomplete")),
        },
        "rows": rows,
        "notes": "daily_path cost verify. Not a promotion.",
    }
    if not dry_run:
        import json

        from research.cf_mass_eval_stage import RESEARCH_ARTIFACT_BUCKET
        from research.r2_io import put_research_artifact

        key = f"research/eval/job={jid}/cost_verify.json"
        put_research_artifact(
            RESEARCH_ARTIFACT_BUCKET,
            key,
            json.dumps(out, default=str).encode("utf-8"),
        )
        out["r2_key"] = key
        out["written"] = True
    return out
