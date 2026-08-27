"""Mechanical sleeves / reconstitution detect. Equal-weight. Does not GO."""
from __future__ import annotations

from tests.research_eval_util import (
    _baskets,
    _eval_complete_cell,
    _eval_complete_year_cells,
    _fund_flow,
    _fund_head,
    _head4_row,
    _theme_fund_row,
)
from research.eval_summary import summarize_daily_path_cells


def test_mechanical_baskets_are_valid_defs() -> None:
    from research.combo_basket_catalog import (
        HISTORICAL_BASKET_RULES,
        RETIRED_BASKET_RULES,
        mechanical_basket_defs,
        validate_basket_members,
    )
    from research.unique_logic.constants import CANDIDATE_POLICY

    defs = mechanical_basket_defs()
    assert len(defs) >= 7
    ids = [d["basket_id"] for d in defs]
    assert len(ids) == len(set(ids))
    rules = {d["rule"] for d in defs}
    assert "low_occupancy_band" not in rules
    assert "event_family_only" in rules
    assert "family_spread" in rules
    assert "known_candidate_head" in rules
    assert "low_occupancy_band" in RETIRED_BASKET_RULES
    assert "surprise_xs_only" in RETIRED_BASKET_RULES
    assert "two_member_easing" in RETIRED_BASKET_RULES
    assert "event_calendar_only" in RETIRED_BASKET_RULES
    assert "event_calendar_only" not in rules
    for d in defs:
        assert d["valid"] is True
        assert d["go"] is False
        hist = d["rule"] in HISTORICAL_BASKET_RULES
        assert d["historical"] is hist
        assert d["deprecated"] is hist
        if hist:
            assert d["primary"] is False
            assert d["primary_candidate"] is False
        assert 2 <= len(d["members"]) <= 5
        assert validate_basket_members(d["members"]) == []
        assert CANDIDATE_POLICY["go"] is False
    primaries = [d for d in defs if d["primary"] or d.get("primary_candidate")]
    assert any(d["rule"] == "fundamentals_sleeve" for d in primaries)
    assert "fundamentals_sleeve" in rules
    assert "margin_flow_sleeve" in rules
    assert "repo_rate_sleeve" in rules
    fund = next(d for d in defs if d["rule"] == "fundamentals_sleeve")
    assert "cs_eqar_high" not in fund["members"]
    assert "event_cheap_pb_liq_high" not in fund["members"]
    assert fund["primary_candidate"] is True
    assert fund["go"] is False
    flow = next(d for d in defs if d["rule"] == "margin_flow_sleeve")
    repo = next(d for d in defs if d["rule"] == "repo_rate_sleeve")
    inv = next(d for d in defs if d["rule"] == "invert_print_sleeve")
    evf = next(d for d in defs if d["rule"] == "event_fund_cross")
    assert flow["primary_candidate"] is True
    assert evf["primary_candidate"] is True
    assert inv["primary"] is False
    assert inv["primary_candidate"] is False
    assert "repo_3m_down" not in " ".join(inv["members"])
    assert "event_flatten_eps_down" not in evf["members"]
    assert "cs_eqar_high" not in evf["members"]
    assert "cs_on_impulse" not in repo["members"]
    assert repo["primary_candidate"] is False
    assert repo["primary"] is False
    from research.combo_basket_catalog import primary_mechanical_basket_defs

    prim = primary_mechanical_basket_defs()
    assert prim
    assert all(d.get("primary") or d.get("primary_candidate") for d in prim)
    assert all(d["rule"] != "cs_family_only" for d in prim)
    assert all(d["rule"] != "low_occupancy_band" for d in prim)
    assert all(d["rule"] != "surprise_xs_only" for d in prim)
    assert {d["rule"] for d in prim} >= {
        "fundamentals_sleeve",
        "margin_flow_sleeve",
        "event_fund_cross",
    }
    assert "event_family_only" not in {d["rule"] for d in prim}
    assert "known_candidate_head" not in {d["rule"] for d in prim}
    for d in defs:
        assert "nested_parents" in d
        assert isinstance(d["nested_parents"], list)
        assert d["nested_parent_count"] == len(d["nested_parents"])


