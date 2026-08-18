"""W92 / w0818b — options_225 BaseVol + ATM IV daily series (synthetic chains)."""

from __future__ import annotations

import pytest

from research.options_225_vol_series import (
    DATASET_ID,
    GAP_POLICY,
    IV_FIELDS_AVAILABLE_FROM,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    OPTIONS_225_VOL_SERIES_VERSION,
    OPTIONS_225_VOL_SERIES_WAVE,
    PHASE7,
    READY_DECLARED,
    build_daily_atm_iv_series,
    build_daily_basevol_series,
    build_series_bundle_from_rows,
    build_spread_series,
    calendar_gap_dates,
    normalize_options_225_row,
    pearson_corr,
    summarize_vol_series,
)


def _contract(
    *,
    date: str,
    code: str,
    strike: float,
    pc: str,
    cm: str,
    ltd: str,
    sqd: str,
    under: float,
    base_vol: float | str,
    iv: float | str,
    vo: float = 10.0,
    oi: float = 100.0,
    em: str = "002",
) -> dict:
    return {
        "Date": date,
        "Code": code,
        "Strike": strike,
        "PCDiv": pc,
        "CM": cm,
        "LTD": ltd,
        "SQD": sqd,
        "UnderPx": under,
        "BaseVol": base_vol,
        "IV": iv,
        "Vo": vo,
        "OI": oi,
        "EmMrgnTrgDiv": em,
        "O": 1.0,
        "H": 1.0,
        "L": 1.0,
        "C": 1.0,
    }


def _mini_chain_day(
    date: str,
    *,
    under: float = 40000.0,
    base_vol: float = 20.0,
    front_cm: str = "2024-02",
    ltd: str = "2024-02-08",
    sqd: str = "2024-02-09",
    atm_strike: float = 40000.0,
    put_iv: float = 20.5,
    call_iv: float = 19.5,
    extra_strike: float = 40500.0,
) -> list[dict]:
    """Synthetic settlement chain: ATM put/call + one OTM each."""
    rows = [
        _contract(
            date=date,
            code="P_ATM",
            strike=atm_strike,
            pc="1",
            cm=front_cm,
            ltd=ltd,
            sqd=sqd,
            under=under,
            base_vol=base_vol,
            iv=put_iv,
            vo=50.0,
        ),
        _contract(
            date=date,
            code="C_ATM",
            strike=atm_strike,
            pc="2",
            cm=front_cm,
            ltd=ltd,
            sqd=sqd,
            under=under,
            base_vol=base_vol,
            iv=call_iv,
            vo=80.0,
        ),
        _contract(
            date=date,
            code="P_OTM",
            strike=extra_strike,
            pc="1",
            cm=front_cm,
            ltd=ltd,
            sqd=sqd,
            under=under,
            base_vol=base_vol,
            iv=22.0,
            vo=1.0,
        ),
        _contract(
            date=date,
            code="C_OTM",
            strike=extra_strike,
            pc="2",
            cm=front_cm,
            ltd=ltd,
            sqd=sqd,
            under=under,
            base_vol=base_vol,
            iv=18.0,
            vo=1.0,
        ),
        # farther month should not win front-CM selection
        _contract(
            date=date,
            code="C_BACK",
            strike=atm_strike,
            pc="2",
            cm="2024-03",
            ltd="2024-03-07",
            sqd="2024-03-08",
            under=under,
            base_vol=base_vol,
            iv=25.0,
            vo=5.0,
        ),
    ]
    return rows


def test_wave_pins_and_freezes():
    assert OPTIONS_225_VOL_SERIES_VERSION.startswith(
        "research-options-225-vol-series/v1"
    )
    assert "W93" in OPTIONS_225_VOL_SERIES_WAVE or "W92" in OPTIONS_225_VOL_SERIES_WAVE
    assert DATASET_ID == "derivatives_bars_daily_options_225"
    assert GAP_POLICY == "disclose_only_no_ffill_no_invent"
    assert IV_FIELDS_AVAILABLE_FROM == "2016-07-19"
    assert MASS_RESEARCH == "NO-GO"
    assert PHASE7 == "OFF"
    assert READY_DECLARED is False
    assert OPERATIONAL_GO is False


