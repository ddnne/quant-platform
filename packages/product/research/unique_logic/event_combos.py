"""New unique theses as combo gates (not numeric variants).

CF Worker eventHeld / gatedCsHeld is the candidate-grade path.
Catalog YAML under ``specs/research_logics`` is the declaration SoT
(gates / cs_gate / side) and the combo runtime dispatch table.
Does not promote / GO.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from research.daily_path_eval import held_book_daily_mtm, panel_index
from research.unique_logic.constants import (
    CF_NEW_THESIS_IDS,
    KNOWN_EVENT_GATES,
    WORKER_ISOLATE_LIMIT_IDS,
    is_ungated_name_level_cs,
    sparse_15name_reason,
)
from research.unique_logic.near_duplicate import is_near_duplicate
from research.unique_logic import event, event_filters, event_sides

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
        "why_different_from": list(s.get("why_different_from") or []),
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
    """Lazy-import catalog rows so ``yaml_combo_rows`` can call ``_combo_row``."""
    from research.unique_logic.catalog import yaml_combo_rows

    return tuple(yaml_combo_rows())


NEW_COMBO_LOGIC: tuple[dict[str, Any], ...] = _yaml_combo_runtime_rows()


def spec_by_id(logic_id: str) -> dict[str, Any] | None:
    for s in NEW_COMBO_LOGIC:
        if s["logic_id"] == logic_id:
            return s
    return None


def combo_runtime_spec(logic_id: str) -> dict[str, Any] | None:
    """YAML-derived runtime row for a combo thesis.

    Catalog YAML under ``specs/research_logics`` is declaration and combo
    dispatch SoT. ``NEW_COMBO_LOGIC`` is built from ``yaml_combo_rows``.
    Does not GO.
    """
    return spec_by_id(logic_id)


def assert_yaml_matches_specs(*, root: Any = None) -> None:
    """Fail if combo catalog YAML is missing required params or go=True.

    Every combo YAML (evaluator = evaluate_combo_daily_mtm) must declare
    ``params.gates`` (list, may be empty), ``params.cs_gate``, and
    ``params.side``. ``yaml_combo_rows()`` ids must equal those YAML stems.
    No spec may have ``go=True``. Does not GO.
    """
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
    lid = str(spec.get("logic_id") or "")
    declared = combo_runtime_spec(lid) or dict(spec)
    kind = str(declared.get("kind") or "event")
    extra_adv = adv_by_code or dict(
        ((declared.get("extra") or spec.get("extra") or {}).get("adv_by_code") or {})
    )
    if kind in {"event", "surprise_xs"}:
        return _eval_event_combo(
            declared,
            bars=bars,
            overnight=overnight,
            curve=curve,
            events=events,
            margin_by_code=margin_by_code,
            one_way_cost=one_way_cost,
            period_start=period_start,
            period_end=period_end,
            adv_by_code=extra_adv,
        )
    return _eval_cs_combo(
        declared,
        bars=bars,
        overnight=overnight,
        curve=curve,
        margin_by_code=margin_by_code,
        one_way_cost=one_way_cost,
    )


def _eval_event_combo(
    spec: Mapping[str, Any],
    *,
    bars: Mapping[str, Any],
    overnight: Mapping[str, float],
    curve: Mapping[str, Any],
    events: Mapping[str, Any],
    margin_by_code: Mapping[str, Mapping[str, float]],
    one_way_cost: float,
    period_start: str | None,
    period_end: str | None,
    adv_by_code: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    params = dict(spec.get("params") or {})
    gates = tuple(params.get("gates") or spec.get("gates") or ())
    side = str(params.get("side") or spec.get("side") or "orig")
    min_hist = int(params.get("min_hist") or 20)
    collected = event._collect_event_entries(
        bars, events, spec=spec, period_start=period_start, period_end=period_end
    )
    collected = event_filters._attach_disc_time(collected, events)
    extra: dict[str, Any] = {
        "combo_gates": list(gates),
        "side": side,
        "cf_native": True,
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
    fund = event_sides.classify_funding_entries(
        collected, overnight, min_hist=min_hist
    )
    abs_pairs = event_filters._abs_surprise_pairs(events)
    spread = dict((curve or {}).get("spread_by_date") or {})
    accept: dict[str, bool] = {}
    sign_mult: dict[str, float] = {}
    for ev in collected["entries"]:
        key = event_sides._event_key(ev)
        ok = True
        for g in gates:
            if g not in KNOWN_EVENT_GATES:
                ok = False
                continue
            if g == "easy_funding" and not fund["easy"].get(key):
                ok = False
            elif g == "tight_funding":
                on = overnight.get(ev["entry_date"])
                med = event.pit_median_on_dates(
                    overnight, [ev["entry_date"]], min_hist=min_hist
                ).get(ev["entry_date"])
                if on is None or med is None or float(on) < float(med):
                    ok = False
            elif g == "steep_curve" and float(spread.get(ev["entry_date"]) or 0) <= 0:
                ok = False
            elif g == "invert_curve" and float(spread.get(ev["entry_date"]) or 1) > 0:
                ok = False
            elif g == "afterclose":
                t = str(ev.get("disc_time") or "").strip()
                hh = int(t[:2]) if len(t) >= 2 and t[:2].isdigit() else -1
                if hh < 15:
                    ok = False
            elif g == "large_surprise":
                prior = [a for d, a in abs_pairs if d < ev["disc_date"]]
                if len(prior) < min_hist:
                    ok = False
                else:
                    prior_s = sorted(prior)
                    mid = len(prior_s) // 2
                    med = (
                        prior_s[mid]
                        if len(prior_s) % 2
                        else (prior_s[mid - 1] + prior_s[mid]) / 2
                    )
                    if abs(float(ev["surprise"])) < med:
                        ok = False
            elif g == "uncrowded_margin":
                series = dict((margin_by_code or {}).get(ev["code"]) or {})
                last = event_filters._last_print_before(series, ev["entry_date"])
                if last is None:
                    ok = False
                else:
                    med_by = event.pit_median_on_dates(
                        series, [ev["entry_date"]], min_hist=min_hist
                    )
                    med = med_by.get(ev["entry_date"])
                    if med is None or float(last[1]) >= float(med):
                        ok = False
            elif g == "crowded_margin":
                series = dict((margin_by_code or {}).get(ev["code"]) or {})
                last = event_filters._last_print_before(series, ev["entry_date"])
                med_by = event.pit_median_on_dates(
                    series, [ev["entry_date"]], min_hist=min_hist
                )
                med = med_by.get(ev["entry_date"])
                if last is None or med is None or float(last[1]) < float(med):
                    ok = False
            elif g == "pre_mom":
                pack = (collected.get("per_code") or {}).get(ev["code"]) or {}
                mom = event_filters._pre_entry_mom(
                    dlist=list(pack.get("dlist") or []),
                    close_by_code=(collected.get("close_by") or {}).get(ev["code"]) or {},
                    entry_idx=int(ev["entry_idx"]),
                    momentum_n=5,
                )
                if mom is None or mom == 0 or (1 if mom > 0 else -1) != int(ev["sign"]):
                    ok = False
            elif g == "cluster":
                disc_dates = sorted(
                    {str(e.get("disc_date") or "")[:10] for e in collected["entries"]}
                )
                entry_d = str(ev["entry_date"])[:10]
                n_disc = sum(
                    1
                    for x in disc_dates
                    if x < entry_d and x >= _add_days(entry_d, -5)
                )
                hist = {
                    dd: float(
                        sum(1 for x in disc_dates if x < dd and x >= _add_days(dd, -5))
                    )
                    for dd in disc_dates
                    if dd < entry_d
                }
                med_c = event.pit_median_on_dates(hist, [entry_d], min_hist=10).get(
                    entry_d
                )
                if med_c is None or n_disc < float(med_c):
                    ok = False
            elif g == "first_half_month":
                if str(ev["entry_date"])[8:10] > "15":
                    ok = False
            elif g == "month_end_skip":
                if str(ev["entry_date"])[8:10] >= "28":
                    ok = False
            elif g == "fy_end":
                if not (
                    str(ev["entry_date"])[5:7] == "03"
                    and str(ev["entry_date"])[8:10] >= "15"
                ):
                    ok = False
            elif g == "fy_results":
                if str(ev["entry_date"])[5:7] != "05":
                    ok = False
            elif g == "fy_start":
                if str(ev["entry_date"])[5:7] != "04":
                    ok = False
            elif g == "overnight_easing":
                d = str(ev["entry_date"])[:10]
                prevs = sorted(x for x in overnight if x < d)
                if not prevs or overnight.get(d) is None:
                    ok = False
                elif float(overnight[d]) >= float(overnight[prevs[-1]]):
                    ok = False
            elif g == "overnight_tightening":
                d = str(ev["entry_date"])[:10]
                prevs = sorted(x for x in overnight if x < d)
                if not prevs or overnight.get(d) is None:
                    ok = False
                elif float(overnight[d]) <= float(overnight[prevs[-1]]):
                    ok = False
            elif g == "skip_monday":
                if _weekday(str(ev["entry_date"])) == 0:
                    ok = False
            elif g == "tue_thu":
                if _weekday(str(ev["entry_date"])) not in {1, 2, 3}:
                    ok = False
            elif g == "friday_skip":
                if _weekday(str(ev["entry_date"])) == 4:
                    ok = False
            elif g == "friday_only":
                if _weekday(str(ev["entry_date"])) != 4:
                    ok = False
            elif g == "skip_tuesday":
                if _weekday(str(ev["entry_date"])) == 1:
                    ok = False
            elif g == "skip_wednesday":
                if _weekday(str(ev["entry_date"])) == 2:
                    ok = False
            elif g == "not_last_week":
                if str(ev["entry_date"])[8:10] >= "24":
                    ok = False
            elif g == "month_start7":
                if str(ev["entry_date"])[8:10] > "07":
                    ok = False
            elif g == "not_first_week":
                if str(ev["entry_date"])[8:10] <= "07":
                    ok = False
            elif g == "on_impulse":
                d = str(ev["entry_date"])[:10]
                prevs = sorted(x for x in overnight if x < d)
                if not prevs or overnight.get(d) is None:
                    ok = False
                else:
                    abs_ch = abs(float(overnight[d]) - float(overnight[prevs[-1]]))
                    hist = {}
                    prev_list = list(prevs)
                    for i, dd in enumerate(prev_list[1:], start=1):
                        hist[dd] = abs(float(overnight[dd]) - float(overnight[prev_list[i - 1]]))
                    med = event.pit_median_on_dates(hist, [d], min_hist=20).get(d)
                    if med is None or abs_ch < float(med):
                        ok = False
            elif g == "invert_curve":
                if float(spread.get(ev["entry_date"]) or 1) > 0:
                    ok = False
            elif g == "positive_eps":
                if ev.get("eps") is None or float(ev.get("eps") or 0) <= 0:
                    ok = False
            elif g == "eps_up":
                if ev.get("eps") is None or ev.get("prior_eps") is None:
                    ok = False
                elif float(ev["eps"]) <= float(ev["prior_eps"]):
                    ok = False
            elif g == "midmonth":
                dd = str(ev["entry_date"])[8:10]
                if dd < "10" or dd > "20":
                    ok = False
            elif g == "div_positive":
                if ev.get("div_ann") is None or float(ev.get("div_ann") or 0) <= 0:
                    ok = False
            elif g == "eq_ar_high" or g == "eq_ar_low":
                val = ev.get("eq_ar")
                if val is None:
                    ok = False
                else:
                    hist: dict[str, float] = {}
                    for row in list(events.get(ev["code"]) or []):
                        dd = str(row.get("disc_date") or "")[:10]
                        q = row.get("eq_ar")
                        if dd and dd < ev["entry_date"] and q is not None:
                            hist[dd] = float(q)
                    med = event.pit_median_on_dates(
                        hist, [ev["entry_date"]], min_hist=8
                    ).get(ev["entry_date"])
                    if med is None:
                        ok = False
                    elif g == "eq_ar_high" and float(val) < float(med):
                        ok = False
                    elif g == "eq_ar_low" and float(val) >= float(med):
                        ok = False
            elif g == "ta_up":
                if ev.get("ta") is None or ev.get("prior_ta") is None:
                    ok = False
                elif float(ev["ta"]) <= float(ev["prior_ta"]):
                    ok = False
            elif g == "cheap_pb":
                bps = ev.get("bps")
                close = ((collected.get("close_by") or {}).get(ev["code"]) or {}).get(
                    ev["entry_date"]
                )
                if bps is None or close is None or float(bps) == 0:
                    ok = False
                else:
                    pb = float(close) / float(bps)
                    hist = {}
                    cmap = (collected.get("close_by") or {}).get(ev["code"]) or {}
                    fins = list(events.get(ev["code"]) or [])
                    for dd, px in sorted(cmap.items()):
                        if dd >= ev["entry_date"]:
                            break
                        fin = None
                        for row in fins:
                            x = str(row.get("disc_date") or "")[:10]
                            if x and x <= dd:
                                fin = row
                        b = (fin or {}).get("bps") if fin else None
                        if b is not None and float(b) != 0 and px:
                            hist[dd] = float(px) / float(b)
                    med = event.pit_median_on_dates(
                        hist, [ev["entry_date"]], min_hist=min_hist
                    ).get(ev["entry_date"])
                    if med is None or pb >= float(med):
                        ok = False
            elif g == "margin_up" or g == "margin_down":
                series = dict((margin_by_code or {}).get(ev["code"]) or {})
                prior = sorted(k for k in series if k < ev["entry_date"])
                if len(prior) < 2:
                    ok = False
                else:
                    delta = float(series[prior[-1]]) - float(series[prior[-2]])
                    if g == "margin_up" and delta <= 0:
                        ok = False
                    if g == "margin_down" and delta >= 0:
                        ok = False
            elif g == "overnight_p10":
                d = str(ev["entry_date"])[:10]
                on = overnight.get(d)
                hist = [overnight[x] for x in overnight if x < d]
                if len(hist) < min_hist or on is None:
                    ok = False
                else:
                    srt = sorted(hist)
                    p10 = srt[max(0, int(0.1 * (len(srt) - 1)))]
                    if float(on) > float(p10):
                        ok = False
            elif g == "curve_flatten":
                d = str(ev["entry_date"])[:10]
                prevs = sorted(x for x in spread if x < d)
                sp = spread.get(d)
                if not prevs or sp is None:
                    ok = False
                elif float(sp) >= float(spread[prevs[-1]]):
                    ok = False
            elif g == "repo_3m_down":
                d = str(ev["entry_date"])[:10]
                prevs = sorted(x for x in overnight if x < d)
                on = overnight.get(d)
                sp = spread.get(d)
                if not prevs or on is None or sp is None:
                    ok = False
                else:
                    prev = prevs[-1]
                    psp = spread.get(prev)
                    pon = overnight.get(prev)
                    if psp is None or pon is None:
                        ok = False
                    elif float(on) + float(sp) >= float(pon) + float(psp):
                        ok = False
            elif g == "liq_high":
                adv_map = dict(adv_by_code or {})
                adv = adv_map.get(ev["code"])
                vals = [float(v) for v in adv_map.values() if v is not None]
                if adv is None or len(vals) < 4:
                    ok = False
                else:
                    med = sorted(vals)[len(vals) // 2]
                    if float(adv) < float(med):
                        ok = False
            elif g == "price_down":
                pack = (collected.get("per_code") or {}).get(ev["code"]) or {}
                dlist = list(pack.get("dlist") or [])
                close_by = (collected.get("close_by") or {}).get(ev["code"]) or {}
                i = int(ev.get("entry_idx") or 0)
                if i < 5 or not dlist:
                    ok = False
                else:
                    c0 = close_by.get(dlist[i - 5])
                    c1 = close_by.get(dlist[i] if i < len(dlist) else None)
                    if c0 is None or c1 is None or float(c0) == 0:
                        ok = False
                    elif (float(c1) / float(c0) - 1.0) >= 0:
                        ok = False
            elif g in {"cheap_iv", "rich_iv", "nky_vol_high_skip"}:
                # Worker SoT: needs panel vol sidecar. Missing → skip, no invent.
                ok = False
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
                accept[event_sides._event_key(ev)] = False
                continue
            rec["entry_idx"] = i0
            rec["entry_date"] = dlist[i0]
            new_entries.append(rec)
        collected = dict(collected)
        collected["entries"] = new_entries
    if str(spec.get("kind")) == "surprise_xs":
        collected = dict(collected)
        collected["entries"] = [
            ev
            for ev in collected["entries"]
            if accept.get(event_sides._event_key(ev), False)
        ]
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
                if accept.get(event_sides._event_key(ev), False)
            ],
        )
        pack["logic_id"] = spec["logic_id"]
        pack["combo_gates"] = list(gates)
        pack["promote_as_main"] = False
        pack["go"] = False
        return pack
    return event_sides._finish_signed_event_book(
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
    curve: Mapping[str, Any],
    margin_by_code: Mapping[str, Mapping[str, float]],
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
    spread = dict((curve or {}).get("spread_by_date") or {})
    gate = str(spec.get("cs_gate") or params.get("cs_gate") or "")
    extra_cf_only: list[str] = []
    for i, d in enumerate(dates):
        on = overnight.get(d)
        prev_on = overnight.get(dates[i - 1]) if i else None
        med_on = None
        if overnight:
            med_on = event.pit_median_on_dates(overnight, [d], min_hist=20).get(d)
        keep = True
        loc_invert = invert
        if gate == "overnight_easy":
            keep = on is not None and med_on is not None and float(on) < float(med_on)
        elif gate == "overnight_tight_invert":
            keep = on is not None and med_on is not None and float(on) >= float(med_on)
            loc_invert = True
        elif gate == "curve_invert_invert":
            keep = float(spread.get(d) or 1) <= 0
            loc_invert = True
        elif gate == "month_start":
            keep = d[8:10] <= "05"
        elif gate == "overnight_up":
            keep = prev_on is not None and on is not None and float(on) > float(prev_on)
        elif gate == "fy_end_invert":
            keep = d[5:7] == "03" and d[8:10] >= "15"
            loc_invert = True
        elif gate == "fy_start":
            keep = d[5:7] == "04"
        elif gate == "curve_steep":
            keep = float(spread.get(d) or 0) > 0
        elif gate == "overnight_p90_invert":
            hist = [overnight[x] for x in overnight if x < d]
            if len(hist) < 20 or on is None:
                keep = False
            else:
                srt = sorted(hist)
                p90 = srt[int(0.9 * (len(srt) - 1))]
                keep = float(on) >= float(p90)
                loc_invert = True
        elif gate == "margin_crowd_chase":
            keep = _universe_margin_delta(margin_by_code, d) > 0
            loc_invert = True
        elif gate == "margin_decrowd":
            keep = _universe_margin_delta(margin_by_code, d) < 0
        elif gate == "margin_change_nonzero":
            keep = _universe_margin_delta(margin_by_code, d) != 0
        elif gate == "repo_3m_up":
            prev_sp = spread.get(dates[i - 1]) if i else None
            sp = spread.get(d)
            keep = (
                prev_on is not None
                and on is not None
                and prev_sp is not None
                and sp is not None
                and (float(on) + float(sp)) > (float(prev_on) + float(prev_sp))
            )
        elif gate == "skip_monday":
            keep = _weekday(d) != 0
        elif gate == "skip_tuesday":
            keep = _weekday(d) != 1
        elif gate == "skip_wednesday":
            keep = _weekday(d) != 2
        elif gate == "not_last_week":
            keep = d[8:10] < "24"
        elif gate == "month_start7":
            keep = d[8:10] <= "07"
        elif gate == "not_first_week":
            keep = d[8:10] > "07"
        elif gate == "overnight_easy_skip_friday":
            med_on = event.pit_median_on_dates(overnight, [d], min_hist=20).get(d) if overnight else None
            keep = (
                _weekday(d) != 4
                and on is not None
                and med_on is not None
                and float(on) < float(med_on)
            )
        elif gate == "margin_crowd_skip_friday_invert":
            keep = _weekday(d) != 4 and _universe_margin_delta(margin_by_code, d) > 0
            loc_invert = True
        elif gate == "overnight_down_skip_tuesday":
            keep = (
                _weekday(d) != 1
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "margin_up":
            keep = _universe_margin_delta(margin_by_code, d) > 0
        elif gate == "margin_down":
            keep = _universe_margin_delta(margin_by_code, d) < 0
        elif gate == "on_impulse":
            if prev_on is None or on is None:
                keep = False
            else:
                abs_ch = abs(float(on) - float(prev_on))
                hist = {}
                for j in range(1, i):
                    a = overnight.get(dates[j])
                    b = overnight.get(dates[j - 1])
                    if a is not None and b is not None:
                        hist[dates[j]] = abs(float(a) - float(b))
                med = event.pit_median_on_dates(hist, [d], min_hist=20).get(d) if hist else None
                keep = med is not None and abs_ch >= float(med)
        elif gate == "overnight_p10":
            hist = [overnight[x] for x in overnight if x < d]
            if len(hist) < 20 or on is None:
                keep = False
            else:
                srt = sorted(hist)
                p10 = srt[max(0, int(0.1 * (len(srt) - 1)))]
                keep = float(on) <= float(p10)
        elif gate == "repo_3m_down":
            prev_sp = spread.get(dates[i - 1]) if i else None
            sp = spread.get(d)
            keep = (
                prev_on is not None
                and on is not None
                and prev_sp is not None
                and sp is not None
                and (float(on) + float(sp)) < (float(prev_on) + float(prev_sp))
            )
        elif gate == "curve_flatten":
            prev_sp = spread.get(dates[i - 1]) if i else None
            sp = spread.get(d)
            keep = prev_sp is not None and sp is not None and float(sp) < float(prev_sp)
        elif gate in {
            "eq_ar_high_margin_down",
            "ta_up_margin_down",
            "cheap_pb_easy",
            "eq_ar_high_on_impulse",
            "cheap_pb_margin_down",
            "eq_ar_low_margin_up_invert",
        }:
            extra_cf_only.append(gate)
            keep = False
        elif gate == "tue_thu":
            keep = _weekday(d) in {1, 2, 3}
        elif gate == "overnight_down":
            keep = (
                prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "overnight_up_invert":
            keep = (
                prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
            loc_invert = True
        elif gate == "midmonth":
            keep = d[8:10] >= "10" and d[8:10] <= "20"
        elif gate == "friday_invert":
            keep = _weekday(d) == 4
            loc_invert = True
        elif gate == "not_month_end":
            keep = d[8:10] < "28"
        elif gate == "midmonth_overnight_down":
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "tue_thu_overnight_down":
            keep = (
                _weekday(d) in {1, 2, 3}
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "overnight_down_skip_monday":
            keep = (
                _weekday(d) != 0
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "friday_overnight_up_invert":
            keep = (
                _weekday(d) == 4
                and prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
            loc_invert = True
        elif gate == "margin_crowd_midmonth_invert":
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and _universe_margin_delta(margin_by_code, d) > 0
            )
            loc_invert = True
        elif gate == "curve_steep_midmonth":
            keep = d[8:10] >= "10" and d[8:10] <= "20" and float(spread.get(d) or 0) > 0
        elif gate == "tue_thu_overnight_up":
            keep = (
                _weekday(d) in {1, 2, 3}
                and prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
        elif gate == "curve_steep_skip_monday":
            keep = _weekday(d) != 0 and float(spread.get(d) or 0) > 0
        elif gate == "midmonth_overnight_up_invert":
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
            loc_invert = True
        elif gate == "margin_crowd_tue_thu_invert":
            keep = (
                _weekday(d) in {1, 2, 3}
                and _universe_margin_delta(margin_by_code, d) > 0
            )
            loc_invert = True
        elif gate == "first_half_overnight_down":
            keep = (
                d[8:10] <= "15"
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "midmonth_overnight_up":
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
        elif gate == "month_start_overnight_down":
            keep = (
                d[8:10] <= "05"
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "month_start10_overnight_down":
            keep = (
                d[8:10] <= "10"
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "iv_below_skip_monday":
            vol = _vol_sidecar()
            keep = _weekday(d) != 0 and _apply_vol_gate(
                "iv_below_basevol", d, dates[i - 1] if i else None, vol
            )
            if not vol:
                extra_cf_only.append(gate)
        elif gate == "friday_overnight_down":
            keep = (
                _weekday(d) == 4
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "tue_thu_curve_steep":
            keep = _weekday(d) in {1, 2, 3} and float(spread.get(d) or 0) > 0
        elif gate == "overnight_up_skip_monday":
            keep = (
                _weekday(d) != 0
                and prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
        elif gate == "margin_crowd_skip_monday_invert":
            keep = _weekday(d) != 0 and _universe_margin_delta(margin_by_code, d) > 0
            loc_invert = True
        elif gate == "overnight_easy_skip_monday":
            med_on = event.pit_median_on_dates(overnight, [d], min_hist=20).get(d) if overnight else None
            keep = (
                _weekday(d) != 0
                and on is not None
                and med_on is not None
                and float(on) < float(med_on)
            )
        elif gate == "overnight_down_skip_friday":
            keep = (
                _weekday(d) != 4
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "midmonth_overnight_easy":
            med_on = event.pit_median_on_dates(overnight, [d], min_hist=20).get(d) if overnight else None
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and on is not None
                and med_on is not None
                and float(on) < float(med_on)
            )
        elif gate == "tue_thu_overnight_easy":
            med_on = event.pit_median_on_dates(overnight, [d], min_hist=20).get(d) if overnight else None
            keep = (
                _weekday(d) in {1, 2, 3}
                and on is not None
                and med_on is not None
                and float(on) < float(med_on)
            )
        elif gate == "friday_curve_steep":
            keep = _weekday(d) == 4 and float(spread.get(d) or 0) > 0
        elif gate == "nky_compress_midmonth":
            vol = _vol_sidecar()
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and _apply_vol_gate("nky_term_compress", d, dates[i - 1] if i else None, vol)
            )
            if not vol:
                extra_cf_only.append(gate)
        elif gate == "iv_below_midmonth":
            vol = _vol_sidecar()
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and _apply_vol_gate("iv_below_basevol", d, dates[i - 1] if i else None, vol)
            )
            if not vol:
                extra_cf_only.append(gate)
        elif gate in {
            "opt225_skew_high",
            "nky_term_high",
            "opt225_spread_wide",
            "nky_term_compress",
            "opt225_skew_and_term",
            "basevol_up",
            "iv_below_basevol",
        }:
            vol = _vol_sidecar()
            keep = _apply_vol_gate(gate, d, dates[i - 1] if i else None, vol)
            if not vol:
                extra_cf_only.append(gate)
        elif gate in {
            "eq_ar_high",
            "eq_ar_low_invert",
            "ta_up",
            "eq_ar_high_easy",
            "eq_ar_high_cheap_iv",
            "eq_ar_high_repo3m_down",
            "eq_ar_high_flatten",
            "margin_down_easy",
            "overnight_p10_steep",
            "repo3m_down_easy",
            "cheap_pb_cheap_iv",
            "eq_ar_high_overnight_p10",
            "ta_up_easy",
            "margin_up_easy",
            "curve_flatten_easy",
            "eq_ar_low_tight_invert",
            "cheap_pb",
            "expensive_pb_invert",
            "earnings_yield_high",
            "roe_high",
            "div_positive",
            "np_positive",
            "nky_vol_high_invert",
            "short_ratio_up_invert",
            "short_ratio_down",
            "margin_up_tight_invert",
        }:
            # Name-level fund/flow extras are Worker SoT. Local skip, no invent.
            keep = False
            extra_cf_only.append(gate)
        elif gate:
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
        extra={"cs_gate": gate, "cf_native": True},
        repo_by_date=overnight,
    )
    pack.update(
        {
            "logic_id": spec["logic_id"],
            "status": "ok",
            "cs_gate": gate,
            "promote_as_main": False,
            "go": False,
            "cf_native": True,
            "cf_only_gates": extra_cf_only,
            "python_skipped_cf_only": bool(extra_cf_only),
        }
    )
    return pack


def _add_days(iso: str, n: int) -> str:
    from datetime import date, timedelta

    try:
        y, m, d = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
        return (date(y, m, d) + timedelta(days=n)).isoformat()
    except (TypeError, ValueError):
        return iso


def _weekday(iso: str) -> int:
    """Monday=0 … Sunday=6. Invalid date → -1 (gate fail-closed)."""
    from datetime import date

    try:
        return date(int(iso[:4]), int(iso[5:7]), int(iso[8:10])).weekday()
    except (TypeError, ValueError):
        return -1


_VOL_CACHE: dict[str, dict[str, float]] | None = None


def _vol_sidecar() -> dict[str, dict[str, float]]:
    global _VOL_CACHE
    if _VOL_CACHE is not None:
        return _VOL_CACHE
    out: dict[str, dict[str, float]] = {}
    try:
        from research.eval_universe import (
            load_nky_vol_series_from_sqlite,
            load_opt225_regime_bundle_for_eval,
        )

        nky = load_nky_vol_series_from_sqlite() or {}
        out["nky_term"] = {
            str(k)[:10]: float(v)
            for k, v in dict(nky.get("rv_ratio_by_date") or {}).items()
            if v is not None
        }
        opt = load_opt225_regime_bundle_for_eval() or {}
        def _abs(series: Any) -> dict[str, float]:
            if not isinstance(series, dict):
                return {}
            raw = series.get("rv_abs_by_date") or series
            if not isinstance(raw, dict):
                return {}
            return {str(k)[:10]: float(v) for k, v in raw.items() if v is not None}

        out["skew"] = _abs(opt.get("skew") or {})
        out["spread"] = _abs(opt.get("spread") or {})
        out["basevol"] = _abs(opt.get("basevol") or {})
        out["nky_abs"] = {
            str(k)[:10]: float(v)
            for k, v in dict(nky.get("rv_abs_by_date") or {}).items()
            if v is not None
        }
    except Exception:
        out = {}
    _VOL_CACHE = out
    return out


def _apply_vol_gate(
    gate: str,
    d: str,
    prev: str | None,
    vol: Mapping[str, Mapping[str, float]],
) -> bool:
    if not vol:
        return False
    if gate == "nky_term_high":
        series = vol.get("nky_term") or {}
        med = event.pit_median_on_dates(series, [d], min_hist=20).get(d)
        v = series.get(d)
        return med is not None and v is not None and float(v) >= float(med)
    if gate == "nky_term_compress":
        series = vol.get("nky_term") or {}
        if not prev:
            return False
        a, b = series.get(d), series.get(prev)
        return a is not None and b is not None and float(a) < float(b)
    if gate == "opt225_skew_high":
        series = vol.get("skew") or {}
        med = event.pit_median_on_dates(series, [d], min_hist=20).get(d)
        v = series.get(d)
        return med is not None and v is not None and float(v) >= float(med)
    if gate == "opt225_spread_wide":
        series = vol.get("spread") or {}
        med = event.pit_median_on_dates(
            {k: abs(float(x)) for k, x in series.items()}, [d], min_hist=20
        ).get(d)
        v = series.get(d)
        return med is not None and v is not None and abs(float(v)) >= float(med)
    if gate == "opt225_skew_and_term":
        return _apply_vol_gate("opt225_skew_high", d, prev, vol) and _apply_vol_gate(
            "nky_term_high", d, prev, vol
        )
    if gate == "basevol_up":
        series = vol.get("basevol") or {}
        if not prev:
            return False
        a, b = series.get(d), series.get(prev)
        return a is not None and b is not None and float(a) > float(b)
    if gate == "iv_below_basevol":
        series = vol.get("spread") or {}
        v = series.get(d)
        return v is not None and float(v) < 0
    return False


def _universe_margin_delta(
    margin_by_code: Mapping[str, Mapping[str, float]],
    query: str,
) -> float:
    deltas: list[float] = []
    q = str(query)[:10]
    for series in (margin_by_code or {}).values():
        prior = sorted(d for d in series if str(d)[:10] < q)
        if len(prior) < 2:
            continue
        a = series[prior[-2]]
        b = series[prior[-1]]
        try:
            deltas.append(float(b) - float(a))
        except (TypeError, ValueError):
            continue
    if not deltas:
        return 0.0
    return sum(deltas) / len(deltas)
