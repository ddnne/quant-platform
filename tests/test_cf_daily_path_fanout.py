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
    assert len(CF_NEW_THESIS_IDS) >= 80


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
