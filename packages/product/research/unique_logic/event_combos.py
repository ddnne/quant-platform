"""Combo theses: YAML dispatch, CF Worker occupancy path. Does not GO."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from research.daily_path_eval import held_book_daily_mtm, panel_index
from research.unique_logic.constants import (
    CF_NEW_THESIS_IDS,
    WORKER_ISOLATE_LIMIT_IDS,
    is_ungated_name_level_cs,
    sparse_15name_reason,
)
from research.unique_logic.near_duplicate import is_near_duplicate
from research.unique_logic import event

COMBO_LOGIC_IDS: frozenset[str] = frozenset(CF_NEW_THESIS_IDS)


def _combo_row(s: Mapping[str, Any]) -> dict[str, Any]:
    sparse = sparse_15name_reason(
        logic_id=str(s.get("logic_id") or ""),
        gates=[str(g) for g in (s.get("gates") or ())],
        cs_gate=str(s.get("cs_gate") or ""),
    )
    dup = is_near_duplicate(str(s.get("logic_id") or ""))
    ao = is_ungated_name_level_cs(
        kind=str(s.get("kind") or ""),
        cs_gate=str(s.get("cs_gate") or ""),
        logic_id=str(s.get("logic_id") or ""),
    )
    isolate = str(s.get("logic_id") or "") in WORKER_ISOLATE_LIMIT_IDS
    main_pool = False if (sparse or dup or ao or isolate) else bool(s.get("main_pool", True))
    return {
        **dict(s),
        "new_unique_logic": True,
        "catalog": True,
        "headline": False,
        "promote_as_main": False,
        "go": False,
        "generation_enabled": False,
        "main_pool": main_pool,
        "data_requirement_unmet": bool(sparse),
        "worker_isolate_limit": isolate,
        "near_duplicate": dup,
        "always_on_cs_sticky": ao,
        "sparse_15name_reason": sparse,
        "params": {
            "post_hold_days": 5,
            "hold_days": 10,
            "momentum_n": 5,
            "min_hist": 20,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "gates": list(s.get("gates") or ()),
            "side": s.get("side") or "orig",
            "cs_gate": s.get("cs_gate"),
            "entry_shift": s.get("entry_shift") or 0,
            "hold_tail_days": s.get("hold_tail_days") or 0,
            "mode": s["logic_id"],
        },
        "datasets": [
            "equities_bars_daily",
            "fins_summary",
            "jsda_tokyo_repo_rates",
            "markets_calendar",
        ],
        "signal_definition": s["thesis"],
        "position_rule": "PIT gates; missing sidecar → skip (no ffill / no invent)",
        "evaluator": "research.unique_logic.event_combos.evaluate_combo_daily_mtm",
    }


def _yaml_combo_runtime_rows() -> tuple[dict[str, Any], ...]:
    """Lazy-import: ``yaml_combo_rows`` calls ``_combo_row``."""
    from research.unique_logic.catalog import yaml_combo_rows

    return tuple(yaml_combo_rows())


NEW_COMBO_LOGIC: tuple[dict[str, Any], ...] = _yaml_combo_runtime_rows()


def spec_by_id(logic_id: str) -> dict[str, Any] | None:
    for s in NEW_COMBO_LOGIC:
        if s["logic_id"] == logic_id:
            return s
    return None


combo_runtime_spec = spec_by_id


def assert_yaml_matches_specs(*, root: Any = None) -> None:
    """Fail if combo YAML is missing gates/cs_gate/side or sets go=True."""
    from research.unique_logic.catalog import (
        _COMBO_EVALUATOR,
        load_catalog_specs,
        yaml_combo_rows,
    )

    combo_yaml = [
        s
        for s in load_catalog_specs(root=root)
        if str(s.get("evaluator") or "") == _COMBO_EVALUATOR
    ]
    problems: list[str] = []
    stems: set[str] = set()
    for spec in combo_yaml:
        lid = str(spec.get("logic_id") or "")
        path = spec.get("catalog_path")
        stem = Path(str(path)).stem if path else lid
        stems.add(stem)
        if spec.get("go") is True:
            problems.append(f"{lid}: go=True")
        params = spec.get("params")
        if not isinstance(params, Mapping):
            problems.append(f"{lid}: YAML params missing")
            continue
        if "gates" not in params:
            problems.append(f"{lid}: YAML params missing gates")
        elif not isinstance(params.get("gates"), list):
            problems.append(f"{lid}: YAML params.gates not a list")
        if "cs_gate" not in params:
            problems.append(f"{lid}: YAML params missing cs_gate")
        if "side" not in params:
            problems.append(f"{lid}: YAML params missing side")
    if problems:
        raise AssertionError("combo YAML self-check: " + " | ".join(problems[:40]))

    row_ids = {str(r["logic_id"]) for r in yaml_combo_rows(root=root)}
    if row_ids != stems:
        missing = sorted(stems - row_ids)
        extra = sorted(row_ids - stems)
        parts: list[str] = []
        if missing:
            parts.append("yaml_combo_rows missing ids: " + ", ".join(missing[:40]))
        if extra:
            parts.append("yaml_combo_rows extra ids: " + ", ".join(extra[:40]))
        raise AssertionError("combo YAML self-check: " + " | ".join(parts))


def evaluate_combo_daily_mtm(
    spec: Mapping[str, Any],
    *,
    bars: Mapping[str, Any],
    overnight: Mapping[str, float],
    curve: Mapping[str, Any],
    events: Mapping[str, Any],
    margin_by_code: Mapping[str, Mapping[str, float]],
    topix_by_date: Mapping[str, float] | None = None,
    one_way_cost: float = 0.001,
    period_start: str | None = None,
    period_end: str | None = None,
    adv_by_code: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Python fallback for combo theses. CF Worker is the SoT path."""
    del curve, margin_by_code, topix_by_date, adv_by_code
    lid = str(spec.get("logic_id") or "")
    declared = combo_runtime_spec(lid) or dict(spec)
    kind = str(declared.get("kind") or "event")
    if kind in {"event", "surprise_xs"}:
        return _eval_event_combo(
            declared,
            bars=bars,
            overnight=overnight,
            events=events,
            one_way_cost=one_way_cost,
            period_start=period_start,
            period_end=period_end,
        )
    return _eval_cs_combo(
        declared,
        bars=bars,
        overnight=overnight,
        one_way_cost=one_way_cost,
    )