def test_normalize_blank_iv_fields():
    row = normalize_options_225_row(
        {
            "Date": "2015-05-01",
            "Code": "x",
            "Strike": 20000,
            "PCDiv": "1",
            "CM": "2015-05",
            "BaseVol": "",
            "IV": "",
            "UnderPx": "",
            "LTD": "",
            "SQD": "",
        }
    )
    assert row is not None
    assert row["base_vol"] is None and row["iv"] is None and row["under_px"] is None


def test_basevol_unique_per_day_no_ffill_gap():
    rows = (
        _mini_chain_day("2024-01-04", base_vol=18.0, put_iv=18.2, call_iv=17.8)
        + _mini_chain_day("2024-01-05", base_vol=19.0, put_iv=19.1, call_iv=18.9)
        # 2024-01-06 missing entirely → gap, not invented
        + _mini_chain_day("2024-01-09", base_vol=21.0, put_iv=21.2, call_iv=20.8)
    )
    # pre-IV era day with blank BaseVol must be omitted
    rows += [
        _contract(
            date="2015-05-01",
            code="old",
            strike=20000,
            pc="1",
            cm="2015-05",
            ltd="",
            sqd="",
            under=0,
            base_vol="",
            iv="",
        )
    ]
    # fix under on blank row — use empty under via normalize; rebuild without bad under 0
    rows[-1]["UnderPx"] = ""
    rows[-1]["LTD"] = ""
    rows[-1]["SQD"] = ""

    base = build_daily_basevol_series(rows)
    dates = [r["date"] for r in base]
    assert dates == ["2024-01-04", "2024-01-05", "2024-01-09"]
    assert base[0]["base_vol"] == 18.0
    assert base[0]["n_contracts"] == 5
    assert base[0]["ffill_applied"] is False
    assert all(r["gap_policy"] == GAP_POLICY for r in base)
    # no invented 2024-01-06 / 2015-05-01
    assert "2024-01-06" not in dates
    assert "2015-05-01" not in dates


def test_atm_iv_picks_front_cm_nearest_strike_avg_pc():
    rows = _mini_chain_day(
        "2024-01-10",
        under=40010.0,
        atm_strike=40000.0,
        put_iv=20.5,
        call_iv=19.5,
        base_vol=20.0,
    )
    atm = build_daily_atm_iv_series(rows)
    assert len(atm) == 1
    row = atm[0]
    assert row["date"] == "2024-01-10"
    assert row["cm"] == "2024-02"
    assert row["strike"] == 40000.0
    assert row["pc_used"] == "avg"
    assert row["atm_iv"] == pytest.approx(20.0)
    assert row["put_iv"] == 20.5
    assert row["call_iv"] == 19.5
    assert row["ffill_applied"] is False
    assert row["near_expiry_fallback"] is False
    assert int(row["dte"] or 0) >= 6


def test_atm_iv_rolls_near_expiry_front_cm():
    """W93: DTE<=5 front CM must lose to next month when available."""
    date = "2024-02-05"  # LTD 2024-02-08 → DTE=3 < min_dte=6
    rows = _mini_chain_day(
        date,
        under=40000.0,
        atm_strike=40000.0,
        put_iv=80.0,  # blown-up front IV
        call_iv=70.0,
        base_vol=25.0,
        front_cm="2024-02",
        ltd="2024-02-08",
        sqd="2024-02-09",
    )
    # next CM with calm IV (should win after min_dte roll)
    rows += [
        _contract(
            date=date,
            code="P_NEXT",
            strike=40000.0,
            pc="1",
            cm="2024-03",
            ltd="2024-03-07",
            sqd="2024-03-08",
            under=40000.0,
            base_vol=25.0,
            iv=25.2,
        ),
        _contract(
            date=date,
            code="C_NEXT",
            strike=40000.0,
            pc="2",
            cm="2024-03",
            ltd="2024-03-07",
            sqd="2024-03-08",
            under=40000.0,
            base_vol=25.0,
            iv=24.8,
        ),
    ]
    atm = build_daily_atm_iv_series(rows)
    assert len(atm) == 1
    assert atm[0]["cm"] == "2024-03"
    # mini_chain also seeds C_BACK@2024-03 IV=25.0; median(call)=24.9 → avg≈25.05
    assert atm[0]["atm_iv"] == pytest.approx(25.05)
    assert atm[0]["cm_pick_rule"] == "ltd_min_dte"
    assert atm[0]["near_expiry_fallback"] is False
    assert int(atm[0]["dte"] or 0) >= 6
    # blown-up front IV must NOT be selected
    assert atm[0]["atm_iv"] < 40.0


