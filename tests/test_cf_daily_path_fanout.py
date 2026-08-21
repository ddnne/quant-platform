"""CF isolate fan-out daily_path driver (not a period-net pass)."""
from __future__ import annotations

from research.cf_daily_path_job import FANOUT_VERSION, run_cf_daily_path_fanout
from research.cf_mass_eval_job import CF_BAR_NATIVE_LOGIC_IDS


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


def test_bar_native_count_meets_thirty() -> None:
    assert len(CF_BAR_NATIVE_LOGIC_IDS) >= 30
