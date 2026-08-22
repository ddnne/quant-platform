"""Eval registry contract — recording SoT is R2/D1, not wave markdown."""
from __future__ import annotations

from research.eval_registry import (
    EVAL_REGISTRY_VERSION,
    EvalJobManifest,
    dumps_manifest,
    manifest_from_window_rows,
    r2_manifest_key,
)
from research.eval_windows import FROZEN_PIN_SNAPSHOT, HONEST_3Y_WINDOWS
from research.daily_path_eval import stitch_net, summarize_path


def test_honest_windows_are_the_shared_catalog() -> None:
    ids = [w["window_id"] for w in HONEST_3Y_WINDOWS]
    assert ids == ["w2017_2019", "w2020_2022", "w2023_2025"]
    assert len(FROZEN_PIN_SNAPSHOT) == 3


def test_manifest_from_rows_is_queryable_shape() -> None:
    rows = [
        {
            "logic_id": "overnight_level_cs_tilt",
            "window": "w2020_2022",
            "daily_path_DD": -0.211,
            "total_ret_net": -0.198,
            "occupancy_frac": 0.715,
            "dd_duration": 165,
            "recovered": False,
            "n_days": 193,
            "daily_path_complete": True,
        }
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
    from research.eval_registry import summarize_daily_path_cells

    cells = [
        {
            "logic_id": "unwired_overlay",
            "window_id": "y2015_full",
            "occupancy": 0.87,
            "total_ret_net": 0.04,
            "eval_path": "cs_generic",
            "path_fallback": "path_broken",
            "t_stat": 1.2,
            "sharpe_daily": 0.3,
            "daily_path_DD": -0.1,
        }
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

    broken = {
        "logic_id": "unwired_overlay",
        "window": "y2015_full",
        "daily_path_complete": True,
        "eval_path": "cs_generic",
        "path_fallback": "path_broken",
        "daily_path_DD": -0.1,
        "total_ret_net": 0.04,
        "occupancy_frac": 0.87,
        "n_days": 40,
        "recovered": False,
    }
    assert is_path_broken_cell(broken) is True
    assert is_daily_path_complete_cell(broken) is False
    mdh = {**broken, "eval_path": "mdh_generic", "path_fallback": "mdh_empty_sidecar"}
    assert is_daily_path_complete_cell(mdh) is False
    ok = {
        "logic_id": "nky_vol_abs_level",
        "window": "y2015_full",
        "daily_path_complete": True,
        "eval_path": "nky_vol:nky_vol_abs_level",
        "daily_path_DD": -0.1,
        "total_ret_net": 0.01,
        "occupancy_frac": 0.5,
        "n_days": 40,
        "recovered": True,
    }
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
    from research.eval_registry import summarize_daily_path_cells

    cells = [
        {
            "logic_id": "xs_rank_ls_sticky",
            "window_id": f"y{y}",
            "occupancy": 0.90,
            "total_ret_net": 0.04,
            "eval_path": "xs_rank_sticky",
            "daily_path_complete": True,
        }
        for y in (2015, 2017, 2019, 2021, 2023, 2025)
    ]
    summary = summarize_daily_path_cells(cells, job_id="eval-test-always")
    row = summary["logics"][0]
    assert "always_on" in row["flags"]
    assert row["tag"] != "strong"
    assert summary["n_candidate_logics"] == 0
    assert summary["always_on_excluded_from_main"] is True


def test_always_on_gate_is_never_candidate() -> None:
    from research.eval_registry import summarize_daily_path_cells

    cells = [
        {
            "logic_id": "surprise_xs_afterclose",
            "window_id": f"y{y}",
            "occupancy": 1.0,
            "total_ret_net": 0.01,
            "eval_path": "eventHeld",
            "daily_path_complete": True,
        }
        for y in (2015, 2017, 2019)
    ]
    summary = summarize_daily_path_cells(cells, job_id="eval-test-ao-gate")
    row = summary["logics"][0]
    assert "always_on" in row["flags"]
    assert row["candidate"] is False
    assert row["main_pool"] is False


def test_combo_basket_blend_is_equal_weight() -> None:
    from research.combo_basket import (
        DEFAULT_CANDIDATE_BASKET,
        blend_net_daily,
        blend_window_cells,
        occupancy_in_candidate_band,
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
        {
            "logic_id": "a",
            "window_id": "y2015_full",
            "dates": ["d0", "d1", "d2"],
            "net_daily": [0.0, 0.02, 0.0],
            "occupancy": 0.2,
            "daily_path_complete": True,
        },
        {
            "logic_id": "b",
            "window_id": "y2015_full",
            "dates": ["d0", "d1", "d2"],
            "net_daily": [0.0, 0.0, 0.02],
            "occupancy": 0.3,
            "daily_path_complete": True,
        },
    ]
    rows = blend_window_cells(cells, basket_id="basket_a_b", logic_ids=["a", "b"])
    assert len(rows) == 1
    assert rows[0]["go"] is False
    assert rows[0]["eval_path"] == "equal_weight_basket"
    assert rows[0]["daily_path_complete"] is True


def test_near_empty_and_term_ratio_are_not_candidates() -> None:
    from research.eval_registry import summarize_daily_path_cells

    cells = [
        {
            "logic_id": "opt225_atm_iv_term_ratio",
            "window_id": f"y{y}",
            "occupancy": 0.0,
            "total_ret_net": 0.0,
            "eval_path": "opt225:term_ratio",
            "daily_path_complete": True,
        }
        for y in (2015, 2017, 2019, 2021, 2023, 2025)
    ]
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
    from research.eval_registry import summarize_daily_path_cells

    cells = [
        {
            "logic_id": "event_skip_monday",
            "window_id": f"y{y}",
            "occupancy": 0.18,
            "total_ret_net": 0.01,
            "t_stat": 0.4,
            "sharpe_daily": 0.05,
            "eval_path": "eventHeld",
            "daily_path_complete": True,
        }
        for y in (2015, 2017, 2019, 2021, 2023, 2025)
    ]
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


def test_path_broken_is_not_candidate() -> None:
    from research.eval_registry import summarize_daily_path_cells

    cells = [
        {
            "logic_id": "unwired_overlay",
            "window_id": "y2015_full",
            "occupancy": 0.40,
            "total_ret_net": 0.02,
            "eval_path": "cs_generic",
            "path_fallback": "path_broken",
            "t_stat": 2.0,
            "daily_path_complete": True,
        }
    ]
    summary = summarize_daily_path_cells(cells, job_id="eval-test-broken-cand")
    row = summary["logics"][0]
    assert row["candidate"] is False
    assert row["tag"] == "path_broken"


def test_proposal_schema_reads_summary_weakness_flags() -> None:
    from research.unique_logic.proposal_schema import (
        proposal_blocked_by_summary,
        weakness_flags_from_summary,
    )

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
    from research.unique_logic.proposal_schema import CANDIDATE_KEEP_SIMPLE

    assert "path_broken" in CANDIDATE_KEEP_SIMPLE
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
