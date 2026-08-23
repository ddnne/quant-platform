"""Eval registry contract — recording SoT is R2/D1, not wave markdown."""
from __future__ import annotations

import pytest

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
    from research.eval_windows import honest_window_ids

    ids = [w["window_id"] for w in HONEST_3Y_WINDOWS]
    assert ids == ["w2017_2019", "w2020_2022", "w2023_2025"]
    got = honest_window_ids()
    assert set(ids) <= got
    assert "y2017_q4" in got
    assert "y2021_full" in got
    assert "y2025_q4" in got
    assert "y2015_full" not in got


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
    assert row["candidate"] is False


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


@pytest.mark.parametrize(
    "logic_id,occupancy,eval_path,years",
    [
        ("xs_rank_ls_sticky", 0.90, "xs_rank_sticky", None),
        ("surprise_xs_afterclose", 1.0, "eventHeld", (2015, 2017, 2019)),
        ("mf_value_mom_rate", 0.85, "mf_unique", None),
    ],
)
def test_always_on_occupancy_is_not_candidate(
    logic_id: str,
    occupancy: float,
    eval_path: str,
    years: tuple[int, ...] | None,
) -> None:
    kw: dict = {"occupancy": occupancy, "eval_path": eval_path}
    if years is not None:
        kw["years"] = years
    if logic_id == "xs_rank_ls_sticky":
        kw["total_ret_net"] = 0.04
    cells = _eval_complete_year_cells(logic_id, **kw)
    summary = summarize_daily_path_cells(cells, job_id=f"eval-test-ao-{logic_id}")
    row = summary["logics"][0]
    assert "always_on" in row["flags"]
    assert row["candidate"] is False
    assert summary["n_candidate_logics"] == 0


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


def test_usable_eval_snapshot_is_not_a_pass() -> None:
    from research.occupancy_audit import usable_eval_snapshot

    snap = usable_eval_snapshot({"mid_n_explore": {}, "liq_large": {}})
    assert snap["go"] is False
    assert snap["not_a_pass"] is True
    assert snap["inventory"]["version"] == "usable-inventory/v1"
    assert snap["usable_read"]["version"] == "usable-read/v3"
    assert snap["usable_read"]["do_not_silent_unpark"] is True
    assert snap["cost_risk"]["fake_split"] is False
    assert snap["cost_risk"]["not_a_pass"] is True
    assert snap["series"]["version"] == "usable-series/v1"
    assert snap["series"]["go"] is False


def test_write_usable_eval_snapshot_local_only(tmp_path) -> None:
    from research.occupancy_audit import write_usable_eval_snapshot

    out = write_usable_eval_snapshot(
        {"mid_n_explore": {}, "liq_large": {}},
        wave="test24em",
        root=tmp_path,
        put_r2=False,
    )
    assert out["go"] is False
    assert out["yaml_remains_sot"] is True
    assert out["puts"] == []
    assert (tmp_path / "eval-usable-inventory-test24em.json").is_file()
    assert (tmp_path / "eval-combo-jsonl-test24em.jsonl").is_file()


def test_write_eval_wave_pack_local_only(tmp_path) -> None:
    import json

    from research.occupancy_audit import write_eval_wave_pack

    out = write_eval_wave_pack(
        {"mid_n_explore": {"x": 0.4}, "liq_large": {"x": 0.41}},
        wave="test24ep",
        root=tmp_path,
        put_r2=False,
    )
    assert out["go"] is False
    assert out["not_a_pass"] is True
    assert out["catalog_and_plus_n_stopped"] is True
    assert out["reconstitution_apply"] is False
    assert out["n_unique22_parked"] >= 1
    assert out["occupancy_maps_job"] == "eval-occupancy-maps-test24ep"
    assert out["series_sleeve_job"] == "eval-series-sleeve-test24ep"
    assert (tmp_path / "eval-occupancy-maps-test24ep.json").is_file()
    assert (tmp_path / "eval-occupancy-drift-test24ep.json").is_file()
    assert (tmp_path / "eval-unique22-park-test24ep.json").is_file()
    assert (tmp_path / "eval-reconstitution-plan-test24ep.json").is_file()
    assert (tmp_path / "eval-series-sleeve-test24ep.json").is_file()
    recon = json.loads(
        (tmp_path / "eval-reconstitution-plan-test24ep.json").read_text(
            encoding="utf-8"
        )
    )
    fund = next(
        s for s in recon["sleeves"] if s["basket_id"] == "basket_theme_fund"
    )
    assert recon["apply"] is False
    assert isinstance(fund["nested_parent_count"], int)
    assert fund["nested_parent_count"] >= 1
    assert fund["nested_pairs"]
    preview = recon["occupancy_preview"]
    assert preview["apply"] is False
    assert preview["do_not_restitch_blend"] is True
    assert preview["human_choice_required"] is True
    assert "basket_theme_fund" in preview["human_pending"]
    assert preview["keep_sleeves_job"] == "eval-cf-dp-both-sleeves-20260824df"
    prev_fund = next(
        s for s in preview["sleeves"] if s["basket_id"] == "basket_theme_fund"
    )
    assert prev_fund["apply"] is False
    assert prev_fund["current"]["occupancy_mean_not_a_blend"] is True
    sleeve = json.loads(
        (tmp_path / "eval-series-sleeve-test24ep.json").read_text(encoding="utf-8")
    )
    assert sleeve["apply"] is False
    assert sleeve["invert_primary"] is False
    assert sleeve["go"] is False


