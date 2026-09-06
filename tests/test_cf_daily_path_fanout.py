"""CF isolate fan-out daily_path driver (not a period-net pass)."""
from __future__ import annotations

import pytest

from research.cf_daily_path_job import (
    CF_EVENT_DAILY_PATH_IDS,
    run_both_track_sleeve_fanout,
    run_cf_daily_path_fanout,
    sleeve_durability_logic_ids,
)
from research.cf_mass_eval_job import CF_BAR_NATIVE_LOGIC_IDS, panels_cache_id


@pytest.fixture(autouse=True)
def _allow_mass_screen_capability(monkeypatch) -> None:
    monkeypatch.setattr(
        "research.cf_mass_eval_job.require_capability",
        lambda name, caps=None: {
            "capability": name,
            "allowed": True,
            "reasons": [],
            "go": False,
            "not_a_pass": True,
        },
    )


def test_mass_fanout_fails_before_network_or_local_staging(tmp_path) -> None:
    from research.mass_disabled import MassResearchDisabledError

    staging_dir = tmp_path / "mass-stage"

    def unexpected_post(**_kwargs):
        raise AssertionError("disabled Mass fanout must not issue HTTP")

    with pytest.raises(MassResearchDisabledError, match="Mass research remains"):
        run_cf_daily_path_fanout(
            job_id="test-disabled-fanout",
            logic_ids=["nky_vol_abs_level"],
            mode="synthetic",
            staging_dir=staging_dir,
            http_post=unexpected_post,
        )
    assert not staging_dir.exists()


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



def test_bar_native_ids_are_not_unique_leftover() -> None:
    from research.unique_logic.worker_bodies import unique_leftover_logic_ids

    assert CF_BAR_NATIVE_LOGIC_IDS
    assert set(CF_BAR_NATIVE_LOGIC_IDS).isdisjoint(unique_leftover_logic_ids())


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
    from research.unique_logic.constants import (
        CF_EVENT_FIDELITY,
        CF_NEW_THESIS_IDS,
    )

    assert "aligned" in CF_EVENT_FIDELITY["surprise"]
    assert "intended_lite_windows" in CF_EVENT_FIDELITY
    assert set(CF_NEW_THESIS_IDS)




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
    from research.unique_logic.constants import ALWAYS_ON_PARK_IDS, NEAR_EMPTY_PARK_IDS

    assert NEAR_EMPTY_PARK_IDS.isdisjoint(pack["logic_ids"])
    assert ALWAYS_ON_PARK_IDS.isdisjoint(pack["logic_ids"])
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


def test_mass_eval_spec_drops_unique_but_keeps_bar_native() -> None:
    from research.cf_mass_eval_job import build_cf_mass_eval_job_spec

    spec = build_cf_mass_eval_job_spec(
        job_id="eval-test-drop-unique",
        logic_ids=["event_skip_monday", "nky_vol_abs_level"],
        mode="synthetic",
    )
    lids = [str(L.get("logic_id")) for L in spec["logics"]]
    assert "event_skip_monday" not in lids
    assert "nky_vol_abs_level" in lids
    assert "event_skip_monday" in spec["dropped_unique_unsupported"]
    assert spec["candidate_eval_sot"] == "daily_path_mtm_after_cost/v1"


def test_mass_eval_screen_is_not_candidate_grade() -> None:
    from research.cf_mass_eval_job import try_cf_mass_eval_status

    st = try_cf_mass_eval_status()
    assert st["status"] == "implemented"
    assert st["default_mode"] == "r2_panels"
    assert st["screen_kind"] == "period_net"
    assert st["candidate_grade"] is False
    assert st["n_survivors_are_not_a_pass"] is True
    assert st["daily_path_complete"] is False
    assert st["candidate_grade"] is False
    assert st.get("unique_unsupported_on_period_net") is True
    assert st.get("candidate_eval_sot") == "daily_path_mtm_after_cost/v1"


def test_unique_mdh_collapse_is_not_candidate_complete() -> None:
    from research.cf_mass_eval_job import is_unique_period_net_unsupported
    from research.eval_registry import (
        is_daily_path_complete_cell,
        is_path_collapsed_cell,
    )

    assert is_unique_period_net_unsupported("event_skip_monday") is True
    assert is_unique_period_net_unsupported("nky_vol_abs_level") is False
    collapsed = {
        "logic_id": "event_skip_monday",
        "window": "y2015_full",
        "daily_path_complete": True,
        "signal_id": "c21_lite_fallback_mdh:event_calendar_gate",
        "skip_reason": "unique_unsupported_on_period_net",
    }
    assert is_path_collapsed_cell(collapsed) is True
    assert is_daily_path_complete_cell(collapsed) is False
