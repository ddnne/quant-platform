"""Rate/flow/fund thicken sidecars + NKY/opt225 attach. No invent/ffill. Not GO."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from pit.personal_research_view import PersonalResearchDataView
from research.eval_loaders import (
    build_repo_curve_series,
    load_fins_events_from_sqlite,
    load_margin_from_sqlite,
    load_nky_vol_series_from_sqlite,
    load_opt225_regime_bundle_for_eval,
    load_repo_rows_all_tenors_from_sqlite,
    load_repo_rows_from_sqlite,
    load_short_ratio_series_from_sqlite,
)
from research.options_225_vol_series import (
    DATASET_ID,
    OPTIONS_225_VOL_SERIES_VERSION,
)


def _require_view(view: Any) -> PersonalResearchDataView:
    if not isinstance(view, PersonalResearchDataView):
        raise TypeError("eval sqlite loaders require PersonalResearchDataView")
    return view


def _load_markets_calendar_map(
    view: PersonalResearchDataView,
    *,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    bound = _require_view(view)
    hol: dict[str, str] = {}
    day = str(end or start or "").strip()[:10]
    if not day:
        return {"hol_div_by_date": {}}
    window_start = str(start or day)[:10]
    for page in bound.iter_decision_pages(
        decision_date=day,
        dataset="markets_calendar",
        codes=(),
        start=window_start,
        end=day,
    ):
        for row in page:
            payload = row.get("payload") or row.get("raw_payload")
            if not isinstance(payload, Mapping):
                continue
            stamp = str(payload.get("Date") or str(row.get("event_time") or "")[:10])[:10]
            if not stamp:
                continue
            hol_div = payload.get("HolDiv")
            if hol_div is None:
                hol_div = payload.get("HolidayDivision")
            hol[stamp] = str(hol_div) if hol_div is not None else ""
    return {"hol_div_by_date": hol}


def _build_thicken_sidecars(
    period: Mapping[str, Any],
    *,
    codes: Sequence[str],
    view: PersonalResearchDataView,
) -> dict[str, Any]:
    from research.cost_models import load_repo_rate_series_from_rows

    bound = _require_view(view)
    p_start = str(period.get("period_start") or period.get("start") or "")[:10]
    p_end = str(period.get("period_end") or period.get("end") or "")[:10]
    burn_start = p_start
    if p_start:
        try:
            year, month, day = int(p_start[:4]), int(p_start[5:7]), int(p_start[8:10])
            year -= 2
            burn_start = f"{year:04d}-{month:02d}-{day:02d}"
        except ValueError:
            burn_start = p_start

    out: dict[str, Any] = {}
    cal = _load_markets_calendar_map(
        bound, start=burn_start or None, end=p_end or None
    )
    out["calendar"] = {"hol_div_by_date": cal.get("hol_div_by_date") or {}}

    as_of_s = str(p_end or "")[:10]
    if not as_of_s:
        raise ValueError("as_of is required (PIT has no latest default)")
    overnight = load_repo_rows_from_sqlite(
        bound, as_of=as_of_s, start=burn_start or None, end=p_end or None
    )
    series = load_repo_rate_series_from_rows(overnight) if overnight else None
    all_tenors = load_repo_rows_all_tenors_from_sqlite(
        bound, as_of=as_of_s, start=burn_start or None, end=p_end or None
    )
    curve = build_repo_curve_series(all_tenors) if all_tenors else {}
    rates_by_date = dict((series or {}).get("rates_by_date") or {})
    if p_start or p_end:
        rates_by_date = {
            day: float(value)
            for day, value in rates_by_date.items()
            if (not burn_start or day >= burn_start) and (not p_end or day <= p_end)
        }
    spread_by = dict(curve.get("spread_by_date") or {})
    if p_start or p_end:
        spread_by = {
            day: float(value)
            for day, value in spread_by.items()
            if (not burn_start or day >= burn_start) and (not p_end or day <= p_end)
        }
    out["repo_rate_regime"] = {
        "status": "ok" if rates_by_date else "empty",
        "rates_by_date": rates_by_date,
        "spread_by_date": spread_by,
    }

    margin_levels = load_margin_from_sqlite(
        bound,
        codes=codes,
        start=burn_start or None,
        end=p_end or None,
    )
    level_by_code: dict[str, dict[str, float]] = {}
    change_by_code: dict[str, dict[str, float]] = {}
    for code, pairs in margin_levels.items():
        clipped = [
            (day, float(value))
            for day, value in pairs
            if (not burn_start or day >= burn_start) and (not p_end or day <= p_end)
        ]
        if not clipped:
            continue
        level_by_code[code] = {day: value for day, value in clipped}
        change: dict[str, float] = {}
        for index in range(1, len(clipped)):
            _day0, value0 = clipped[index - 1]
            day1, value1 = clipped[index]
            if value0 != 0:
                change[day1] = (value1 / value0) - 1.0
        change_by_code[code] = change
    out["flow_regime"] = {
        "status": "ok" if level_by_code else "empty",
        "margin_level_by_code": level_by_code,
        "margin_change_by_code": change_by_code,
    }

    short_pairs = load_short_ratio_series_from_sqlite(
        bound,
        section="0050",
        start=burn_start or None,
        end=p_end or None,
    )
    short_by = {
        day: float(value)
        for day, value in short_pairs
        if (not burn_start or day >= burn_start) and (not p_end or day <= p_end)
    }
    flow = dict(out.get("flow_regime") or {})
    flow["short_ratio_by_date"] = short_by
    if flow.get("status") == "empty" and short_by:
        flow["status"] = "ok"
    out["flow_regime"] = flow

    events = load_fins_events_from_sqlite(
        bound,
        codes=codes,
        start=burn_start or "2014-01-01",
        end=p_end or None,
    )
    compact: dict[str, list[dict[str, Any]]] = {}
    for code, event_rows in events.items():
        rows: list[dict[str, Any]] = []
        for event in event_rows:
            day = str(event.get("disc_date") or "")[:10]
            if not day:
                continue
            if p_end and day > p_end:
                continue
            rows.append(
                {
                    "disc_date": day,
                    "disc_time": event.get("disc_time"),
                    "eps": event.get("eps"),
                    "feps": event.get("feps"),
                    "prior_eps": event.get("prior_eps"),
                    "bps": event.get("bps"),
                    "roe": event.get("roe"),
                    "div_ann": event.get("div_ann"),
                    "np": event.get("np"),
                    "sales": event.get("sales"),
                    "ta": event.get("ta"),
                    "eq_ar": event.get("eq_ar"),
                    "prior_ta": event.get("prior_ta"),
                }
            )
        if rows:
            compact[code] = rows
    out["fund_regime"] = {"events_by_code": compact}

    rates = dict((out.get("repo_rate_regime") or {}).get("rates_by_date") or {})
    out["repo_rate_by_date"] = rates
    if isinstance(out.get("repo_rate_regime"), dict):
        out["repo_rate_regime"] = {
            **out["repo_rate_regime"],
            "rate_by_date": rates,
        }
    return out


def attach_nky_proxy(
    bars_json: dict[str, list[list[Any]]],
    period: Mapping[str, Any],
    view: PersonalResearchDataView,
) -> dict[str, Any]:
    bound = _require_view(view)
    nky = load_nky_vol_series_from_sqlite(
        bound,
        start=period.get("period_start"),
        end=period.get("period_end"),
    )
    closes_by = dict(nky.get("closes_by_date") or {})
    p_start = str(period.get("period_start") or "")[:10]
    p_end = str(period.get("period_end") or "")[:10]
    idx_pairs = [
        [day, float(price)]
        for day, price in sorted(closes_by.items())
        if (not p_start or day >= p_start) and (not p_end or day <= p_end)
    ]
    nky_meta: dict[str, Any] = {}
    if closes_by:
        all_pairs = sorted(closes_by.items())
        if p_start:
            burn = [item for item in all_pairs if item[0] < p_start][-80:]
            in_win = [
                item
                for item in all_pairs
                if item[0] >= p_start and (not p_end or item[0] <= p_end)
            ]
            idx_pairs = [[day, float(price)] for day, price in (burn + in_win)]
        if idx_pairs:
            bars_json["__NKY_PROXY__"] = idx_pairs
            nky_meta = {
                "index_proxy": {
                    "dataset": "indices_bars_daily_topix",
                    "label": "TOPIX",
                    "role": "nky_vol_proxy_compare_only",
                    "note": (
                        "TOPIX closes staged as __NKY_PROXY__ for beta and "
                        "realized-vol comparisons only. Nikkei 225 option "
                        "volatility remains the canonical volatility signal."
                    ),
                },
                "nky_vol_series": {
                    "rv_short_by_date": nky.get("rv_short_by_date") or {},
                    "rv_long_by_date": nky.get("rv_long_by_date") or {},
                    "rv_abs_by_date": nky.get("rv_abs_by_date") or {},
                    "rv_ratio_by_date": nky.get("rv_ratio_by_date") or {},
                },
            }
    return nky_meta


def attach_opt225_regime(view: PersonalResearchDataView) -> dict[str, Any]:
    opt225_meta: dict[str, Any] = {}
    opt225 = load_opt225_regime_bundle_for_eval(_require_view(view))
    if not opt225:
        return opt225_meta
    source = {
        "dataset": str(opt225.get("dataset") or ""),
        "version": str(opt225.get("version") or ""),
    }
    expected_source = {
        "dataset": DATASET_ID,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
    }
    if source != expected_source:
        return {"opt225_error": "options_225 source identity mismatch"}
    compact: dict[str, Any] = {}
    for kind in (
        "basevol",
        "atm_iv",
        "spread",
        "spread_change",
        "skew",
        "cm_term",
        "cm_term_ratio",
        "basevol_delta",
    ):
        series = dict(opt225.get(kind) or {})
        if not series:
            continue
        compact[kind] = {
            "rv_abs_by_date": series.get("rv_abs_by_date") or {},
            "rv_short_by_date": series.get("rv_short_by_date") or {},
            "rv_long_by_date": series.get("rv_long_by_date") or {},
            "rv_ratio_by_date": series.get("rv_ratio_by_date") or {},
        }
    compact["source"] = source
    return {
        "opt225_regime": compact,
        "base_vol_series": dict((compact.get("basevol") or {}).get("rv_abs_by_date") or {}),
        "atm_iv_series": dict((compact.get("atm_iv") or {}).get("rv_abs_by_date") or {}),
        "iv_base_spread": dict((compact.get("spread") or {}).get("rv_abs_by_date") or {}),
        "skew_series": dict((compact.get("skew") or {}).get("rv_abs_by_date") or {}),
        "cm_term_series": dict((compact.get("cm_term") or {}).get("rv_abs_by_date") or {}),
        "cm_term_ratio_series": dict(
            (compact.get("cm_term_ratio") or {}).get("rv_abs_by_date") or {}
        ),
        "basevol_delta_series": dict(
            (compact.get("basevol_delta") or {}).get("rv_abs_by_date") or {}
        ),
    }