def test_mechanical_baskets_report_nested_parents_without_reject() -> None:
    """theme_fund / event_fund nested 2-AND⊂3-AND is detected, not invalid."""
    from research.combo_basket_catalog import (
        mechanical_basket_defs,
        nested_parent_pairs,
        validate_basket_members,
    )

    defs = {d["rule"]: d for d in mechanical_basket_defs()}
    fund = defs["fundamentals_sleeve"]
    evf = defs["event_fund_cross"]
    pairs_fund = {(p["parent"], p["child"]) for p in fund["nested_parents"]}
    pairs_evf = {(p["parent"], p["child"]) for p in evf["nested_parents"]}
    known = ("event_ta_up_positive_eps", "event_ac_peps_taup")
    assert known in pairs_fund
    assert known in pairs_evf
    assert (
        "event_afterclose_positive_eps",
        "event_ac_peps_taup",
    ) in pairs_evf
    assert fund["valid"] is True
    assert evf["valid"] is True
    assert validate_basket_members(fund["members"]) == []
    assert validate_basket_members(evf["members"]) == []
    assert nested_parent_pairs(["event_ta_up_positive_eps"]) == []
    assert nested_parent_pairs([]) == []


def test_historical_baskets_are_deprecated_not_invalid() -> None:
    from research.combo_basket_catalog import (
        HISTORICAL_BASKET_RULES,
        mechanical_basket_defs,
        primary_mechanical_basket_defs,
    )

    defs = mechanical_basket_defs()
    hist = [d for d in defs if d["historical"]]
    live = [d for d in defs if not d["historical"]]
    assert {d["rule"] for d in hist} == set(HISTORICAL_BASKET_RULES)
    assert hist and all(d["deprecated"] is True for d in hist)
    assert all(d["valid"] is True for d in hist)
    assert all(d["primary"] is False for d in hist)
    assert all(d["deprecated"] is False for d in live)
    prim_rules = {d["rule"] for d in primary_mechanical_basket_defs()}
    assert prim_rules.isdisjoint(HISTORICAL_BASKET_RULES)


def test_mechanical_basket_defs_cache_returns_copies() -> None:
    from research.combo_basket_catalog import mechanical_basket_defs
    from research.unique_logic.catalog import clear_catalog_caches

    a = mechanical_basket_defs()
    a[0]["members"].append("mutated")
    b = mechanical_basket_defs()
    assert "mutated" not in b[0]["members"]
    clear_catalog_caches()
    c = mechanical_basket_defs()
    fund = next(d for d in c if d["rule"] == "fundamentals_sleeve")
    assert fund["valid"] is True
    assert fund["nested_parent_count"] >= 1
    from research.combo_basket_catalog import primary_sleeve_member_ids

    ids = primary_sleeve_member_ids()
    assert "event_ta_up_positive_eps" in ids
    assert "cs_on_impulse" not in ids
    clear_catalog_caches()
    assert "event_ta_up_positive_eps" in primary_sleeve_member_ids()


