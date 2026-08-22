"""Eval registry contract — recording SoT is R2/D1, not wave markdown."""
from __future__ import annotations

from tests.research_eval_util import (
    _baskets,
    _eval_cell,
    _eval_complete_cell,
    _eval_complete_year_cells,
    _fund_flow,
    _fund_head,
    _head4_row,
    _theme_fund_row,
)
from research.eval_registry import (
    EVAL_REGISTRY_VERSION,
    EvalJobManifest,
    dumps_manifest,
    manifest_from_window_rows,
    r2_manifest_key,
)
from research.eval_summary import (
    CANDIDATE_KEEP_SIMPLE,
    proposal_blocked_by_summary,
    summarize_daily_path_cells,
    weakness_flags_from_summary,
)
from research.eval_windows import HONEST_3Y_WINDOWS
from research.daily_path_eval import stitch_net, summarize_path

def test_honest_windows_are_the_shared_catalog() -> None:
    ids = [w["window_id"] for w in HONEST_3Y_WINDOWS]
    assert ids == ["w2017_2019", "w2020_2022", "w2023_2025"]


def test_manifest_from_rows_is_queryable_shape() -> None:
    rows = [
        _eval_cell(
            "overnight_level_cs_tilt",
            window="w2020_2022",
            daily_path_DD=-0.211,
            total_ret_net=-0.198,
            occupancy_frac=0.715,
            dd_duration=165,
            recovered=False,
            n_days=193,
            daily_path_complete=True,
        )
    ]
    man = manifest_from_window_rows(
        job_id="eval-test-1",
        protocol="daily_path_mtm_after_cost/v1",
        git_sha="deadbeef",
        rows=rows,
        one_way_cost=0.001,
    )
    assert isinstance(man, EvalJobManifest)
    body = man.to_dict()
    assert body["version"] == EVAL_REGISTRY_VERSION
    assert body["promote_as_main"] is False
    assert body["go"] is False
    assert body["mass"] == "NO-GO"
    assert body["research_candidate"] is False
    assert body["cells"][0]["logic_id"] == "overnight_level_cs_tilt"
    assert body["r2_manifest_key"] == r2_manifest_key("eval-test-1")
    dumped = dumps_manifest(man)
    assert '"job_id": "eval-test-1"' in dumped


def test_stitch_net_empty_is_honest() -> None:
    pack = stitch_net([], [])
    assert pack["n_equity_points"] == 0
    assert pack["daily_path_DD"] is None


def test_summarize_path_passes_gate_fields() -> None:
    row = summarize_path(
        {
            "status": "ok",
            "logic_id": "xs_rank_ls_sticky",
            "drawdown": {"max_dd": -0.14, "dd_duration_days": 10, "recovered": True},
            "daily_path_dd_gate": {"complete": True, "measured": True},
            "total_return_net": 0.01,
        }
    )
    assert row["daily_path_DD"] == -0.14
    assert row["daily_path_complete"] is True


def test_summarize_marks_path_broken_not_suspicious() -> None:

    cells = [
        _eval_complete_cell(
            "unwired_overlay",
            occupancy=0.87,
            total_ret_net=0.04,
            eval_path="cs_generic",
            path_fallback="path_broken",
            t_stat=1.2,
            sharpe_daily=0.3,
            daily_path_DD=-0.1,
        )
    ]
    summary = summarize_daily_path_cells(cells, job_id="eval-test-path")
    row = summary["logics"][0]
    assert "path_broken" in row["flags"]
    assert row["tag"] == "path_broken"
    assert row["explore_only"] is True
    assert row["go"] is False
    assert summary["n_path_broken"] == 1
    assert summary["path_broken_excluded_from_complete"] is True
    assert summary["n_complete_cells"] == 0