def test_atm_iv_call_only_when_put_missing():
    rows = [
        _contract(
            date="2024-01-11",
            code="C_ATM",
            strike=39000,
            pc="2",
            cm="2024-02",
            ltd="2024-02-08",
            sqd="2024-02-09",
            under=39005,
            base_vol=15.0,
            iv=15.25,
        ),
        # put at same strike but blank IV → ignored
        _contract(
            date="2024-01-11",
            code="P_ATM",
            strike=39000,
            pc="1",
            cm="2024-02",
            ltd="2024-02-08",
            sqd="2024-02-09",
            under=39005,
            base_vol=15.0,
            iv="",
        ),
    ]
    atm = build_daily_atm_iv_series(rows)
    assert len(atm) == 1
    assert atm[0]["pc_used"] == "2"
    assert atm[0]["atm_iv"] == pytest.approx(15.25)


def test_spread_inner_join_and_no_ffill():
    base = [
        {"date": "2024-01-04", "base_vol": 18.0},
        {"date": "2024-01-05", "base_vol": 19.0},
        {"date": "2024-01-08", "base_vol": 20.0},  # atm missing
    ]
    atm = [
        {"date": "2024-01-04", "atm_iv": 18.1, "strike": 100, "under_px": 100, "cm": "2024-02", "pc_used": "avg"},
        {"date": "2024-01-05", "atm_iv": 18.5, "strike": 100, "under_px": 100, "cm": "2024-02", "pc_used": "avg"},
        {"date": "2024-01-09", "atm_iv": 21.0, "strike": 100, "under_px": 100, "cm": "2024-02", "pc_used": "2"},
    ]
    spread = build_spread_series(base, atm)
    assert [r["date"] for r in spread] == ["2024-01-04", "2024-01-05"]
    assert spread[0]["spread"] == pytest.approx(0.1)
    assert spread[1]["spread"] == pytest.approx(-0.5)
    assert all(r["ffill_applied"] is False for r in spread)


def test_emergency_margin_deferred_to_settlement_rows():
    rows = _mini_chain_day("2024-01-12", base_vol=16.0, put_iv=16.2, call_iv=15.8)
    # duplicate chain with emergency flag and bogus BaseVol must be ignored
    emergency = []
    for r in rows:
        e = dict(r)
        e["EmMrgnTrgDiv"] = "001"
        e["BaseVol"] = 99.0
        e["IV"] = 99.0
        e["Code"] = e["Code"] + "_EM"
        emergency.append(e)
    base = build_daily_basevol_series(rows + emergency)
    atm = build_daily_atm_iv_series(rows + emergency)
    assert len(base) == 1 and base[0]["base_vol"] == 16.0
    assert atm[0]["atm_iv"] == pytest.approx(16.0)


def test_calendar_gaps_disclosed_not_filled():
    gaps = calendar_gap_dates(["2024-01-04", "2024-01-05", "2024-01-08"])
    assert "2024-01-06" in gaps and "2024-01-07" in gaps
    assert "2024-01-04" not in gaps


def test_corr_and_bundle_stats():
    rows = (
        _mini_chain_day("2024-01-04", base_vol=18.0, put_iv=18.2, call_iv=17.8)
        + _mini_chain_day("2024-01-05", base_vol=20.0, put_iv=20.4, call_iv=19.6)
        + _mini_chain_day("2024-01-08", base_vol=22.0, put_iv=22.5, call_iv=21.5)
    )
    bundle = build_series_bundle_from_rows(rows)
    assert bundle["mass_research"] == "NO-GO"
    assert bundle["ffill_applied"] is False
    stats = bundle["stats"]
    assert stats["n_base_vol_days"] == 3
    assert stats["n_atm_iv_days"] == 3
    assert stats["n_spread_days"] == 3
    assert stats["corr_basevol_atm_iv"] == pytest.approx(1.0)
    assert pearson_corr([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)
    # avg put/call equals base in this synth → near-zero spread
    assert stats["spread_abs_mean"] == pytest.approx(0.0)
    summary = summarize_vol_series(
        bundle["base_vol_series"], bundle["atm_iv_series"], bundle["spread_series"]
    )
    assert summary["gap_policy"] == GAP_POLICY