def test_reconstitution_options_drop_nested_without_reject() -> None:
    from research.combo_basket_catalog import (
        reconstitution_options,
        reconstitution_plan,
        would_nest_in_sleeve,
    )

    fund = [
        "event_ta_up_positive_eps",
        "event_large_surprise_positive_eps",
        "event_ac_peps_taup",
        "event_eqar_high_positive_eps",
        "event_positive_eps_liq_high",
    ]
    opts = reconstitution_options(fund)
    assert opts["apply_reject"] is False
    assert opts["go"] is False
    drop_p = opts["drop_parents_keep_children"]
    drop_c = opts["drop_children_keep_parents"]
    assert "event_ta_up_positive_eps" not in drop_p["members"]
    assert "event_ac_peps_taup" in drop_p["members"]
    assert "event_ac_peps_taup" not in drop_c["members"]
    assert "event_ta_up_positive_eps" in drop_c["members"]
    assert drop_p["nested_parent_count"] == 0
    assert drop_c["nested_parent_count"] == 0
    assert would_nest_in_sleeve("event_ta_up_positive_eps", ["event_ac_peps_taup"])
    assert not would_nest_in_sleeve(
        "event_eqar_high_positive_eps",
        ["event_large_surprise_positive_eps"],
    )
    plan = {p["basket_id"]: p for p in reconstitution_plan()}
    assert plan["basket_theme_fund"]["needs_reconstitution"] is True
    assert plan["basket_event_fund"]["needs_reconstitution"] is True
    assert plan["basket_theme_flow"]["needs_reconstitution"] is False
    assert isinstance(plan["basket_theme_fund"]["nested_parent_count"], int)
    assert plan["basket_theme_fund"]["nested_parent_count"] >= 1
    assert isinstance(plan["basket_event_fund"]["nested_parent_count"], int)
    assert plan["basket_event_fund"]["nested_parent_count"] >= 1
    assert plan["basket_theme_fund"]["apply_reject"] is False
    assert plan["basket_head4"]["historical"] is True
    assert plan["basket_head4"]["needs_reconstitution"] is False
    from research.combo_basket import active_reconstitution_plan as reexport
    from research.combo_basket_catalog import active_reconstitution_plan

    active = {p["basket_id"] for p in active_reconstitution_plan()}
    assert {p["basket_id"] for p in reexport()} == active
    assert "basket_head4" not in active
    assert "basket_theme_fund" in active
    assert "basket_theme_flow" in active


def test_replacement_reject_reasons_block_soup_and_primary() -> None:
    from research.combo_basket_catalog import replacement_reject_reasons
    from research.unique_logic.constants import PRI_FLOW_GATES

    flow = [
        "event_positive_eps_uncrowded",
        "surprise_xs_ac_peps_taup",
        "surprise_xs_uncrowded_afterclose",
        "event_ta_up_uncrowded",
    ]
    rest = flow[:-1]
    assert "one_and_soup" in replacement_reject_reasons(
        "event_skip_announce_day", rest, theme_gates=PRI_FLOW_GATES
    )
    assert "one_and_soup" in replacement_reject_reasons(
        "event_curve_invert_fade", rest, theme_gates=PRI_FLOW_GATES
    )
    assert "already_primary_member" in replacement_reject_reasons(
        "event_large_surprise_positive_eps", rest, theme_gates=PRI_FLOW_GATES
    )
    assert "theme_gate_mismatch" in replacement_reject_reasons(
        "event_epsu_peps", rest, theme_gates=PRI_FLOW_GATES
    )
    assert replacement_reject_reasons("event_positive_eps_uncrowded", rest) == []


def test_blend_option_summary_is_descriptive_not_a_pass() -> None:
    from research.combo_basket import blend_option_summary

    cells = [
        _eval_complete_cell(
            "a",
            occupancy=0.2,
            dates=["d0", "d1", "d2"],
            net_daily=[0.0, 0.02, 0.0],
        ),
        _eval_complete_cell(
            "b",
            occupancy=0.3,
            dates=["d0", "d1", "d2"],
            net_daily=[0.0, 0.0, 0.02],
        ),
    ]
    for c in cells:
        c["window_id"] = "w0"
        c["daily_path_complete"] = True
    out = blend_option_summary(cells, basket_id="t", logic_ids=["a", "b"])
    assert out["n_windows"] == 1
    assert out["apply"] is False
    assert out["go"] is False
    assert out["not_a_pass"] is True
    assert "net_daily" not in out
    assert out["members"] == ["a", "b"]
    from research.combo_basket import filter_cells_honest_windows

    y2015 = dict(cells[0])
    y2015["window_id"] = "y2015_full"
    y2017 = dict(cells[0])
    y2017["window_id"] = "y2017_q4"
    kept = filter_cells_honest_windows([y2015, y2017])
    assert [c["window_id"] for c in kept] == ["y2017_q4"]
    honest = blend_option_summary(
        [y2015, y2017, dict(cells[1], window_id="y2017_q4")],
        basket_id="t",
        logic_ids=["a", "b"],
        honest=True,
    )
    assert honest["honest_windows"] is True
    assert honest["n_windows"] == 1
    from research.combo_basket import stitch_cells_honest_windows

    a17 = dict(cells[0])
    a17["window_id"] = "y2017_q4"
    a17["dates"] = ["d0", "d1"]
    a17["net_daily"] = [0.0, 0.01]
    a19 = dict(cells[0])
    a19["window_id"] = "y2019_full"
    a19["dates"] = ["e0", "e1"]
    a19["net_daily"] = [0.0, 0.02]
    a15 = dict(cells[0])
    a15["window_id"] = "y2015_full"
    st = stitch_cells_honest_windows([a17, a19, a15])
    assert {c["window_id"] for c in st} == {"w2017_2019"}
    cell = st[0]
    assert cell["net_daily"] == [0.0, 0.01, 0.0, 0.02]
    assert cell["missing_shards"] == []
    b17 = dict(cells[1])
    b17["window_id"] = "y2017_q4"
    b17["dates"] = ["d0", "d1"]
    b17["net_daily"] = [0.0, 0.00]
    b19 = dict(cells[1])
    b19["window_id"] = "y2019_full"
    b19["dates"] = ["e0", "e1"]
    b19["net_daily"] = [0.0, 0.02]
    stitched_sum = blend_option_summary(
        [a17, a19, a15, b17, b19],
        basket_id="t",
        logic_ids=["a", "b"],
        stitch=True,
    )
    assert stitched_sum["stitched"] is True
    assert stitched_sum["n_windows"] == 1
    assert stitched_sum["apply"] is False