def test_path_broken_cell_is_not_complete() -> None:
    from research.eval_registry import (
        is_daily_path_complete_cell,
        is_path_broken_cell,
        manifest_from_window_rows,
    )

    broken = _eval_cell(
        "unwired_overlay",
        window="y2015_full",
        daily_path_complete=True,
        eval_path="cs_generic",
        path_fallback="path_broken",
        daily_path_DD=-0.1,
        total_ret_net=0.04,
        occupancy_frac=0.87,
        n_days=40,
        recovered=False,
    )
    assert is_path_broken_cell(broken) is True
    assert is_daily_path_complete_cell(broken) is False
    mdh = {**broken, "eval_path": "mdh_generic", "path_fallback": "mdh_empty_sidecar"}
    assert is_daily_path_complete_cell(mdh) is False
    ok = _eval_cell(
        "nky_vol_abs_level",
        window="y2015_full",
        daily_path_complete=True,
        eval_path="nky_vol:nky_vol_abs_level",
        daily_path_DD=-0.1,
        total_ret_net=0.01,
        occupancy_frac=0.5,
        n_days=40,
        recovered=True,
    )
    assert is_path_broken_cell(ok) is False
    assert is_daily_path_complete_cell(ok) is True
    man = manifest_from_window_rows(
        job_id="eval-test-complete",
        protocol="daily_path_mtm_after_cost/v1",
        git_sha="deadbeef",
        rows=[broken, ok],
        one_way_cost=0.001,
    )
    assert man.to_dict()["n_daily_path_complete"] == 1
    assert man.cells[0].daily_path_complete is False
    assert man.cells[1].daily_path_complete is True


def test_always_on_is_not_strong() -> None:

    cells = _eval_complete_year_cells(
        "xs_rank_ls_sticky",
        occupancy=0.90,
        total_ret_net=0.04,
        eval_path="xs_rank_sticky",
    )
    summary = summarize_daily_path_cells(cells, job_id="eval-test-always")
    row = summary["logics"][0]
    assert "always_on" in row["flags"]
    assert row["tag"] != "strong"
    assert summary["n_candidate_logics"] == 0
    assert summary["always_on_excluded_from_main"] is True


def test_always_on_gate_is_never_candidate() -> None:

    cells = _eval_complete_year_cells(
        "surprise_xs_afterclose",
        years=(2015, 2017, 2019),
        occupancy=1.0,
        eval_path="eventHeld",
    )
    summary = summarize_daily_path_cells(cells, job_id="eval-test-ao-gate")
    row = summary["logics"][0]
    assert "always_on" in row["flags"]
    assert row["candidate"] is False
    assert row["main_pool"] is False


