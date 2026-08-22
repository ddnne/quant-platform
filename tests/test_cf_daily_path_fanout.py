"""CF isolate fan-out daily_path driver (not a period-net pass)."""
from __future__ import annotations

from research.cf_daily_path_job import (
    CF_EVENT_DAILY_PATH_IDS,
    FANOUT_VERSION,
    run_both_track_sleeve_fanout,
    run_cf_daily_path_fanout,
    sleeve_durability_logic_ids,
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
    assert pack["not_a_pass"] is True
    assert pack["promote_as_main"] is False
    assert pack["longest_isolate_sec"] is not None
    assert pack["fanout_sec"] is not None


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
    from research.eval_tracks import NEXT_RESEARCH_QUEUE

    assert len(NEXT_RESEARCH_QUEUE) >= 5
    assert all(q.get("not_a_pass") is True for q in NEXT_RESEARCH_QUEUE)
    assert all(q.get("go") is not True for q in NEXT_RESEARCH_QUEUE)
    qids = [q["id"] for q in NEXT_RESEARCH_QUEUE]
    q0 = NEXT_RESEARCH_QUEUE[0]
    assert q0["id"] == "cf_propose_llm_not_stub"
    assert "Workers AI" in q0["why"]
    assert "no auto-inject" in q0["why"]
    assert "both_track_sleeve_durability" in qids
    assert "propose_clone_retry" in qids
    assert "llm_title_gate_polarity" in qids
    both = next(q for q in NEXT_RESEARCH_QUEUE if q["id"] == "both_track_sleeve_durability")
    assert both["tracks"] == BOTH_EVAL_TRACK_IDS
    assert both["entry"] == "research.cf_daily_path_job.run_both_track_sleeve_fanout"
    assert both["not_a_pass"] is True
    assert both["go"] is False
    assert "recorded" in both["why"]
    assert "eval-cf-dp-both-sleeves-20260822c" in both["why"]
    assert "thesis_counts_only_with_worker_body" in qids
    assert "no_go_until_both_tracks" in qids
    assert "unique22_leftover_lids" in qids
    assert "month_start_leftover_hold" in qids


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

    research_dir = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "product"
        / "research"
    )
    # AST import walk only — comments are not imports.
    banned_factory = ("mass_strategy_factory", "class_hyp_eval")
    # CF path must not import offline bar_eval (or family modules).
    banned_cf = banned_factory + ("bar_eval",)
    files: dict[str, tuple[str, ...]] = {
        "cf_daily_path_job.py": banned_cf,
        "cf_mass_eval_job.py": banned_cf,
        "cf_mass_eval_stage.py": banned_cf,
        "cf_mass_eval_run.py": banned_cf,
        "cf_mass_eval_thicken.py": banned_cf,
        "cf_propose_thesis.py": banned_cf + ("factory",),
        "bar_native_specs.py": banned_cf,
        "eval_universe.py": banned_cf,
        "unique_logic/event_combos.py": banned_cf,
        "eval_windows.py": banned_cf,
    }
    for path in sorted(research_dir.glob("eval_loaders*.py")):
        files[str(path.relative_to(research_dir))] = banned_cf
    for path in sorted((research_dir / "offline").glob("bar_eval*.py")):
        files[str(path.relative_to(research_dir))] = banned_factory
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


def _fake_select_not_head_n(*, max_codes: int, **kwargs):
    from research.eval_universe import EVAL_UNIVERSE_POOL

    n = int(max_codes)
    codes = [f"Z{i:04d}" for i in range(n)]
    assert codes != list(EVAL_UNIVERSE_POOL)[:n]
    return codes


