"""CF isolate fan-out daily_path driver (not a period-net pass)."""
from __future__ import annotations

from research.cf_daily_path_job import (
    CF_EVENT_DAILY_PATH_IDS,
    FANOUT_VERSION,
    run_cf_daily_path_fanout,
)
from research.cf_mass_eval_job import CF_BAR_NATIVE_LOGIC_IDS, panels_cache_id


def test_fanout_aggregates_cells_and_does_not_promote() -> None:
    def fake_post(*, url: str, body: bytes, headers: dict) -> dict:
        assert url.endswith("/v1/daily-path")
        import json

        spec = json.loads(body.decode("utf-8"))
        lid = spec["logics"][0]["logic_id"]
        pid = spec["periods"][0]["period_id"]
        return {
            "ok": True,
            "cells": [
                {
                    "logic_id": lid,
                    "window": pid,
                    "window_id": pid,
                    "daily_path_DD": -0.02,
                    "total_ret_net": 0.01,
                    "dd_duration": 3,
                    "recovered": True,
                    "recovery_days": 2,
                    "n_days": 40,
                    "daily_path_complete": True,
                    "survived": False,
                    "go": False,
                }
            ],
        }

    ids = list(CF_BAR_NATIVE_LOGIC_IDS)[:3]
    pack = run_cf_daily_path_fanout(
        job_id="test-fanout-dp",
        logic_ids=ids,
        skip_stage=True,
        mode="synthetic",
        http_post=fake_post,
        max_workers=3,
        periods=[{"period_id": "y2015_full", "period_start": "2015-01-05", "period_end": "2015-03-01"}],
    )
    assert pack["version"] == FANOUT_VERSION
    assert pack["parallel_model"] == "cf_isolate_fanout_one_logic"
    assert pack["n_logics"] == 3
    assert pack["n_cells"] == 3
    assert pack["n_daily_path_complete"] == 3
    assert pack["go"] is False
    assert pack["promote_as_main"] is False
    assert pack["longest_isolate_sec"] is not None
    assert pack["fanout_sec"] is not None
    assert pack["mass_research"] == "NO-GO"


def test_fanout_path_broken_cells_are_not_complete() -> None:
    def fake_post(*, url: str, body: bytes, headers: dict) -> dict:
        import json

        spec = json.loads(body.decode("utf-8"))
        lid = spec["logics"][0]["logic_id"]
        pid = spec["periods"][0]["period_id"]
        return {
            "ok": True,
            "cells": [
                {
                    "logic_id": lid,
                    "window_id": pid,
                    "daily_path_complete": True,
                    "eval_path": "cs_generic",
                    "path_fallback": "path_broken",
                    "daily_path_DD": -0.02,
                    "total_ret_net": 0.01,
                    "n_days": 40,
                    "survived": False,
                    "go": False,
                }
            ],
        }

    pack = run_cf_daily_path_fanout(
        job_id="test-fanout-broken",
        logic_ids=["unwired_overlay"],
        skip_stage=True,
        mode="synthetic",
        http_post=fake_post,
        max_workers=1,
        periods=[
            {
                "period_id": "y2015_full",
                "period_start": "2015-01-05",
                "period_end": "2015-03-01",
            }
        ],
    )
    assert pack["n_cells"] == 1
    assert pack["n_daily_path_complete"] == 0
    assert pack["n_logic_ok"] == 0
    assert pack["go"] is False


def test_daily_path_spec_keeps_unique_event() -> None:
    from research.cf_mass_eval_job import build_cf_mass_eval_job_spec

    spec = build_cf_mass_eval_job_spec(
        job_id="eval-test-dp-keep-unique",
        logic_ids=["event_skip_monday", "nky_vol_abs_level"],
        mode="synthetic",
        drop_unique_unsupported=False,
    )
    lids = [str(L.get("logic_id")) for L in spec["logics"]]
    assert "event_skip_monday" in lids
    assert "nky_vol_abs_level" in lids
    assert spec.get("dropped_unique_unsupported") in (None, [], ())


def test_eval_universe_is_not_fifteen() -> None:
    from research.cf_mass_eval_job import DEFAULT_MAX_CODES
    from research.eval_universe import (
        EVAL_UNIVERSE_POOL,
        UNIVERSE_MIN_FINS_EQAR,
        UNIVERSE_MIN_FINS_TA,
        UNIVERSE_SELECT_RULE,
    )

    assert DEFAULT_MAX_CODES > 80
    assert len(EVAL_UNIVERSE_POOL) >= DEFAULT_MAX_CODES
    assert UNIVERSE_SELECT_RULE == "adv_desc_skip_missing_bars_and_fins"
    assert UNIVERSE_MIN_FINS_TA == 1
    assert UNIVERSE_MIN_FINS_EQAR == 1


def test_eval_tracks_are_two_and_not_head_n() -> None:
    from research.eval_tracks import (
        EVAL_TRACK_LIQ_LARGE,
        EVAL_TRACK_MID_N,
        EVAL_TRACKS,
        eval_track,
        infer_eval_track,
    )

    assert set(EVAL_TRACKS) == {EVAL_TRACK_MID_N, EVAL_TRACK_LIQ_LARGE}
    mid = eval_track(EVAL_TRACK_MID_N)
    large = eval_track(EVAL_TRACK_LIQ_LARGE)
    assert mid["max_codes"] == 80
    assert large["max_codes"] == 100
    assert mid["universe_select"] == "adv_desc_skip_missing_bars_and_fins"
    assert large["universe_select"] == "adv_desc_skip_missing_bars_and_fins"
    assert mid["head_n_forbidden"] is True
    assert large["head_n_forbidden"] is True
    assert mid["not_a_pass"] is True
    assert large["go"] is False
    assert infer_eval_track(max_codes=80) == EVAL_TRACK_MID_N
    assert infer_eval_track(max_codes=100) == EVAL_TRACK_LIQ_LARGE
    from research.eval_tracks import NEXT_RESEARCH_QUEUE

    assert len(NEXT_RESEARCH_QUEUE) >= 5
    assert all(q.get("not_a_pass") is True for q in NEXT_RESEARCH_QUEUE)
    assert all(q.get("go") is not True for q in NEXT_RESEARCH_QUEUE)