def test_mechanical_baskets_are_four_valid_defs() -> None:
    from research.combo_basket_catalog import (
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
        assert d["deprecated"] is False
        assert d["go"] is False
        assert 2 <= len(d["members"]) <= 5
        assert validate_basket_members(d["members"]) == []
        assert CANDIDATE_POLICY["go"] is False
    primaries = [d for d in defs if d["primary"] or d.get("primary_candidate")]
    assert any(d["rule"] == "fundamentals_sleeve" for d in primaries)
    event4 = next(d for d in defs if d["rule"] == "event_family_only")
    head4 = next(d for d in defs if d["rule"] == "known_candidate_head")
    fam4 = next(d for d in defs if d["rule"] == "family_spread")
    assert event4["primary_candidate"] is False
    assert head4["primary_candidate"] is False
    assert fam4["primary_candidate"] is False
    cs = [d for d in defs if d["rule"] == "cs_family_only"]
    assert cs and cs[0]["primary"] is False
    rules = {d["rule"] for d in defs}
    assert "fundamentals_sleeve" in rules
    assert "margin_flow_sleeve" in rules
    assert "repo_rate_sleeve" in rules
    fund = next(d for d in defs if d["rule"] == "fundamentals_sleeve")
    assert "cs_eqar_high" not in fund["members"]
    assert "event_eqar_high_liq_high" in fund["members"]
    assert "event_eqar_rising_nkyvol" in fund["members"]
    assert "event_ta_up_liq_high" in fund["members"]
    assert "event_cheap_pb_liq_high" not in fund["members"]
    assert "cs_eqar_high_margin_down" not in fund["members"]
    assert fund["primary_candidate"] is True
    assert fund["go"] is False
    flow = next(d for d in defs if d["rule"] == "margin_flow_sleeve")
    repo = next(d for d in defs if d["rule"] == "repo_rate_sleeve")
    evf = next(d for d in defs if d["rule"] == "event_fund_cross")
    assert flow["primary_candidate"] is True
    assert evf["primary_candidate"] is True
    assert "cs_on_impulse" not in repo["members"]
    assert "event_repo3m_down_pead" in repo["members"]
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


def test_compare_headn_vs_liq_does_not_pass() -> None:
    from research.combo_basket_compare import compare_headn_vs_liq

    head = _fund_flow((3, 3), (3, 3), job_id="eval-cf-dp-baskets100-20260822a")
    liq = _fund_flow((4, 2), (4, 2), job_id="eval-cf-dp-baskets-liq100-20260822b")
    out = compare_headn_vs_liq(head, liq)
    assert out["version"] == "composition-compare/v1"
    assert out["not_a_pass"] is True
    assert out["go"] is False
    assert out["liq_print_is_not_stable"] is True
    assert "basket_theme_fund" in out["liq_majority_better"]


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


def test_summarize_emits_candidate_family_counts() -> None:

    cells = _eval_complete_year_cells(
        "event_skip_monday", occupancy=0.18, eval_path="eventHeld"
    )
    summary = summarize_daily_path_cells(cells, job_id="eval-test-fam")
    assert summary["n_candidate_logics"] == 1
    assert summary["candidate_family_counts"]["event_new"] == 1
    assert summary["go"] is False


def test_combo_basket_blend_is_equal_weight() -> None:
    from research.combo_basket import (
        blend_net_daily,
        blend_window_cells,
        occupancy_in_candidate_band,
    )
    from research.combo_basket_catalog import (
        DEFAULT_CANDIDATE_BASKET,
        validate_basket_members,
    )

    assert len(DEFAULT_CANDIDATE_BASKET) >= 2
    assert len(DEFAULT_CANDIDATE_BASKET) <= 5
    assert validate_basket_members(["a"]) == ["need_at_least_2_members"]
    blended = blend_net_daily([[0.0, 0.02, 0.00], [0.0, 0.00, 0.02]])
    assert abs(blended[1] - 0.01) < 1e-12
    assert abs(blended[2] - 0.01) < 1e-12
    assert occupancy_in_candidate_band(0.2) is True
    assert occupancy_in_candidate_band(0.9) is False
    assert occupancy_in_candidate_band(0.01) is False
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
    assert row["candidate"] is True
    assert row["n_pos_windows"] == 6
    assert row["go"] is False


def test_near_duplicate_is_not_candidate() -> None:
    from research.unique_logic.near_duplicate import NEAR_DUPLICATE_PARK

    lid = sorted(NEAR_DUPLICATE_PARK)[0]
    cells = [_eval_complete_cell(lid, occupancy=0.20, eval_path="eventHeld")]
    summary = summarize_daily_path_cells(cells, job_id="eval-test-dup")
    row = summary["logics"][0]
    assert "near_duplicate" in row["flags"]
    assert row["candidate"] is False
    assert row["main_pool"] is False


def test_economic_themes_exist_in_catalog() -> None:
    from research.unique_logic.constants import ECONOMIC_THEME_IDS
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC

    py = {s["logic_id"] for s in NEW_COMBO_LOGIC}
    assert len(ECONOMIC_THEME_IDS["surprise_funding"]) >= 4
    assert len(ECONOMIC_THEME_IDS["margin_price_disagree"]) >= 4
    assert len(ECONOMIC_THEME_IDS["repo_cs"]) >= 4
    assert len(ECONOMIC_THEME_IDS["vol_conditional"]) >= 4
    assert len(ECONOMIC_THEME_IDS["fundamentals"]) >= 6
    assert len(ECONOMIC_THEME_IDS["fund_leverage_cross"]) >= 5
    assert len(ECONOMIC_THEME_IDS["fund_flow_liq"]) >= 8
    assert len(ECONOMIC_THEME_IDS["margin_surprise"]) >= 5
    assert len(ECONOMIC_THEME_IDS["repo_event"]) >= 4
    assert len(ECONOMIC_THEME_IDS["vol_fund_cross"]) >= 4
    for theme, ids in ECONOMIC_THEME_IDS.items():
        for lid in ids:
            assert lid in py, f"{lid} missing from combo specs ({theme})"
            spec = next(s for s in NEW_COMBO_LOGIC if s["logic_id"] == lid)
            assert spec.get("near_duplicate") is False


def test_sparse_gate_combo_parks_at_generation() -> None:
    from research.unique_logic.constants import sparse_15name_reason
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC

    assert (
        sparse_15name_reason(
            gates=("fy_results", "overnight_easing"),
        )
        == "may_plus_easing"
    )
    assert (
        sparse_15name_reason(cs_gate="friday_curve_steep") == "friday_plus_steep"
    )
    assert sparse_15name_reason(gates=("skip_tuesday",)) is None
    fresh = [
        s
        for s in NEW_COMBO_LOGIC
        if s["logic_id"]
        in {
            "cs_eqar_high_easy",
            "surprise_xs_tight_fade",
            "cs_on_impulse",
        }
    ]
    assert len(fresh) == 3
    for s in fresh:
        assert s.get("data_requirement_unmet") is False
        assert s.get("main_pool") is True
        assert s.get("sparse_15name_reason") is None
        assert s.get("near_duplicate") is False
    for lid in (
        "event_eqar_high_pead",
        "event_crowd_on_impulse",
        "surprise_xs_repo3m_down",
        "cs_eqar_high_easy",
    ):
        row = next(s for s in NEW_COMBO_LOGIC if s["logic_id"] == lid)
        assert row.get("near_duplicate") is False
        assert row.get("data_requirement_unmet") is False
        assert row.get("main_pool") is True
        assert row.get("always_on_cs_sticky") is False
    for lid in (
        "cs_eqar_high",
        "cs_eqar_low_fade",
        "cs_ta_up",
        "cs_cheap_pb",
        "cs_np_positive",
    ):
        row = next(s for s in NEW_COMBO_LOGIC if s["logic_id"] == lid)
        assert row.get("main_pool") is False
        assert row.get("always_on_cs_sticky") is True
    from research.unique_logic.constants import is_ungated_name_level_cs

    assert is_ungated_name_level_cs(kind="cs", cs_gate="eq_ar_high") is True
    assert is_ungated_name_level_cs(kind="cs", cs_gate="eq_ar_high_easy") is False
    assert is_ungated_name_level_cs(
        kind="cs", cs_gate="eq_ar_high_margin_down", logic_id="cs_eqar_high_margin_down"
    ) is False
    by = {s["logic_id"]: s for s in NEW_COMBO_LOGIC}
    assert by["cs_eqar_high"]["always_on_cs_sticky"] is True
    assert by["cs_eqar_high"]["main_pool"] is False
    assert by["cs_eqar_high_margin_down"]["always_on_cs_sticky"] is False
    assert by["cs_eqar_high_margin_down"]["main_pool"] is True
    cells = [_eval_complete_cell("cs_eqar_high", occupancy=0.20, eval_path="gated_cs")]
    summary = summarize_daily_path_cells(cells, job_id="eval-test-cs-sticky")
    assert "always_on_cs_sticky" in summary["logics"][0]["flags"]
    cheap_and = next(
        s for s in NEW_COMBO_LOGIC if s["logic_id"] == "event_cheap_iv_cheap_pb"
    )
    assert cheap_and.get("data_requirement_unmet") is True
    assert cheap_and.get("main_pool") is False


def test_isolate_limit_logic_is_not_candidate() -> None:
    from research.unique_logic.constants import WORKER_ISOLATE_LIMIT_IDS

    assert WORKER_ISOLATE_LIMIT_IDS == frozenset()
    cells = [
        _eval_complete_cell(
            "cs_eqar_high_on_impulse", occupancy=0.20, eval_path="gated_cs"
        )
    ]
    summary = summarize_daily_path_cells(cells, job_id="eval-test-isolate")
    row = summary["logics"][0]
    assert "worker_isolate_limit" not in row["flags"]


def test_sparse_15name_is_data_requirement_unmet() -> None:
    from research.unique_logic.constants import SPARSE_ON_15NAME_SHARD

    assert SPARSE_ON_15NAME_SHARD == frozenset(
        {
            "event_may_easing",
            "flow_disagree_tue_thu",
            "event_midmonth_steep",
            "cs_steep_friday",
            "flow_disagree_skip_friday",
        }
    )
    for lid in sorted(SPARSE_ON_15NAME_SHARD):
        cells = [
            _eval_complete_cell(
                lid, occupancy=0.03, total_ret_net=0.0, eval_path="eventHeld"
            )
        ]
        summary = summarize_daily_path_cells(cells, job_id="eval-test-sparse")
        row = summary["logics"][0]
        assert "near_empty" in row["flags"]
        assert "data_requirement_unmet" in row["flags"]
        assert row["candidate"] is False
        assert row["main_pool"] is False


def test_near_empty_and_term_ratio_are_not_candidates() -> None:

    cells = _eval_complete_year_cells(
        "opt225_atm_iv_term_ratio",
        occupancy=0.0,
        total_ret_net=0.0,
        eval_path="opt225:term_ratio",
    )
    summary = summarize_daily_path_cells(cells, job_id="eval-test-empty")
    row = summary["logics"][0]
    assert "near_empty" in row["flags"]
    assert "data_requirement_unmet" in row["flags"]
    assert row["candidate"] is False
    assert row["main_pool"] is False
    assert summary["n_candidate_logics"] == 0
    assert summary["near_empty_excluded_from_candidate"] is True
    assert summary["strong_t_floor"] is None
    assert summary["simple_strategies_kept_for_combinations"] is True


def test_modest_t_gated_thesis_stays_candidate() -> None:

    cells = _eval_complete_year_cells(
        "event_skip_monday",
        occupancy=0.18,
        t_stat=0.4,
        sharpe_daily=0.05,
        eval_path="eventHeld",
    )
    summary = summarize_daily_path_cells(cells, job_id="eval-test-modest")
    row = summary["logics"][0]
    assert row["candidate"] is True
    assert row["main_pool"] is True
    assert row["go"] is False
    assert row["promote_as_main"] is False
    assert summary["n_candidate_logics"] == 1
    assert summary["strong_t_floor"] is None
    assert "path_broken" not in row["flags"]
    assert "always_on" not in row["flags"]


def test_path_collapsed_is_not_candidate() -> None:
    from research.eval_registry import (
        is_daily_path_complete_cell,
        is_path_collapsed_cell,
    )

    cells = _eval_complete_year_cells(
        "event_skip_monday",
        occupancy=0.20,
        total_ret_net=0.02,
        eval_path="mdh_generic",
        signal_id="c21_lite_fallback_mdh:event_calendar_gate",
        skip_reason="unique_unsupported_on_period_net",
        path_collapsed=True,
        t_stat=2.0,
    )
    assert is_path_collapsed_cell(cells[0]) is True
    assert is_daily_path_complete_cell(cells[0]) is False
    summary = summarize_daily_path_cells(cells, job_id="eval-test-collapsed")
    row = summary["logics"][0]
    assert "path_collapsed" in row["flags"]
    assert row["candidate"] is False
    assert row["main_pool"] is False
    assert row["tag"] == "path_collapsed"
    assert summary["n_candidate_logics"] == 0
    assert summary["n_path_collapsed"] == 1
    assert summary["path_collapsed_excluded_from_candidate"] is True


def test_mf_value_at_always_on_threshold_is_parked() -> None:
    from research.unique_logic.constants import ALWAYS_ON_OCCUPANCY_WARN

    cells = _eval_complete_year_cells(
        "mf_value_mom_rate",
        occupancy=ALWAYS_ON_OCCUPANCY_WARN,
        eval_path="mf_unique",
    )
    summary = summarize_daily_path_cells(cells, job_id="eval-test-mf-park")
    row = summary["logics"][0]
    assert "always_on" in row["flags"]
    assert row["candidate"] is False
    assert row["main_pool"] is False


def test_path_broken_is_not_candidate() -> None:

    cells = [
        _eval_complete_cell(
            "unwired_overlay",
            occupancy=0.40,
            total_ret_net=0.02,
            eval_path="cs_generic",
            path_fallback="path_broken",
            t_stat=2.0,
        )
    ]
    summary = summarize_daily_path_cells(cells, job_id="eval-test-broken-cand")
    row = summary["logics"][0]
    assert row["candidate"] is False
    assert row["tag"] == "path_broken"


def test_proposal_schema_reads_summary_weakness_flags() -> None:
    summary = {
        "logics": [
            {
                "logic_id": "xs_rank_ls_sticky",
                "flags": ["always_on"],
                "tag": "suspicious",
            },
            {
                "logic_id": "unwired_overlay",
                "flags": ["path_broken"],
                "tag": "path_broken",
            },
        ]
    }
    flags = weakness_flags_from_summary(summary)
    assert "always_on" in flags["xs_rank_ls_sticky"]
    assert "path_broken" in flags["unwired_overlay"]
    assert "path_broken" in CANDIDATE_KEEP_SIMPLE
    assert "path_collapsed" in CANDIDATE_KEEP_SIMPLE
    assert "always_on" in CANDIDATE_KEEP_SIMPLE
    assert "near_empty" in CANDIDATE_KEEP_SIMPLE
    blocked = proposal_blocked_by_summary(
        {
            "logic_id": "clone",
            "why_different_from": ["unwired_overlay"],
            "signal_definition": "x",
        },
        summary,
    )
    assert any("path_broken" in r for r in blocked)
