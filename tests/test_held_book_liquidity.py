"""ADV liquidity multiplier on held_book_daily_mtm (fail-closed missing ADV)."""

from __future__ import annotations

from research.daily_path_eval import held_book_daily_mtm


DATES = ["2024-01-02", "2024-01-03", "2024-01-04"]
HELD = {"7203": {"2024-01-02": -1.0, "2024-01-03": -1.0}}
CLOSE = {"7203": {"2024-01-02": 100.0, "2024-01-03": 101.0, "2024-01-04": 102.0}}
REPO = {"2024-01-02": 1.0, "2024-01-03": 1.0}


def _pack(adv):
    return held_book_daily_mtm(
        held_by_code_date=HELD,
        close_by=CLOSE,
        dates=DATES,
        hold_days=10,
        one_way_cost=0.001,
        logic_id="liq_unit",
        repo_by_date=REPO,
        adv_by_code=adv,
    )


def _net(adv):
    return _pack(adv)["net_daily"][1]


def test_liq_mult_scales_with_adv_bucket() -> None:
    missing = _pack(None)
    high = _net({"7203": 2e9})
    mid = _net({"7203": 2e8})
    low = _net({"7203": 1e7})
    assert missing["cost_adv_incomplete"] is True
    assert missing["n_active_days"] == 0
    assert abs(missing["net_daily"][1]) < 1e-15
    assert mid < high
    assert low < mid


def test_missing_code_adv_does_not_invent() -> None:
    other_only = _pack({"9999": 1e7})
    none = _pack(None)
    assert other_only["cost_adv_incomplete"] is True
    assert none["cost_adv_incomplete"] is True
    assert abs(other_only["net_daily"][1]) < 1e-15
    assert abs(none["net_daily"][1]) < 1e-15


def test_dispatch_contextvar_passes_adv_to_held_book() -> None:
    from research.daily_path_eval import (
        held_book_daily_mtm,
        reset_held_book_adv,
        set_held_book_adv,
    )

    token = set_held_book_adv({"7203": 1e7})
    try:
        via_ctx = held_book_daily_mtm(
            held_by_code_date=HELD,
            close_by=CLOSE,
            dates=DATES,
            hold_days=10,
            one_way_cost=0.001,
            logic_id="liq_unit",
            repo_by_date=REPO,
        )["net_daily"][1]
    finally:
        reset_held_book_adv(token)
    explicit = _net({"7203": 1e7})
    missing = _net(None)
    assert abs(via_ctx - explicit) < 1e-12
    assert via_ctx < missing
