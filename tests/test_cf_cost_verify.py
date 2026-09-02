"""daily_path cost verify: fail-closed missing ADV, ON vs OFF, ADV buckets."""
from __future__ import annotations

from research.cf_cost_verify import (
    HIGH_ADV_JPY,
    LOW_ADV_JPY,
    run_cost_on_off_compare,
)
from research.daily_path_eval import held_book_daily_mtm

DATES = ["2024-01-02", "2024-01-03", "2024-01-04"]
HELD = {"7203": {"2024-01-02": 1.0, "2024-01-03": 1.0}}
CLOSE = {"7203": {"2024-01-02": 100.0, "2024-01-03": 101.0, "2024-01-04": 102.0}}


def _mtm(*, one_way: float, adv):
    return held_book_daily_mtm(
        held_by_code_date=HELD,
        close_by=CLOSE,
        dates=DATES,
        hold_days=10,
        one_way_cost=one_way,
        logic_id="liq_unit",
        adv_by_code=adv,
    )


def test_missing_adv_skips_name_no_invent() -> None:
    missing = _mtm(one_way=0.001, adv=None)
    present = _mtm(one_way=0.001, adv={"7203": HIGH_ADV_JPY})
    assert missing["cost_adv_incomplete"] is True
    assert missing["n_active_days"] == 0
    assert all(abs(float(x)) < 1e-15 for x in missing["net_daily"])
    assert present["cost_adv_incomplete"] is False
    assert present["n_active_days"] > 0
    other_only = _mtm(one_way=0.001, adv={"9999": LOW_ADV_JPY})
    assert other_only["cost_adv_incomplete"] is True
    assert other_only["n_active_days"] == 0

    mixed_held = {
        "7203": {"2024-01-02": 1.0, "2024-01-03": 1.0},
        "9999": {"2024-01-02": 1.0, "2024-01-03": 1.0},
    }
    mixed_close = {
        **CLOSE,
        "9999": {"2024-01-02": 100.0, "2024-01-03": 110.0, "2024-01-04": 120.0},
    }
    mixed = held_book_daily_mtm(
        held_by_code_date=mixed_held,
        close_by=mixed_close,
        dates=DATES,
        hold_days=10,
        one_way_cost=0.001,
        logic_id="liq_unit",
        adv_by_code={"7203": HIGH_ADV_JPY},
    )
    only_high = present
    assert mixed["cost_adv_incomplete"] is True
    assert mixed["n_active_days"] == only_high["n_active_days"]
    assert mixed["net_daily"] == only_high["net_daily"]


def test_one_way_on_vs_off_changes_net_when_positions_exist() -> None:
    pack = run_cost_on_off_compare(logic_ids=["liq_unit"], dry_run=True)
    assert pack["on_off"]["occupied"] is True
    assert pack["on_off"]["must_differ"] is True
    assert pack["on_off"]["differs"] is True
    assert pack["short_book"]["differs"] is True
    assert pack["high_turnover"]["differs"] is True
    assert pack["missing_adv"]["skipped_no_invent"] is True
    assert pack["r2_key"] is None
    on = _mtm(one_way=0.001, adv={"7203": HIGH_ADV_JPY})
    off = _mtm(one_way=0.0, adv={"7203": HIGH_ADV_JPY})
    assert on["n_active_days"] > 0
    assert on["net_daily"] != off["net_daily"]
    assert on["net_daily"][1] < off["net_daily"][1]


def test_low_adv_has_larger_cost_drag_than_high_adv() -> None:
    pack = run_cost_on_off_compare(logic_ids=["liq_unit"], dry_run=True)
    assert pack["adv_bucket"]["high_adv"] == HIGH_ADV_JPY
    assert pack["adv_bucket"]["low_adv"] == LOW_ADV_JPY
    assert pack["adv_bucket"]["high_cheaper"] is True
    assert abs(pack["adv_bucket"]["cost_drag_low"]) > abs(
        pack["adv_bucket"]["cost_drag_high"]
    )
    high = _mtm(one_way=0.001, adv={"7203": HIGH_ADV_JPY})
    low = _mtm(one_way=0.001, adv={"7203": LOW_ADV_JPY})
    high_drag = high["gross_daily"][1] - high["net_daily"][1]
    low_drag = low["gross_daily"][1] - low["net_daily"][1]
    assert abs(low_drag) > abs(high_drag)
    assert low["net_daily"][1] < high["net_daily"][1]


def test_go_false_not_a_pass_no_git_scores() -> None:
    pack = run_cost_on_off_compare(logic_ids=["liq_unit"], dry_run=True)
    assert pack["go"] is False
    assert pack["not_a_pass"] is True
    assert pack["promote_as_main"] is False
    assert pack["dry_run"] is True
    assert pack["skipped_live_cf"] is True
    assert pack["written_git_scores"] is False
    assert pack["r2_key"] is None
    assert pack["missing_adv"]["skipped_no_invent"] is True


def test_remote_cost_verify_uses_worker_put(monkeypatch) -> None:
    seen: list[str] = []

    def _fake_put(bucket, key, body, **kwargs):
        assert kwargs.get("dry_run") is not True
        seen.append(key)
        return {"status": "put_ok"}

    pack = run_cost_on_off_compare(
        logic_ids=["liq_unit"],
        dry_run=False,
        job_id="eval-cf-cost-test",
        artifact_put=_fake_put,
    )
    assert pack["go"] is False
    assert pack["written"] is True
    assert pack["r2_key"] == "research/eval/job=eval-cf-cost-test/cost_verify.json"
    assert seen == ["research/eval/job=eval-cf-cost-test/cost_verify.json"]


def test_eval_tracks_cost_models_hold_why() -> None:
    from research.eval_tracks import NEXT_RESEARCH_QUEUE

    row = next(q for q in NEXT_RESEARCH_QUEUE if q["id"] == "cost_models_modulation_hold")
    assert row["why"] == (
        "live math stays in cost_models; daily_path uses ADV 3-bucket "
        "+ repo short-drag fail-closed missing ADV"
    )
    assert row["go"] is False
    assert row["not_a_pass"] is True


def test_liquidity_multipliers_are_behaviorally_ordered() -> None:
    from research.cost_models import LIQUIDITY_TX_MULT

    assert LIQUIDITY_TX_MULT["high"] == 1.0
    assert LIQUIDITY_TX_MULT["mid"] == 1.5
    assert LIQUIDITY_TX_MULT["low"] == 2.5
    assert (
        LIQUIDITY_TX_MULT["high"]
        < LIQUIDITY_TX_MULT["mid"]
        < LIQUIDITY_TX_MULT["low"]
    )
