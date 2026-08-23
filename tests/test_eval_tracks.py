"""Eval tracks / universe. ADV-ranked, never head-N. Not GO."""
from __future__ import annotations


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
        BOTH_EVAL_TRACK_IDS,
        EVAL_TRACK_LIQ_LARGE,
        EVAL_TRACK_MID_N,
        EVAL_TRACKS,
        eval_track,
        infer_eval_track,
    )

    assert set(EVAL_TRACKS) == {EVAL_TRACK_MID_N, EVAL_TRACK_LIQ_LARGE}
    assert BOTH_EVAL_TRACK_IDS == (EVAL_TRACK_MID_N, EVAL_TRACK_LIQ_LARGE)
    mid = eval_track(EVAL_TRACK_MID_N)
    large = eval_track(EVAL_TRACK_LIQ_LARGE)
    assert mid["max_codes"] == 80
    assert large["max_codes"] == 100
    assert mid["universe_select"] == "adv_desc_skip_missing_bars_and_fins"
    assert large["universe_select"] == "adv_desc_skip_missing_bars_and_fins"
    assert mid["head_n_forbidden"] is True
    assert large["head_n_forbidden"] is True
    assert mid["go"] is False
    assert large["go"] is False
    assert mid["not_a_pass"] is True
    assert large["not_a_pass"] is True
    assert infer_eval_track(max_codes=80) == EVAL_TRACK_MID_N
    assert infer_eval_track(max_codes=100) == EVAL_TRACK_LIQ_LARGE
    from research.eval_tracks import (
        CURRENT_EVAL_WAVE,
        CATALOG_AND_PLUS_N_STOPPED,
        EVENT_THREE_AND_PLUS_N_STOPPED,
        NEXT_RESEARCH_QUEUE,
        RECONSTITUTION_APPLY,
    )
    from research.combo_basket_catalog import (
        RECONSTITUTION_APPLY as BASKET_RECONSTITUTION_APPLY,
    )

    assert EVENT_THREE_AND_PLUS_N_STOPPED is True
    assert CATALOG_AND_PLUS_N_STOPPED is True
    assert RECONSTITUTION_APPLY is False
    assert BASKET_RECONSTITUTION_APPLY is False
    assert CURRENT_EVAL_WAVE
    assert "go" not in CURRENT_EVAL_WAVE.lower()
    assert len(NEXT_RESEARCH_QUEUE) >= 5
    assert all(q.get("not_a_pass") is True for q in NEXT_RESEARCH_QUEUE)
    assert all(q.get("go") is not True for q in NEXT_RESEARCH_QUEUE)
    qids = [q["id"] for q in NEXT_RESEARCH_QUEUE]
    q0 = NEXT_RESEARCH_QUEUE[0]
    assert q0["id"] == "cf_propose_llm_not_stub"
    assert "Workers AI" in q0["why"]
    assert "no auto-inject" in q0["why"]
    assert "both_track_sleeve_durability" in qids
    assert "reconstitution_human_pending" in qids
    assert "propose_clone_retry" in qids
    assert "llm_title_gate_polarity" in qids
    both = next(q for q in NEXT_RESEARCH_QUEUE if q["id"] == "both_track_sleeve_durability")
    assert both["tracks"] == BOTH_EVAL_TRACK_IDS
    assert both["entry"] == "research.cf_daily_path_job.run_both_track_sleeve_fanout"
    assert both["not_a_pass"] is True
    assert both["go"] is False
    assert "recorded" in both["why"]
    assert "thesis_counts_only_with_worker_body" in qids
    assert "no_go_until_both_tracks" in qids
    assert "unique22_leftover_lids" in qids
    assert "month_start_leftover_hold" in qids
    assert "otc_parse_zero" in qids
    assert "cheap_pb_event_reuse" in qids
    assert "catalog_and_plus_n_stopped" in qids
    assert "known_thin_do_not_rewrite" in qids


def test_offline_default_periods_match_cf_mass() -> None:
    import research.eval_windows as ew
    from research.cf_mass_eval_job import DEFAULT_REAL_MULTIYEAR_PERIODS as cf_periods
    from research.offline import bar_eval as be

    assert ew.DEFAULT_PERIODS == cf_periods
    assert callable(be.evaluate_multi_day_hold_on_bars)
    doc = f"{be.__doc__ or ''}"
    assert "not CF SoT" in doc
    assert "no GO" in doc


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

def test_eval_flags_are_single_sot() -> None:
    import research.combo_basket_catalog as baskets
    import research.eval_flags as flags
    import research.eval_tracks as tracks

    assert flags.RECONSTITUTION_APPLY is False
    assert tracks.RECONSTITUTION_APPLY is flags.RECONSTITUTION_APPLY
    assert baskets.RECONSTITUTION_APPLY is flags.RECONSTITUTION_APPLY
    assert tracks.CATALOG_AND_PLUS_N_STOPPED is flags.CATALOG_AND_PLUS_N_STOPPED
    assert tracks.CURRENT_EVAL_WAVE == flags.CURRENT_EVAL_WAVE
    assert flags.CATALOG_YAML_COUNT_AT_STOP == 2254

def test_catalog_and_plus_n_stopped_and_known_thin() -> None:
    from research.eval_flags import (
        CATALOG_AND_PLUS_N_STOPPED,
        CATALOG_YAML_COUNT_AT_STOP,
        EVENT_THREE_AND_PLUS_N_STOPPED,
        RECONSTITUTION_APPLY,
    )
    from research.unique_logic.worker_bodies import (
        CatalogAndPlusNStoppedError,
        EventThreeAndBatchError,
        KnownThinRewriteError,
        assert_catalog_and_plus_n_stopped,
        assert_known_thin_unused_absent,
        assert_new_batch_not_event_three_and,
    )

    assert CATALOG_AND_PLUS_N_STOPPED is True
    assert EVENT_THREE_AND_PLUS_N_STOPPED is True
    assert RECONSTITUTION_APPLY is False
    freeze = assert_catalog_and_plus_n_stopped()
    assert freeze["ok"] is True
    assert freeze["n"] == CATALOG_YAML_COUNT_AT_STOP
    thin = assert_known_thin_unused_absent()
    assert thin["ok"] is True
    assert thin["hits"] == []
    ok3 = assert_new_batch_not_event_three_and(
        [{"logic_id": "a", "params": {"gates": ["margin_up", "liq_high"]}}]
    )
    assert ok3["ok"] is True
    try:
        assert_new_batch_not_event_three_and(
            [
                {
                    "logic_id": "bad3",
                    "params": {"gates": ["margin_up", "liq_high", "eps_up"]},
                }
            ]
        )
        raise AssertionError("3-AND batch must reject")
    except EventThreeAndBatchError:
        pass
    try:
        assert_known_thin_unused_absent(
            [
                {
                    "logic_id": "event_mdn_np",
                    "params": {"gates": ["margin_down", "np_negative"]},
                }
            ]
        )
        raise AssertionError("known-thin rewrite must reject")
    except KnownThinRewriteError:
        pass
    assert CatalogAndPlusNStoppedError is not EventThreeAndBatchError