def test_usable_sleeve_coverage_does_not_apply() -> None:
    from research.combo_basket_catalog import (
        BLEND_THINNER_KEEP_IDS,
        usable_sleeve_coverage,
    )

    out = usable_sleeve_coverage({"mid_n_explore": {}, "liq_large": {}})
    assert out["apply"] is False
    assert BLEND_THINNER_KEEP_IDS == frozenset(
        {"event_afterclose_uncrowded", "surprise_xs_peps_uncr"}
    )
    assert out["keep_sleeves_job"] == "eval-cf-dp-both-sleeves-20260824df"
    assert out["human_pending"] == [
        "basket_theme_fund",
        "basket_event_fund",
    ]
    assert out["go"] is False
    assert out["invert_primary"] is False
    by_id = {s["basket_id"]: s for s in out["sleeves"]}
    assert by_id["basket_theme_fund"]["needs_reconstitution"] is True
    assert by_id["basket_theme_fund"]["nested_parent_count"] >= 1
    assert by_id["basket_theme_invert"]["primary"] is False
    assert by_id["basket_theme_flow"]["needs_reconstitution"] is False
    assert out["replacement_candidates"] == []


def test_reconstitution_occupancy_preview_does_not_apply() -> None:
    from research.combo_basket_catalog import reconstitution_occupancy_preview

    out = reconstitution_occupancy_preview(
        {
            "mid_n_explore": {"event_ta_up_positive_eps": 0.4},
            "liq_large": {"event_ta_up_positive_eps": 0.41},
        }
    )
    assert out["apply"] is False
    assert out["go"] is False
    assert out["do_not_restitch_blend"] is True
    by_id = {s["basket_id"]: s for s in out["sleeves"]}
    fund = by_id["basket_theme_fund"]
    assert fund["apply"] is False
    assert fund["needs_reconstitution"] is True
    assert out["human_choice_required"] is True
    assert "basket_theme_fund" in out["human_pending"]
    assert fund["current"]["n"] == 5
    assert fund["drop_parents_keep_children"]["occupancy_mean_not_a_blend"] is True
    lo = next(
        r
        for r in fund["current"]["by_id"]
        if r["logic_id"] == "event_ta_up_positive_eps"
    )
    assert lo["lo"] == 0.4


def test_retired_inventory_cannot_supply_blend_replacements() -> None:
    from research.combo_basket_catalog import (
        BLEND_THINNER_KEEP_IDS,
        usable_sleeve_coverage,
    )

    occ = {
        "mid_n_explore": {lid: 0.45 for lid in BLEND_THINNER_KEEP_IDS},
        "liq_large": {lid: 0.46 for lid in BLEND_THINNER_KEEP_IDS},
    }
    out = usable_sleeve_coverage(occ)
    assert out["n_usable"] == 0
    assert out["replacement_candidates"] == []
    assert out["n_replacement_ok"] == 0
    assert out["blend_thinner_excluded"] == []
    assert out["apply"] is False
    assert out["go"] is False