def test_both_track_sleeve_fanout_default_is_off_network(monkeypatch) -> None:
    from research import cf_daily_path_job as mod
    from research.eval_tracks import (
        EVAL_TRACK_LIQ_LARGE,
        EVAL_TRACK_MID_N,
        EVAL_TRACKS,
    )
    from research.eval_universe import EVAL_UNIVERSE_POOL

    seen_max: list[int] = []

    def fake_select(*, max_codes: int, **kwargs):
        seen_max.append(int(max_codes))
        return _fake_select_not_head_n(max_codes=max_codes)

    def boom(*_a, **_k):
        raise AssertionError("live CF must not be called on dry_run default")

    monkeypatch.setattr(mod, "invoke_cf_daily_path", boom)
    monkeypatch.setattr(mod, "run_cf_daily_path_fanout", boom)

    pack = run_both_track_sleeve_fanout(
        job_id="test-both-sleeve-offnet",
        select_universe=fake_select,
    )
    assert pack["dry_run"] is True
    assert pack["skipped_live_cf"] is True
    assert pack["go"] is False
    assert pack["not_a_pass"] is True
    assert pack["promote_as_main"] is False
    assert pack["head_n_forbidden"] is True
    assert pack["sleeve_majority_is_not_a_pass"] is True
    assert pack["logic_ids"] == sleeve_durability_logic_ids()
    assert "event_eqar_high_liq_high" in pack["logic_ids"]
    assert "cs_margin_up_chase" in pack["logic_ids"]
    assert "event_cheap_pb_liq_high" in pack["logic_ids"]
    assert "event_eqar_rising_afterclose" in pack["logic_ids"]
    tracks = {t["eval_track"]: t for t in pack["tracks"]}
    assert set(tracks) == {EVAL_TRACK_MID_N, EVAL_TRACK_LIQ_LARGE}
    assert tracks[EVAL_TRACK_MID_N]["max_codes"] == EVAL_TRACKS[EVAL_TRACK_MID_N]["max_codes"]
    assert tracks[EVAL_TRACK_LIQ_LARGE]["max_codes"] == EVAL_TRACKS[EVAL_TRACK_LIQ_LARGE]["max_codes"]
    assert seen_max == [
        int(EVAL_TRACKS[EVAL_TRACK_MID_N]["max_codes"]),
        int(EVAL_TRACKS[EVAL_TRACK_LIQ_LARGE]["max_codes"]),
    ]
    assert tracks[EVAL_TRACK_MID_N]["selected_codes"] != list(EVAL_UNIVERSE_POOL)[:80]
    assert tracks[EVAL_TRACK_LIQ_LARGE]["selected_codes"] != list(EVAL_UNIVERSE_POOL)[:100]
    assert tracks[EVAL_TRACK_MID_N]["universe_select"] == "adv_desc_skip_missing_bars_and_fins"
    assert pack["compare"]["not_a_pass"] is True
    assert pack["compare"]["go"] is False
    assert pack["compare"]["liq_print_is_not_stable"] is True
    assert pack.get("r2_keys") is None  # dry_run does not write R2


def test_both_track_sleeve_fanout_records_via_daily_path() -> None:
    from research.eval_tracks import EVAL_TRACK_LIQ_LARGE, EVAL_TRACK_MID_N, EVAL_TRACKS

    posts: list[tuple[str, int, str]] = []

    def fake_post(*, url: str, body: bytes, headers: dict) -> dict:
        import json

        spec = json.loads(body.decode("utf-8"))
        lid = spec["logics"][0]["logic_id"]
        pid = spec["periods"][0]["period_id"]
        posts.append((url, int(spec["max_codes"]), lid))
        return {
            "ok": True,
            "cells": [
                {
                    "logic_id": lid,
                    "window_id": pid,
                    "daily_path_DD": -0.02,
                    "total_ret_net": 0.01,
                    "n_days": 40,
                    "daily_path_complete": True,
                    "survived": False,
                    "go": False,
                }
            ],
        }

    pack = run_both_track_sleeve_fanout(
        job_id="test-both-sleeve-record",
        dry_run=True,
        logic_ids=["event_eqar_high_pead", "cs_margin_up_chase"],
        select_universe=_fake_select_not_head_n,
        http_post=fake_post,
        skip_stage=True,
        mode="synthetic",
        max_workers=2,
        periods=[
            {
                "period_id": "y2015_full",
                "period_start": "2015-01-05",
                "period_end": "2015-03-01",
            }
        ],
    )
    assert pack["go"] is False
    assert pack["not_a_pass"] is True
    assert pack["skipped_live_cf"] is True
    assert pack["n_tracks"] == 2
    tracks = {t["eval_track"]: t for t in pack["tracks"]}
    assert tracks[EVAL_TRACK_MID_N]["max_codes"] == EVAL_TRACKS[EVAL_TRACK_MID_N]["max_codes"]
    assert tracks[EVAL_TRACK_LIQ_LARGE]["max_codes"] == EVAL_TRACKS[EVAL_TRACK_LIQ_LARGE]["max_codes"]
    assert tracks[EVAL_TRACK_MID_N]["n_cells"] == 2
    assert tracks[EVAL_TRACK_LIQ_LARGE]["n_cells"] == 2
    assert "n_logic_ok" in tracks[EVAL_TRACK_MID_N]
    assert "n_logic_ok" in tracks[EVAL_TRACK_LIQ_LARGE]
    assert all(url.endswith("/v1/daily-path") for url, _n, _lid in posts)
    max_codes = {n for _url, n, _lid in posts}
    assert max_codes == {
        int(EVAL_TRACKS[EVAL_TRACK_MID_N]["max_codes"]),
        int(EVAL_TRACKS[EVAL_TRACK_LIQ_LARGE]["max_codes"]),
    }
    assert pack["compare"]["go"] is False
    assert pack["compare"]["not_a_pass"] is True


def test_both_track_sleeve_fanout_uses_select_eval_universe() -> None:
    import ast
    from pathlib import Path

    research_dir = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "product"
        / "research"
    )
    src = (research_dir / "cf_daily_path_job.py").read_text(encoding="utf-8")
    mass_src = (research_dir / "cf_mass_eval_job.py").read_text(encoding="utf-8")
    assert "select_eval_universe" in src
    assert "select_eval_universe" in mass_src
    assert "selected[: int(max_codes)]" not in src
    assert "selected[: int(max_codes)]" not in mass_src
    assert "run_both_track_sleeve_fanout" in src
    tree = ast.parse(src)
    names = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    ]
    assert "run_both_track_sleeve_fanout" in names
