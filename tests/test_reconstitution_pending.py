"""Human reconstitution pending. Apply stays False. Not GO."""
from __future__ import annotations


def test_reconstitution_apply_is_false() -> None:
    from research.combo_basket_catalog import (
        HUMAN_RECONSTITUTION_PENDING,
        KEEP_BOTH_SLEEVES_JOB,
        FLOW_FIFTH_BLEND_THINNER_JOB,
        reconstitution_occupancy_preview,
    )
    from research.eval_flags import RECONSTITUTION_APPLY
    from research.reconstitution_pending import pending_reconstitution_pack

    assert RECONSTITUTION_APPLY is False
    assert HUMAN_RECONSTITUTION_PENDING == (
        "basket_theme_fund",
        "basket_event_fund",
    )
    preview = reconstitution_occupancy_preview()
    assert preview["apply"] is False
    assert preview["go"] is False
    assert preview["do_not_restitch_blend"] is True
    assert preview["human_choice_required"] is True
    assert preview["human_pending"] == list(HUMAN_RECONSTITUTION_PENDING)
    pack = pending_reconstitution_pack()
    assert pack["preview_exists"] is True
    assert pack["apply"] is False
    assert pack["go"] is False
    assert pack["not_a_pass"] is True
    assert pack["do_not_auto_choose"] is True
    assert pack["human_only_drop_parents_vs_drop_children"] is True
    assert pack["do_not_restitch_blend"] is True
    assert pack["human_pending"] == [
        "basket_theme_fund",
        "basket_event_fund",
    ]
    assert pack["keep_sleeves_job"] == KEEP_BOTH_SLEEVES_JOB
    assert KEEP_BOTH_SLEEVES_JOB == "eval-cf-dp-both-sleeves-20260824df"
    assert pack["flow_fifth_blend_thinner_job"] == FLOW_FIFTH_BLEND_THINNER_JOB
    assert FLOW_FIFTH_BLEND_THINNER_JOB == "eval-flow-5th-blend-20260824ek"
    by_id = {s["basket_id"]: s for s in pack["sleeves"]}
    assert set(by_id) == {
        "basket_theme_fund",
        "basket_event_fund",
    }
    assert by_id["basket_theme_fund"]["apply"] is False
    assert by_id["basket_event_fund"]["apply"] is False
    assert RECONSTITUTION_APPLY is False