def test_merge_occupancy_cell_dumps_later_mtime_wins(tmp_path) -> None:
    import json
    import time

    from research.occupancy_audit import merge_occupancy_cell_dumps

    old = [{"logic_id": "x", "occupancy": 0.2}]
    new = [{"logic_id": "x", "occupancy": 0.5}]
    older = tmp_path / "eval-occupancy-audit-z-mid_n_explore_cells.json"
    newer = tmp_path / "eval-occupancy-audit-a-mid_n_explore_cells.json"
    older.write_text(json.dumps(old), encoding="utf-8")
    time.sleep(0.05)
    newer.write_text(json.dumps(new), encoding="utf-8")
    (tmp_path / "eval-occupancy-audit-a-liq_large_cells.json").write_text(
        json.dumps(new), encoding="utf-8"
    )
    out = merge_occupancy_cell_dumps(tmp_path)
    assert out["mid_n_explore"]["x"] == 0.5
    assert out["liq_large"]["x"] == 0.5


def test_load_ops_occupancy_prefers_maps_over_cells(tmp_path) -> None:
    import json

    from research.occupancy_audit import load_ops_occupancy, write_eval_wave_pack

    cells = [{"logic_id": "old", "occupancy": 0.2}]
    (tmp_path / "eval-occupancy-audit-x-mid_n_explore_cells.json").write_text(
        json.dumps(cells), encoding="utf-8"
    )
    (tmp_path / "eval-occupancy-audit-x-liq_large_cells.json").write_text(
        json.dumps(cells), encoding="utf-8"
    )
    write_eval_wave_pack(
        {"mid_n_explore": {"new": 0.3}, "liq_large": {"new": 0.31}},
        wave="testmaps",
        root=tmp_path,
        put_r2=False,
    )
    occ = load_ops_occupancy(tmp_path)
    assert occ["mid_n_explore"]["new"] == 0.3
    assert "old" not in occ["mid_n_explore"]


def test_load_ops_occupancy_overlays_newer_cells(tmp_path) -> None:
    import json
    import time

    from research.occupancy_audit import load_ops_occupancy, write_eval_wave_pack

    write_eval_wave_pack(
        {"mid_n_explore": {"old": 0.2}, "liq_large": {"old": 0.21}},
        wave="testold",
        root=tmp_path,
        put_r2=False,
    )
    time.sleep(0.05)
    newer = [{"logic_id": "fresh", "occupancy": 0.4}]
    (tmp_path / "eval-occupancy-audit-z-mid_n_explore_cells.json").write_text(
        json.dumps(newer), encoding="utf-8"
    )
    (tmp_path / "eval-occupancy-audit-z-liq_large_cells.json").write_text(
        json.dumps(newer), encoding="utf-8"
    )
    occ = load_ops_occupancy(tmp_path)
    assert occ["mid_n_explore"]["old"] == 0.2
    assert occ["mid_n_explore"]["fresh"] == 0.4
    assert occ["liq_large"]["old"] == 0.21
    assert occ["liq_large"]["fresh"] == 0.4


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