def test_four_member_sleeve_requires_thicker_than_weakest() -> None:
    from research.combo_basket_catalog import (
        mechanical_basket_defs,
        usable_sleeve_coverage,
    )

    flow = next(
        d for d in mechanical_basket_defs() if d["basket_id"] == "basket_theme_flow"
    )
    members = [str(x) for x in flow["members"]]
    occ_ids = {m: 0.43 for m in members}
    occ_ids["surprise_xs_taup_uncr"] = 0.43
    occ_ids["event_afterclose_liq_high"] = 0.55
    occ = {"mid_n_explore": occ_ids, "liq_large": dict(occ_ids)}
    out = usable_sleeve_coverage(occ)
    flow_row = next(s for s in out["sleeves"] if s["basket_id"] == "basket_theme_flow")
    assert flow_row["weakest_lo"] == 0.43
    flow_cands = [
        c for c in out["replacement_candidates"] if c["basket_id"] == "basket_theme_flow"
    ]
    ids = {c["logic_id"] for c in flow_cands}
    assert "surprise_xs_taup_uncr" not in ids
    assert all(c["lo"] > 0.43 for c in flow_cands)


def test_meta_baskets_are_fund_line_and_not_a_pass() -> None:
    from research.combo_basket_catalog import (
        META_BASKETS,
        RETIRED_META_IDS,
        meta_basket_defs,
    )

    defs = meta_basket_defs()
    assert len(META_BASKETS) == 3
    assert {d["meta_id"] for d in defs} == {
        "meta_fund_flow",
        "meta_fund_event",
        "meta_fund_flow_event",
    }
    assert "meta_event4_flow" in RETIRED_META_IDS
    assert "meta_event4_fund" in RETIRED_META_IDS
    assert "meta_head_fund" in RETIRED_META_IDS
    for d in defs:
        assert d["valid"] is True
        assert d["go"] is False
        assert d["not_a_pass"] is True
        assert d["deprecated"] is False
        assert 2 <= len(d["sleeves"]) <= 3
        assert d["meta_id"] not in RETIRED_META_IDS


def test_compare_basket_summaries_classifies_flip() -> None:
    from research.combo_basket_compare import compare_basket_summaries

    a = _baskets(
        _theme_fund_row(4, 2, rule="fundamentals_sleeve", primary_candidate=True),
        _head4_row(5, 1, rule="known_candidate_head", primary_candidate=False),
    )
    b = _baskets(
        _theme_fund_row(4, 2, rule="fundamentals_sleeve", primary_candidate=True),
        _head4_row(2, 4, rule="known_candidate_head", primary_candidate=False),
    )
    out = compare_basket_summaries(a, b, label_a="univ50", label_b="univ80")
    assert out["go"] is False
    assert out["not_a_pass"] is True
    assert "basket_theme_fund" in out["stable_majority"]
    assert "basket_head4" in out["flipped"]
    assert "basket_theme_fund" in out["preferred_materials"]


def test_classify_sleeves_three_n_dilutes_at_100() -> None:
    from research.combo_basket_compare import classify_sleeves_three_n

    s50 = _fund_head((4, 2), (5, 1))
    s80 = _fund_head((4, 2), (2, 4))
    s100 = _fund_head((3, 3), (3, 3))
    out = classify_sleeves_three_n(s50, s80, s100)
    assert out["version"] == "sleeve-universe-stability/v2"
    assert out["univ100_is_not_stable"] is True
    assert out["go"] is False
    assert out["not_a_pass"] is True
    assert "basket_theme_fund" in out["stable_mid"]
    assert "basket_theme_fund" in out["dilutes_at_large"]
    assert "basket_head4" in out["unstable"]
    by = {r["basket_id"]: r for r in out["sleeves"]}
    assert by["basket_theme_fund"]["class"] != "stable"