def _eval_event_combo(
    spec: Mapping[str, Any],
    *,
    bars: Mapping[str, Any],
    overnight: Mapping[str, float],
    events: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None,
    period_end: str | None,
) -> dict[str, Any]:
    params = dict(spec.get("params") or {})
    gates = tuple(params.get("gates") or spec.get("gates") or ())
    side = str(params.get("side") or spec.get("side") or "orig")
    collected = event._collect_event_entries(
        bars, events, spec=spec, period_start=period_start, period_end=period_end
    )
    extra: dict[str, Any] = {
        "promote_as_main": False,
        "go": False,
    }
    if collected.get("n_events") == 0:
        return {
            "status": "no_events_in_shard",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": "no events in shard",
            **extra,
        }
    accept: dict[str, bool] = {}
    sign_mult: dict[str, float] = {}
    for ev in collected["entries"]:
        key = event._event_key(ev)
        # Worker comboEventGateOk is SoT; local fallback is ungated only.
        ok = not gates
        accept[key] = ok
        sign_mult[key] = -1.0 if side == "flip" else 1.0
    shift = int(params.get("entry_shift") or spec.get("entry_shift") or 0)
    tail = int(params.get("hold_tail_days") or spec.get("hold_tail_days") or 0)
    if shift or tail:
        new_entries = []
        per = dict(collected.get("per_code") or {})
        for ev in collected["entries"]:
            rec = dict(ev)
            pack = per.get(rec["code"]) or {}
            dlist = list(pack.get("dlist") or [])
            i0 = int(rec["entry_idx"]) + shift
            if tail:
                end0 = min(int(rec["entry_idx"]) + int(collected["hold_days"]), len(dlist))
                i0 = max(i0, end0 - tail)
            if i0 < 0 or i0 >= len(dlist):
                accept[event._event_key(ev)] = False
                continue
            rec["entry_idx"] = i0
            rec["entry_date"] = dlist[i0]
            new_entries.append(rec)
        collected = dict(collected)
        collected["entries"] = new_entries
    if str(spec.get("kind")) == "surprise_xs":
        pack = event.evaluate_surprise_xs_rank_hold_daily_mtm(
            bars,
            events,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=period_start,
            period_end=period_end,
            entries=[
                ev
                for ev in collected["entries"]
                if accept.get(event._event_key(ev), False)
            ],
        )
        return pack
    return event._finish_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
        sign_mult_by_key=sign_mult,
        repo_by_date=overnight,
    )


def _eval_cs_combo(
    spec: Mapping[str, Any],
    *,
    bars: Mapping[str, Any],
    overnight: Mapping[str, float],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom occupancy with a date gate (matches Worker gatedCsHeld)."""
    from features.class_signals import cross_section_rank_signs

    params = dict(spec.get("params") or {})
    n = int(params.get("momentum_n") or 5)
    idx = panel_index(bars, momentum_n=n)
    dates = list(idx.get("dates") or [])
    h = int(params.get("hold_days") or 10)
    lf = float(params.get("long_frac") or 0.3)
    sf = float(params.get("short_frac") or 0.3)
    invert = str(spec.get("cs_gate") or params.get("cs_gate") or "") in {
        "always_invert",
        "overnight_tight_invert",
        "curve_invert_invert",
    }
    close_by = idx.get("close_by") or {}
    scores_by_date: dict[str, dict[str, float]] = {d: {} for d in dates}
    for code, cmap in close_by.items():
        for i, d in enumerate(dates):
            if i < n:
                continue
            c0 = cmap.get(dates[i - n])
            c1 = cmap.get(d)
            if c0 and c1 and c0 != 0:
                scores_by_date[d][code] = (c1 / c0) - 1.0
    held: dict[str, dict[str, float | None]] = {
        c: {d: None for d in dates} for c in close_by
    }
    gate = str(spec.get("cs_gate") or params.get("cs_gate") or "")
    for d in dates:
        keep = True
        loc_invert = invert
        if gate:
            # Worker comboCsGateOk is SoT.
            keep = False
        scores = scores_by_date.get(d) or {}
        if not keep or len(scores) < 2:
            continue
        ranks = cross_section_rank_signs(scores, long_frac=lf, short_frac=sf)
        for code, sgn in ranks.items():
            if sgn is None:
                continue
            v = -float(sgn) if loc_invert else float(sgn)
            held.setdefault(code, {})[d] = v
    sticky: dict[str, dict[str, float]] = {}
    for code, cmap in held.items():
        sticky[code] = {}
        held_pos = 0.0
        since = 0
        for i, d in enumerate(dates):
            entry = cmap.get(d)
            if i == 0 or since >= h:
                if entry is not None:
                    held_pos = float(entry)
                since = 1
            else:
                since += 1
            sticky[code][d] = held_pos
    pack = held_book_daily_mtm(
        held_by_code_date=sticky,
        close_by=idx.get("close_by") or {},
        dates=dates,
        hold_days=h,
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra={"cs_gate": gate},
        repo_by_date=overnight,
    )
    return pack