def test_blend_thinner_keep_ids_are_excluded() -> None:
    from research.combo_basket_catalog import (
        BLEND_THINNER_KEEP_IDS,
        usable_sleeve_coverage,
    )

    occ = {
        "mid_n_explore": {lid: 0.45 for lid in BLEND_THINNER_KEEP_IDS},
        "liq_large": {lid: 0.46 for lid in BLEND_THINNER_KEEP_IDS},
    }
    out = usable_sleeve_coverage(occ)
    cand = {c["logic_id"] for c in out["replacement_candidates"]}
    assert cand.isdisjoint(BLEND_THINNER_KEEP_IDS)
    excluded = {x["logic_id"] for x in out["blend_thinner_excluded"]}
    assert BLEND_THINNER_KEEP_IDS <= excluded
    assert all(x["apply"] is False for x in out["blend_thinner_excluded"])
    assert len(out["blend_thinner_excluded"]) == len(BLEND_THINNER_KEEP_IDS)


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


def test_cost_defaults_are_shared() -> None:
    from research.cost_defaults import DEFAULT_ONE_WAY_COST, DEFAULT_ONE_WAY_COST_BP
    from research.cost_models import DEFAULT_ONE_WAY_COST as cost_cost
    from research.holding_metrics import DEFAULT_ONE_WAY_COST as hold_cost
    from research.paper_candidate_adapt import DEFAULT_ONE_WAY_COST as paper_cost
    from research.robustness_gate import DEFAULT_ONE_WAY_COST as gate_cost

    assert DEFAULT_ONE_WAY_COST_BP == 10.0
    assert DEFAULT_ONE_WAY_COST == 0.001
    assert cost_cost == hold_cost == paper_cost == gate_cost == DEFAULT_ONE_WAY_COST


def test_run_eval_wave_local_stub_never_writes(tmp_path) -> None:
    from research.occupancy_audit import run_eval_wave

    def _invoke(**_kwargs):
        return {
            "ok": False,
            "error": "llm_failed",
            "n_adoptable": 0,
            "proposals": [],
            "reviews": [],
        }

    out = run_eval_wave(
        {"mid_n_explore": {"x": 0.4}, "liq_large": {"x": 0.4}},
        wave="test24eq",
        root=tmp_path,
        put_r2=False,
        propose=True,
        invoke=_invoke,
    )
    assert out["go"] is False
    assert out["catalog_written"] is False
    assert out["auto_inject"] is False
    assert out["propose"]["written"] is False
    assert out["propose"]["llm_failed_not_soup"] is True
    assert (tmp_path / "eval-occupancy-maps-test24eq.json").is_file()
    assert (tmp_path / "eval-cf-propose-test24eq.json").is_file()


def test_merge_daily_path_cells_for_ids_later_file_wins(tmp_path) -> None:
    import json

    from research.occupancy_audit import merge_daily_path_cells_for_ids

    a = {
        "logic_id": "x",
        "window_id": "w0",
        "net_daily": [0.0, 0.01],
        "occupancy": 0.2,
    }
    b = dict(a)
    b["occupancy"] = 0.4
    (tmp_path / "eval-a-mid_n_explore_cells.json").write_text(
        json.dumps([a]), encoding="utf-8"
    )
    (tmp_path / "eval-b-mid_n_explore_cells.json").write_text(
        json.dumps([b]), encoding="utf-8"
    )
    (tmp_path / "eval-c-liq_large_cells.json").write_text(
        json.dumps([a]), encoding="utf-8"
    )
    out = merge_daily_path_cells_for_ids(tmp_path, ["x"])
    assert len(out["mid_n_explore"]) == 1
    assert out["mid_n_explore"][0]["occupancy"] == 0.4
    assert len(out["liq_large"]) == 1


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
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC, spec_by_id

    py = {s["logic_id"] for s in NEW_COMBO_LOGIC}
    assert set(ECONOMIC_THEME_IDS)
    assert all(ids for ids in ECONOMIC_THEME_IDS.values())
    for theme, ids in ECONOMIC_THEME_IDS.items():
        for lid in ids:
            assert lid in py, f"{lid} missing from combo specs ({theme})"
            spec = spec_by_id(lid)
            assert spec is not None
            assert spec.get("near_duplicate") is False


def test_sparse_gate_combo_parks_at_generation() -> None:
    from research.unique_logic.constants import sparse_15name_reason
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC, spec_by_id

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
        row = spec_by_id(lid)
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
        row = spec_by_id(lid)
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