def test_compare_mid_vs_liq_does_not_pass() -> None:
    from research.combo_basket_compare import compare_mid_vs_liq

    mid = _fund_flow((3, 3), (3, 3), job_id="eval-cf-dp-baskets80-sleeves-20260822a")
    liq = _fund_flow((5, 1), (5, 1), job_id="eval-cf-dp-baskets-liq100-sleeves-20260822a")
    out = compare_mid_vs_liq(mid, liq)
    assert out["version"] == "composition-compare/v2"
    assert out["not_a_pass"] is True
    assert out["go"] is False
    assert out["liq_print_is_not_stable"] is True
    assert "basket_theme_fund" in out["liq_majority_better"]
    assert out["liq_majority_better"]  # majority-better is still not a pass


def test_retired_catalog_result_is_not_a_candidate_family() -> None:

    cells = _eval_complete_year_cells(
        "event_skip_monday", occupancy=0.18, eval_path="eventHeld"
    )
    summary = summarize_daily_path_cells(cells, job_id="eval-test-fam")
    row = summary["logics"][0]
    assert summary["n_candidate_logics"] == 0
    assert summary["candidate_family_counts"] == {}
    assert row["candidate"] is False
    assert "worker_body_missing" in row["flags"]
    assert summary["go"] is False


def test_combo_basket_blend_is_equal_weight() -> None:
    from research.combo_basket import (
        blend_net_daily,
        blend_window_cells,
        occupancy_in_candidate_band,
    )
    from research.combo_basket_catalog import (
        HISTORICAL_HEAD4_MEMBERS,
        validate_basket_members,
    )

    assert 2 <= len(HISTORICAL_HEAD4_MEMBERS) <= 5
    assert validate_basket_members(["a"]) == ["need_at_least_2_members"]
    cal = validate_basket_members(
        ["event_skip_monday_uncrowded", "event_ta_up_uncrowded"]
    )
    assert "calendar_member" in cal
    blended = blend_net_daily([[0.0, 0.02, 0.00], [0.0, 0.00, 0.02]])
    assert abs(blended[1] - 0.01) < 1e-12
    assert abs(blended[2] - 0.01) < 1e-12
    assert occupancy_in_candidate_band(0.2) is True
    assert occupancy_in_candidate_band(0.9) is False
    assert occupancy_in_candidate_band(0.01) is False
    assert occupancy_in_candidate_band(0.10) is False
    assert occupancy_in_candidate_band(0.12) is False
    cells = [
        _eval_complete_cell(
            "a",
            occupancy=0.2,
            dates=["d0", "d1", "d2"],
            net_daily=[0.0, 0.02, 0.0],
        ),
        _eval_complete_cell(
            "b",
            occupancy=0.3,
            dates=["d0", "d1", "d2"],
            net_daily=[0.0, 0.0, 0.02],
        ),
    ]
    rows = blend_window_cells(cells, basket_id="basket_a_b", logic_ids=["a", "b"])
    assert len(rows) == 1
    assert rows[0]["go"] is False
    assert rows[0]["eval_path"] == "equal_weight_basket"
    assert rows[0]["daily_path_complete"] is True


def test_summarize_basket_trends_is_not_a_pass() -> None:
    from research.combo_basket import summarize_basket_trends

    cells = _eval_complete_year_cells(
        "basket_head4",
        occupancy=0.3,
        union_occupancy=0.7,
        t_stat=0.4,
        sharpe_daily=0.2,
        daily_path_DD=-0.05,
        members=["a", "b"],
    )
    summary = summarize_basket_trends(cells, job_id="eval-test-baskets")
    assert summary["n_baskets"] == 1
    assert summary["go"] is False
    assert summary["not_a_pass"] is True
    assert "low_occupancy_band" in summary["retired_rules"]
    row = summary["baskets"][0]
    assert row["candidate"] is False
    assert "historical" in row["flags"]
    assert row["n_pos_windows"] == 6
    assert row["go"] is False
    assert row["historical"] is True
    assert row["deprecated"] is True
    assert row["primary"] is False