def test_rank_eval_codes_is_not_head_n_and_skips_missing() -> None:
    from research.eval_universe import rank_eval_codes

    scored = [
        {"code": "AAAAA", "adv": 10.0, "n_bars": 50, "n_ta": 1, "n_eqar": 1},
        {"code": "BBBBB", "adv": 100.0, "n_bars": 50, "n_ta": 1, "n_eqar": 1},
        {"code": "CCCCC", "adv": 90.0, "n_bars": 10, "n_ta": 1, "n_eqar": 1},
        {"code": "DDDDD", "adv": 80.0, "n_bars": 50, "n_ta": 0, "n_eqar": 1},
        {"code": "EEEEE", "adv": 70.0, "n_bars": 50, "n_ta": 1, "n_eqar": 0},
        {"code": "FFFFF", "adv": 60.0, "n_bars": 50, "n_ta": 1, "n_eqar": 1},
    ]
    ranked = rank_eval_codes(scored, max_codes=10)
    assert ranked[0] == "BBBBB"
    assert ranked != [row["code"] for row in scored][: len(ranked)]
    assert "CCCCC" not in ranked
    assert "DDDDD" not in ranked
    assert "EEEEE" not in ranked
    assert "AAAAA" in ranked


def test_empty_pool_does_not_fall_back_to_head_n() -> None:
    from research.eval_universe import EVAL_UNIVERSE_POOL, select_eval_universe

    out = select_eval_universe(max_codes=10, pool=())
    assert out == []
    assert out != list(EVAL_UNIVERSE_POOL)[:10]


def test_bar_native_count_meets_thirty() -> None:
    assert len(CF_BAR_NATIVE_LOGIC_IDS) >= 30


def test_event_daily_path_ids_cover_filters_and_sides() -> None:
    from research.unique_logic.constants import (
        ADAPTIVE_LOGIC_IDS,
        EVENT_FILTER_LOGIC_IDS,
        EVENT_LOGIC_IDS,
        EVENT_SIDES_LOGIC_IDS,
    )

    assert "event_funding_stress_skip" in CF_EVENT_DAILY_PATH_IDS
    assert "afterclose_only_event_hold" in CF_EVENT_DAILY_PATH_IDS
    assert "event_funding_easy_short" in CF_EVENT_DAILY_PATH_IDS
    assert "event_margin_crowding_skip" in CF_EVENT_DAILY_PATH_IDS
    assert set(EVENT_LOGIC_IDS) <= set(CF_EVENT_DAILY_PATH_IDS)
    assert set(EVENT_FILTER_LOGIC_IDS) <= set(CF_EVENT_DAILY_PATH_IDS)
    assert set(EVENT_SIDES_LOGIC_IDS) <= set(CF_EVENT_DAILY_PATH_IDS)
    assert set(ADAPTIVE_LOGIC_IDS) <= set(CF_EVENT_DAILY_PATH_IDS)
    assert len(CF_EVENT_DAILY_PATH_IDS) >= 13
    from research.unique_logic.constants import (
        CF_EVENT_FIDELITY,
        CF_NEW_THESIS_IDS,
    )

    assert "aligned" in CF_EVENT_FIDELITY["surprise"]
    assert "intended_lite_windows" in CF_EVENT_FIDELITY
    assert len(CF_NEW_THESIS_IDS) >= 116


def test_cf_daily_path_job_does_not_import_factory() -> None:
    import ast
    from pathlib import Path

    import research.eval_universe as eu

    research_dir = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "product"
        / "research"
    )
    # AST import walk only — comments are not imports.
    banned_both = ("mass_strategy_factory", "class_hyp_eval")
    files: dict[str, tuple[str, ...]] = {
        "cf_daily_path_job.py": banned_both,
        "cf_mass_eval_job.py": banned_both,
        "cf_mass_eval_stage.py": banned_both,
        "bar_native_specs.py": banned_both,
        "eval_universe.py": banned_both,
        "eval_loaders.py": banned_both,
        "unique_logic/event_combos.py": banned_both,
        "eval_windows.py": banned_both,
        "offline/bar_eval.py": banned_both,
    }
    for name, banned in files.items():
        path = research_dir / name
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for token in banned:
                        assert token not in alias.name, name
            elif isinstance(node, ast.ImportFrom) and node.module:
                for token in banned:
                    assert token not in node.module, name
                    assert node.module != f"research.{token}", name
    assert not hasattr(eu, "DEFAULT_EVAL_CODES")


def test_panels_cache_id_stable() -> None:
    a = panels_cache_id(
        [{"period_id": "y2015_full"}, {"period_id": "y2017_q4"}],
        max_codes=12,
        max_days=80,
    )
    b = panels_cache_id(
        [{"period_id": "y2015_full"}, {"period_id": "y2017_q4"}],
        max_codes=12,
        max_days=80,
    )
    assert a == b
    assert len(a) == 16
