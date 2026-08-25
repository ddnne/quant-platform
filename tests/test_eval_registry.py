"""Eval registry contract — recording SoT is R2/D1, not wave markdown."""
from __future__ import annotations

import pytest

from tests.research_eval_util import (
    _eval_cell,
    _eval_complete_cell,
    _eval_complete_year_cells,
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


def test_retired_gated_thesis_stays_out_of_candidate_pool() -> None:

    cells = _eval_complete_year_cells(
        "event_skip_monday",
        occupancy=0.18,
        t_stat=0.4,
        sharpe_daily=0.05,
        eval_path="eventHeld",
    )
    summary = summarize_daily_path_cells(cells, job_id="eval-test-modest")
    row = summary["logics"][0]
    assert row["candidate"] is False
    assert row["main_pool"] is False
    assert row["go"] is False
    assert row["promote_as_main"] is False
    assert summary["n_candidate_logics"] == 0
    assert summary["strong_t_floor"] is None
    assert "path_broken" not in row["flags"]
    assert "always_on" not in row["flags"]
    assert "worker_body_missing" in row["flags"]


def test_partial_windows_are_not_candidate() -> None:
    complete = _eval_complete_cell(
        "event_skip_monday",
        occupancy=0.20,
        total_ret_net=0.02,
        eval_path="eventHeld",
        t_stat=0.4,
        sharpe_daily=0.05,
    )
    incomplete = dict(complete)
    incomplete["window"] = "y2016_full"
    incomplete["daily_path_complete"] = False
    summary = summarize_daily_path_cells(
        [complete, incomplete], job_id="eval-test-partial-windows"
    )
    assert summary["logics"][0]["candidate"] is False


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
