"""Eval registry contract — recording SoT is R2/D1, not wave markdown."""
from __future__ import annotations

from tests.research_eval_util import (
    _eval_cell,
)
from research.eval_registry import (
    EVAL_REGISTRY_VERSION,
    EvalJobManifest,
    dumps_manifest,
    manifest_from_window_rows,
    r2_manifest_key,
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
